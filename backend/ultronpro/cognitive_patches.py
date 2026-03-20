from __future__ import annotations

import json
import time
import hashlib
from pathlib import Path
from typing import Any

PATCHES_PATH = Path('/app/data/cognitive_patches.jsonl')
STATE_PATH = Path('/app/data/cognitive_patches_state.json')

DEFAULT_STATE: dict[str, Any] = {
    'version': 1,
    'active_patch_ids': [],
    'last_updated_at': 0,
    'last_known_good_patch_ids': [],
    'active_snapshot': {},
}

ALLOWED_STATUS = {
    'proposed',
    'evaluating',
    'evaluated',
    'promoted',
    'rejected',
    'rolled_back',
    'archived',
}

ALLOWED_KINDS = {
    'heuristic_patch',
    'routing_patch',
    'confidence_patch',
    'adapter_patch',
    'planner_patch',
}


def _now() -> int:
    return int(time.time())


def _ensure_parent(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)


def _normalize_status(status: str | None) -> str:
    s = str(status or 'proposed').strip().lower()
    return s if s in ALLOWED_STATUS else 'proposed'


def _normalize_kind(kind: str | None) -> str:
    k = str(kind or 'heuristic_patch').strip().lower()
    return k if k in ALLOWED_KINDS else 'heuristic_patch'


def _make_id(kind: str, problem_pattern: str, created_at: int) -> str:
    base = f'{kind}|{problem_pattern}|{created_at}'
    return f'cp_{hashlib.sha1(base.encode("utf-8", errors="ignore")).hexdigest()[:12]}'


def _load_state() -> dict[str, Any]:
    try:
        if STATE_PATH.exists():
            d = json.loads(STATE_PATH.read_text(encoding='utf-8'))
            if isinstance(d, dict):
                out = dict(DEFAULT_STATE)
                out.update(d)
                out['active_patch_ids'] = [str(x) for x in (out.get('active_patch_ids') or []) if x]
                return out
    except Exception:
        pass
    return dict(DEFAULT_STATE)


def _save_state(d: dict[str, Any]):
    _ensure_parent(STATE_PATH)
    out = dict(DEFAULT_STATE)
    out.update(d or {})
    out['last_updated_at'] = _now()
    STATE_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')


def _append_jsonl(path: Path, row: dict[str, Any]):
    _ensure_parent(path)
    with path.open('a', encoding='utf-8') as f:
        f.write(json.dumps(row, ensure_ascii=False) + '\n')


def _read_rows() -> list[dict[str, Any]]:
    if not PATCHES_PATH.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        for ln in PATCHES_PATH.read_text(encoding='utf-8', errors='ignore').splitlines():
            ln = ln.strip()
            if not ln:
                continue
            try:
                row = json.loads(ln)
            except Exception:
                continue
            if isinstance(row, dict):
                rows.append(row)
    except Exception:
        return []
    return rows


def list_patches(limit: int = 200, status: str | None = None, kind: str | None = None) -> list[dict[str, Any]]:
    rows = _read_rows()
    if status:
        st = _normalize_status(status)
        rows = [r for r in rows if str(r.get('status') or 'proposed') == st]
    if kind:
        kd = _normalize_kind(kind)
        rows = [r for r in rows if str(r.get('kind') or 'heuristic_patch') == kd]
    rows.sort(key=lambda r: (int(r.get('created_at') or 0), str(r.get('id') or '')), reverse=True)
    return rows[:max(1, int(limit))]


def get_patch(patch_id: str) -> dict[str, Any] | None:
    pid = str(patch_id or '').strip()
    if not pid:
        return None
    for row in _read_rows()[::-1]:
        if str(row.get('id') or '') == pid:
            return row
    return None


def create_patch(payload: dict[str, Any]) -> dict[str, Any]:
    now = _now()
    kind = _normalize_kind(str(payload.get('kind') or 'heuristic_patch'))
    problem_pattern = str(payload.get('problem_pattern') or '').strip()[:300]
    pid = str(payload.get('id') or '').strip() or _make_id(kind, problem_pattern, now)
    row: dict[str, Any] = {
        'id': pid,
        'created_at': int(payload.get('created_at') or now),
        'updated_at': now,
        'kind': kind,
        'source': str(payload.get('source') or 'manual')[:120],
        'problem_pattern': problem_pattern,
        'hypothesis': str(payload.get('hypothesis') or '')[:1200],
        'proposed_change': payload.get('proposed_change') if isinstance(payload.get('proposed_change'), dict) else {},
        'expected_gain': str(payload.get('expected_gain') or '')[:800],
        'risk_level': str(payload.get('risk_level') or 'medium')[:40],
        'status': _normalize_status(str(payload.get('status') or 'proposed')),
        'evidence_refs': payload.get('evidence_refs') if isinstance(payload.get('evidence_refs'), list) else [],
        'benchmark_before': payload.get('benchmark_before') if isinstance(payload.get('benchmark_before'), dict) else {},
        'benchmark_after': payload.get('benchmark_after') if isinstance(payload.get('benchmark_after'), dict) else {},
        'promoted_at': payload.get('promoted_at'),
        'rollback_ref': payload.get('rollback_ref'),
        'shadow_metrics': payload.get('shadow_metrics') if isinstance(payload.get('shadow_metrics'), dict) else {},
        'domain_regression': payload.get('domain_regression') if isinstance(payload.get('domain_regression'), dict) else {},
        'canary_state': payload.get('canary_state') if isinstance(payload.get('canary_state'), dict) else {},
        'tags': [str(x)[:60] for x in (payload.get('tags') or []) if str(x).strip()][:20],
        'notes': str(payload.get('notes') or '')[:1200],
    }
    _append_jsonl(PATCHES_PATH, row)
    return row


def append_revision(patch_id: str, patch: dict[str, Any], *, new_status: str | None = None) -> dict[str, Any] | None:
    current = get_patch(patch_id)
    if not current:
        return None
    merged = dict(current)
    for k, v in (patch or {}).items():
        if k in {'id', 'created_at'}:
            continue
        merged[k] = v
    merged['updated_at'] = _now()
    if new_status is not None:
        merged['status'] = _normalize_status(new_status)
    else:
        merged['status'] = _normalize_status(str(merged.get('status') or current.get('status') or 'proposed'))
    if merged['status'] == 'promoted' and not merged.get('promoted_at'):
        merged['promoted_at'] = _now()
    _append_jsonl(PATCHES_PATH, merged)
    _refresh_state_from_rows()
    return merged


def promote_patch(patch_id: str, note: str | None = None) -> dict[str, Any] | None:
    row = append_revision(patch_id, {'notes': str(note or '')[:1200]}, new_status='promoted')
    if not row:
        return None
    state = _load_state()
    active = set(str(x) for x in (state.get('active_patch_ids') or []) if x)
    active.add(str(patch_id))
    state['active_patch_ids'] = sorted(active)
    state['last_known_good_patch_ids'] = sorted(active)
    state['active_snapshot'] = {
        'ts': _now(),
        'active_patch_ids': sorted(active),
        'reason': 'promotion',
        'source_patch_id': str(patch_id),
    }
    _save_state(state)
    return row


def reject_patch(patch_id: str, reason: str | None = None, evidence_refs: list[str] | None = None) -> dict[str, Any] | None:
    current = get_patch(patch_id)
    if not current:
        return None
    merged_evidence = [str(x)[:200] for x in (current.get('evidence_refs') or []) if str(x).strip()]
    for ref in (evidence_refs or []):
        sref = str(ref)[:200]
        if sref and sref not in merged_evidence:
            merged_evidence.append(sref)
    return append_revision(
        patch_id,
        {
            'evidence_refs': merged_evidence[:30],
            'notes': ((str(current.get('notes') or '') + '\n' if current.get('notes') else '') + f"rejection_reason={str(reason or 'unspecified')[:500]}")[:1200],
        },
        new_status='rejected',
    )


def rollback_patch(patch_id: str, rollback_ref: str | None = None, note: str | None = None) -> dict[str, Any] | None:
    row = append_revision(patch_id, {
        'rollback_ref': str(rollback_ref or '')[:200] or None,
        'notes': str(note or '')[:1200],
    }, new_status='rolled_back')
    if not row:
        return None
    state = _load_state()
    current_active = [str(x) for x in (state.get('active_patch_ids') or []) if str(x)]
    state['active_patch_ids'] = [x for x in current_active if str(x) != str(patch_id)]
    if state.get('last_known_good_patch_ids'):
        state['active_patch_ids'] = [str(x) for x in (state.get('last_known_good_patch_ids') or []) if str(x) != str(patch_id)]
    state['active_snapshot'] = {
        'ts': _now(),
        'active_patch_ids': state['active_patch_ids'],
        'reason': 'rollback',
        'source_patch_id': str(patch_id),
        'rollback_ref': str(rollback_ref or '')[:200] or None,
    }
    _save_state(state)
    return row


def stats() -> dict[str, Any]:
    rows = _read_rows()
    counts: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    for r in rows:
        st = str(r.get('status') or 'proposed')
        kd = str(r.get('kind') or 'heuristic_patch')
        counts[st] = counts.get(st, 0) + 1
        by_kind[kd] = by_kind.get(kd, 0) + 1
    state = _load_state()
    return {
        'ok': True,
        'path': str(PATCHES_PATH),
        'state_path': str(STATE_PATH),
        'total_rows': len(rows),
        'counts_by_status': counts,
        'counts_by_kind': by_kind,
        'active_patch_ids': state.get('active_patch_ids') or [],
        'last_known_good_patch_ids': state.get('last_known_good_patch_ids') or [],
        'active_snapshot': state.get('active_snapshot') or {},
        'last_updated_at': state.get('last_updated_at') or 0,
    }


def _refresh_state_from_rows():
    rows = _read_rows()
    active: set[str] = set()
    for r in rows:
        pid = str(r.get('id') or '')
        st = str(r.get('status') or 'proposed')
        if not pid:
            continue
        if st == 'promoted':
            active.add(pid)
        elif st == 'rolled_back' and pid in active:
            active.remove(pid)
    state = _load_state()
    state['active_patch_ids'] = sorted(active)
    _save_state(state)
