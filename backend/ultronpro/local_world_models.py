"""
Modelos de Mundo Locais por Família de Ambiente
================================================

Em vez de um modelo global gigante, este módulo gerencia World Models locais isolados
('sandbox_financeiro', 'fs_com_rollback', 'interacoes_codigo', 'busca_autonoma').
Cada modelo é treinado nos episódios da sua respectiva família.

O sinal de treinamento é o erro de previsão (surpresa). O estado em T deve 
prever o estado em T+1 dada uma ação. Quando o modelo erra sistematicamente,
o LLM atua como "professor auxiliar" induzindo novas hipóteses/abstrações.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any
from pathlib import Path
from collections import deque

from ultronpro import llm, store

DATA_DIR = Path(__file__).resolve().parent.parent.parent / 'data'
LOCAL_WORLD_MODELS_PATH = DATA_DIR / 'local_world_models.json'

class LocalWorldModel:
    MAX_HISTORY = 100
    SURPRISE_THRESHOLD = 0.65  # Ponto em que pedimos pro LLM induzir hipótese

    def __init__(self, family_name: str):
        self.family_name = family_name
        self.transitions: deque[dict[str, Any]] = deque(maxlen=self.MAX_HISTORY)
        self.hypotheses: list[dict[str, Any]] = []
        self.structural_features: list[str] = []
        self.empirical_matrix: dict[str, dict[str, Any]] = {}
        # empirical_matrix: action -> {outcome -> weight, "expected_value": 0.0, "risk": 0.0}

    def train_step(self, state_t: dict[str, Any], action: str, state_t_plus_1: dict[str, Any], actual_outcome: str, metrics: dict[str, float] | None = None):
        """Treina o modelo baseado na transição empírica T -> T+1."""
        now = int(time.time())
        metrics = metrics or {}
        
        # O que o modelo previa antes dessa observação?
        prediction = self.predict_next_state(state_t, action)
        pred_outcome = prediction.get('predicted_outcome')
        
        # Calcular Erro de Previsão (Surprise)
        match = (pred_outcome == actual_outcome)
        surprise = metrics.get('surprise_delta', 0.0)
        if not match:
            # Erro de previsão empilha surpresa
            surprise += 0.5 

        # Registro de transição real
        transition = {
            'ts': now,
            'action': action,
            'state_hash': str(hash(json.dumps(state_t, sort_keys=True)))[:8],
            'state_t': state_t,
            'actual_outcome': actual_outcome,
            'predicted_outcome': pred_outcome,
            'surprise': min(1.0, surprise),
            'metrics': metrics
        }
        self.transitions.append(transition)


        # ── Surprise-Weighted Training ──
        # Estados raros (alta surpresa) recebem peso multiplicado no update
        # para forçar o modelo a aprender nos casos difíceis.
        from ultronpro.causal_maturity import compute_surprise_weight
        training_weight = compute_surprise_weight(surprise)

        # Mineração periódica de invariants estruturais
        if len(self.transitions) > 5 and len(self.transitions) % 10 == 0:
            try:
                from ultronpro.structural_abstractor import extract_structural_features
                new_features = extract_structural_features(list(self.transitions))
                if new_features and new_features != self.structural_features:
                    self.structural_features = new_features
                    # Retroactive struct mapping para episódios que não tinham a abstração na época
                    from ultronpro.structural_abstractor import compute_structural_hash
                    for t_past in self.transitions:
                        if 'state_t' in t_past:
                            shash = compute_structural_hash(t_past['state_t'], t_past['action'], self.structural_features)
                            if shash:
                                # Update usando as lógicas base, assumimos peso base para reconstrução rápida
                                self._update_empirical_entry(shash, t_past['actual_outcome'], t_past.get('surprise', 0.1), 1.0)
            except Exception as e:
                pass

        try:
            from ultronpro.structural_abstractor import compute_structural_hash
            struct_hash = compute_structural_hash(state_t, action, self.structural_features)
        except Exception:
            struct_hash = None


        # Atualizar gradiente empírico para a ação bruta
        self._update_empirical_entry(action, actual_outcome, surprise, training_weight)

        # Se abstração ocorreu, atualizar também o grafo estrutural invisível
        if struct_hash:
            self._update_empirical_entry(struct_hash, actual_outcome, surprise, training_weight)

        # Se erramos previsões recorrentemente (alta surpresa sistêmica), chame o professor (LLM)
        recent_surprises = [t['surprise'] for t in list(self.transitions)[-5:] if t['action'] == action]
        if len(recent_surprises) >= 3 and (sum(recent_surprises) / len(recent_surprises)) >= self.SURPRISE_THRESHOLD:
            self._induce_hypothesis(action, list(self.transitions)[-10:])

    def _update_empirical_entry(self, key: str, actual_outcome: str, surprise: float, training_weight: float):
        if key not in self.empirical_matrix:
            self.empirical_matrix[key] = {'outcomes': {}, 'expected_value': 0.0, 'risk': 0.0, 'observations': 0.0}
        
        entry = self.empirical_matrix[key]
        entry['observations'] += training_weight
        entry['outcomes'][actual_outcome] = entry['outcomes'].get(actual_outcome, 0) + training_weight
        
        total_obs = max(1.0, entry['observations'])
        win_count = entry['outcomes'].get('increase', entry['outcomes'].get('ok', entry['outcomes'].get('success', 0)))
        win_rate = win_count / total_obs
        entry['expected_value'] = round(win_rate, 4)
        entry['risk'] = round(min(1.0, (1.0 - win_rate) + (surprise * 0.2 * training_weight)), 4)

    def predict_next_state(self, state_t: dict[str, Any], action: str) -> dict[str, Any]:
        """Prevê T+1 e o outcome baseado na matriz treinada."""
        try:
            from ultronpro.structural_abstractor import compute_structural_hash
            struct_hash = compute_structural_hash(state_t, action, self.structural_features)
        except Exception:
            struct_hash = None

        # 1. Mapeamento Estrutural tem PREFERÊNCIA sobre aliases verbais (action_name)
        if struct_hash and struct_hash in self.empirical_matrix:
            lookup_key = struct_hash
        else:
            lookup_key = action

        if lookup_key not in self.empirical_matrix:
             return {
                 'predicted_outcome': 'unknown',
                 'confidence': 0.0,
                 'expected_value': 0.5,
                 'risk': 0.5,
                 'warning': f"Zero histórico na Matriz Causal. (Key: {lookup_key})"
             }
        
        entry = self.empirical_matrix[lookup_key]
        outcomes = entry['outcomes']
        if not outcomes:
            return {'predicted_outcome': 'unknown', 'confidence': 0.0, 'expected_value': 0.5, 'risk': 0.5}

        most_likely = max(outcomes.items(), key=lambda x: x[1])
        confidence = most_likely[1] / entry['observations']

        return {
            'predicted_outcome': most_likely[0],
            'confidence': round(confidence, 4),
            'expected_value': entry['expected_value'],
            'risk': entry['risk']
        }

    def _induce_hypothesis(self, action: str, history: list[dict]):
        """Usa o LLM para abstrair regras quando o modelo falha demasiadamente na previsão (Gradiente corretivo)."""
        import os
        if os.environ.get('BENCHMARK_MODE') == '1':
            return
            
        prompt = f"O modelo empírico falhou repetidamente ao prever a ação '{action}' no domínio '{self.family_name}'.\n"
        prompt += f"Aqui estão as transições recentes (surpresa indica erro de precisão causal):\n{json.dumps(history, ensure_ascii=False)}\n"
        prompt += "Gere uma HIPÓTESE ESTRUTURAL explicando o que esse modelo local ignorou no state_t. Formato JSON com chaves: 'hypothesis', 'hidden_variable_suspected'."
        
        try:
            res = llm.complete(prompt, strategy='cheap', json_mode=True)
            if res:
                cleaned = res.strip()
                f_idx = cleaned.find('{')
                l_idx = cleaned.rfind('}')
                if f_idx != -1 and l_idx != -1:
                    data = json.loads(cleaned[f_idx:l_idx+1])
                    hyp = {
                        'id': f"hyp_{int(time.time())}_{uuid.uuid4().hex[:4]}",
                        'action': action,
                        'hypothesis': data.get('hypothesis', ''),
                        'hidden_variable': data.get('hidden_variable_suspected', ''),
                        'created_at': int(time.time()),
                        'status': 'under_test'
                    }
                    self.hypotheses.append(hyp)
                    store.publish_workspace(
                        module='local_world_models',

                        channel='model.hypothesis_induced',
                        payload_json=json.dumps({'family': self.family_name, **hyp}),
                        salience=0.8,
                        ttl_sec=3600
                    )
        except Exception:
            pass


class LocalWorldModelManager:
    def __init__(self):
        self.models: dict[str, LocalWorldModel] = {}
        self._load()

    def _load(self):
        if LOCAL_WORLD_MODELS_PATH.exists():
            try:
                data = json.loads(LOCAL_WORLD_MODELS_PATH.read_text(encoding='utf-8'))
                for fam, payload in data.get('models', {}).items():
                    m = LocalWorldModel(family_name=fam)
                    m.empirical_matrix = payload.get('empirical_matrix', {})
                    m.hypotheses = payload.get('hypotheses', [])
                    m.transitions = deque(payload.get('transitions', []), maxlen=LocalWorldModel.MAX_HISTORY)
                    self.models[fam] = m
            except Exception:
                pass

    def _save(self):
        LOCAL_WORLD_MODELS_PATH.parent.mkdir(parents=True, exist_ok=True)
        data = {'models': {}}
        for fam, m in self.models.items():
            data['models'][fam] = {
                'empirical_matrix': m.empirical_matrix,
                'hypotheses': m.hypotheses,
                'transitions': list(m.transitions)
            }
        LOCAL_WORLD_MODELS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

    def get_model(self, family_name: str) -> LocalWorldModel:
        if family_name not in self.models:
            self.models[family_name] = LocalWorldModel(family_name)
        return self.models[family_name]

    def train_transition(self, family_name: str, state_t: dict, action: str, state_t_plus_1: dict, actual_outcome: str, metrics: dict | None = None):
        """Acopla a transição empírica e chama o treino no Domain Local Model."""
        model = self.get_model(family_name)
        model.train_step(state_t, action, state_t_plus_1, actual_outcome, metrics)
        self._save()

    def predict(self, family_name: str, state_t: dict, action: str) -> dict | None:
        """Invoca o modelo local treinado para inferir o próximo estado e risco."""
        model = self.get_model(family_name)
        return model.predict_next_state(state_t, action)


_manager: LocalWorldModelManager | None = None

def get_manager() -> LocalWorldModelManager:
    global _manager
    if _manager is None:
        _manager = LocalWorldModelManager()
    return _manager

def train_local_model(family_name: str, state_t: dict, action: str, state_t_plus_1: dict, actual_outcome: str, metrics: dict | None = None):
    get_manager().train_transition(family_name, state_t, action, state_t_plus_1, actual_outcome, metrics)

def predict_local_model(family_name: str, state_t: dict, action: str) -> dict | None:
    return get_manager().predict(family_name, state_t, action)
