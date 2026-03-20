from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

STATE_PATH = Path('/app/data/cognitive_state.json')

DEFAULT_STATE = {
    'beliefs': {},
    'goals': [],
    'uncertainties': [],
    'constraints': [],
    'self_model': {
        'strengths': [],
        'failure_patterns': [],
        'confidence_by_domain': {},
    },
    'updated_at': 0,
}


def _now() -> int:
    return int(time.time())


def _normalize(d: dict[str, Any]) -> dict[str, Any]:
    out = dict(DEFAULT_STATE)
    out.update(d or {})
    if not isinstance(out.get('beliefs'), dict):
        out['beliefs'] = {}
    for k in ('goals', 'uncertainties', 'constraints'):
        if not isinstance(out.get(k), list):
            out[k] = []
    sm = out.get('self_model') if isinstance(out.get('self_model'), dict) else {}
    out['self_model'] = {
        'strengths': sm.get('strengths') if isinstance(sm.get('strengths'), list) else [],
        'failure_patterns': sm.get('failure_patterns') if isinstance(sm.get('failure_patterns'), list) else [],
        'confidence_by_domain': sm.get('confidence_by_domain') if isinstance(sm.get('confidence_by_domain'), dict) else {},
    }
    return out


def get_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return _normalize({})
    try:
        return _normalize(json.loads(STATE_PATH.read_text(encoding='utf-8')))
    except Exception:
        return _normalize({})


def save_state(state: dict[str, Any]) -> dict[str, Any]:
    out = _normalize(state)
    out['updated_at'] = _now()
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    return out


def _append_unique(lst: list[Any], item: Any, limit: int = 40):
    if item in lst:
        return
    lst.append(item)
    if len(lst) > limit:
        del lst[:len(lst)-limit]


def apply_reflexion_signal(*, action: str, confidence: float, hypothesis: str, reason: str, aggregate: dict[str, Any] | None = None):
    st = get_state()
    agg = aggregate if isinstance(aggregate, dict) else {}

    # beliefs about operational behavior
    if hypothesis:
        st['beliefs'][f'reflexion_hypothesis_{_now()}'] = str(hypothesis)[:220]

    # uncertainties from high observed error/outliers
    err = float(agg.get('error_rate') or 0.0)
    outl = float(agg.get('outliers_gt_10s_pct') or 0.0)
    if err >= 0.2:
        _append_unique(st['uncertainties'], 'Taxa de erro elevada em fluxos recentes.')
    if outl >= 0.2:
        _append_unique(st['uncertainties'], 'Latência instável (>10s) em parcela relevante das requisições.')

    # self-model confidence by domain heuristic
    domain = 'general'
    by_cls = agg.get('by_input_class') if isinstance(agg.get('by_input_class'), dict) else {}
    if by_cls:
        domain = sorted(by_cls.items(), key=lambda kv: int((kv[1] or {}).get('n') or 0), reverse=True)[0][0]
    cur_conf = st['self_model']['confidence_by_domain'].get(domain)
    if not isinstance(cur_conf, (int, float)):
        cur_conf = 0.5
    if action != 'none' and confidence >= 0.7:
        cur_conf = min(1.0, float(cur_conf) + 0.03)
    elif err > 0.15:
        cur_conf = max(0.0, float(cur_conf) - 0.05)
    st['self_model']['confidence_by_domain'][domain] = round(float(cur_conf), 4)

    # strengths / failure patterns
    if err < 0.08 and outl < 0.08:
        _append_unique(st['self_model']['strengths'], 'Execução estável sob carga recente.')
    if err >= 0.15:
        _append_unique(st['self_model']['failure_patterns'], 'Erros recorrentes em janelas de avaliação recentes.')

    if reason:
        _append_unique(st['constraints'], f'Constraint observada: {str(reason)[:120]}', limit=30)

    return save_state(st)


def compact_for_prompt(max_chars: int = 900) -> dict[str, Any]:
    s = get_state()
    c = {
        'beliefs': dict(list((s.get('beliefs') or {}).items())[-6:]),
        'goals': (s.get('goals') or [])[-6:],
        'uncertainties': (s.get('uncertainties') or [])[-6:],
        'constraints': (s.get('constraints') or [])[-6:],
        'self_model': {
            'strengths': (s.get('self_model') or {}).get('strengths', [])[-4:],
            'failure_patterns': (s.get('self_model') or {}).get('failure_patterns', [])[-4:],
            'confidence_by_domain': (s.get('self_model') or {}).get('confidence_by_domain', {}),
        },
    }
    raw = json.dumps(c, ensure_ascii=False)
    if len(raw) > int(max_chars or 900):
        c['beliefs'] = dict(list(c['beliefs'].items())[-3:])
        c['constraints'] = c['constraints'][-3:]
        raw = json.dumps(c, ensure_ascii=False)
    c['budget'] = {'actual_chars': len(raw), 'max_chars': int(max_chars or 900)}
    return c
