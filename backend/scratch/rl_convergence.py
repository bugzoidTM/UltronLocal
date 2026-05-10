import json, sys, os
sys.path.insert(0, os.path.abspath("."))
from pathlib import Path
from ultronpro import rl_policy

# RL state
state_path = Path("data/online_rl_state.json")
if state_path.exists():
    st = json.loads(state_path.read_text(encoding="utf-8"))
    print("=== RL STATE ===")
    print(f"  cycle_count : {st.get('cycle_count')}")
    print(f"  last_action : {(st.get('last_action') or {}).get('kind')}")
    print(f"  last_reward : {st.get('last_reward')}")
else:
    print("NO RL STATE FILE")

# Policy summary
summary = rl_policy.policy_summary(limit=100)
arms = summary.get("arms", [])
print()
print("=== RL POLICY ARMS ===")
print(f"  global_updates : {summary.get('global_updates')}")
print(f"  total_arms     : {len(arms)}")
for arm in sorted(arms, key=lambda a: -a.get("mean", 0)):
    key = f"{arm.get('kind','?')}|{arm.get('context','?')}"
    print(f"  {key:<45} mean={arm['mean']:.3f} n={arm['n']} ema={arm.get('ema_reward',0):.3f} alpha={arm.get('alpha',0):.2f} beta={arm.get('beta',0):.2f}")

# Run log
run_log = Path("data/online_rl_runs.jsonl")
if run_log.exists():
    lines = [l for l in run_log.read_text("utf-8", errors="ignore").splitlines() if l.strip()]
    print()
    print(f"=== RUN LOG: {len(lines)} total entries ===")
    runs = []
    for l in lines:
        try:
            runs.append(json.loads(l))
        except Exception:
            pass
    successful = [r for r in runs if r.get("ok")]
    print(f"  ok runs: {len(successful)} / {len(runs)}")

    by_kind: dict = {}
    for r in runs:
        sel = (r.get("selection") or {}).get("selected") or {}
        kind = sel.get("kind", "?")
        ctx = sel.get("context", "?")
        arm_key = f"{kind}|{ctx}"
        reward = (r.get("reward") or {}).get("reward", 0)
        by_kind.setdefault(arm_key, []).append(reward)
    print("  By arm:")
    for k, rewards in sorted(by_kind.items()):
        avg = sum(rewards) / len(rewards) if rewards else 0
        print(f"    {k:<40} n={len(rewards)} avg_reward={avg:.3f}")

    # reward trend (all runs in chronological order)
    all_rewards = []
    for r in runs:
        rw = (r.get("reward") or {}).get("reward")
        if rw is not None:
            all_rewards.append(float(rw))

    if len(all_rewards) >= 4:
        first_half = all_rewards[:len(all_rewards)//2]
        second_half = all_rewards[len(all_rewards)//2:]
        avg_first = sum(first_half)/len(first_half)
        avg_second = sum(second_half)/len(second_half)
        print()
        print("=== REWARD TREND ===")
        print(f"  first half avg  : {avg_first:.3f}")
        print(f"  second half avg : {avg_second:.3f}")
        delta = avg_second - avg_first
        print(f"  delta           : {delta:+.3f}  ({'improving' if delta > 0 else 'degrading'})")

    print()
    print("  Last 8 runs:")
    for r in runs[-8:]:
        sel = (r.get("selection") or {}).get("selected") or {}
        kind = sel.get("kind", "?")
        ctx = sel.get("context", "?")
        reward = (r.get("reward") or {}).get("reward", None)
        rw_str = f"{reward:.3f}" if reward is not None else "N/A"
        print(f"    [{kind:<35}|{ctx}] reward={rw_str} ok={r.get('ok')}")
else:
    print("NO RUN LOG FILE")
