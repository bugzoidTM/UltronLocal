"""Self-Calibrating Promotion Gate.

Replaces human-configured thresholds with experience-derived thresholds
based on the historical success/failure record of promoted patches.

The system defines its own standards by learning from its own outcomes.
Persistence: data/self_calibrating_gate_state.json
"""
from __future__ import annotations

import json
import statistics
import time
from pathlib import Path
from typing import Any

STATE_PATH = Path(__file__).resolve().parent.parent / 'data' / 'self_calibrating_gate_state.json'
LOOP_LOG_PATH = Path(__file__).resolve().parent.parent / 'data' / 'cognitive_patch_loop_runs.jsonl'
ROLLBACK_LOG_PATH = Path(__file__).resolve().parent.parent / 'data' / 'cognitive_rollbacks.jsonl'

# Safety floors: thresholds can never go below these (prevents self-sabotage)
SAFETY_FLOORS = {
    'min_delta': 0.01,
    'max_regressed_cases': 0,
    'max_domain_regression_delta': -0.08,
    'min_canary_rollout_pct': 3,
}

# Human defaults (used as cold-start when no history exists)
COLD_START_DEFAULTS = {
    'min_delta': 0.03,
    'max_regressed_cases': 1,
    'max_domain_regression_delta': -0.02,
    'require_canary': True,
    'min_canary_rollout_pct': 5,
}

# Minimum number of resolved patches before self-calibration kicks in
MIN_HISTORY_SIZE = 5


def _now() -> int:
    return int(time.time())


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    try:
        for line in path.read_text(encoding='utf-8', errors='ignore').splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    rows.append(obj)
            except Exception:
                continue
    except Exception:
        pass
    return rows


def _load_state() -> dict[str, Any]:
    if STATE_PATH.exists():
        try:
            d = json.loads(STATE_PATH.read_text(encoding='utf-8'))
            if isinstance(d, dict):
                d.setdefault('thresholds', dict(COLD_START_DEFAULTS))
                d.setdefault('calibration_history', [])
                d.setdefault('patch_outcomes', [])
                d.setdefault('calibration_count', 0)
                return d
        except Exception:
            pass
    return {
        'thresholds': dict(COLD_START_DEFAULTS),
        'calibration_history': [],
        'patch_outcomes': [],
        'calibration_count': 0,
        'updated_at': 0,
    }


def _save_state(state: dict[str, Any]):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    state['updated_at'] = _now()
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')


# ────────────────────────────────────────────
# History Analysis
# ────────────────────────────────────────────

def analyze_history() -> dict[str, Any]:
    """Analyze patch promotion history to classify outcomes."""
    loop_rows = _load_jsonl(LOOP_LOG_PATH)
    rollback_rows = _load_jsonl(ROLLBACK_LOG_PATH)

    # Build set of rolled-back patch IDs
    rolled_back_ids = set()
    for r in rollback_rows:
        pid = str(r.get('patch_id') or '')
        if pid and r.get('event') == 'automatic_rollback':
            rolled_back_ids.add(pid)

    successes: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    rejections: list[dict[str, Any]] = []

    for row in loop_rows:
        action = str(row.get('final_action') or '')
        pid = str(row.get('patch_id') or '')
        gate = row.get('promotion_gate') if isinstance(row.get('promotion_gate'), dict) else {}
        shadow = row.get('shadow_eval') if isinstance(row.get('shadow_eval'), dict) else {}
        summary = gate.get('summary') if isinstance(gate.get('summary'), dict) else {}

        outcome = {
            'patch_id': pid,
            'action': action,
            'delta': float(shadow.get('delta') or summary.get('delta') or 0.0),
            'regressed_cases': int(shadow.get('regressed_cases') or summary.get('regressed_cases') or 0),
            'cases_total': int(shadow.get('cases_total') or summary.get('cases_total') or 0),
            'ts': int(row.get('ts') or 0),
        }

        if action == 'promote':
            if pid in rolled_back_ids:
                outcome['result'] = 'rollback'
                failures.append(outcome)
            else:
                outcome['result'] = 'success'
                successes.append(outcome)
        elif action == 'reject':
            outcome['result'] = 'rejected'
            rejections.append(outcome)

    return {
        'ok': True,
        'successes': successes,
        'failures': failures,
        'rejections': rejections,
        'total_resolved': len(successes) + len(failures) + len(rejections),
        'rolled_back_ids': list(rolled_back_ids),
    }


# ────────────────────────────────────────────
# Calibration
# ────────────────────────────────────────────

def calibrate() -> dict[str, Any]:
    """Derive thresholds from historical outcomes."""
    analysis = analyze_history()
    state = _load_state()
    successes = analysis.get('successes') or []
    failures = analysis.get('failures') or []
    total = int(analysis.get('total_resolved') or 0)

    old_thresholds = dict(state.get('thresholds') or COLD_START_DEFAULTS)

    if total < MIN_HISTORY_SIZE:
        # Not enough data — stay on defaults
        state['thresholds'] = dict(COLD_START_DEFAULTS)
        _save_state(state)
        return {
            'ok': True,
            'calibrated': False,
            'reason': f'insufficient_history ({total} < {MIN_HISTORY_SIZE})',
            'thresholds': state['thresholds'],
        }

    new_th = dict(COLD_START_DEFAULTS)

    # --- min_delta calibration ---
    # Use median delta of successful patches × 0.8 as threshold
    success_deltas = [float(s.get('delta') or 0.0) for s in successes if float(s.get('delta') or 0.0) > 0]
    failure_deltas = [float(f.get('delta') or 0.0) for f in failures]

    if success_deltas:
        median_success = statistics.median(success_deltas)
        # If we have failures, set threshold above the max failure delta
        if failure_deltas:
            max_failure = max(failure_deltas)
            # Threshold = midpoint between worst failure and median success
            new_th['min_delta'] = round((max_failure + median_success) / 2.0, 4)
        else:
            new_th['min_delta'] = round(median_success * 0.8, 4)

    # --- max_regressed_cases calibration ---
    success_regressed = [int(s.get('regressed_cases') or 0) for s in successes]
    if success_regressed:
        # P75 of regressed cases in successful patches
        sorted_reg = sorted(success_regressed)
        p75_idx = min(len(sorted_reg) - 1, int(len(sorted_reg) * 0.75))
        new_th['max_regressed_cases'] = sorted_reg[p75_idx]

    # If rollbacks happened with certain regression patterns, tighten
    if failures:
        failure_regressed = [int(f.get('regressed_cases') or 0) for f in failures]
        min_fail_reg = min(failure_regressed) if failure_regressed else 999
        # Ensure threshold is below the minimum failure regression count
        if new_th['max_regressed_cases'] >= min_fail_reg:
            new_th['max_regressed_cases'] = max(0, min_fail_reg - 1)

    # --- Apply safety floors ---
    new_th['min_delta'] = max(SAFETY_FLOORS['min_delta'], new_th['min_delta'])
    new_th['max_regressed_cases'] = max(SAFETY_FLOORS['max_regressed_cases'], new_th['max_regressed_cases'])
    new_th['max_domain_regression_delta'] = max(
        SAFETY_FLOORS['max_domain_regression_delta'],
        new_th.get('max_domain_regression_delta', COLD_START_DEFAULTS['max_domain_regression_delta']),
    )
    new_th['min_canary_rollout_pct'] = max(
        SAFETY_FLOORS['min_canary_rollout_pct'],
        new_th.get('min_canary_rollout_pct', COLD_START_DEFAULTS['min_canary_rollout_pct']),
    )

    state['thresholds'] = new_th
    state['calibration_count'] = int(state.get('calibration_count') or 0) + 1

    # Record calibration event
    cal_event = {
        'ts': _now(),
        'old_thresholds': old_thresholds,
        'new_thresholds': new_th,
        'sample_size': total,
        'successes': len(successes),
        'failures': len(failures),
    }
    hist = list(state.get('calibration_history') or [])
    hist.append(cal_event)
    state['calibration_history'] = hist[-100:]

    # Record patch outcomes for observability
    state['patch_outcomes'] = (successes + failures)[-200:]

    _save_state(state)
    return {
        'ok': True,
        'calibrated': True,
        'old_thresholds': old_thresholds,
        'new_thresholds': new_th,
        'sample_size': total,
        'successes': len(successes),
        'failures': len(failures),
        'calibration_count': state['calibration_count'],
    }


def calibrated_thresholds() -> dict[str, Any]:
    """Return current calibrated thresholds for use by promotion_gate."""
    state = _load_state()
    return dict(state.get('thresholds') or COLD_START_DEFAULTS)


# ────────────────────────────────────────────
# Observability
# ────────────────────────────────────────────

def status(limit: int = 15) -> dict[str, Any]:
    state = _load_state()
    analysis = analyze_history()
    return {
        'ok': True,
        'thresholds': state.get('thresholds') or {},
        'safety_floors': SAFETY_FLOORS,
        'cold_start_defaults': COLD_START_DEFAULTS,
        'calibration_count': int(state.get('calibration_count') or 0),
        'calibration_history': (state.get('calibration_history') or [])[-max(1, int(limit)):],
        'analysis_summary': {
            'total_resolved': analysis.get('total_resolved'),
            'successes': len(analysis.get('successes') or []),
            'failures': len(analysis.get('failures') or []),
            'rejections': len(analysis.get('rejections') or []),
        },
        'min_history_size': MIN_HISTORY_SIZE,
        'updated_at': int(state.get('updated_at') or 0),
    }
