use std::cmp::Ordering;
use std::collections::HashSet;
use std::env;
use std::io::{self, Read};

const DEFAULT_DIMS: usize = 128;

fn normalize_text(input: &str) -> String {
    input
        .chars()
        .map(|c| match c {
            'Á' | 'À' | 'Â' | 'Ã' | 'Ä' | 'á' | 'à' | 'â' | 'ã' | 'ä' => 'a',
            'É' | 'È' | 'Ê' | 'Ë' | 'é' | 'è' | 'ê' | 'ë' => 'e',
            'Í' | 'Ì' | 'Î' | 'Ï' | 'í' | 'ì' | 'î' | 'ï' => 'i',
            'Ó' | 'Ò' | 'Ô' | 'Õ' | 'Ö' | 'ó' | 'ò' | 'ô' | 'õ' | 'ö' => 'o',
            'Ú' | 'Ù' | 'Û' | 'Ü' | 'ú' | 'ù' | 'û' | 'ü' => 'u',
            'Ç' | 'ç' => 'c',
            'Ñ' | 'ñ' => 'n',
            _ => c.to_ascii_lowercase(),
        })
        .collect::<String>()
}

fn tokens(text: &str) -> Vec<String> {
    let norm = normalize_text(text);
    let mut out = Vec::new();
    let mut cur = String::new();
    for ch in norm.chars() {
        if ch.is_ascii_alphanumeric() || ch == '_' {
            cur.push(ch);
        } else if !cur.is_empty() {
            out.push(cur.clone());
            cur.clear();
        }
    }
    if !cur.is_empty() {
        out.push(cur);
    }
    out
}

fn fnv1a64(input: &str) -> u64 {
    let mut hash: u64 = 0xcbf29ce484222325;
    for b in input.as_bytes() {
        hash ^= *b as u64;
        hash = hash.wrapping_mul(0x100000001b3);
    }
    hash
}

fn embed(text: &str, dims: usize) -> Vec<f32> {
    let dims = dims.max(8);
    let mut vec = vec![0.0_f32; dims];
    let toks = tokens(text);

    for tok in toks.iter() {
        let h = fnv1a64(tok);
        let idx = (h as usize) % dims;
        let sign = if (h >> 63) & 1 == 1 { -1.0 } else { 1.0 };
        vec[idx] += sign;

        if tok.len() >= 4 {
            for i in 0..=(tok.len().saturating_sub(3)) {
                let gram = &tok[i..i + 3];
                let gh = fnv1a64(gram);
                let gidx = (gh as usize) % dims;
                let gsign = if (gh >> 62) & 1 == 1 { -0.35 } else { 0.35 };
                vec[gidx] += gsign;
            }
        }
    }

    let norm = vec.iter().map(|v| v * v).sum::<f32>().sqrt();
    if norm > 0.0 {
        for v in vec.iter_mut() {
            *v /= norm;
        }
    }
    vec
}

fn cosine(a: &[f32], b: &[f32]) -> f32 {
    let n = a.len().min(b.len());
    if n == 0 {
        return 0.0;
    }
    let mut dot = 0.0_f32;
    let mut na = 0.0_f32;
    let mut nb = 0.0_f32;
    for i in 0..n {
        dot += a[i] * b[i];
        na += a[i] * a[i];
        nb += b[i] * b[i];
    }
    let denom = na.sqrt() * nb.sqrt();
    if denom == 0.0 { 0.0 } else { dot / denom }
}

fn json_escape(input: &str) -> String {
    let mut out = String::new();
    for ch in input.chars() {
        match ch {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if c.is_control() => out.push_str(&format!("\\u{:04x}", c as u32)),
            c => out.push(c),
        }
    }
    out
}

fn vector_json(vec: &[f32]) -> String {
    let body = vec
        .iter()
        .map(|v| format!("{:.6}", v))
        .collect::<Vec<_>>()
        .join(",");
    format!("[{}]", body)
}

fn has_any(toks: &[String], needles: &[&str]) -> Vec<String> {
    let mut hits = Vec::new();
    for tok in toks {
        for needle in needles {
            if tok == needle || tok.starts_with(needle) {
                hits.push((*needle).to_string());
            }
        }
    }
    hits.sort();
    hits.dedup();
    hits
}

fn classify_intent(text: &str) -> String {
    let toks = tokens(text);
    let set: HashSet<&str> = toks.iter().map(|s| s.as_str()).collect();
    let question = text.contains('?')
        || set.iter().any(|t| matches!(*t, "quem" | "qual" | "quais" | "quando" | "onde" | "como" | "who" | "what" | "when" | "where" | "how"));
    let self_hits = has_any(&toks, &["voce", "vc", "ultron", "ultronpro", "seu", "sua", "your", "you"]);
    let creation_hits = has_any(&toks, &["nasc", "criad", "criador", "creator", "orig", "desenvolv"]);
    let capability_hits = has_any(&toks, &["llm", "modelo", "model", "provider", "provedor", "capaz", "consegue"]);
    let action_hits = has_any(&toks, &["criar", "execut", "rode", "rodar", "analise", "corrij", "implementar", "faca"]);
    let current_hits = has_any(&toks, &["atual", "hoje", "agora", "latest", "current", "presidente", "ceo", "preco", "versao"]);
    let search_hits = has_any(&toks, &["busque", "pesquise", "procure", "web", "internet", "noticia", "lookup"]);

    let (label, category, confidence, method, signals) = if !self_hits.is_empty() && (!creation_hits.is_empty() || !capability_hits.is_empty() || question) {
        let category = if !creation_hits.is_empty() {
            "autobiographical_creation"
        } else if !capability_hits.is_empty() {
            "autobiographical_capability"
        } else {
            "autobiographical_identity"
        };
        ("autobiographical", category, 0.82_f32, "rust_symbolic_self", [self_hits, creation_hits, capability_hits].concat())
    } else if question && (!current_hits.is_empty() || !search_hits.is_empty()) {
        ("external_factual", "current_world_fact", 0.74_f32, "rust_symbolic_external", [current_hits, search_hits].concat())
    } else if !action_hits.is_empty() {
        ("action_request", "tool_or_code_action", 0.68_f32, "rust_symbolic_action", action_hits)
    } else {
        ("general", "none", 0.35_f32, "rust_symbolic_general", Vec::new())
    };

    let signals_json = signals
        .iter()
        .map(|s| format!("\"{}\"", json_escape(s)))
        .collect::<Vec<_>>()
        .join(",");
    format!(
        "{{\"ok\":true,\"label\":\"{}\",\"category\":\"{}\",\"confidence\":{:.3},\"method\":\"{}\",\"signals\":[{}]}}",
        label, category, confidence, method, signals_json
    )
}

fn parse_event(source: &str, text: &str) -> String {
    let toks = tokens(text);
    let severity = if has_any(&toks, &["panic", "critical", "fatal", "crash"]).len() > 0 {
        "critical"
    } else if has_any(&toks, &["error", "erro", "failed", "falha", "timeout", "exception"]).len() > 0 {
        "error"
    } else if has_any(&toks, &["warn", "warning", "alerta", "risk"]).len() > 0 {
        "warning"
    } else {
        "info"
    };
    let event_type = if toks.iter().any(|t| t.contains("audio") || t.contains("voice")) {
        "audio"
    } else if toks.iter().any(|t| t.contains("http") || t.contains("api")) {
        "network"
    } else if toks.iter().any(|t| t.contains("file") || t.contains("path") || t.contains("fs")) {
        "filesystem"
    } else {
        "system"
    };
    let summary = text.trim().chars().take(220).collect::<String>();
    format!(
        "{{\"ok\":true,\"source\":\"{}\",\"event_type\":\"{}\",\"severity\":\"{}\",\"summary\":\"{}\",\"token_count\":{}}}",
        json_escape(source),
        event_type,
        severity,
        json_escape(&summary),
        toks.len()
    )
}

fn score_rerank(query: &str, candidate: &str) -> f32 {
    let qtoks = tokens(query);
    let ctoks = tokens(candidate);
    let cset: HashSet<&str> = ctoks.iter().map(|s| s.as_str()).collect();
    let qset: HashSet<&str> = qtoks.iter().map(|s| s.as_str()).collect();
    let overlap = qset.iter().filter(|t| cset.contains(**t)).count() as f32;
    let union = qset.union(&cset).count().max(1) as f32;
    let lexical = overlap / union;

    let neg_markers = ["nao", "não", "sem", "evitar", "exceto", "without", "avoid", "except"];
    let mut hard_neg = 0.0_f32;
    for idx in 0..qtoks.len() {
        if neg_markers.contains(&qtoks[idx].as_str()) && idx + 1 < qtoks.len() && cset.contains(qtoks[idx + 1].as_str()) {
            hard_neg += 0.18;
        }
    }
    let semantic = cosine(&embed(query, DEFAULT_DIMS), &embed(candidate, DEFAULT_DIMS));
    (lexical * 0.55) + (semantic * 0.45) - hard_neg
}

fn read_stdin() -> String {
    let mut input = String::new();
    let _ = io::stdin().read_to_string(&mut input);
    input
}

fn rerank(query: &str, top_k: usize) -> String {
    let input = read_stdin();
    let mut scored = Vec::new();
    for (idx, line) in input.lines().enumerate() {
        let trimmed = line.trim();
        if trimmed.is_empty() {
            continue;
        }
        let mut parts = trimmed.splitn(2, '\t');
        let first = parts.next().unwrap_or("");
        let second = parts.next();
        let (id, text) = match second {
            Some(t) => (first.to_string(), t.to_string()),
            None => (idx.to_string(), first.to_string()),
        };
        scored.push((score_rerank(query, &text), id, text));
    }
    scored.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap_or(Ordering::Equal));
    let rows = scored
        .iter()
        .take(top_k.max(1))
        .map(|(score, id, text)| {
            format!(
                "{{\"id\":\"{}\",\"score\":{:.4},\"text\":\"{}\"}}",
                json_escape(id),
                score,
                json_escape(text)
            )
        })
        .collect::<Vec<_>>()
        .join(",");
    format!("{{\"ok\":true,\"results\":[{}]}}", rows)
}

fn arg_value(args: &[String], name: &str, default: &str) -> String {
    for i in 0..args.len() {
        if args[i] == name && i + 1 < args.len() {
            return args[i + 1].clone();
        }
    }
    default.to_string()
}

fn print_usage() {
    eprintln!("usage:");
    eprintln!("  ultron_local_infer embed --text TEXT [--dims 128]");
    eprintln!("  ultron_local_infer intent --text TEXT");
    eprintln!("  ultron_local_infer parse-event --source NAME --text TEXT");
    eprintln!("  ultron_local_infer rerank --query TEXT [--top-k 10] < candidates.tsv");
}

fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() < 2 {
        print_usage();
        std::process::exit(2);
    }
    let command = args[1].as_str();
    match command {
        "embed" => {
            let text = arg_value(&args, "--text", "");
            let dims = arg_value(&args, "--dims", "128").parse::<usize>().unwrap_or(DEFAULT_DIMS);
            let vec = embed(&text, dims);
            println!(
                "{{\"ok\":true,\"dims\":{},\"embedding\":{}}}",
                vec.len(),
                vector_json(&vec)
            );
        }
        "intent" => {
            let text = arg_value(&args, "--text", "");
            println!("{}", classify_intent(&text));
        }
        "parse-event" => {
            let source = arg_value(&args, "--source", "system");
            let text = arg_value(&args, "--text", "");
            println!("{}", parse_event(&source, &text));
        }
        "rerank" | "search" => {
            let query = arg_value(&args, "--query", "");
            let top_k = arg_value(&args, "--top-k", "10").parse::<usize>().unwrap_or(10);
            println!("{}", rerank(&query, top_k));
        }
        _ => {
            print_usage();
            std::process::exit(2);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn embeddings_are_normalized() {
        let v = embed("UltronPro memoria causal", 64);
        let norm = v.iter().map(|x| x * x).sum::<f32>().sqrt();
        assert!((norm - 1.0).abs() < 0.001);
    }

    #[test]
    fn intent_detects_self_query() {
        let out = classify_intent("qual LLM voce usa?");
        assert!(out.contains("\"label\":\"autobiographical\""));
    }

    #[test]
    fn rerank_prefers_overlap() {
        let a = score_rerank("memoria episodica causal", "memoria episodica estruturada causal");
        let b = score_rerank("memoria episodica causal", "receita de bolo");
        assert!(a > b);
    }
}
