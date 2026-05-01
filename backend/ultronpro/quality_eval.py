from __future__ import annotations

import os
import json
from pathlib import Path
from typing import Any

LOG_PATH = Path(__file__).resolve().parent.parent / 'data' / 'quality_eval.jsonl'


def _clip01(v: float) -> float:
    return max(0.0, min(1.0, float(v)))


def _has_gap_language(answer: str) -> bool:
    a = str(answer or '').lower()
    return any(x in a for x in ['não sei', 'nao sei', 'falt', 'incerteza', 'não encontrei', 'nao encontrei', 'lacuna'])


def _needs_external_verification(meta: dict[str, Any]) -> bool:
    keys = {
        'ground_truth',
        'gold_answer',
        'expected_answer',
        'external_benchmark_id',
        'benchmark_id',
        'external_benchmark_item',
        'benchmark_item',
        'code_validation',
        'source_validation',
        'independent_sources',
        'cross_modal',
    }
    return any(k in meta for k in keys)


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
    groundedness = 0.35
    relevance = 0.45
    context_fitness = 0.65
    self_critique = 0.35
    coverage_score = 0.0
    source_diversity = 0.0
    redundancy_score = 0.0

    external_verification: dict[str, Any] | None = None
    factual_eval: dict[str, Any] = {}
    cross_modal: dict[str, Any] = {}
    factual_override_score: float | None = None

    if _needs_external_verification(meta):
        try:
            from ultronpro import external_benchmarks
            external_verification = external_benchmarks.verify_response_against_reality(
                query=q,
                answer=a,
                context_meta=meta,
                tool_outputs=tools,
                record=bool(meta.get('record_external_verification', True)),
            )
            factual_eval = external_verification.get('factual_eval') if isinstance(external_verification.get('factual_eval'), dict) else {}
            cross_modal = external_verification.get('cross_modal') if isinstance(external_verification.get('cross_modal'), dict) else {}
        except Exception as e:
            external_verification = {'ok': False, 'error': f'external_verification_failed:{type(e).__name__}'}

    if factual_eval.get('has_ground_truth'):
        is_correct = bool(factual_eval.get('factual_correct'))
        if os.getenv('ULTRON_TRACE_ANCHOR') == '1':
            print(
                "DEBUG_ANCHOR: "
                f"truth='{factual_eval.get('gold_answer')}' "
                f"vs answer='{a[:50]}' -> is_correct={is_correct}"
            )
        if is_correct:
            factual_override_score = float(factual_eval.get('factual_score') or 0.975)
            task_success = factual_override_score
            groundedness = factual_override_score
            relevance = factual_override_score
            context_fitness = max(context_fitness, 0.9)
            self_critique = max(self_critique, 0.9)
        else:
            alerts = list(dict.fromkeys((factual_eval.get('alerts') or []) + ['external_anchor_failure']))
            if cross_modal.get('needs_revision'):
                alerts.append('cross_modal_validation_failed')
            return {
                'dimensions': {k: 0.1 for k in ['task_success', 'groundedness', 'relevance', 'context_fitness', 'self_critique']},
                'composite_score': 0.1,
                'alerts': alerts,
                'threshold_breached': True,
                'is_anchor_failure': True,
                'external_verification': external_verification,
                'factual_eval': factual_eval,
                'cross_modal': cross_modal,
                'hindsight_replay': (external_verification or {}).get('hindsight_replay') if isinstance(external_verification, dict) else None,
            }

    if not factual_eval.get('has_ground_truth'):
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

    if factual_override_score is not None:
        composite = max(composite, round(_clip01(factual_override_score), 4))
    if cross_modal:
        if bool(cross_modal.get('needs_revision')):
            alerts.append('cross_modal_validation_failed')
            composite = min(composite, 0.35)
        elif int(cross_modal.get('unavailable_count') or 0) > 0:
            alerts.append('cross_modal_validation_unavailable')

    alerts = list(dict.fromkeys(alerts))
    threshold_breached = composite < 0.6
    if cross_modal:
        threshold_breached = threshold_breached or bool(cross_modal.get('needs_revision'))

    out = {
        'dimensions': dimensions,
        'composite_score': composite,
        'alerts': alerts,
        'threshold_breached': threshold_breached,
        'rag_diagnostics': {
            'coverage_score': round(_clip01(coverage_score), 4),
            'source_diversity': round(_clip01(source_diversity), 4),
            'redundancy_score': round(_clip01(redundancy_score), 4),
            'selected_count': int(rag_diversity.get('selected_count') or 0) if rag_diversity else 0,
            'candidate_count': int(rag_diversity.get('candidate_count') or 0) if rag_diversity else 0,
        },
    }
    if external_verification is not None:
        out['external_verification'] = external_verification
        out['factual_eval'] = factual_eval
        out['cross_modal'] = cross_modal
    return out


def persist_eval(row: dict[str, Any]) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open('a', encoding='utf-8') as f:
        f.write(json.dumps(row, ensure_ascii=False) + '\n')
    try:
        qeval = row.get('quality_eval') if isinstance(row.get('quality_eval'), dict) else {}
        if qeval:
            from ultronpro import rl_policy
            kind = str(row.get('strategy') or row.get('action_kind') or row.get('task_type') or 'quality_eval')[:80]
            context = str(row.get('task_type') or row.get('context_profile') or 'general')[:60]
            rl_policy.observe_quality_eval(kind=kind, context=context, quality_eval=qeval)
    except Exception:
        pass
