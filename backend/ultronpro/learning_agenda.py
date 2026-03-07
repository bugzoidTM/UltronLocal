import json
import time
from pathlib import Path
from typing import Any

STATE_PATH = Path('/app/data/learning_agenda.json')


def _default() -> dict[str, Any]:
    now = int(time.time())
    return {
        'enabled': True,
        'exploration_budget_ratio': 0.2,
        'min_gap_to_trigger': 0.25,
        'domains': [
            {'name': 'distributed-systems', 'target_depth': 120, 'weight': 1.0},
            {'name': 'security', 'target_depth': 100, 'weight': 1.0},
            {'name': 'economics', 'target_depth': 90, 'weight': 0.9},
            {'name': 'law-tech', 'target_depth': 80, 'weight': 0.8},
            {'name': 'science-method', 'target_depth': 90, 'weight': 0.9},
        ],
        'last_tick_at': 0,
        'history': [{'ts': now, 'event': 'init'}],
    }


def _load() -> dict[str, Any]:
    if STATE_PATH.exists():
        try:
            d = json.loads(STATE_PATH.read_text(encoding='utf-8'))
            if isinstance(d, dict):
                base = _default()
                for k, v in base.items():
                    d.setdefault(k, v)
                return d
        except Exception:
            pass
    d = _default()
    _save(d)
    return d


def _save(d: dict[str, Any]):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding='utf-8')


def status() -> dict[str, Any]:
    s = _load()
    s['path'] = str(STATE_PATH)
    return s


def config_patch(patch: dict[str, Any]) -> dict[str, Any]:
    s = _load()
    for k in ['enabled', 'exploration_budget_ratio', 'min_gap_to_trigger']:
        if k in patch:
            s[k] = patch[k]
    if 'domains' in patch and isinstance(patch.get('domains'), list):
        s['domains'] = patch['domains']
    _save(s)
    return status()


def _coverage_from_plasticity(plasticity_status: dict[str, Any]) -> dict[str, float]:
    # lightweight proxy: use signals available now
    labels = (plasticity_status.get('labels') or {}) if isinstance(plasticity_status, dict) else {}
    total = float(sum(int(v or 0) for v in labels.values()) or 1)
    # synthetic baseline by domain from total data volume
    base = min(1.0, total / 500.0)
    return {
        'distributed-systems': round(base * 0.9, 4),
        'security': round(base * 0.75, 4),
        'economics': round(base * 0.6, 4),
        'law-tech': round(base * 0.45, 4),
        'science-method': round(base * 0.7, 4),
    }


def tick(plasticity_status: dict[str, Any]) -> dict[str, Any]:
    s = _load()
    now = int(time.time())
    s['last_tick_at'] = now
    if not bool(s.get('enabled')):
        _save(s)
        return {'ok': True, 'triggered': False, 'reason': 'disabled', 'state': s}

    cov = _coverage_from_plasticity(plasticity_status or {})
    domains = s.get('domains') or []
    scored = []
    for d in domains:
        name = str(d.get('name') or '')
        tgt = max(1.0, float(d.get('target_depth') or 100.0))
        w = float(d.get('weight') or 1.0)
        c = float(cov.get(name) or 0.0)
        gap = max(0.0, 1.0 - c)
        pr = round(gap * w, 4)
        scored.append({'domain': name, 'coverage': c, 'gap': round(gap, 4), 'priority': pr})

    scored.sort(key=lambda x: x['priority'], reverse=True)
    top = scored[0] if scored else None
    trigger = bool(top and top['gap'] >= float(s.get('min_gap_to_trigger') or 0.25))

    row = {'ts': now, 'event': 'tick', 'top': top, 'trigger': trigger}
    s['history'] = (s.get('history') or [])[-199:] + [row]
    _save(s)
    return {'ok': True, 'triggered': trigger, 'top': top, 'rank': scored[:5], 'state': s}
