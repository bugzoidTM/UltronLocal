import asyncio
import json
import logging
import os
import time
from typing import Any, Optional

from ultronpro import (
    self_model, 
    world_model, 
    store, 
    uncertainty, 
    self_improvement_engine, 
    cognitive_patch_loop,
    intrinsic_utility,
    executive_instrumentation,
    self_modification,
    rl_policy,
    roadmap_auditor
)

logger = logging.getLogger("uvicorn")

class MetacognitiveLoop:
    """
    Loop Metacognitivo Unificado do UltronPro.
    
    Este loop coordena os seis pilares da consciência operacional:
    1. Self-Model: Percepção de capacidades e estados internos.
    2. World Model: Modelagem do ambiente e predição de outcomes.
    3. Memória Autobiográfica: Recuperação histórica de sucessos e falhas.
    4. Incerteza Calibrada: Avaliação bayesiana da confiabilidade das crenças.
    5. Reward Grounded: Alinhamento com utilidade intrínseca e sinais ambientais.
    6. Auto-intervenção: Modificação ativa do próprio código/parâmetros.
    """
    def __init__(self):
        self.enabled = True
        self.interval_sec = 300  # Ciclo de reflexão principal a cada 5 min
        self._task: Optional[asyncio.Task] = None
        self.last_reflection: dict[str, Any] = {}
        self.tick_count = 0

    def start(self):
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run_forever())
            logger.info("[META] Unidade de Reflexão Metacognitiva Unificada iniciada.")

    async def _run_forever(self):
        await asyncio.sleep(float(os.getenv('ULTRON_METACOGNITIVE_LOOP_START_DELAY_SEC', '210'))) # Aguarda warmup do ecossistema
        while self.enabled:
            try:
                from ultronpro import runtime_guard
                if await runtime_guard.checkpoint("metacognitive_loop"):
                    continue
            except Exception:
                pass
            try:
                await asyncio.to_thread(self.tick_sync)
            except Exception as e:
                logger.error(f"[META] Erro crítico no ciclo de reflexão: {e}", exc_info=True)
            await asyncio.sleep(self.interval_sec)

    def tick_sync(self):
        """Executa um ciclo completo de consciência, julgamento e auto-ajuste de forma síncrona."""
        logger.info("--- [META] INICIANDO CICLO DE CONSCIÊNCIA UNIFICADA ---")
        
        # 1. PERCEPÇÃO INTEGRADA (Self & World)
        self_report = self_model.generate_operational_consciousness_report()
        world_state = world_model.get_world_state()
        utility_status = intrinsic_utility.status()
        
        # 2. RECORDAÇÃO E ESPAÇO DE TRABALHO GLOBAL
        # Buscamos o que está no foco da atenção global agora
        workspace_items = store.read_workspace(limit=15)
        recent_memories = store.list_autobiographical_memories(limit=5, min_importance=0.6)
        
        # Filtramos sinais de interesse no workspace
        causal_alerts = [it for it in workspace_items if it.get('channel') == 'causal.assessment' and float(it.get('salience') or 0) > 0.6]
        integrity_alerts = [it for it in workspace_items if it.get('channel') == 'integrity.alert']
        world_sims = [it for it in workspace_items if it.get('channel') == 'world.simulation']
        
        # Marcar itens consumidos para rastreabilidade de autoria/atenção
        for it in workspace_items:
            try:
                store.mark_workspace_consumed(it['id'], 'metacognition')
            except Exception:
                pass
        
        # 3. CALIBRAÇÃO DE INCERTEZA (Epistemic Evaluation)
        # Extraímos métricas de surpresa e confiança do self-model
        stats = self_model.load()
        pred_data = stats.get('predictive', {})
        avg_surprise = float(pred_data.get('avg_surprise', 0.0))
        
        # Calibramos a confiança geral baseada na robustez dos dados
        causal = self_model.causal_summary(limit=1)
        tasks = causal.get('task_outcomes', [])
        general_stats = tasks[0] if tasks else {'success': 0, 'count': 0}
        
        calibration = uncertainty.estimate_uncertainty(
            int(general_stats.get('success', 0)), 
            int(general_stats.get('count', 0))
        )
        reliability = calibration['calibrated_score']
        
        # 4. GROUNDING DE RECOMPENSA (Value Realignment)
        # Verificamos se a utilidade intrínseca está em queda (deriva de objetivo)
        current_utility = float(utility_status.get('utility', 0.5))
        utility_history = utility_status.get('utility_history', [])
        utility_trend = 0.0
        if len(utility_history) >= 2:
            utility_trend = current_utility - float(utility_history[-2].get('utility', current_utility))

        # 5. DIAGNÓSTICO METACOGNITIVO (Análise de Discrepância)
        needs_intervention = False
        triggers = []
        
        # Trigger A: Surpresa Preditiva Alta (World Model falhou em prever o ambiente)
        if avg_surprise > 0.35:
            needs_intervention = True
            triggers.append(f"Alta surpresa preditiva ({avg_surprise:.2f})")
            
        # Trigger B: Baixa Confiabilidade Calibrada (Self-Model detecta incapacidade estatística)
        if reliability < 0.4 and general_stats.get('count', 0) > 5:
            needs_intervention = True
            triggers.append(f"Incerteza crítica detectada (Reliability: {reliability:.2f})")
            
        # Trigger C: Queda na Utilidade Grounded (O sistema não está atingindo seus drives intrínsecos)
        if utility_trend < -0.1 or current_utility < 0.4:
            needs_intervention = True
            triggers.append(f"Degradação de utilidade intrínseca (Trend: {utility_trend:.2f})")
            
        # Trigger D: Conflitos ou Alertas de Integridade no Workspace
        if integrity_alerts or len(causal_alerts) > 2:
            needs_intervention = True
            triggers.append(f"Alertas de integridade/causalidade no workspace ({len(integrity_alerts) + len(causal_alerts)} itens)")

        # 6. AUTO-INTERVENÇÃO (Self-Modification & Improvement)
        intervention_results = {}
        if needs_intervention:
            reason = " | ".join(triggers)
            logger.warning(f"[META] DISPARANDO AUTO-INTERVENÇÃO: {reason}")
            
            # A. Identificar limitações concretas
            limitations = self_improvement_engine.identify_limitations()
            
            # B. Se a falha for persistente em patches, tentar auto-modificação simbólica
            if avg_surprise > 0.5:
                # Tentativa de sanar gap via patches cognitivos
                patch_res = cognitive_patch_loop.scan_and_autorun(scan_limit=20, process_limit=1)
                intervention_results['patch_scan'] = patch_res
            
            # C. Atualizar política de RL para evitar trajetórias de baixa utilidade
            rl_policy.update('metacognitive_adjustment', 'system', 0.0 if utility_trend < 0 else 1.0)
            
            # D. Registrar na memória autobiográfica de longo prazo (episódico)
            store.add_autobiographical_memory(
                text=f"Auto-intervenção metacognitiva devido a: {reason}",
                memory_type='episodic',
                importance=0.9,
                content_json=json.dumps({
                    'triggers': triggers,
                    'metrics': {
                        'surprise': avg_surprise,
                        'reliability': reliability,
                        'utility': current_utility,
                        'utility_trend': utility_trend
                    },
                    'limitations_found': len(limitations)
                })
            )
            intervention_results['limitations_count'] = len(limitations)
        else:
            logger.info("[META] Estado nominal mantido. Equilíbrio entre drives e realidade.")

        # 7. CONSOLIDAÇÃO E SNAPSHOT
        self.last_reflection = {
            'ts': int(time.time()),
            'status': 'INTERVENTION' if needs_intervention else 'NOMINAL',
            'triggers': triggers,
            'metrics': {
                'self_quality': self_report.get('state_summary', {}).get('avg_quality_composite', 0.0),
                'world_entities': world_state.get('entity_count', 0),
                'perceived_reliability': reliability,
                'grounded_utility': current_utility,
                'surprise_factor': avg_surprise
            },
            'intervention': intervention_results,
            'workspace_signals': {
                'causal_alerts': len(causal_alerts),
                'integrity_alerts': len(integrity_alerts),
                'world_sims': len(world_sims)
            }
        }
        
        # 8. PUBLICAR NO WORKSPACE GLOBAL
        try:
            store.publish_workspace(
                module='metacognition',
                channel='metacog.snapshot',
                payload_json=json.dumps(self.last_reflection),
                salience=0.75 if needs_intervention else 0.4,
                ttl_sec=1200
            )
        except Exception:
            pass
        
        # 9. MECANISMO DE ATENÇÃO (CLEANUP)
        try:
            cleaned = store.cleanup_workspace(max_items=120)
            if cleaned > 0:
                logger.info(f"[META] Atenção seletiva: {cleaned} itens removidos do workspace por baixa saliência/expiração.")
        except Exception:
            pass

        # 10. SELF-ROADMAP AUDIT (Fase 6.2)
        self.tick_count += 1
        if self.tick_count % 10 == 0:
            try:
                audit = roadmap_auditor.audit_roadmap()
                logger.info(f"[META] Roadmap Audit: {audit.get('avg_progress', 0)*100:.1f}% completo.")
            except Exception:
                pass
        
        # 11. EXECUTIVE INSTRUMENTATION (Fase 6.1)
        try:
            exec_metrics = executive_instrumentation.get_executive_summary()
            logger.info(f"[META] Executive Alinhamento: {exec_metrics.get('alignment_score', 0)*100:.1f}%")
        except Exception:
            pass
            
        logger.info(f"[META] Ciclo finalizado. Status: {self.last_reflection['status']}")

    def get_status(self) -> dict:
        return {
            "active": self._task is not None and not self._task.done(),
            "last_reflection": self.last_reflection,
            "config": {
                "interval_sec": self.interval_sec,
                "enabled": self.enabled
            }
        }

# Singleton
_instance = MetacognitiveLoop()

def get_metacognitive_loop() -> MetacognitiveLoop:
    return _instance

def start_metacognitive_loop():
    _instance.start()
