"""Standalone verification of rl_policy.py (no heavy imports)."""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Minimal stub to avoid importing the entire ultronpro tree
os.environ.setdefault('ULTRON_RL_DECAY_EVERY', '5')  # faster decay for test

# Direct import of rl_policy (it only depends on stdlib + os/json/pathlib)
import ultronpro.rl_policy as rp

# Clean state
rp.STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
if rp.STATE_PATH.exists():
    rp.STATE_PATH.unlink()

print("=== RL Policy Verification ===\n")

# 1) Simulate a high-reward action
for i in range(5):
    rp.update('ask_evidence', 'normal', 0.85)
print("[OK] 5 updates for ask_evidence with reward=0.85")

# 2) Simulate a low-reward action
for i in range(5):
    rp.update('generate_analogy', 'normal', 0.25)
print("[OK] 5 updates for generate_analogy with reward=0.25")

# 3) Sample priorities (should be positive for ask_evidence, negative for analogy)
p_good = [rp.sample_priority('ask_evidence', 'normal') for _ in range(20)]
p_bad = [rp.sample_priority('generate_analogy', 'normal') for _ in range(20)]
avg_good = sum(p_good) / len(p_good)
avg_bad = sum(p_bad) / len(p_bad)

print(f"\nask_evidence  avg priority adjustment: {avg_good:+.1f} (samples: {p_good[:5]}...)")
print(f"analogy       avg priority adjustment: {avg_bad:+.1f} (samples: {p_bad[:5]}...)")

assert avg_good > avg_bad, f"FAIL: good action ({avg_good}) should have higher priority than bad ({avg_bad})"
print("\n[PASS] High-reward actions get higher priority than low-reward actions")

# 4) Check policy summary
s = rp.policy_summary()
assert s['total_arms'] == 2, f"FAIL: expected 2 arms, got {s['total_arms']}"
print(f"[PASS] Policy has {s['total_arms']} arms")

for a in s['arms']:
    print(f"  {a['kind']}|{a['context']}: mean={a['mean']:.3f} ema={a['ema_reward']:.3f} n={a['n']}")

# 5) Test protected kind safety
rp.update('auto_resolve_conflicts', 'normal', 0.1)
rp.update('auto_resolve_conflicts', 'normal', 0.1)
rp.update('auto_resolve_conflicts', 'normal', 0.1)
p_protected = rp.sample_priority('auto_resolve_conflicts', 'normal')
assert p_protected >= 0, f"FAIL: protected kind should never get negative priority, got {p_protected}"
print(f"[PASS] Protected kind safety floor works (priority={p_protected})")

# 6) Verify persistence
state = json.loads(rp.STATE_PATH.read_text(encoding='utf-8'))
assert state['global_updates'] >= 13, f"FAIL: expected >= 13 updates, got {state['global_updates']}"
print(f"[PASS] Persistence works ({state['global_updates']} updates saved)")

print("\n=== ALL TESTS PASSED ===")
