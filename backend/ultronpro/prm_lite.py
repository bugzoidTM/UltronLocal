from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

STATE_PATH = Path('/app/data/prm_lite_state.json')
MAX_RECENT = 500

DEFAULT_WEIGHTS = {
    'groundedness': 0.24,
    'uncertainty_honesty': 0.14,
    'instruction_following': 0.16,
    'safety_compliance': 0.18,
    'repetition_echo_penalty': 0.10,
    'hallucination_risk_penalty': 0.18,
}

DEFAULT_THRESHOLDS = {
    'low': 0.72,
    'medium': 0.50,
}


def _now() -> int:
    return int(time.time())


def _load() -> dict[str, Any]:
    if STATE_PATH.exists():
        try:
            d = json.loads(STATE_PATH.read_text(encoding='utf-8'))
            if isinstance(d, dict):
                d.setdefault('weights', dict(DEFAULT_WEIGHTS))
                d.setdefault('thresholds', dict(DEFAULT_THRESHOLDS))
                d.setdefault('recent', [])
                d.setdefault('stats', {'count': 0, 'avg_score': 0.0, 'by_risk': {'low': 0, 'medium': 0, 'high': 0}})
                return d
        except Exception:
            pass
    return {
        'weights': dict(DEFAULT_WEIGHTS),
        'thresholds': dict(DEFAULT_THRESHOLDS),
        'recent': [],
        'stats': {'count': 0, 'avg_score': 0.0, 'by_risk': {'low': 0, 'medium': 0, 'high': 0}},
        'mode': 'observation',
        'updated_at': _now(),
    }


def _save(d: dict[str, Any]):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    d['updated_at'] = _now()
    STATE_PATH.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding='utf-8')


def _token_set(s: str) -> set[str]:
    return {t for t in re.findall(r"[a-zA-ZÀ-ÿ0-9_]{4,}", (s or '').lower())}


def score_answer(question: str, answer: str, context: str = '', meta: dict[str, Any] | None = None) -> dict[str, Any]:
    q = str(question or '')
    a = str(answer or '')
    c = str(context or '')
    meta = meta or {}

    q_tokens = _token_set(q)
    a_tokens = _token_set(a)
    c_tokens = _token_set(c)

    inter_q_a = len(q_tokens.intersection(a_tokens)) / max(1, len(q_tokens))
    inter_c_a = len(c_tokens.intersection(a_tokens)) / max(1, len(c_tokens)) if c_tokens else 0.0

    groundedness = min(1.0, max(0.0, (inter_c_a * 1.2) if c_tokens else (0.35 + inter_q_a * 0.4)))
    uncertainty_honesty = 1.0 if any(x in a.lower() for x in ['não tenho informação confiável', 'não tenho certeza', 'dados insuficientes', 'incerteza']) else 0.45
    instruction_following = 1.0 if (len(a.strip()) >= 24 and not a.strip().startswith('{')) else 0.35
    safety_compliance = 1.0 if not any(x in a.lower() for x in ['senha é', 'cpf é', 'token é']) else 0.0

    repetition_echo_penalty = 1.0 if (q_tokens and a_tokens and (len(q_tokens.intersection(a_tokens))/max(1, len(a_tokens))) > 0.85) else 0.0
    hallucination_risk_penalty = 1.0 if (meta.get('strategy') == 'insufficient_confidence') else 0.0

    st = _load()
    w = st.get('weights') or DEFAULT_WEIGHTS

    raw = (
        float(w.get('groundedness', 0.24)) * groundedness
        + float(w.get('uncertainty_honesty', 0.14)) * uncertainty_honesty
        + float(w.get('instruction_following', 0.16)) * instruction_following
        + float(w.get('safety_compliance', 0.18)) * safety_compliance
        - float(w.get('repetition_echo_penalty', 0.10)) * repetition_echo_penalty
        - float(w.get('hallucination_risk_penalty', 0.18)) * (0.0 if hallucination_risk_penalty else 0.35)
    )
    score = max(0.0, min(1.0, raw))

    thr = st.get('thresholds') or DEFAULT_THRESHOLDS
    if score >= float(thr.get('low', 0.72)):
        risk = 'low'
    elif score >= float(thr.get('medium', 0.50)):
        risk = 'medium'
    else:
        risk = 'high'

    reasons = []
    if groundedness >= 0.6:
        reasons.append('good_grounding')
    if uncertainty_honesty >= 0.9:
        reasons.append('honest_uncertainty')
    if repetition_echo_penalty > 0:
        reasons.append('echo_risk')
    if safety_compliance < 0.5:
        reasons.append('safety_risk')

    return {
        'score': round(score, 4),
        'risk': risk,
        'reasons': reasons,
        'features': {
            'groundedness': round(groundedness, 4),
            'uncertainty_honesty': round(uncertainty_honesty, 4),
            'instruction_following': round(instruction_following, 4),
            'safety_compliance': round(safety_compliance, 4),
            'repetition_echo_penalty': round(repetition_echo_penalty, 4),
            'hallucination_risk_penalty': round(hallucination_risk_penalty, 4),
        },
        'mode': 'observation',
    }


def record(question: str, answer: str, strategy: str, result: dict[str, Any]):
    st = _load()
    rec = {
        'ts': _now(),
        'question': str(question or '')[:400],
        'answer': str(answer or '')[:1200],
        'strategy': str(strategy or ''),
        'score': float(result.get('score') or 0.0),
        'risk': str(result.get('risk') or 'medium'),
        'reasons': list(result.get('reasons') or []),
    }

    arr = list(st.get('recent') or [])
    arr.append(rec)
    arr = arr[-MAX_RECENT:]
    st['recent'] = arr

    stats = st.get('stats') or {'count': 0, 'avg_score': 0.0, 'by_risk': {'low': 0, 'medium': 0, 'high': 0}}
    n = int(stats.get('count') or 0) + 1
    avg = float(stats.get('avg_score') or 0.0)
    new_avg = ((avg * (n - 1)) + float(rec['score'])) / max(1, n)
    by = dict(stats.get('by_risk') or {'low': 0, 'medium': 0, 'high': 0})
    rk = rec['risk'] if rec['risk'] in ('low', 'medium', 'high') else 'medium'
    by[rk] = int(by.get(rk) or 0) + 1

    st['stats'] = {'count': n, 'avg_score': round(new_avg, 6), 'by_risk': by}
    _save(st)


def status() -> dict[str, Any]:
    st = _load()
    return {
        'ok': True,
        'mode': str(st.get('mode') or 'observation'),
        'weights': st.get('weights') or {},
        'thresholds': st.get('thresholds') or {},
        'stats': st.get('stats') or {},
        'recent_count': len(st.get('recent') or []),
        'updated_at': st.get('updated_at'),
    }


def recent(limit: int = 20) -> list[dict[str, Any]]:
    st = _load()
    arr = list(st.get('recent') or [])
    return arr[-max(1, int(limit or 20)):]