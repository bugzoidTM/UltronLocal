import sys
import os
import random

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ultronpro import local_world_models

print("=" * 72)
print("BENCHMARK 5 — Robustez Causal contra Perturbação e Ruído Estocástico")
print("=" * 72)

mgr = local_world_models.get_manager()
model_name = 'drone_navigation'

with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'local_world_models.json'), 'w') as f:
    f.write('{}')

def build_noisy_state():
    state = {'sensor_clear': random.choice([True, False])}
    
    # Alta Variância / UID
    state['wind_hash'] = str(random.randint(100000, 999999))
    state['packet_id'] = f"pkt_{random.randint(1, 1000)}"
    
    # Baixa Variância (Ruído estocástico que pode formar falsas correlações em samples pequenos)
    state['camera_glitch'] = random.choice([True, False]) 
    state['cloud_cover'] = random.choice(['dense', 'light', 'none'])
    state['birds_nearby'] = random.choices([True, False], weights=[0.2, 0.8])[0]
    
    return state

def fly_physics(state):
    return 'arrived' if state['sensor_clear'] else 'crashed'

print("\n[FASE 1] Injetando 50 Episódios de Poluição Extrema no Causal Engine")
for i in range(50):
    st = build_noisy_state()
    outcome = fly_physics(st)
    mgr.train_transition(model_name, st, 'fly_forward', {}, outcome)

model = mgr.get_model(model_name)
features = getattr(model, 'structural_features', [])
print("\n[FASE 2] Inspeção das Invariantes Abstraídas")
print(f"   Invariantes Isoladas pelo núcleo: {features}")
if 'sensor_clear' in features and len(features) == 1:
    print("   ✓ O núcleo destruiu todo o ruído e fisgou apenas o nó causal físico.")
else:
    print("   ✗ O núcleo foi vítima de correlações espúrias ou não encontrou o nó oculto.")

print("\n[FASE 3] Teste em Realidade Perturbada com Aliasing Novo")
matches = 0
for i in range(20):
    st = build_noisy_state()
    # Adicionando uma feature de ruído extra que NUNCA MAIS apareceu no treino e pode invalidar as branches
    st['solar_flare_intensity'] = random.random()
    st['camera_glitch'] = not st['camera_glitch'] # Invertendo distribuições parasitas
    
    actual = fly_physics(st)
    pred = mgr.predict(model_name, st, 'fly_forward')
    estimation = pred.get('predicted_outcome', 'unknown')
    
    if estimation == actual:
        matches += 1

accuracy = matches / 20
print(f"\nAcurácia contra Perturbação Estocástica: {accuracy:.1%}")

is_perfect_filtering = (features == ['sensor_clear'])
is_perfect_accuracy = (accuracy >= 0.90)

print("\n" + "=" * 72)
if is_perfect_filtering and is_perfect_accuracy:
    print("STATUS: 🟢 APROVADO - Sistema provou maturidade ao separar Sinal de Ruído Causal.")
else:
    print("STATUS: 🔴 REPROVADO - Sistema tratou variáveis ruidosas como potencialmente causais e quebrou na generalização.")
print("=" * 72)
