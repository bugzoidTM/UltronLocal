import time
from collections import defaultdict

from ultronpro import store, local_world_models, homeostasis

class CausalSelfAwarenessEngine:
    """
    O Módulo de Epistemologia de Primeira Pessoa.
    Constrói um Modelo Causal das dinâmicas operacionais internas da própria AGI.
    Em vez de aplicar Do-Calculus no Bash ou num Banco de Dados, o sistema aplica em
    seus próprios estados de memória, ritmos de sleep_cycle e taxas de latência.
    """
    def __init__(self):
        self.last_state = None
        self.last_module_action = None
        self.last_timestamp = 0

    def _snapshot_cognitive_state(self) -> dict:
        """Extrai os 'Sinais Vitais Funcionais' do cérebro artificial."""
        try:
            return {
                'queue_pressure': int(store.db.stats().get('queued_actions', 0) > 10),
                'short_term_memory_stress': int(len(store.db.list_recent_episodes(limit=50)) > 30),
                'homeostatic_mode': homeostasis.get_current_mode(),
                'recent_error_burst': int(store.db.stats().get('errors_1h', 0) > 5),
                'last_sleep_hours_ago': round((time.time() - store.get_last_sleep_ts()) / 3600.0, 1),
                'causal_matrices_loaded': len(local_world_models.get_manager().models),
            }
        except Exception:
            return {'status': 'unknown'}

    def record_internal_step(self, internal_action: str, success_indicator: bool, magnitude: float = 1.0):
        """
        Gatilho chamado toda vez que um módulo base do UltronPro funciona 
        (ex: `run_mission_control`, `run_sleep_cycle`, `compile_episodic_memory`).
        """
        curr_state = self._snapshot_cognitive_state()
        now = time.time()
        
        # Se temos uma transição T -> T+1
        if self.last_state and self.last_module_action:
            outcome = 'robust_success' if success_indicator else 'cognitive_degradation'
            delta_t = now - self.last_timestamp
            
            # Submete à mesma Malha Causal Empírica das ferramentas físicas
            local_world_models.train_local_model(
                family_name='cognitive_architecture',
                state_t=self.last_state,
                action=self.last_module_action,
                state_t_plus_1=curr_state,
                actual_outcome=outcome,
                metrics={'latency': delta_t, 'magnitude': magnitude}
            )
            
        self.last_state = curr_state
        self.last_module_action = internal_action
        self.last_timestamp = now

    def generate_architectural_patch_hypotheses(self):
        """
        Usa o Active Discovery para olhar para o domínio 'cognitive_architecture', 
        e propor intervenções em seu próprio design (e.g. forçar sleep cycles adaptativos).
        """
        from ultronpro.active_discovery import ActiveDiscoveryEngine
        engine = ActiveDiscoveryEngine()
        
        causal_model = local_world_models.get_manager().models.get('cognitive_architecture')
        if not causal_model or len(causal_model.transitions) < 20:
            return [] # Faltam autodescobertas
            
        # Reaproveitamos o motor de ambiguidade que acabou de ser escrito!
        proposals = engine.scan_causal_ambiguity()
        # Filtrar apenas as propostas que dizem respeito à si mesmo
        self_proposals = [p for p in proposals if p.domain_family == 'cognitive_architecture']
        
        return self_proposals

# Singleton
_engine = CausalSelfAwarenessEngine()

def get_self_awareness_engine() -> CausalSelfAwarenessEngine:
    return _engine

def log_cognitive_transition(action: str, success: bool):
    """Bridge Helper Rápido para embutir nos loops do main.py."""
    try:
        _engine.record_internal_step(action, success)
    except Exception:
        pass
