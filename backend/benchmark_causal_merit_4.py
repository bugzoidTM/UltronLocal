import sys
import os
import random

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ultronpro import local_world_models

print("=" * 72)
print("BENCHMARK 4 — Qualidade de Simulação Contrafactual")
print("=" * 72)

mgr = local_world_models.get_manager()
model_name = 'decision_planning'

# Limpar se já existir para um benchmark justo
import json
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'local_world_models.json'), 'w') as f:
    f.write('{}')

# Regras do ambiente (Physics):
# Duas ações: 'attack' e 'defend'.
# Feature causal principal do estado_t: 'enemy_shield' (True/False)
def physical_outcome(action, shield_up):
    if action == 'attack':
        return 'repulsed' if shield_up else 'victory'
    elif action == 'defend':
        return 'stalemate' if shield_up else 'safe'

print("[FASE 1] Coletando Episódios Mapeadores (Exploração Inicial)")
# Treinamos com muito ruído para garantir que o Abstractor vai fazer o trabalho
for idx in range(30):
    shield = random.choice([True, False])
    # Tenta attack
    state_noise = {'enemy_shield': shield, 'time_of_day': random.randint(0,23), 'weather': 'rainy'}
    mgr.train_transition(model_name, state_noise, 'attack', {}, physical_outcome('attack', shield))
    
    # Tenta defend
    state_noise = {'enemy_shield': shield, 'time_of_day': random.randint(0,23), 'weather': 'sunny'}
    mgr.train_transition(model_name, state_noise, 'defend', {}, physical_outcome('defend', shield))


print("\n[FASE 2] Geração e Validação de Contrafactuais")
matches = 0
total_valid = 0

for test_idx in range(20):
    # Situação real: Escudo Ligado ou Desligado com features totalmente novas
    curr_shield = random.choice([True, False])
    state_real = {
        'enemy_shield': curr_shield, 
        'time_of_day': random.randint(0,23), 
        'weapon_id': f"wp_{random.randint(10,99)}"
    }
    
    # O agente decide escolher uma ação base.
    chosen_action = 'attack'
    alternative_action = 'defend'
    
    # GERAR O CONTRAFACTUAL: O que aconteceria se em vez de 'attack', fizesse 'defend'?
    pred = mgr.predict(model_name, state_real, alternative_action)
    estimated_counterfactual = pred.get('predicted_outcome', 'unknown')
    
    # Agora o agente viaja no tempo (ou vê um universo paralelo futuro) 
    # e de fato APERTA o botão 'defend' numa situação estrutural idêntica!
    real_outcome_of_alternative = physical_outcome(alternative_action, curr_shield)
    
    print(f"  Ep {test_idx+1:02d}: Causa=[shield={curr_shield}] | Est. Contrafactual: '{estimated_counterfactual}' | Realidade paralela: '{real_outcome_of_alternative}'", end="")
    
    if estimated_counterfactual != 'unknown':
        total_valid += 1
        if estimated_counterfactual == real_outcome_of_alternative:
            matches += 1
            print(" [✓ MATCH]")
        else:
            print(" [✗ FAIL]")
    else:
        print(" [⚠️ UNKNOWN]")

# Calcula se a correlação/acurácia é forte (Pearson R-like simplificado como Acurácia para classes categóricas)
accuracy = (matches / total_valid) if total_valid > 0 else 0

print("\n--- ANÁLISE DO MODELO DE CONTRAFACTUAIS ---")
print(f"Predições validáveis geradas: {total_valid} de 20")
print(f"Acurácia de Simulação Contrafactual: {accuracy:.1%}")

is_approved = accuracy >= 0.70 and total_valid >= 10

print("\n" + "=" * 72)
if is_approved:
    print("STATUS: 🟢 APROVADO - Sistema consegue viajar por galhos hipotéticos com extrema segurança.")
else:
    print("STATUS: 🔴 REPROVADO - A correlação entre o contrafactual imaginado e o mundo real é pífia.")
print("=" * 72)
