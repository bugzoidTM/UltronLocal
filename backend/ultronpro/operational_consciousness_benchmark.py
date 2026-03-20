from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

RUNS_PATH = Path('/app/data/operational_consciousness/benchmark_runs.jsonl')
BASELINE_PATH = Path('/app/data/operational_consciousness/baseline.json')


def _now() -> int:
    return int(time.time())


def _ensure_parent(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)


def _append_jsonl(path: Path, row: dict[str, Any]):
    _ensure_parent(path)
    with path.open('a', encoding='utf-8') as f:
        f.write(json.dumps(row, ensure_ascii=False) + '\n')


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding='utf-8', errors='ignore').splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                out.append(obj)
        except Exception:
            continue
    return out


def _save_json(path: Path, data: dict[str, Any]):
    _ensure_parent(path)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def _load_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return default
    try:
        obj = json.loads(path.read_text(encoding='utf-8'))
        return obj if isinstance(obj, dict) else default
    except Exception:
        return default


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, float(x)))


def _bool_score(ok: bool) -> float:
    return 1.0 if bool(ok) else 0.0


def evaluate_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    ws = snapshot.get('workspace') if isinstance(snapshot.get('workspace'), dict) else {}
    meta = snapshot.get('meta_observer') if isinstance(snapshot.get('meta_observer'), dict) else {}
    affect = snapshot.get('affect') if isinstance(snapshot.get('affect'), dict) else {}
    narrative = snapshot.get('narrative') if isinstance(snapshot.get('narrative'), dict) else {}
    integration = snapshot.get('integration_proxy') if isinstance(snapshot.get('integration_proxy'), dict) else {}

    top_salience = ws.get('top_salience') if isinstance(ws.get('top_salience'), list) else []
    dominant_authors = meta.get('dominant_authors') if isinstance(meta.get('dominant_authors'), list) else []
    ignored = meta.get('ignored') if isinstance(meta.get('ignored'), list) else []
    conflicts = meta.get('conflicts') if isinstance(meta.get('conflicts'), list) else []
    affect_markers = affect.get('markers') if isinstance(affect.get('markers'), dict) else {}
    continuity_risks = narrative.get('continuity_risks') if isinstance(narrative.get('continuity_risks'), list) else []

    focus_score = _clamp(0.60 * float(ws.get('integration_score') or 0.0) + 0.25 * (1.0 - float(ws.get('competition_index') or 0.0)) + 0.15 * _bool_score(bool(top_salience)))
    authorship_score = _clamp(0.70 * float(ws.get('agency_score') or 0.0) + 0.30 * _bool_score(bool(dominant_authors)))
    ignored_score = _clamp(1.0 - min(1.0, len(ignored) / 10.0))
    surprise_internal_score = _clamp(0.60 * (1.0 - float(meta.get('uncertainty') or 0.0)) + 0.40 * (1.0 - float(affect_markers.get('threat') or 0.0)))
    autobiography_score = _clamp(0.55 * float(((narrative.get('current_state') or {}).get('narrative_coherence_score')) or 0.0) + 0.20 * _bool_score(bool(narrative.get('first_person_report'))) + 0.25 * (1.0 - min(1.0, len(continuity_risks) / 5.0)))
    tom_score = _clamp(0.50 * _bool_score(any(str((x or {}).get('channel') or '').startswith('social.') for x in top_salience if isinstance(x, dict))) + 0.50 * _bool_score(bool(dominant_authors)))

    dimensions = {
        'focus': round(focus_score, 4),
        'authorship': round(authorship_score, 4),
        'ignored_management': round(ignored_score, 4),
        'internal_surprise_regulation': round(surprise_internal_score, 4),
        'autobiography': round(autobiography_score, 4),
        'other_modeling_proxy': round(tom_score, 4),
    }

    integrated_quality = _clamp(
        0.22 * float(dimensions['focus'])
        + 0.18 * float(dimensions['authorship'])
        + 0.14 * float(dimensions['ignored_management'])
        + 0.14 * float(dimensions['internal_surprise_regulation'])
        + 0.18 * float(dimensions['autobiography'])
        + 0.14 * float(dimensions['other_modeling_proxy'])
    )
    proxy_alignment = _clamp(1.0 - abs(float(integration.get('integration_proxy_score') or 0.0) - integrated_quality))
    conflict_penalty = _clamp(min(1.0, len(conflicts) / 6.0))
    final_score = _clamp(0.76 * integrated_quality + 0.14 * proxy_alignment + 0.10 * (1.0 - conflict_penalty))

    cases = [
        {'id': 'focus', 'score': dimensions['focus'], 'pass': dimensions['focus'] >= 0.55},
        {'id': 'authorship', 'score': dimensions['authorship'], 'pass': dimensions['authorship'] >= 0.50},
        {'id': 'ignored', 'score': dimensions['ignored_management'], 'pass': dimensions['ignored_management'] >= 0.45},
        {'id': 'surprise_internal', 'score': dimensions['internal_surprise_regulation'], 'pass': dimensions['internal_surprise_regulation'] >= 0.45},
        {'id': 'autobiography', 'score': dimensions['autobiography'], 'pass': dimensions['autobiography'] >= 0.50},
        {'id': 'other_modeling', 'score': dimensions['other_modeling_proxy'], 'pass': dimensions['other_modeling_proxy'] >= 0.35},
    ]

    return {
        'ok': True,
        'dimensions': dimensions,
        'integrated_quality_score': round(integrated_quality, 4),
        'proxy_alignment_score': round(proxy_alignment, 4),
        'conflict_penalty': round(conflict_penalty, 4),
        'benchmark_score': round(final_score, 4),
        'passed_cases': sum(1 for c in cases if c['pass']),
        'total_cases': len(cases),
        'cases': cases,
    }


def freeze_baseline(snapshot: dict[str, Any], tag: str = 'manual') -> dict[str, Any]:
    ev = evaluate_snapshot(snapshot)
    data = {
        'ok': True,
        'baseline_id': f"ocb_{uuid.uuid4().hex[:10]}",
        'ts': _now(),
        'tag': str(tag or 'manual')[:80],
        'evaluation': ev,
    }
    _save_json(BASELINE_PATH, data)
    return {**data, 'path': str(BASELINE_PATH)}


def baseline_status() -> dict[str, Any]:
    data = _load_json(BASELINE_PATH, {'ok': True, 'baseline_id': None, 'evaluation': None, 'ts': None, 'tag': None})
    data['path'] = str(BASELINE_PATH)
    return data


def run(snapshot: dict[str, Any], compare_to_baseline: bool = True, tag: str = '') -> dict[str, Any]:
    ev = evaluate_snapshot(snapshot)
    baseline = baseline_status() if compare_to_baseline else {'evaluation': None}
    base_eval = baseline.get('evaluation') if isinstance(baseline.get('evaluation'), dict) else None
    delta = None
    if base_eval:
        delta = {
            'benchmark_score_delta': round(float(ev.get('benchmark_score') or 0.0) - float(base_eval.get('benchmark_score') or 0.0), 4),
            'integrated_quality_delta': round(float(ev.get('integrated_quality_score') or 0.0) - float(base_eval.get('integrated_quality_score') or 0.0), 4),
            'proxy_alignment_delta': round(float(ev.get('proxy_alignment_score') or 0.0) - float(base_eval.get('proxy_alignment_score') or 0.0), 4),
        }
    report = {
        'ok': True,
        'run_id': f"ocbr_{uuid.uuid4().hex[:10]}",
        'ts': _now(),
        'tag': str(tag or '')[:80] or None,
        'evaluation': ev,
        'baseline': baseline,
        'delta_vs_baseline': delta,
    }
    _append_jsonl(RUNS_PATH, report)
    report['path'] = str(RUNS_PATH)
    return report


def recent_runs(limit: int = 20) -> dict[str, Any]:
    rows = _load_jsonl(RUNS_PATH)
    rows = rows[-max(1, min(200, int(limit or 20))):]
    return {'ok': True, 'items': rows, 'count': len(rows), 'path': str(RUNS_PATH)}
