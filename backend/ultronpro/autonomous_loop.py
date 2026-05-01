import asyncio
import json
import time
import os
import logging
from typing import Any, Optional
from pathlib import Path

from ultronpro import store, planner, autonomous_executor, reflector, self_model
from ultronpro.subconscious_veto import evaluate_narrative_veto

logger = logging.getLogger("uvicorn")

class AutonomousGoalLoop:
    """
    Motor de Proatividade do UltronPro.
    Implementa o ciclo P.E.O.R.U (Plan, Execute, Observe, Reflect, Update).
    Roda em background e persegue objetivos persistidos no SQLite.
    """
    def __init__(self):
        self.enabled = os.getenv('ULTRON_AUTONOMOUS_LOOP', '1') == '1'
        self.interval_sec = 60 # Ciclo a cada 1 minuto
        self._task: Optional[asyncio.Task] = None
        self.metrics = {
            'goals_pursued': 0,
            'successes': 0,
            'failures': 0,
            'avg_reward': 0.0
        }

    def start(self):
        if not self.enabled:
            logger.info("AutonomousGoalLoop: Disabled by environment.")
            return
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run_forever())
            logger.info("AutonomousGoalLoop: Service started in background.")

    async def _run_forever(self):
        # Aguarda o sistema estabilizar
        await asyncio.sleep(10)
        while self.enabled:
            try:
                await self.tick()
            except Exception as e:
                logger.error(f"AutonomousGoalLoop: Error in tick: {e}")
            await asyncio.sleep(self.interval_sec)

    async def tick(self):
        """Um passo do ciclo P.E.O.R.U para metas ativas."""
        active_goals = store.get_active_goals(limit=3)
        if not active_goals:
            return

        for goal in active_goals:
            goal_id = goal['id']

            # Publish intention to workspace
            try:
                store.publish_workspace(
                    module='autonomous_loop',
                    channel='goal.pursuit',
                    payload_json=json.dumps({
                        'goal_id': goal_id,
                        'title': goal['title'],
                        'attempt': goal['attempts_count'] + 1
                    }),
                    salience=0.5,
                    ttl_sec=300
                )
            except Exception:
                pass

            # Verifica se já excedeu o limite
            if goal['attempts_count'] >= goal['max_attempts']:
                store.update_goal_status(goal_id, 'failed', meta_json=json.dumps({"reason": "max_attempts_exceeded"}))
                continue

            logger.info(f"[PEORU] Pursuing: {goal['title']} (Attempt {goal['attempts_count']+1})")
            
            # --- VETO SUBCONSCIENTE (Fase 5.3 / 5.8) ---
            try:
                veto_decision = evaluate_narrative_veto(goal['title'], goal.get('description', ''))
                if veto_decision.get('vetoed'):
                    logger.warning(f"[SUBCONSCIOUS VETO] Goal '{goal['title']}' foi vetada. Razão: {veto_decision.get('reason')}")
                    store.add_goal_attempt(
                        goal_id,
                        plan_json="{}",
                        success=False,
                        error_text=f"VETADO_PELO_SUBCONSCIENTE: {veto_decision.get('reason')}",
                        reward=-1.0,
                        duration_ms=0,
                        result_json=json.dumps({'veto_reason': veto_decision.get('reason')})
                    )
                    store.update_goal_status(goal_id, 'failed', meta_json=json.dumps({"reason": "vetoed"}))
                    # Registro explícito desse ato autônomo na memória de longo prazo
                    store.add_memory(
                        key=f"veto_episodic_{goal_id}",
                        value={"action": "vetoed_external_goal", "goal": goal['title'], "reason": veto_decision.get('reason')},
                        domain="self_model", layer="episodic"
                    )

                    # Publish veto to workspace with high salience
                    try:
                        store.publish_workspace(
                            module='autonomous_loop',
                            channel='integrity.alert',
                            payload_json=json.dumps({
                                'type': 'subconscious_veto',
                                'goal': goal['title'],
                                'reason': veto_decision.get('reason')
                            }),
                            salience=0.85,
                            ttl_sec=600
                        )
                    except Exception:
                        pass

                    continue
            except Exception as e:
                logger.error(f"[SUBCONSCIOUS] Falha ao avaliar veto narrativo: {e}")

            # 1. PLAN
            plan = None
            try:
                # O planejador olha o objetivo e o histórico de falhas
                plan = planner.propose_goal_plan(goal, store)
            except Exception as e:
                logger.warning(f"Planning failed for goal {goal_id}: {e}")
                continue

            # 2. EXECUTE
            start_ts = time.time()
            success = False
            error = None
            result = None
            try:
                result = await autonomous_executor.run_plan(plan, goal_id=goal_id)
                success = result.get('success', False)
                error = result.get('error')
            except Exception as e:
                success = False
                error = str(e)
            
            duration_ms = int((time.time() - start_ts) * 1000)

            # 3. OBSERVE
            reward = 1.0 if success else -0.5
            if success:
                self.metrics['successes'] += 1
            else:
                self.metrics['failures'] += 1
                
            # 4. REFLECT
            reflection = None
            if not success:
                history = store.get_goal_history(goal_id, limit=5)
                # O refletor analisa o erro e sugere correções para a próxima tentativa
                reflection = reflector.reflect_on_failure(goal, {'error_text': error, 'plan_json': json.dumps(plan)}, history)
                logger.info(f"Reflected on failure: {reflection.get('diagnosis')}")

            # 5. UPDATE
            store.add_goal_attempt(
                goal_id,
                plan_json=json.dumps(plan),
                success=success,
                error_text=error,
                reward=reward,
                duration_ms=duration_ms,
                result_json=json.dumps({'result': result, 'reflection': reflection})
            )

            # Record in self_model for calibrated uncertainty
            self_model.record_action_outcome(
                strategy='autonomous_goal_pursuit',
                task_type=goal.get('title', 'unknown')[:80],
                budget_profile='background',
                ok=success,
                latency_ms=duration_ms,
                notes=f"Refl: {reflection.get('suggestion') if reflection else 'SUCCESS'}"
            )

            if success:
                store.update_goal_status(goal_id, 'done', meta_json=json.dumps(result))
                logger.info(f"Goal {goal_id} COMPLETED: {goal['title']}")
            elif goal['attempts_count'] + 1 >= goal['max_attempts']:
                store.update_goal_status(goal_id, 'failed', meta_json=json.dumps({'error': error, 'reflection': reflection}))
                logger.info(f"Goal {goal_id} PERMANENTLY FAILED.")
            
            self.metrics['goals_pursued'] += 1
            await asyncio.sleep(5) # Delay entre metas para não sobrecarregar

    def get_status(self) -> dict:
        return {
            "enabled": self.enabled,
            "metrics": self.metrics,
            "active_task": self._task is not None and not self._task.done()
        }

# Singleton instance
_instance = AutonomousGoalLoop()

def get_autonomous_loop() -> AutonomousGoalLoop:
    return _instance

def start_autonomous_goal_loop():
    _instance.start()
