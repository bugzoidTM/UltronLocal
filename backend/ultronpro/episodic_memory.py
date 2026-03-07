import json
import time
import os
from pathlib import Path
from typing import Any

EPISODIC_PATH = Path('/app/data/episodic_memory.jsonl')
AUDIT_PATH = Path('/app/data/episodic_audit.jsonl')


def _tokens(text: str) -> set[str]:
    import re
    return {t for t in re.findall(r"[a-zA-ZÀ-ÿ0-9_]{4,}", (text or '').lower())}


def _infer_error_class(error_text: str) -> str:
    e = str(error_text or '').lower()
    if not e:
        return 'none'
    if '403' in e or 'forbidden' in e or 'permission' in e or 'acl' in e:
        return '403'
    if '429' in e or 'rate limit' in e or 'too many requests' in e:
        return '429'
    if any(x in e for x in ['500', '501', '502', '503', '504', '5xx', 'bad gateway', 'gateway timeout']):
        return '5xx'
    if 'timeout' in e or 'timed out' in e or 'connection aborted' in e:
        return 'timeout'
    if 'json' in e or 'parse' in e or 'decode' in e or 'invalid regular expression' in e:
        return 'parse'
    if 'sql' in e or 'db' in e or 'database' in e or 'postgres' in e or 'sqlite' in e:
        return 'db'
    return 'other'


def _audit_enabled() -> bool:
    return str(os.getenv('ULTRON_EPISODIC_AUDIT', '1')).strip().lower() not in ('0', 'false', 'no', 'off')


def _append_audit(row: dict[str, Any]):
    if not _audit_enabled():
        return
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with AUDIT_PATH.open('a', encoding='utf-8') as f:
        f.write(json.dumps(row, ensure_ascii=False) + '\n')


def append_episode(*, action_id: int, kind: str, text: str, task_type: str, strategy: str, ok: bool, latency_ms: int, error: str = '', meta: dict[str, Any] | None = None):
    EPISODIC_PATH.parent.mkdir(parents=True, exist_ok=True)
    _meta = dict(meta or {})
    now = int(time.time())
    err_text = str(error or '')[:240]
    error_class = str(_meta.get('error_class') or _infer_error_class(err_text))
    outcome = str(_meta.get('outcome') or ('success' if bool(ok) else 'failure'))
    tool = str(_meta.get('tool') or strategy or kind or task_type or 'unknown')
    txt = str(text or '')[:420]

    # Data-quality gate (no forced reasoning, only input hygiene)
    missing = []
    if not str(task_type or '').strip():
        missing.append('task_type')
    if int(latency_ms or 0) <= 0:
        missing.append('latency_ms')
    if not str(tool or '').strip():
        missing.append('tool')
    if not str(outcome or '').strip():
        missing.append('outcome')
    if not str(error_class or '').strip():
        missing.append('error_class')
    quality = 'strong' if not missing else 'weak'

    # Dedup TTL for repetitive/noisy events
    dedup_ttl_sec = int(os.getenv('ULTRON_EPISODIC_DEDUP_TTL_SEC', '1800') or 1800)
    qkey = f"{str(task_type or '').strip().lower()}|{str(tool).lower()}|{str(error_class).lower()}|{' '.join(sorted(list(_tokens(txt)))[:10])}"
    duplicate_recent = False
    for e in recent(limit=200):
        try:
            ets = int(e.get('ts') or 0)
            if now - ets > dedup_ttl_sec:
                continue
            eq = f"{str(e.get('task_type') or '').strip().lower()}|{str(e.get('tool') or e.get('strategy') or '').lower()}|{str(e.get('error_class') or '').lower()}|{' '.join(sorted(list(_tokens(str(e.get('text') or ''))))[:10])}"
            if eq == qkey:
                duplicate_recent = True
                break
        except Exception:
            continue

    row = {
        'ts': now,
        'action_id': int(action_id),
        'kind': str(kind or ''),
        'task_type': str(task_type or ''),
        'strategy': str(strategy or kind or ''),
        'text': txt,
        'ok': bool(ok),
        'latency_ms': int(latency_ms or 0),
        'error': err_text,
        'error_class': error_class,
        'tool': tool,
        'outcome': outcome,
        'quality': quality,
        'meta': _meta,
    }

    # Audit every decision path
    _append_audit({
        'ts': now,
        'event': 'append_episode_decision',
        'action_id': int(action_id),
        'accepted': (not duplicate_recent),
        'duplicate_recent': duplicate_recent,
        'quality': quality,
        'missing_fields': missing,
        'task_type': str(task_type or ''),
        'tool': tool,
        'error_class': error_class,
        'latency_ms': int(latency_ms or 0),
        'outcome': outcome,
    })

    if duplicate_recent:
        return

    with EPISODIC_PATH.open('a', encoding='utf-8') as f:
        f.write(json.dumps(row, ensure_ascii=False) + '\n')


def recent(limit: int = 1200) -> list[dict[str, Any]]:
    if not EPISODIC_PATH.exists():
        return []
    rows = []
    for ln in EPISODIC_PATH.read_text(encoding='utf-8', errors='ignore').splitlines()[-max(10, int(limit or 1200)):]:
        if not ln.strip():
            continue
        try:
            rows.append(json.loads(ln))
        except Exception:
            continue
    return rows


def find_similar(*, kind: str, text: str, task_type: str = '', limit: int = 5) -> list[dict[str, Any]]:
    q = _tokens(f"{kind} {task_type} {text}")
    out: list[tuple[float, dict[str, Any]]] = []
    for e in recent(limit=1600):
        et = _tokens(f"{e.get('kind','')} {e.get('task_type','')} {e.get('text','')}")
        if not et or not q:
            continue
        inter = len(q & et)
        if inter <= 0:
            continue
        sim = inter / max(1, len(q | et))
        quality = 0.15 if bool(e.get('ok')) else -0.12
        speed = 0.1 if int(e.get('latency_ms') or 0) < 1200 else -0.06
        score = sim + quality + speed
        out.append((score, e))
    out.sort(key=lambda x: x[0], reverse=True)
    return [e for _, e in out[:max(1, int(limit or 5))]]


def strategy_hints(kind: str, text: str, task_type: str = '') -> dict[str, Any]:
    sims = find_similar(kind=kind, text=text, task_type=task_type, limit=8)
    if not sims:
        return {'ok': True, 'hints': [], 'similar': []}
    good = [s for s in sims if bool(s.get('ok'))]
    bad = [s for s in sims if not bool(s.get('ok'))]
    hints = []
    if good:
        hints.append('Preferir estratégia semelhante aos episódios de sucesso com baixa latência.')
    if bad:
        hints.append('Evitar abordagem que falhou em episódios análogos recentes.')
    return {'ok': True, 'hints': hints[:3], 'similar': sims[:5]}
