import time
from pathlib import Path
from typing import Any
import json


STATE_PATH = Path(__file__).resolve().parent.parent / 'data' / 'agi_path_state.json'


def _default() -> dict[str, Any]:
    now = int(time.time())
    return {
        'enabled': True,
        'auto_tick_sec': 600,
        'target_agi_percent': 90.0,
        'last_tick_at': 0,
        'last_reason': 'init',
        'gaps': {},
        'actions': [],
        'history': [{'ts': now, 'event': 'init', 'note': 'agi path initialized'}],
    }


def _load() -> dict[str, Any]:
    try:
        if STATE_PATH.exists():
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


def _save(d: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding='utf-8')


def status() -> dict[str, Any]:
    s = _load()
    s['path'] = str(STATE_PATH)
    return s


def config_patch(patch: dict[str, Any]) -> dict[str, Any]:
    s = _load()
    for k in ['enabled', 'auto_tick_sec', 'target_agi_percent']:
        if k in (patch or {}):
            s[k] = patch[k]
    _save(s)
    return status()


def _score_gaps(snapshot: dict[str, Any], target_agi_percent: float) -> tuple[dict[str, float], list[str]]:
    agi = (snapshot or {}).get('agi') or {}
    pillars = agi.get('pillars') or {}
    inputs = agi.get('inputs') or {}
    plast = (snapshot or {}).get('plasticity') or {}
    agi_pct = float(agi.get('agi_mode_percent') or 0.0)
    learning = float(pillars.get('learning') or 0.0)
    adaptation = float(pillars.get('adaptation') or 0.0)
    autonomy = float(pillars.get('autonomy') or 0.0)
    grounding = float(pillars.get('grounding') or 0.0)
    critique = float(agi.get('self_critique') or 0.0)
    memory = float(agi.get('memory_discipline') or 0.0)

    halluc = float(plast.get('hallucination_rate') or 1.0)
    actions_done = int(inputs.get('actions_done_recent') or 0)

    gaps = {
        'agi_target_gap': round(max(0.0, float(target_agi_percent) - agi_pct), 2),
        'learning_gap': round(max(0.0, 80.0 - learning), 2),
        'adaptation_gap': round(max(0.0, 75.0 - adaptation), 2),
        'autonomy_gap': round(max(0.0, 75.0 - autonomy), 2),
        'grounding_gap': round(max(0.0, 82.0 - grounding), 2),
        'critique_gap': round(max(0.0, 78.0 - critique), 2),
        'memory_gap': round(max(0.0, 78.0 - memory), 2),
        'hallucination_excess': round(max(0.0, halluc - 0.12), 4),
        'execution_gap': max(0, 60 - actions_done),
    }

    actions: list[str] = []
    if gaps['hallucination_excess'] > 0:
        actions.append('tighten_grounding_and_feedback')
    if gaps['critique_gap'] > 0:
        actions.append('strengthen_internal_critique')
    if gaps['memory_gap'] > 0:
        actions.append('discipline_memory_writeback')
    if gaps['execution_gap'] > 0:
        actions.append('raise_safe_autonomy_throughput')
    if gaps['grounding_gap'] > 0:
        actions.append('prioritize_grounding_tasks')
    if gaps['agi_target_gap'] <= 8.0:
        actions.append('approaching_agi_like_zone')

    return gaps, actions


def tick(snapshot: dict[str, Any]) -> dict[str, Any]:
    s = _load()
    now = int(time.time())
    s['last_tick_at'] = now

    if not bool(s.get('enabled')):
        s['last_reason'] = 'disabled'
        _save(s)
        return {'ok': True, 'triggered': False, 'reason': 'disabled', 'state': status()}

    gaps, actions = _score_gaps(snapshot, float(s.get('target_agi_percent') or 90.0))
    s['gaps'] = gaps
    s['actions'] = actions

    triggered = False
    trigger_out = None

    if 'strengthen_internal_critique' in actions or 'discipline_memory_writeback' in actions:
        s['last_reason'] = 'cognitive_hardening_needed'
    else:
        s['last_reason'] = 'monitor_only'

    s['history'] = (s.get('history') or [])[-149:] + [{
        'ts': now,
        'event': 'tick',
        'triggered': triggered,
        'gaps': gaps,
        'actions': actions,
        'reason': s.get('last_reason'),
    }]
    _save(s)
    return {'ok': True, 'triggered': triggered, 'actions': actions, 'gaps': gaps, 'trigger_out': trigger_out, 'state': status()}
