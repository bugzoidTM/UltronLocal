from __future__ import annotations

import json
import time
import tempfile
from pathlib import Path
from typing import Any

from ultronpro import cognitive_patches, shadow_eval

LEDGER_PATH = Path(__file__).resolve().parent.parent / 'data' / 'cognitive_rollbacks.jsonl'


def _now() -> int:
    return int(time.time())


def _ensure_parent(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)


def _append_row(row: dict[str, Any]):
    _ensure_parent(LEDGER_PATH)
    with LEDGER_PATH.open('a', encoding='utf-8') as f:
        f.write(json.dumps(row, ensure_ascii=False) + '\n')


def detect_regression(patch_id: str, thresholds: dict[str, Any] | None = None) -> dict[str, Any] | None:
    patch = cognitive_patches.get_patch(patch_id)
    if not patch:
        return None
    shadow_metrics = patch.get('shadow_metrics') if isinstance(patch.get('shadow_metrics'), dict) else {}
    domain_regression = patch.get('domain_regression') if isinstance(patch.get('domain_regression'), dict) else {}
    th = {
        'max_delta_drop': 0.0,
        'max_regressed_cases': 1,
        'max_domain_delta': -0.02,
    }
    th.update(thresholds or {})
    delta = float(shadow_metrics.get('delta') or 0.0)
    regressed_cases = int(shadow_metrics.get('regressed_cases') or 0)
    domain_hits = []
    for domain, stats in domain_regression.items():
        d = float((stats or {}).get('delta') or 0.0)
        if d < float(th['max_domain_delta']):
            domain_hits.append({'domain': domain, 'delta': d})
    regression_detected = (delta <= float(th['max_delta_drop'])) or (regressed_cases > int(th['max_regressed_cases'])) or bool(domain_hits)
    return {
        'ok': True,
        'patch_id': patch_id,
        'regression_detected': regression_detected,
        'thresholds': th,
        'summary': {
            'delta': delta,
            'regressed_cases': regressed_cases,
            'domain_hits': domain_hits,
        },
    }


def auto_rollback_if_needed(patch_id: str, thresholds: dict[str, Any] | None = None, note: str | None = None) -> dict[str, Any] | None:
    detected = detect_regression(patch_id, thresholds=thresholds)
    if not detected:
        return None
    if not bool(detected.get('regression_detected')):
        return {
            'ok': True,
            'patch_id': patch_id,
            'rolled_back': False,
            'detection': detected,
        }
    row = cognitive_patches.rollback_patch(
        patch_id,
        rollback_ref='auto_regression_guard',
        note=(note or 'automatic rollback due to detected regression'),
    )
    ledger = {
        'ts': _now(),
        'patch_id': patch_id,
        'event': 'automatic_rollback',
        'reason': str(note or 'automatic rollback due to detected regression')[:500],
        'detection': detected,
        'active_snapshot_after': (cognitive_patches.stats().get('active_snapshot') or {}),
        'last_known_good_after': (cognitive_patches.stats().get('last_known_good_patch_ids') or []),
        'rolled_back_patch': row,
    }
    _append_row(ledger)
    return {
        'ok': True,
        'patch_id': patch_id,
        'rolled_back': True,
        'detection': detected,
        'ledger': ledger,
    }


def monitor_longitudinal_regressions(time_window_hours: int = 24) -> dict[str, Any]:
    """
    Avalia a sanidade a longo prazo de patches promovidos cruzando
    com o benchmark externo/longitudinal, aplicando rollback preventivo.
    """
    from ultronpro import benchmark_correlation
    
    # Run the correlation check first
    correlation_report = benchmark_correlation.measure_patch_external_correlation()
    
    thresholds = {
        'max_delta_drop': -0.05,
    }
    
    rolled_back_count = 0
    actions = []
    
    for p_report in correlation_report.get('patches', []):
        if not p_report.get('global_aligned'):
            if p_report.get('external_global_delta', 0.0) < thresholds['max_delta_drop']:
                # The external benchmark heavily regressed after this patch!
                pid = p_report['patch_id']
                rb_result = auto_rollback_if_needed(pid, thresholds={'max_delta_drop': 0.0}, note="longitudinal external regression detected via benchmark suite")
                
                if rb_result and rb_result.get('rolled_back'):
                    rolled_back_count += 1
                actions.append(rb_result)
                
    return {
        'ok': True,
        'ts': _now(),
        'rolled_back_count': rolled_back_count,
        'correlation_score': correlation_report.get('correlation_score'),
        'actions': actions
    }


def run_selftest() -> dict[str, Any]:
    old_patch_path = cognitive_patches.PATCHES_PATH
    old_patch_state = cognitive_patches.STATE_PATH
    old_shadow_log = shadow_eval.LOG_PATH
    old_canary_log = shadow_eval.CANARY_LOG_PATH
    old_ledger = LEDGER_PATH
    with tempfile.TemporaryDirectory(prefix='rollback-manager-') as td:
        base = Path(td)
        cognitive_patches.PATCHES_PATH = base / 'cognitive_patches.jsonl'
        cognitive_patches.STATE_PATH = base / 'cognitive_patches_state.json'
        shadow_eval.LOG_PATH = base / 'shadow_eval_runs.jsonl'
        shadow_eval.CANARY_LOG_PATH = base / 'shadow_eval_canary.jsonl'
        globals()['LEDGER_PATH'] = base / 'cognitive_rollbacks.jsonl'
        try:
            good = cognitive_patches.create_patch({
                'kind': 'heuristic_patch',
                'source': 'selftest',
                'problem_pattern': 'good baseline patch',
                'status': 'promoted',
            })
            cognitive_patches.promote_patch(good['id'], note='seed last known good')
            bad = cognitive_patches.create_patch({
                'kind': 'confidence_patch',
                'source': 'selftest',
                'problem_pattern': 'bad patch with regression',
                'status': 'evaluating',
            })
            cognitive_patches.promote_patch(bad['id'], note='promoted before regression check')
            cognitive_patches.append_revision(bad['id'], {
                'shadow_metrics': {
                    'delta': -0.11,
                    'regressed_cases': 2,
                    'cases_total': 3,
                },
                'domain_regression': {
                    'planning': {'delta': -0.09, 'regressed_cases': 1, 'cases': 2},
                },
            }, new_status='promoted')
            result = auto_rollback_if_needed(bad['id'], note='selftest regression rollback')
            return {
                'ok': True,
                'result': result,
                'stats_after': cognitive_patches.stats(),
                'bad_patch_after': cognitive_patches.get_patch(bad['id']),
            }
        finally:
            cognitive_patches.PATCHES_PATH = old_patch_path
            cognitive_patches.STATE_PATH = old_patch_state
            shadow_eval.LOG_PATH = old_shadow_log
            shadow_eval.CANARY_LOG_PATH = old_canary_log
            globals()['LEDGER_PATH'] = old_ledger
