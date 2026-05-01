"""
Structural Abstractors
======================

Módulo responsável por minerar o histórico empírico de um LocalWorldModel
e extrair assinaturas estruturais baseadas em Information Gain (ou Gini Impurity).
Ele descobre quais atributos do `state_t` preveem garantidamente o resultado,
independente da string arbitrária da Ação (`action_name`).
"""

from typing import Any

def _flatten_dict(d: dict, parent_key: str = '', sep: str = '.') -> dict:
    items = []
    if not isinstance(d, dict):
        return {parent_key: str(d)}
        
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.extend(_flatten_dict(v, new_key, sep=sep).items())
        elif isinstance(v, list):
            items.append((new_key, "list_len_" + str(len(v))))
        else:
            items.append((new_key, str(v)))
    return dict(items)

def extract_structural_features(transitions: list[dict[str, Any]]) -> list[str]:
    """
    Analisa uma lista de transições e determina por métrica de Pureza (Information Gain/Gini)
    quais chaves do dict `state_t` separam os resultados perfeitamente.
    """
    if len(transitions) < 5:
        return []

    # 1. Obter todas as chaves possíveis de state_t e converter para features planas, incluindo a Action
    data = []
    for t in transitions:
        flat_state = _flatten_dict(t.get('state_t', {}))
        # Ao injetar a action no estado, permitimos que as sub-branches do Gini isolem o contexto da ação
        flat_state['__action'] = t.get('action', 'unknown')
        outcome = t.get('actual_outcome', 'unknown')
        data.append((flat_state, outcome))

    # 2. Encontrar chaves com variância mínima condicional
    # Para cada chave e cada branch conjundo (Action, Valor), qual a probabilidade do outcome?
    feature_stats = {}
    for flat_state, outcome in data:
        action = flat_state.get('__action', 'unknown')
        for k, v in flat_state.items():
            if k == '__action': continue
            
            if k not in feature_stats:
                feature_stats[k] = {}
            
            joint_branch = f"{action}|{v}"
            if joint_branch not in feature_stats[k]:
                feature_stats[k][joint_branch] = {}
            
            feature_stats[k][joint_branch][outcome] = feature_stats[k][joint_branch].get(outcome, 0) + 1

    structural_keys = set()
    total_samples = len(data)

    # 3. Calcular heurística de "Pureza" (Gini Impurity por branch)
    for k, val_distributions in feature_stats.items():
        # Ignorar features que mudam a cada rodada (ex: timestamps, hashes únicos)
        if len(val_distributions) >= total_samples * 0.5:
            continue
            
        weighted_impurity = 0.0
        for val, outcomes in val_distributions.items():
            branch_total = sum(outcomes.values())
            # Impureza de Gini = 1 - sum(p_i^2)
            gini = 1.0 - sum((cnt / branch_total) ** 2 for cnt in outcomes.values())
            weighted_impurity += (branch_total / total_samples) * gini

        # Se a variável reduz a impureza para um nível drástico (quase perfeto), ela é uma CAUSA ESTRUTURAL
        # Threshold de pureza: impurity <= 0.15 significa que quase sempre que o valor ocorre, o resultado é o mesmo
        if weighted_impurity <= 0.15:
            structural_keys.add(k)

    return sorted(list(structural_keys))


def compute_structural_hash(state_t: dict[str, Any], action: str, structural_keys: list[str]) -> str | None:
    """
    Gera o alias criptográfico do state baseado nas chaves invariantes de estrutura.
    Amarrado explicitamente à Ação (já que uma invariante tem efeitos diferentes dependendo da ação física).
    """
    if not structural_keys:
         return None
         
    flat_state = _flatten_dict(state_t)
    pairs = []
    for k in structural_keys:
        if k in flat_state:
            pairs.append(f"{k}={flat_state[k]}")
    
    if not pairs:
        return None
        
    # Ordenar para manter consistência isotrópica
    signature = f"struct:{action}|" + "|".join(sorted(pairs))
    return signature

