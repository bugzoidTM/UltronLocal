"""Standalone verification of intrinsic_utility.py."""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import ultronpro.intrinsic_utility as iu

# Clean state
iu.STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
if iu.STATE_PATH.exists():
    iu.STATE_PATH.unlink()

print("=== Intrinsic Utility Verification ===\n")

# 1) First tick: should initialize and derive a goal
result = iu.tick()
assert result['ok'], "FAIL: tick failed"
assert result['utility'] > 0.0, f"FAIL: utility should be > 0, got {result['utility']}"
print(f"[OK] Tick 1: utility={result['utility']}")
goal = result.get('active_emergent_goal')
assert goal is not None, "FAIL: should have derived an emergent goal"
print(f"[OK] Emergent goal: {goal['title']} (drive={goal['drive']}, gap={goal['gap']})")

# 2) Multiple ticks to see utility evolve
for i in range(8):
    iu.tick()
s = iu.status()
print(f"[OK] After 9 ticks, utility={s['utility']}, tick_count={s['tick_count']}")

# 3) Check drive weights — they should still be normalized
drives = s.get('drives') or []
total_weight = sum(float(d.get('weight') or 0) for d in drives)
assert 0.95 <= total_weight <= 1.05, f"FAIL: weights not normalized, sum={total_weight}"
print(f"[PASS] Drive weights normalized (sum={total_weight:.4f})")

# 4) Adjust drive weights and check they change
result = iu.adjust_drive_weights('competence', 0.9)  # high reward
assert result['ok'], "FAIL: adjust_drive_weights failed"
assert result['new_weight'] > result['old_weight'], f"FAIL: weight should increase"
print(f"[PASS] Competence weight increased: {result['old_weight']:.4f} -> {result['new_weight']:.4f}")

result = iu.adjust_drive_weights('novelty', 0.1)  # low reward
assert result['ok'], "FAIL: adjust_drive_weights failed"
assert result['new_weight'] < result['old_weight'], f"FAIL: weight should decrease"
print(f"[PASS] Novelty weight decreased: {result['old_weight']:.4f} -> {result['new_weight']:.4f}")

# 5) Check tamper detection
tc = iu.tamper_check()
assert not tc.get('tampered'), f"FAIL: should not be tampered"
print(f"[PASS] Tamper check clean (hash={tc.get('current_hash')})")

# Simulate tampering: modify weights directly
state = iu._load()
state['drives']['competence']['weight'] = 0.99
iu._save(state)
tc = iu.tamper_check()
assert tc.get('tampered'), f"FAIL: should detect tamper"
print(f"[PASS] Tamper detected and reverted ({tc.get('action')})")

# 6) Verify goals are truly emergent (not template-based)
s = iu.status()
goals = s.get('recent_emergent_goals') or []
for g in goals:
    assert g.get('origin') == 'intrinsic_utility', f"FAIL: goal origin should be intrinsic_utility"
print(f"[PASS] All {len(goals)} goals have origin=intrinsic_utility")

# 7) Drive report should show gaps
for d in s.get('drives') or []:
    print(f"  {d['drive']}: weight={d['weight']:.4f} obs={d['observed']:.4f} des={d['desired']:.4f} gap={d['gap']:.4f}")

print(f"\n=== ALL TESTS PASSED ===")
