import json
import time
from pathlib import Path
from typing import Any

EPISODIC_PATH = Path('/app/data/episodic_memory.jsonl')
EPISODIC_ARCHIVE_PATH = Path('/app/data/episodic_memory_archive.jsonl')
ABSTRACTIONS_PATH = Path('/app/data/episodic_abstractions.json')
REPORT_PATH = Path('/app/data/sleep_cycle_report.json')


def _tokens(text: str) -> set[str]:
    import re
    return {t for t in re.findall(r"[a-zA-ZÀ-ÿ0-9_]{4,}", (text or '').lower())}


def _load_episodes() -> list[dict[str, Any]]:
    if not EPISODIC_PATH.exists():
        return []
    out = []
    for ln in EPISODIC_PATH.read_text(encoding='utf-8', errors='ignore').splitlines():
        if not ln.strip():
            continue
        try:
            out.append(json.loads(ln))
        except Exception:
            continue
    return out


def _append_archive(rows: list[dict[str, Any]]):
    if not rows:
        return
    EPISODIC_ARCHIVE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with EPISODIC_ARCHIVE_PATH.open('a', encoding='utf-8') as fp:
        for r in rows:
            fp.write(json.dumps(r, ensure_ascii=False) + '\n')


def _extract_rule(group_key: str, eps: list[dict[str, Any]]) -> str:
    ok = sum(1 for e in eps if bool(e.get('ok')))
    bad = len(eps) - ok
    if 'timeout' in group_key or 'retry' in group_key:
        return 'Aplicar retry com backoff e timeout curto quando houver latência intermitente de API.'
    if bad > ok:
        return 'Evitar estratégia atual em contexto semelhante; usar validação de evidência antes de executar.'
    return 'Reutilizar estratégia com maior taxa de sucesso em contexto análogo e monitorar latência.'


def run_cycle(retention_days: int = 14, max_active_rows: int = 3000) -> dict[str, Any]:
    now = int(time.time())
    keep_after = now - max(1, int(retention_days)) * 86400

    # NEW: also abstract from recent window (deep-metacognition warmup)
    recent_abstraction_hours = 48
    min_group_episodes = 2
    try:
        recent_abstraction_hours = max(6, int(Path('/app/data/sleep_cycle_recent_hours.txt').read_text().strip()))
    except Exception:
        pass
    try:
        min_group_episodes = max(2, int(Path('/app/data/sleep_cycle_min_group.txt').read_text().strip()))
    except Exception:
        pass
    recent_after = now - recent_abstraction_hours * 3600

    eps = _load_episodes()
    if not eps:
        rep = {'ok': True, 'ts': now, 'episodes_total': 0, 'pruned': 0, 'abstracted': 0}
        REPORT_PATH.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding='utf-8')
        return rep

    # split by retention
    fresh = [e for e in eps if int(e.get('ts') or 0) >= keep_after]
    stale = [e for e in eps if int(e.get('ts') or 0) < keep_after]

    # dedupe fresh by coarse semantic key
    dedup = {}
    for e in fresh:
        key = (str(e.get('kind') or ''), str(e.get('task_type') or ''), tuple(sorted(list(_tokens(str(e.get('text') or ''))))[:8]))
        dedup[key] = e
    fresh = list(dedup.values())

    # clip active to budget by newest first
    fresh.sort(key=lambda x: int(x.get('ts') or 0), reverse=True)
    fresh = fresh[:max(200, int(max_active_rows))]

    # build abstractions from stale + recent active episodes
    groups: dict[str, list[dict[str, Any]]] = {}
    source_rows = list(stale)
    source_rows.extend([e for e in fresh if int(e.get('ts') or 0) >= recent_after])
    for e in source_rows:
        key = f"{e.get('kind','')}|{e.get('task_type','')}"
        groups.setdefault(key, []).append(e)

    abs_old = {'items': []}
    if ABSTRACTIONS_PATH.exists():
        try:
            abs_old = json.loads(ABSTRACTIONS_PATH.read_text(encoding='utf-8'))
        except Exception:
            abs_old = {'items': []}

    # avoid duplicating same rule/group in a short period
    recent_existing = (abs_old.get('items') or [])[-200:]
    recent_keys = {f"{x.get('group','')}|{x.get('rule','')}" for x in recent_existing}

    abstractions = []
    for k, arr in groups.items():
        if len(arr) < min_group_episodes:
            continue
        rule = _extract_rule(k, arr)
        dedupe_key = f"{k}|{rule}"
        if dedupe_key in recent_keys:
            continue
        abstractions.append({
            'ts': now,
            'group': k,
            'episodes': len(arr),
            'rule': rule,
            'success_rate': round(sum(1 for x in arr if bool(x.get('ok'))) / max(1, len(arr)), 4),
            'window_hours': recent_abstraction_hours,
        })

    # Bootstrap fallback: if strict grouping found nothing, abstract by task_type only
    if not abstractions:
        tg: dict[str, list[dict[str, Any]]] = {}
        for e in source_rows:
            key = f"task:{e.get('task_type','unknown')}"
            tg.setdefault(key, []).append(e)
        for k, arr in tg.items():
            if len(arr) < max(1, min_group_episodes - 1):
                continue
            rule = _extract_rule(k, arr)
            dedupe_key = f"{k}|{rule}"
            if dedupe_key in recent_keys:
                continue
            abstractions.append({
                'ts': now,
                'group': k,
                'episodes': len(arr),
                'rule': rule,
                'success_rate': round(sum(1 for x in arr if bool(x.get('ok'))) / max(1, len(arr)), 4),
                'window_hours': recent_abstraction_hours,
                'bootstrap': True,
            })
    abs_old['items'] = (abs_old.get('items') or [])[-1200:] + abstractions
    ABSTRACTIONS_PATH.write_text(json.dumps(abs_old, ensure_ascii=False, indent=2), encoding='utf-8')

    # archive stale, keep fresh active
    _append_archive(stale)
    EPISODIC_PATH.write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in fresh) + ('\n' if fresh else ''), encoding='utf-8')

    rep = {
        'ok': True,
        'ts': now,
        'episodes_total': len(eps),
        'active_after': len(fresh),
        'pruned': len(stale),
        'abstracted': len(abstractions),
        'retention_days': retention_days,
        'max_active_rows': max_active_rows,
        'recent_abstraction_hours': recent_abstraction_hours,
        'min_group_episodes': min_group_episodes,
        'paths': {
            'episodic_active': str(EPISODIC_PATH),
            'episodic_archive': str(EPISODIC_ARCHIVE_PATH),
            'abstractions': str(ABSTRACTIONS_PATH),
        },
    }
    REPORT_PATH.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding='utf-8')
    return rep
