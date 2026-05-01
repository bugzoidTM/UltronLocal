"""
MPC Planner — Model Predictive Control para Planejamento
======================================================
Fase D: Planejador baseado em controle preditivo.
Usa World Models locais para simular sequências de ações (Tree Search)
e aplica rollout escolhendo a trajetória de menor risco. Se o mundo real
divergir da previsão (surprise_delta elevado), executa abort/rollback.
"""

from __future__ import annotations

import collections
import time
import uuid
import json
from typing import Any

from ultronpro import llm, local_world_models, store

class MPCPlanner:
    DIVERGENCE_THRESHOLD = 0.65  # Threshold de surpresa para ativar rollback

    def __init__(self):
        self.metrics = {
            'mpc_successes': 0,
            'mpc_rollbacks': 0,
            'average_surprise': 0.0,
            'total_sequences': 0
        }
        
    def generate_action_sequences(self, domain: str, goal: str, state_t: dict) -> list[list[dict[str, Any]]]:
        """Usa o LLM para propor *sequências* possíveis de passos (independente de previsão)."""
        prompt = f"""Dado o objetivo: '{goal}' no domínio '{domain}'.
Gere 3 rotas (sequências de ações) alternativas.
Retorne um array JSON onde cada elemento é uma rota. Cada rota é um array de objetos de ação: {{"action": "...", "params": {{...}}}}."""

        res = llm.complete(prompt, strategy='cheap', json_mode=True)
        routes = []
        if res:
            try:
                cleaned = res.strip()
                f_idx = cleaned.find('[')
                l_idx = cleaned.rfind(']')
                if f_idx != -1 and l_idx != -1:
                    routes = json.loads(cleaned[f_idx:l_idx+1])
                    if isinstance(routes, list) and all(isinstance(r, list) for r in routes):
                        return routes
            except Exception:
                pass
        return routes

    def simulate_sequence(self, domain: str, state_t: dict, sequence: list[dict[str, Any]]) -> dict[str, Any]:
        """Simula a sequência usando a matriz empírica do Local World Model."""
        current_state = state_t
        cumulative_risk = 0.0
        cumulative_ev = 0.0
        trajectory = []

        for step in sequence:
            action_id = step.get('action', 'unknown')
            # Phase C integration: Use Local World Model Predictor
            prediction = local_world_models.predict_local_model(domain, current_state, action_id)
            
            p_risk = prediction.get('risk', 0.5) if prediction else 0.5
            p_ev = prediction.get('expected_value', 0.5) if prediction else 0.5
            p_out = prediction.get('predicted_outcome', 'unknown') if prediction else 'unknown'

            cumulative_risk += p_risk
            cumulative_ev += p_ev
            
            # Simple synthetic state progression
            next_state = {**current_state, '_latest_action': action_id, '_predicted_status': p_out}
            
            trajectory.append({
                'action': action_id,
                'predicted_outcome': p_out,
                'step_risk': p_risk,
                'step_ev': p_ev
            })
            current_state = next_state

        penalty = 1.0 if not trajectory else len(trajectory)
        avg_risk = cumulative_risk / penalty
        avg_ev = cumulative_ev / penalty

        return {
            'sequence': sequence,
            'trajectory': trajectory,
            'expected_risk': avg_risk,
            'expected_value': avg_ev,
            'final_state': current_state
        }

    def choose_best_trajectory(self, simulations: list[dict[str, Any]]) -> dict[str, Any] | None:
        """MPC Rule: Escolher sequência com Menor Risco dentre as que tem EV mínimo."""
        if not simulations:
            return None
        valid_sims = [s for s in simulations if s['expected_value'] > 0.1]
        if not valid_sims:
             valid_sims = simulations
             
        # Ordena asc para Risco
        valid_sims.sort(key=lambda x: x['expected_risk'])
        return valid_sims[0]

    def execute_and_monitor(self, domain: str, best_sim: dict[str, Any], initial_state: dict, context_executor: Any = None) -> dict[str, Any]:
        """
        Executa a sequência escolhida passo a passo. 
        Mede divergência real x simulação. Se divergir > DIVERGENCE_THRESHOLD, freia e faz rollback.
        """
        self.metrics['total_sequences'] += 1
        sequence = best_sim['sequence']
        trajectory = best_sim['trajectory']
        
        executed_steps = []
        rollback_triggered = False
        current_state = initial_state
        
        cumulative_surprise = 0.0

        for i, step in enumerate(sequence):
            action_id = step.get('action')
            predicted_out = trajectory[i]['predicted_outcome']
            
            # Execução Real (Mockada aqui se não houver executor injetado, no ambiente real usa sandbox/bash)
            # Para interações de codigo, FS de arquivo via main.py, etc
            actual_outcome = 'success'
            surprise_delta = 0.1
            if context_executor:
                try:
                    res = context_executor.run_action(step)
                    actual_outcome = res.get('status', 'failure')
                    surprise_delta = res.get('surprise_delta', 0.8 if actual_outcome != predicted_out else 0.1)
                except Exception:
                    actual_outcome = 'error'
                    surprise_delta = 0.9

            cumulative_surprise += surprise_delta
            
            # Treinamento automático do Local World Model com o que aconteceu
            next_state = {**current_state, '_latest_action': action_id, '_actual_status': actual_outcome}
            local_world_models.train_local_model(
                family_name=domain,
                state_t=current_state,
                action=action_id,
                state_t_plus_1=next_state,
                actual_outcome=actual_outcome,
                metrics={'surprise_delta': surprise_delta}
            )

            executed_steps.append({'action': action_id, 'outcome': actual_outcome, 'surprise': surprise_delta})
            current_state = next_state

            # Rollback Constraint Checking (Divergence Monitor)
            if surprise_delta >= self.DIVERGENCE_THRESHOLD:
                # O mundo real não se comporta como a simulação. Abortar e Rollback.
                rollback_triggered = True
                self.metrics['mpc_rollbacks'] += 1
                if context_executor and hasattr(context_executor, 'rollback'):
                    context_executor.rollback(executed_steps)
                # Publicar divergência em workspaces globais do Ultron
                store.publish_workspace(
                    module='mpc_planner',
                    channel='mpc.rollback',
                    payload_json=json.dumps({'step': i, 'action': action_id, 'surprise': surprise_delta}),
                    salience=0.9,
                    ttl_sec=1200
                )
                break

        avg_surprise = cumulative_surprise / len(executed_steps) if executed_steps else 0.0
        # Media de surpresa global ao longo do motor
        self.metrics['average_surprise'] = (self.metrics['average_surprise'] * (self.metrics['total_sequences'] - 1) + avg_surprise) / self.metrics['total_sequences']

        if not rollback_triggered:
            self.metrics['mpc_successes'] += 1

        return {
            'executed': executed_steps,
            'rollback': rollback_triggered,
            'average_surprise': round(avg_surprise, 4),
            'metrics_state': self.metrics
        }


_planner: MPCPlanner | None = None

def get_mpc_planner() -> MPCPlanner:
    global _planner
    if _planner is None:
        _planner = MPCPlanner()
    return _planner

def run_mpc_cycle(domain: str, goal: str, initial_state: dict, context_executor: Any = None) -> dict[str, Any]:
    planner = get_mpc_planner()
    
    # 1. Busca de Caminhos
    routes = planner.generate_action_sequences(domain, goal, initial_state)
    
    # 2. Simulação com Causal Models Locais
    sims = [planner.simulate_sequence(domain, initial_state, r) for r in routes if r]
    
    # 3. Model Predictive Choice
    best = planner.choose_best_trajectory(sims)
    
    if not best:
        return {'status': 'planning_failed', 'reason': 'Não foi possível compilar matriz de simulação.'}
        
    # 4. Rollout and Monitor
    return planner.execute_and_monitor(domain, best, initial_state, context_executor)
