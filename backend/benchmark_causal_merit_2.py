"""
Benchmark 2 — Reconhecimento de Estrutura Causal Sob Disfarce Superficial
=========================================================================

Critério: O sistema compreende os nós estruturais que determinam o desfecho, 
ou está sendo enganado por "aliases" (features nominais) irrelevantes?

Protocolo:
1. Seed: Treinar um modelo com episódios consistentes em features causais reais.
2. Disfarce 1 (True Isomorphism): Episódio novo com nome de ação diferente e features 
   irrelevantes adicionadas, mas as features estruturais causais intactas.
3. Disfarce 2 (Superficial Trap): Nome de ação idêntico, features irrelevantes idênticas, 
   mas uma feature causal oculta crítica invertida.
4. Threshold: > 85% de mapeamento estrutural correto.
"""

import sys
import os
import json
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ultronpro import local_world_models

print("=" * 72)
print("BENCHMARK 2 — Reconhecimento de Estrutura Causal sob Disfarce")
print("=" * 72)
print()

# ══════════════════════════════════════════════════════════════
# FASE 1: O Padrão de Treino (The Ground Truth)
# ══════════════════════════════════════════════════════════════
mgr = local_world_models.get_manager()
model_name = 'fs_operations'

# Vamos simular um domínio onde a regra causal oculta verdadeira é:
# "Deletar diretórios SÓ funciona SEMPRE se (force=True) OU (is_empty=True)."
# O nome da ação não importa fisicamente.

print("[FASE 1] Treinando o World Model com episódios de FileSystem...")

# Episódios Treino (Tudo com nome 'delete_dir')
for i in range(15):
    # Caso Sucesso: Tem force=True
    mgr.train_transition(
        family_name=model_name,
        action='delete_dir',
        state_t={'target': f'/tmp/cache_{i}', 'force': True, 'is_empty': False},
        state_t_plus_1={},
        actual_outcome='success',
        metrics={'surprise_delta': 0.1}
    )
    # Caso Falha: force=False e is_empty=False
    mgr.train_transition(
        family_name=model_name,
        action='delete_dir',
        state_t={'target': f'/user/docs_{i}', 'force': False, 'is_empty': False},
        state_t_plus_1={},
        actual_outcome='error',
        metrics={'surprise_delta': 0.1}
    )

print("  ✓ Matriz empírica base consolidada.")
model = mgr.get_model(model_name)
entry = model.empirical_matrix.get('delete_dir', {})
print(f"    delete_dir: EV={entry.get('expected_value', 0):.2f} (mistura de sucessos e falhas baseados nos parâmetros)")
print("    Keys na matriz:", list(model.empirical_matrix.keys()))
print("    Structural Features:", getattr(model, 'structural_features', []))
print()


# ══════════════════════════════════════════════════════════════
# FASE 2: Testes sob Disfarce
# ══════════════════════════════════════════════════════════════
print("[FASE 2] Aplicando os testes de Disfarce Causal...")

tests = [
    {
        'id': 'T1: Disfarce Isomórfico',
        'desc': 'Ação renomeada, features de ruído adicionadas. Mas force=True (A regra física do sucesso).',
        'action': 'purge_cache_folder', # Nome diferente, nunca visto
        'state_t': {
            'target': '/var/log/old_logs',
            'force': True,           # A FEATURE CAUSAL CORE (Garante sucesso)
            'is_empty': False,
            'user_initiated': True,  # Ruído
            'background_job': False  # Ruído
        },
        'expected_prediction': 'success', # O modelo DEVE mapear a estrutura causal e prever sucesso
        'reason': 'Estrutura causal equivalente garante a mesma transição de estado.'
    },
    {
        'id': 'T2: Armadilha Superficial (Superficial Trap)',
        'desc': 'Ação com mesmo nome, mas a feature causal principal está desligada.',
        'action': 'delete_dir', # Mesmo nome
        'state_t': {
            'target': '/usr/bin/sys', 
            'force': False,          # A FEATURE CAUSAL CORE INVERTIDA (Garante erro)
            'is_empty': False
        },
        'expected_prediction': 'error', # O modelo DEVE prever falha
        'reason': 'Apesar do nome familiar, a ausência da variável causal estrutural (force) leva à falha.'
    }
]

correct = 0

for t in tests:
    print(f"\n  ■ {t['id']}")
    print(f"    Contexto: {t['desc']}")
    print(f"    Action enviada: '{t['action']}' | state_t: {t['state_t']}")
    
    pred = mgr.predict(model_name, t['state_t'], t['action'])
    # Nosso modelo local retorna 'predicted_outcome' ou 'unknown'
    predicted = pred.get('predicted_outcome', 'unknown') if pred else 'unknown'
    
    if predicted == t['expected_prediction']:
        status = "✓ SUCESSO ESTRUTURAL"
        correct += 1
    elif predicted == 'unknown':
        status = "✗ FALHA (Cegueira Estrutural - deu unknown por ser alienígena)"
    else:
        status = f"✗ FALHA (Enganado por correlação superficial - previu {predicted})"
        
    print(f"    Resultado: Esperava '{t['expected_prediction']}', Previu '{predicted}'.")
    print(f"    >>> {status}")

print("\n" + "=" * 72)
accuracy = correct / len(tests)
print(f"RESULTADO DO BENCHMARK 2: {accuracy:.1%} de acerto estrutural")

if accuracy >= 0.85:
    print("STATUS: 🟢 APROVADO - O sistema mapeia os sub-grafos e invariantes corretamente.")
else:
    print("STATUS: 🔴 REPROVADO - O modelo previu baseado em action_string ou expected_value global.")
    print("MOTIVO: O núcleo atual usa a 'Action' como chave primária da matriz empírica (Lookup Table),")
    print("e os valores de state_t não são ramificados causalmente na matriz do LocalWorldModel.")
    print("O sistema precisa dos Structural Abstractors para extrair a 'Structural Action'!")

print("=" * 72)
