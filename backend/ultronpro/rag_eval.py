from __future__ import annotations

from typing import Any

from ultronpro import rag_router, rag_eval_store


def _avg(nums: list[float]) -> float:
    vals = [float(x) for x in nums if isinstance(x, (int, float))]
    if not vals:
        return 0.0
    return round(sum(vals) / len(vals), 4)


async def evaluate_queries(items: list[dict[str, Any]], top_k: int = 5) -> dict[str, Any]:
    rows = []
    for item in items or []:
        query = str(item.get('query') or '').strip()
        expected_domains = list(item.get('expected_domains') or [])
        task_type = str(item.get('task_type') or 'general')
        if not query:
            continue
        routed = await rag_router.search_routed(query=query, task_type=task_type, top_k=top_k)
        got_domains = list(routed.get('domains') or [])
        results = list(routed.get('results') or [])
        diversity = dict(routed.get('diversity') or {})
        useful_hits = sum(1 for r in results if float(r.get('adjusted_router_score') or r.get('router_score') or r.get('score') or 0.0) >= 0.2)
        domain_coverage = 0.0
        avg_result_score = _avg([float(r.get('adjusted_router_score') or r.get('router_score') or r.get('score') or 0.0) for r in results]) if results else 0.0
        unique_sources = len({str(r.get('source_id') or '') for r in results}) if results else 0
        unique_domains = len({str(r.get('domain') or '') for r in results}) if results else 0
        if expected_domains:
            domain_coverage = len(set(expected_domains) & set(got_domains)) / max(1, len(set(expected_domains)))
        rows.append({
            'query': query,
            'task_type': task_type,
            'expected_domains': expected_domains,
            'got_domains': got_domains,
            'domain_coverage': round(domain_coverage, 4),
            'results_count': len(results),
            'useful_hits': useful_hits,
            'unique_sources': unique_sources,
            'unique_domains': unique_domains,
            'avg_result_score': avg_result_score,
            'top_router_score': max([float(r.get('adjusted_router_score') or r.get('router_score') or r.get('score') or 0.0) for r in results], default=0.0),
            'search_plan': routed.get('search_plan') or [],
            'diversity': diversity,
        })

    report = {
        'ok': True,
        'n': len(rows),
        'avg_domain_coverage': _avg([r.get('domain_coverage') for r in rows]),
        'avg_results_count': _avg([r.get('results_count') for r in rows]),
        'avg_useful_hits': _avg([r.get('useful_hits') for r in rows]),
        'avg_unique_sources': _avg([r.get('unique_sources') for r in rows]),
        'avg_unique_domains': _avg([r.get('unique_domains') for r in rows]),
        'avg_result_score': _avg([r.get('avg_result_score') for r in rows]),
        'avg_top_router_score': _avg([r.get('top_router_score') for r in rows]),
        'rows': rows,
    }
    try:
        rag_eval_store.persist_run(report)
    except Exception:
        pass
    return report
