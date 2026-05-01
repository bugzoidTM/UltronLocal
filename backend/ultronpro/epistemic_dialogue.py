import json
import time
from pathlib import Path
from collections import defaultdict
from typing import Any

from ultronpro import store, local_world_models, episodic_compiler
from ultronpro.structural_abstractor import _flatten_dict

DATA_DIR = Path(__file__).resolve().parent.parent.parent / 'data'
OVERRIDES_PATH = DATA_DIR / 'human_causal_overrides.jsonl'

def _ensure_overrides():
    if not OVERRIDES_PATH.parent.exists():
        OVERRIDES_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not OVERRIDES_PATH.exists():
        OVERRIDES_PATH.write_text("")

class EpistemicCollabEngine:
    """
    O salto da Epistemologia Fechada para a Episteme Colaborativa.
    Permite expor as crenças causais internas do Agente, permitindo que o humano 
    injete axiomas físicos (vetos) sobre covariâncias coincidentais.
    """
    def __init__(self):
        self.manager = local_world_models.get_manager()
        _ensure_overrides()

    def export_causal_graph(self, domain: str) -> dict[str, Any]:
        """
        Gera uma representação legível e matematicamente estrita do Grafo Causal 
        construído autonomamente, para inspeção humana.
        """
        model = self.manager.models.get(domain)
        if not model:
            return {'error': f"Domain '{domain}' tem amostragem insuficiente."}
            
        # Calcula pesos básicos (frequência de transição)
        graph = {'domain': domain, 'edges': []}
        edge_weights = defaultdict(float)
        
        for t in model.transitions:
            flat_st = _flatten_dict(t.get('state_t', {}))
            out = t.get('actual_outcome', 'unknown')
            
            for k in flat_st.keys():
                edge_weights[(k, out)] += 1.0
                
        total = max(1.0, sum(edge_weights.values()))
        
        for (var, outcome), weight in sorted(edge_weights.items(), key=lambda x: x[1], reverse=True):
            if weight / total > 0.05: # Ocultar ruído ínfimo na visualização
                graph['edges'].append({
                    'origin': var,
                    'target': outcome,
                    'empirical_weight': round(weight / total, 3),
                    'observations': int(weight)
                })
                
        try:
            lib = episodic_compiler._load_abstractions()
            graph['abstractions'] = [a for a in lib.get('abstractions', []) if a.get('domain') == domain and a.get('status') in ('compiled_skill', 'hypothesis')]
        except Exception:
             graph['abstractions'] = []
             
        return graph

    def dispute_edge(self, domain: str, spurious_var: str, human_rationale: str) -> dict[str, Any]:
        """
        O humano aponta: "O var '{spurious_var}' não causa o outcome, foi coincidência. Eis a evidência: {human_rationale}".
        O Sistema submissamente reescreve seu grafo, cortando a aresta estrita e 
        rebaixando quaisquer habilidades que dependiam dessa mentira.
        """
        model = self.manager.models.get(domain)
        if not model:
            return {'status': 'error', 'msg': 'Modelo base não encontrado.'}
            
        override = {
            'ts': int(time.time()),
            'domain': domain,
            'spurious_variable': spurious_var,
            'human_evidence': human_rationale,
            'type': 'edge_deletion'
        }
        
        with OVERRIDES_PATH.open('a', encoding='utf-8') as f:
            f.write(json.dumps(override, ensure_ascii=False) + '\n')
            
        # 1. Purga da Estrutura Fundamental do Modelo (Para parar de monitorar essa feature)
        if spurious_var in model.structural_features:
            model.structural_features.remove(spurious_var)
            
        # 2. Reavaliação Punitiva das Abstrações Baseadas em Mentiras (Belief Revision)
        demoted_skills = 0
        lib = episodic_compiler._load_abstractions()
        for a in lib.get('abstractions', []):
            if a.get('domain') == domain and a.get('status') in ('compiled_skill', 'under_test', 'hypothesis'):
                # Se a estrutura causal confiou na variável espúria
                if spurious_var.lower() in a.get('causal_structure', '').lower():
                    a['status'] = 'rejected_by_epistemic_dispute'
                    a['rejection_reason'] = f"Humano provou covariância espúria em '{spurious_var}': {human_rationale}"
                    demoted_skills += 1
                    
        if demoted_skills > 0:
            episodic_compiler._save_abstractions(lib)
            
        # Feedback ao Workspace
        store.db.add_event('epistemic_dispute', f"Humano quebrou ilusão causal: Aresta ['{spurious_var}' -> Output] destruída via evidência externa.")
        
        store.publish_workspace(
            module='epistemic_collab',
            channel='causal.human_override',
            payload_json=json.dumps(override, ensure_ascii=False),
            salience=1.0, # Nível MÁXIMO, humano falou = gravidade pura
            ttl_sec=7200
        )
        
        return {
            'status': 'beliefs_revised',
            'action_taken': f"Removido nó '{spurious_var}'.",
            'demoted_abstractions': demoted_skills,
            'message': f"A evidência foi incorporada. {demoted_skills} Skills falsas foram cassadas."
        }

if __name__ == '__main__':
    print("Testando Epistemic Collaboration...")
    e = EpistemicCollabEngine()
    print("Graph:", json.dumps(e.export_causal_graph('sandbox_financeiro'), indent=2))
