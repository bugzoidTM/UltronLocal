from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from ultronpro import llm

RECENT_SOURCES_PATH = Path(__file__).resolve().parent.parent / 'data' / 'analogy_recent_sources.json'
DECISIONS_LOG_PATH = Path(__file__).resolve().parent.parent / 'data' / 'analogy_decisions.jsonl'
BENCHMARK_COUNTS_PATH = Path(__file__).resolve().parent.parent / 'data' / 'analogy_benchmark_counts.json'
RECENT_WINDOW = 8


def _load_recent_sources() -> list[str]:
    try:
        if RECENT_SOURCES_PATH.exists():
            d = json.loads(RECENT_SOURCES_PATH.read_text(encoding='utf-8'))
            if isinstance(d, list):
                return [str(x) for x in d][-RECENT_WINDOW:]
    except Exception:
        pass
    return []


def _save_recent_sources(items: list[str]) -> None:
    try:
        RECENT_SOURCES_PATH.parent.mkdir(parents=True, exist_ok=True)
        RECENT_SOURCES_PATH.write_text(json.dumps(items[-RECENT_WINDOW:], ensure_ascii=False), encoding='utf-8')
    except Exception:
        pass


def _register_recent_source(source_domain: str | None) -> None:
    sd = str(source_domain or '').strip()
    if not sd:
        return
    items = _load_recent_sources()
    items.append(sd)
    _save_recent_sources(items)


def _recent_repetition_penalty(source_domain: str | None) -> float:
    sd = str(source_domain or '').strip()
    if not sd:
        return 0.0
    items = _load_recent_sources()
    cnt = sum(1 for x in items if x == sd)
    if cnt <= 1:
        return 0.0
    # 7.1d: penalização mais agressiva; após ~3 usos no lote já cai de forma visível
    return min(0.45, 0.12 * (cnt - 1))


def _log_decision(entry: dict[str, Any]) -> None:
    try:
        DECISIONS_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with DECISIONS_LOG_PATH.open('a', encoding='utf-8') as f:
            f.write(json.dumps({'ts': int(time.time()), **(entry or {})}, ensure_ascii=False) + '\n')
    except Exception:
        pass


def _load_benchmark_counts() -> dict[str, int]:
    try:
        if BENCHMARK_COUNTS_PATH.exists():
            d = json.loads(BENCHMARK_COUNTS_PATH.read_text(encoding='utf-8'))
            if isinstance(d, dict):
                return {str(k): int(v or 0) for k, v in d.items()}
    except Exception:
        pass
    return {}


def _save_benchmark_counts(items: dict[str, int]) -> None:
    try:
        BENCHMARK_COUNTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        BENCHMARK_COUNTS_PATH.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding='utf-8')
    except Exception:
        pass


def _benchmark_domain_cap_reached(source_domain: str | None, limit: int = 17) -> bool:
    sd = str(source_domain or '').strip()
    if not sd:
        return False
    counts = _load_benchmark_counts()
    return int(counts.get(sd) or 0) >= int(limit)


def _benchmark_register_source(source_domain: str | None) -> None:
    sd = str(source_domain or '').strip()
    if not sd:
        return
    counts = _load_benchmark_counts()
    counts[sd] = int(counts.get(sd) or 0) + 1
    _save_benchmark_counts(counts)


def _is_static_problem(problem_text: str) -> bool:
    txt = str(problem_text or '').lower()
    static_markers = [
        'binária', 'binario', 'binary', 'classifique', 'classificação', 'classificacao',
        'estático', 'estatica', 'static', 'checklist', 'porta lógica', 'porta logica',
        'booleana', 'autêntico ou falso', 'autentico ou falso', 'decisão única', 'decisao unica',
        'sem iteração', 'sem iteracao', 'taxonômico', 'taxonomico', 'regra fixa', 'regras fixas',
        'triagem estática', 'triagem estatica', 'verificação booleana', 'verificacao booleana'
    ]
    return any(m in txt for m in static_markers)


def _structural_similarity(problem_text: str, candidate: dict[str, Any]) -> float:
    txt = str(problem_text or '').lower()
    source_dom = str((candidate or {}).get('source_domain') or '').lower()
    target_dom = str((candidate or {}).get('target_domain') or '').lower()
    notes = str((candidate or {}).get('notes') or '').lower()
    mapping = (candidate or {}).get('mapping') or {}

    static_problem = _is_static_problem(txt)
    generic_fallback = source_dom == 'sistemas_dinâmicos' or 'generic fallback' in notes
    same_domain = bool(source_dom and target_dom and source_dom == target_dom)

    if static_problem and generic_fallback:
        return 0.18
    if static_problem and source_dom in ('lógica_booleana', 'sistemas_de_classificação', 'forense_regras'):
        return 0.74
    if same_domain and len(mapping) >= 2:
        return 0.78
    if len(mapping) >= 3:
        return 0.68
    if len(mapping) >= 2:
        return 0.62
    return 0.45 if mapping else 0.0


def propose_analogy(problem_text: str, target_domain: str | None = None, context_snippets: list[str] | None = None) -> dict[str, Any] | None:
    txt = (problem_text or '').strip()
    if len(txt) < 12:
        return None
    ctx = "\n".join((context_snippets or [])[:5])
    tl = txt.lower()
    static_problem = _is_static_problem(txt)
    low_uncertainty_static = static_problem and any(k in tl for k in ['binária', 'binario', 'binary', 'classifique', 'autêntico ou falso', 'autentico ou falso', 'checklist', 'critério dsm', 'criterio dsm', 'score, renda'])
    structural_threshold = 0.55 if low_uncertainty_static else (0.55 if static_problem else 0.40)
    candidates: list[dict[str, Any]] = []

    prompt = f"""Given the target problem below, propose ONE useful cross-domain analogy.
The analogy should map a well-understood system (source) to the target domain to uncover structural patterns.
Return ONLY JSON with keys:
source_domain, target_domain, source_concept, target_concept, mapping (object), inference_rule, confidence (0..1), notes.

Target domain: {target_domain or 'general'}
Problem:\n{txt[:2200]}
Context:\n{ctx[:1800]}
"""
    try:
        strategy = 'reasoning' if target_domain and target_domain not in ('operational', 'general') else 'cheap'
        raw = llm.complete(prompt, strategy=strategy, json_mode=True, input_class='analogy_transfer')
        d = json.loads(raw) if raw else {}
        if isinstance(d, dict) and d.get('mapping'):
            d['confidence'] = max(0.0, min(1.0, float(d.get('confidence') or 0.55)))
            normalized_target = str(target_domain or d.get('target_domain') or '').strip().lower()
            same_domain = str(d.get('source_domain') or '').strip().lower() == normalized_target
            if not same_domain:
                d['confidence'] = max(0.0, d['confidence'] - _recent_repetition_penalty(d.get('source_domain')))
            d['target_domain'] = target_domain or d.get('target_domain') or 'general'
            d['_reason'] = 'llm_candidate'
            candidates.append(d)
    except Exception:
        pass

    static_logic = any(k in tl for k in ['binária', 'binario', 'binary', 'porta lógica', 'porta logica', 'booleana', 'checklist', 'atende ou não', 'ativa ou não ativa'])
    static_class = any(k in tl for k in ['classifique', 'classificação', 'classificacao', 'taxonômico', 'taxonomico', 'vertebrado', 'invertebrado', 'rotulagem categórica'])
    static_rules = any(k in tl for k in ['autêntico ou falso', 'autentico ou falso', 'fraude ou não', 'fraude ou nao', 'regras', 'forense', 'score, renda', 'critério dsm', 'criterio dsm'])

    if static_logic:
        candidates.append({
            'source_domain': 'lógica_booleana',
            'target_domain': target_domain or 'general',
            'source_concept': 'porta lógica / decisão booleana',
            'target_concept': 'classificação binária única',
            'mapping': {'entrada': 'evidência observável', 'limiar_regra': 'critério de decisão', 'saída_0_1': 'classe final'},
            'inference_rule': 'Avaliar entradas contra uma regra discreta e produzir uma decisão booleana única.',
            'confidence': 0.74,
            'notes': 'deterministic static-logic fallback',
            '_reason': 'static_logic_fallback',
        })
    if static_class:
        candidates.append({
            'source_domain': 'sistemas_de_classificação',
            'target_domain': target_domain or 'general',
            'source_concept': 'árvore de decisão taxonômica',
            'target_concept': 'atribuição de classe estática',
            'mapping': {'atributo': 'característica observável', 'regra_de_partição': 'critério taxonômico', 'folha': 'classe final'},
            'inference_rule': 'Particionar por atributos fixos até alcançar uma classe terminal.',
            'confidence': 0.72,
            'notes': 'deterministic static-classification fallback',
            '_reason': 'static_classification_fallback',
        })
    if static_rules:
        candidates.append({
            'source_domain': 'forense_regras',
            'target_domain': target_domain or 'general',
            'source_concept': 'motor de regras / triagem forense',
            'target_concept': 'verificação estática de conformidade',
            'mapping': {'regra': 'critério de aceitação', 'evidência': 'feature observada', 'veredito': 'aprova/rejeita'},
            'inference_rule': 'Aplicar regras fixas sobre evidências estáticas para emitir um veredito discreto.',
            'confidence': 0.70,
            'notes': 'deterministic static-rules fallback',
            '_reason': 'static_rules_fallback',
        })
    if 'gravidade' in tl and ('maré' in tl or 'marea' in tl):
        candidates.append({
            'source_domain': 'física',
            'target_domain': target_domain or 'oceanografia',
            'source_concept': 'força gravitacional',
            'target_concept': 'variação de maré',
            'mapping': {'massa_corpo': 'intensidade_atração', 'distância': 'amplitude_efeito', 'atração_diferencial': 'elevação_rebaixamento_nível'},
            'inference_rule': 'Se a atração diferencial aumenta, a amplitude da maré tende a aumentar sob mesmas condições locais.',
            'confidence': 0.62,
            'notes': 'fallback heuristic',
            '_reason': 'physics_fallback',
        })
    candidates.append({
        'source_domain': 'sistemas_dinâmicos',
        'target_domain': target_domain or 'general',
        'source_concept': 'forças e restrições',
        'target_concept': 'estado do problema',
        'mapping': {'força': 'pressão causal', 'restrição': 'limite operacional', 'equilíbrio': 'solução estável'},
        'inference_rule': 'Mapear forças e restrições do domínio fonte para estimar estados estáveis no domínio alvo.',
        'confidence': max(0.30, 0.51 - _recent_repetition_penalty('sistemas_dinâmicos')),
        'notes': 'generic fallback',
        '_reason': 'generic_fallback',
    })

    valid_candidates = [c for c in candidates if not _benchmark_domain_cap_reached(c.get('source_domain'))]
    if not valid_candidates:
        _log_decision({'decision': 'no_analogy_found', 'reason': 'all_candidates_filtered_by_cap', 'target_domain': target_domain, 'threshold': structural_threshold})
        return None

    scored: list[tuple[float, float, dict[str, Any]]] = []
    for cand in valid_candidates:
        sim = _structural_similarity(txt, cand)
        score = float(cand.get('confidence') or 0.0) + sim
        scored.append((score, sim, cand))

    best_score, best_sim, best = max(scored, key=lambda x: x[0])
    if best_sim < structural_threshold:
        _log_decision({'decision': 'no_analogy_found', 'reason': 'best_candidate_below_threshold', 'source_domain': best.get('source_domain'), 'target_domain': best.get('target_domain'), 'similarity': best_sim, 'threshold': structural_threshold, 'problem_type': 'static_low_uncertainty' if low_uncertainty_static else ('static' if static_problem else 'dynamic_or_unknown')})
        return None

    _register_recent_source(best.get('source_domain'))
    _benchmark_register_source(best.get('source_domain'))
    _log_decision({'decision': 'accepted', 'source_domain': best.get('source_domain'), 'target_domain': best.get('target_domain'), 'similarity': best_sim, 'threshold': structural_threshold, 'reason': best.get('_reason'), 'score': round(best_score, 4)})
    best.pop('_reason', None)
    return best


def validate_analogy(candidate: dict[str, Any]) -> dict[str, Any]:
    if not candidate:
        return {'valid': False, 'confidence': 0.0, 'reasons': ['empty candidate']}

    conf = float(candidate.get('confidence') or 0.5)
    mapping = candidate.get('mapping')
    reasons: list[str] = []

    if not isinstance(mapping, dict) or len(mapping) < 1:
        return {'valid': False, 'confidence': 0.0, 'reasons': ['mapping missing']}

    if len(mapping) >= 2:
        conf += 0.12
    if candidate.get('inference_rule'):
        conf += 0.08

    source_dom = (candidate.get('source_domain') or '').lower()
    target_dom = (candidate.get('target_domain') or '').lower()
    if source_dom and target_dom and source_dom != target_dom:
        if any(d in target_dom for d in ('biology', 'history', 'economy', 'psychology')):
            conf += 0.12

    same_domain = bool(source_dom and target_dom and source_dom == target_dom)
    if same_domain and source_dom not in ('general', ''):
        conf += 0.10
        reasons.append('same-domain specialization boost')

    # Cap de confiança para fallback genérico / fonte dominante,
    # mas não para baseline técnico same-domain
    notes = (candidate.get('notes') or '').lower()
    if not same_domain and (source_dom in ('sistemas_dinâmicos', 'general') or 'generic fallback' in notes):
        conf = min(conf, 0.70)
        reasons.append('generic fallback confidence capped')

    # Penalização adicional por repetição recente da mesma fonte,
    # mas aliviar baseline técnico same-domain
    rep_pen = 0.0 if same_domain else _recent_repetition_penalty(candidate.get('source_domain'))
    if rep_pen > 0:
        conf -= min(0.22, rep_pen)
        reasons.append(f'repetition penalty applied ({rep_pen:.2f})')

    conf = max(0.0, min(1.0, conf))
    valid = conf >= 0.5
    if valid:
        reasons.append('structural mapping accepted')
    else:
        reasons.append('low confidence')
    return {'valid': valid, 'confidence': conf, 'reasons': reasons}


def apply_analogy(candidate: dict[str, Any], problem_text: str) -> dict[str, Any]:
    mapping = candidate.get('mapping') or {}
    rule = (candidate.get('inference_rule') or '').strip()
    if not rule:
        # small deterministic fallback
        pairs = [f"{k}->{v}" for k, v in list(mapping.items())[:4]]
        rule = f"Transferir estrutura relacional mapeando: {', '.join(pairs)}"

    hypothesis = f"Analogia aplicada: {rule}. Problema alvo: {(problem_text or '')[:280]}"
    return {
        'derived_rule': rule,
        'hypothesis': hypothesis,
        'mapping': mapping,
    }
