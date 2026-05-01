"""
World Model — Modelo do Ambiente
================================

Sistema que mantém um modelo persistente do ambiente/externo.
Armazena observações, estados, e permite previsões.

Características:
- Observações do ambiente (entradas, saídas, estados)
- Estado corrente do "mundo" 
- Histórico de transições
- Previsões baseadas em padrões
- Integração com o sistema de goals

"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from dataclasses import dataclass, asdict, field
from typing import Any, Optional
from collections import deque

DATA_DIR = Path(__file__).resolve().parent.parent.parent / 'data'
WORLD_MODEL_PATH = DATA_DIR / 'world_model.json'


@dataclass
class Observation:
    id: str
    ts: int
    source: str
    event_type: str
    content: str
    state_before: dict
    state_after: dict
    outcome: str
    metadata: dict = field(default_factory=dict)


@dataclass
class WorldState:
    entities: dict
    last_update: int
    version: int


class WorldModel:
    MAX_HISTORY = 200
    MAX_ENTITIES = 100
    
    def __init__(self):
        self.observations: deque[Observation] = deque(maxlen=self.MAX_HISTORY)
        self.entities: dict[str, dict] = {}
        self.version = 0
        self._load()

    def _load(self):
        if not WORLD_MODEL_PATH.exists():
            return
        try:
            data = json.loads(WORLD_MODEL_PATH.read_text(encoding='utf-8'))
            self.entities = data.get('entities', {})
            self.version = data.get('version', 0)
            obs_list = data.get('observations', [])
            self.observations = deque(
                [Observation(**o) for o in obs_list[-self.MAX_HISTORY:]],
                maxlen=self.MAX_HISTORY
            )
        except Exception:
            pass

    def _save(self):
        data = {
            'entities': self.entities,
            'version': self.version,
            'observations': [asdict(o) for o in list(self.observations)[-self.MAX_HISTORY:]],
            'updated_at': int(time.time()),
        }
        WORLD_MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        WORLD_MODEL_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

    def observe(self, source: str, event_type: str, content: str,
                state_before: dict | None = None, state_after: dict | None = None,
                outcome: str = 'unknown', metadata: dict | None = None) -> Observation:
        """Registra uma observação do ambiente."""
        now = int(time.time())
        
        obs = Observation(
            id=f"obs_{now}_{uuid.uuid4().hex[:6]}",
            ts=now,
            source=source,
            event_type=event_type,
            content=content,
            state_before=state_before or {},
            state_after=state_after or {},
            outcome=outcome,
            metadata=metadata or {},
        )
        
        self.observations.append(obs)
        
        if state_after:
            self._update_entities(state_after)
        
        self.version += 1
        self._save()

        # Publish to global workspace
        try:
            from ultronpro import store
            store.publish_workspace(
                module='world_model',
                channel='world.observation',
                payload_json=json.dumps({
                    'id': obs.id,
                    'source': source,
                    'event_type': event_type,
                    'outcome': outcome,
                    'summary': content[:100]
                }),
                salience=0.45,
                ttl_sec=600
            )
        except Exception:
            pass

        return obs

    def _update_entities(self, state: dict):
        """Atualiza entidades no modelo do mundo."""
        for entity_id, entity_data in state.items():
            if len(self.entities) >= self.MAX_ENTITIES and entity_id not in self.entities:
                oldest = sorted(self.entities.items(), key=lambda x: x[1].get('last_seen', 0))
                if oldest:
                    del self.entities[oldest[0][0]]
            
            if entity_id in self.entities:
                self.entities[entity_id].update(entity_data)
                self.entities[entity_id]['last_seen'] = int(time.time())
            else:
                self.entities[entity_id] = {
                    **entity_data,
                    'first_seen': int(time.time()),
                    'last_seen': int(time.time()),
                }

    def update_entity(self, entity_id: str, data: dict):
        """Atualiza uma entidade específica."""
        now = int(time.time())
        if entity_id in self.entities:
            self.entities[entity_id].update(data)
            self.entities[entity_id]['last_seen'] = now
        else:
            self.entities[entity_id] = {
                **data,
                'first_seen': now,
                'last_seen': now,
            }
        self.version += 1
        self._save()

    def get_entity(self, entity_id: str) -> Optional[dict]:
        """Retorna dados de uma entidade."""
        return self.entities.get(entity_id)

    def get_recent_observations(self, n: int = 20, event_type: str | None = None) -> list[dict]:
        """Retorna observações recentes."""
        obs = list(self.observations)
        if event_type:
            obs = [o for o in obs if o.event_type == event_type]
        return [asdict(o) for o in obs[-n:]]

    def get_state_summary(self) -> dict:
        """Retorna resumo do estado atual."""
        recent = list(self.observations)[-10:]
        
        outcomes = {}
        for o in self.observations:
            outcomes[o.outcome] = outcomes.get(o.outcome, 0) + 1
        
        return {
            'version': self.version,
            'entity_count': len(self.entities),
            'observation_count': len(self.observations),
            'entities': dict(list(self.entities.items())[:10]),
            'recent_events': [
                {'ts': o.ts, 'type': o.event_type, 'content': o.content[:50]}
                for o in recent
            ],
            'outcomes': outcomes,
            'updated_at': self.observations[-1].ts if self.observations else 0,
        }

    def predict_next(self, event_type: str) -> dict | None:
        """Prediz próximo estado baseado em padrões históricos usando probabilidades simples (Probabilístico)."""
        relevant = [o for o in self.observations if o.event_type == event_type]
        if len(relevant) < 3:
            return None
        
        outcomes = {}
        for o in relevant:
            outcomes[o.outcome] = outcomes.get(o.outcome, 0) + 1
        
        if not outcomes:
            return None
        
        most_likely = max(outcomes.items(), key=lambda x: x[1])
        return {
            'event_type': event_type,
            'predicted_outcome': most_likely[0],
            'confidence': round(most_likely[1] / len(relevant), 4),
            'based_on': len(relevant),
            'type': 'probabilistic_historical'
        }

    def simulate_action(self, action_type: str, params: dict) -> dict:
        """
        Simula a consequência de uma ação antes dela acontecer.
        - lane_0 (Determinístico): Para tarefas lógicas e previsíveis do OS ou banco.
        - Probabilístico Clássico: Para integrações e LLM (onde há ruído exógeno).
        """
        # --- Simulador Determinístico (lane_0) ---
        deterministic_actions = {
            'file_move': lambda p: {
                'source': p.get('source_path', 'unknown'),
                'destination': p.get('dest_path', 'unknown'),
                '_effect': f"O arquivo deixará de existir na origem ({p.get('source_path')}) e surgirá no destino ({p.get('dest_path')})."
            },
            'file_delete': lambda p: {
                'target': p.get('path', 'unknown'),
                '_effect': f"O arquivo em {p.get('path')} será removido e o espaço em disco liberado."
            },
            'file_write': lambda p: {
                'target': p.get('path', 'unknown'),
                '_effect': f"O conteúdo de {p.get('path')} será substituído/criado. O hash do arquivo e mtime vão mudar."
            },
            'python_run': lambda p: {
                'target': p.get('script', 'unknown'),
                '_effect': f"Processo instanciado usando {p.get('script')}. Efeitos colaterais dependentes do código em runtime."
            }
        }
        
        if action_type in deterministic_actions:
            state_delta = deterministic_actions[action_type](params)
            return {
                'action_type': action_type,
                'simulation_type': 'deterministic',
                'predicted_outcome': 'success',
                'state_delta': state_delta,
                'confidence': 0.99,
                'warning': 'Ação puramente determinística baseada na física do sistema.'
            }
            
        # --- Simulador Probabilístico (Ruído de Ambiente) ---
        # Calculamos média móvel de sucessos de tentativas passadas (Moving average of successes)
        relevant = [o for o in self.observations if o.event_type == action_type]
        
        if not relevant:
             return {
                'action_type': action_type,
                'simulation_type': 'probabilistic',
                'predicted_outcome': 'unknown',
                'state_delta': {},
                'confidence': 0.0,
                'warning': 'Zero histórico para essa ação. Alucinação evitada. Confiança cega assumida de 50%.'
            }
            
        success_count = sum(1 for o in relevant if o.outcome.lower() in ('success', 'ok', 'true', '1', 'resolved'))
        win_rate = success_count / len(relevant)
        
        pred_outcome = 'success' if win_rate >= 0.5 else 'failure'
        
        res = {
            'action_type': action_type,
            'simulation_type': 'probabilistic',
            'predicted_outcome': pred_outcome,
            'state_delta': {'expected_win_rate': round(win_rate, 4)},
            'confidence': round(max(win_rate, 1 - win_rate), 4),
            'warning': f'Baseado em histórico probabilístico de {len(relevant)} observações passadas.'
        }

        # Publish to global workspace
        try:
            from ultronpro import store
            store.publish_workspace(
                module='world_model',
                channel='world.simulation',
                payload_json=json.dumps(res),
                salience=0.6,
                ttl_sec=300
            )
        except Exception:
            pass

        return res

    def clear(self):
        """Limpa o modelo."""
        self.observations.clear()
        self.entities.clear()
        self.version = 0
        self._save()


_world_model: Optional[WorldModel] = None


def get_world_model() -> WorldModel:
    global _world_model
    if _world_model is None:
        _world_model = WorldModel()
    return _world_model


def observe(source: str, event_type: str, content: str,
           state_before: dict | None = None, state_after: dict | None = None,
           outcome: str = 'unknown', metadata: dict | None = None) -> Observation:
    return get_world_model().observe(source, event_type, content, state_before, state_after, outcome, metadata)


def update_entity(entity_id: str, data: dict):
    get_world_model().update_entity(entity_id, data)


def get_entity(entity_id: str) -> Optional[dict]:
    return get_world_model().get_entity(entity_id)


def get_world_state() -> dict:
    return get_world_model().get_state_summary()


def predict_next(event_type: str) -> dict | None:
    return get_world_model().predict_next(event_type)


def simulate_action(action_type: str, params: dict) -> dict:
    return get_world_model().simulate_action(action_type, params)
