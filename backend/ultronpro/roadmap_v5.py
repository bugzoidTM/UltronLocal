import time
from pathlib import Path
from typing import Any


STATE_PATH = Path(__file__).resolve().parent.parent / 'data' / 'roadmap_v5_state.json'


def _default() -> dict[str, Any]:
    now = int(time.time())
    return {
        'enabled': True,
        'phase': 1,
        'phase_name': 'Fase 1 — Confiabilidade Cognitiva',
        'auto_tick_sec': 300,
        'rest_until_ts': 0,
        'last_tick_at': 0,
        'last_reason': 'init',
        'history': [
            {'ts': now, 'event': 'init', 'phase': 1, 'note': 'roadmap v5 orchestrator initialized'}
        ],
    }


def _load() -> dict[str, Any]:
    try:
        if STATE_PATH.exists():
            import json
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
    import json
    STATE_PATH.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding='utf-8')


def status() -> dict[str, Any]:
    s = _load()
    s['path'] = str(STATE_PATH)
    return s


def config_patch(patch: dict[str, Any]) -> dict[str, Any]:
    s = _load()
    for k in ['enabled', 'auto_tick_sec', 'rest_until_ts']:
        if k in (patch or {}):
            s[k] = patch[k]
    _save(s)
    return status()


def set_rest(hours: int) -> dict[str, Any]:
    s = _load()
    s['rest_until_ts'] = int(time.time()) + max(0, int(hours)) * 3600
    s['last_reason'] = f'rest_{hours}h'
    s['history'] = (s.get('history') or [])[-99:] + [{'ts': int(time.time()), 'event': 'rest_set', 'hours': int(hours)}]
    _save(s)
    return status()


def _phase_name(p: int) -> str:
    return {
        1: 'Fase 1 — Confiabilidade Cognitiva',
        2: 'Fase 2 — Memória e Crítica Interna',
        3: 'Fase 3 — Agência de Longo Horizonte',
        4: 'Fase 4 — Meta-Raciocínio e Generalização',
    }.get(int(p), 'Fase desconhecida')


def _advance(s: dict[str, Any], to_phase: int, note: str) -> None:
    s['phase'] = int(to_phase)
    s['phase_name'] = _phase_name(int(to_phase))
    s['history'] = (s.get('history') or [])[-99:] + [{'ts': int(time.time()), 'event': 'phase_advance', 'phase': int(to_phase), 'note': note}]


def tick(snapshot: dict[str, Any]) -> dict[str, Any]:
    s = _load()
    now = int(time.time())
    s['last_tick_at'] = now

    if not bool(s.get('enabled')):
        s['last_reason'] = 'disabled'
        _save(s)
        return {'ok': True, 'triggered': False, 'reason': 'disabled', 'state': status()}

    if now < int(s.get('rest_until_ts') or 0):
        s['last_reason'] = 'rest_window'
        _save(s)
        return {'ok': True, 'triggered': False, 'reason': 'rest_window', 'state': status()}

    agi = (snapshot or {}).get('agi') or {}
    pillars = agi.get('pillars') or {}
    inputs = agi.get('inputs') or {}
    plast = (snapshot or {}).get('plasticity') or {}
    phase = int(s.get('phase') or 1)

    # Fase 1 -> Fase 2
    if phase == 1:
        if float(pillars.get('learning') or 0.0) >= 70.0 and float(plast.get('hallucination_rate') or 1.0) <= 0.20:
            _advance(s, 2, 'criteria_met_phase1')
            s['last_reason'] = 'advanced_phase_2'
            _save(s)
            return {'ok': True, 'triggered': True, 'action': 'phase_advance', 'state': status()}

    # Fase 2: consolidar memória, grounding e crítica interna
    if phase == 2:
        context_fitness = float(agi.get('context_fitness') or pillars.get('grounding') or 0.0)
        if context_fitness >= 78.0 and float(plast.get('hallucination_rate') or 1.0) <= 0.15:
            _advance(s, 3, 'phase2_cognitive_stability')
            s['last_reason'] = 'advanced_phase_3'
            _save(s)
            return {'ok': True, 'triggered': True, 'action': 'phase_advance', 'state': status()}

        s['last_reason'] = 'phase2_wait_cognitive_stability'
        _save(s)
        return {'ok': True, 'triggered': False, 'action': 'phase2_cognitive_hardening', 'state': status()}

    # Fase 3 -> Fase 4
    if phase == 3:
        # modo acelerado: transição mais responsiva mantendo dois sinais (execução + maturidade AGI)
        if int(inputs.get('actions_done_recent') or 0) >= 45 and float(agi.get('agi_mode_percent') or 0.0) >= 70.0:
            _advance(s, 4, 'phase3_execution_stable_accelerated')
            s['last_reason'] = 'advanced_phase_4'
            _save(s)
            return {'ok': True, 'triggered': True, 'action': 'phase_advance', 'state': status()}

    s['last_reason'] = 'no_transition'
    _save(s)
    return {'ok': True, 'triggered': False, 'reason': 'no_transition', 'state': status()}
