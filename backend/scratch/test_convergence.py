import json, sys, os
sys.path.insert(0, os.path.abspath("."))
from ultronpro import rl_convergence_report

r = rl_convergence_report.compute()
g3 = r.get("gap3", {})
cyc = r.get("cycles", {})
arms = r.get("arms", {})
pol = r.get("policy", {})

print("=== GAP 3 - Convergencia RL ===")
print("Score Gap3:              ", g3.get("score"))
print("Convergencia demonstrada:", g3.get("convergence_demonstrated"))
print()
print("Criterios do roadmap:")
for k, v in (g3.get("criteria") or {}).items():
    status = "OK" if v else "FAIL"
    print(f"  [{status}] {k}: {v}")
print()
print("Ciclos totais:    ", cyc.get("total"))
print("global_updates:   ", pol.get("global_updates"))
trend = cyc.get("trend", 0)
print("Tendencia global: ", f"{trend:+.4f}")
print("1a metade avg:    ", cyc.get("first_half_avg"))
print("2a metade avg:    ", cyc.get("second_half_avg"))
print()
print("Bracos distintos: ", arms.get("distinct"))
print("arm_std:          ", arms.get("arm_std"), "(anti lock-in, >0.05 bom)")
print("lock_in_suspected:", arms.get("lock_in_suspected"))
print()
print("Scores por componente:")
for k, v in (r.get("score_components") or {}).items():
    print(f"  {k:<25}: {v:.3f}")

ema = cyc.get("global_ema") or []
print()
print("EMA global (ultimos 10):", [round(x, 3) for x in ema[-10:]])
print()
print("Bracos (top 5):")
for arm in (arms.get("stats") or [])[:5]:
    print(f"  {arm['arm']:<45} mean={arm['mean']:.3f} n={arm['n']} trend={arm['trend']:+.3f} improving={arm['improving']}")
