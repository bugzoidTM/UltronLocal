from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from ultronpro import llm

TRACE_PATH = Path('/app/data/eval_traces.jsonl')
if not TRACE_PATH.exists():
    _alt = Path('/root/.openclaw/workspace/UltronPro/backend/data/eval_traces.jsonl')
    if _alt.exists():
        TRACE_PATH = _alt
STATE_PATH = Path('/app/data/reflexion_state.json')
LOG_PATH = Path('/app/data/reflexion_decisions.jsonl')
PROPOSALS_PATH = Path('/app/data/reflexion_proposals.jsonl')
LEARNING_PATH = Path('/app/data/reflexion_learning.jsonl')

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
}

PRM_STATE_PATH = Path('/app/data/prm_lite_state.json')
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


def _build_prompt(rows: list[dict[str, Any]], agg: dict[str, Any], thresholds: dict[str, float]) -> str:
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

    _append_jsonl(LEARNING_PATH, pending)
    st['pending_hypothesis_eval'] = None


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

    prompt = _build_prompt(rows, agg, thr)
    system = 'You are Ultron Reflexion Agent. Output ONLY valid JSON. Be conservative and factual.'
    raw = llm.complete(prompt=prompt, strategy='metacog_canary_qwen', system=system, json_mode=False, inject_persona=False, max_tokens=260)
    dec = _safe_parse_json(raw)

    action = str(dec.get('action') or 'none').strip()
    conf = float(dec.get('confidence') or 0.0)
    reason = str(dec.get('reason') or '').strip()[:500]
    hypothesis = str(dec.get('hypothesis') or reason or 'No explicit hypothesis').strip()[:700]
    applied: dict[str, Any] = {'type': 'none'}

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

    st['last_line'] = total_lines
    st['last_action'] = action
    st['last_confidence'] = conf
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
        'paths': {'state': str(STATE_PATH), 'log': str(LOG_PATH), 'proposals': str(PROPOSALS_PATH), 'learning': str(LEARNING_PATH)},
    }


def status() -> dict[str, Any]:
    st = _load_state()
    return {
        'ok': True,
        'state': st,
        'paths': {
            'trace': str(TRACE_PATH),
            'state': str(STATE_PATH),
            'log': str(LOG_PATH),
            'proposals': str(PROPOSALS_PATH),
            'learning': str(LEARNING_PATH),
            'prm_state': str(PRM_STATE_PATH),
        }
    }
