from __future__ import annotations

from typing import Any
import time
import json
import uuid
import msvcrt
from pathlib import Path
from ultronpro import store

DATA_DIR = Path(__file__).resolve().parent.parent / 'data'
STATE_PATH = DATA_DIR / 'squad_phase_b.json'

DEFAULT = {
    'enabled': True,
    'task_queue': [],
    'active_tasks': {},
    'completed_tasks': [],
    'orchestration_mode': 'sequential',
    'max_concurrent': 3,
    'retry_policy': {'max_attempts': 3, 'backoff_sec': 30},
}


def _load() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return json.loads(json.dumps(DEFAULT))
    try:
        with open(STATE_PATH, 'r', encoding='utf-8') as f:
            msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
            content = f.read()
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        return json.loads(content)
    except Exception:
        return json.loads(json.dumps(DEFAULT))


def _save(state: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(STATE_PATH, 'w', encoding='utf-8') as f:
        msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
        f.write(json.dumps(state, ensure_ascii=False, indent=2))
        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)


def enqueue_task(task: dict[str, Any], priority: int = 5) -> dict[str, Any]:
    st = _load()
    task_id = f"task_{uuid.uuid4().hex}"
    entry = {
        'id': task_id,
        'task': task,
        'priority': int(priority),
        'status': 'queued',
        'created_at': time.time(),
        'attempts': 0,
    }
    st['task_queue'].append(entry)
    st['task_queue'].sort(key=lambda x: (x['priority'], -x['created_at']), reverse=True)
    _save(st)
    store.db.add_event('phase_b', f"Task enqueued: {task_id}")
    return {'ok': True, 'task_id': task_id, 'position': len(st['task_queue'])}


def dequeue_next() -> dict[str, Any] | None:
    st = _load()
    active_count = len([t for t in st['active_tasks'].values() if t['status'] == 'running'])
    max_concurrent = int(st.get('max_concurrent') or 3)
    
    if active_count >= max_concurrent:
        return None
    
    queued = [t for t in st['task_queue'] if t['status'] == 'queued']
    if not queued:
        return None
    
    next_task = queued[0]
    st['task_queue'].remove(next_task)
    next_task['status'] = 'running'
    next_task['started_at'] = time.time()
    st['active_tasks'][next_task['id']] = next_task
    _save(st)
    return next_task


def complete_task(task_id: str, result: Any, success: bool = True) -> dict[str, Any]:
    st = _load()
    if task_id not in st['active_tasks']:
        return {'ok': False, 'error': 'task_not_found'}
    
    task = st['active_tasks'][task_id]
    task['status'] = 'completed' if success else 'failed'
    task['completed_at'] = time.time()
    task['result'] = result
    task['success'] = success
    
    st['completed_tasks'].append(task)
    if len(st['completed_tasks']) > 1000:
        st['completed_tasks'] = st['completed_tasks'][-500:]
    
    del st['active_tasks'][task_id]
    _save(st)
    
    event_kind = 'task_completed' if success else 'task_failed'
    store.db.add_event('phase_b', f"{event_kind}: {task_id}")
    return {'ok': True, 'task_id': task_id, 'status': task['status']}


def retry_task(task_id: str) -> dict[str, Any]:
    st = _load()
    if task_id not in st['active_tasks']:
        return {'ok': False, 'error': 'task_not_found'}
    
    task = st['active_tasks'][task_id]
    retry_policy = st.get('retry_policy') or DEFAULT['retry_policy']
    max_attempts = int(retry_policy.get('max_attempts') or 3)
    
    if task['attempts'] >= max_attempts:
        return complete_task(task_id, {'error': 'max_retries_exceeded'}, success=False)
    
    task['attempts'] += 1
    task['status'] = 'queued'
    task['last_retry_at'] = time.time()
    
    backoff = int(retry_policy.get('backoff_sec') or 30)
    st['task_queue'].append(task)
    del st['active_tasks'][task_id]
    _save(st)
    
    store.db.add_event('phase_b', f"Task retry scheduled: {task_id} (attempt {task['attempts']}/{max_attempts})")
    return {'ok': True, 'task_id': task_id, 'retry_count': task['attempts'], 'backoff_sec': backoff}


def status() -> dict[str, Any]:
    st = _load()
    now = time.time()
    
    active = list(st['active_tasks'].values())
    running = [t for t in active if t['status'] == 'running']
    
    queue_stats = {
        'queued': len([t for t in st['task_queue'] if t['status'] == 'queued']),
        'high_priority': len([t for t in st['task_queue'] if t['priority'] >= 8]),
    }
    
    return {
        'ok': True,
        'enabled': bool(st.get('enabled', True)),
        'orchestration_mode': st.get('orchestration_mode', 'sequential'),
        'max_concurrent': int(st.get('max_concurrent') or 3),
        'queue': queue_stats,
        'active': {
            'total': len(active),
            'running': len(running),
            'tasks': [t['id'] for t in running],
        },
        'completed_today': len([t for t in st['completed_tasks'] 
                               if t.get('completed_at', 0) >= now - 86400]),
        'retry_policy': st.get('retry_policy', DEFAULT['retry_policy']),
    }


def set_orchestration_mode(mode: str) -> dict[str, Any]:
    valid_modes = ['sequential', 'parallel', 'priority', 'fair']
    if mode not in valid_modes:
        return {'ok': False, 'error': f'invalid_mode', 'valid_modes': valid_modes}
    
    st = _load()
    st['orchestration_mode'] = mode
    _save(st)
    store.db.add_event('phase_b', f"Orchestration mode changed to: {mode}")
    return {'ok': True, 'mode': mode}


def set_max_concurrent(limit: int) -> dict[str, Any]:
    if limit < 1 or limit > 20:
        return {'ok': False, 'error': 'invalid_limit', 'min': 1, 'max': 20}
    
    st = _load()
    st['max_concurrent'] = int(limit)
    _save(st)
    return {'ok': True, 'max_concurrent': int(limit)}


def get_task(task_id: str) -> dict[str, Any] | None:
    st = _load()
    
    for t in st['task_queue']:
        if t['id'] == task_id:
            return t
    
    if task_id in st['active_tasks']:
        return st['active_tasks'][task_id]
    
    for t in reversed(st['completed_tasks']):
        if t['id'] == task_id:
            return t
    
    return None


def cancel_task(task_id: str) -> dict[str, Any]:
    st = _load()
    
    for i, t in enumerate(st['task_queue']):
        if t['id'] == task_id:
            st['task_queue'].pop(i)
            _save(st)
            store.db.add_event('phase_b', f"Task cancelled: {task_id}")
            return {'ok': True, 'task_id': task_id, 'status': 'cancelled'}
    
    if task_id in st['active_tasks']:
        task = st['active_tasks'][task_id]
        task['status'] = 'cancelled'
        task['cancelled_at'] = time.time()
        st['completed_tasks'].append(task)
        if len(st['completed_tasks']) > 1000:
            st['completed_tasks'] = st['completed_tasks'][-500:]
        del st['active_tasks'][task_id]
        _save(st)
        store.db.add_event('phase_b', f"Task cancelled: {task_id}")
        return {'ok': True, 'task_id': task_id, 'status': 'cancelled'}
    
    return {'ok': False, 'error': 'task_not_found'}
