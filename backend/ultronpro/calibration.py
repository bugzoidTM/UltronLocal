from __future__ import annotations

from pathlib import Path
from typing import Any
import json
import time

from ultronpro import self_model

PATH = Path('/app/data/calibration_state.json')


def _default() -> dict[str, Any]:
    return {
        'updated_at': int(time.time()),
        'runs': [],
        'summary': {
            'count': 0,
            'avg_pred_error': 0.5,
            'avg_actual_error': 0.5,
            'overconfidence_gap': 0.0,
            'brier': 0.25,
        },
    }


def _load() -> dict[str, Any]:
    if PATH.exists():
        try:
            d = json.loads(PATH.read_text(encoding='utf-8'))
            if isinstance(d, dict):
                d.setdefault('runs', [])
                d.setdefault('summary', _default()['summary'])
                return d
        except Exception:
            pass
    return _default()


def _save(d: dict[str, Any]) -> None:
    d['updated_at'] = int(time.time())
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding='utf-8')


def _clip01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def predict_error(strategy: str, task_type: str, budget_profile: str) -> dict[str, Any]:
    # Base prior from causal utility
    scores = self_model.best_strategy_scores(limit=100)
    util = float(scores.get(str(strategy), 0.5))
    pred = 1.0 - util

    # Adjust by empirical overconfidence gap
    st = _load()
    gap = float((st.get('summary') or {}).get('overconfidence_gap') or 0.0)
    pred = _clip01(pred + max(0.0, gap) * 0.5)

    # Deep profile should reduce error for critical tasks slightly
    if str(task_type) == 'critical' and str(budget_profile) == 'deep':
        pred = _clip01(pred - 0.06)
    if str(task_type) in ('heartbeat', 'review') and str(budget_profile) == 'cheap':
        pred = _clip01(pred - 0.03)

    return {
        'ok': True,
        'pred_error': round(pred, 4),
        'pred_confidence': round(1.0 - pred, 4),
        'strategy': strategy,
        'task_type': task_type,
        'budget_profile': budget_profile,
        'overconfidence_gap': round(gap, 4),
    }


def update(pred_error: float, actual_error: int, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    d = _load()
    runs = list(d.get('runs') or [])
    p = _clip01(pred_error)
    a = 1 if int(actual_error) else 0
    item = {
        'ts': int(time.time()),
        'pred_error': p,
        'actual_error': a,
        'meta': meta or {},
        'brier_term': round((p - a) ** 2, 6),
    }
    runs.append(item)
    runs = runs[-2000:]
    d['runs'] = runs

    n = len(runs)
    avg_p = sum(float(x.get('pred_error') or 0.0) for x in runs) / max(1, n)
    avg_a = sum(float(x.get('actual_error') or 0.0) for x in runs) / max(1, n)
    brier = sum(float(x.get('brier_term') or 0.0) for x in runs) / max(1, n)
    d['summary'] = {
        'count': n,
        'avg_pred_error': round(avg_p, 4),
        'avg_actual_error': round(avg_a, 4),
        'overconfidence_gap': round(avg_a - avg_p, 4),
        'brier': round(brier, 4),
    }
    _save(d)
    return {'ok': True, 'summary': d['summary']}


def status(limit: int = 40) -> dict[str, Any]:
    d = _load()
    return {'ok': True, 'summary': d.get('summary') or {}, 'recent': (d.get('runs') or [])[-max(1, int(limit)):], 'path': str(PATH)}
