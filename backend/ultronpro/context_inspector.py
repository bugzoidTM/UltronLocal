from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

CONTEXT_LOG = Path(__file__).resolve().parent.parent / 'data' / 'context_metrics.jsonl'
QUALITY_LOG = Path(__file__).resolve().parent.parent / 'data' / 'quality_eval.jsonl'
RAG_EVAL_LOG = Path(__file__).resolve().parent.parent / 'data' / 'rag_eval_runs.jsonl'


def _read_jsonl(path: Path, limit: int = 200) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        with path.open('r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        return []
    if limit > 0:
        return rows[-limit:]
    return rows


def _avg(nums: list[float]) -> float | None:
    vals = [float(x) for x in nums if isinstance(x, (int, float))]
    if not vals:
        return None
    return round(sum(vals) / len(vals), 4)


def _count_alert(rows: list[dict[str, Any]], alert_name: str) -> int:
    n = 0
    for r in rows:
        q = r.get('quality_eval') if isinstance(r.get('quality_eval'), dict) else {}
        alerts = q.get('alerts') if isinstance(q.get('alerts'), list) else []
        if alert_name in alerts:
            n += 1
    return n


def _build_rag_eval_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            'runs': 0,
            'avg_domain_coverage': None,
            'avg_results_count': None,
            'avg_useful_hits': None,
            'avg_top_router_score': None,
            'recent_low_coverage_cases': [],
        }

    low_cov = []
    for run in rows[-10:]:
        for row in list(run.get('rows') or []):
            cov = row.get('domain_coverage')
            if isinstance(cov, (int, float)) and float(cov) < 0.5:
                low_cov.append({
                    'ts': run.get('ts'),
                    'query': str(row.get('query') or '')[:180],
                    'task_type': row.get('task_type'),
                    'expected_domains': row.get('expected_domains') or [],
                    'got_domains': row.get('got_domains') or [],
                    'domain_coverage': cov,
                })
            if len(low_cov) >= 10:
                break
        if len(low_cov) >= 10:
            break

    return {
        'runs': len(rows),
        'avg_domain_coverage': _avg([r.get('avg_domain_coverage') for r in rows]),
        'avg_results_count': _avg([r.get('avg_results_count') for r in rows]),
        'avg_useful_hits': _avg([r.get('avg_useful_hits') for r in rows]),
        'avg_unique_sources': _avg([r.get('avg_unique_sources') for r in rows]),
        'avg_unique_domains': _avg([r.get('avg_unique_domains') for r in rows]),
        'avg_result_score': _avg([r.get('avg_result_score') for r in rows]),
        'avg_top_router_score': _avg([r.get('avg_top_router_score') for r in rows]),
        'recent_low_coverage_cases': low_cov,
    }


def build_report(limit: int = 200) -> dict[str, Any]:
    ctx_rows = _read_jsonl(CONTEXT_LOG, limit=limit)
    qual_rows = _read_jsonl(QUALITY_LOG, limit=limit)
    rag_eval_rows = _read_jsonl(RAG_EVAL_LOG, limit=max(20, limit))

    by_profile: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_task: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in ctx_rows:
        by_profile[str(row.get('context_profile') or 'unknown')].append(row)
        by_task[str(row.get('task_type') or 'unknown')].append(row)

    profiles_summary = {}
    for profile, rows in by_profile.items():
        profiles_summary[profile] = {
            'n': len(rows),
            'avg_latency_ms': _avg([r.get('latency_ms') for r in rows]),
            'avg_planner_prompt_tokens_est': _avg([(r.get('context_metrics') or {}).get('planner_prompt_tokens_est') for r in rows if isinstance(r.get('context_metrics'), dict)]),
            'avg_synth_prompt_tokens_est': _avg([(r.get('context_metrics') or {}).get('synth_prompt_tokens_est') for r in rows if isinstance(r.get('context_metrics'), dict)]),
            'avg_selected_context_tokens_est': _avg([(r.get('context_metrics') or {}).get('selected_context_tokens_est') for r in rows if isinstance(r.get('context_metrics'), dict)]),
            'avg_excluded_context_count': _avg([(r.get('context_metrics') or {}).get('excluded_context_count') for r in rows if isinstance(r.get('context_metrics'), dict)]),
            'hard_fallback_gate_rate': round(sum(1 for r in rows if bool((r.get('context_metrics') or {}).get('hard_fallback_gate'))) / max(1, len(rows)), 4),
            'avg_quality_score': _avg([((r.get('quality_eval') or {}).get('composite_score')) for r in rows if isinstance(r.get('quality_eval'), dict)]),
        }

    tasks_summary = {}
    for task, rows in by_task.items():
        tasks_summary[task] = {
            'n': len(rows),
            'avg_latency_ms': _avg([r.get('latency_ms') for r in rows]),
            'avg_quality_score': _avg([((r.get('quality_eval') or {}).get('composite_score')) for r in rows if isinstance(r.get('quality_eval'), dict)]),
            'fallback_rate': round(sum(1 for r in rows if bool(((r.get('quality_eval') or {}).get('alerts')) and 'missing_gap_disclosure' in ((r.get('quality_eval') or {}).get('alerts') or []))) / max(1, len(rows)), 4),
        }

    poor_quality = []
    for r in sorted(ctx_rows, key=lambda x: float((((x.get('quality_eval') or {}).get('composite_score')) or 9999))):
        qev = r.get('quality_eval') if isinstance(r.get('quality_eval'), dict) else {}
        score = qev.get('composite_score')
        if isinstance(score, (int, float)) and float(score) < 0.6:
            poor_quality.append({
                'ts': r.get('ts'),
                'query': str(r.get('query') or '')[:180],
                'task_type': r.get('task_type'),
                'context_profile': r.get('context_profile'),
                'quality_score': score,
                'alerts': qev.get('alerts') or [],
            })
        if len(poor_quality) >= 10:
            break

    alerts_summary = {
        'quality_score_below_threshold': _count_alert(qual_rows, 'quality_score_below_threshold'),
        'groundedness_low': _count_alert(qual_rows, 'groundedness_low'),
        'relevance_low': _count_alert(qual_rows, 'relevance_low'),
        'missing_gap_disclosure': _count_alert(qual_rows, 'missing_gap_disclosure'),
    }

    return {
        'ok': True,
        'window': {
            'context_rows': len(ctx_rows),
            'quality_rows': len(qual_rows),
            'rag_eval_runs': len(rag_eval_rows),
            'limit': limit,
        },
        'profiles_summary': profiles_summary,
        'tasks_summary': tasks_summary,
        'alerts_summary': alerts_summary,
        'poor_quality_examples': poor_quality,
        'rag_eval_summary': _build_rag_eval_summary(rag_eval_rows),
    }
