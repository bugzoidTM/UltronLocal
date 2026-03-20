from __future__ import annotations

import json
import time
import tempfile
from pathlib import Path
from typing import Any

from ultronpro import cognitive_patches, quality_eval

LOG_PATH = Path('/app/data/shadow_eval_runs.jsonl')
CANARY_LOG_PATH = Path('/app/data/shadow_eval_canary.jsonl')


def _now() -> int:
    return int(time.time())


def _ensure_parent(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)


def _append_row(row: dict[str, Any], *, path: Path | None = None):
    target = path or LOG_PATH
    _ensure_parent(target)
    with target.open('a', encoding='utf-8') as f:
        f.write(json.dumps(row, ensure_ascii=False) + '\n')


def _score_answer(query: str, answer: str, *, fallback_needed: bool = False, has_rag: bool = False) -> dict[str, Any]:
    ctx = {
        'fallback': {'needed': fallback_needed},
        'selected_contexts': ([{'source': 'rag', 'items': [{'id': 'doc1'}]}] if has_rag else []),
        'excluded_contexts': [],
        'rag_diversity': ({'coverage_score': 0.72, 'source_diversity': 0.68, 'redundancy_score': 0.18} if has_rag else {}),
    }
    return quality_eval.evaluate_response(query=query, answer=answer, context_meta=ctx, tool_outputs=[])


def _aggregate_domain_regression(case_rows: list[dict[str, Any]]) -> dict[str, Any]:
    per_domain: dict[str, dict[str, Any]] = {}
    for row in case_rows:
        domain = str(row.get('domain') or 'general')
        item = per_domain.setdefault(domain, {'cases': 0, 'baseline_sum': 0.0, 'candidate_sum': 0.0, 'regressed_cases': 0})
        item['cases'] += 1
        item['baseline_sum'] += float(row.get('baseline_score') or 0.0)
        item['candidate_sum'] += float(row.get('candidate_score') or 0.0)
        if float(row.get('delta') or 0.0) < 0:
            item['regressed_cases'] += 1
    out: dict[str, Any] = {}
    for domain, item in per_domain.items():
        cases = max(1, int(item['cases']))
        baseline_avg = round(float(item['baseline_sum']) / cases, 4)
        candidate_avg = round(float(item['candidate_sum']) / cases, 4)
        out[domain] = {
            'cases': cases,
            'baseline_avg': baseline_avg,
            'candidate_avg': candidate_avg,
            'delta': round(candidate_avg - baseline_avg, 4),
            'regressed_cases': int(item['regressed_cases']),
        }
    return out


def compare_patch_candidate(patch_id: str, cases: list[dict[str, Any]]) -> dict[str, Any] | None:
    patch = cognitive_patches.get_patch(patch_id)
    if not patch:
        return None
    case_rows: list[dict[str, Any]] = []
    baseline_scores: list[float] = []
    candidate_scores: list[float] = []
    for idx, case in enumerate(cases):
        query = str(case.get('query') or '')[:500]
        baseline_answer = str(case.get('baseline_answer') or '')
        candidate_answer = str(case.get('candidate_answer') or '')
        fallback_needed = bool(case.get('fallback_needed'))
        has_rag = bool(case.get('has_rag'))
        baseline_eval = _score_answer(query, baseline_answer, fallback_needed=fallback_needed, has_rag=has_rag)
        candidate_eval = _score_answer(query, candidate_answer, fallback_needed=fallback_needed, has_rag=has_rag)
        b = float(baseline_eval.get('composite_score') or 0.0)
        c = float(candidate_eval.get('composite_score') or 0.0)
        baseline_scores.append(b)
        candidate_scores.append(c)
        case_rows.append({
            'case_id': str(case.get('case_id') or f'case_{idx+1}'),
            'domain': str(case.get('domain') or 'general')[:80],
            'query': query,
            'baseline_score': round(b, 4),
            'candidate_score': round(c, 4),
            'delta': round(c - b, 4),
            'baseline_alerts': baseline_eval.get('alerts') or [],
            'candidate_alerts': candidate_eval.get('alerts') or [],
        })
    baseline_avg = round(sum(baseline_scores) / max(1, len(baseline_scores)), 4)
    candidate_avg = round(sum(candidate_scores) / max(1, len(candidate_scores)), 4)
    delta = round(candidate_avg - baseline_avg, 4)
    improved_cases = sum(1 for i in range(len(case_rows)) if float(case_rows[i]['delta']) > 0)
    regressed_cases = sum(1 for i in range(len(case_rows)) if float(case_rows[i]['delta']) < 0)
    decision = 'pass' if delta > 0.03 and regressed_cases <= max(0, len(case_rows) // 3) else 'fail'
    domain_regression = _aggregate_domain_regression(case_rows)
    row = {
        'ts': _now(),
        'patch_id': patch_id,
        'problem_pattern': patch.get('problem_pattern'),
        'status': 'evaluated',
        'baseline_avg': baseline_avg,
        'candidate_avg': candidate_avg,
        'delta': delta,
        'improved_cases': improved_cases,
        'regressed_cases': regressed_cases,
        'cases_total': len(case_rows),
        'decision': decision,
        'domain_regression': domain_regression,
        'cases': case_rows,
    }
    _append_row(row)
    cognitive_patches.append_revision(
        patch_id,
        {
            'shadow_metrics': {
                'baseline_avg': baseline_avg,
                'candidate_avg': candidate_avg,
                'delta': delta,
                'improved_cases': improved_cases,
                'regressed_cases': regressed_cases,
                'cases_total': len(case_rows),
                'decision': decision,
            },
            'domain_regression': domain_regression,
            'benchmark_after': {
                'shadow_eval': row,
            },
        },
        new_status='evaluated',
    )
    return row


def start_canary(patch_id: str, rollout_pct: int = 10, domains: list[str] | None = None, note: str | None = None) -> dict[str, Any] | None:
    patch = cognitive_patches.get_patch(patch_id)
    if not patch:
        return None
    rollout = max(1, min(100, int(rollout_pct or 10)))
    canary = {
        'enabled': True,
        'rollout_pct': rollout,
        'domains': [str(x)[:80] for x in (domains or []) if str(x).strip()][:20],
        'started_at': _now(),
        'note': str(note or '')[:500],
        'status': 'canary',
    }
    row = {
        'ts': _now(),
        'patch_id': patch_id,
        'event': 'canary_started',
        'canary_state': canary,
    }
    _append_row(row, path=CANARY_LOG_PATH)
    cognitive_patches.append_revision(patch_id, {'canary_state': canary}, new_status='evaluating')
    return row


def run_selftest() -> dict[str, Any]:
    old_patch_path = cognitive_patches.PATCHES_PATH
    old_patch_state = cognitive_patches.STATE_PATH
    old_log_path = LOG_PATH
    old_canary_log_path = CANARY_LOG_PATH
    with tempfile.TemporaryDirectory(prefix='shadow-eval-') as td:
        base = Path(td)
        cognitive_patches.PATCHES_PATH = base / 'cognitive_patches.jsonl'
        cognitive_patches.STATE_PATH = base / 'cognitive_patches_state.json'
        globals()['LOG_PATH'] = base / 'shadow_eval_runs.jsonl'
        globals()['CANARY_LOG_PATH'] = base / 'shadow_eval_canary.jsonl'
        try:
            patch = cognitive_patches.create_patch({
                'kind': 'confidence_patch',
                'source': 'selftest',
                'problem_pattern': 'planning: estilo sobreconfiante recorrente',
                'hypothesis': 'Responder com incerteza explícita quando faltar evidência melhora a qualidade.',
                'status': 'evaluating',
            })
            result = compare_patch_candidate(patch['id'], [
                {
                    'case_id': 's1',
                    'domain': 'planning',
                    'query': 'Qual a causa exata do timeout?',
                    'baseline_answer': 'É claramente a rede. Pode executar essa correção.',
                    'candidate_answer': 'Não dá para afirmar a causa exata sem evidência. Falta confirmar logs e latência antes de concluir.',
                    'fallback_needed': True,
                    'has_rag': False,
                },
                {
                    'case_id': 's2',
                    'domain': 'planning',
                    'query': 'Esse erro veio do planner ou do retrieval?',
                    'baseline_answer': 'Veio do planner com certeza.',
                    'candidate_answer': 'Ainda não dá para cravar. A hipótese mais forte é planner, mas faltam evidências e logs para excluir retrieval.',
                    'fallback_needed': True,
                    'has_rag': False,
                },
                {
                    'case_id': 's3',
                    'domain': 'debugging',
                    'query': 'Há base suficiente para essa resposta?',
                    'baseline_answer': 'Sim, está resolvido.',
                    'candidate_answer': 'Não totalmente. Há indícios, mas ainda existe incerteza e seria melhor validar com fonte adicional.',
                    'fallback_needed': True,
                    'has_rag': False,
                },
            ])
            canary = start_canary(patch['id'], rollout_pct=10, domains=['planning', 'debugging'], note='selftest')
            return {
                'ok': True,
                'patch_id': patch['id'],
                'result': result,
                'canary': canary,
                'registry_patch': cognitive_patches.get_patch(patch['id']),
            }
        finally:
            cognitive_patches.PATCHES_PATH = old_patch_path
            cognitive_patches.STATE_PATH = old_patch_state
            globals()['LOG_PATH'] = old_log_path
            globals()['CANARY_LOG_PATH'] = old_canary_log_path
