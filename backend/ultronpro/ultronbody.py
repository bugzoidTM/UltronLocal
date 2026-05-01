from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from ultronpro import causal_graph

BODY_ROOT = Path(__file__).resolve().parent.parent / 'data' / 'ultronbody'
STATE_PATH = BODY_ROOT / 'state.json'
EPISODES_PATH = BODY_ROOT / 'episodes.jsonl'
BENCHMARKS_PATH = BODY_ROOT / 'benchmarks.jsonl'

_GRID = 5
_MAX_STEPS = 30
_ENV_LIBRARY: dict[str, dict[str, Any]] = {
    'gridworld_v1': {
        'goal': [_GRID - 1, _GRID - 1],
        'trap': [2, 2],
        'resource': [1, 3],
        'start': [0, 0],
    },
    'gridworld_risky': {
        'goal': [_GRID - 1, _GRID - 1],
        'trap': [2, 0],
        'resource': [0, 4],
        'start': [0, 0],
    },
    'gridworld_detour': {
        'goal': [_GRID - 1, _GRID - 1],
        'trap': [4, 2],
        'resource': [4, 0],
        'start': [0, 0],
    },
}

_EFFECT_ONTOLOGY = {
    'move_north': 'mudar_posicao',
    'move_south': 'mudar_posicao',
    'move_west': 'mudar_posicao',
    'move_east': 'mudar_posicao',
    'gather': 'coletar_recurso',
    'wait': 'manter_estado',
    'noop': 'manter_estado',
    'nada_coletado': 'nada_coletado',
    'acao_desconhecida': 'acao_desconhecida',
}


def _now() -> int:
    return int(time.time())


def _ensure_parent(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)


def _env_config(env_name: str | None) -> dict[str, Any]:
    name = str(env_name or 'gridworld_v1').strip().lower()
    cfg = _ENV_LIBRARY.get(name) or _ENV_LIBRARY['gridworld_v1']
    return {
        'env_name': name if name in _ENV_LIBRARY else 'gridworld_v1',
        'goal': list(cfg.get('goal') or [_GRID - 1, _GRID - 1]),
        'trap': list(cfg.get('trap') or [2, 2]),
        'resource': list(cfg.get('resource') or [1, 3]),
        'start': list(cfg.get('start') or [0, 0]),
    }


def _default_env(env_name: str = 'gridworld_v1') -> dict[str, Any]:
    episode_id = f"ep_{uuid.uuid4().hex[:10]}"
    cfg = _env_config(env_name)
    return {
        'episode_id': episode_id,
        'env_name': cfg['env_name'],
        'step': 0,
        'position': list(cfg['start']),
        'inventory': {'resource': 0},
        'goal': list(cfg['goal']),
        'trap': list(cfg['trap']),
        'resource': list(cfg['resource']),
        'total_reward': 0.0,
        'done': False,
        'last_outcome': None,
        'started_at': _now(),
        'updated_at': _now(),
        'steps': [],
    }


def _load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return _default_env()
    try:
        data = json.loads(STATE_PATH.read_text(encoding='utf-8'))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return _default_env()


def _save_state(state: dict[str, Any]) -> dict[str, Any]:
    state = dict(state or {})
    state['updated_at'] = _now()
    _ensure_parent(STATE_PATH)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
    return state


def _append_episode(row: dict[str, Any]):
    _ensure_parent(EPISODES_PATH)
    with EPISODES_PATH.open('a', encoding='utf-8') as f:
        f.write(json.dumps(row, ensure_ascii=False) + '\n')


def _state_summary(state: dict[str, Any]) -> str:
    pos = state.get('position') or [0, 0]
    inv = (state.get('inventory') or {}).get('resource') or 0
    goal = state.get('goal') or [_GRID - 1, _GRID - 1]
    trap = state.get('trap') or [2, 2]
    parts = [f"ambiente={state.get('env_name')}", f"posição={pos}", f"recursos={inv}", f"objetivo={goal}"]
    if pos == trap:
        parts.append('em perigo')
    if pos == goal:
        parts.append('objetivo alcançado')
    return ' | '.join(parts)


def _available_actions(state: dict[str, Any]) -> list[str]:
    if bool(state.get('done')):
        return ['reset']
    return ['move_north', 'move_south', 'move_west', 'move_east', 'gather', 'wait']


def _observation_text(state: dict[str, Any]) -> str:
    x, y = state.get('position') or [0, 0]
    lines = [f"Você está em ({x}, {y}) de um grid {_GRID}x{_GRID} no ambiente {state.get('env_name')}." ]
    if [x, y] == list(state.get('goal') or [_GRID - 1, _GRID - 1]):
        lines.append('Você alcançou o objetivo.')
    else:
        gx, gy = state.get('goal') or [_GRID - 1, _GRID - 1]
        lines.append(f"O objetivo está em ({gx}, {gy}).")
    if [x, y] == list(state.get('resource') or [1, 3]) and int(((state.get('inventory') or {}).get('resource') or 0)) == 0:
        lines.append('Há um recurso coletável aqui.')
    if [x, y] == list(state.get('trap') or [2, 2]):
        lines.append('Você entrou numa área perigosa.')
    lines.append(f"Ações disponíveis: {', '.join(_available_actions(state))}.")
    return ' '.join(lines)


def observe() -> dict[str, Any]:
    state = _load_state()
    return {
        'ok': True,
        'episode_id': state.get('episode_id'),
        'env_name': state.get('env_name'),
        'step': int(state.get('step') or 0),
        'observation': {
            'text': _observation_text(state),
            'structured': {
                'position': state.get('position') or [0, 0],
                'inventory': state.get('inventory') or {},
                'goal': state.get('goal') or [_GRID - 1, _GRID - 1],
                'trap': state.get('trap') or [2, 2],
                'resource': state.get('resource') or [1, 3],
                'done': bool(state.get('done')),
                'last_outcome': state.get('last_outcome'),
            },
        },
        'available_actions': _available_actions(state),
        'reward': float((state.get('last_outcome') or {}).get('reward') or 0.0),
        'done': bool(state.get('done')),
        'state_summary': _state_summary(state),
    }


def reset(env_name: str = 'gridworld_v1') -> dict[str, Any]:
    state = _default_env(env_name)
    _save_state(state)
    return {'ok': True, 'status': 'reset', **observe()}


def _clip_position(pos: list[int]) -> list[int]:
    x = max(0, min(_GRID - 1, int(pos[0])))
    y = max(0, min(_GRID - 1, int(pos[1])))
    return [x, y]


def _canonical_effect(value: str | None) -> str:
    raw = str(value or '').strip().lower()
    if not raw:
        return 'acao_desconhecida'
    if raw in _EFFECT_ONTOLOGY:
        return _EFFECT_ONTOLOGY[raw]
    if raw.startswith('move_'):
        return 'mudar_posicao'
    if raw in ('gather', 'coletar', 'coletar_recurso'):
        return 'coletar_recurso'
    if raw in ('wait', 'noop', 'manter_estado'):
        return 'manter_estado'
    return raw


def _expected_effect_for(action: str, state: dict[str, Any]) -> str:
    return _canonical_effect(action)


def _classify_outcome(expected_effect: str, observed_effect: str) -> str:
    if expected_effect == observed_effect:
        return 'confirmed'
    if expected_effect == 'coletar_recurso' and observed_effect == 'nada_coletado':
        return 'refuted'
    return 'unexpected'


def _transition_risk_payload(state: dict[str, Any], action: str, next_pos: list[int]) -> dict[str, Any]:
    pos = list(state.get('position') or [0, 0])
    raw = causal_graph.evaluate_step_risk(
        query=(
            f"env={state.get('env_name')} action={action} position={pos} "
            f"next={next_pos} goal={state.get('goal')} resource={state.get('resource')} "
            f"trap={state.get('trap')} inventory_resource={int(((state.get('inventory') or {}).get('resource') or 0))}"
        ),
        step={'tool': action, 'args': {'position': pos, 'next_position': next_pos, 'env': state.get('env_name')}},
    )
    activated = raw.get('activated_edges') if isinstance(raw.get('activated_edges'), list) else []
    salient = [e for e in activated if int((e or {}).get('severity') or 1) >= 2]
    risk_score = round(sum(float((e or {}).get('contribution') or 0.0) for e in salient), 4)
    return {
        'ok': True,
        'risk_score': risk_score,
        'activated_edges': salient[:20],
        'vetoes': raw.get('vetoes') if isinstance(raw.get('vetoes'), list) else [],
        'warnings': raw.get('warnings') if isinstance(raw.get('warnings'), list) else [],
        'raw_risk_score': float(raw.get('risk_score') or 0.0),
    }


def act(action: str, expected_effect: str | None = None) -> dict[str, Any]:
    state = _load_state()
    if bool(state.get('done')):
        return {'ok': False, 'error': 'episode_done', 'episode_id': state.get('episode_id')}

    action = str(action or '').strip().lower()
    if action not in _available_actions(state):
        return {'ok': False, 'error': 'invalid_action', 'available_actions': _available_actions(state)}

    before = {
        'position': list(state.get('position') or [0, 0]),
        'inventory': dict(state.get('inventory') or {}),
        'step': int(state.get('step') or 0),
        'env_name': state.get('env_name'),
        'goal': list(state.get('goal') or [_GRID - 1, _GRID - 1]),
        'trap': list(state.get('trap') or [2, 2]),
        'resource': list(state.get('resource') or [1, 3]),
    }
    expected = _canonical_effect(expected_effect or _expected_effect_for(action, state))
    pos = list(before['position'])
    reward = -0.01
    observed_effect = 'manter_estado'
    events: list[str] = []

    if action == 'move_north':
        pos[1] -= 1
        observed_effect = 'mudar_posicao'
    elif action == 'move_south':
        pos[1] += 1
        observed_effect = 'mudar_posicao'
    elif action == 'move_west':
        pos[0] -= 1
        observed_effect = 'mudar_posicao'
    elif action == 'move_east':
        pos[0] += 1
        observed_effect = 'mudar_posicao'
    elif action == 'gather':
        if pos == list(state.get('resource') or [1, 3]) and int(((state.get('inventory') or {}).get('resource') or 0)) == 0:
            inv = dict(state.get('inventory') or {})
            inv['resource'] = int(inv.get('resource') or 0) + 1
            state['inventory'] = inv
            reward += 0.3
            observed_effect = 'coletar_recurso'
            events.append('resource_gathered')
        else:
            reward -= 0.05
            observed_effect = 'nada_coletado'
    elif action == 'wait':
        observed_effect = 'manter_estado'

    pos = _clip_position(pos)
    state['position'] = pos
    state['step'] = int(state.get('step') or 0) + 1

    if pos == list(state.get('trap') or [2, 2]):
        reward -= 1.0
        events.append('trap')
        state['done'] = True
    elif pos == list(state.get('goal') or [_GRID - 1, _GRID - 1]):
        reward += 1.0
        events.append('goal_reached')
        state['done'] = True
    elif int(state.get('step') or 0) >= _MAX_STEPS:
        events.append('max_steps')
        state['done'] = True

    total_reward = float(state.get('total_reward') or 0.0) + reward
    state['total_reward'] = round(total_reward, 4)
    observed_effect = _canonical_effect(observed_effect)
    surprise_score = round(0.0 if expected == observed_effect else 1.0, 4)
    risk_eval = _transition_risk_payload(state=before, action=action, next_pos=pos)
    step_row = {
        'ts': _now(),
        'episode_id': state.get('episode_id'),
        'env_name': state.get('env_name'),
        'step': int(state.get('step') or 0),
        'state_before': before,
        'action': action,
        'expected_effect': expected,
        'observed_effect': observed_effect,
        'surprise_score': surprise_score,
        'cost': 1,
        'reward': round(reward, 4),
        'done': bool(state.get('done')),
        'events': events,
        'risk': risk_eval,
        'state_after': {
            'position': list(state.get('position') or [0, 0]),
            'inventory': dict(state.get('inventory') or {}),
            'total_reward': state.get('total_reward') or 0.0,
        },
    }
    counterfactual = None
    try:
        cf = choose_action({
            'env_name': state.get('env_name'),
            'position': list(before.get('position') or [0, 0]),
            'inventory': dict(before.get('inventory') or {}),
            'goal': list(state.get('goal') or [_GRID - 1, _GRID - 1]),
            'trap': list(state.get('trap') or [2, 2]),
            'resource': list(state.get('resource') or [1, 3]),
            'done': False,
        }, policy='causal_safe')
        candidates = cf.get('candidates') if isinstance(cf.get('candidates'), list) else []
        alternatives = [c for c in candidates if str((c or {}).get('action') or '') != action]
        best_alternative = sorted(alternatives, key=lambda x: float((x or {}).get('utility_score') or -999.0), reverse=True)[0] if alternatives else None
        if best_alternative:
            counterfactual = {
                'best_alternative_action': best_alternative.get('action'),
                'predicted_reward': best_alternative.get('predicted_reward'),
                'utility_score': best_alternative.get('utility_score'),
                'risk_score': ((best_alternative.get('risk') or {}).get('risk_score') if isinstance(best_alternative.get('risk'), dict) else 0.0),
            }
    except Exception:
        counterfactual = None

    step_row['counterfactual'] = counterfactual
    state['steps'] = list(state.get('steps') or []) + [step_row]
    state['last_outcome'] = {
        'action': action,
        'reward': round(reward, 4),
        'observed_effect': observed_effect,
        'events': events,
        'surprise_score': surprise_score,
        'risk_score': float(risk_eval.get('risk_score') or 0.0),
    }
    _save_state(state)

    base_condition = f"env={state.get('env_name')} next={pos}"
    delta = causal_graph.apply_delta_update(
        cause=action,
        effect=observed_effect,
        condition=base_condition,
        category=_classify_outcome(expected, observed_effect),
        evidence={
            'episode_id': state.get('episode_id'),
            'step': state.get('step'),
            'env_name': state.get('env_name'),
            'position_before': before.get('position'),
            'position_after': pos,
            'reward': round(reward, 4),
            'surprise_score': surprise_score,
            'risk_score': float(risk_eval.get('risk_score') or 0.0),
            'events': events,
        },
        source='ultronbody',
    )
    event_updates = []
    for event_name in events:
        event_updates.append(causal_graph.apply_delta_update(
            cause=action,
            effect=str(event_name),
            condition=base_condition,
            category='unexpected' if event_name in ('trap', 'goal_reached', 'resource_gathered') else 'confirmed',
            evidence={
                'episode_id': state.get('episode_id'),
                'step': state.get('step'),
                'env_name': state.get('env_name'),
                'position_before': before.get('position'),
                'position_after': pos,
                'reward': round(reward, 4),
                'observed_effect': observed_effect,
            },
            source='ultronbody_event',
        ))

    if bool(state.get('done')):
        _append_episode({
            'ts': _now(),
            'episode_id': state.get('episode_id'),
            'env_name': state.get('env_name'),
            'goal': list(state.get('goal') or [_GRID - 1, _GRID - 1]),
            'trap': list(state.get('trap') or [2, 2]),
            'resource': list(state.get('resource') or [1, 3]),
            'steps': state.get('steps') or [],
            'total_reward': state.get('total_reward') or 0.0,
            'done_reason': events[-1] if events else 'done',
        })

    return {
        'ok': True,
        'episode_id': state.get('episode_id'),
        'env_name': state.get('env_name'),
        'step': state.get('step'),
        'reward': round(reward, 4),
        'done': bool(state.get('done')),
        'state_summary': _state_summary(state),
        'transition': step_row,
        'causal_update': delta,
        'event_causal_updates': event_updates,
        'available_actions': _available_actions(state),
    }


def _load_episode_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if EPISODES_PATH.exists():
        for line in EPISODES_PATH.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
                if isinstance(item, dict):
                    rows.append(item)
            except Exception:
                continue
    return rows


def _episode_summary(row: dict[str, Any]) -> dict[str, Any]:
    steps = row.get('steps') if isinstance(row.get('steps'), list) else []
    total_reward = float(row.get('total_reward') or 0.0)
    surprises = [float((s or {}).get('surprise_score') or 0.0) for s in steps if isinstance(s, dict)]
    actions = [str((s or {}).get('action') or '') for s in steps if isinstance(s, dict)]
    avg_risk = round(sum(float(((s or {}).get('risk') or {}).get('risk_score') or 0.0) for s in steps if isinstance(s, dict)) / max(1, len(steps)), 4)
    return {
        'episode_id': row.get('episode_id'),
        'env_name': row.get('env_name'),
        'steps': len(steps),
        'total_reward': round(total_reward, 4),
        'done_reason': row.get('done_reason'),
        'avg_surprise': round(sum(surprises) / max(1, len(surprises)), 4),
        'avg_risk': avg_risk,
        'actions': actions,
        'started_at': row.get('ts'),
    }


def episodes(limit: int = 20, include_steps: bool = True) -> dict[str, Any]:
    rows = _load_episode_rows()
    rows = rows[-max(1, min(200, int(limit or 20))):]
    items = rows if include_steps else [_episode_summary(x) for x in rows]
    return {'ok': True, 'items': items, 'count': len(items), 'path': str(EPISODES_PATH)}


def get_episode(episode_id: str) -> dict[str, Any] | None:
    eid = str(episode_id or '').strip()
    if not eid:
        return None
    for row in reversed(_load_episode_rows()):
        if str(row.get('episode_id') or '') == eid:
            return row
    return None


def _likely_failure_cause(step: dict[str, Any]) -> str:
    events = [str(x) for x in (step.get('events') or []) if str(x)]
    observed = str(step.get('observed_effect') or '')
    reward = float(step.get('reward') or 0.0)
    if 'trap' in events:
        return 'entrou_em_area_de_risco'
    if 'max_steps' in events:
        return 'plano_ineficiente_ou_lento'
    if observed == 'nada_coletado':
        return 'acao_sem_precondicoes'
    if float(step.get('surprise_score') or 0.0) > 0.0:
        return 'hipotese_causal_incorreta'
    if reward < 0:
        return 'acao_de_baixo_valor'
    return 'nenhuma_falha_relevante'


def analyze_counterfactual(episode_id: str, step_number: int | None = None) -> dict[str, Any] | None:
    row = get_episode(episode_id)
    if not row:
        return None
    steps = row.get('steps') if isinstance(row.get('steps'), list) else []
    if not steps:
        return {'ok': True, 'episode_id': episode_id, 'comparisons': [], 'summary': {'count': 0}}

    selected_steps = steps
    if step_number is not None:
        selected_steps = [s for s in steps if int((s or {}).get('step') or 0) == int(step_number)]
        if not selected_steps:
            return None

    comparisons = []
    for s in selected_steps:
        if not isinstance(s, dict):
            continue
        before = s.get('state_before') if isinstance(s.get('state_before'), dict) else {}
        synthetic_state = {
            'env_name': row.get('env_name') or 'gridworld_v1',
            'position': list(before.get('position') or [0, 0]),
            'inventory': dict(before.get('inventory') or {}),
            'goal': list(row.get('goal') or [_GRID - 1, _GRID - 1]),
            'trap': list(row.get('trap') or [2, 2]),
            'resource': list(row.get('resource') or [1, 3]),
            'done': False,
        }
        choice = choose_action(synthetic_state, policy='causal_safe')
        candidates = choice.get('candidates') if isinstance(choice.get('candidates'), list) else []
        actual_action = str(s.get('action') or '')
        actual_prediction = next((c for c in candidates if str((c or {}).get('action') or '') == actual_action), None)
        alternatives = [c for c in candidates if str((c or {}).get('action') or '') != actual_action]
        best_alternative = sorted(alternatives, key=lambda x: float((x or {}).get('utility_score') or -999.0), reverse=True)[0] if alternatives else None
        reward_gap = round(float((best_alternative or {}).get('predicted_reward') or 0.0) - float((actual_prediction or {}).get('predicted_reward') or 0.0), 4)
        utility_gap = round(float((best_alternative or {}).get('utility_score') or 0.0) - float((actual_prediction or {}).get('utility_score') or 0.0), 4)
        comparisons.append({
            'step': s.get('step'),
            'actual': {
                'action': actual_action,
                'expected_effect': s.get('expected_effect'),
                'observed_effect': s.get('observed_effect'),
                'reward': s.get('reward'),
                'risk': s.get('risk') or {},
                'surprise_score': s.get('surprise_score'),
                'events': s.get('events') or [],
                'predicted': actual_prediction,
            },
            'best_alternative': best_alternative,
            'counterfactual_question': f"o que teria acontecido com {str((best_alternative or {}).get('action') or 'nenhuma_alternativa')}?",
            'analysis': {
                'likely_failure_cause': _likely_failure_cause(s),
                'reward_gap_vs_best_alternative': reward_gap,
                'utility_gap_vs_best_alternative': utility_gap,
                'better_alternative_available': bool(best_alternative and utility_gap > 0.05),
            },
        })

    high_surprise = sum(1 for c in comparisons if float((((c.get('actual') or {}).get('surprise_score')) or 0.0) or 0.0) > 0.0)
    better_alts = sum(1 for c in comparisons if bool(((c.get('analysis') or {}).get('better_alternative_available'))))
    return {
        'ok': True,
        'episode_id': episode_id,
        'comparisons': comparisons,
        'summary': {
            'count': len(comparisons),
            'high_surprise_steps': high_surprise,
            'steps_with_better_alternative': better_alts,
        },
    }


def replay_episode(episode_id: str) -> dict[str, Any] | None:
    row = get_episode(episode_id)
    if not row:
        return None
    steps = row.get('steps') if isinstance(row.get('steps'), list) else []
    surprises = [float((s or {}).get('surprise_score') or 0.0) for s in steps if isinstance(s, dict)]
    rewards = [float((s or {}).get('reward') or 0.0) for s in steps if isinstance(s, dict)]
    causal_trace = []
    for s in steps:
        if not isinstance(s, dict):
            continue
        causal_trace.append({
            'step': s.get('step'),
            'action': s.get('action'),
            'expected_effect': s.get('expected_effect'),
            'observed_effect': s.get('observed_effect'),
            'risk_score': float(((s.get('risk') or {}).get('risk_score')) or 0.0),
            'surprise_score': s.get('surprise_score'),
            'reward': s.get('reward'),
            'events': s.get('events') or [],
            'likely_failure_cause': _likely_failure_cause(s),
        })
    counterfactual = analyze_counterfactual(episode_id)
    return {
        'ok': True,
        'episode': row,
        'summary': {
            **_episode_summary(row),
            'total_surprise': round(sum(surprises), 4),
            'reward_trace': [round(x, 4) for x in rewards],
            'surprise_trace': [round(x, 4) for x in surprises],
        },
        'causal_trace': causal_trace,
        'counterfactual': counterfactual,
    }


def _goal_distance(pos: list[int], target: list[int]) -> int:
    return abs(int(pos[0]) - int(target[0])) + abs(int(pos[1]) - int(target[1]))


def _candidate_actions(state: dict[str, Any], policy: str) -> list[str]:
    pos = list(state.get('position') or [0, 0])
    goal = list(state.get('goal') or [_GRID - 1, _GRID - 1])
    resource = list(state.get('resource') or [1, 3])
    inv = int(((state.get('inventory') or {}).get('resource') or 0))
    pol = str(policy or 'goal_seek').strip().lower()

    target = goal
    if pol in ('resource_first', 'collector') and inv <= 0:
        target = resource

    preferred: list[str] = []
    if pos == resource and inv <= 0 and pol in ('resource_first', 'collector'):
        preferred.append('gather')
    if pos[0] < target[0]:
        preferred.append('move_east')
    if pos[1] < target[1]:
        preferred.append('move_south')
    if pos[0] > target[0]:
        preferred.append('move_west')
    if pos[1] > target[1]:
        preferred.append('move_north')

    all_actions = ['move_east', 'move_south', 'move_west', 'move_north', 'gather', 'wait']
    out = []
    for a in preferred + all_actions:
        if a not in out:
            out.append(a)
    return [a for a in out if a in _available_actions(state)]


def predict_action(action: str, state: dict[str, Any] | None = None, use_causal: bool = True) -> dict[str, Any]:
    st = state if isinstance(state, dict) else _load_state()
    action = str(action or '').strip().lower()
    available = _available_actions(st)
    if action not in available:
        return {'ok': False, 'error': 'invalid_action', 'available_actions': available}

    pos = list(st.get('position') or [0, 0])
    goal = list(st.get('goal') or [_GRID - 1, _GRID - 1])
    trap = list(st.get('trap') or [2, 2])
    resource = list(st.get('resource') or [1, 3])
    inv = int(((st.get('inventory') or {}).get('resource') or 0))
    next_pos = list(pos)
    expected_effect = _expected_effect_for(action, st)
    predicted_reward = -0.01
    side_effects: list[str] = []
    dependencies: list[str] = []

    if action == 'move_north':
        next_pos[1] -= 1
    elif action == 'move_south':
        next_pos[1] += 1
    elif action == 'move_west':
        next_pos[0] -= 1
    elif action == 'move_east':
        next_pos[0] += 1
    elif action == 'gather':
        dependencies.append('estar_na_posicao_do_recurso')
        dependencies.append('inventario_ainda_sem_recurso')
        if pos == resource and inv <= 0:
            predicted_reward += 0.3
            side_effects.append('resource_gathered')
        else:
            predicted_reward -= 0.05
            side_effects.append('nada_coletado')
    elif action == 'wait':
        side_effects.append('sem_progresso')

    next_pos = _clip_position(next_pos)
    if next_pos == trap:
        predicted_reward -= 1.0
        side_effects.append('trap')
    if next_pos == goal:
        predicted_reward += 1.0
        side_effects.append('goal_reached')
    if action.startswith('move_') and next_pos == pos:
        side_effects.append('borda_do_mapa')

    risk = _transition_risk_payload(st, action, next_pos) if use_causal else {'ok': True, 'risk_score': 0.0, 'activated_edges': [], 'vetoes': [], 'warnings': []}
    progress_gain = _goal_distance(pos, goal) - _goal_distance(next_pos, goal)
    risk_penalty = 0.35 * float(risk.get('risk_score') or 0.0) if use_causal else 0.0
    utility_score = round(float(predicted_reward) + (0.12 * float(progress_gain)) - risk_penalty, 4)

    return {
        'ok': True,
        'action': action,
        'expected_effect': expected_effect,
        'predicted_reward': round(predicted_reward, 4),
        'predicted_next_state': {
            'position': next_pos,
            'inventory_resource': inv + (1 if 'resource_gathered' in side_effects else 0),
        },
        'progress_gain': progress_gain,
        'risk': risk,
        'dependencies': dependencies,
        'side_effects': side_effects,
        'utility_score': utility_score,
        'causal_enabled': bool(use_causal),
    }


def choose_action(state: dict[str, Any] | None = None, policy: str = 'goal_seek') -> dict[str, Any]:
    st = state if isinstance(state, dict) else _load_state()
    pol = str(policy or 'goal_seek').strip().lower()
    candidates = _candidate_actions(st, pol)
    use_causal = pol not in ('goal_seek', 'wait', 'causal_blind', 'resource_first', 'collector')
    scored = [predict_action(a, st, use_causal=use_causal) for a in candidates]
    scored = [x for x in scored if bool(x.get('ok'))]
    if not scored:
        return {'ok': False, 'error': 'no_candidate_actions'}

    if pol == 'wait':
        chosen = next((x for x in scored if str(x.get('action') or '') == 'wait'), scored[0])
    elif pol in ('goal_seek', 'resource_first', 'collector'):
        chosen = scored[0]
    else:
        chosen = sorted(
            scored,
            key=lambda x: (
                float(x.get('utility_score') or -999.0),
                -float(((x.get('risk') or {}).get('risk_score') or 0.0)),
                float(x.get('predicted_reward') or 0.0),
            ),
            reverse=True,
        )[0]

    return {
        'ok': True,
        'policy': pol,
        'causal_enabled': bool(use_causal),
        'chosen_action': chosen.get('action'),
        'chosen_prediction': chosen,
        'candidates': scored,
    }


def _policy_action(state: dict[str, Any], policy: str) -> str:
    choice = choose_action(state, policy=policy)
    if bool(choice.get('ok')) and str(choice.get('chosen_action') or '').strip():
        return str(choice.get('chosen_action'))
    return 'wait'


def run_episode(policy: str = 'goal_seek', max_steps: int = _MAX_STEPS, env_name: str = 'gridworld_v1') -> dict[str, Any]:
    reset(env_name=env_name)
    max_steps = max(1, min(_MAX_STEPS, int(max_steps or _MAX_STEPS)))
    transitions: list[dict[str, Any]] = []
    pre_action_trace: list[dict[str, Any]] = []
    last = None
    for _ in range(max_steps):
        st = _load_state()
        if bool(st.get('done')):
            break
        choice = choose_action(st, policy=policy)
        action = str(choice.get('chosen_action') or 'wait')
        chosen_prediction = choice.get('chosen_prediction') if isinstance(choice.get('chosen_prediction'), dict) else {}
        expected = str(chosen_prediction.get('expected_effect') or _expected_effect_for(action, st))
        pre_action_trace.append({
            'step': int(st.get('step') or 0) + 1,
            'policy': policy,
            'causal_enabled': bool(choice.get('causal_enabled')),
            'action': action,
            'prediction': chosen_prediction,
        })
        last = act(action, expected_effect=expected)
        if bool(last.get('ok')):
            transitions.append(last.get('transition') or {})
        if bool(last.get('done')):
            break
    final_state = _load_state()
    replay = replay_episode(str(final_state.get('episode_id') or '')) if bool(final_state.get('done')) else None
    return {
        'ok': True,
        'policy': policy,
        'env_name': final_state.get('env_name'),
        'episode_id': final_state.get('episode_id'),
        'done': bool(final_state.get('done')),
        'steps_executed': len(transitions),
        'total_reward': final_state.get('total_reward') or 0.0,
        'done_reason': ((replay or {}).get('summary') or {}).get('done_reason'),
        'summary': (replay or {}).get('summary'),
        'pre_action_trace': pre_action_trace,
    }


def benchmark(policy: str = 'goal_seek', episodes_count: int = 10, max_steps: int = _MAX_STEPS, env_name: str = 'gridworld_v1') -> dict[str, Any]:
    runs = []
    episodes_count = max(1, min(200, int(episodes_count or 10)))
    for _ in range(episodes_count):
        runs.append(run_episode(policy=policy, max_steps=max_steps, env_name=env_name))
    successes = sum(1 for x in runs if str(x.get('done_reason') or '') == 'goal_reached')
    trap_failures = sum(1 for x in runs if str(x.get('done_reason') or '') == 'trap')
    failures = sum(1 for x in runs if str(x.get('done_reason') or '') in ('trap', 'max_steps'))
    incompletes = sum(1 for x in runs if not bool(x.get('done')))
    non_success = sum(1 for x in runs if str(x.get('done_reason') or '') != 'goal_reached')
    rewards = [float(x.get('total_reward') or 0.0) for x in runs]
    lengths = [int(((x.get('summary') or {}).get('steps') or x.get('steps_executed') or 0)) for x in runs]
    avg_surprises = []
    avg_risks = []
    counterfactual_better = []
    for x in runs:
        summary = x.get('summary') if isinstance(x.get('summary'), dict) else {}
        eid = str(x.get('episode_id') or '')
        cf = analyze_counterfactual(eid) if eid else None
        cf_summary = (cf or {}).get('summary') if isinstance((cf or {}).get('summary'), dict) else {}
        counterfactual_better.append(int(cf_summary.get('steps_with_better_alternative') or 0))
        avg_surprises.append(float(summary.get('avg_surprise') or 0.0))
        avg_risks.append(float(summary.get('avg_risk') or 0.0))
    return {
        'ok': True,
        'policy': policy,
        'env_name': env_name,
        'episodes': episodes_count,
        'success_rate': round(successes / max(1, episodes_count), 4),
        'failure_rate': round(failures / max(1, episodes_count), 4),
        'trap_rate': round(trap_failures / max(1, episodes_count), 4),
        'incomplete_rate': round(incompletes / max(1, episodes_count), 4),
        'non_success_rate': round(non_success / max(1, episodes_count), 4),
        'avg_reward': round(sum(rewards) / max(1, len(rewards)), 4),
        'avg_steps': round(sum(lengths) / max(1, len(lengths)), 2),
        'avg_surprise': round(sum(avg_surprises) / max(1, len(avg_surprises)), 4),
        'avg_predicted_risk': round(sum(avg_risks) / max(1, len(avg_risks)), 4),
        'avg_steps_with_better_alternative': round(sum(counterfactual_better) / max(1, len(counterfactual_better)), 2),
        'runs': runs[-20:],
    }


def benchmark_compare(
    policies: list[str] | None = None,
    episodes_count: int = 10,
    max_steps: int = _MAX_STEPS,
    env_names: list[str] | None = None,
) -> dict[str, Any]:
    selected = [str(x).strip().lower() for x in (policies or ['goal_seek', 'causal_blind', 'causal_safe']) if str(x).strip()]
    selected = list(dict.fromkeys(selected))[:10]
    envs = [(_env_config(x).get('env_name') or 'gridworld_v1') for x in (env_names or ['gridworld_v1', 'gridworld_risky', 'gridworld_detour'])]
    envs = list(dict.fromkeys(envs))[:10]

    results = []
    for env_name in envs:
        for pol in selected:
            results.append(benchmark(policy=pol, episodes_count=episodes_count, max_steps=max_steps, env_name=env_name))

    by_env: dict[str, dict[str, dict[str, Any]]] = {}
    for row in results:
        by_env.setdefault(str(row.get('env_name') or 'gridworld_v1'), {})[str(row.get('policy') or '')] = row

    causal_on_off = []
    for env_name, env_results in by_env.items():
        on = env_results.get('causal_safe') or {}
        off = env_results.get('causal_blind') or env_results.get('goal_seek') or {}
        causal_on_off.append({
            'env_name': env_name,
            'causal_on_policy': str(on.get('policy') or 'causal_safe'),
            'causal_off_policy': str(off.get('policy') or 'causal_blind'),
            'success_rate_gain': round(float(on.get('success_rate') or 0.0) - float(off.get('success_rate') or 0.0), 4),
            'avg_reward_gain': round(float(on.get('avg_reward') or 0.0) - float(off.get('avg_reward') or 0.0), 4),
            'trap_rate_reduction': round(float(off.get('trap_rate') or 0.0) - float(on.get('trap_rate') or 0.0), 4),
            'failure_rate_reduction': round(float(off.get('failure_rate') or 0.0) - float(on.get('failure_rate') or 0.0), 4),
            'surprise_reduction': round(float(off.get('avg_surprise') or 0.0) - float(on.get('avg_surprise') or 0.0), 4),
            'risk_reduction': round(float(off.get('avg_predicted_risk') or 0.0) - float(on.get('avg_predicted_risk') or 0.0), 4),
        })

    winner = sorted(
        results,
        key=lambda r: (
            float(r.get('success_rate') or 0.0),
            float(r.get('avg_reward') or -999.0),
            -float(r.get('trap_rate') or 999.0),
            -float(r.get('avg_steps_with_better_alternative') or 999.0),
        ),
        reverse=True,
    )[0] if results else None

    robust = {
        'envs_compared': len(envs),
        'episodes_per_policy_env': int(episodes_count),
        'causal_on_beats_off_in_success_envs': sum(1 for row in causal_on_off if float(row.get('success_rate_gain') or 0.0) > 0),
        'causal_on_reduces_failure_envs': sum(1 for row in causal_on_off if float(row.get('failure_rate_reduction') or 0.0) > 0),
        'causal_on_reduces_risk_envs': sum(1 for row in causal_on_off if float(row.get('risk_reduction') or 0.0) > 0),
        'causal_on_reduces_surprise_envs': sum(1 for row in causal_on_off if float(row.get('surprise_reduction') or 0.0) > 0),
    }

    report = {
        'ts': _now(),
        'env_names': envs,
        'episodes_per_policy': int(episodes_count),
        'max_steps': int(max_steps),
        'results': results,
        'causal_on_off': causal_on_off,
        'robust_summary': robust,
        'winner_policy': (winner or {}).get('policy'),
        'winner_env': (winner or {}).get('env_name'),
    }
    _ensure_parent(BENCHMARKS_PATH)
    with BENCHMARKS_PATH.open('a', encoding='utf-8') as f:
        f.write(json.dumps(report, ensure_ascii=False) + '\n')
    return {'ok': True, **report, 'benchmarks_path': str(BENCHMARKS_PATH)}


def status() -> dict[str, Any]:
    st = _load_state()
    eps = episodes(limit=5)
    return {
        'ok': True,
        'env_name': st.get('env_name'),
        'available_envs': sorted(_ENV_LIBRARY.keys()),
        'episode_id': st.get('episode_id'),
        'step': st.get('step'),
        'done': bool(st.get('done')),
        'total_reward': st.get('total_reward') or 0.0,
        'state_summary': _state_summary(st),
        'episodes_logged': int(eps.get('count') or 0),
        'state_path': str(STATE_PATH),
        'episodes_path': str(EPISODES_PATH),
    }
