from __future__ import annotations

import re
from pathlib import Path
from typing import Any

ROADMAP_CANDIDATES = [
    Path('/root/.openclaw/workspace/UltronPro/ROADMAP_AGI_FRONTS.md'),
    Path('/app/ultronpro/ROADMAP_AGI_FRONTS.md'),
]
STATUS_PAT = re.compile(r'_Status[^:]*:\s*(.+?)_\s*$')
PERCENT_PAT = re.compile(r'(\d+)%')
ITEM_PAT = re.compile(r'- \[(FEITO|PENDENTE|EM ANDAMENTO(?:\s+\d+%)?)\]')


def _resolve_path() -> Path:
    last_error: Exception | None = None
    for candidate in ROADMAP_CANDIDATES:
        try:
            if candidate.exists():
                candidate.read_text(encoding='utf-8')
                return candidate
        except Exception as exc:
            last_error = exc
            continue
    if last_error:
        raise last_error
    raise FileNotFoundError('ROADMAP_AGI_FRONTS.md not found in configured candidates')


def _read_text() -> str:
    return _resolve_path().read_text(encoding='utf-8')


def _empty_counters() -> dict[str, int]:
    return {'feito': 0, 'em_andamento': 0, 'pendente': 0}


def _parse_status_line(text: str) -> dict[str, Any]:
    raw = text.strip()
    m = PERCENT_PAT.search(raw)
    pct = int(m.group(1)) if m else None
    if 'FEITO' in raw:
        norm = 'done'
    elif 'PENDENTE' in raw:
        norm = 'pending'
    elif 'EM ANDAMENTO' in raw:
        norm = 'in_progress'
    elif pct is not None:
        norm = 'done' if pct >= 100 else ('pending' if pct <= 0 else 'in_progress')
    else:
        norm = 'unknown'
    return {'raw': raw, 'percent': pct, 'normalized': norm}


def _bucket_for_heading(line: str) -> tuple[str, str] | None:
    s = line.strip()
    if s.startswith('## Front ') and ' = ' not in s:
        return ('front', s.removeprefix('## ').strip())
    if s.startswith('# Fase '):
        return ('phase', s.removeprefix('# ').strip())
    if s.startswith('## ') and re.match(r'^##\s+\d+(?:\.\d+)+\s+', s):
        return ('milestone', s.removeprefix('## ').strip())
    return None


def parse() -> dict[str, Any]:
    lines = _read_text().splitlines()
    overall = None
    current: tuple[str, str] | None = None
    fronts: list[dict[str, Any]] = []
    phases: list[dict[str, Any]] = []
    milestones: list[dict[str, Any]] = []

    def _target_list(kind: str) -> list[dict[str, Any]]:
        return {'front': fronts, 'phase': phases, 'milestone': milestones}[kind]

    for idx, line in enumerate(lines, start=1):
        if 'Status geral do roadmap:' in line and overall is None:
            m = PERCENT_PAT.search(line)
            overall = int(m.group(1)) if m else None
        bucket = _bucket_for_heading(line)
        if bucket:
            kind, title = bucket
            rec = {'title': title, 'line': idx, 'status': None, 'items': _empty_counters()}
            _target_list(kind).append(rec)
            current = (kind, title)
            continue
        sm = STATUS_PAT.search(line.strip())
        if sm and current:
            kind, title = current
            lst = _target_list(kind)
            if lst and lst[-1]['title'] == title and lst[-1]['status'] is None:
                lst[-1]['status'] = _parse_status_line(sm.group(1))
            continue
        im = ITEM_PAT.search(line)
        if im and current:
            token = im.group(1)
            kind, title = current
            lst = _target_list(kind)
            if lst and lst[-1]['title'] == title:
                if token.startswith('FEITO'):
                    lst[-1]['items']['feito'] += 1
                elif token.startswith('PENDENTE'):
                    lst[-1]['items']['pendente'] += 1
                else:
                    lst[-1]['items']['em_andamento'] += 1

    return {
        'ok': True,
        'path': str(_resolve_path()),
        'overall_percent': overall,
        'fronts': fronts,
        'phases': phases,
        'milestones': milestones,
    }


def _aggregate_evidence(data: dict[str, Any]) -> tuple[dict[str, dict[str, int]], dict[str, dict[str, int]]]:
    fronts = data.get('fronts') or []
    phases = data.get('phases') or []
    milestones = data.get('milestones') or []
    front_buckets = {x.get('title'): _empty_counters() for x in fronts}
    phase_buckets = {x.get('title'): _empty_counters() for x in phases}

    events = sorted(
        [(x.get('line'), 'phase', x.get('title')) for x in phases]
        + [(x.get('line'), 'front', x.get('title')) for x in fronts]
        + [(x.get('line'), 'milestone', x.get('title')) for x in milestones],
        key=lambda x: (int(x[0] or 0), {'phase': 0, 'front': 1, 'milestone': 2}.get(x[1], 9)),
    )
    milestone_map = {x.get('title'): x for x in milestones}
    current_phase = None
    current_front = None
    for _, kind, title in events:
        if kind == 'phase':
            current_phase = title
        elif kind == 'front':
            current_front = title
        elif kind == 'milestone':
            items = (milestone_map.get(title) or {}).get('items') or _empty_counters()
            if current_phase in phase_buckets:
                for k in phase_buckets[current_phase]:
                    phase_buckets[current_phase][k] += int(items.get(k) or 0)
            if current_front in front_buckets:
                for k in front_buckets[current_front]:
                    front_buckets[current_front][k] += int(items.get(k) or 0)
    return front_buckets, phase_buckets


def macro_status() -> dict[str, Any]:
    data = parse()
    front_buckets, phase_buckets = _aggregate_evidence(data)
    return {
        'ok': True,
        'path': data.get('path'),
        'overall_percent': data.get('overall_percent'),
        'fronts': [
            {
                'title': x.get('title'),
                'percent': (x.get('status') or {}).get('percent'),
                'status': (x.get('status') or {}).get('normalized'),
                'evidence_counts': front_buckets.get(x.get('title'), _empty_counters()),
            }
            for x in (data.get('fronts') or [])
        ],
        'phases': [
            {
                'title': x.get('title'),
                'percent': (x.get('status') or {}).get('percent'),
                'status': (x.get('status') or {}).get('normalized'),
                'evidence_counts': phase_buckets.get(x.get('title'), _empty_counters()),
            }
            for x in (data.get('phases') or [])
        ],
    }


def item_summary() -> dict[str, Any]:
    data = parse()
    totals = _empty_counters()
    for section in (data.get('milestones') or []):
        items = section.get('items') or {}
        for k in totals:
            totals[k] += int(items.get(k) or 0)
    total_items = sum(totals.values())
    completion_rate = round(float(totals['feito']) / max(1, total_items), 4)
    return {
        'ok': True,
        'path': data.get('path'),
        'totals': totals,
        'total_items': total_items,
        'completion_rate': completion_rate,
        'milestones': [
            {
                'title': x.get('title'),
                'line': x.get('line'),
                'status': x.get('status'),
                'items': x.get('items'),
            }
            for x in (data.get('milestones') or [])
        ],
    }


def scorecard() -> dict[str, Any]:
    macro = macro_status()
    return {
        'ok': True,
        'overall_percent': macro.get('overall_percent'),
        'front_scores': [
            {
                'title': x.get('title'),
                'score': int(x.get('percent') or 0),
                'status': x.get('status'),
                'evidence_counts': x.get('evidence_counts') or _empty_counters(),
            }
            for x in (macro.get('fronts') or [])
        ],
        'scoring_note': 'Score atual é derivado dos percentuais explícitos do roadmap e das contagens de evidência do próprio arquivo. Vinculação mais forte a benchmarks depende de ampliar a evidência pública e interna por front.',
    }
