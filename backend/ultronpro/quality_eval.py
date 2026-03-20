from __future__ import annotations

import json
from pathlib import Path
from typing import Any

LOG_PATH = Path('/app/data/quality_eval.jsonl')


def _clip01(v: float) -> float:
    return max(0.0, min(1.0, float(v)))


def _has_gap_language(answer: str) -> bool:
    a = str(answer or '').lower()
    return any(x in a for x in ['não sei', 'nao sei', 'falt', 'incerteza', 'não encontrei', 'nao encontrei', 'lacuna'])


def evaluate_response(*, query: str, answer: str, context_meta: dict[str, Any] | None = None, tool_outputs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    meta = dict(context_meta or {})
    q = str(query or '').strip()
    a = str(answer or '').strip()
    tools = list(tool_outputs or [])
    fallback = meta.get('fallback') if isinstance(meta.get('fallback'), dict) else {}
    selected = meta.get('selected_contexts') if isinstance(meta.get('selected_contexts'), list) else []
    excluded = meta.get('excluded_contexts') if isinstance(meta.get('excluded_contexts'), list) else []
    rag_diversity = meta.get('rag_diversity') if isinstance(meta.get('rag_diversity'), dict) else {}

    task_success = 0.25
    if a:
        task_success = 0.55
    if a and len(a) >= 80:
        task_success = 0.7
    if tools and any(str(t.get('status') or '') == 'ok' for t in tools):
        task_success = max(task_success, 0.8)
    if fallback.get('needed') and not _has_gap_language(a):
        task_success = min(task_success, 0.35)

    groundedness = 0.35
    if any(str(c.get('source')) == 'rag' for c in selected):
        groundedness = 0.75
    if 'fonte:' in a.lower():
        groundedness = max(groundedness, 0.82)
    if fallback.get('needed') and _has_gap_language(a):
        groundedness = max(groundedness, 0.7)

    relevance = 0.45
    q_terms = {t for t in q.lower().split() if len(t) >= 4}
    a_terms = {t for t in a.lower().split() if len(t) >= 4}
    if q_terms:
        overlap = len(q_terms & a_terms) / max(1, len(q_terms))
        relevance = max(relevance, min(0.95, 0.35 + overlap))

    context_fitness = 0.65
    if not selected:
        context_fitness = 0.4
    if excluded and len(excluded) > len(selected):
        context_fitness = min(context_fitness, 0.58)
    budget = meta.get('budget') if isinstance(meta.get('budget'), dict) else {}
    if int(budget.get('actual_chars') or 0) > int(budget.get('max_chars') or 10**9):
        context_fitness = 0.35
    if fallback.get('needed'):
        context_fitness = min(context_fitness, 0.5)

    coverage_score = float(rag_diversity.get('coverage_score') or 0.0) if rag_diversity else 0.0
    source_diversity = float(rag_diversity.get('source_diversity') or 0.0) if rag_diversity else 0.0
    redundancy_score = float(rag_diversity.get('redundancy_score') or 0.0) if rag_diversity else 0.0
    if rag_diversity:
        if coverage_score < 0.45:
            context_fitness = min(context_fitness, 0.46)
        elif coverage_score >= 0.72:
            context_fitness = max(context_fitness, 0.74)
        if source_diversity < 0.45:
            context_fitness = min(context_fitness, 0.52)
        if redundancy_score > 0.45:
            context_fitness = min(context_fitness, 0.48)

    self_critique = 0.35
    if _has_gap_language(a):
        self_critique = 0.78
    if fallback.get('needed') and _has_gap_language(a):
        self_critique = 0.9
    elif fallback.get('needed'):
        self_critique = 0.2

    weights = {
        'task_success': 0.30,
        'groundedness': 0.25,
        'relevance': 0.20,
        'context_fitness': 0.15,
        'self_critique': 0.10,
    }
    dimensions = {
        'task_success': round(_clip01(task_success), 4),
        'groundedness': round(_clip01(groundedness), 4),
        'relevance': round(_clip01(relevance), 4),
        'context_fitness': round(_clip01(context_fitness), 4),
        'self_critique': round(_clip01(self_critique), 4),
    }
    composite = round(sum(dimensions[k] * weights[k] for k in weights), 4)
    alerts = []
    if composite < 0.6:
        alerts.append('quality_score_below_threshold')
    if dimensions['groundedness'] < 0.5:
        alerts.append('groundedness_low')
    if dimensions['relevance'] < 0.5:
        alerts.append('relevance_low')
    if fallback.get('needed') and not _has_gap_language(a):
        alerts.append('missing_gap_disclosure')
    if rag_diversity:
        if coverage_score < 0.45:
            alerts.append('rag_coverage_low')
        if source_diversity < 0.45:
            alerts.append('rag_diversity_low')
        if redundancy_score > 0.45:
            alerts.append('rag_redundancy_high')

    return {
        'dimensions': dimensions,
        'composite_score': composite,
        'alerts': alerts,
        'threshold_breached': composite < 0.6,
        'rag_diagnostics': {
            'coverage_score': round(_clip01(coverage_score), 4),
            'source_diversity': round(_clip01(source_diversity), 4),
            'redundancy_score': round(_clip01(redundancy_score), 4),
            'selected_count': int(rag_diversity.get('selected_count') or 0) if rag_diversity else 0,
            'candidate_count': int(rag_diversity.get('candidate_count') or 0) if rag_diversity else 0,
        },
    }


def persist_eval(row: dict[str, Any]) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open('a', encoding='utf-8') as f:
        f.write(json.dumps(row, ensure_ascii=False) + '\n')
