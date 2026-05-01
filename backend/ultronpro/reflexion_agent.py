from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from ultronpro import llm, cognitive_state, causal_graph, store

logger = logging.getLogger("uvicorn")

TRACE_PATH = Path(__file__).resolve().parent.parent / 'data' / 'eval_traces.jsonl'
try:
    _has_trace = TRACE_PATH.exists()
except Exception:
    _has_trace = False
if not _has_trace:
    _alt = Path('/root/.openclaw/workspace/UltronPro/backend/data/eval_traces.jsonl')
    try:
        if _alt.exists():
            TRACE_PATH = _alt
    except Exception:
        pass
STATE_PATH = Path(__file__).resolve().parent.parent / 'data' / 'reflexion_state.json'
LOG_PATH = Path(__file__).resolve().parent.parent / 'data' / 'reflexion_decisions.jsonl'
PROPOSALS_PATH = Path(__file__).resolve().parent.parent / 'data' / 'reflexion_proposals.jsonl'
LEARNING_PATH = Path(__file__).resolve().parent.parent / 'data' / 'reflexion_learning.jsonl'
LEARNING_PROPOSALS_PATH = Path(__file__).resolve().parent.parent / 'data' / 'learning_proposals.jsonl'

DEFAULTS = {
    'enabled': True,
    'min_new_traces': 20,
    'max_context_traces': 20,
    'human_approval_confidence_threshold': 0.7,
    'auto_apply_confidence_threshold': 0.7,
    'post_action_eval_min_new_traces': 20,
    'last_line': 0,
    'last_tick_ts': 0,
    'last_action': 'none',
    'pending_hypothesis_eval': None,
    'cycle_count': 0,
    'curiosity_probe_interval': 5,
}

PRM_STATE_PATH = Path(__file__).resolve().parent.parent / 'data' / 'prm_lite_state.json'
PRM_LOW_MIN = 0.40
PRM_LOW_MAX = 0.80
PRM_MED_MIN = 0.20
PRM_MED_MAX = 0.70

REVERSIBLE_ACTIONS = {'adjust_prm_thresholds', 'flag_problem_category'}
IRREVERSIBLE_ACTIONS = {'request_teacher_examples', 'propose_rag_ingest'}


def _now() -> int:
    return int(time.time())


def _load_state() -> dict[str, Any]:
    if STATE_PATH.exists():
        try:
            d = json.loads(STATE_PATH.read_text(encoding='utf-8'))
            if isinstance(d, dict):
                out = dict(DEFAULTS)
                out.update(d)
                return out
        except Exception:
            pass
    return dict(DEFAULTS)


def _save_state(d: dict[str, Any]):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    d['last_tick_ts'] = _now()
    STATE_PATH.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding='utf-8')


def _append_jsonl(path: Path, row: dict[str, Any]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as f:
        f.write(json.dumps(row, ensure_ascii=False) + '\n')


def _read_all_traces() -> tuple[list[dict[str, Any]], int]:
    if not TRACE_PATH.exists():
        return [], 0
    lines = TRACE_PATH.read_text(encoding='utf-8', errors='ignore').splitlines()
    rows: list[dict[str, Any]] = []
    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        try:
            rows.append(json.loads(ln))
        except Exception:
            continue
    return rows, len(lines)


def _slice_new_rows(all_rows: list[dict[str, Any]], last_line: int, max_context: int) -> list[dict[str, Any]]:
    start = max(0, int(last_line or 0))
    rows = all_rows[start:]
    if len(rows) > max_context:
        rows = rows[-max_context:]
    return rows


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {
        'count': len(rows),
        'outliers_gt_10s_pct': 0.0,
        'error_rate': 0.0,
        'by_strategy': {},
        'by_input_class': {},
        'by_strategy_input_class': {},
    }
    if not rows:
        return out

    outl = 0
    err = 0
    by_s: dict[str, dict[str, Any]] = {}
    by_c: dict[str, dict[str, Any]] = {}
    by_sc: dict[str, dict[str, Any]] = {}

    for r in rows:
        s = str(r.get('final_strategy') or 'none')
        c = str(r.get('input_class') or 'none')
        k = f'{s}|{c}'
        lat = r.get('latency_ms')
        ok = bool(r.get('ok', True))

        if isinstance(lat, (int, float)) and float(lat) > 10000:
            outl += 1
        if not ok:
            err += 1

        for dst, key in ((by_s, s), (by_c, c), (by_sc, k)):
            if key not in dst:
                dst[key] = {'n': 0, 'errors': 0, 'outliers_gt_10s': 0}
            dst[key]['n'] += 1
            if not ok:
                dst[key]['errors'] += 1
            if isinstance(lat, (int, float)) and float(lat) > 10000:
                dst[key]['outliers_gt_10s'] += 1

    def enrich(m: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        for _, v in m.items():
            n = max(1, int(v.get('n') or 0))
            v['error_rate'] = round(float(v.get('errors') or 0) / n, 4)
            v['outlier_rate'] = round(float(v.get('outliers_gt_10s') or 0) / n, 4)
        return m

    out['outliers_gt_10s_pct'] = round(outl / max(1, len(rows)), 4)
    out['error_rate'] = round(err / max(1, len(rows)), 4)
    out['by_strategy'] = enrich(by_s)
    out['by_input_class'] = enrich(by_c)
    out['by_strategy_input_class'] = enrich(by_sc)
    return out


def _load_prm_thresholds() -> dict[str, float]:
    if PRM_STATE_PATH.exists():
        try:
            d = json.loads(PRM_STATE_PATH.read_text(encoding='utf-8'))
            t = d.get('thresholds') if isinstance(d, dict) else None
            if isinstance(t, dict):
                return {'low': float(t.get('low', 0.72)), 'medium': float(t.get('medium', 0.50))}
        except Exception:
            pass
    return {'low': 0.72, 'medium': 0.50}


def _apply_prm_thresholds(low: float, medium: float) -> dict[str, Any]:
    low = max(PRM_LOW_MIN, min(PRM_LOW_MAX, float(low)))
    medium = max(PRM_MED_MIN, min(PRM_MED_MAX, float(medium)))
    if medium >= low:
        medium = max(PRM_MED_MIN, round(low - 0.02, 4))

    cur = {'thresholds': {'low': 0.72, 'medium': 0.50}}
    if PRM_STATE_PATH.exists():
        try:
            loaded = json.loads(PRM_STATE_PATH.read_text(encoding='utf-8'))
            if isinstance(loaded, dict):
                cur = loaded
        except Exception:
            pass

    before = dict((cur.get('thresholds') or {}))
    cur['thresholds'] = {'low': round(low, 4), 'medium': round(medium, 4)}
    cur['updated_at'] = _now()
    PRM_STATE_PATH.write_text(json.dumps(cur, ensure_ascii=False, indent=2), encoding='utf-8')
    return {'before': before, 'after': cur['thresholds']}


def _safe_parse_json(s: str) -> dict[str, Any]:
    txt = str(s or '').strip()
    if not txt:
        return {}
    try:
        return json.loads(txt)
    except Exception:
        pass
    i = txt.find('{')
    j = txt.rfind('}')
    if i >= 0 and j > i:
        try:
            return json.loads(txt[i:j + 1])
        except Exception:
            return {}
    return {}


def _build_prompt(rows: list[dict[str, Any]], agg: dict[str, Any], thresholds: dict[str, float], cog_state: dict[str, Any] | None = None) -> str:
    compact_rows = []
    for r in rows[-20:]:
        compact_rows.append({
            'request_id': r.get('request_id'),
            'strategy': r.get('final_strategy'),
            'input_class': r.get('input_class'),
            'ok': r.get('ok'),
            'latency_ms': r.get('latency_ms'),
            'prm_score': r.get('prm_score'),
            'prm_risk': r.get('prm_risk'),
            'gate_decision': r.get('gate_decision'),
        })
    spec = {
        'task': 'Decide if there is a meaningful failure pattern and whether to act now.',
        'allowed_actions': ['none', 'adjust_prm_thresholds', 'flag_problem_category', 'request_teacher_examples', 'propose_rag_ingest'],
        'policy': {
            'reversible_actions': sorted(list(REVERSIBLE_ACTIONS)),
            'irreversible_actions': sorted(list(IRREVERSIBLE_ACTIONS)),
            'auto_apply_confidence_threshold': 0.7,
            'below_threshold_behavior': 'register_hypothesis_only',
        },
        'response_json_schema': {
            'action': 'string',
            'confidence': 'float_0_1',
            'reason': 'string',
            'hypothesis': 'string',
            'category': 'string_optional',
            'threshold_patch': {'low': 'float_optional', 'medium': 'float_optional'},
            'teacher_request': {'task_type': 'string_optional', 'note': 'string_optional'},
            'rag_proposal': {'topic': 'string_optional', 'query_hint': 'string_optional'},
        },
        'current_prm_thresholds': thresholds,
        'aggregate': agg,
        'recent_traces': compact_rows,
        'cognitive_state': cog_state or {},
    }
    return json.dumps(spec, ensure_ascii=False)


def _prepare_hypothesis_record(*, action: str, confidence: float, reason: str, hypothesis: str, baseline: dict[str, Any], at_line: int, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        'ts': _now(),
        'acao': action,
        'confianca': round(float(confidence), 4),
        'razao': reason,
        'hipotese': hypothesis,
        'baseline': baseline,
        'start_line': int(at_line),
        'detalhes': details or {},
        'resultado_observado': None,
        'hipotese_confirmada': None,
        'confianca_pos_acao': None,
        'status': 'pending',
    }


def _evaluate_pending_if_ready(st: dict[str, Any], all_rows: list[dict[str, Any]], total_lines: int):
    pending = st.get('pending_hypothesis_eval')
    if not isinstance(pending, dict):
        return
    min_new = int(st.get('post_action_eval_min_new_traces') or 20)
    start_line = int(pending.get('start_line') or total_lines)
    if total_lines - start_line < min_new:
        return

    post_rows = all_rows[start_line:]
    post_agg = _aggregate(post_rows)
    base = pending.get('baseline') if isinstance(pending.get('baseline'), dict) else {}
    base_err = float(base.get('error_rate') or 0.0)
    base_out = float(base.get('outliers_gt_10s_pct') or 0.0)
    post_err = float(post_agg.get('error_rate') or 0.0)
    post_out = float(post_agg.get('outliers_gt_10s_pct') or 0.0)

    improved = (post_err < base_err) or (post_out < base_out)
    conf = float(pending.get('confianca') or 0.0)
    post_conf = min(1.0, conf + 0.08) if improved else max(0.0, conf - 0.12)

    result_txt = (
        f"error_rate {base_err:.4f}->{post_err:.4f}; "
        f"outliers_gt_10s_pct {base_out:.4f}->{post_out:.4f}; "
        f"window_n={len(post_rows)}"
    )

    pending['resultado_observado'] = result_txt
    pending['hipotese_confirmada'] = bool(improved)
    pending['confianca_pos_acao'] = round(post_conf, 4)
    pending['status'] = 'evaluated'
    pending['evaluated_ts'] = _now()

    if bool(improved):
        try:
            causal_graph.ingest_confirmed_hypothesis(
                hypothesis=str(pending.get('hipotese') or ''),
                details={
                    'baseline': pending.get('baseline') or {},
                    'observed': {'error_rate': post_err, 'outliers_gt_10s_pct': post_out, 'window_n': len(post_rows)},
                    'action': pending.get('acao'),
                },
            )
        except Exception:
            pass

    _append_jsonl(LEARNING_PATH, pending)
    st['pending_hypothesis_eval'] = None


def _extract_gap_evidence(rows: list[dict[str, Any]], last_n: int = 50) -> dict[str, Any]:
    sample = rows[-max(1, int(last_n or 50)):]
    by_cls: dict[str, dict[str, Any]] = {}
    topic_counts: dict[str, int] = {}

    for r in sample:
        cls = str(r.get('input_class') or 'general')
        ok = bool(r.get('ok', True))
        b = by_cls.setdefault(cls, {'n': 0, 'err': 0})
        b['n'] += 1
        if not ok:
            b['err'] += 1
        topic_counts[cls] = int(topic_counts.get(cls) or 0) + 1

    conf_domains = ((cognitive_state.get_state().get('self_model') or {}).get('confidence_by_domain') or {})
    low_conf = []
    for dom, c in (conf_domains.items() if isinstance(conf_domains, dict) else []):
        try:
            cv = float(c)
        except Exception:
            continue
        if cv < 0.6:
            low_conf.append({'domain': str(dom), 'confidence': round(cv, 4)})

    rag_cov = []
    for topic, cnt in sorted(topic_counts.items(), key=lambda kv: kv[1], reverse=True)[:8]:
        try:
            hits = store.db.search_triples(topic, limit=30)
            docs = len(hits or [])
        except Exception:
            docs = 0
        if docs < 3:
            rag_cov.append({'topic': topic, 'trace_mentions': int(cnt), 'rag_docs': int(docs)})

    recur_fail = []
    for cls, s in by_cls.items():
        n = int(s.get('n') or 0)
        er = (float(s.get('err') or 0) / max(1, n))
        if n >= 5 and er > 0.10:
            recur_fail.append({'input_class': cls, 'error_rate': round(er, 4), 'n': n})

    return {
        'window_n': len(sample),
        'low_confidence_domains': low_conf,
        'low_rag_coverage_topics': rag_cov,
        'recurrent_failure_classes': recur_fail,
    }


def _curiosity_closed_keys() -> set[str]:
    keys: set[str] = set()
    if not LEARNING_PROPOSALS_PATH.exists():
        return keys
    for ln in LEARNING_PROPOSALS_PATH.read_text(encoding='utf-8', errors='ignore').splitlines()[-3000:]:
        if not ln.strip():
            continue
        try:
            o = json.loads(ln)
        except Exception:
            continue
        if str(o.get('kind') or '') != 'curiosity_probe_closed':
            continue
        d = o.get('details') if isinstance(o.get('details'), dict) else {}
        k = str(d.get('key') or '').strip()
        if k:
            keys.add(k)
    return keys


def _emit_curiosity_probes(gaps: dict[str, Any]) -> list[dict[str, Any]]:
    created = []
    ts = _now()
    closed = _curiosity_closed_keys()

    # 1) low confidence -> benchmark proposal
    for x in (gaps.get('low_confidence_domains') or [])[:4]:
        k = f"benchmark_specific:{str(x.get('domain') or '').strip().lower()}"
        if k in closed:
            continue
        row = {
            'id': f"cp_{ts}_{len(created)+1}",
            'ts': ts,
            'kind': 'curiosity_probe',
            'title': f"Confiança baixa em domínio: {x.get('domain')}",
            'details': {
                'probe_type': 'benchmark_specific',
                'key': k,
                'domain': x.get('domain'),
                'confidence': x.get('confidence'),
                'trigger': 'confidence_by_domain_lt_0.6',
                'evidence': x,
            },
        }
        _append_jsonl(LEARNING_PROPOSALS_PATH, row)
        created.append(row)

    # 2) low rag coverage -> ingest proposal
    for x in (gaps.get('low_rag_coverage_topics') or [])[:4]:
        k = f"rag_ingest_proposal:{str(x.get('topic') or '').strip().lower()}"
        if k in closed:
            continue
        row = {
            'id': f"cp_{ts}_{len(created)+1}",
            'ts': ts,
            'kind': 'curiosity_probe',
            'title': f"Cobertura RAG baixa: {x.get('topic')}",
            'details': {
                'probe_type': 'rag_ingest_proposal',
                'key': k,
                'topic': x.get('topic'),
                'rag_docs': x.get('rag_docs'),
                'trace_mentions': x.get('trace_mentions'),
                'trigger': 'topic_in_traces_and_rag_docs_lt_3',
                'evidence': x,
            },
        }
        _append_jsonl(LEARNING_PROPOSALS_PATH, row)
        created.append(row)

    # 3) recurrent failures -> finetune proposal
    for x in (gaps.get('recurrent_failure_classes') or [])[:4]:
        k = f"gap_finetune_proposal:{str(x.get('input_class') or '').strip().lower()}"
        if k in closed:
            continue
        row = {
            'id': f"cp_{ts}_{len(created)+1}",
            'ts': ts,
            'kind': 'curiosity_probe',
            'title': f"Falha recorrente em classe: {x.get('input_class')}",
            'details': {
                'probe_type': 'gap_finetune_proposal',
                'key': k,
                'input_class': x.get('input_class'),
                'error_rate': x.get('error_rate'),
                'n': x.get('n'),
                'trigger': 'input_class_error_rate_gt_10pct_last_50',
                'evidence': x,
            },
        }
        _append_jsonl(LEARNING_PROPOSALS_PATH, row)
        created.append(row)

    return created


def _run_curiosity_probe_if_due(st: dict[str, Any], all_rows: list[dict[str, Any]]) -> dict[str, Any]:
    cyc = int(st.get('cycle_count') or 0)
    interval = max(1, int(st.get('curiosity_probe_interval') or 5))
    if cyc <= 0 or (cyc % interval) != 0:
        return {'triggered': False, 'cycle_count': cyc, 'interval': interval}

    gaps = _extract_gap_evidence(all_rows, last_n=50)
    created = _emit_curiosity_probes(gaps)
    return {
        'triggered': True,
        'cycle_count': cyc,
        'interval': interval,
        'gaps': gaps,
        'created_count': len(created),
        'created': created[:6],
    }


def tick(force: bool = False) -> dict[str, Any]:
    st = _load_state()
    if not bool(st.get('enabled', True)) and not force:
        return {'ok': True, 'skipped': True, 'reason': 'disabled'}

    all_rows, total_lines = _read_all_traces()
    _evaluate_pending_if_ready(st, all_rows, total_lines)

    new_count = max(0, total_lines - int(st.get('last_line') or 0))
    if (not force) and new_count < int(st.get('min_new_traces') or 20):
        _save_state(st)
        return {'ok': True, 'skipped': True, 'reason': 'not_enough_new_traces', 'new_count': new_count, 'required': int(st.get('min_new_traces') or 20), 'last_line': int(st.get('last_line') or 0), 'total_lines': total_lines}

    rows = _slice_new_rows(all_rows, int(st.get('last_line') or 0), int(st.get('max_context_traces') or 20))
    agg = _aggregate(rows)
    thr = _load_prm_thresholds()

    cog = cognitive_state.compact_for_prompt(max_chars=800)
    prompt = _build_prompt(rows, agg, thr, cog_state=cog)
    system = 'You are Ultron Reflexion Agent. Output ONLY valid JSON. Be conservative and factual.'
    
    # Tentar LLM cloud com fallback determinístico
    dec = None
    try:
        # Lane 1 micro: loops usam provider barato
        raw = llm.complete(prompt=prompt, strategy='reflexion_loop', system=system, json_mode=False, inject_persona=False, max_tokens=260)
        dec = _safe_parse_json(raw)
    except Exception as e:
        logger.warning(f"Reflexion LLM unavailable: {e}. Using deterministic fallback.")
    
    # Fallback determinístico: analisar métricas diretamente
    if dec is None:
        action, conf, reason, hypothesis = _deterministic_reflexion(agg, rows)
        dec = {'action': action, 'confidence': conf, 'reason': reason, 'hypothesis': hypothesis}
    
    action = str(dec.get('action') or 'none').strip()
    conf = float(dec.get('confidence') or 0.0)
    reason = str(dec.get('reason') or '').strip()[:500]
    hypothesis = str(dec.get('hypothesis') or reason or 'No explicit hypothesis').strip()[:700]
    applied: dict[str, Any] = {'type': 'none', 'llm_used': dec is not None}

    auto_thr = float(st.get('auto_apply_confidence_threshold') or 0.7)
    human_thr = float(st.get('human_approval_confidence_threshold') or 0.7)

    # Below confidence threshold: hypothesis only, no action.
    if conf <= human_thr:
        action = 'none'
        applied = {'type': 'hypothesis_only', 'status': 'recorded'}
        _append_jsonl(PROPOSALS_PATH, {
            'ts': _now(), 'action': action, 'confidence': conf, 'reason': reason,
            'hypothesis': hypothesis, 'status': 'hypothesis_only'
        })

    elif action == 'adjust_prm_thresholds':
        p = dec.get('threshold_patch') if isinstance(dec.get('threshold_patch'), dict) else {}
        low, med = p.get('low'), p.get('medium')
        if conf > auto_thr and isinstance(low, (int, float)) and isinstance(med, (int, float)):
            applied = {'type': 'adjust_prm_thresholds', **_apply_prm_thresholds(float(low), float(med)), 'reversible': True}
        else:
            applied = {'type': 'adjust_prm_thresholds', 'status': 'invalid_patch'}

    elif action == 'flag_problem_category':
        category = str(dec.get('category') or 'unknown')[:120]
        applied = {'type': 'flag_problem_category', 'category': category, 'reversible': True}
        _append_jsonl(PROPOSALS_PATH, {'ts': _now(), 'action': action, 'confidence': conf, 'reason': reason, 'hypothesis': hypothesis, 'status': 'registered', 'category': category})

    elif action in IRREVERSIBLE_ACTIONS:
        # Never auto-execute irreversible actions in phase 2.
        payload = {
            'teacher_request': dec.get('teacher_request') if isinstance(dec.get('teacher_request'), dict) else {},
            'rag_proposal': dec.get('rag_proposal') if isinstance(dec.get('rag_proposal'), dict) else {},
        }
        applied = {'type': action, 'status': 'needs_human_approval', 'reversible': False}
        _append_jsonl(PROPOSALS_PATH, {'ts': _now(), 'action': action, 'confidence': conf, 'reason': reason, 'hypothesis': hypothesis, 'status': 'needs_human_approval', 'proposal': payload})

    else:
        action = 'none'
        applied = {'type': 'none'}

    # Register hypothesis for learning/evaluation window if any actual action happened.
    if action in REVERSIBLE_ACTIONS and applied.get('type') not in ('none', 'hypothesis_only', 'invalid_patch'):
        st['pending_hypothesis_eval'] = _prepare_hypothesis_record(
            action=action,
            confidence=conf,
            reason=reason,
            hypothesis=hypothesis,
            baseline={'error_rate': agg.get('error_rate', 0.0), 'outliers_gt_10s_pct': agg.get('outliers_gt_10s_pct', 0.0)},
            at_line=total_lines,
            details={'applied': applied},
        )

    row = {
        'ts': _now(),
        'new_count': new_count,
        'aggregate': agg,
        'current_thresholds': thr,
        'decision': {'action': action, 'confidence': conf, 'reason': reason, 'hypothesis': hypothesis, 'raw': dec},
        'applied': applied,
    }
    _append_jsonl(LOG_PATH, row)

    try:
        cognitive_state.apply_reflexion_signal(
            action=action,
            confidence=conf,
            hypothesis=hypothesis,
            reason=reason,
            aggregate=agg,
        )
    except Exception:
        pass

    st['last_line'] = total_lines
    st['last_action'] = action
    st['last_confidence'] = conf
    st['cycle_count'] = int(st.get('cycle_count') or 0) + 1
    probe = _run_curiosity_probe_if_due(st, all_rows)
    _save_state(st)

    return {
        'ok': True,
        'triggered': action != 'none',
        'new_count': new_count,
        'action': action,
        'confidence': conf,
        'reason': reason,
        'hypothesis': hypothesis,
        'applied': applied,
        'curiosity_probe': probe,
        'paths': {
            'state': str(STATE_PATH),
            'log': str(LOG_PATH),
            'proposals': str(PROPOSALS_PATH),
            'learning': str(LEARNING_PATH),
            'learning_proposals': str(LEARNING_PROPOSALS_PATH),
        },
    }


def status() -> dict[str, Any]:
    st = _load_state()
    return {
        'ok': True,
        'state': st,
        'cognitive_state': cognitive_state.compact_for_prompt(max_chars=900),
        'causal_graph': causal_graph.status(),
        'paths': {
            'trace': str(TRACE_PATH),
            'state': str(STATE_PATH),
            'log': str(LOG_PATH),
            'proposals': str(PROPOSALS_PATH),
            'learning': str(LEARNING_PATH),
            'learning_proposals': str(LEARNING_PROPOSALS_PATH),
            'prm_state': str(PRM_STATE_PATH),
            'cognitive_state': str(Path(__file__).resolve().parent.parent / 'data' / 'cognitive_state.json'),
        }
    }


def _deterministic_reflexion(agg: dict, rows: list[dict]) -> tuple[str, float, str, str]:
    """
    Fallback determinístico para reflexion.
    
    Analisa métricas agregadas diretamente sem LLM.
    Retorna: (action, confidence, reason, hypothesis)
    """
    total_traces = int(agg.get('total', 0))
    if total_traces == 0:
        return 'none', 0.3, 'No traces to analyze (deterministic fallback)', 'Sistema ocioso'
    
    # Calcular taxa de sucesso
    successes = int(agg.get('successes', 0))
    failures = int(agg.get('failures', 0))
    success_rate = successes / max(1, total_traces)
    
    # Detectar problemas por padrões determinísticos
    problem_categories = []
    
    if success_rate < 0.5:
        problem_categories.append('low_success_rate')
    
    if failures > successes:
        problem_categories.append('failure_dominant')
    
    # Calcular variância de latência
    latencies = [r.get('latency_ms', 0) for r in rows if isinstance(r, dict)]
    if latencies:
        avg_lat = sum(latencies) / len(latencies)
        high_lat_count = sum(1 for l in latencies if l > avg_lat * 2)
        if high_lat_count > len(latencies) * 0.3:
            problem_categories.append('high_latency_variance')
    
    # Determinar ação baseado em regras
    if 'low_success_rate' in problem_categories:
        return (
            'flag_problem_category',
            0.6,
            f'Deterministic: success_rate={success_rate:.0%}, failures={failures} (fallback)',
            f'Baixa taxa de sucesso detectada: {success_rate:.0%}. Necessária investigação.'
        )
    
    if 'failure_dominant' in problem_categories:
        return (
            'flag_problem_category',
            0.5,
            f'Deterministic: failures={failures} > successes={successes} (fallback)',
            f'Falhas dominam: {failures} contra {successes} acertos.'
        )
    
    # Nenhum problema crítico
    return (
        'none',
        0.8,
        f'Deterministic: nominal state (success_rate={success_rate:.0%})',
        f'Sistema em estado nominal. Taxa de sucesso: {success_rate:.0%}.'
    )
