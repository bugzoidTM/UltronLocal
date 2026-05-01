"""
Causal Discovery — Descoberta Causal
=====================================

Sistema de descoberta causal que aprende relações causais a partir de observações
e realiza inferência para prever resultados de intervenções.

Funcionalidades:
- Detecção de padrões causais em observações temporais
- Construção de grafo causal a partir de dados
- Inferência causal (do-calculus)
- Avaliação de intervenções
- Descoberta de variáveis latentes

"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from dataclasses import dataclass, asdict, field
from typing import Any, Optional
from collections import deque, defaultdict
from statistics import mean, stdev

DATA_DIR = Path(__file__).resolve().parent.parent.parent / 'data'
CAUSAL_DISCOVERY_PATH = DATA_DIR / 'causal_discovery.json'


@dataclass
class CausalEdge:
    cause: str
    effect: str
    strength: float
    confidence: float
    observations: int
    lag: int
    created_at: int
    last_seen: int
    knowledge_type: str = "observational"  # observational, interventional_weak, interventional_strong



@dataclass
class CausalHypothesis:
    id: str
    cause: str
    effect: str
    mechanism: str
    evidence: list[str]
    confidence: float
    testable: bool
    created_at: int


class CausalDiscovery:
    MIN_OBSERVATIONS = 3
    MAX_EDGES = 200
    CORRELATION_THRESHOLD = 0.6
    
    def __init__(self):
        self.edges: dict[tuple[str, str], CausalEdge] = {}
        self.hypotheses: list[CausalHypothesis] = []
        self.observations: deque = deque(maxlen=1000)
        self._load()

    def _load(self):
        if not CAUSAL_DISCOVERY_PATH.exists():
            return
        try:
            data = json.loads(CAUSAL_DISCOVERY_PATH.read_text(encoding='utf-8'))
            self.edges = {
                (e['cause'], e['effect']): CausalEdge(**e)
                for e in data.get('edges', [])
            }
            self.hypotheses = [CausalHypothesis(**h) for h in data.get('hypotheses', [])]
            self.observations = deque(data.get('observations', []), maxlen=1000)
        except Exception:
            pass

    def _save(self):
        data = {
            'edges': [asdict(e) for e in self.edges.values()],
            'hypotheses': [asdict(h) for h in self.hypotheses],
            'observations': list(self.observations),
            'updated_at': int(time.time()),
        }
        CAUSAL_DISCOVERY_PATH.parent.mkdir(parents=True, exist_ok=True)
        CAUSAL_DISCOVERY_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2))

    def add_observation(self, event_type: str, outcome: str, context: dict | None = None):
        """Adiciona uma observação para análise causal e correlação genérica."""
        obs = {
            'id': f"obs_{time.time()}_{uuid.uuid4().hex[:6]}",
            'ts': int(time.time()),
            'event_type': event_type,
            'outcome': outcome,
            'context': context or {},
        }
        self.observations.append(obs)
        self._analyze_correlations()
        self._save()

    def record_closed_domain_intervention(self, domain: str, action: str, magnitude: float, direction: str, context: dict | None = None):
        """Registra uma intervenção real executada no Domínio Causal Fechado.
        As observações aqui são usadas pelo Árbitro Primário para validar hipóteses do LLM.
        Magnitude e direção (increase/decrease) são mapeadas formalmente como evidência robusta.
        """
        obs = {
            'id': f"intv_{time.time()}_{uuid.uuid4().hex[:6]}",
            'ts': int(time.time()),
            'domain': domain,
            'event_type': f"[{domain}] {action}",
            'outcome': direction,
            'magnitude': float(magnitude),
            'context': context or {},
            'is_formal_intervention': True
        }
        # A intervenção formal entra também no pipeline de observações e reforça a aresta causal mais forte.
        self.observations.append(obs)
        self._analyze_correlations()
        self._save()

    # ── Closed-Loop Prediction-Error Propagation ────────────────────

    def register_prediction(self, domain: str, action: str, expected_outcome: str,
                            expected_magnitude: float, confidence: float,
                            context: dict | None = None) -> dict:
        """PRE-ACTION: Registra a previsão explícita antes de executar.
        'Espero que Y mude de V1 para V2 com confiança C'.
        Retorna um prediction_id para ser resolvido após a execução.
        """
        pred = {
            'prediction_id': f"pred_{time.time()}_{uuid.uuid4().hex[:6]}",
            'ts': int(time.time()),
            'domain': domain,
            'action': action,
            'expected_outcome': expected_outcome,       # 'increase' | 'decrease'
            'expected_magnitude': float(expected_magnitude),
            'confidence': max(0.01, min(1.0, float(confidence))),
            'context': context or {},
            'resolved': False,
        }
        self.observations.append(pred)
        self._save()
        return pred

    def measure_and_propagate(self, prediction_id: str, actual_outcome: str,
                              actual_magnitude: float) -> dict:
        """POST-ACTION: Mede o resultado real, calcula o erro e propaga
        para as arestas causais relevantes.

        Ajuste de peso:
          - Proporcional à magnitude do erro
          - Inversamente proporcional à confiança prévia
          - Direção: reforça se acertou, enfraquece se errou
        """
        # Buscar a previsão original
        pred = None
        for obs in self.observations:
            if isinstance(obs, dict) and obs.get('prediction_id') == prediction_id:
                pred = obs
                break
        if not pred:
            return {'ok': False, 'reason': 'prediction_not_found'}

        pred['resolved'] = True
        pred['actual_outcome'] = actual_outcome
        pred['actual_magnitude'] = float(actual_magnitude)

        # ── Calcular Erro de Previsão ──
        direction_match = (pred['expected_outcome'] == actual_outcome)
        magnitude_error = abs(pred['expected_magnitude'] - actual_magnitude)
        max_mag = max(abs(pred['expected_magnitude']), abs(actual_magnitude), 1.0)
        normalized_error = magnitude_error / max_mag   # 0..1
        prior_confidence = pred['confidence']

        # Surpresa = erro normalizado (0 = previsão perfeita, 1 = completamente errado)
        surprise = normalized_error if direction_match else min(1.0, normalized_error + 0.5)

        # ── Learning Rate inversamente proporcional à confiança prévia ──
        # Alta confiança + grande erro = ajuste grande (o modelo estava "seguro" e errou)
        # Baixa confiança + pequeno erro = ajuste pequeno (já esperávamos incerteza)
        learning_rate = surprise * (1.0 / max(0.1, prior_confidence))
        learning_rate = min(0.25, learning_rate)  # Cap para evitar oscilação

        # ── Propagar para arestas relevantes ──
        action_key = pred['action']
        domain_key = pred['domain']
        propagated_edges = []

        for key, edge in self.edges.items():
            # Aresta é relevante se causa ou efeito contém o domínio/ação
            cause_match = (action_key in edge.cause or domain_key in edge.cause)
            effect_match = (domain_key in edge.effect or action_key in edge.effect)
            if not (cause_match or effect_match):
                continue

            old_strength = edge.strength
            old_confidence = edge.confidence

            if direction_match and surprise < 0.3:
                # Previsão acertada: reforçar aresta
                edge.confidence = min(0.99, edge.confidence + learning_rate * 0.5)
                edge.strength = edge.strength + (learning_rate * 0.1 * (1 if edge.strength >= 0 else -1))
                # Promover knowledge_type se estiver sendo repetidamente confirmada
                if edge.observations >= 5 and edge.confidence >= 0.8:
                    edge.knowledge_type = 'interventional_strong'
                elif edge.knowledge_type == 'observational':
                    edge.knowledge_type = 'interventional_weak'
            else:
                # Previsão errada: enfraquecer aresta proporcionalmente
                edge.confidence = max(0.05, edge.confidence - learning_rate)
                edge.strength = edge.strength * (1.0 - learning_rate * 0.3)
                # Degradar knowledge_type se confiança caiu muito
                if edge.confidence < 0.4 and edge.knowledge_type == 'interventional_strong':
                    edge.knowledge_type = 'interventional_weak'

            edge.observations += 1
            edge.last_seen = int(time.time())

            propagated_edges.append({
                'edge': f"{edge.cause}->{edge.effect}",
                'old_confidence': round(old_confidence, 4),
                'new_confidence': round(edge.confidence, 4),
                'old_strength': round(old_strength, 4),
                'new_strength': round(edge.strength, 4),
                'knowledge_type': edge.knowledge_type,
            })

        self._save()

        result = {
            'ok': True,
            'prediction_id': prediction_id,
            'direction_match': direction_match,
            'magnitude_error': round(magnitude_error, 4),
            'normalized_error': round(normalized_error, 4),
            'surprise': round(surprise, 4),
            'learning_rate': round(learning_rate, 4),
            'prior_confidence': round(prior_confidence, 4),
            'edges_propagated': len(propagated_edges),
            'propagation_details': propagated_edges,
        }

        # Publicar o sinal de treinamento no workspace
        try:
            from ultronpro import store
            store.publish_workspace(
                module='causal_discovery',
                channel='causal.prediction_error',
                payload_json=json.dumps({
                    'prediction_id': prediction_id,
                    'surprise': round(surprise, 4),
                    'edges_updated': len(propagated_edges),
                    'direction_match': direction_match,
                }),
                salience=0.7 if surprise > 0.3 else 0.4,
                ttl_sec=1800
            )
        except Exception:
            pass

        return result

    def _analyze_correlations(self):
        """Analisa correlações entre eventos para descobrir potenciais causas."""
        if len(self.observations) < self.MIN_OBSERVATIONS:
            return
        
        events = defaultdict(list)
        for obs in self.observations:
            et = obs.get('event_type', '')
            out = obs.get('outcome', '')
            if et:
                events[et].append(out)
        
        event_types = list(events.keys())
        for i, cause_et in enumerate(event_types):
            for effect_et in event_types[i+1:]:
                cause_outcomes = events[cause_et]
                effect_outcomes = events[effect_et]
                
                if len(cause_outcomes) < 2 or len(effect_outcomes) < 2:
                    continue
                
                corr = self._compute_correlation(cause_outcomes, effect_outcomes)
                
                if abs(corr) >= self.CORRELATION_THRESHOLD:
                    key = (cause_et, effect_et)
                    
                    cause_intervention_count = sum(1 for obs in self.observations if obs.get('event_type') == cause_et and obs.get('is_formal_intervention'))
                    
                    k_type = "observational"
                    if cause_intervention_count > 0:
                        k_type = "interventional_weak"
                        if cause_intervention_count >= 5 and abs(corr) >= 0.8:
                            k_type = "interventional_strong"

                    if key in self.edges:
                        edge = self.edges[key]
                        edge.strength = (edge.strength * edge.observations + corr) / (edge.observations + 1)
                        edge.observations += 1
                        edge.last_seen = int(time.time())
                        if k_type != "observational" and k_type != edge.knowledge_type:
                            # Upgrade edge knowledge type if it qualifies
                            if k_type == "interventional_strong" or (k_type == "interventional_weak" and edge.knowledge_type == "observational"):
                                edge.knowledge_type = k_type
                    else:
                        self.edges[key] = CausalEdge(
                            cause=cause_et,
                            effect=effect_et,
                            strength=corr,
                            confidence=abs(corr),
                            observations=1,
                            lag=1,
                            created_at=int(time.time()),
                            last_seen=int(time.time()),
                            knowledge_type=k_type
                        )
        
        if len(self.edges) > self.MAX_EDGES:
            sorted_edges = sorted(self.edges.items(), key=lambda x: x[1].confidence)
            for k, _ in sorted_edges[:len(self.edges) - self.MAX_EDGES]:
                del self.edges[k]

    def _compute_correlation(self, x: list, y: list) -> float:
        """Calcula correlação simples entre duas listas."""
        if len(x) != len(y) or len(x) < 2:
            return 0.0
        
        try:
            mean_x = mean(x)
            mean_y = mean(y)
            
            num = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
            den_x = sum((xi - mean_x) ** 2 for xi in x)
            den_y = sum((yi - mean_y) ** 2 for yi in y)
            
            if den_x == 0 or den_y == 0:
                return 0.0
            
            return num / (den_x * den_y) ** 0.5
        except (ValueError, TypeError):
            return 0.0

    def discover_causal_hypotheses(self) -> list[CausalHypothesis]:
        """Gera hipóteses causais a partir das arestas descobertas."""
        new_hypotheses = []
        
        for edge in self.edges.values():
            existing = any(h.cause == edge.cause and h.effect == edge.effect for h in self.hypotheses)
            if existing:
                continue
            
            if edge.confidence < 0.5:
                continue
            
            hypothesis = CausalHypothesis(
                id=f"hyp_{int(time.time())}_{uuid.uuid4().hex[:6]}",
                cause=edge.cause,
                effect=edge.effect,
                mechanism=f"{edge.cause} influencia {edge.effect} com força {edge.strength:.2f}",
                evidence=[f"{edge.observations} observações", f"correlação: {edge.strength:.2f}"],
                confidence=edge.confidence,
                testable=edge.observations >= 5,
                created_at=int(time.time()),
            )
            new_hypotheses.append(hypothesis)
        
        self.hypotheses.extend(new_hypotheses[:10])
        self.hypotheses = self.hypotheses[-50:]
        
        return new_hypotheses

    def infer_causal_effect(self, cause: str, effect: str) -> dict:
        """Infere o efeito causal entre causa e efeito."""
        key = (cause, effect)
        
        if key in self.edges:
            edge = self.edges[key]
            return {
                'cause': cause,
                'effect': effect,
                'inferred_effect': edge.strength,
                'confidence': edge.confidence,
                'observations': edge.observations,
            }
        
        reverse_key = (effect, cause)
        if reverse_key in self.edges:
            edge = self.edges[reverse_key]
            return {
                'cause': cause,
                'effect': effect,
                'inferred_effect': -edge.strength,
                'confidence': edge.confidence * 0.8,
                'observations': edge.observations,
            }
        
        return {
            'cause': cause,
            'effect': effect,
            'inferred_effect': 0.0,
            'confidence': 0.0,
            'observations': 0,
        }

    def simulate_intervention(self, intervention: dict[str, Any], steps: int = 3) -> dict:
        """Simula o efeito de uma intervenção."""
        cause = intervention.get('cause')
        effect_size = intervention.get('effect_size', 1.0)
        
        if not cause:
            return {'error': 'Causa não especificada'}
        
        affected_edges = [(k, e) for k, e in self.edges.items() if k[0] == cause]
        
        if not affected_edges:
            return {
                'cause': cause,
                'effect_size': effect_size,
                'downstream_effects': [],
                'confidence': 0.0,
            }
        
        downstream = []
        visited = set()
        queue = [(cause, effect_size)]
        
        for _ in range(steps):
            if not queue:
                break
            current_cause, current_effect = queue.pop(0)
            
            for (c, e), edge in self.edges.items():
                if c == current_cause and e not in visited:
                    downstream_effect = current_effect * edge.strength
                    downstream.append({
                        'node': e,
                        'effect': round(downstream_effect, 3),
                        'confidence': edge.confidence,
                    })
                    queue.append((e, downstream_effect))
                    visited.add(e)
        
        avg_confidence = mean([d['confidence'] for d in downstream]) if downstream else 0.0
        
        return {
            'cause': cause,
            'effect_size': effect_size,
            'downstream_effects': downstream,
            'confidence': round(avg_confidence, 3),
            'nodes_affected': len(downstream),
        }

    def get_causal_graph(self) -> dict:
        """Retorna o grafo causal em formato para visualização."""
        nodes = set()
        edges = []
        
        for edge in self.edges.values():
            nodes.add(edge.cause)
            nodes.add(edge.effect)
            edges.append({
                'from': edge.cause,
                'to': edge.effect,
                'label': f"{edge.strength:.2f}",
                'color': '#10b981' if edge.strength > 0 else '#ef4444',
            })
        
        return {
            'nodes': [{'id': n} for n in nodes],
            'edges': edges,
        }

    def get_status(self) -> dict:
        """Retorna status do sistema de descoberta causal."""
        return {
            'edge_count': len(self.edges),
            'hypothesis_count': len(self.hypotheses),
            'observation_count': len(self.observations),
            'top_edges': [
                {
                    'cause': e.cause,
                    'effect': e.effect,
                    'strength': round(e.strength, 3),
                    'confidence': round(e.confidence, 3),
                    'observations': e.observations,
                }
                for e in sorted(self.edges.values(), key=lambda x: x.confidence, reverse=True)[:10]
            ],
            'testable_hypotheses': sum(1 for h in self.hypotheses if h.testable),
        }

    def clear(self):
        """Limpa o sistema."""
        self.edges.clear()
        self.hypotheses.clear()
        self.observations.clear()
        self._save()


_causal_discovery: Optional[CausalDiscovery] = None


def get_causal_discovery() -> CausalDiscovery:
    global _causal_discovery
    if _causal_discovery is None:
        _causal_discovery = CausalDiscovery()
    return _causal_discovery


def add_causal_observation(event_type: str, outcome: str, context: dict | None = None):
    return get_causal_discovery().add_observation(event_type, outcome, context)

def record_closed_domain_intervention(domain: str, action: str, magnitude: float, direction: str, context: dict | None = None):
    return get_causal_discovery().record_closed_domain_intervention(domain, action, magnitude, direction, context)


def discover_causal_hypotheses() -> list[CausalHypothesis]:
    return get_causal_discovery().discover_causal_hypotheses()


def infer_causal_effect(cause: str, effect: str) -> dict:
    return get_causal_discovery().infer_causal_effect(cause, effect)


def simulate_causal_intervention(intervention: dict) -> dict:
    return get_causal_discovery().simulate_intervention(intervention)


def get_causal_graph() -> dict:
    return get_causal_discovery().get_causal_graph()


def get_causal_discovery_status() -> dict:
    return get_causal_discovery().get_status()


def register_prediction(domain: str, action: str, expected_outcome: str,
                         expected_magnitude: float, confidence: float,
                         context: dict | None = None) -> dict:
    return get_causal_discovery().register_prediction(
        domain, action, expected_outcome, expected_magnitude, confidence, context)


def measure_and_propagate(prediction_id: str, actual_outcome: str,
                           actual_magnitude: float) -> dict:
    return get_causal_discovery().measure_and_propagate(
        prediction_id, actual_outcome, actual_magnitude)
