import math
import random
from dataclasses import dataclass
from collections import defaultdict
from typing import Any

from ultronpro import local_world_models
from ultronpro.structural_abstractor import _flatten_dict

@dataclass
class ExperimentProposal:
    domain_family: str
    action: str
    target_state: dict[str, Any]
    hypothesis: str
    expected_information_gain: float
    description: str

def compute_entropy(outcome_counts: dict[str, int]) -> float:
    """Calcula a pureza termodinâmica da distribuição de resultados (bits)"""
    total = sum(outcome_counts.values())
    if total == 0: return 0.0
    
    entropy = 0.0
    for cnt in outcome_counts.values():
        p = cnt / total
        entropy -= p * math.log2(p)
    return entropy

class ActiveDiscoveryEngine:
    def __init__(self):
        self.manager = local_world_models.get_manager()
        
    def scan_causal_ambiguity(self) -> list[ExperimentProposal]:
        """
        Escaneia as matrizes de mundo local em busca de buracos negros causais. 
        Mapeia Variavéis de Confusão (Confounding Variables) que estão impedindo 
        os Structural Abstractors de compilar regras limpas.
        """
        proposals = []
        
        for family_name, model in self.manager.models.items():
            if len(model.transitions) < 5:
                continue # Ignora modelos embrionários
                
            action_states = defaultdict(list)
            for t in model.transitions:
                action = t.get('action')
                state = t.get('state_t', {})
                outcome = t.get('actual_outcome', 'unknown')
                action_states[action].append((_flatten_dict(state), outcome))
                
            for action, data_pairs in action_states.items():
                if len(data_pairs) < 5: 
                    continue
                
                # Identifica matrizes onde a Incerteza do resultado bruto é alta
                outcome_dist = defaultdict(int)
                for _, out in data_pairs:
                    outcome_dist[out] += 1
                    
                base_entropy = compute_entropy(outcome_dist)
                
                # Se o ambiente já é previsível, não há Ciência a investigar no nó global 
                if base_entropy < 0.2:
                    continue
                    
                # Busca de Variáveis de Confusão (Confounders)
                # I.e., duplas de variáveis que por coincidência aleatória sempre agiram juntas nos testes orgânicos
                keys_seen = set()
                for st, _ in data_pairs:
                    for k in st.keys(): keys_seen.add(k)
                    
                con_pairs = self._find_confounding_pairs(data_pairs, list(keys_seen))
                
                for key_a, key_b, val_a, val_b in con_pairs:
                    # Desenha a Intervenção Do-Calculus P(Y | do(X))
                    # Se sempre vimos key_a=X e key_b=Y juntos, disparamos A=X e B=~Y.
                    expected_ig = base_entropy * 0.8 # Heurística: Isolar correlação quebra 80% da ignorância de nó
                    
                    test_state = self._construct_base_state(data_pairs)
                    test_state[key_a] = val_a
                    
                    # Intervenção (Desassociando a Correlação Empírica)
                    test_state[key_b] = not val_b if isinstance(val_b, bool) else f"{val_b}_intervention"
                    
                    desc = f"Quebra de covariância espúria entre '{key_a}' e '{key_b}'. O sistema intervirá ativamente para separar as variáveis que sempre orbitaram juntas e identificar qual rege a física do comando."
                    hypothesis = f"H0: Se o resultado mudar com a intervenção, '{key_b}' detém massa causal primária. H1: Se permanecer idêntico ao empírico, '{key_a}' é a verdadeira Structural Feature."
                    
                    proposal = ExperimentProposal(
                        domain_family=family_name,
                        action=action,
                        target_state=test_state,
                        hypothesis=hypothesis,
                        expected_information_gain=expected_ig,
                        description=desc
                    )
                    proposals.append(proposal)
                    
        proposals.sort(key=lambda x: x.expected_information_gain, reverse=True)
        return proposals
        
    def _find_confounding_pairs(self, data_pairs, keys):
        pairs = []
        keys = keys[:50] # Hard-cap para controle de explosão combinatória O(n^2)
        
        for i in range(len(keys)):
            for j in range(i+1, len(keys)):
                k1, k2 = keys[i], keys[j]
                
                # Ignorar timestamps e hashes identificáveis
                if 'time' in k1 or 'hash' in k1 or 'time' in k2 or 'hash' in k2:
                    continue
                
                covariation_pure = True
                memory_mapping = None
                valid_samples = 0
                
                for st, _ in data_pairs:
                    if k1 in st and k2 in st:
                        v1, v2 = st[k1], st[k2]
                        mapping_sig = f"{str(v1)}:||:{str(v2)}"
                        
                        if memory_mapping is None:
                            memory_mapping = mapping_sig
                            valid_samples += 1
                        elif memory_mapping == mapping_sig:
                            valid_samples += 1
                        else:
                            covariation_pure = False
                            break
                
                # Só nos interessamos pelo confounder se ele contaminou >= 4 episódios sem nunca divergir
                if covariation_pure and valid_samples >= 4:
                     vals = memory_mapping.split(":||:")
                     try:
                         val_1 = eval(vals[0]) if vals[0] in ('True', 'False') else vals[0]
                         val_2 = eval(vals[1]) if vals[1] in ('True', 'False') else vals[1]
                         pairs.append((k1, k2, val_1, val_2))
                     except Exception:
                         pass
        return pairs
        
    def _construct_base_state(self, data_pairs):
        if not data_pairs: return {}
        return dict(data_pairs[-1][0])


if __name__ == "__main__":
    print("\n=======================================================")
    print("   ACTIVE CAUSAL DISCOVERY & EPISTEMIC SIMULATOR")
    print("=======================================================\n")
    print("Iniciando varredura entrópica do World Model...")
    
    engine = ActiveDiscoveryEngine()
    proposals = engine.scan_causal_ambiguity()
    
    if not proposals:
        print("Nenhuma ambiguidade estrutural severa detectada. Modelos causais perfeitamente resolvidos.")
    else:
        print(f"Detectadas {len(proposals)} oportunidades de CIÊNCIA ATIVA para desambiguação:\n")
        
        # Elimina duplicados lógicos para impressão enxuta
        unique_logs = set()
        count = 1
        for p in proposals:
            sig = f"{p.domain_family}|{p.action}|{p.hypothesis}"
            if sig in unique_logs: continue
            unique_logs.add(sig)
            
            print(f"[EXPERIMENTO #{count:02d}] ⚗️")
            print(f"  ├─ Domínio Físico : {p.domain_family}")
            print(f"  ├─ Ação Testada   : {p.action}")
            print(f"  ├─ Info Gain L(θ) : {p.expected_information_gain:.3f} bits simulados")
            print(f"  ├─ Justificativa  : {p.description}")
            print(f"  ├─ Hipótese H0/H1 : {p.hypothesis}")
            print(f"  └─ Payload Interventivo (Estado do Sandbox a ser forçado):\n      {p.target_state}\n")
            
            count += 1
            if count > 3: break
