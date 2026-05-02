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

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
AUTONOMY_STATE_PATH = DATA_DIR / "autonomous_loop_state.json"


def _now() -> int:
    return int(time.time())


def _clamp01(value: float) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except Exception:
        return 0.0


def _safe_json(obj: Any) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False, default=str)
    except Exception:
        return "{}"

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
        self.goals: dict[str, dict[str, Any]] = {}
        self.action_history: list[dict[str, Any]] = []
        self.reward_weights: dict[str, float] = {}
        self.last_environment: dict[str, Any] = {}
        self.last_prediction: dict[str, Any] = {}
        self.last_suggestions: list[dict[str, Any]] = []
        self.metrics = {
            'goals_pursued': 0,
            'successes': 0,
            'failures': 0,
            'avg_reward': 0.0
        }
        self._load()

    def _load(self) -> None:
        if not AUTONOMY_STATE_PATH.exists():
            return
        try:
            data = json.loads(AUTONOMY_STATE_PATH.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return
            self.goals = data.get("goals") if isinstance(data.get("goals"), dict) else {}
            self.action_history = data.get("action_history") if isinstance(data.get("action_history"), list) else []
            self.reward_weights = data.get("reward_weights") if isinstance(data.get("reward_weights"), dict) else {}
            self.metrics.update(data.get("metrics") if isinstance(data.get("metrics"), dict) else {})
            self.last_environment = data.get("last_environment") if isinstance(data.get("last_environment"), dict) else {}
            self.last_prediction = data.get("last_prediction") if isinstance(data.get("last_prediction"), dict) else {}
            self.last_suggestions = data.get("last_suggestions") if isinstance(data.get("last_suggestions"), list) else []
        except Exception as exc:
            logger.debug("AutonomousGoalLoop: failed to load state: %s", exc)

    def _save(self) -> None:
        try:
            AUTONOMY_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            AUTONOMY_STATE_PATH.write_text(
                json.dumps(
                    {
                        "updated_at": _now(),
                        "goals": self.goals,
                        "action_history": self.action_history[-400:],
                        "reward_weights": self.reward_weights,
                        "metrics": self.metrics,
                        "last_environment": self.last_environment,
                        "last_prediction": self.last_prediction,
                        "last_suggestions": self.last_suggestions[-20:],
                    },
                    ensure_ascii=False,
                    indent=2,
                    default=str,
                ),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.debug("AutonomousGoalLoop: failed to save state: %s", exc)

    def set_goal(self, goal_id: str, description: str, deadline: str | None = None) -> dict[str, Any]:
        """Register a lightweight autonomous goal used by the API/status loop."""
        gid = str(goal_id or f"goal_{_now()}").strip()
        goal = {
            "id": gid,
            "description": str(description or "").strip(),
            "deadline": deadline,
            "progress": float((self.goals.get(gid) or {}).get("progress") or 0.0),
            "status": str((self.goals.get(gid) or {}).get("status") or "active"),
            "created_at": int((self.goals.get(gid) or {}).get("created_at") or _now()),
            "updated_at": _now(),
            "evidence": list((self.goals.get(gid) or {}).get("evidence") or [])[-20:],
        }
        self.goals[gid] = goal
        try:
            title = goal["description"][:180] or gid
            store.db.upsert_goal(title=title, description=goal["description"], priority=5)
        except Exception:
            pass
        self._save()
        return goal

    def update_goal_progress(self, goal_id: str, progress: float, evidence: str = "") -> dict[str, Any]:
        """Update local goal progress and mirror meaningful progress to the workspace."""
        gid = str(goal_id or "").strip()
        if not gid:
            return {"ok": False, "reason": "missing_goal_id"}
        goal = self.goals.get(gid) or self.set_goal(gid, "", None)
        goal["progress"] = _clamp01(max(float(goal.get("progress") or 0.0), float(progress or 0.0)))
        goal["updated_at"] = _now()
        if evidence:
            ev = list(goal.get("evidence") or [])
            ev.append({"ts": _now(), "text": str(evidence)[:700], "progress": goal["progress"]})
            goal["evidence"] = ev[-30:]
        if goal["progress"] >= 1.0:
            goal["status"] = "done"
        self.goals[gid] = goal
        try:
            store.publish_workspace(
                module="autonomous_loop",
                channel="goal.progress",
                payload_json=_safe_json({"goal_id": gid, "progress": goal["progress"], "evidence": evidence[:240]}),
                salience=0.68 if goal["status"] == "done" else 0.48,
                ttl_sec=1800,
            )
        except Exception:
            pass
        self._save()
        return {"ok": True, "goal": goal}

    def _reward_from_outcome(self, success: bool, quality_score: float, latency_ms: int) -> float:
        speed = 1.0 - min(1.0, max(0.0, float(latency_ms or 0)) / 30000.0)
        base = 0.55 if success else 0.10
        reward = base + 0.35 * _clamp01(quality_score) + 0.10 * speed
        if not success:
            reward -= 0.25
        return round(_clamp01(reward), 4)

    def record_action(
        self,
        action_kind: str,
        context: str,
        success: bool,
        latency_ms: int,
        quality_score: float = 0.5,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Record an action outcome and update the local reinforcement summary."""
        kind = str(action_kind or "unknown")[:80]
        reward = self._reward_from_outcome(bool(success), float(quality_score or 0.0), int(latency_ms or 0))
        row = {
            "ts": _now(),
            "action_kind": kind,
            "context": str(context or "")[:500],
            "success": bool(success),
            "latency_ms": int(latency_ms or 0),
            "quality_score": round(_clamp01(float(quality_score or 0.0)), 4),
            "reward": reward,
            "metadata": dict(metadata or {}),
        }
        self.action_history.append(row)
        self.action_history = self.action_history[-400:]

        old = float(self.reward_weights.get(kind, 0.5) or 0.5)
        self.reward_weights[kind] = round(0.82 * old + 0.18 * reward, 4)
        self.metrics["successes"] = int(self.metrics.get("successes") or 0) + (1 if success else 0)
        self.metrics["failures"] = int(self.metrics.get("failures") or 0) + (0 if success else 1)
        self.metrics["goals_pursued"] = int(self.metrics.get("goals_pursued") or 0) + 1
        n = max(1, int(self.metrics.get("goals_pursued") or 1))
        prev_avg = float(self.metrics.get("avg_reward") or 0.0)
        self.metrics["avg_reward"] = round(((prev_avg * (n - 1)) + reward) / n, 4)
        self._save()
        return {"ok": True, "reward": reward, "action": row, "weight": self.reward_weights[kind]}

    def _rolling_metrics(self) -> dict[str, Any]:
        actions = []
        try:
            actions = store.db.list_actions(limit=160)
        except Exception:
            actions = []

        recent = actions[-120:]
        denom = max(1, len(recent))
        done = [a for a in recent if str(a.get("status") or "") == "done"]
        risky = [a for a in recent if str(a.get("status") or "") in ("done_with_risk", "blocked", "error")]
        blocked = [a for a in recent if str(a.get("status") or "") == "blocked"]
        queued = [a for a in recent if str(a.get("status") or "") == "queued"]

        episodes = []
        try:
            from ultronpro import episodic_memory

            episodes = episodic_memory.recent(limit=120)
        except Exception:
            episodes = []
        latencies = [int(e.get("latency_ms") or 0) for e in episodes if int(e.get("latency_ms") or 0) > 0]
        avg_latency = int(sum(latencies) / max(1, len(latencies))) if latencies else 1000

        structured = []
        try:
            from ultronpro import episodic_memory

            structured = episodic_memory.recent_structured(limit=80)
        except Exception:
            structured = []
        surprises = []
        for ep in structured[-50:]:
            try:
                em = ep.get("episodic_memory") if isinstance(ep.get("episodic_memory"), dict) else {}
                surprises.append(float(em.get("surpresa_calculada") or 0.0))
            except Exception:
                continue
        avg_surprise = sum(surprises) / max(1, len(surprises)) if surprises else 0.25

        return {
            "action_sample": len(recent),
            "success_rate": round(len(done) / denom, 4),
            "error_rate": round(len(risky) / denom, 4),
            "blocked_rate": round(len(blocked) / denom, 4),
            "queue_size": len(queued),
            "latency_ms": avg_latency,
            "surprise_score": round(_clamp01(avg_surprise), 4),
        }

    def perceive_environment(self) -> dict[str, Any]:
        """Perceive the operational environment and persist it into memory/world-model layers."""
        metrics = self._rolling_metrics()
        hs = {}
        wm = {}
        intrinsic = {}
        try:
            from ultronpro import homeostasis

            hs = homeostasis.status()
        except Exception:
            hs = {}
        try:
            from ultronpro import working_memory

            wm = working_memory.get_working_memory_status()
        except Exception:
            wm = {}
        try:
            from ultronpro import intrinsic_utility

            intrinsic = intrinsic_utility.status(limit=5)
        except Exception:
            intrinsic = {}

        vitals = hs.get("vitals") if isinstance(hs.get("vitals"), dict) else {}
        metrics["drift_score"] = round(
            _clamp01(
                0.45 * float(vitals.get("goal_drift") or 0.0)
                + 0.35 * float(vitals.get("contradiction_stress") or 0.0)
                + 0.20 * float(vitals.get("memory_pressure") or 0.0)
            ),
            4,
        )
        environment = {
            "ts": _now(),
            "metrics": metrics,
            "homeostasis": {
                "mode": hs.get("mode"),
                "vitals": vitals,
                "updated_at": hs.get("updated_at"),
            },
            "working_memory": {
                "item_count": wm.get("item_count"),
                "capacity_used": wm.get("capacity_used"),
                "attention_state": wm.get("attention_state"),
                "avg_salience": wm.get("avg_salience"),
            },
            "intrinsic": {
                "utility": intrinsic.get("utility"),
                "active_emergent_goal": intrinsic.get("active_emergent_goal"),
            },
            "local_goals": [
                {
                    "id": gid,
                    "progress": g.get("progress"),
                    "status": g.get("status"),
                    "description": str(g.get("description") or "")[:160],
                }
                for gid, g in list(self.goals.items())[-20:]
            ],
        }

        prediction = {}
        try:
            from ultronpro import self_predictive_model

            prediction = self_predictive_model.record_health_snapshot(
                metrics,
                source="autonomous_loop_environment",
                persist=True,
            )
        except Exception as exc:
            prediction = {"ok": False, "error": str(exc)[:180]}

        try:
            from ultronpro import world_model

            pred = prediction.get("prediction") if isinstance(prediction.get("prediction"), dict) else {}
            outcome = "risk" if float(pred.get("degradation_risk") or 0.0) >= 0.45 else "nominal"
            world_model.observe(
                source="autonomous_loop",
                event_type="environment_tick",
                content=f"mode={environment['homeostasis'].get('mode')} success={metrics.get('success_rate')} risk={pred.get('degradation_risk')}",
                state_after={"autonomy_environment": environment},
                outcome=outcome,
                metadata={"prediction": pred},
            )
        except Exception:
            pass

        try:
            from ultronpro import working_memory

            pred = prediction.get("prediction") if isinstance(prediction.get("prediction"), dict) else {}
            working_memory.add_to_working_memory(
                content=(
                    f"Autonomy perception: mode={environment['homeostasis'].get('mode')} "
                    f"success={metrics.get('success_rate')} error={metrics.get('error_rate')} "
                    f"risk={pred.get('degradation_risk')}"
                ),
                source="autonomous_loop",
                item_type="environment_snapshot",
                salience=0.72 if float(pred.get("degradation_risk") or 0.0) >= 0.45 else 0.45,
                metadata={"metrics": metrics, "prediction": pred},
            )
        except Exception:
            pass

        self.last_environment = environment
        self.last_prediction = prediction
        self._save()
        return {"ok": True, "environment": environment, "prediction": prediction}

    def suggest_actions(self, environment: dict[str, Any], prediction: dict[str, Any]) -> list[dict[str, Any]]:
        pred = prediction.get("prediction") if isinstance(prediction.get("prediction"), dict) else prediction
        metrics = environment.get("metrics") if isinstance(environment.get("metrics"), dict) else {}
        hs = environment.get("homeostasis") if isinstance(environment.get("homeostasis"), dict) else {}
        risk = float(pred.get("degradation_risk") or 0.0)
        indicators = set(pred.get("leading_indicators") if isinstance(pred.get("leading_indicators"), list) else [])
        suggestions: list[dict[str, Any]] = []

        if risk >= 0.75:
            suggestions.append({
                "kind": "deliberate_task",
                "text": "(autonomy-risk) Risco alto de degradacao: pausar acoes pesadas, revisar erros recentes e pedir ajuda humana se persistir.",
                "priority": 9,
                "reason": "high_degradation_risk",
                "meta": {"task_type": "critical", "require_contrafactual": True, "risk": risk},
            })
        elif risk >= 0.45:
            suggestions.append({
                "kind": "curate_memory",
                "text": "(autonomy-risk) Entrar em modo conservador: curar memoria recente e reduzir ruido antes de novas exploracoes.",
                "priority": 7,
                "reason": "moderate_degradation_risk",
                "meta": {"task_type": "review", "risk": risk},
            })

        if "error_rate_increase" in indicators or float(metrics.get("error_rate") or 0.0) >= 0.22:
            suggestions.append({
                "kind": "deliberate_task",
                "text": "(autonomy-learning) Analisar padroes dos ultimos erros e propor uma correcao verificavel.",
                "priority": 8,
                "reason": "error_rate_increase",
                "meta": {"problem_text": "Identificar causas comuns de falhas recentes e escolher a correcao de menor risco.", "task_type": "review"},
            })

        if "surprise_increase" in indicators or float(metrics.get("surprise_score") or 0.0) >= 0.55:
            suggestions.append({
                "kind": "self_play_simulation",
                "text": "(autonomy-world-model) Rodar simulacoes internas para reduzir surpresa e atualizar modelo causal local.",
                "priority": 6,
                "reason": "surprise_increase",
                "meta": {"size": 16, "task_type": "review"},
            })

        if str(hs.get("mode") or "") == "repair":
            suggestions.append({
                "kind": "auto_resolve_conflicts",
                "text": "(autonomy-repair) Resolver conflito aberto de maior impacto antes de continuar exploracao.",
                "priority": 8,
                "reason": "homeostasis_repair",
                "meta": {"task_type": "review"},
            })

        if not suggestions:
            suggestions.append({
                "kind": "intrinsic_tick",
                "text": "(autonomy-nominal) Atualizar drives intrinsecos e manter objetivo emergente alinhado a evidencias recentes.",
                "priority": 4,
                "reason": "nominal_learning_continuity",
                "meta": {"task_type": "heartbeat"},
            })

        return suggestions[:6]

    def _enqueue_suggestion_if_new(self, suggestion: dict[str, Any]) -> int | None:
        kind = str(suggestion.get("kind") or "ask_evidence")
        text = str(suggestion.get("text") or "")
        if not text:
            return None
        try:
            recent = store.db.list_actions(limit=120)
            for action in recent:
                if str(action.get("status") or "") != "queued":
                    continue
                if str(action.get("kind") or "") == kind and str(action.get("text") or "") == text:
                    return None
            meta = dict(suggestion.get("meta") or {})
            meta.setdefault("origin", "autonomous_closure_cycle")
            return store.db.enqueue_action(
                kind=kind,
                text=text,
                priority=int(suggestion.get("priority") or 0),
                meta_json=_safe_json(meta),
                expires_at=time.time() + 30 * 60,
                cooldown_key=f"autonomous_closure:{kind}:{abs(hash(text)) % 100000}",
            )
        except Exception:
            return None

    def cycle(self, *, enqueue: bool = True) -> dict[str, Any]:
        """Synchronous perception -> prediction -> suggestion cycle for API/manual ticks."""
        perceived = self.perceive_environment()
        environment = perceived.get("environment") if isinstance(perceived.get("environment"), dict) else {}
        prediction = perceived.get("prediction") if isinstance(perceived.get("prediction"), dict) else {}
        suggestions = self.suggest_actions(environment, prediction)
        enqueued: list[int] = []
        if enqueue:
            for suggestion in suggestions[:3]:
                action_id = self._enqueue_suggestion_if_new(suggestion)
                if action_id:
                    enqueued.append(int(action_id))
        self.last_suggestions = suggestions
        self._save()
        try:
            store.publish_workspace(
                module="autonomous_loop",
                channel="autonomy.suggestions",
                payload_json=_safe_json({"suggestions": suggestions, "enqueued": enqueued}),
                salience=0.62,
                ttl_sec=1200,
            )
        except Exception:
            pass
        return {
            "ok": True,
            "environment": environment,
            "prediction": prediction,
            "suggestions": suggestions,
            "enqueued_action_ids": enqueued,
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
        active_goals = store.db.get_active_goals(limit=3)
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
                store.db.update_goal_status(goal_id, 'failed', meta_json=json.dumps({"reason": "max_attempts_exceeded"}))
                continue

            logger.info(f"[PEORU] Pursuing: {goal['title']} (Attempt {goal['attempts_count']+1})")
            
            # --- VETO SUBCONSCIENTE (Fase 5.3 / 5.8) ---
            try:
                veto_decision = evaluate_narrative_veto(goal['title'], goal.get('description', ''))
                if veto_decision.get('vetoed'):
                    logger.warning(f"[SUBCONSCIOUS VETO] Goal '{goal['title']}' foi vetada. Razão: {veto_decision.get('reason')}")
                    store.db.add_goal_attempt(
                        goal_id,
                        plan_json="{}",
                        success=False,
                        error_text=f"VETADO_PELO_SUBCONSCIENTE: {veto_decision.get('reason')}",
                        reward=-1.0,
                        duration_ms=0,
                        result_json=json.dumps({'veto_reason': veto_decision.get('reason')})
                    )
                    store.db.update_goal_status(goal_id, 'failed', meta_json=json.dumps({"reason": "vetoed"}))
                    # Registro explícito desse ato autônomo na memória de longo prazo
                    store.db.add_event(
                        'autonomous_veto',
                        f"Goal vetado: {goal['title'][:160]} reason={str(veto_decision.get('reason') or '')[:180]}",
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
                history = store.db.get_goal_history(goal_id, limit=5)
                # O refletor analisa o erro e sugere correções para a próxima tentativa
                reflection = reflector.reflect_on_failure(goal, {'error_text': error, 'plan_json': json.dumps(plan)}, history)
                logger.info(f"Reflected on failure: {reflection.get('diagnosis')}")

            # 5. UPDATE
            store.db.add_goal_attempt(
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

            try:
                close_loop_with_intrinsic(
                    action_kind='autonomous_goal_pursuit',
                    context=goal.get('title', 'unknown'),
                    success=success,
                    quality_score=1.0 if success else 0.25,
                    latency_ms=duration_ms,
                    risk_reason=error or '',
                    metadata={'goal_id': goal_id, 'reflection': reflection},
                )
            except Exception:
                pass

            if success:
                store.db.update_goal_status(goal_id, 'done', meta_json=json.dumps(result))
                logger.info(f"Goal {goal_id} COMPLETED: {goal['title']}")
            elif goal['attempts_count'] + 1 >= goal['max_attempts']:
                store.db.update_goal_status(goal_id, 'failed', meta_json=json.dumps({'error': error, 'reflection': reflection}))
                logger.info(f"Goal {goal_id} PERMANENTLY FAILED.")
            
            self.metrics['goals_pursued'] += 1
            await asyncio.sleep(5) # Delay entre metas para não sobrecarregar

    def get_status(self) -> dict:
        return {
            "ok": True,
            "enabled": self.enabled,
            "metrics": self.metrics,
            "active_task": self._task is not None and not self._task.done(),
            "reward_weights": self.reward_weights,
            "active_goals": [g for g in self.goals.values() if str(g.get("status") or "") in ("active", "open")],
            "history_size": len(self.action_history),
            "last_environment": self.last_environment,
            "last_prediction": self.last_prediction,
            "last_suggestions": self.last_suggestions,
            "state_path": str(AUTONOMY_STATE_PATH),
        }

# Singleton instance
_instance = AutonomousGoalLoop()

def get_autonomous_loop() -> AutonomousGoalLoop:
    return _instance

def start_autonomous_goal_loop():
    _instance.start()


def get_emergent_goal() -> dict[str, Any] | None:
    try:
        from ultronpro import intrinsic_utility

        status = intrinsic_utility.status(limit=5)
        goal = status.get("active_emergent_goal")
        if goal:
            return goal
        tick = intrinsic_utility.tick()
        return tick.get("active_emergent_goal")
    except Exception:
        return None


def get_self_generated_goals_summary() -> dict[str, Any]:
    try:
        from ultronpro import intrinsic_utility

        st = intrinsic_utility.status(limit=20)
        return {
            "ok": True,
            "utility": st.get("utility"),
            "drives": st.get("drives"),
            "recent_emergent_goals": st.get("recent_emergent_goals"),
            "active_emergent_goal": st.get("active_emergent_goal"),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:180]}


def close_loop_with_intrinsic(
    *,
    action_kind: str,
    context: str,
    success: bool,
    quality_score: float,
    latency_ms: int,
    risk_reason: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Close the autonomous feedback loop across memory, prediction, reward and learning."""
    loop = get_autonomous_loop()
    meta = dict(metadata or {})
    meta["risk_reason"] = str(risk_reason or "")[:240]
    recorded = loop.record_action(
        action_kind=action_kind,
        context=context,
        success=bool(success),
        latency_ms=int(latency_ms or 0),
        quality_score=float(quality_score or 0.0),
        metadata=meta,
    )
    reward = float(recorded.get("reward") or 0.0)

    try:
        from ultronpro import intrinsic_utility

        active = intrinsic_utility.status(limit=3).get("active_emergent_goal") or {}
        drive = str(active.get("drive") or "")
        if drive:
            meta["intrinsic_adjustment"] = intrinsic_utility.adjust_drive_weights(drive, reward)
    except Exception:
        pass

    try:
        self_model.record_action_outcome(
            strategy=str(action_kind or "unknown"),
            task_type=str(meta.get("task_type") or context or "autonomous_feedback")[:80],
            budget_profile=str(meta.get("budget_profile") or "autonomous"),
            ok=bool(success),
            latency_ms=int(latency_ms or 0),
            notes=str(risk_reason or "closed_loop")[:240],
        )
    except Exception:
        pass

    try:
        from ultronpro import world_model

        world_model.observe(
            source="autonomous_loop",
            event_type=str(action_kind or "action_outcome")[:80],
            content=str(context or "")[:600],
            state_before={"action_kind": action_kind, "metadata": meta},
            state_after={"success": bool(success), "quality_score": quality_score, "reward": reward},
            outcome="success" if success else "failure",
            metadata={"latency_ms": int(latency_ms or 0), "risk_reason": risk_reason[:240]},
        )
    except Exception:
        pass

    try:
        from ultronpro import working_memory

        working_memory.add_to_working_memory(
            content=(
                f"Action outcome: {action_kind} success={bool(success)} "
                f"quality={float(quality_score or 0.0):.2f} reward={reward:.2f} reason={str(risk_reason or '')[:120]}"
            ),
            source="autonomous_loop",
            item_type="action_outcome",
            salience=0.78 if not success else 0.52,
            metadata={"action_kind": action_kind, "reward": reward, **meta},
        )
    except Exception:
        pass

    try:
        from ultronpro import local_world_models

        state_t = {"context": str(context or "")[:240], "task_type": str(meta.get("task_type") or "autonomous")}
        state_t1 = {**state_t, "success": bool(success), "reward": reward}
        local_world_models.train_local_model(
            family_name=str(meta.get("world_family") or "autonomous_actions"),
            state_t=state_t,
            action=str(action_kind or "unknown"),
            state_t_plus_1=state_t1,
            actual_outcome="success" if success else "failure",
            metrics={"surprise_delta": max(0.0, 1.0 - reward), "quality_score": float(quality_score or 0.0)},
        )
    except Exception:
        pass

    try:
        from ultronpro import episodic_memory

        episodic_memory.append_episode(
            action_id=int(abs(hash(f"{action_kind}:{context}:{time.time()}")) % 2147483647),
            kind=str(action_kind or "autonomous_feedback"),
            text=str(context or ""),
            task_type=str(meta.get("task_type") or "autonomous"),
            strategy=str(action_kind or "unknown"),
            ok=bool(success),
            latency_ms=int(latency_ms or 0),
            error=str(risk_reason or ""),
            meta={"reward": reward, **meta},
        )
    except Exception:
        pass

    try:
        from ultronpro import self_corrector

        if success:
            self_corrector.record_success(str(action_kind or "unknown"), str(context or "")[:200])
        else:
            self_corrector.learn_from_error(
                action=str(action_kind or "unknown"),
                context=str(context or "")[:200],
                error=str(risk_reason or "autonomous_outcome_failed"),
                metadata={"quality_score": quality_score, "reward": reward, **meta},
            )
    except Exception:
        pass

    try:
        from ultronpro import self_predictive_model

        loop.perceive_environment()
        predictive = self_predictive_model.status()
        pred = predictive.get("prediction") if isinstance(predictive.get("prediction"), dict) else {}
        if float(pred.get("degradation_risk") or 0.0) >= 0.45:
            loop.last_suggestions = loop.suggest_actions(loop.last_environment or {}, predictive)
            loop._save()
    except Exception:
        pass

    try:
        store.publish_workspace(
            module="autonomous_loop",
            channel="feedback.closed",
            payload_json=_safe_json({
                "action_kind": action_kind,
                "success": bool(success),
                "quality_score": quality_score,
                "latency_ms": latency_ms,
                "reward": reward,
                "risk_reason": risk_reason[:240],
            }),
            salience=0.76 if not success else 0.50,
            ttl_sec=1800,
        )
    except Exception:
        pass

    return {"ok": True, "reward": reward, "recorded": recorded, "metadata": meta}
