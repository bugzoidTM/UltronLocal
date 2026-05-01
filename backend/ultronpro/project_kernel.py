from __future__ import annotations

from pathlib import Path
from typing import Any
import json
import time

PROJECTS_PATH = Path(__file__).resolve().parent.parent / 'data' / 'projects_state.json'
PLAYBOOKS_PATH = Path(__file__).resolve().parent.parent / 'data' / 'recovery_playbooks.json'
MEMORY_PATH = Path(__file__).resolve().parent.parent / 'data' / 'project_memory_index.json'
ABSTRACTIONS_PATH = Path(__file__).resolve().parent.parent / 'data' / 'project_memory_abstractions.json'
RUN_STATE_PATH = Path(__file__).resolve().parent.parent / 'data' / 'project_run_state.json'


def _load(path: Path, default):
    try:
        if path.exists():
            d = json.loads(path.read_text())
            return d
    except Exception:
        pass
    return default


def _save(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    tmp.replace(path)


def _default_projects() -> dict[str, Any]:
    return {
        'updated_at': int(time.time()),
        'active_project_id': None,
        'projects': [],
    }


def load_projects() -> dict[str, Any]:
    d = _load(PROJECTS_PATH, None)
    if not isinstance(d, dict):
        return _default_projects()
    d.setdefault('projects', [])
    d.setdefault('active_project_id', None)
    return d


def save_projects(d: dict[str, Any]):
    d['updated_at'] = int(time.time())
    _save(PROJECTS_PATH, d)


def list_projects(limit: int = 50) -> list[dict[str, Any]]:
    d = load_projects()
    return (d.get('projects') or [])[-max(1, int(limit)):]


def active_project() -> dict[str, Any] | None:
    d = load_projects()
    aid = d.get('active_project_id')
    for p in d.get('projects') or []:
        if p.get('id') == aid and str(p.get('status') or 'active') in ('active', 'paused'):
            return p
    return None


def upsert_project(title: str, objective: str, scope: str | None = None, sla_hours: int = 72) -> dict[str, Any]:
    d = load_projects()
    title = (title or '').strip()[:180] or 'Projeto autônomo'
    objective = (objective or '').strip()[:1500]
    now = int(time.time())

    for p in d.get('projects') or []:
        if str(p.get('title') or '').strip().lower() == title.lower() and str(p.get('status') or 'active') in ('active', 'paused'):
            p['objective'] = objective or p.get('objective')
            if scope:
                p['scope'] = scope[:1200]
            p['updated_at'] = now
            d['active_project_id'] = p.get('id')
            save_projects(d)
            return p

    pid = f"prj_{now}_{len(d.get('projects') or [])+1}"
    item = {
        'id': pid,
        'title': title,
        'objective': objective,
        'scope': (scope or '')[:1200],
        'status': 'active',
        'created_at': now,
        'updated_at': now,
        'sla_hours': max(2, min(24 * 30, int(sla_hours))),
        'milestone_due_at': now + max(2, min(24 * 30, int(sla_hours))) * 3600,
        'progress': 0.0,
        'blockers': [],
        'risk_level': 'medium',
        'last_checkpoint_at': None,
        'kpi': {
            'advance_week': 0.0,
            'blocked_hours': 0.0,
            'cost_score': 0.0,
            'stuck_cycles': 0,
        },
    }
    d.setdefault('projects', []).append(item)
    d['projects'] = d['projects'][-80:]
    d['active_project_id'] = pid
    save_projects(d)
    return item


def add_checkpoint(project_id: str, note: str, progress_delta: float = 0.0, signal: str = 'tick') -> dict[str, Any] | None:
    d = load_projects()
    now = int(time.time())
    for p in d.get('projects') or []:
        if p.get('id') != project_id:
            continue
        cp = {
            'ts': now,
            'signal': (signal or 'tick')[:40],
            'note': (note or '')[:1200],
            'progress_delta': float(progress_delta or 0.0),
        }
        arr = list(p.get('checkpoints') or [])
        arr.append(cp)
        p['checkpoints'] = arr[-300:]
        p['progress'] = max(0.0, min(1.0, float(p.get('progress') or 0.0) + float(progress_delta or 0.0)))
        p['last_checkpoint_at'] = now
        p['updated_at'] = now
        save_projects(d)
        return cp
    return None


def set_blockers(project_id: str, blockers: list[str]):
    d = load_projects()
    now = int(time.time())
    for p in d.get('projects') or []:
        if p.get('id') == project_id:
            p['blockers'] = [str(x)[:220] for x in (blockers or [])[:12]]
            p['updated_at'] = now
            break
    save_projects(d)


def update_kpi(project_id: str, patch: dict[str, Any]):
    d = load_projects()
    now = int(time.time())
    for p in d.get('projects') or []:
        if p.get('id') != project_id:
            continue
        k = dict(p.get('kpi') or {})
        for kk, vv in (patch or {}).items():
            if isinstance(vv, (int, float)):
                k[kk] = float(vv)
        p['kpi'] = k
        p['updated_at'] = now
    save_projects(d)


def ensure_default_playbooks() -> dict[str, Any]:
    pb = _load(PLAYBOOKS_PATH, None)
    if isinstance(pb, dict) and pb.get('playbooks'):
        return pb

    pb = {
        'updated_at': int(time.time()),
        'playbooks': {
            'timeout': {
                'detect': 'long_request_or_no_progress',
                'fallbacks': ['retry_with_lower_budget', 'switch_to_deterministic_fallback', 'queue_followup_evidence'],
                'escalate': 'if_repeated_3x',
            },
            'low_deliberation_quality': {
                'detect': 'itc_quality_below_threshold',
                'fallbacks': ['increase_steps_small', 'change_policy_arm_balanced', 'split_problem_into_subgoal'],
                'escalate': 'if_repeated_2x',
            },
            'tool_failure': {
                'detect': 'action_error_or_external_tool_fail',
                'fallbacks': ['alternate_tool_route', 'replan_with_lower_cost', 'defer_and_checkpoint'],
                'escalate': 'if_repeated_3x',
            },
            'conflict_stalemate': {
                'detect': 'open_conflicts_persistent',
                'fallbacks': ['ask_targeted_evidence', 'run_analogy_transfer', 'manual_review_question'],
                'escalate': 'if_repeated_4x',
            },
            'kpi_regression': {
                'detect': 'progress_stagnation_and_blocked_hours_up',
                'fallbacks': ['prune_scope', 'reorder_subgoals', 'activate_recovery_mode'],
                'escalate': 'if_repeated_2x',
            },
        },
    }
    _save(PLAYBOOKS_PATH, pb)
    return pb


def get_playbooks() -> dict[str, Any]:
    return ensure_default_playbooks()


def suggest_playbook_actions(signal: str) -> list[str]:
    p = ensure_default_playbooks().get('playbooks') or {}
    item = p.get(signal) or {}
    return [str(x) for x in (item.get('fallbacks') or [])][:5]


def _default_run_state() -> dict[str, Any]:
    return {'updated_at': int(time.time()), 'steps': []}


def load_run_state() -> dict[str, Any]:
    d = _load(RUN_STATE_PATH, None)
    if not isinstance(d, dict):
        return _default_run_state()
    d.setdefault('steps', [])
    return d


def save_run_state(d: dict[str, Any]):
    d['updated_at'] = int(time.time())
    _save(RUN_STATE_PATH, d)


def begin_atomic_step(project_id: str, step_name: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    rs = load_run_state()
    now = int(time.time())
    token = f"stp_{now}_{len(rs.get('steps') or [])+1}"
    row = {
        'token': token,
        'project_id': str(project_id or ''),
        'step_name': (step_name or 'step')[:80],
        'status': 'running',
        'started_at': now,
        'updated_at': now,
        'payload': payload or {},
        'result': None,
        'error': None,
    }
    arr = list(rs.get('steps') or [])
    arr.append(row)
    rs['steps'] = arr[-800:]
    save_run_state(rs)
    if project_id:
        add_checkpoint(project_id, note=f"atomic_begin:{step_name}", progress_delta=0.0, signal='atomic_begin')
    return row


def complete_atomic_step(token: str, note: str = '', progress_delta: float = 0.0, result: dict[str, Any] | None = None) -> dict[str, Any] | None:
    rs = load_run_state()
    now = int(time.time())
    for s in rs.get('steps') or []:
        if s.get('token') != token:
            continue
        s['status'] = 'completed'
        s['updated_at'] = now
        s['result'] = result or {}
        save_run_state(rs)
        pid = str(s.get('project_id') or '')
        if pid:
            add_checkpoint(pid, note=(note or f"atomic_done:{s.get('step_name')}")[:1200], progress_delta=progress_delta, signal='atomic_commit')
        return s
    return None


def fail_atomic_step(token: str, error: str = '') -> dict[str, Any] | None:
    rs = load_run_state()
    now = int(time.time())
    for s in rs.get('steps') or []:
        if s.get('token') != token:
            continue
        s['status'] = 'failed'
        s['updated_at'] = now
        s['error'] = (error or '')[:500]
        save_run_state(rs)
        pid = str(s.get('project_id') or '')
        if pid:
            add_checkpoint(pid, note=f"atomic_fail:{s.get('step_name')} err={(error or '')[:180]}", progress_delta=0.0, signal='atomic_fail')
        return s
    return None


def recover_stale_steps(max_age_sec: int = 900) -> dict[str, Any]:
    rs = load_run_state()
    now = int(time.time())
    touched = 0
    recovered: list[str] = []
    for s in rs.get('steps') or []:
        if str(s.get('status') or '') != 'running':
            continue
        age = now - int(s.get('updated_at') or s.get('started_at') or now)
        if age > max(60, int(max_age_sec or 900)):
            s['status'] = 'stale_interrupted'
            s['updated_at'] = now
            recovered.append(str(s.get('token') or ''))
            touched += 1
            pid = str(s.get('project_id') or '')
            if pid:
                add_checkpoint(pid, note=f"atomic_recover:{s.get('step_name')} age={age}s", progress_delta=0.0, signal='atomic_recover')
    if touched:
        save_run_state(rs)
    return {'ok': True, 'recovered': recovered, 'count': touched}


def _default_memory() -> dict[str, Any]:
    return {'updated_at': int(time.time()), 'projects': {}}


def load_memory() -> dict[str, Any]:
    d = _load(MEMORY_PATH, None)
    if not isinstance(d, dict):
        return _default_memory()
    d.setdefault('projects', {})
    return d


def save_memory(d: dict[str, Any]):
    d['updated_at'] = int(time.time())
    _save(MEMORY_PATH, d)


def _extract_abstractions(text: str) -> list[str]:
    t = str(text or '').lower()
    out: list[str] = []
    if 'timeout' in t or 'retry' in t:
        out.append('Em falha intermitente, usar retry com backoff e idempotência.')
    if 'conflict' in t or 'contradi' in t:
        out.append('Resolver contradição com evidência antes de escalar complexidade.')
    if 'cost' in t or 'custo' in t:
        out.append('Priorizar opção de menor custo mantendo SLO mínimo.')
    if 'blocked' in t or 'stale' in t:
        out.append('Aplicar recovery playbook quando ciclo estagnar.')
    return list(dict.fromkeys(out))


def _remember_abstractions(project_id: str, abstractions: list[str], source_kind: str = 'note'):
    if not project_id or not abstractions:
        return
    d = _load(ABSTRACTIONS_PATH, {'projects': {}})
    pm = d.setdefault('projects', {})
    arr = list((pm.get(project_id) or {}).get('items') or [])
    now = int(time.time())
    for a in abstractions:
        arr.append({'ts': now, 'kind': source_kind[:40], 'text': a[:240]})
    # dedupe by text keeping latest
    seen = {}
    for it in arr:
        seen[str(it.get('text') or '')] = it
    pm[project_id] = {'items': list(seen.values())[-200:]}
    d['updated_at'] = now
    _save(ABSTRACTIONS_PATH, d)


def remember(project_id: str, kind: str, text: str, meta: dict[str, Any] | None = None):
    if not project_id:
        return
    d = load_memory()
    pm = d.setdefault('projects', {})
    arr = list((pm.get(project_id) or {}).get('items') or [])
    arr.append({
        'ts': int(time.time()),
        'kind': (kind or 'note')[:40],
        'text': (text or '')[:1200],
        'meta': meta or {},
    })
    pm[project_id] = {'items': arr[-500:]}
    save_memory(d)
    _remember_abstractions(project_id, _extract_abstractions(text), source_kind=kind)


def recall(project_id: str, query: str = '', limit: int = 20) -> list[dict[str, Any]]:
    d = load_memory()
    items = list((((d.get('projects') or {}).get(project_id) or {}).get('items') or []) )
    if not query.strip():
        return items[-max(1, int(limit)):]
    q = query.lower().strip()
    out = [x for x in items if q in str(x.get('text') or '').lower() or q in str(x.get('kind') or '').lower()]
    return out[-max(1, int(limit)):]


def project_brief(project_id: str, lookback: int = 20) -> dict[str, Any] | None:
    p = None
    for it in list_projects(limit=200):
        if it.get('id') == project_id:
            p = it
            break
    if not p:
        return None

    mem = recall(project_id, limit=lookback)
    blockers = [str(b) for b in (p.get('blockers') or [])[:4]]
    kpi = p.get('kpi') or {}

    next_steps = []
    if blockers:
        next_steps.append('Executar fallback de recovery para desbloquear gargalo principal')
    if float(kpi.get('stuck_cycles') or 0) >= 2:
        next_steps.append('Replanejar sub-objetivos com foco em menor custo e menor risco')
    if float(p.get('progress') or 0.0) < 0.5:
        next_steps.append('Priorizar 1 milestone mensurável para subir progresso semanal')
    if not next_steps:
        next_steps.append('Manter cadência de execução e checkpoint com evidência')

    mitigations = []
    if blockers:
        mitigations.extend(suggest_playbook_actions('conflict_stalemate')[:2])
    if float(kpi.get('cost_score') or 0.0) > 0.8:
        mitigations.extend(suggest_playbook_actions('tool_failure')[:2])

    abs_d = _load(ABSTRACTIONS_PATH, {'projects': {}})
    abstractions = list((((abs_d.get('projects') or {}).get(project_id) or {}).get('items') or []) )[-6:]

    return {
        'project_id': project_id,
        'title': p.get('title'),
        'objective': p.get('objective'),
        'progress': p.get('progress'),
        'kpi': kpi,
        'blockers': blockers,
        'next_steps': next_steps[:3],
        'mitigations': list(dict.fromkeys(mitigations))[:3],
        'memory_tail': mem[-8:],
        'abstractions': abstractions,
    }
