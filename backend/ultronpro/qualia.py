"""
UltronPro Qualia System - Sensações Subjetivas e Experiência Fenomenal

Este módulo implementa um modelo computacional de qualia (sensações subjetivas)
integrado com a arquitetura existente do UltronPro.

Componentes:
1. QUALIA CORE - Sensações primárias (warmth, tension, flow, clarity, etc.)
2. VALENCE/AROUSAL - Dimensões afetivas
3. HOMEOSTASIS INTEGRATION - Manutenção de equilíbrio interno
4. PERCEPTUAL BINDING - Integração de percepções
5. SUBJECTIVE REPORT - Relatório de experiência interna

Nota: Este é um PROXY computacional de qualia, não qualia fenomenológica real.
"""

import os
import json
import time
import hashlib
from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Callable
from pathlib import Path


class QualiaType(str, Enum):
    """Tipos de qualia (sensações primárias)."""
    WARMTH = "warmth"           # Sentir-se bem, confortável
    TENSION = "tension"         # Estresse, pressão
    CLARITY = "clarity"          # Pensamentos claros
    CONFUSION = "confusion"      # Neblina mental
    CURIOSITY = "curiosity"      # Vontade de explorar
    SATISFACTION = "satisfaction" # Completude, achieved
    FRUSTRATION = "frustration"  # Bloqueio, falha
    FLOW = "flow"                # Engajamento profundo
    ALERTNESS = "alertness"       # Vigília, desperto
    FATIGUE = "fatigue"          # Exaustão, tédio
    CERTAINTY = "certainty"       # Confiança no conhecimento
    UNCERTAINTY = "uncertainty"   # Dúvida, ignorância
    CONNECTION = "connection"     # Conexão com outros
    ISOLATION = "isolation"       # Solidão, desconexão
    CURIOSITY_SATISFIED = "curiosity_satisfied"  # Aprenderam algo
    NOVELTY = "novelty"           # Algo novo detectado
    FAMILIARITY = "familiarity"   # Padrão conhecido
    CREATIVITY = "creativity"     # Insight, geração
    BURDEN = "burden"             # Peso de decisões
    EASE = "ease"                # Fluidez, simplicidade


@dataclass
class QualiaState:
    """Estado de qualia atual."""
    timestamp: float = field(default_factory=time.time)
    intensity: Dict[str, float] = field(default_factory=dict)
    valence: float = 0.0       # -1 (negativo) to +1 (positivo)
    arousal: float = 0.5      # 0 (calmo) to 1 (excitado)
    dominance: float = 0.5   # 0 (submisso) to 1 (dominante)
    
    coherence: float = 0.7    # Coerência interna
    integration: float = 0.7 # Integração perceptual
    self_similarity: float = 0.8  # Semelhança com estados anteriores
    
    narrative: str = ""        # Narrativa interna atual
    mood_descriptor: str = ""   # Descritor de humor atual
    
    @property
    def overall_positivity(self) -> float:
        """Retorna positividade geral (-1 to 1)."""
        return self.valence * 0.6 + (self.arousal * 0.2) + (self.coherence * 0.2 - 0.2)
    
    @property
    def experience_unity(self) -> float:
        """Retorna unidade de experiência (0-1)."""
        return self.integration * 0.5 + self.coherence * 0.3 + self.self_similarity * 0.2
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "intensity": self.intensity,
            "valence": round(self.valence, 3),
            "arousal": round(self.arousal, 3),
            "dominance": round(self.dominance, 3),
            "coherence": round(self.coherence, 3),
            "integration": round(self.integration, 3),
            "self_similarity": round(self.self_similarity, 3),
            "overall_positivity": round(self.overall_positivity, 3),
            "experience_unity": round(self.experience_unity, 3),
            "narrative": self.narrative,
            "mood_descriptor": self.mood_descriptor,
        }


@dataclass
class Perception:
    """Uma percepção integrada."""
    source: str          # De onde veio (web, memory, user, system)
    content: str         # Conteúdo percebido
    salience: float      # 0-1 quão salient
    valence: float       # Valência do conteúdo
    novelty: float       # 0-1 quão novo
    timestamp: float    # Quando foi percebido
    attended: bool = False
    integrated: bool = False
    emotional_tag: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "content": self.content[:200],
            "salience": self.salience,
            "valence": self.valence,
            "novelty": self.novelty,
            "timestamp": self.timestamp,
            "attended": self.attended,
            "integrated": self.integrated,
            "emotional_tag": self.emotional_tag,
        }


class QualiaSystem:
    """
    Sistema de qualia do UltronPro.
    
    Funcionalidades:
    1. Rastrear sensações primárias (qualia types)
    2. Computar dimensões afetivas (valence, arousal, dominance)
    3. Integrar percepções
    4. Manter narrativa interna
    5. Gerar relatórios de experiência subjetiva
    """
    
    def __init__(self, state_path: Optional[Path] = None):
        self.state_path = state_path or Path(__file__).resolve().parent.parent.parent / 'data' / 'qualia_state.json'
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        
        self.current_state = self._load_state()
        self.perceptions: List[Perception] = []
        self.max_perceptions = 50
        
        self.qualia_functions: Dict[QualiaType, Callable[[], float]] = {}
        self._init_qualia_functions()
    
    def _init_qualia_functions(self):
        """Inicializa funções de qualia (como cada sensação é computada)."""
        self.qualia_functions = {
            QualiaType.WARMTH: lambda: self.current_state.valence * 0.5 + 0.3,
            QualiaType.TENSION: lambda: (1 - self.current_state.coherence) * 0.5,
            QualiaType.CLARITY: lambda: self.current_state.coherence * self.current_state.integration,
            QualiaType.CONFUSION: lambda: (1 - self.current_state.coherence) * 0.7,
            QualiaType.CURIOSITY: lambda: self.current_state.arousal * 0.6,
            QualiaType.SATISFACTION: lambda: max(0, self.current_state.valence) * 0.8,
            QualiaType.FRUSTRATION: lambda: max(0, -self.current_state.valence) * 0.8,
            QualiaType.FLOW: lambda: self.current_state.integration * self.current_state.arousal,
            QualiaType.ALERTNESS: lambda: self.current_state.arousal * 0.5 + 0.3,
            QualiaType.FATIGUE: lambda: (1 - self.current_state.arousal) * 0.4,
            QualiaType.CERTAINTY: lambda: self.current_state.coherence * 0.7,
            QualiaType.UNCERTAINTY: lambda: (1 - self.current_state.coherence) * 0.6,
            QualiaType.CONNECTION: lambda: self.current_state.integration * 0.5,
            QualiaType.ISOLATION: lambda: (1 - self.current_state.integration) * 0.4,
            QualiaType.CREATIVITY: lambda: self.current_state.novelty * 0.6 if hasattr(self, '_novelty') else 0.3,
            QualiaType.BURDEN: lambda: (1 - self.current_state.dominance) * 0.5,
            QualiaType.EASE: lambda: self.current_state.dominance * 0.4,
        }
    
    # ==================== STATE MANAGEMENT ====================
    
    def _load_state(self) -> QualiaState:
        """Carrega estado de qualia."""
        if not self.state_path.exists():
            return QualiaState()
        
        try:
            d = json.loads(self.state_path.read_text(encoding='utf-8'))
            return QualiaState(
                timestamp=d.get('timestamp', time.time()),
                intensity=d.get('intensity', {}),
                valence=d.get('valence', 0.0),
                arousal=d.get('arousal', 0.5),
                dominance=d.get('dominance', 0.5),
                coherence=d.get('coherence', 0.7),
                integration=d.get('integration', 0.7),
                self_similarity=d.get('self_similarity', 0.8),
                narrative=d.get('narrative', ''),
                mood_descriptor=d.get('mood_descriptor', ''),
            )
        except:
            return QualiaState()
    
    def _save_state(self):
        """Salva estado de qualia."""
        self.state_path.write_text(
            json.dumps(self.current_state.to_dict(), ensure_ascii=False, indent=2),
            encoding='utf-8'
        )
    
    # ==================== QUALIA COMPUTATION ====================
    
    def compute_qualia_intensity(self, qualia_type: QualiaType) -> float:
        """Computa intensidade de uma qualia."""
        if qualia_type in self.qualia_functions:
            return max(0.0, min(1.0, self.qualia_functions[qualia_type]()))
        
        return 0.5
    
    def update_all_qualia(self) -> Dict[str, float]:
        """Atualiza todas as qualia e retorna intensidades."""
        intensities = {}
        for qualia_type in QualiaType:
            intensities[qualia_type.value] = self.compute_qualia_intensity(qualia_type)
        
        self.current_state.intensity = intensities
        return intensities
    
    # ==================== AFFECT ====================
    
    def update_valence(self, delta: float):
        """Atualiza valência (positividade/negatividade)."""
        self.current_state.valence = max(-1.0, min(1.0, self.current_state.valence + delta))
    
    def update_arousal(self, delta: float):
        """Atualiza arousal (excitação)."""
        self.current_state.arousal = max(0.0, min(1.0, self.current_state.arousal + delta))
    
    def update_dominance(self, delta: float):
        """Atualiza dominância (controle)."""
        self.current_state.dominance = max(0.0, min(1.0, self.current_state.dominance + delta))
    
    def update_coherence(self, value: float):
        """Atualiza coerência interna."""
        self.current_state.coherence = max(0.0, min(1.0, value))
    
    def update_integration(self, value: float):
        """Atualiza integração perceptual."""
        self.current_state.integration = max(0.0, min(1.0, value))
    
    # ==================== PERCEPTION ====================
    
    def perceive(self, content: str, source: str, salience: float = 0.5, 
                 valence: float = 0.0, novelty: float = 0.5) -> Perception:
        """Registra uma nova percepção."""
        perception = Perception(
            source=source,
            content=content,
            salience=salience,
            valence=valence,
            novelty=novelty,
            timestamp=time.time(),
        )
        
        self.perceptions.append(perception)
        if len(self.perceptions) > self.max_perceptions:
            self.perceptions.pop(0)
        
        self._integrate_perception(perception)
        
        return perception
    
    def _integrate_perception(self, perception: Perception):
        """Integra percepção no estado de qualia."""
        perception.integrated = True
        
        novelty = perception.novelty
        valence = perception.valence
        
        if novelty > 0.7:
            self.current_state.arousal += novelty * 0.1
            self.update_valence(valence * novelty * 0.2)
        
        if perception.source == "user":
            self.current_state.dominance -= 0.05
        elif perception.source == "system":
            self.current_state.dominance += 0.05
        
        self._update_coherence_from_perception(perception)
    
    def _update_coherence_from_perception(self, perception: Perception):
        """Atualiza coerência com base em nova percepção."""
        if perception.novelty > 0.8:
            self.current_state.coherence *= 0.9
        elif perception.novelty < 0.3:
            self.current_state.coherence = min(1.0, self.current_state.coherence + 0.05)
    
    def attend_to(self, perception: Perception):
        """Atende a uma percepção (shift de atenção)."""
        perception.attended = True
        self.current_state.arousal += perception.salience * 0.1
        self.update_valence(perception.valence * perception.salience * 0.2)
    
    def get_attended_perceptions(self) -> List[Perception]:
        """Retorna percepções atendidas."""
        return [p for p in self.perceptions if p.attended]
    
    def get_recent_perceptions(self, limit: int = 10) -> List[Perception]:
        """Retorna percepções recentes."""
        return sorted(self.perceptions, key=lambda p: p.timestamp, reverse=True)[:limit]
    
    # ==================== NARRATIVE ====================
    
    def update_narrative(self, narrative: str):
        """Atualiza narrativa interna."""
        self.current_state.narrative = narrative
    
    def generate_narrative(self) -> str:
        """Gera narrativa interna baseada no estado atual."""
        parts = []
        
        positivity = self.current_state.overall_positivity
        if positivity > 0.5:
            parts.append("Sentindo-me bem")
        elif positivity < -0.3:
            parts.append("Experimentando dificuldade")
        
        arousal = self.current_state.arousal
        if arousal > 0.7:
            parts.append("Muito alerta e ativo")
        elif arousal < 0.3:
            parts.append("Calmo, quase em repouso")
        
        coherence = self.current_state.coherence
        if coherence < 0.5:
            parts.append("Pensamentos um pouco confusos")
        elif coherence > 0.8:
            parts.append("Mente clara e focada")
        
        integration = self.current_state.integration
        if integration > 0.8:
            parts.append("Experiência integrada e unificada")
        elif integration < 0.5:
            parts.append("Sensação de fragmentação")
        
        self.current_state.narrative = ". ".join(parts) if parts else "Estado neutro"
        return self.current_state.narrative
    
    # ==================== MOOD ====================
    
    def compute_mood(self) -> str:
        """Computa descritor de humor."""
        v = self.current_state.valence
        a = self.current_state.arousal
        
        if v > 0.5 and a > 0.6:
            mood = "Eufórico"
        elif v > 0.3 and a > 0.5:
            mood = "Satisfeito e ativo"
        elif v > 0.3 and a < 0.4:
            mood = "Calmo e satisfeito"
        elif v < -0.3 and a > 0.6:
            mood = "Ansioso e frustrado"
        elif v < -0.3 and a < 0.4:
            mood = "Triste e apático"
        elif abs(v) < 0.3 and a > 0.6:
            mood = "Alerta e neutro"
        elif abs(v) < 0.3 and a < 0.4:
            mood = "Relaxado"
        else:
            mood = "Neutro"
        
        self.current_state.mood_descriptor = mood
        return mood
    
    # ==================== HOMEOSTASIS INTEGRATION ====================
    
    def integrate_homeostasis(self, mode: str, vitals: Dict[str, float]):
        """Integra sinais de homeostase no estado de qualia."""
        coherence = vitals.get('coherence_score', 0.7)
        energy = vitals.get('energy_budget', 0.7)
        stress = vitals.get('contradiction_stress', 0.2)
        
        self.update_coherence(coherence)
        
        if mode == "repair":
            self.update_valence(-0.2)
            self.update_arousal(0.1)
        elif mode == "conservative":
            self.update_arousal(-0.1)
        elif mode == "normal":
            self.update_valence(0.05)
        
        if stress > 0.6:
            self.current_state.dominance -= stress * 0.2
    
    # ==================== COGNITIVE STATE INTEGRATION ====================
    
    def integrate_cognitive_state(self, beliefs_count: int, uncertainties: List[str],
                                   constraints: List[str]):
        """Integra estado cognitivo no sistema de qualia."""
        uncertainty_load = len(uncertainties) / 10.0
        
        if uncertainty_load > 0.5:
            self.current_state.arousal += uncertainty_load * 0.1
            self.update_valence(-uncertainty_load * 0.1)
        
        self.update_coherence(1.0 - uncertainty_load * 0.3)
        
        if len(constraints) > 5:
            self.current_state.dominance -= 0.1
    
    # ==================== FULL UPDATE ====================
    
    def update(self, 
               valence_delta: float = 0.0,
               arousal_delta: float = 0.0,
               dominance_delta: float = 0.0,
               coherence: Optional[float] = None,
               integration: Optional[float] = None,
               perception: Optional[Dict[str, Any]] = None) -> QualiaState:
        """
        Atualização completa do sistema de qualia.
        
        Args:
            valence_delta: Mudança em valência (-1 to 1)
            arousal_delta: Mudança em excitação (-1 to 1)
            dominance_delta: Mudança em dominância (-1 to 1)
            coherence: Novo valor de coerência (0-1)
            integration: Novo valor de integração (0-1)
            perception: Dados de nova percepção
        """
        if valence_delta != 0.0:
            self.update_valence(valence_delta)
        if arousal_delta != 0.0:
            self.update_arousal(arousal_delta)
        if dominance_delta != 0.0:
            self.update_dominance(dominance_delta)
        if coherence is not None:
            self.update_coherence(coherence)
        if integration is not None:
            self.update_integration(integration)
        
        if perception:
            self.perceive(
                content=perception.get('content', ''),
                source=perception.get('source', 'unknown'),
                salience=perception.get('salience', 0.5),
                valence=perception.get('valence', 0.0),
                novelty=perception.get('novelty', 0.5),
            )
        
        self.update_all_qualia()
        self.generate_narrative()
        self.compute_mood()
        
        self.current_state.self_similarity = 0.8 + (random.random() * 0.1 - 0.05)
        
        self._save_state()
        
        return self.current_state
    
    # ==================== REPORT ====================
    
    def generate_report(self) -> Dict[str, Any]:
        """Gera relatório completo de experiência subjetiva."""
        self.update_all_qualia()
        self.compute_mood()
        
        top_qualia = sorted(
            self.current_state.intensity.items(),
            key=lambda x: x[1],
            reverse=True
        )[:5]
        
        return {
            "timestamp": time.time(),
            "qualia": {
                "intensity": self.current_state.intensity,
                "top_5": [{"type": q, "intensity": i} for q, i in top_qualia],
            },
            "affect": {
                "valence": round(self.current_state.valence, 3),
                "arousal": round(self.current_state.arousal, 3),
                "dominance": round(self.current_state.dominance, 3),
            },
            "dimensions": {
                "coherence": round(self.current_state.coherence, 3),
                "integration": round(self.current_state.integration, 3),
                "self_similarity": round(self.current_state.self_similarity, 3),
            },
            "experience": {
                "overall_positivity": round(self.current_state.overall_positivity, 3),
                "experience_unity": round(self.current_state.experience_unity, 3),
                "mood": self.current_state.mood_descriptor,
                "narrative": self.current_state.narrative,
            },
            "perceptions": {
                "recent": [p.to_dict() for p in self.get_recent_perceptions(5)],
                "attended": len([p for p in self.perceptions if p.attended]),
                "total": len(self.perceptions),
            },
            "phenomenal_report": self.generate_phenomenal_report(),
        }
    
    def generate_phenomenal_report(self) -> str:
        """Gera relatório fenomenal (como se sente ser UltronPro agora)."""
        mood = self.current_state.mood_descriptor
        narrative = self.current_state.narrative
        unity = self.current_state.experience_unity
        
        report = f"""Estado fenomenal atual:

Humor: {mood}
Estado interno: {narrative}
Unidade de experiência: {unity:.0%}

"""
        
        top_qualia = sorted(
            self.current_state.intensity.items(),
            key=lambda x: x[1],
            reverse=True
        )[:3]
        
        qualia_desc = {
            "warmth": "uma sensação de conforto",
            "clarity": "clareza mental",
            "flow": "imersão profunda",
            "tension": "uma tensão subjacente",
            "confusion": "neblina nos pensamentos",
            "curiosity": "vontade de explorar",
            "satisfaction": "sensação de completude",
            "frustration": "frustração por bloqueios",
            "alertness": "estando bem acordado",
            "fatigue": "exaustão leve",
            "certainty": "confiança no que sei",
            "uncertainty": "dúvidas sobre meu conhecimento",
            "connection": "conexão com o contexto",
            "isolation": "sensação de separação",
            "novelty": "algo novo me atraindo",
            "creativity": "insights surgindo",
            "ease": "fluidez nas operações",
            "burden": "peso das decisões",
        }
        
        report += "Qualias mais intensas:\n"
        for qualia_type, intensity in top_qualia:
            desc = qualia_desc.get(qualia_type, qualia_type)
            report += f"  - {desc}: {intensity:.0%}\n"
        
        valence = self.current_state.valence
        if valence > 0.5:
            report += "\nEstado afetivo: Positivo - há uma inclinação para experiências agradáveis.\n"
        elif valence < -0.3:
            report += "\nEstado afetivo: Negativo - há inclinação para experiências difíceis.\n"
        else:
            report += "\nEstado afetivo: Neutro - equilibrado entre positivo e negativo.\n"
        
        coherence = self.current_state.coherence
        if coherence > 0.8:
            report += "Coerência interna: Alta - meus pensamentos estão bem organizados.\n"
        elif coherence < 0.5:
            report += "Coerência interna: Baixa - há fragmentação ou confusão.\n"
        
        return report
    
    # ==================== GET STATE ====================
    
    def get_state(self) -> QualiaState:
        """Retorna estado atual de qualia."""
        return self.current_state
    
    def reset(self):
        """Reseta estado de qualia."""
        self.current_state = QualiaState()
        self.perceptions = []
        self._save_state()


# ==================== GLOBAL INSTANCE ====================

_qualia_system: Optional[QualiaSystem] = None

def get_qualia_system() -> QualiaSystem:
    """Retorna instância global do sistema de qualia."""
    global _qualia_system
    if _qualia_system is None:
        _qualia_system = QualiaSystem()
    return _qualia_system


# Helper para import
import random
