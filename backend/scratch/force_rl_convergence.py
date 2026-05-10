"""
force_rl_convergence.py  –  Acelera o RL loop para demonstrar convergência do Gap 3.

Executa N ciclos cobrindo todos os 7 braços com include_cooldown=True,
registrando reward série por braço e calculando EMA e tendência.
"""
import json, sys, os, time
sys.path.insert(0, os.path.abspath("."))

from ultronpro import online_rl_loop, rl_policy
from pathlib import Path

N_CYCLES = 21          # suficiente para cobrir todos os 7 braços 3x
ARMS = list(online_rl_loop.ACTION_CATALOG.keys())
CONVERGENCE_PATH = Path("data/rl_convergence_series.jsonl")

print(f"=== GAP 3: Forçando {N_CYCLES} ciclos RL cobrindo {len(ARMS)} braços ===")
print(f"Braços: {ARMS}")
print()

series: list[dict] = []
for i, kind in enumerate(ARMS * 3):  # 3 passagens por todos os braços
    print(f"[{i+1:02d}/{N_CYCLES}] Executando braço: {kind}")
    t0 = time.time()
    result = online_rl_loop.run_once(force_kind=kind, include_cooldown=True)
    elapsed = round(time.time() - t0, 2)
    reward = (result.get("reward") or {}).get("reward")
    ok = result.get("ok")
    action_ok = (result.get("action_result") or {}).get("ok", False)
    comps = (result.get("reward") or {}).get("components", {})
    evidence = (result.get("reward") or {}).get("evidence", {})
    rw_str = f"{reward:.3f}" if reward is not None else "ERR"
    print(f"         reward={rw_str} ok={ok} action_ok={action_ok} elapsed={elapsed}s")
    print(f"         evidence={evidence}")
    series.append({
        "ts": int(time.time()),
        "cycle": i + 1,
        "kind": kind,
        "reward": reward,
        "ok": ok,
        "action_ok": action_ok,
        "components": comps,
        "evidence": evidence,
    })
    # Pausa mínima para não sobrecarregar
    time.sleep(0.5)

# Salvar série de convergência
CONVERGENCE_PATH.parent.mkdir(exist_ok=True)
with CONVERGENCE_PATH.open("a", encoding="utf-8") as f:
    for row in series:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")

print()
print("=== RESULTADO FINAL ===")
summary = rl_policy.policy_summary(limit=100)
arms = summary.get("arms", [])
print(f"  global_updates : {summary.get('global_updates')}")
print(f"  total_arms     : {len(arms)}")
print()
print("  Braços por mean (decrescente):")
for arm in sorted(arms, key=lambda a: -a.get("mean", 0)):
    key = f"{arm.get('kind')}|{arm.get('context')}"
    print(f"    {key:<45} mean={arm['mean']:.3f} n={arm['n']} ema={arm.get('ema_reward',0):.3f}")

# Calcular tendência por braço
print()
print("  Tendência por braço (first vs last reward):")
by_arm: dict = {}
for row in series:
    k = row["kind"]
    r = row.get("reward")
    if r is not None:
        by_arm.setdefault(k, []).append(r)

for k, rewards in sorted(by_arm.items()):
    if len(rewards) >= 2:
        trend = rewards[-1] - rewards[0]
        avg = sum(rewards) / len(rewards)
        print(f"    {k:<40} n={len(rewards)} avg={avg:.3f} trend={trend:+.3f}")
    else:
        print(f"    {k:<40} n={len(rewards)} (apenas 1 amostra)")

# Geral
valid = [r["reward"] for r in series if r.get("reward") is not None]
if valid:
    n = len(valid)
    first_half = valid[:n//2]
    second_half = valid[n//2:]
    avg1 = sum(first_half)/len(first_half)
    avg2 = sum(second_half)/len(second_half)
    print()
    print(f"  Média primeiros {len(first_half)} ciclos: {avg1:.3f}")
    print(f"  Média últimos   {len(second_half)} ciclos: {avg2:.3f}")
    print(f"  Tendência global: {avg2 - avg1:+.3f} ({'✓ CONVERGINDO' if avg2 >= avg1 else '✗ DEGRADANDO'})")

print()
print(f"Série salva em: {CONVERGENCE_PATH}")
print("Gap 3 - Ciclos verificados:", len([r for r in series if r.get("reward") is not None]))
