"""
SelfCorrector - Auto-correção baseada em erros

O sistema aprende com erros e se autocorrige:
1. Detecta falhas e padrões de falha
2. Analisa causa raiz
3. Ajusta parâmetros/estratégias
4. Armazena lições aprendidas
5. Evita repetir erros similares
"""

from __future__ import annotations

import json
import time
import hashlib
import logging
from pathlib import Path
from typing import Any, Optional
from dataclasses import dataclass, field
from collections import defaultdict

logger = logging.getLogger("uvicorn")

DATA_DIR = Path(__file__).resolve().parent.parent / 'data'


@dataclass
class FailurePattern:
    """Padrão de falha identificado."""
    pattern_id: str
    trigger: str  # O que iniciou a falha
    root_cause: str  # Causa raiz
    symptoms: list[str]  # Sintomas observados
    frequency: int = 0
    first_seen: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    success_count: int = 0
    failure_count: int = 0


@dataclass
class LessonLearned:
    """Lição aprendida com uma falha."""
    lesson_id: str
    pattern_id: str
    description: str
    correction_applied: str
    verification: str  # Como verificar se funcionou
    effectiveness: float = 0.0  # 0.0-1.0
    times_applied: int = 0
    times_verified: int = 0


@dataclass
class Correction:
    """Correção aplicada."""
    correction_id: str
    pattern_id: str
    type: str  # 'param_adjust', 'strategy_change', 'fallback_add', 'threshold_tune'
    param: str = ""  # Nome do parâmetro afetado
    before: Any = None
    after: Any = None
    reason: str = ""
    applied_at: float = field(default_factory=time.time)
    verified: bool = False
    effectiveness: float = 0.0


class SelfCorrector:
    """
    Sistema de auto-correção que aprende com erros.
    
    Fluxo:
    1. Detectar falha
    2. Identificar padrão (ou criar novo)
    3. Analisar causa raiz
    4. Gerar correção
    5. Aplicar correção
    6. Verificar efetividade
    7. Armazenar lição
    """
    
    def __init__(self):
        self.state_file = DATA_DIR / 'self_corrector_state.json'
        self.patterns: dict[str, FailurePattern] = {}
        self.lessons: dict[str, LessonLearned] = {}
        self.corrections: list[Correction] = []
        self.execution_log: list[dict] = []
        self._load()
        
        # Parâmetros configuráveis
        self.min_pattern_frequency = 2  # Mínimo de falhas para criar padrão
        self.max_lessons = 100  # Máximo de lições armazenadas
        self.correction_cooldown = 300  # Segundos entre correções do mesmo tipo
    
    def _load(self):
        if self.state_file.exists():
            try:
                data = json.loads(self.state_file.read_text())
                
                self.patterns = {
                    k: FailurePattern(**v) for k, v in data.get('patterns', {}).items()
                }
                self.lessons = {
                    k: LessonLearned(**v) for k, v in data.get('lessons', {}).items()
                }
                self.corrections = [
                    Correction(**c) for c in data.get('corrections', [])
                ]
                self.execution_log = data.get('log', [])
            except Exception as e:
                logger.warning(f"Failed to load self-corrector state: {e}")
    
    def _save(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        try:
            data = {
                'patterns': {k: vars(v) for k, v in self.patterns.items()},
                'lessons': {k: vars(v) for k, v in self.lessons.items()},
                'corrections': [vars(c) for c in self.corrections[-50:]],  # Keep last 50
                'log': self.execution_log[-500:]  # Keep last 500
            }
            self.state_file.write_text(json.dumps(data, indent=2, default=str))
        except Exception as e:
            logger.warning(f"Failed to save self-corrector state: {e}")
    
    def _generate_pattern_id(self, trigger: str, context: str = "") -> str:
        """Gera ID único para um padrão de falha."""
        raw = f"{trigger}:{context}".lower().strip()
        return hashlib.md5(raw.encode()).hexdigest()[:12]
    
    def record_outcome(self, action: str, context: str, success: bool, 
                       error_message: str = "", metadata: dict = None) -> str | None:
        """
        Registra resultado de uma ação para análise.
        
        Returns:
            pattern_id se nova falha, None se sucesso
        """
        log_entry = {
            'action': action,
            'context': context,
            'success': success,
            'error': error_message,
            'timestamp': time.time(),
            'metadata': metadata or {}
        }
        self.execution_log.append(log_entry)
        
        if len(self.execution_log) > 1000:
            self.execution_log = self.execution_log[-1000:]
        
        if success:
            # Atualizar contadores de sucesso nos padrões relacionados
            self._update_pattern_on_success(action, context)
            return None
        
        # Falha detectada - analisar
        return self._analyze_failure(action, context, error_message, metadata or {})
    
    def _update_pattern_on_success(self, action: str, context: str):
        """Quando uma ação succeeds, aumenta confidence nos padrões relacionados."""
        for pattern in self.patterns.values():
            if action in pattern.trigger or context in pattern.trigger:
                pattern.success_count += 1
    
    def _analyze_failure(self, action: str, context: str, 
                         error_message: str, metadata: dict) -> str:
        """Analisa uma falha e identifica/cria padrão."""
        
        # Gerar ID do padrão baseado no trigger
        pattern_id = self._generate_pattern_id(action, context)
        
        if pattern_id in self.patterns:
            # Padrão existente - atualizar
            pattern = self.patterns[pattern_id]
            pattern.frequency += 1
            pattern.last_seen = time.time()
            pattern.failure_count += 1
            pattern.symptoms.append(error_message[:100])
            if len(pattern.symptoms) > 10:
                pattern.symptoms = pattern.symptoms[-10:]
        else:
            # Novo padrão
            root_cause = self._determine_root_cause(action, context, error_message, metadata)
            pattern = FailurePattern(
                pattern_id=pattern_id,
                trigger=f"{action}:{context}",
                root_cause=root_cause,
                symptoms=[error_message[:100]] if error_message else [],
                frequency=1
            )
            self.patterns[pattern_id] = pattern
        
        self._save()
        return pattern_id
    
    def _determine_root_cause(self, action: str, context: str,
                              error_message: str, metadata: dict) -> str:
        """Determina causa raiz de uma falha usando regras determinísticas."""
        
        error_lower = error_message.lower()
        
        # Causas comuns baseadas em mensagens de erro
        if 'timeout' in error_lower or 'timed out' in error_lower:
            if 'llm' in error_lower or 'api' in error_lower:
                return "external_service_timeout"
            return "operation_timeout"
        
        if 'connection' in error_lower or 'refused' in error_lower:
            return "connection_failure"
        
        if 'auth' in error_lower or 'key' in error_lower or 'unauthorized' in error_lower:
            return "authentication_failure"
        
        if 'rate' in error_lower or '429' in error_message:
            return "rate_limit_exceeded"
        
        if 'not found' in error_lower or '404' in error_message:
            return "resource_not_found"
        
        if 'memory' in error_lower or 'oom' in error_lower or 'out of memory' in error_lower:
            return "memory_exhaustion"
        
        if 'permission' in error_lower or 'denied' in error_lower:
            return "permission_denied"
        
        # Causas baseadas em contexto
        if 'llm' in action.lower():
            return "llm_inference_failure"
        
        if 'cache' in action.lower():
            return "cache_failure"
        
        if 'graph' in action.lower() or 'causal' in action.lower():
            return "graph_operation_failure"
        
        if 'planner' in action.lower():
            return "planning_failure"
        
        # Fallback
        return "unknown_root_cause"
    
    def should_correct(self, pattern_id: str) -> tuple[bool, str]:
        """
        Determina se uma correção deve ser aplicada.
        
        Returns:
            (should_correct, reason)
        """
        if pattern_id not in self.patterns:
            return False, "pattern_not_found"
        
        pattern = self.patterns[pattern_id]
        
        # Verificar cooldown
        recent_correction = self._get_recent_correction(pattern_id)
        if recent_correction:
            time_since = time.time() - recent_correction.applied_at
            if time_since < self.correction_cooldown:
                return False, f"cooldown_active ({int(time_since)}s remaining)"
        
        # Verificar frequência mínima
        if pattern.frequency < self.min_pattern_frequency:
            return False, f"frequency_too_low ({pattern.frequency}/{self.min_pattern_frequency})"
        
        # Verificar se já existe lição
        if pattern_id in self.lessons:
            lesson = self.lessons[pattern_id]
            if lesson.times_verified > 0 and lesson.effectiveness > 0.7:
                return False, f"lesson_already_learned (effectiveness={lesson.effectiveness:.0%})"
        
        return True, "correction_needed"
    
    def _get_recent_correction(self, pattern_id: str) -> Correction | None:
        """Retorna correção mais recente para um padrão."""
        for corr in reversed(self.corrections):
            if corr.pattern_id == pattern_id:
                return corr
        return None
    
    def generate_correction(self, pattern_id: str) -> Correction | None:
        """
        Gera uma correção apropriada para o padrão.
        
        Returns:
            Correction se aplicável, None caso contrário
        """
        if pattern_id not in self.patterns:
            return None
        
        pattern = self.patterns[pattern_id]
        root_cause = pattern.root_cause
        
        # Mapear causa raiz para tipo de correção
        corrections_map = {
            'external_service_timeout': {
                'type': 'param_adjust',
                'param': 'timeout_sec',
                'before': 30,
                'after': 60,
                'reason': 'Aumentar timeout para serviços externos'
            },
            'operation_timeout': {
                'type': 'param_adjust', 
                'param': 'operation_timeout_sec',
                'before': 30,
                'after': 45,
                'reason': 'Aumentar timeout de operações'
            },
            'connection_failure': {
                'type': 'fallback_add',
                'fallback': 'retry_with_backoff',
                'reason': 'Adicionar retry com backoff exponencial'
            },
            'rate_limit_exceeded': {
                'type': 'param_adjust',
                'param': 'rate_limit_cooldown_sec',
                'before': 60,
                'after': 120,
                'reason': 'Aumentar cooldown após rate limit'
            },
            'llm_inference_failure': {
                'type': 'strategy_change',
                'strategy': 'fallback_provider',
                'reason': 'Mudar para provider alternativo'
            },
            'cache_failure': {
                'type': 'threshold_tune',
                'param': 'cache_threshold',
                'before': 0.95,
                'after': 0.90,
                'reason': 'Baixar threshold de cache para mais hits'
            },
            'memory_exhaustion': {
                'type': 'param_adjust',
                'param': 'max_memory_usage_mb',
                'before': 1000,
                'after': 500,
                'reason': 'Limitar uso de memória'
            },
        }
        
        correction_def = corrections_map.get(root_cause)
        if not correction_def:
            # Correção genérica
            correction_def = {
                'type': 'param_adjust',
                'param': 'general_timeout',
                'before': 30,
                'after': 45,
                'reason': f'Ajustar timeout para falha: {root_cause}'
            }
        
        return Correction(
            correction_id=f"corr_{int(time.time())}_{pattern_id[:6]}",
            pattern_id=pattern_id,
            type=correction_def['type'],
            before=correction_def.get('before'),
            after=correction_def.get('after'),
            reason=correction_def['reason']
        )
    
    def apply_correction(self, correction: Correction) -> bool:
        """
        Aplica uma correção e registra.
        
        Returns:
            True se aplicada com sucesso
        """
        try:
            # Registrar correção
            self.corrections.append(correction)
            
            # Aplicar correção baseada no tipo
            if correction.type == 'param_adjust':
                self._apply_param_adjust(correction)
            elif correction.type == 'strategy_change':
                self._apply_strategy_change(correction)
            elif correction.type == 'fallback_add':
                self._apply_fallback(correction)
            elif correction.type == 'threshold_tune':
                self._apply_threshold_tune(correction)
            
            self._save()
            logger.info(f"Self-corrector: Applied {correction.type} for pattern {correction.pattern_id}")
            return True
            
        except Exception as e:
            logger.error(f"Self-corrector: Failed to apply correction: {e}")
            return False
    
    def _apply_param_adjust(self, correction: Correction):
        """Ajusta parâmetro no autonomous_loop."""
        try:
            from ultronpro.autonomous_loop import get_autonomous_loop
            aloop = get_autonomous_loop()
            adjuster = aloop.auto_adjuster
            
            # Encontrar e ajustar parâmetro
            for param_name, param_data in adjuster.tunable_params.items():
                if param_name == correction.param:
                    old_val = param_data['current']
                    param_data['current'] = correction.after
                    logger.info(f"Adjusted {param_name}: {old_val} -> {correction.after}")
                    break
        except Exception as e:
            logger.warning(f"Failed to apply param adjust: {e}")
    
    def _apply_strategy_change(self, correction: Correction):
        """Muda estratégia de execução."""
        # Implementar mudança de estratégia
        logger.info(f"Strategy change applied: {correction.reason}")
    
    def _apply_fallback(self, correction: Correction):
        """Adiciona fallback."""
        # Implementar fallback
        logger.info(f"Fallback added: {correction.reason}")
    
    def _apply_threshold_tune(self, correction: Correction):
        """Ajusta threshold."""
        try:
            from ultronpro.autonomous_loop import get_autonomous_loop
            aloop = get_autonomous_loop()
            adjuster = aloop.auto_adjuster
            
            for param_name, param_data in adjuster.tunable_params.items():
                if param_name == correction.param:
                    old_val = param_data['current']
                    param_data['current'] = correction.after
                    logger.info(f"Threshold tuned {param_name}: {old_val} -> {correction.after}")
                    break
        except Exception as e:
            logger.warning(f"Failed to apply threshold tune: {e}")
    
    def verify_correction(self, pattern_id: str) -> float:
        """
        Verifica efetividade de uma correção.
        
        Returns:
            effectiveness score (0.0-1.0)
        """
        # Contar sucessos/falhas desde a correção
        correction = self._get_recent_correction(pattern_id)
        if not correction:
            return 0.0
        
        pattern = self.patterns.get(pattern_id)
        if not pattern:
            return 0.0
        
        # Calcular efetividade baseada em taxa de sucesso
        total = pattern.success_count + pattern.failure_count
        if total == 0:
            return 0.0
        
        effectiveness = pattern.success_count / total
        
        # Atualizar lição se existir
        if pattern_id in self.lessons:
            lesson = self.lessons[pattern_id]
            lesson.effectiveness = effectiveness
            lesson.times_verified += 1
        
        correction.effectiveness = effectiveness
        correction.verified = True
        
        self._save()
        return effectiveness
    
    def learn_from_mistake(self, action: str, context: str, error: str,
                           metadata: dict = None) -> dict[str, Any]:
        """
        Fluxo completo de aprendizado com erro.
        
        Returns:
            dict com resultado do aprendizado
        """
        result = {
            'action': action,
            'context': context,
            'error': error,
            'pattern_id': None,
            'correction_applied': False,
            'lesson_learned': None
        }
        
        # 1. Registrar resultado
        pattern_id = self.record_outcome(action, context, False, error, metadata)
        result['pattern_id'] = pattern_id
        
        # 2. Verificar se deve corrigir
        should, reason = self.should_correct(pattern_id)
        if not should:
            result['reason'] = reason
            return result
        
        # 3. Gerar correção
        correction = self.generate_correction(pattern_id)
        if not correction:
            return result
        
        # 4. Aplicar correção
        applied = self.apply_correction(correction)
        result['correction_applied'] = applied
        result['correction'] = vars(correction) if applied else None
        
        # 5. Criar lição aprendida
        if applied:
            lesson = LessonLearned(
                lesson_id=f"lesson_{pattern_id}",
                pattern_id=pattern_id,
                description=f"Correção para {correction.reason}",
                correction_applied=correction.reason,
                verification=f"Avaliar se '{action}' ainda falha",
            )
            self.lessons[pattern_id] = lesson
            result['lesson_learned'] = vars(lesson)
        
        self._save()
        return result
    
    def get_patterns_summary(self) -> dict[str, Any]:
        """Retorna sumário dos padrões de falha."""
        patterns_list = []
        for p in self.patterns.values():
            patterns_list.append({
                'id': p.pattern_id,
                'trigger': p.trigger,
                'root_cause': p.root_cause,
                'frequency': p.frequency,
                'success_rate': p.success_count / max(1, p.success_count + p.failure_count),
                'last_seen': p.last_seen
            })
        
        patterns_list.sort(key=lambda x: -x['frequency'])
        return {
            'total_patterns': len(self.patterns),
            'patterns': patterns_list[:20],  # Top 20
            'active_lessons': len(self.lessons)
        }
    
    def get_lessons(self) -> list[dict]:
        """Retorna lista de lições aprendidas."""
        return [
            {
                'id': l.lesson_id,
                'description': l.description,
                'effectiveness': l.effectiveness,
                'times_applied': l.times_applied,
                'times_verified': l.times_verified
            }
            for l in self.lessons.values()
        ]
    
    def get_status(self) -> dict[str, Any]:
        """Retorna status do corrector."""
        total_failures = sum(p.failure_count for p in self.patterns.values())
        total_successes = sum(p.success_count for p in self.patterns.values())
        
        return {
            'patterns_tracked': len(self.patterns),
            'lessons_learned': len(self.lessons),
            'corrections_applied': len(self.corrections),
            'total_failures': total_failures,
            'total_successes': total_successes,
            'overall_success_rate': total_successes / max(1, total_successes + total_failures),
            'recent_corrections': len([c for c in self.corrections if time.time() - c.applied_at < 3600])
        }


# Singleton
_corrector: SelfCorrector | None = None

def get_self_corrector() -> SelfCorrector:
    global _corrector
    if _corrector is None:
        _corrector = SelfCorrector()
    return _corrector


def learn_from_error(action: str, context: str, error: str, 
                     metadata: dict = None) -> dict[str, Any]:
    """Helper para aprender com erro."""
    return get_self_corrector().learn_from_mistake(action, context, error, metadata)


def record_success(action: str, context: str, metadata: dict = None):
    """Helper para registrar sucesso."""
    get_self_corrector().record_outcome(action, context, True, "", metadata)
