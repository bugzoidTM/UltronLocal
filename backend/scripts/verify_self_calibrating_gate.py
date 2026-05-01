"""Standalone verification of self_calibrating_gate.py."""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import ultronpro.self_calibrating_gate as scg

# Clean state
scg.STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
if scg.STATE_PATH.exists():
    scg.STATE_PATH.unlink()

print("=== Self-Calibrating Gate Verification ===\n")

# 1) Cold-start: no history → use defaults
result = scg.calibrate()
assert not result['calibrated'], f"FAIL: should not calibrate without history"
print(f"[PASS] Cold-start: using defaults (reason={result['reason']})")

th = scg.calibrated_thresholds()
assert th['min_delta'] == 0.03, f"FAIL: min_delta should be 0.03, got {th['min_delta']}"
print(f"[PASS] Default thresholds: min_delta={th['min_delta']}, max_regressed={th['max_regressed_cases']}")

# 2) Simulate history by writing mock loop log
scg.LOOP_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
mock_rows = []

# 4 successful patches (promoted, not rolled back)
for i in range(4):
    mock_rows.append(json.dumps({
        'ts': 1000 + i,
        'patch_id': f'success_{i}',
        'final_action': 'promote',
        'shadow_eval': {'delta': 0.05 + i * 0.01, 'regressed_cases': 0, 'cases_total': 3},
        'promotion_gate': {'summary': {'delta': 0.05 + i * 0.01, 'regressed_cases': 0}},
    }))

# 1 failure (promoted + rolled back)
mock_rows.append(json.dumps({
    'ts': 1010,
    'patch_id': 'failure_0',
    'final_action': 'promote',
    'shadow_eval': {'delta': 0.02, 'regressed_cases': 2, 'cases_total': 3},
    'promotion_gate': {'summary': {'delta': 0.02, 'regressed_cases': 2}},
}))

# 2 rejections
for i in range(2):
    mock_rows.append(json.dumps({
        'ts': 1020 + i,
        'patch_id': f'rejected_{i}',
        'final_action': 'reject',
        'shadow_eval': {'delta': -0.01, 'regressed_cases': 1, 'cases_total': 3},
    }))

# Write mock loop log
old_loop = scg.LOOP_LOG_PATH
scg.LOOP_LOG_PATH.write_text('\n'.join(mock_rows) + '\n', encoding='utf-8')

# Write rollback log for the failure
old_rb = scg.ROLLBACK_LOG_PATH
scg.ROLLBACK_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
scg.ROLLBACK_LOG_PATH.write_text(
    json.dumps({'patch_id': 'failure_0', 'event': 'automatic_rollback'}) + '\n',
    encoding='utf-8',
)

# 3) Analyze history
analysis = scg.analyze_history()
assert analysis['total_resolved'] == 7, f"FAIL: total should be 7, got {analysis['total_resolved']}"
assert len(analysis['successes']) == 4, f"FAIL: should have 4 successes, got {len(analysis['successes'])}"
assert len(analysis['failures']) == 1, f"FAIL: should have 1 failure, got {len(analysis['failures'])}"
assert len(analysis['rejections']) == 2, f"FAIL: should have 2 rejections, got {len(analysis['rejections'])}"
print(f"[PASS] History analysis: {analysis['total_resolved']} resolved ({len(analysis['successes'])} OK, {len(analysis['failures'])} fail, {len(analysis['rejections'])} reject)")

# 4) Calibrate
cal = scg.calibrate()
assert cal['calibrated'], f"FAIL: should calibrate with enough history"
new_th = cal['new_thresholds']
print(f"[PASS] Calibrated! min_delta={new_th['min_delta']}, max_regressed={new_th['max_regressed_cases']}")

# min_delta should be between failure (0.02) and success median (~0.06)
assert new_th['min_delta'] > 0.02, f"FAIL: min_delta should be > failure delta 0.02"
assert new_th['min_delta'] >= scg.SAFETY_FLOORS['min_delta'], f"FAIL: below safety floor"
print(f"[PASS] min_delta={new_th['min_delta']} is above failure delta and safety floor")

# max_regressed should be < failure's regressed (2)
assert new_th['max_regressed_cases'] < 2, f"FAIL: max_regressed should be < failure's 2"
print(f"[PASS] max_regressed={new_th['max_regressed_cases']} is tighter than failure threshold")

# 5) Tamper: verify defaults differ from calibrated
assert new_th['min_delta'] != 0.03, f"FAIL: should differ from defaults"
print(f"[PASS] Calibrated thresholds differ from cold-start defaults")

# 6) Status check
s = scg.status()
assert s['calibration_count'] == 1
print(f"[PASS] Status: calibration_count={s['calibration_count']}, analysis={s['analysis_summary']}")

print(f"\n=== ALL TESTS PASSED ===")
