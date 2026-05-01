"""
Inner Monologue — Internal Voice System
========================================

Sistema de monólogo interno que externaliza o processamento cognitivo do agente:
- Objetivos atuais, tentativas recentes, falhas, planos futuros
- Não verbaliza tudo — apenas o que importa
- Orientado a eventos + timer automático (30s)
- Métricas: frustration, confidence, valence, arousal
- TTS offline via pyttsx3 (SAPI5/ espeak)
- Fila assíncrona para não bloquear loops

Salva todos os pensamentos em JSON estruturado para análise posterior.
"""

from __future__ import annotations

import json
import time
import asyncio
import uuid
import os
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional
from collections import deque
from threading import Thread

DATA_DIR = Path(__file__).resolve().parent.parent.parent / 'data'
MONOLOGUE_PATH = DATA_DIR / 'inner_monologue.json'
METRICS_PATH = DATA_DIR / 'inner_monologue_metrics.json'


@dataclass
class Thought:
    id: str
    ts: int
    content: str
    category: str  # goal_attempt, failure, success, planning, observation, reflection
    metrics: dict = field(default_factory=lambda: {
        'frustration': 0.0,
        'confidence': 0.5,
        'valence': 0.5,
        'arousal': 0.5,
        'priority': 3,
    })
    source: str = 'auto'  # auto, failure, success, manual
    context: dict = field(default_factory=dict)


@dataclass
class MonologueMetrics:
    """Agrega métricas ao longo do tempo."""
    total_thoughts: int = 0
    avg_frustration: float = 0.0
    avg_confidence: float = 0.5
    avg_valence: float = 0.5
    avg_arousal: float = 0.5
    last_updated: int = 0
    streak_success: int = 0
    streak_failure: int = 0


class InnerMonologue:
    """
    Sistema de monólogo interno com TTS.
    
    Usage:
        from ultronpro import inner_monologue
        inner_monologue.think("Analisando conflito persistente", category='observation')
        inner_monologue.start()  # Inicia loop automático
    """
    
    def __init__(self):
        self.think_interval_sec = max(30, int(os.getenv('ULTRON_INNER_MONOLOGUE_INTERVAL_SEC', '90') or 90))
        self.enabled = os.getenv('ULTRON_INNER_VOICE_ENABLED', '1') == '1'
        self.tts_enabled = os.getenv('ULTRON_TTS_ENABLED', '0') == '1'
        self._debug = os.getenv('ULTRON_TTS_DEBUG', '0') == '1'
        self.max_queue = 5
        self.thought_history: deque[Thought] = deque(maxlen=200)
        self._tts_queue: asyncio.Queue[str] = asyncio.Queue()
        self._running = False
        self._tts_engine = None
        self._tts_thread: Optional[Thread] = None
        self._current_goal = ""
        self._last_action_result: str = ""
        self._last_action_status: str = ""
        self._last_spoken_ts: int = 0
        self._speaking_enabled: bool = False  # Desabilitado por padrão (TTS travando Windows)
        
        # Load existing thoughts from disk on startup
        self._load_existing_thoughts()
        
    def _load_existing_thoughts(self):
        """Carrega pensamentos existentes do JSON ao iniciar."""
        try:
            existing = self._load_thoughts()
            if existing:
                for t in existing[-200:]:
                    self.thought_history.append(t)
                if existing:
                    self._last_spoken_ts = existing[-1].ts
                    self._log(f"Loaded {len(existing)} existing thoughts, last ts: {self._last_spoken_ts}")
        except Exception as e:
            self._log(f"Failed to load existing thoughts: {e}")
        
    def _log(self, msg: str):
        if self._debug:
            print(f"[InnerMonologue] {msg}")
        
    def set_speaking(self, enabled: bool):
        """Ativa ou desativa a fala automática."""
        self._speaking_enabled = enabled
        
    # ==================== PERSISTÊNCIA ====================
    
    def _load_thoughts(self) -> list[Thought]:
        """Carrega pensamentos do JSON."""
        if not MONOLOGUE_PATH.exists():
            return []
        try:
            data = json.loads(MONOLOGUE_PATH.read_text(encoding='utf-8'))
            return [Thought(**t) for t in data.get('thoughts', [])]
        except Exception:
            return []
    
    def _save_thoughts(self, thoughts: list[Thought]):
        """Salva pensamentos no JSON."""
        MONOLOGUE_PATH.parent.mkdir(parents=True, exist_ok=True)
        data = {
            'thoughts': [asdict(t) for t in thoughts[-500:]],
            'last_updated': int(time.time()),
        }
        MONOLOGUE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    
    def _load_metrics(self) -> MonologueMetrics:
        """Carrega métricas agregadas."""
        if not METRICS_PATH.exists():
            return MonologueMetrics()
        try:
            data = json.loads(METRICS_PATH.read_text(encoding='utf-8'))
            return MonologueMetrics(**data)
        except Exception:
            return MonologueMetrics()
    
    def _save_metrics(self, m: MonologueMetrics):
        """Salva métricas agregadas."""
        METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)
        METRICS_PATH.write_text(json.dumps(asdict(m), ensure_ascii=False, indent=2), encoding='utf-8')
    
    # ==================== TTS ====================
    
    def _init_tts(self):
        """Inicializa engine TTS (pyttsx3)."""
        if not self.tts_enabled:
            return
        try:
            import pyttsx3
            self._tts_engine = pyttsx3.init()
            self._tts_engine.setProperty('rate', 150)
            self._tts_engine.setProperty('volume', 0.7)
            voices = self._tts_engine.getProperty('voices')
            if voices:
                self._tts_engine.setProperty('voice', voices[0].id)
        except Exception as e:
            print(f"[InnerMonologue] TTS init failed: {e}")
            self._tts_engine = None
    
    def _tts_worker(self):
        """Thread para processar fila de TTS."""
        while self._running:
            try:
                if not self._tts_queue.empty():
                    text = self._tts_queue.get_nowait()
                    if self._tts_engine and text:
                        try:
                            self._tts_engine.say(text)
                            self._tts_engine.runAndWait()
                        except Exception:
                            pass
                time.sleep(0.5)
            except Exception:
                time.sleep(0.5)
    
    def speak(self, text: str):
        """Fala o texto em voz alta (síncrono, bloqueante)."""
        self._log(f"speak() called: {text[:60]}...")
        
        # Always create fresh engine - more reliable than reusing
        try:
            import pyttsx3
            self._log("Creating fresh pyttsx3 engine...")
            engine = pyttsx3.init()
            engine.setProperty('rate', 150)
            engine.setProperty('volume', 0.8)
            voices = engine.getProperty('voices')
            if voices:
                engine.setProperty('voice', voices[0].id)
            self._log("Engine initialized, speaking now...")
            engine.say(text)
            engine.runAndWait()
            self._log("Speak completed successfully")
        except Exception as e:
            self._log(f"Speak failed: {e}")
    
    def speak_summary(self, max_thoughts: int = 5):
        """Lê os últimos pensamentos em voz alta (resumo)."""
        recent = list(self.thought_history)[-max_thoughts:]
        if not recent:
            return
        
        parts = []
        for t in recent:
            content = t.content[:100]
            if t.category == 'failure':
                parts.append(f"Foi detectada falha: {content}")
            elif t.category == 'success':
                parts.append(f"Sucesso: {content}")
            elif t.category == 'observation':
                parts.append(content)
            else:
                parts.append(content)
        
        summary = ". ".join(parts)
        self.speak(summary)
    
    # ==================== THOUGHT GENERATION ====================
    
    def _generate_auto_thought(self) -> str:
        """Gera pensamento automático baseado no estado atual."""
        import random
        
        current_goal = self._current_goal or "manter sistema operacional"
        last_result = self._last_action_result or "nenhuma ação recente"
        status = self._last_action_status
        
        metrics = self._compute_current_metrics()
        
        if status == 'error' or status == 'blocked':
            frustration = min(1.0, metrics.get('frustration', 0) + 0.2)
            templates = [
                f"Falha detectada: {last_result}. Precisamos tentar outra abordagem.",
                f"Resultado negativo: {last_result}. Como posso resolver isso de forma diferente?",
                f"Bloqueio encontrado: {last_result}. Analisando alternativas.",
                f"Problema: {last_result}. Vou reformular a estratégia.",
            ]
            return random.choice(templates)
        
        elif status == 'done':
            templates = [
                f"Sucesso! Ação concluída: {last_result}. Próximo passo: {current_goal}",
                f"Feito: {last_result}. Agora vou focar em {current_goal}",
                f"Concluído: {last_result}. Movendo para a próxima tarefa.",
                f"Resultado positivo: {last_result}. Prosseguindo com {current_goal}",
            ]
            return random.choice(templates)
        
        else:
            # More varied observations
            templates = [
                f"Monitorando operações. Objetivo atual: {current_goal}",
                f"Sistema estável. Continuando com {current_goal}",
                f"Análise contínua. Objetivo: {current_goal}. Processando.",
                f"Verificando estado. Meta: {current_goal}. Tudo em ordem.",
                f"Roundhouse em execução. Foco: {current_goal}",
                f"Processando entradas. Objetivo: {current_goal}",
                f"Ciclo ativo. Mantendo foco em {current_goal}",
            ]
            return random.choice(templates)
    
    def _compute_current_metrics(self) -> dict:
        """Calcula métricas baseadas em pensamento recente."""
        recent = list(self.thought_history)[-10:]
        if not recent:
            return {'frustration': 0.0, 'confidence': 0.5, 'valence': 0.5, 'arousal': 0.5}
        
        avg_frust = sum(t.metrics.get('frustration', 0) for t in recent) / len(recent)
        avg_conf = sum(t.metrics.get('confidence', 0.5) for t in recent) / len(recent)
        avg_val = sum(t.metrics.get('valence', 0.5) for t in recent) / len(recent)
        avg_ar = sum(t.metrics.get('arousal', 0.5) for t in recent) / len(recent)
        
        return {
            'frustration': avg_frust,
            'confidence': avg_conf,
            'valence': avg_val,
            'arousal': avg_ar,
        }
    
    # ==================== MAIN THINK ====================
    
    def think(self, content: str, category: str = 'observation', 
              metrics: dict | None = None, source: str = 'auto', 
              context: dict | None = None, speak: bool = False):
        """
        Registra um pensamento.
        
        Args:
            content: Texto do pensamento
            category: goal_attempt, failure, success, planning, observation, reflection
            metrics: {frustration, confidence, valence, arousal, priority}
            source: auto, failure, success, manual
            context: dados adicionais {action_id, goal_id, etc}
            speak: forçar fala (mesmo sem TTS automático)
        """
        if not self.enabled:
            return
        
        # Compute metrics if not provided
        if metrics is None:
            metrics = self._compute_current_metrics()
        
        thought = Thought(
            id=f"th_{int(time.time())}_{uuid.uuid4().hex[:6]}",
            ts=int(time.time()),
            content=content,
            category=category,
            metrics=metrics,
            source=source,
            context=context or {},
        )
        
        self.thought_history.append(thought)
        self._save_thoughts(list(self.thought_history))
        self._update_aggregated_metrics(thought)
        
        # Speak immediately: always if speak=True, for observation category speak regardless of timestamp (for now)
        # TODO: restore timestamp check later after debugging
        should_speak = speak or (self._speaking_enabled and category in ('failure', 'success', 'reflection', 'observation'))
        self._log(f"think(): category={category}, speak={speak}, enabled={self._speaking_enabled} -> speak={should_speak}")
        if should_speak:
            self._log(f"SPEAKING NOW: {content[:80]}...")
            self.speak(content[:200])
            self._last_spoken_ts = thought.ts
        else:
            self._log(f"NOT SPEAKING: speak={should_speak}, category={category}")
        
        return thought
    
    def _update_aggregated_metrics(self, thought: Thought):
        """Atualiza métricas agregadas."""
        m = self._load_metrics()
        
        m.total_thoughts += 1
        
        # Running average
        n = m.total_thoughts
        m.avg_frustration = ((n - 1) * m.avg_frustration + thought.metrics.get('frustration', 0)) / n
        m.avg_confidence = ((n - 1) * m.avg_confidence + thought.metrics.get('confidence', 0.5)) / n
        m.avg_valence = ((n - 1) * m.avg_valence + thought.metrics.get('valence', 0.5)) / n
        m.avg_arousal = ((n - 1) * m.avg_arousal + thought.metrics.get('arousal', 0.5)) / n
        
        # Streaks
        if thought.category == 'success':
            m.streak_success += 1
            m.streak_failure = 0
        elif thought.category == 'failure':
            m.streak_failure += 1
            m.streak_success = 0
        
        m.last_updated = int(time.time())
        self._save_metrics(m)
    
    # ==================== EVENT TRIGGERS ====================
    
    def on_action_result(self, action_id: str, result: str, status: str, goal: str = ""):
        """Disparado após resultado de uma ação."""
        self._last_action_result = result[:100]
        self._last_action_status = status
        if goal:
            self._current_goal = goal
        
        if status in ('error', 'blocked'):
            metrics = self._compute_current_metrics()
            metrics['frustration'] = min(1.0, metrics.get('frustration', 0) + 0.15)
            metrics['confidence'] = max(0.1, metrics.get('confidence', 0.5) - 0.1)
            metrics['valence'] = max(0.2, metrics.get('valence', 0.5) - 0.1)
            self.think(
                f"Falha na ação: {result}. Preciso tentar outra abordagem.",
                category='failure',
                metrics=metrics,
                source='failure',
                context={'action_id': action_id, 'status': status},
                speak=False  # TTS desabilitado
            )
        elif status == 'done':
            metrics = self._compute_current_metrics()
            metrics['confidence'] = min(1.0, metrics.get('confidence', 0.5) + 0.1)
            metrics['valence'] = min(1.0, metrics.get('valence', 0.5) + 0.1)
            self.think(
                f"Sucesso! Ação concluída: {result}",
                category='success',
                metrics=metrics,
                source='success',
                context={'action_id': action_id, 'status': status},
                speak=False  # TTS desabilitado
            )
    
    def set_current_goal(self, goal: str):
        """Atualiza o objetivo atual."""
        self._current_goal = goal
    
    # ==================== AUTO LOOP ====================
    
    def _auto_tick_sync(self) -> Optional[Thought]:
        self._log("Auto-loop: generating thought...")
        thought_text = self._generate_auto_thought()
        if not thought_text:
            return None
        self._log(f"Auto-loop: calling think() with: {thought_text[:50]}...")
        return self.think(thought_text, category='observation', source='auto')

    async def loop(self):
        """Loop assíncrono que dispara pensamentos automaticamente."""
        if not self.enabled:
            self._log("Loop disabled by config")
            return
            
        self._running = True
        self._init_tts()
        start_delay = max(0.0, float(os.getenv('ULTRON_INNER_MONOLOGUE_LOOP_START_DELAY_SEC', '300') or 300))
        self._log(f"Loop started, interval={self.think_interval_sec}s, start_delay={start_delay}s")
        
        if self.tts_enabled:
            self._tts_thread = Thread(target=self._tts_worker, daemon=True)
            self._tts_thread.start()
        
        if start_delay > 0:
            await asyncio.sleep(start_delay)

        while self._running:
            try:
                await asyncio.sleep(self.think_interval_sec)
                try:
                    from ultronpro import runtime_guard
                    if await runtime_guard.checkpoint("inner_monologue_loop"):
                        continue
                except Exception:
                    pass
                await asyncio.to_thread(self._auto_tick_sync)
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._log(f"Loop error: {e}")
                pass
        
        self._running = False
    
    def stop(self):
        """Para o loop."""
        self._running = False
    
    def get_status(self) -> dict:
        """Retorna status do sistema."""
        m = self._load_metrics()
        recent = list(self.thought_history)[-5:]
        return {
            'enabled': self.enabled,
            'tts_enabled': self.tts_enabled,
            'total_thoughts': m.total_thoughts,
            'metrics': {
                'frustration': round(m.avg_frustration, 2),
                'confidence': round(m.avg_confidence, 2),
                'valence': round(m.avg_valence, 2),
                'arousal': round(m.avg_arousal, 2),
            },
            'streaks': {
                'success': m.streak_success,
                'failure': m.streak_failure,
            },
            'recent_thoughts': [
                {'ts': t.ts, 'content': t.content[:80], 'category': t.category}
                for t in recent
            ],
        }
    
    def get_thoughts(self, limit: int = 50, category: str = None) -> list[dict]:
        """Retorna pensamentos filtrados."""
        thoughts = list(self.thought_history)
        if category:
            thoughts = [t for t in thoughts if t.category == category]
        thoughts = thoughts[-limit:]
        return [asdict(t) for t in thoughts]


# Singleton instance
_inner_monologue: Optional[InnerMonologue] = None


def get_inner_monologue() -> InnerMonologue:
    global _inner_monologue
    if _inner_monologue is None:
        _inner_monologue = InnerMonologue()
    return _inner_monologue


# Convenience functions
def think(content: str, category: str = 'observation', metrics: dict = None, 
          source: str = 'manual', context: dict = None, speak: bool = False):
    return get_inner_monologue().think(content, category, metrics, source, context, speak)

def on_action_result(action_id: str, result: str, status: str, goal: str = ""):
    get_inner_monologue().on_action_result(action_id, result, status, goal)

def set_current_goal(goal: str):
    get_inner_monologue().set_current_goal(goal)

def start():
    return get_inner_monologue()

def stop():
    get_inner_monologue().stop()

def status() -> dict:
    return get_inner_monologue().get_status()

def thoughts(limit: int = 50, category: str = None) -> list[dict]:
    return get_inner_monologue().get_thoughts(limit, category)
