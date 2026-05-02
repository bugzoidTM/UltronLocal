"""Bridge to the lightweight Rust local inference engine.

The Rust binary is intentionally small: deterministic hashed embeddings, vector
search/rerank, symbolic intent rules and event parsing. Python keeps the same
contract as a fallback so weak machines can run today and switch to Rust by
dropping the compiled binary in place.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import time
import unicodedata
from pathlib import Path
from typing import Any


DEFAULT_DIMS = int(os.getenv("ULTRON_LOCAL_INFERENCE_DIMS", "128") or 128)
DEFAULT_TIMEOUT_SEC = float(os.getenv("ULTRON_LOCAL_INFERENCE_TIMEOUT_SEC", "1.5") or 1.5)
ROOT = Path(__file__).resolve().parents[2]
CRATE_DIR = ROOT / "backend" / "rust" / "ultron_local_infer"


def _env_flag(name: str, default: str = "1") -> bool:
    return str(os.getenv(name, default)).strip().lower() in {"1", "true", "yes", "on"}


def _exe_name() -> str:
    return "ultron_local_infer.exe" if os.name == "nt" else "ultron_local_infer"


def candidate_binary_paths() -> list[Path]:
    env_path = os.getenv("ULTRON_LOCAL_INFERENCE_BIN")
    paths: list[Path] = []
    if env_path:
        paths.append(Path(env_path))
    paths.extend([
        CRATE_DIR / "target" / "release" / _exe_name(),
        CRATE_DIR / "target" / "debug" / _exe_name(),
        ROOT / "backend" / "bin" / _exe_name(),
    ])
    found = shutil.which(_exe_name())
    if found:
        paths.append(Path(found))
    return paths


def binary_path() -> Path | None:
    for path in candidate_binary_paths():
        try:
            if path.exists() and path.is_file():
                return path
        except Exception:
            continue
    return None


def rust_available() -> bool:
    return binary_path() is not None


def _normalize(text: str) -> str:
    value = unicodedata.normalize("NFKD", str(text or ""))
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return value.lower()


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9_]+", _normalize(text))


def _hash64(text: str) -> int:
    # Match the spirit of the Rust FNV path with a stable Python hash source.
    return int(hashlib.blake2b(text.encode("utf-8", errors="ignore"), digest_size=8).hexdigest(), 16)


def _fallback_embed(text: str, dims: int = DEFAULT_DIMS) -> list[float]:
    dims = max(8, int(dims or DEFAULT_DIMS))
    vec = [0.0] * dims
    for tok in _tokens(text):
        h = _hash64(tok)
        vec[h % dims] += -1.0 if (h >> 63) & 1 else 1.0
        if len(tok) >= 4:
            for idx in range(0, len(tok) - 2):
                gram = tok[idx:idx + 3]
                gh = _hash64(gram)
                vec[gh % dims] += -0.35 if (gh >> 62) & 1 else 0.35
    norm = math.sqrt(sum(v * v for v in vec))
    if norm > 0:
        vec = [v / norm for v in vec]
    return vec


def cosine_similarity(a: list[float], b: list[float]) -> float:
    n = min(len(a or []), len(b or []))
    if n <= 0:
        return 0.0
    dot = sum(float(a[i]) * float(b[i]) for i in range(n))
    na = math.sqrt(sum(float(x) * float(x) for x in a[:n]))
    nb = math.sqrt(sum(float(x) * float(x) for x in b[:n]))
    denom = na * nb
    return 0.0 if denom == 0 else float(dot / denom)


def _call_engine(args: list[str], *, stdin: str | None = None, timeout_sec: float | None = None) -> dict[str, Any] | None:
    if not _env_flag("ULTRON_LOCAL_INFERENCE_ENABLED", "1"):
        return None
    exe = binary_path()
    if not exe:
        return None
    try:
        proc = subprocess.run(
            [str(exe), *args],
            input=stdin,
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=float(timeout_sec if timeout_sec is not None else DEFAULT_TIMEOUT_SEC),
            check=False,
        )
        if proc.returncode != 0:
            return None
        data = json.loads(proc.stdout or "{}")
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def embed_text(text: str, *, dims: int = DEFAULT_DIMS, prefer_rust: bool = True) -> list[float]:
    if prefer_rust:
        data = _call_engine(["embed", "--text", str(text or ""), "--dims", str(int(dims or DEFAULT_DIMS))])
        vec = (data or {}).get("embedding")
        if isinstance(vec, list) and vec:
            try:
                return [float(v) for v in vec]
            except Exception:
                pass
    return _fallback_embed(text, dims=dims)


def embed_texts(texts: list[str], *, dims: int = DEFAULT_DIMS, prefer_rust: bool = True) -> list[list[float]]:
    return [embed_text(text, dims=dims, prefer_rust=prefer_rust) for text in texts or []]


def classify_intent(text: str, *, prefer_rust: bool = True) -> dict[str, Any]:
    if prefer_rust:
        data = _call_engine(["intent", "--text", str(text or "")])
        if data and data.get("ok"):
            return data

    toks = _tokens(text)
    token_set = set(toks)
    question = "?" in str(text or "") or bool(token_set & {"quem", "qual", "quais", "quando", "onde", "como", "who", "what", "when", "where", "how"})
    self_hits = _hits(toks, ("voce", "vc", "ultron", "ultronpro", "seu", "sua", "your", "you"))
    creation_hits = _hits(toks, ("nasc", "criad", "criador", "creator", "orig", "desenvolv"))
    capability_hits = _hits(toks, ("llm", "modelo", "model", "provider", "provedor", "capaz", "consegue"))
    action_hits = _hits(toks, ("criar", "execut", "rode", "rodar", "analise", "corrij", "implementar", "faca"))
    current_hits = _hits(toks, ("atual", "hoje", "agora", "latest", "current", "presidente", "ceo", "preco", "versao"))
    search_hits = _hits(toks, ("busque", "pesquise", "procure", "web", "internet", "noticia", "lookup"))
    if self_hits and (creation_hits or capability_hits or question):
        category = "autobiographical_creation" if creation_hits else ("autobiographical_capability" if capability_hits else "autobiographical_identity")
        return {"ok": True, "label": "autobiographical", "category": category, "confidence": 0.82, "method": "python_local_symbolic", "signals": self_hits + creation_hits + capability_hits}
    if question and (current_hits or search_hits):
        return {"ok": True, "label": "external_factual", "category": "current_world_fact", "confidence": 0.74, "method": "python_local_symbolic", "signals": current_hits + search_hits}
    if action_hits:
        return {"ok": True, "label": "action_request", "category": "tool_or_code_action", "confidence": 0.68, "method": "python_local_symbolic", "signals": action_hits}
    return {"ok": True, "label": "general", "category": "none", "confidence": 0.35, "method": "python_local_symbolic", "signals": []}


def _hits(tokens: list[str], stems: tuple[str, ...]) -> list[str]:
    out: list[str] = []
    for tok in tokens:
        for stem in stems:
            if tok == stem or tok.startswith(stem):
                out.append(stem)
    return sorted(set(out))


def parse_event(source: str, text: str, *, prefer_rust: bool = True) -> dict[str, Any]:
    if prefer_rust:
        data = _call_engine(["parse-event", "--source", str(source or "system"), "--text", str(text or "")])
        if data and data.get("ok"):
            return data
    toks = _tokens(text)
    severity = "critical" if _hits(toks, ("panic", "critical", "fatal", "crash")) else (
        "error" if _hits(toks, ("error", "erro", "failed", "falha", "timeout", "exception")) else (
            "warning" if _hits(toks, ("warn", "warning", "alerta", "risk")) else "info"
        )
    )
    event_type = "audio" if any("audio" in t or "voice" in t for t in toks) else (
        "network" if any("http" in t or "api" in t for t in toks) else (
            "filesystem" if any("file" in t or "path" in t or "fs" in t for t in toks) else "system"
        )
    )
    return {
        "ok": True,
        "source": str(source or "system"),
        "event_type": event_type,
        "severity": severity,
        "summary": str(text or "").strip()[:220],
        "token_count": len(toks),
    }


def rerank(query: str, candidates: list[dict[str, Any]], *, top_k: int = 10, prefer_rust: bool = True) -> list[dict[str, Any]]:
    rows = []
    for idx, item in enumerate(candidates or []):
        cid = str(item.get("id") or item.get("source_id") or idx)
        text = _candidate_text(item)
        if text:
            rows.append((cid, text, item))

    if prefer_rust and rows:
        stdin = "\n".join(f"{cid}\t{text.replace(chr(9), ' ')}" for cid, text, _ in rows)
        data = _call_engine(["rerank", "--query", str(query or ""), "--top-k", str(int(top_k or 10))], stdin=stdin)
        raw_results = (data or {}).get("results")
        if isinstance(raw_results, list):
            by_id = {cid: item for cid, _, item in rows}
            out = []
            for row in raw_results:
                if not isinstance(row, dict):
                    continue
                item = dict(by_id.get(str(row.get("id") or ""), {}))
                item["_local_inference_score"] = float(row.get("score") or 0.0)
                item["_local_inference_backend"] = "rust"
                out.append(item)
            if out:
                return out[:max(1, int(top_k or 10))]

    scored = []
    qv = embed_text(query, prefer_rust=False)
    qtoks = set(_tokens(query))
    neg_next = _hard_negative_terms(_tokens(query))
    for cid, text, item in rows:
        tv = embed_text(text, prefer_rust=False)
        ttoks = set(_tokens(text))
        lexical = len(qtoks & ttoks) / max(1, len(qtoks | ttoks))
        hard_neg = sum(1 for term in neg_next if term in ttoks) * 0.18
        score = (lexical * 0.55) + (cosine_similarity(qv, tv) * 0.45) - hard_neg
        rr = dict(item)
        rr["_local_inference_score"] = round(float(score), 4)
        rr["_local_inference_backend"] = "python"
        scored.append(rr)
    scored.sort(key=lambda x: float(x.get("_local_inference_score") or 0.0), reverse=True)
    return scored[:max(1, int(top_k or 10))]


def vector_search(query: str, candidates: list[dict[str, Any]], *, top_k: int = 10) -> list[dict[str, Any]]:
    return rerank(query, candidates, top_k=top_k)


def _candidate_text(item: dict[str, Any]) -> str:
    parts = [
        item.get("text"),
        item.get("content"),
        item.get("title"),
        item.get("summary"),
        item.get("subject"),
        item.get("predicate"),
        item.get("object"),
    ]
    return " ".join(str(p) for p in parts if p).strip()


def _hard_negative_terms(toks: list[str]) -> set[str]:
    neg = {"nao", "não", "sem", "evitar", "exceto", "without", "avoid", "except"}
    out = set()
    for idx, tok in enumerate(toks):
        if tok in neg and idx + 1 < len(toks):
            out.add(toks[idx + 1])
    return out


def status() -> dict[str, Any]:
    exe = binary_path()
    return {
        "ok": True,
        "enabled": _env_flag("ULTRON_LOCAL_INFERENCE_ENABLED", "1"),
        "rust_available": bool(exe),
        "binary_path": str(exe) if exe else "",
        "crate_dir": str(CRATE_DIR),
        "fallback": "python_deterministic",
        "dims": DEFAULT_DIMS,
        "checked_at": int(time.time()),
    }
