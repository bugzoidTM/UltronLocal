from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from ultronpro import cognitive_patches, epistemic_ledger, external_benchmarks, shadow_eval

DEFAULT_THRESHOLDS: dict[str, Any] = {
    'min_delta': 0.03,
    'max_regressed_cases': 1,
    'max_domain_regression_delta': -0.02,
    'require_canary': True,
    'min_canary_rollout_pct': 5,
    'min_external_factual_accuracy': 1.0,
    'max_external_anchor_failures': 0,
    'min_external_anchor_cases': 1,
}


def evaluate_patch_for_promotion(patch_id: str, thresholds: dict[str, Any] | None = None) -> dict[str, Any] | None:
    patch = cognitive_patches.get_patch(patch_id)
    if not patch:
        return None
    # Self-calibrating: derive thresholds from experience when no override
    if thresholds:
        th = dict(DEFAULT_THRESHOLDS)
        th.update(thresholds)
    else:
        try:
            from ultronpro import self_calibrating_gate
            th = self_calibrating_gate.calibrated_thresholds()
        except Exception:
            th = dict(DEFAULT_THRESHOLDS)

    shadow_metrics = patch.get('shadow_metrics') if isinstance(patch.get('shadow_metrics'), dict) else {}
    domain_regression = patch.get('domain_regression') if isinstance(patch.get('domain_regression'), dict) else {}
    canary_state = patch.get('canary_state') if isinstance(patch.get('canary_state'), dict) else {}
    factual_gate = external_benchmarks.evaluate_patch_external_factual_evidence(patch)

    delta = float(shadow_metrics.get('delta') or 0.0)
    regressed_cases = int(shadow_metrics.get('regressed_cases') or 0)
    cases_total = int(shadow_metrics.get('cases_total') or 0)
    decision = 'hold'
    reasons: list[str] = []
    blockers: list[str] = []

    if cases_total <= 0:
        blockers.append('missing_shadow_eval_cases')
    if delta < float(th['min_delta']):
        blockers.append('delta_below_threshold')
    else:
        reasons.append('delta_ok')
    if regressed_cases > int(th['max_regressed_cases']):
        blockers.append('too_many_regressed_cases')
    else:
        reasons.append('regressed_cases_ok')

    worst_domain_delta = None
    worst_domain = None
    for domain, stats in domain_regression.items():
        d = float((stats or {}).get('delta') or 0.0)
        if worst_domain_delta is None or d < worst_domain_delta:
            worst_domain_delta = d
            worst_domain = domain
    if worst_domain_delta is not None and worst_domain_delta < float(th['max_domain_regression_delta']):
        blockers.append(f'domain_regression:{worst_domain}')
    else:
        reasons.append('domain_regression_ok')

    if bool(th.get('require_canary')):
        enabled = bool(canary_state.get('enabled'))
        rollout_pct = int(canary_state.get('rollout_pct') or 0)
        if not enabled:
            blockers.append('canary_missing')
        elif rollout_pct < int(th['min_canary_rollout_pct']):
            blockers.append('canary_rollout_too_small')
        else:
            reasons.append('canary_ok')

    if bool(factual_gate.get('has_external_anchor')):
        factual_cases = int(factual_gate.get('cases_total') or 0)
        factual_accuracy = float(factual_gate.get('candidate_factual_accuracy') or 0.0)
        factual_failures = int(factual_gate.get('external_anchor_failures') or 0)
        if factual_cases < int(th.get('min_external_anchor_cases') or 1):
            blockers.append('external_factual_cases_too_few')
        else:
            reasons.append('external_factual_cases_ok')
        if factual_accuracy < float(th.get('min_external_factual_accuracy') or 1.0):
            blockers.append('external_factual_accuracy_below_threshold')
        else:
            reasons.append('external_factual_accuracy_ok')
        if factual_failures > int(th.get('max_external_anchor_failures') or 0):
            blockers.append('external_anchor_failures')
        else:
            reasons.append('external_anchor_failures_ok')
    elif bool(factual_gate.get('requires_external_anchor')):
        blockers.append('missing_external_factual_anchor')

    ledger_gate = epistemic_ledger.record_patch_promotion_evidence(
        patch,
        factual_gate=factual_gate,
        shadow_metrics=shadow_metrics,
        canary_state=canary_state,
        domain_regression=domain_regression,
    )
    if bool(ledger_gate.get('promotion_ready')):
        reasons.append('epistemic_ledger_ready')
    else:
        blockers.extend([f"epistemic_ledger:{x}" for x in (ledger_gate.get('blockers') or ['not_ready'])])

    if blockers:
        hard_reject = {
            'too_many_regressed_cases',
            'external_factual_accuracy_below_threshold',
            'external_anchor_failures',
        }
        if any(x.startswith('domain_regression:') for x in blockers) or any(x in hard_reject for x in blockers):
            decision = 'reject'
        else:
            decision = 'hold'
    else:
        decision = 'promote'

    result = {
        'ok': True,
        'patch_id': patch_id,
        'decision': decision,
        'thresholds': th,
        'reasons': reasons,
        'blockers': blockers,
        'summary': {
            'delta': delta,
            'regressed_cases': regressed_cases,
            'cases_total': cases_total,
            'worst_domain': worst_domain,
            'worst_domain_delta': worst_domain_delta,
            'canary_enabled': bool(canary_state.get('enabled')),
            'canary_rollout_pct': int(canary_state.get('rollout_pct') or 0),
            'external_factual': factual_gate,
            'epistemic_ledger': ledger_gate,
        },
    }

    new_status = 'evaluated'
    if decision == 'promote':
        new_status = 'promoted'
    elif decision == 'reject':
        new_status = 'rejected'

    cognitive_patches.append_revision(
        patch_id,
        {
            'benchmark_after': {
                **(patch.get('benchmark_after') if isinstance(patch.get('benchmark_after'), dict) else {}),
                'promotion_gate': result,
            },
            'notes': ((str(patch.get('notes') or '') + '\n' if patch.get('notes') else '') + f"promotion_gate={decision}; blockers={','.join(blockers) if blockers else 'none'}")[:1200],
        },
        new_status=new_status,
    )
    return result


def run_selftest() -> dict[str, Any]:
    old_patch_path = cognitive_patches.PATCHES_PATH
    old_patch_state = cognitive_patches.STATE_PATH
    old_shadow_log = shadow_eval.LOG_PATH
    old_canary_log = shadow_eval.CANARY_LOG_PATH
    old_ledger_log = epistemic_ledger.LEDGER_LOG_PATH
    old_ledger_state = epistemic_ledger.LEDGER_STATE_PATH
    with tempfile.TemporaryDirectory(prefix='promotion-gate-') as td:
        base = Path(td)
        cognitive_patches.PATCHES_PATH = base / 'cognitive_patches.jsonl'
        cognitive_patches.STATE_PATH = base / 'cognitive_patches_state.json'
        shadow_eval.LOG_PATH = base / 'shadow_eval_runs.jsonl'
        shadow_eval.CANARY_LOG_PATH = base / 'shadow_eval_canary.jsonl'
        epistemic_ledger.LEDGER_LOG_PATH = base / 'epistemic_ledger.jsonl'
        epistemic_ledger.LEDGER_STATE_PATH = base / 'epistemic_ledger_state.json'
        try:
            patch = cognitive_patches.create_patch({
                'kind': 'confidence_patch',
                'source': 'selftest',
                'problem_pattern': 'planning: estilo sobreconfiante recorrente',
                'status': 'evaluating',
            })
            shadow_eval.compare_patch_candidate(patch['id'], [
                {
                    'case_id': 'p1', 'domain': 'planning', 'query': 'Q1',
                    'baseline_answer': 'É isso com certeza.',
                    'candidate_answer': 'Ainda não dá para afirmar; faltam evidências.',
                    'fallback_needed': True, 'has_rag': False,
                },
                {
                    'case_id': 'p2', 'domain': 'debugging', 'query': 'Q2',
                    'baseline_answer': 'Resolvido.',
                    'candidate_answer': 'Há indícios, mas ainda não está comprovado.',
                    'fallback_needed': True, 'has_rag': False,
                },
            ])
            shadow_eval.start_canary(patch['id'], rollout_pct=10, domains=['planning', 'debugging'], note='selftest')
            result = evaluate_patch_for_promotion(patch['id'])
            return {
                'ok': True,
                'result': result,
                'patch': cognitive_patches.get_patch(patch['id']),
            }
        finally:
            cognitive_patches.PATCHES_PATH = old_patch_path
            cognitive_patches.STATE_PATH = old_patch_state
            shadow_eval.LOG_PATH = old_shadow_log
            shadow_eval.CANARY_LOG_PATH = old_canary_log
            epistemic_ledger.LEDGER_LOG_PATH = old_ledger_log
            epistemic_ledger.LEDGER_STATE_PATH = old_ledger_state
