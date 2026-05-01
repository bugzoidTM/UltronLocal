"""
Self-Talk Loop — Internal OODA Proactive Cognition
====================================================

Loop contínuo OODA (Observe–Orient–Decide–Act) que roda como processo
de primeiro nível, sem depender de triggers externos.

O Internal Critic deixa de ser passivo (chamado só sob demanda) e
vira um *Prompter Contínuo*: um modelo leve julga em cada tick do loop
o estado cognitivo atual — tédio, curiosidade, prontidão, anomalia,
oportunidade — e enfileira pensamentos, perguntas e micro-ações
proativas que alimentam o restante do ecossistema.

Pilares:
  1. OBSERVE  — Lê workspace, métricas, monologue recente, curiosidade
  2. ORIENT   — Classifica situação cognitiva (boredom / curiosity /
                readiness / anomaly / opportunity)
  3. DECIDE   — Escolhe ação interna (think / question / investigate /
                consolidate / idle)
  4. ACT      — Executa a ação (publica pensamento, enfileira pergunta,
                dispara micro-investigação, etc)

Saídas publicadas:
  - inner_monologue.think()                → pensamento estruturado
  - store.publish_workspace()              → workspace global
  - curiosity.refresh_questions()          → perguntas proativas
  - mental_simulation.imagine()            → simulação preventiva
  - store.db.add_event()                   → log de auditoria

Cadência padrão: 45s (configurável via ULTRON_SELF_TALK_INTERVAL_SEC)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import random
from typing import Any, Optional

logger = logging.getLogger("uvicorn")

# ─── Configuração ─────────────────────────────────────────────
SELF_TALK_INTERVAL_SEC = max(20, int(os.getenv('ULTRON_SELF_TALK_INTERVAL_SEC', '45')))
SELF_TALK_ENABLED = os.getenv('ULTRON_SELF_TALK_ENABLED', '1') == '1'

# Thresholds para classificação de situação cognitiva
BOREDOM_THRESHOLD = 0.25        # abaixo disso → tédio
CURIOSITY_THRESHOLD = 0.55      # acima disso → curiosidade
ANOMALY_THRESHOLD = 0.70        # surpresa acima disso → anomalia
OPPORTUNITY_GAP_MIN = 3         # mínimo de gaps para disparar oportunidade


# ─── Classificação de Estado Cognitivo ────────────────────────

class CognitivePosture:
    BOREDOM = 'boredom'
    CURIOSITY = 'curiosity'
    READINESS = 'readiness'
    ANOMALY = 'anomaly'
    OPPORTUNITY = 'opportunity'
    IDLE = 'idle'


def _classify_cognitive_state(signals: dict[str, Any]) -> tuple[str, str]:
    """
    Classifica o estado cognitivo atual com base nos sinais.
    Retorna (posture, rationale).
    """
    arousal = float(signals.get('arousal', 0.5))
    frustration = float(signals.get('frustration', 0.0))
    valence = float(signals.get('valence', 0.5))
    surprise = float(signals.get('surprise', 0.0))
    knowledge_gaps = int(signals.get('knowledge_gaps', 0))
    workspace_alerts = int(signals.get('workspace_alerts', 0))
    recent_failures = int(signals.get('recent_failures', 0))
    recent_successes = int(signals.get('recent_successes', 0))
    idle_seconds = int(signals.get('idle_seconds', 0))

    # Anomalia: surpresa alta ou muitos alertas
    if surprise > ANOMALY_THRESHOLD or workspace_alerts >= 3:
        return CognitivePosture.ANOMALY, f"Surpresa alta ({surprise:.2f}) ou alertas no workspace ({workspace_alerts})"

    # Oportunidade: muitos gaps de conhecimento + arousal razoável
    if knowledge_gaps >= OPPORTUNITY_GAP_MIN and arousal > 0.3:
        return CognitivePosture.OPPORTUNITY, f"{knowledge_gaps} lacunas de conhecimento detectadas"

    # Curiosidade: arousal alto + valência positiva
    if arousal > CURIOSITY_THRESHOLD and valence > 0.4:
        return CognitivePosture.CURIOSITY, f"Arousal elevado ({arousal:.2f}) com valência positiva"

    # Tédio: arousal baixo + sem atividade recente
    if arousal < BOREDOM_THRESHOLD and idle_seconds > 60:
        return CognitivePosture.BOREDOM, f"Arousal baixo ({arousal:.2f}), {idle_seconds}s sem atividade"

    # Readiness: sistema em bom estado, pronto para agir
    if frustration < 0.3 and valence > 0.5 and recent_successes > recent_failures:
        return CognitivePosture.READINESS, "Sistema estável com balanço positivo"

    return CognitivePosture.IDLE, "Estado nominal, sem gatilhos especiais"


# ─── Ações Internas ───────────────────────────────────────────

def _act_boredom(signals: dict, rationale: str) -> dict:
    """Tédio → gerar curiosidade, perguntas exploratórias."""
    from ultronpro import inner_monologue, curiosity, store

    thoughts = [
        "Estou sem estímulo externo. Vou explorar lacunas que detectei no meu conhecimento.",
        "Período de inatividade. Bom momento para investigar conceitos que apareceram e nunca aprofundei.",
        "Tédio produtivo: vou gerar perguntas exploratórias sobre temas que não domino.",
        "Sem input. Posso usar isso para consolidar memórias e descobrir padrões nos erros recentes.",
    ]
    thought_text = random.choice(thoughts)
    inner_monologue.think(thought_text, category='reflection', source='self_talk',
                          context={'posture': 'boredom', 'rationale': rationale})

    # Gerar perguntas proativas
    generated = 0
    try:
        generated = curiosity.refresh_questions(target_count=2)
    except Exception:
        pass

    store.db.add_event('self_talk', f"🧠 Boredom → exploração: {generated} perguntas geradas")
    return {'action': 'explore', 'questions_generated': generated, 'thought': thought_text}


def _act_curiosity(signals: dict, rationale: str) -> dict:
    """Curiosidade → investigar o tópico de maior saliência."""
    from ultronpro import inner_monologue, store, working_memory

    # Pegar item de maior saliência do workspace
    ws_items = store.read_workspace(limit=5)
    top_item = None
    for item in ws_items:
        if float(item.get('salience', 0)) > 0.5:
            top_item = item
            break

    if top_item:
        payload = top_item.get('payload_json', '{}')
        try:
            payload_data = json.loads(payload) if isinstance(payload, str) else payload
        except Exception:
            payload_data = {}
        topic = str(payload_data.get('topic', payload_data.get('goal', payload_data.get('type', 'item desconhecido'))))[:120]
        thought_text = f"Curiosidade ativada: encontrei '{topic}' com saliência {top_item.get('salience', '?')} no workspace. Vou investigar mais."
    else:
        thought_text = "Curiosidade elevada, mas sem item saliente no workspace. Vou revisar memórias recentes para encontrar threads soltos."
        topic = 'memórias_recentes'

    inner_monologue.think(thought_text, category='observation', source='self_talk',
                          context={'posture': 'curiosity', 'topic': topic, 'rationale': rationale})

    # Tentar simulação mental do tópico
    sim_result = {}
    try:
        from ultronpro import mental_simulation
        sim_result = mental_simulation.imagine('investigate', topic, {'source': 'self_talk_curiosity'})
    except Exception:
        pass

    store.db.add_event('self_talk', f"🔍 Curiosity → investigação: {topic[:80]}")
    return {'action': 'investigate', 'topic': topic, 'simulation': sim_result, 'thought': thought_text}


def _act_anomaly(signals: dict, rationale: str) -> dict:
    """Anomalia → alerta + simulação mental preventiva."""
    from ultronpro import inner_monologue, store, mental_simulation

    thought_text = f"⚠️ Anomalia detectada: {rationale}. Executando simulação mental preventiva."
    inner_monologue.think(thought_text, category='reflection', source='self_talk',
                          context={'posture': 'anomaly', 'rationale': rationale},
                          metrics={'frustration': 0.0, 'confidence': 0.3,
                                   'valence': 0.3, 'arousal': 0.8, 'priority': 5})

    # Simular impacto
    sim_result = {}
    try:
        sim_result = mental_simulation.imagine('anomaly_response', rationale,
                                                {'source': 'self_talk_anomaly',
                                                 'signals': {k: v for k, v in signals.items()
                                                             if isinstance(v, (int, float, str, bool))}})
    except Exception:
        pass

    # Publicar alerta de alta saliência no workspace
    try:
        store.publish_workspace(
            module='self_talk_loop',
            channel='self_talk.anomaly',
            payload_json=json.dumps({
                'type': 'anomaly_detected',
                'rationale': rationale,
                'simulation_posture': sim_result.get('posture', 'unknown'),
            }),
            salience=0.85,
            ttl_sec=600
        )
    except Exception:
        pass

    store.db.add_event('self_talk', f"🚨 Anomaly → simulação preventiva: posture={sim_result.get('posture', '?')}")
    return {'action': 'alert_and_simulate', 'simulation': sim_result, 'thought': thought_text}


def _act_opportunity(signals: dict, rationale: str) -> dict:
    """Oportunidade → enfileirar perguntas direcionadas + monólogo."""
    from ultronpro import inner_monologue, curiosity, store

    gaps = int(signals.get('knowledge_gaps', 0))
    thought_text = f"Oportunidade: {gaps} lacunas de conhecimento podem ser fechadas agora. Gerando investigação focada."
    inner_monologue.think(thought_text, category='planning', source='self_talk',
                          context={'posture': 'opportunity', 'gaps': gaps, 'rationale': rationale})

    generated = 0
    try:
        generated = curiosity.refresh_questions(target_count=min(3, gaps))
    except Exception:
        pass

    store.db.add_event('self_talk', f"💡 Opportunity → {generated} perguntas sobre lacunas")
    return {'action': 'exploit_gaps', 'questions_generated': generated, 'gaps': gaps, 'thought': thought_text}


def _act_readiness(signals: dict, rationale: str) -> dict:
    """Prontidão → consolidar aprendizado, micro-reflexão."""
    from ultronpro import inner_monologue, store

    thoughts = [
        "Sistema em equilíbrio. Bom momento para consolidar o que aprendi nos últimos ciclos.",
        "Prontidão: desempenho estável. Vou revisar se há micro-otimizações pendentes.",
        "Equilíbrio operacional atingido. Posso refletir sobre padrões dos últimos sucessos.",
    ]
    thought_text = random.choice(thoughts)
    inner_monologue.think(thought_text, category='reflection', source='self_talk',
                          context={'posture': 'readiness', 'rationale': rationale})

    store.db.add_event('self_talk', f"✅ Readiness → consolidação")
    return {'action': 'consolidate', 'thought': thought_text}


def _act_idle(signals: dict, rationale: str) -> dict:
    """Idle → sem ação especial, apenas registro leve."""
    return {'action': 'idle', 'thought': 'Estado nominal, nenhuma ação necessária.'}


# Action dispatch
_ACTION_MAP = {
    CognitivePosture.BOREDOM: _act_boredom,
    CognitivePosture.CURIOSITY: _act_curiosity,
    CognitivePosture.ANOMALY: _act_anomaly,
    CognitivePosture.OPPORTUNITY: _act_opportunity,
    CognitivePosture.READINESS: _act_readiness,
    CognitivePosture.IDLE: _act_idle,
}


# ─── OODA Engine ──────────────────────────────────────────────

class SelfTalkLoop:
    """
    Motor OODA interno de primeiro nível.
    Observe → Orient → Decide → Act em cadência contínua.
    """

    def __init__(self):
        self.enabled = SELF_TALK_ENABLED
        self.interval_sec = SELF_TALK_INTERVAL_SEC
        self._task: Optional[asyncio.Task] = None
        self.tick_count = 0
        self.posture_history: list[dict] = []  # últimas 50 posturas
        self.last_tick_result: dict = {}
        self._last_tick_ts: int = 0

    def start(self):
        """Inicia o loop como background task."""
        if not self.enabled:
            logger.info("[SELF-TALK] Disabled by env (ULTRON_SELF_TALK_ENABLED=0)")
            return
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run_forever())
            logger.info(f"[SELF-TALK] OODA loop started (interval={self.interval_sec}s)")

    async def _run_forever(self):
        """Loop principal."""
        await asyncio.sleep(float(os.getenv('ULTRON_SELF_TALK_LOOP_START_DELAY_SEC', '120')))  # Warmup
        while self.enabled:
            try:
                from ultronpro import runtime_guard
                if await runtime_guard.checkpoint("self_talk_loop"):
                    continue
            except Exception:
                pass
            try:
                result = await asyncio.to_thread(self._tick_sync)
                self.last_tick_result = result
            except Exception as e:
                logger.warning(f"[SELF-TALK] Tick error: {e}")
                self.last_tick_result = {'error': str(e)}
            await asyncio.sleep(self.interval_sec)

    def _tick_sync(self) -> dict:
        """Um ciclo OODA completo de forma síncrona."""
        self.tick_count += 1
        self._last_tick_ts = int(time.time())

        # ── OBSERVE ──
        signals = self._observe()

        # ── ORIENT ──
        posture, rationale = _classify_cognitive_state(signals)

        # ── DECIDE + ACT ──
        action_fn = _ACTION_MAP.get(posture, _act_idle)
        try:
            act_result = action_fn(signals, rationale)
        except Exception as e:
            logger.warning(f"[SELF-TALK] Action '{posture}' failed: {e}")
            act_result = {'action': 'error', 'error': str(e)}

        # ── RECORD ──
        entry = {
            'tick': self.tick_count,
            'ts': self._last_tick_ts,
            'posture': posture,
            'rationale': rationale,
            'action': act_result.get('action', 'unknown'),
        }
        self.posture_history.append(entry)
        if len(self.posture_history) > 50:
            self.posture_history = self.posture_history[-50:]

        # Publicar no workspace
        try:
            from ultronpro import store
            store.publish_workspace(
                module='self_talk_loop',
                channel='self_talk.tick',
                payload_json=json.dumps(entry),
                salience=0.4 if posture in ('idle', 'readiness') else 0.65,
                ttl_sec=300
            )
        except Exception:
            pass

        logger.info(f"[SELF-TALK] Tick #{self.tick_count}: posture={posture}, action={act_result.get('action')}")
        return {
            'tick': self.tick_count,
            'posture': posture,
            'rationale': rationale,
            'signals': {k: v for k, v in signals.items() if isinstance(v, (int, float, str, bool))},
            'result': act_result,
        }

    def _observe(self) -> dict[str, Any]:
        """
        Fase OBSERVE: coleta sinais de todos os módulos relevantes.
        Leve, sem chamadas LLM.
        """
        signals: dict[str, Any] = {
            'arousal': 0.5,
            'frustration': 0.0,
            'valence': 0.5,
            'surprise': 0.0,
            'knowledge_gaps': 0,
            'workspace_alerts': 0,
            'recent_failures': 0,
            'recent_successes': 0,
            'idle_seconds': 0,
        }

        # 1. Inner monologue metrics
        try:
            from ultronpro import inner_monologue
            mono_status = inner_monologue.status()
            metrics = mono_status.get('metrics', {})
            signals['arousal'] = float(metrics.get('arousal', 0.5))
            signals['frustration'] = float(metrics.get('frustration', 0.0))
            signals['valence'] = float(metrics.get('valence', 0.5))
            streaks = mono_status.get('streaks', {})
            signals['recent_failures'] = int(streaks.get('failure', 0))
            signals['recent_successes'] = int(streaks.get('success', 0))
        except Exception:
            pass

        # 2. Mental simulation surprise
        try:
            from ultronpro import mental_simulation
            ms_status = mental_simulation.status()
            signals['surprise'] = float(ms_status.get('avg_surprise_score', 0.0))
        except Exception:
            pass

        # 3. Curiosity gaps
        try:
            from ultronpro import curiosity
            stats = curiosity.get_stats()
            gaps = stats.get('top_gaps', [])
            signals['knowledge_gaps'] = len(gaps)
        except Exception:
            pass

        # 4. Workspace alerts
        try:
            from ultronpro import store
            ws = store.read_workspace(limit=20)
            alerts = [it for it in ws if it.get('channel') in ('integrity.alert', 'causal.assessment')
                      and float(it.get('salience', 0)) > 0.6]
            signals['workspace_alerts'] = len(alerts)
        except Exception:
            pass

        # 5. Idle time (approx)
        try:
            from ultronpro import store
            actions = store.db.list_actions(limit=1)
            if actions:
                last_ts = int(actions[0].get('created_at', 0) or 0)
                if last_ts > 0:
                    signals['idle_seconds'] = max(0, int(time.time()) - last_ts)
        except Exception:
            pass

        return signals

    def stop(self):
        """Para o loop."""
        self.enabled = False
        if self._task and not self._task.done():
            self._task.cancel()
        logger.info("[SELF-TALK] Loop stopped")

    def get_status(self) -> dict:
        """Status para API."""
        # Calcular distribuição de posturas
        posture_counts: dict[str, int] = {}
        for entry in self.posture_history:
            p = entry.get('posture', 'unknown')
            posture_counts[p] = posture_counts.get(p, 0) + 1

        return {
            'enabled': self.enabled,
            'running': self._task is not None and not self._task.done(),
            'tick_count': self.tick_count,
            'interval_sec': self.interval_sec,
            'last_tick_ts': self._last_tick_ts,
            'last_posture': self.posture_history[-1] if self.posture_history else None,
            'posture_distribution': posture_counts,
            'recent_postures': self.posture_history[-10:],
            'last_result': self.last_tick_result,
        }


# ─── Singleton ────────────────────────────────────────────────

_instance: Optional[SelfTalkLoop] = None


def get_self_talk_loop() -> SelfTalkLoop:
    global _instance
    if _instance is None:
        _instance = SelfTalkLoop()
    return _instance


# ─── Public API ───────────────────────────────────────────────

def start():
    """Inicia o Self-Talk loop."""
    get_self_talk_loop().start()


def stop():
    """Para o Self-Talk loop."""
    get_self_talk_loop().stop()


def status() -> dict:
    """Status do Self-Talk loop."""
    return get_self_talk_loop().get_status()
