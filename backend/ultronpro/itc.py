from __future__ import annotations

from pathlib import Path
from typing import Any
import json
import random
import time

from ultronpro import llm

HISTORY_PATH = Path('/app/data/itc_history.json')
POLICY_PATH = Path('/app/data/itc_policy.json')
CHECKPOINT_PATH = Path('/app/data/itc_checkpoint.json')


ARMS = [
    {'name': 'fast', 'max_steps': 4, 'budget_seconds': 25},
    {'name': 'balanced', 'max_steps': 6, 'budget_seconds': 45},
    {'name': 'deep', 'max_steps': 8, 'budget_seconds': 70},
]


def _load_json(path: Path, default):
    try:
        if path.exists():
            d = json.loads(path.read_text())
            return d
    except Exception:
        pass
    return default


def _save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def _load_history() -> list[dict[str, Any]]:
    d = _load_json(HISTORY_PATH, [])
    return d if isinstance(d, list) else []


def _save_history(items: list[dict[str, Any]]):
    _save_json(HISTORY_PATH, items[-600:])


def _default_policy() -> dict[str, Any]:
    return {
        'epsilon': 0.18,
        'counts': {a['name']: 0 for a in ARMS},
        'values': {a['name']: 0.5 for a in ARMS},
        'updated_at': int(time.time()),
    }


def _load_policy() -> dict[str, Any]:
    d = _load_json(POLICY_PATH, None)
    if not isinstance(d, dict):
        return _default_policy()
    d.setdefault('epsilon', 0.18)
    d.setdefault('counts', {})
    d.setdefault('values', {})
    for a in ARMS:
        d['counts'].setdefault(a['name'], 0)
        d['values'].setdefault(a['name'], 0.5)
    return d


def _save_policy(pol: dict[str, Any]):
    pol['updated_at'] = int(time.time())
    _save_json(POLICY_PATH, pol)


def _checkpoint(payload: dict[str, Any]):
    data = {'ts': int(time.time()), **payload}
    _save_json(CHECKPOINT_PATH, data)


def history(limit: int = 40) -> list[dict[str, Any]]:
    arr = _load_history()
    return arr[-max(1, int(limit)):]


def policy_status() -> dict[str, Any]:
    return _load_policy()


def _choose_arm(problem_text: str, use_rl: bool = True) -> dict[str, Any]:
    if not use_rl:
        return ARMS[1]

    pol = _load_policy()
    eps = float(pol.get('epsilon') or 0.18)

    # contextual bias by complexity keywords
    p = (problem_text or '').lower()
    complex_hits = sum(1 for k in ['conflito', 'trade-off', 'ambígu', 'causal', 'risco', 'multiobjetivo'] if k in p)

    if random.random() < eps:
        arm = random.choice(ARMS)
    else:
        vals = pol.get('values') or {}
        arm = sorted(ARMS, key=lambda a: float(vals.get(a['name']) or 0.0), reverse=True)[0]

    if complex_hits >= 2 and arm['name'] == 'fast':
        arm = ARMS[1]
    if complex_hits >= 4:
        arm = ARMS[2]
    return arm


def _update_policy(arm_name: str, reward: float):
    pol = _load_policy()
    c = int((pol.get('counts') or {}).get(arm_name) or 0) + 1
    v = float((pol.get('values') or {}).get(arm_name) or 0.5)
    alpha = 1.0 / max(1, c)
    nv = (1.0 - alpha) * v + alpha * float(reward)
    pol['counts'][arm_name] = c
    pol['values'][arm_name] = max(0.0, min(1.0, nv))
    # anneal epsilon slowly
    pol['epsilon'] = max(0.06, float(pol.get('epsilon') or 0.18) * 0.998)
    _save_policy(pol)


def _generate_step(problem_text: str, prior: str) -> dict[str, Any]:
    prompt = (
        'Run a private deliberate reasoning step. Return ONLY JSON with keys: '\
        'hypothesis, counter_hypothesis, test, confidence (0..1).\n'
        f'Problem: {problem_text[:1800]}\nPrior: {prior[:700]}'
    )
    try:
        raw = llm.complete(prompt, strategy='reasoning', json_mode=True)
        d = json.loads(raw) if raw else {}
        h = str(d.get('hypothesis') or '').strip()
        if not h:
            raise ValueError('empty hypothesis')
        return {
            'hypothesis': h,
            'counter_hypothesis': str(d.get('counter_hypothesis') or '').strip()[:260],
            'test': str(d.get('test') or '').strip()[:260],
            'confidence': max(0.0, min(1.0, float(d.get('confidence') or 0.5))),
        }
    except Exception:
        return {
            'hypothesis': 'Reduzir incerteza no subproblema mais crítico.',
            'counter_hypothesis': 'Abordagem alternativa de menor custo.',
            'test': 'Executar microteste observável e comparar impacto/risco.',
            'confidence': 0.52,
        }


def _verify_step(problem_text: str, step: dict[str, Any]) -> dict[str, Any]:
    # quick deterministic checks first
    hyp = str(step.get('hypothesis') or '').strip()
    tst = str(step.get('test') or '').strip()
    if len(hyp) < 10 or len(tst) < 10:
        return {'valid': False, 'issue': 'underspecified', 'fix': 'Detalhar hipótese e teste observável.', 'delta': -0.15}

    prompt = (
        'Verify this reasoning step. Return ONLY JSON with keys: valid(true/false), '\
        'issue, fix, confidence_delta(-0.5..0.2).\n'
        f'Problem: {problem_text[:1500]}\n'
        f'Step hypothesis: {hyp[:300]}\nStep test: {tst[:300]}'
    )
    try:
        raw = llm.complete(prompt, strategy='cheap', json_mode=True)
        d = json.loads(raw) if raw else {}
        valid = bool(d.get('valid'))
        return {
            'valid': valid,
            'issue': str(d.get('issue') or '')[:220],
            'fix': str(d.get('fix') or '')[:240],
            'delta': max(-0.5, min(0.2, float(d.get('confidence_delta') or (0.03 if valid else -0.08)))),
        }
    except Exception:
        return {'valid': True, 'issue': '', 'fix': '', 'delta': 0.0}


def _antithesis_check(problem_text: str, step: dict[str, Any]) -> dict[str, Any]:
    hyp = str(step.get('hypothesis') or '').strip()
    ch = str(step.get('counter_hypothesis') or '').strip()
    if not hyp:
        return {'refuted': True, 'score': 0.0, 'reason': 'empty_hypothesis'}

    prompt = (
        'You are an adversarial reviewer. Try to refute the hypothesis using the counter-hypothesis. '
        'Return ONLY JSON with keys: refuted(true/false), score(0..1), reason, revision.\n'
        f'Problem: {problem_text[:1400]}\n'
        f'Hypothesis: {hyp[:320]}\n'
        f'Counter-hypothesis: {ch[:320]}\n'
        f'Test: {str(step.get("test") or "")[:260]}'
    )
    try:
        raw = llm.complete(prompt, strategy='cheap', json_mode=True)
        d = json.loads(raw) if raw else {}
        return {
            'refuted': bool(d.get('refuted')),
            'score': max(0.0, min(1.0, float(d.get('score') or 0.5))),
            'reason': str(d.get('reason') or '')[:220],
            'revision': str(d.get('revision') or '')[:260],
        }
    except Exception:
        # fail-soft heuristic: if explicit counter is present, mild penalty only
        return {'refuted': False, 'score': 0.48 if ch else 0.55, 'reason': 'fallback_heuristic', 'revision': ''}


def _run_linear_episode(problem_text: str, steps: int, budget: int) -> dict[str, Any]:
    start = time.time()
    traces: list[dict[str, Any]] = []
    hidden_trace: list[dict[str, Any]] = []
    prior = ''
    corrected = 0

    for i in range(steps):
        if (time.time() - start) >= budget:
            break

        st = _generate_step(problem_text, prior)
        ver = _verify_step(problem_text, st)
        ant = _antithesis_check(problem_text, st)
        conf = max(0.0, min(1.0, float(st.get('confidence') or 0.5) + float(ver.get('delta') or 0.0)))
        conf = max(0.0, min(1.0, conf * (0.88 + 0.24 * float(ant.get('score') or 0.5))))

        if not bool(ver.get('valid')) and ver.get('fix'):
            corrected += 1
            st['hypothesis'] = str(ver.get('fix'))[:260]
            st['test'] = f"Revalidar: {st.get('test') or 'microteste'}"
            conf = max(0.0, min(1.0, conf + 0.05))

        if bool(ant.get('refuted')) and ant.get('revision'):
            corrected += 1
            st['hypothesis'] = str(ant.get('revision'))[:260]
            conf = max(0.0, min(1.0, conf - 0.08))

        step_public = {
            'step': i + 1,
            'hypothesis': str(st.get('hypothesis') or '')[:220],
            'test': str(st.get('test') or '')[:220],
            'confidence': round(conf, 3),
            'corrected': bool((not ver.get('valid')) or bool(ant.get('refuted'))),
        }
        traces.append(step_public)
        hidden_trace.append({'step': i + 1, 'raw': st, 'verification': ver, 'antithesis': ant, 'confidence': conf})
        prior = '; '.join([x['hypothesis'] for x in traces[-3:]])

    return {'steps': traces, 'hidden_trace': hidden_trace, 'corrected': corrected, 'elapsed': round(time.time() - start, 3), 'search_mode': 'linear'}


def _run_mcts_episode(problem_text: str, steps: int, budget: int, branching: int = 2, checkpoint_every_sec: int = 30, deep_mode: bool = False) -> dict[str, Any]:
    start = time.time()
    branching = max(2, min(4, int(branching or 2)))

    node_seq = 0
    root = {
        'id': 0, 'parent': None, 'depth': 0, 'step': {'hypothesis': '', 'test': '', 'confidence': 0.5},
        'visits': 1, 'value': 0.0, 'children': []
    }
    nodes = {0: root}
    corrected = 0
    last_cp = time.time()

    def ucb(child: dict[str, Any], parent_visits: int, c: float = 1.18) -> float:
        v = float(child.get('value') or 0.0)
        n = max(1, int(child.get('visits') or 0))
        return (v / n) + c * ((parent_visits ** 0.5) / (1.0 + n))

    def path_to(nid: int) -> list[dict[str, Any]]:
        out = []
        cur = nodes.get(nid)
        while cur and cur.get('parent') is not None:
            out.append(cur)
            cur = nodes.get(cur.get('parent'))
        return list(reversed(out))

    iterations = 0
    while (time.time() - start) < budget and iterations < (steps * 5):
        iterations += 1

        # Selection
        current = root
        while current.get('children'):
            pvis = max(1, int(current.get('visits') or 1))
            kids = [nodes[cid] for cid in current['children'] if cid in nodes]
            if not kids:
                break
            current = sorted(kids, key=lambda k: ucb(k, pvis), reverse=True)[0]
            if int(current.get('depth') or 0) >= steps:
                break

        # Expansion
        if int(current.get('depth') or 0) < steps and (time.time() - start) < budget:
            prior = '; '.join([n['step']['hypothesis'] for n in path_to(int(current['id']))[-3:] if n.get('step')])
            for _ in range(branching):
                if (time.time() - start) >= budget:
                    break
                st = _generate_step(problem_text, prior)
                ver = _verify_step(problem_text, st)
                ant = _antithesis_check(problem_text, st)
                conf = max(0.0, min(1.0, float(st.get('confidence') or 0.5) + float(ver.get('delta') or 0.0)))
                conf = max(0.0, min(1.0, conf * (0.88 + 0.24 * float(ant.get('score') or 0.5))))

                if not bool(ver.get('valid')) and ver.get('fix'):
                    corrected += 1
                    st['hypothesis'] = str(ver.get('fix'))[:260]
                    st['test'] = f"Revalidar: {st.get('test') or 'microteste'}"
                    conf = max(0.0, min(1.0, conf + 0.05))

                if bool(ant.get('refuted')) and ant.get('revision'):
                    corrected += 1
                    st['hypothesis'] = str(ant.get('revision'))[:260]
                    conf = max(0.0, min(1.0, conf - 0.08))

                node_seq += 1
                child = {
                    'id': node_seq,
                    'parent': int(current['id']),
                    'depth': int(current.get('depth') or 0) + 1,
                    'step': {
                        'hypothesis': str(st.get('hypothesis') or '')[:220],
                        'test': str(st.get('test') or '')[:220],
                        'confidence': round(conf, 3),
                        'corrected': bool((not ver.get('valid')) or bool(ant.get('refuted'))),
                    },
                    'visits': 0,
                    'value': 0.0,
                    'children': [],
                }
                nodes[node_seq] = child
                current['children'].append(node_seq)

        # periodic checkpoint for long-running ITC
        now = time.time()
        if deep_mode and (now - last_cp) >= max(10, int(checkpoint_every_sec or 30)):
            best_conf = 0.0
            try:
                best_conf = max([float((n.get('step') or {}).get('confidence') or 0.0) for n in nodes.values()])
            except Exception:
                pass
            _checkpoint({
                'kind': 'itc_deep_think',
                'search_mode': 'mcts',
                'budget_seconds': budget,
                'elapsed_sec': round(now - start, 3),
                'iterations': iterations,
                'nodes': len(nodes),
                'best_confidence': round(best_conf, 3),
                'branching_factor': branching,
                'steps_cap': steps,
            })
            last_cp = now

        # Simulation / Backpropagation (one-step rollout proxy)
        leaf = current
        if current.get('children'):
            leaf = nodes[current['children'][-1]]
        reward = float((leaf.get('step') or {}).get('confidence') or 0.0)

        cur = leaf
        while cur is not None:
            cur['visits'] = int(cur.get('visits') or 0) + 1
            cur['value'] = float(cur.get('value') or 0.0) + reward
            pid = cur.get('parent')
            cur = nodes.get(pid) if pid is not None else None

    leaves = [n for n in nodes.values() if int(n.get('depth') or 0) > 0]
    leaves_sorted = sorted(leaves, key=lambda n: ((float((n.get('step') or {}).get('confidence') or 0.0)), int(n.get('depth') or 0)), reverse=True)
    best = leaves_sorted[0] if leaves_sorted else None
    best_path = path_to(int(best['id'])) if best else []

    traces = []
    for idx, n in enumerate(best_path, start=1):
        st = n.get('step') or {}
        traces.append({
            'step': idx,
            'hypothesis': str(st.get('hypothesis') or '')[:220],
            'test': str(st.get('test') or '')[:220],
            'confidence': round(float(st.get('confidence') or 0.0), 3),
            'corrected': bool(st.get('corrected')),
        })

    return {
        'steps': traces,
        'hidden_trace': {'nodes': len(nodes), 'iterations': iterations, 'branching': branching},
        'corrected': corrected,
        'elapsed': round(time.time() - start, 3),
        'search_mode': 'mcts',
        'search_tree_nodes': len(nodes),
        'search_iterations': iterations,
        'branching_factor': branching,
    }


def run_episode(problem_text: str, max_steps: int = 0, budget_seconds: int = 0, use_rl: bool = True, search_mode: str = 'mcts', branching_factor: int = 2, checkpoint_every_sec: int = 30) -> dict[str, Any]:
    p = (problem_text or '').strip()
    if len(p) < 12:
        return {'status': 'insufficient_context'}

    arm = _choose_arm(p, use_rl=use_rl)
    steps = int(max_steps) if int(max_steps or 0) > 0 else int(arm['max_steps'])
    budget = int(budget_seconds) if int(budget_seconds or 0) > 0 else int(arm['budget_seconds'])

    mode = str(search_mode or 'mcts').lower().strip()
    if mode not in ('mcts', 'iterative', 'linear', 'deep_think'):
        mode = 'mcts'

    is_deep = mode == 'deep_think'
    steps = max(2, min(18 if is_deep else 12, steps))
    budget = max(12, min(6 * 3600 if is_deep else 3600, budget))

    run = _run_mcts_episode(
        p,
        steps=steps,
        budget=budget,
        branching=(max(2, branching_factor) if is_deep else branching_factor),
        checkpoint_every_sec=checkpoint_every_sec,
        deep_mode=is_deep,
    ) if mode in ('mcts', 'deep_think') else _run_linear_episode(p, steps=steps, budget=budget)

    traces = run.get('steps') or []
    corrected = int(run.get('corrected') or 0)
    quality = round(sum(float(s.get('confidence') or 0) for s in traces) / max(1, len(traces)), 3) if traces else 0.0
    elapsed = float(run.get('elapsed') or 0.0)

    # RL reward: quality gains, penalize latency and correction burden
    reward = max(0.0, min(1.0, quality - min(0.35, elapsed / 240.0) - min(0.25, corrected * 0.05)))
    if use_rl:
        _update_policy(arm['name'], reward)

    chosen = sorted(traces, key=lambda x: float(x.get('confidence') or 0), reverse=True)[0] if traces else None

    out = {
        'status': 'ok' if traces else 'empty',
        'problem_text': p[:2200],
        'steps': traces,
        'chosen': chosen,
        'elapsed_sec': round(elapsed, 3),
        'budget_seconds': budget,
        'max_steps': steps,
        'policy_arm': arm['name'],
        'quality_proxy': quality,
        'corrections': corrected,
        'reward': round(reward, 3),
        'search_mode': run.get('search_mode') or mode,
    }
    if run.get('search_tree_nodes') is not None:
        out['search_tree_nodes'] = int(run.get('search_tree_nodes') or 0)
        out['search_iterations'] = int(run.get('search_iterations') or 0)
        out['branching_factor'] = int(run.get('branching_factor') or 0)
    if is_deep:
        out['checkpoint_path'] = str(CHECKPOINT_PATH)
        _checkpoint({'kind': 'itc_deep_think_final', 'status': out.get('status'), 'elapsed_sec': out.get('elapsed_sec'), 'quality_proxy': out.get('quality_proxy'), 'search_tree_nodes': out.get('search_tree_nodes', 0), 'search_iterations': out.get('search_iterations', 0)})

    arr = _load_history()
    arr.append({'ts': int(time.time()), **out, 'internal': {'trace': run.get('hidden_trace')}})
    _save_history(arr)
    return out
