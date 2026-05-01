import sys, json, time
from pathlib import Path
sys.path.insert(0, str(Path("f:/sistemas/UltronPro/backend").resolve()))

from ultronpro import intrinsic_utility
from ultronpro import self_model

# 1. Lê gap inicial
status_before = intrinsic_utility.status()
autonomy_before = next(
    (d for d in status_before['drives'] if d['drive'] == 'autonomy'), None
)

if not autonomy_before:
    # Se não encontrar pelo nome 'autonomy', tenta listar o que tem
    print("ERRO: Drive 'autonomy' não encontrado.")
    print("Drives disponíveis:", [d['drive'] for d in status_before['drives']])
    sys.exit(1)

print(f"ANTES — observed: {autonomy_before['observed']:.6f}")
print(f"ANTES — gap: {autonomy_before['gap']:.6f}")

# 2. Injeta 50 eventos com strategy='local' no modelo causal
print("\nInjetando 50 eventos locais...")
for i in range(50):
    self_model.record_action_outcome(
        strategy="local",
        task_type="test_autonomy_cycle",
        budget_profile="default",
        ok=True,
        notes=f"Evento de teste de autonomia {i}"
    )

# 3. Força recálculo do drive
print("Executando tick() da utilidade intrínseca...")
intrinsic_utility.tick()

# 4. Lê gap depois
status_after = intrinsic_utility.status()
autonomy_after = next(
    (d for d in status_after['drives'] if d['drive'] == 'autonomy'), None
)

print(f"\nDEPOIS — observed: {autonomy_after['observed']:.6f}")
print(f"DEPOIS — gap: {autonomy_after['gap']:.6f}")

# 5. Veredito
# No intrinsic_utility.py, gap = (desired - observed) * weight
delta_observed = autonomy_after['observed'] - autonomy_before['observed']
delta_gap = autonomy_before['gap'] - autonomy_after['gap']

print(f"\nDelta observed: {delta_observed:.6f}")
print(f"Delta gap: {delta_gap:.6f}")

if delta_gap > 0.01:
    print(f"\n✅ CICLO FECHADO — o drive respondeu positivamente à telemetria local.")
elif delta_gap > 0:
    print(f"\n⚠️ CICLO PARCIAL — o sensor detectou a mudança, mas o impacto no gap foi amortecido.")
else:
    print(f"\n❌ CICLO ABERTO — o drive é imune às ações injetadas.")
