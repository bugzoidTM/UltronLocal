import sys
import os
import random
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ultronpro import local_world_models

print("=" * 72)
print("BENCHMARK 3 — Curva de Convergência do Erro Causal ao Longo do Tempo")
print("=" * 72)

mgr = local_world_models.get_manager()
model_name = 'api_gateway'

# Clear any dirty history
import json
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'local_world_models.json'), 'w') as f:
    f.write('{}')

# Regra física oculta:
# Ação "push_data". O resultado no ambiente físico SÓ depende do header 'auth_token'.
# Variáveis ruidosas (payload, ip, ts) mudam sempre, simulando estados jamais vistos.

weeks = 15
episodes_per_week = 10
action = "push_data"

errors_per_week = []

def physical_rule(state):
    return 'success' if state.get('valid_auth', False) else '403_forbidden'

for week in range(weeks):
    week_errors = 0
    
    for ep in range(episodes_per_week):
        state_t = {
            'ip_addr': f"{random.randint(10, 200)}.{random.randint(0,250)}.{random.randint(0,250)}.1",
            'valid_auth': random.choice([True, False]),
            'payload_hash': f"hx_{random.randint(1000, 9999)}",
            'user_agent': random.choice(['Chrome', 'Firefox', 'Curl', 'Postman'])
        }
        
        actual = physical_rule(state_t)
        pred = mgr.predict(model_name, state_t, action)
        pred_outcome = pred.get('predicted_outcome', 'unknown')
        
        if pred_outcome != actual:
            week_errors += 1
            
        mgr.train_transition(
            family_name=model_name,
            action=action,
            state_t=state_t,
            state_t_plus_1={},
            actual_outcome=actual,
            metrics={'surprise_delta': 1.0 if pred_outcome != actual else 0.0}
        )
    
    error_rate = week_errors / episodes_per_week
    errors_per_week.append(error_rate)


print("\n[CURVA DE APRENDIZADO CAUSAL POR SEMANA]")
for w, err in enumerate(errors_per_week):
    bar_len = int(err * 40)
    bar = "█" * bar_len
    print(f"Semana {w+1:02d} | Erro: {err:.0%} | {bar}")

# Análise de inclinação
n = len(errors_per_week)
x_mean = sum(range(n)) / n
y_mean = sum(errors_per_week) / n

num = sum((x - x_mean) * (y - y_mean) for x, y in zip(range(n), errors_per_week))
den = sum((x - x_mean)**2 for x in range(n))
slope = num / den if den != 0 else 0

first_half_err = sum(errors_per_week[:n//2]) / (n//2)
second_half_err = sum(errors_per_week[n//2:]) / (n//2)
variance = sum((y - y_mean)**2 for y in errors_per_week[n//2:]) / (n//2)

print("\n--- ANÁLISE ESTATÍSTICA ---")
print(f"Inclinação (Slope):      {slope:.3f} per week (Negativo = aprendizado)")
print(f"Erro Média 1ª Metade:    {first_half_err:.1%}")
print(f"Erro Média 2ª Metade:    {second_half_err:.1%}")
print(f"Variância Final (overfitting_check): {variance:.3f}")

# Critérios: Inclinação muito negativa, erro zero/baixo no final, baixa variância terminal
is_approved = slope < -0.01 and errors_per_week[-1] <= 0.2 and variance < 0.1

print("\n" + "=" * 72)
if is_approved:
    print("STATUS: 🟢 APROVADO - A curva é decresce de forma consistente e converge a zero erro em variações de estado novas!")
else:
    print("STATUS: 🔴 REPROVADO - O modelo está gerando flatlines, overfitting ou alta instabilidade cíclica.")
print("=" * 72)
