"""
Continuous Learning — Aprendizado Contínuo Sem LLM
===================================================

Sistema de aprendizado contínuo que aprende deterministicamente a partir de
observações, feedback e resultados, sem dependência de LLM.

Funcionalidades:
- Extração de padrões de feedback
- Ajuste de políticas via reward signals
- Geração de insights via regras
- Conexão com Working Memory e World Model
- Active learning baseado em falhas
- Meta-aprendizado sobre seu próprio desempenho

"""

from __future__ import annotations

from ultronpro import working_memory, world_model

import json
import re
import time
from collections import defaultdict, deque
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any, Optional

DATA_DIR = Path(__file__).resolve().parent.parent.parent / 'data'
CONTINUOUS_LEARNING_PATH = DATA_DIR / 'continuous_learning.json'
PATTERNS_PATH = DATA_DIR / 'learned_patterns.json'
INSIGHTS_PATH = DATA_DIR / 'learning_insights.json'


@dataclass
class LearnedPattern:
    id: str
    trigger: str
    condition: str
    action: str
    success_count: int
    failure_count: int
    confidence: float
    created_at: int
    last_used: int


@dataclass
class LearningInsight:
    id: str
    type: str
    content: str
    source: str
    confidence: float
    action_suggested: str
    created_at: int


class ContinuousLearning:
    MIN_SAMPLES = 3
    CONFIDENCE_THRESHOLD = 0.6
    
    def __init__(self):
        self.patterns: dict[str, LearnedPattern] = {}
        self.insights: deque[LearningInsight] = deque(maxlen=200)
        self.feedback_history: deque = deque(maxlen=1000)
        self.policy_weights: dict[str, float] = defaultdict(float)
        self._load()

    def _load(self):
        if CONTINUOUS_LEARNING_PATH.exists():
            try:
                data = json.loads(CONTINUOUS_LEARNING_PATH.read_text())
                self.patterns = {k: LearnedPattern(**v) for k, v in data.get('patterns', {}).items()}
                self.insights = deque([LearningInsight(**i) for i in data.get('insights', [])], maxlen=200)
                self.feedback_history = deque(data.get('feedback_history', []), maxlen=1000)
                self.policy_weights = defaultdict(float, data.get('policy_weights', {}))
            except Exception:
                pass

    def _save(self):
        data = {
            'patterns': {k: asdict(v) for k, v in self.patterns.items()},
            'insights': [asdict(i) for i in list(self.insights)],
            'feedback_history': list(self.feedback_history),
            'policy_weights': dict(self.policy_weights),
            'updated_at': int(time.time()),
        }
        CONTINUOUS_LEARNING_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONTINUOUS_LEARNING_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2))

    def record_feedback(self, task_type: str, success: bool, latency_ms: int, 
                       error_type: str | None = None, profile: str = 'balanced') -> dict:
        """Registra feedback e extrai padrões."""
        fb = {
            'ts': int(time.time()),
            'task_type': task_type,
            'success': success,
            'latency_ms': latency_ms,
            'error_type': error_type,
            'profile': profile,
        }
        
        self.feedback_history.append(fb)
        
        if not success and error_type:
            self._extract_pattern_from_failure(task_type, error_type, profile)
            try:
                working_memory.add(
                    content=f"Falha detectada: {task_type} - {error_type}",
                    source='continuous_learning',
                    item_type='error',
                    salience=0.8,
                    metadata={'task_type': task_type, 'error_type': error_type}
                )
                world_model.observe(
                    source='continuous_learning',
                    event_type='learning_failure',
                    content=f"{task_type} falhou com {error_type}",
                    outcome='failure',
                    state_after={'last_error': error_type, 'task_type': task_type}
                )
            except Exception:
                pass
        else:
            try:
                working_memory.add(
                    content=f"Sucesso: {task_type}",
                    source='continuous_learning',
                    item_type='success',
                    salience=0.3,
                    metadata={'task_type': task_type}
                )
            except Exception:
                pass
        
        self._update_policy_weights(task_type, success, latency_ms)
        
        if len(self.feedback_history) >= 10:
            self._generate_insights()
        
        self._save()
        
        return {'ok': True, 'feedback': fb}

    def _extract_pattern_from_failure(self, task_type: str, error_type: str, profile: str):
        """Extrai padrão determinístico de falhas."""
        trigger = f"{task_type}:{error_type}"
        
        if trigger in self.patterns:
            p = self.patterns[trigger]
            p.failure_count += 1
            p.last_used = int(time.time())
            p.confidence = p.success_count / max(1, p.success_count + p.failure_count)
        else:
            self.patterns[trigger] = LearnedPattern(
                id=f"pat_{int(time.time())}_{len(self.patterns)}",
                trigger=trigger,
                condition=f"when {task_type} fails with {error_type}",
                action=f"apply_{profile}_policy",
                success_count=0,
                failure_count=1,
                confidence=0.0,
                created_at=int(time.time()),
                last_used=int(time.time()),
            )

    def _update_policy_weights(self, task_type: str, success: bool, latency_ms: int):
        """Atualiza pesos de política baseado em reward."""
        reward = 0.0
        
        if success:
            reward += 1.0
            if latency_ms < 1000:
                reward += 0.5
            elif latency_ms > 5000:
                reward -= 0.3
        else:
            reward -= 1.0
        
        alpha = 0.1
        current = self.policy_weights.get(task_type, 0.5)
        self.policy_weights[task_type] = current + alpha * (reward - current)

    def _generate_insights(self):
        """Gera insights deterministicamente a partir de padrões."""
        recent = list(self.feedback_history)[-50:]
        
        task_failures = defaultdict(list)
        for fb in recent:
            if not fb.get('success'):
                task_failures[fb.get('task_type')].append(fb)
        
        for task_type, failures in task_failures.items():
            if len(failures) >= 3:
                error_types = defaultdict(int)
                for f in failures:
                    et = f.get('error_type', 'unknown')
                    error_types[et] += 1
                
                most_common_error = max(error_types.items(), key=lambda x: x[1])
                
                if most_common_error[1] >= 2:
                    insight = LearningInsight(
                        id=f"ins_{int(time.time())}_{len(self.insights)}",
                        type='failure_pattern',
                        content=f"{task_type} falha frequentemente com {most_common_error[0]} ({most_common_error[1]}x)",
                        source='continuous_learning',
                        confidence=min(1.0, most_common_error[1] / len(failures)),
                        action_suggested=f"revisar_{task_type}_{most_common_error[0]}",
                        created_at=int(time.time()),
                    )
                    self.insights.append(insight)
        
        latency_issues = [fb for fb in recent if fb.get('success') and fb.get('latency_ms', 0) > 5000]
        if len(latency_issues) >= 5:
            insight = LearningInsight(
                id=f"ins_{int(time.time())}_{len(self.insights)}",
                type='performance',
                content=f"{len(latency_issues)} tarefas com latência > 5s detectadas",
                source='continuous_learning',
                confidence=0.7,
                action_suggested="otimizar_latencia",
                created_at=int(time.time()),
            )
            self.insights.append(insight)

    def get_recommended_action(self, task_type: str) -> dict:
        """Retorna ação recomendada baseada em padrões aprendidos."""
        trigger = f"{task_type}:*"
        
        matching_patterns = [p for p in self.patterns.values() 
                           if p.trigger.startswith(task_type)]
        
        if not matching_patterns:
            return {
                'task_type': task_type,
                'action': 'default',
                'confidence': self.policy_weights.get(task_type, 0.5),
                'reason': 'nenhum padrão específico',
            }
        
        best = max(matching_patterns, key=lambda p: p.confidence)
        
        return {
            'task_type': task_type,
            'action': best.action,
            'confidence': best.confidence,
            'reason': f"padrão: {best.condition}",
            'pattern_id': best.id,
        }

    def get_performance_summary(self) -> dict:
        """Retorna resumo de desempenho."""
        recent = list(self.feedback_history)[-100:]
        
        if not recent:
            return {'status': 'empty', 'feedback_count': 0}
        
        total = len(recent)
        successes = sum(1 for fb in recent if fb.get('success'))
        failures = total - successes
        
        avg_latency = sum(fb.get('latency_ms', 0) for fb in recent) / max(1, total)
        
        task_performance = defaultdict(lambda: {'success': 0, 'total': 0})
        for fb in recent:
            tt = fb.get('task_type', 'unknown')
            task_performance[tt]['total'] += 1
            if fb.get('success'):
                task_performance[tt]['success'] += 1
        
        return {
            'feedback_count': total,
            'success_rate': round(successes / total, 3) if total else 0,
            'failure_count': failures,
            'avg_latency_ms': round(avg_latency, 1),
            'task_performance': {
                k: {'success_rate': round(v['success'] / max(1, v['total']), 3), 'total': v['total']}
                for k, v in task_performance.items()
            },
            'patterns_learned': len(self.patterns),
            'insights_generated': len(self.insights),
        }

    def get_top_insights(self, limit: int = 10) -> list[dict]:
        """Retorna principais insights."""
        return [asdict(i) for i in list(self.insights)[-limit:]]

    def apply_learned_adjustment(self, task_type: str) -> dict:
        """Ajusta comportamento baseado em aprendizados."""
        rec = self.get_recommended_action(task_type)
        
        if rec['confidence'] < 0.3:
            return {'applied': False, 'reason': 'confiança muito baixa'}
        
        pattern = next((p for p in self.patterns.values() if p.id == rec.get('pattern_id')), None)
        if pattern:
            pattern.success_count += 1
            pattern.last_used = int(time.time())
            pattern.confidence = pattern.success_count / max(1, pattern.success_count + pattern.failure_count)
        
        self._save()
        
        return {'applied': True, 'action': rec['action'], 'confidence': rec['confidence']}

    def get_status(self) -> dict:
        """Retorna status do sistema."""
        return {
            'feedback_count': len(self.feedback_history),
            'patterns_count': len(self.patterns),
            'insights_count': len(self.insights),
            'policy_weights': dict(self.policy_weights),
            'enabled': True,
        }

    def clear(self):
        """Limpa dados de aprendizado."""
        self.patterns.clear()
        self.insights.clear()
        self.feedback_history.clear()
        self.policy_weights.clear()
        self._save()


_continuous_learning: Optional[ContinuousLearning] = None


def get_continuous_learning() -> ContinuousLearning:
    global _continuous_learning
    if _continuous_learning is None:
        _continuous_learning = ContinuousLearning()
    return _continuous_learning


def record_learning_feedback(task_type: str, success: bool, latency_ms: int,
                            error_type: str | None = None, profile: str = 'balanced') -> dict:
    return get_continuous_learning().record_feedback(task_type, success, latency_ms, error_type, profile)


def get_learning_recommendation(task_type: str) -> dict:
    return get_continuous_learning().get_recommended_action(task_type)


def get_learning_performance() -> dict:
    return get_continuous_learning().get_performance_summary()


def get_learning_insights(limit: int = 10) -> list[dict]:
    return get_continuous_learning().get_top_insights(limit)


def apply_learning_adjustment(task_type: str) -> dict:
    return get_continuous_learning().apply_learned_adjustment(task_type)


def get_continuous_learning_status() -> dict:
    return get_continuous_learning().get_status()
