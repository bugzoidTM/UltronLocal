"""Autonomous internal cognition loop for UltronPro.

This module closes a small but important internal loop:

1. perceive internal state from events, workspace, goals, actions and conflicts;
2. predict operational risks and suggest safe internal actions;
3. execute one reversible internal action and learn from the observed outcome.

It does not depend on chat traffic. It uses the existing SQLite store,
Global Workspace, actions table, episodic memory and local world models.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import asdict, dataclass
from typing import Any

from ultronpro import store


def _env_flag(name: str, default: str = "1") -> bool:
    return str(os.getenv(name, default)).strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(float(os.getenv(name, str(default)) or default))
    except Exception:
        return default


ENABLED = _env_flag("ULTRON_AUTONOMOUS_COGNITION_ENABLED", "1")
INTERVAL_SEC = max(30, _env_int("ULTRON_AUTONOMOUS_COGNITION_INTERVAL_SEC", 90))
MAX_ACTIONS_PER_TICK = max(1, _env_int("ULTRON_AUTONOMOUS_COGNITION_MAX_ACTIONS", 1))

ERROR_MARKERS = (
    "error",
    "erro",
    "exception",
    "falha",
    "failed",
    "timeout",
    "blocked",
    "veto",
)

_task: asyncio.Task | None = None
_running = False
_last_cycle: dict[str, Any] = {}
_metrics: dict[str, Any] = {
    "ticks": 0,
    "perceptions": 0,
    "risk_forecasts": 0,
    "suggestions": 0,
    "actions_executed": 0,
    "consequences_learned": 0,
    "last_error": None,
}


@dataclass
class RiskForecast:
    risk_id: str
    score: float
    reason: str
    evidence: dict[str, Any]
    recommended_action: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ActionSuggestion:
    action_key: str
    kind: str
    text: str
    priority: int
    expected_effect: str
    risk_score: float
    evidence: dict[str, Any]
    workspace_channel: str = "autonomous.action_suggestion"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _now() -> float:
    return time.time()


def _clip01(value: float) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except Exception:
        return 0.0


def _json_dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str, separators=(",", ":"))


def _json_loads(value: Any, default: Any = None) -> Any:
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value or ""))
    except Exception:
        return default


def _db(store_module: Any = None) -> Any:
    module = store_module or store
    return getattr(module, "db", module)


def _call(obj: Any, name: str, *args: Any, default: Any = None, **kwargs: Any) -> Any:
    fn = getattr(obj, name, None)
    if not callable(fn):
        return default
    try:
        return fn(*args, **kwargs)
    except Exception:
        return default


def _recent_error_count(events: list[dict[str, Any]], window_sec: int = 3600) -> int:
    cutoff = _now() - max(60, int(window_sec or 3600))
    count = 0
    for event in events:
        try:
            if float(event.get("created_at") or 0.0) < cutoff:
                continue
        except Exception:
            continue
        text = f"{event.get('kind', '')} {event.get('text', '')} {event.get('meta_json', '')}".lower()
        if any(marker in text for marker in ERROR_MARKERS):
            count += 1
    return count


def _parse_workspace_payload(item: dict[str, Any]) -> dict[str, Any]:
    payload = _json_loads(item.get("payload_json"), {})
    return payload if isinstance(payload, dict) else {"payload": payload}


def _queued_action_keys(actions: list[dict[str, Any]]) -> set[str]:
    keys = set()
    for action in actions:
        if str(action.get("status") or "") != "queued":
            continue
        key = str(action.get("cooldown_key") or "").strip()
        if key:
            keys.add(key)
    return keys


def observe_internal_state(
    *,
    store_module: Any = None,
    limit: int = 80,
    publish: bool = True,
) -> dict[str, Any]:
    """Perceive internal state and publish it to the Global Workspace."""
    db = _db(store_module)
    limit = max(10, min(300, int(limit or 80)))

    events = _call(db, "list_events", 0, limit, default=[]) or []
    workspace = _call(db, "read_workspace", limit=limit, include_expired=False, default=[]) or []
    actions = _call(db, "list_actions", limit=limit, default=[]) or []
    goals = _call(db, "get_active_goals", limit=10, default=None)
    if goals is None:
        active = _call(db, "get_active_goal", default=None)
        goals = [active] if active else []
    conflicts = _call(db, "list_conflicts", status="open", limit=20, default=[]) or []
    episodes = _call(db, "list_episodic_episodes", limit=20, default=[]) or []

    queued_actions = [a for a in actions if str(a.get("status") or "") == "queued"]
    failed_actions = [a for a in actions if str(a.get("status") or "") in {"error", "blocked"}]
    high_salience = [w for w in workspace if float(w.get("salience") or 0.0) >= 0.75]
    unconsumed_high = [
        w for w in high_salience
        if "autonomous_cognition" not in str(w.get("consumed_by_json") or "")
    ]

    top_focus = []
    for item in sorted(workspace, key=lambda w: float(w.get("salience") or 0.0), reverse=True)[:5]:
        payload = _parse_workspace_payload(item)
        top_focus.append({
            "id": item.get("id"),
            "channel": item.get("channel"),
            "module": item.get("module"),
            "salience": round(float(item.get("salience") or 0.0), 4),
            "summary": str(
                payload.get("summary")
                or payload.get("reason")
                or payload.get("type")
                or payload.get("goal")
                or payload.get("topic")
                or item.get("channel")
            )[:180],
        })

    snapshot = {
        "ok": True,
        "ts": _now(),
        "event_count": len(events),
        "workspace_count": len(workspace),
        "high_salience_count": len(high_salience),
        "unconsumed_high_salience_count": len(unconsumed_high),
        "queued_action_count": len(queued_actions),
        "failed_action_count": len(failed_actions),
        "active_goal_count": len(goals),
        "open_conflict_count": len(conflicts),
        "recent_episode_count": len(episodes),
        "recent_error_count": _recent_error_count(events),
        "top_focus": top_focus,
        "goals": [
            {
                "id": g.get("id"),
                "title": str(g.get("title") or "")[:180],
                "priority": int(g.get("priority") or 0),
                "attempts_count": int(g.get("attempts_count") or 0),
                "max_attempts": int(g.get("max_attempts") or 5),
            }
            for g in goals if isinstance(g, dict)
        ],
    }

    if publish:
        _call(
            db,
            "publish_workspace",
            module="autonomous_cognition",
            channel="autonomous.perception",
            payload_json=_json_dumps(snapshot),
            salience=0.62 + min(0.18, snapshot["unconsumed_high_salience_count"] * 0.03),
            ttl_sec=600,
        )
        _call(
            db,
            "add_event",
            "autonomous_cognition",
            (
                "perception "
                f"workspace={snapshot['workspace_count']} queued={snapshot['queued_action_count']} "
                f"errors={snapshot['recent_error_count']} goals={snapshot['active_goal_count']}"
            ),
            _json_dumps({"snapshot": snapshot}),
        )
        _metrics["perceptions"] += 1

    return snapshot


def predict_risks(
    snapshot: dict[str, Any],
    *,
    store_module: Any = None,
    publish: bool = True,
) -> list[dict[str, Any]]:
    """Predict risks from the perceived internal state."""
    db = _db(store_module)
    risks: list[RiskForecast] = []

    workspace_pressure = _clip01(
        (float(snapshot.get("workspace_count") or 0.0) / 80.0)
        + (float(snapshot.get("unconsumed_high_salience_count") or 0.0) * 0.08)
    )
    if workspace_pressure >= 0.35:
        risks.append(RiskForecast(
            "workspace_attention_pressure",
            workspace_pressure,
            "Global Workspace has many or highly salient unconsumed signals.",
            {
                "workspace_count": snapshot.get("workspace_count"),
                "unconsumed_high_salience_count": snapshot.get("unconsumed_high_salience_count"),
            },
            "compact_workspace_focus",
        ))

    action_backlog = _clip01(float(snapshot.get("queued_action_count") or 0.0) / 12.0)
    if action_backlog >= 0.25:
        risks.append(RiskForecast(
            "queued_action_backlog",
            action_backlog,
            "Queued actions are accumulating faster than they are resolved.",
            {"queued_action_count": snapshot.get("queued_action_count")},
            "prioritize_action_backlog",
        ))

    recent_errors = _clip01(float(snapshot.get("recent_error_count") or 0.0) / 8.0)
    if recent_errors >= 0.25:
        risks.append(RiskForecast(
            "recent_failure_cluster",
            recent_errors,
            "Recent events contain repeated error/failure markers.",
            {"recent_error_count": snapshot.get("recent_error_count")},
            "trigger_reflexion_review",
        ))

    if int(snapshot.get("active_goal_count") or 0) <= 0:
        risks.append(RiskForecast(
            "goal_starvation",
            0.58,
            "No active/open internal goal is available for autonomous pursuit.",
            {"active_goal_count": 0},
            "create_self_maintenance_goal",
        ))

    conflicts = _clip01(float(snapshot.get("open_conflict_count") or 0.0) / 6.0)
    if conflicts >= 0.2:
        risks.append(RiskForecast(
            "open_conflict_pressure",
            conflicts,
            "Unresolved conflicts can fragment planning and memory consolidation.",
            {"open_conflict_count": snapshot.get("open_conflict_count")},
            "queue_conflict_review",
        ))

    out = [r.to_dict() for r in sorted(risks, key=lambda r: r.score, reverse=True)]
    if publish:
        _call(
            db,
            "publish_workspace",
            module="autonomous_cognition",
            channel="autonomous.risk_forecast",
            payload_json=_json_dumps({"risks": out, "snapshot_ts": snapshot.get("ts")}),
            salience=0.66 + min(0.22, max([r["score"] for r in out], default=0.0) * 0.22),
            ttl_sec=900,
        )
        _metrics["risk_forecasts"] += 1
    return out


def _suggestion_from_risk(risk: dict[str, Any]) -> ActionSuggestion:
    action = str(risk.get("recommended_action") or "observe_again")
    score = _clip01(float(risk.get("score") or 0.0))
    templates = {
        "compact_workspace_focus": (
            "Compress attention state and prune low-salience workspace residue.",
            "reduce workspace pressure and expose a clearer focus set",
        ),
        "prioritize_action_backlog": (
            "Publish an action-backlog focus item for the executor before adding more work.",
            "make queued work visible and reduce duplicated autonomous suggestions",
        ),
        "trigger_reflexion_review": (
            "Trigger a reflexion review over recent failures before further autonomous execution.",
            "convert repeated failure into a diagnostic hypothesis",
        ),
        "create_self_maintenance_goal": (
            "Create a standing internal goal to maintain autonomy, memory and risk calibration.",
            "give the autonomous executor a durable target when the user is absent",
        ),
        "queue_conflict_review": (
            "Publish a conflict review request for the highest-pressure open contradictions.",
            "route contradictions into the existing conflict/reflexion machinery",
        ),
    }
    text, expected = templates.get(action, ("Observe again after the next internal event.", "avoid acting on weak evidence"))
    return ActionSuggestion(
        action_key=f"autocog:{action}",
        kind="autonomous_internal",
        text=text,
        priority=max(1, min(9, int(round(score * 10)))),
        expected_effect=expected,
        risk_score=score,
        evidence=dict(risk.get("evidence") or {}),
    )


def suggest_actions(
    snapshot: dict[str, Any],
    risks: list[dict[str, Any]],
    *,
    store_module: Any = None,
    enqueue: bool = True,
    publish: bool = True,
) -> list[dict[str, Any]]:
    """Turn risk forecasts into safe, reversible internal action suggestions."""
    db = _db(store_module)
    actions = _call(db, "list_actions", limit=120, default=[]) or []
    queued_keys = _queued_action_keys(actions)

    suggestions: list[ActionSuggestion] = []
    for risk in risks:
        suggestion = _suggestion_from_risk(risk)
        if suggestion.action_key in {s.action_key for s in suggestions}:
            continue
        suggestions.append(suggestion)

    enqueued = []
    if enqueue:
        expires = _now() + 1800
        for suggestion in suggestions[:5]:
            if suggestion.action_key in queued_keys:
                continue
            action_id = _call(
                db,
                "enqueue_action",
                suggestion.kind,
                suggestion.text,
                suggestion.priority,
                _json_dumps({
                    "source": "autonomous_cognition",
                    "action_key": suggestion.action_key,
                    "expected_effect": suggestion.expected_effect,
                    "risk_score": suggestion.risk_score,
                    "evidence": suggestion.evidence,
                    "snapshot_ts": snapshot.get("ts"),
                }),
                expires,
                suggestion.action_key,
                default=None,
            )
            if action_id:
                enqueued.append({"id": action_id, "action_key": suggestion.action_key})

    out = [s.to_dict() for s in suggestions]
    if publish:
        _call(
            db,
            "publish_workspace",
            module="autonomous_cognition",
            channel="autonomous.action_suggestions",
            payload_json=_json_dumps({"suggestions": out, "enqueued": enqueued}),
            salience=0.68 + min(0.18, len(enqueued) * 0.04),
            ttl_sec=900,
        )
        _metrics["suggestions"] += len(out)
    return out


def _internal_actions(db: Any) -> list[dict[str, Any]]:
    actions = _call(db, "list_actions", limit=80, default=[]) or []
    return [
        a for a in sorted(actions, key=lambda x: (-int(x.get("priority") or 0), int(x.get("id") or 0)))
        if str(a.get("status") or "") == "queued" and str(a.get("kind") or "") == "autonomous_internal"
    ]


def _execute_internal_action(db: Any, action: dict[str, Any]) -> dict[str, Any]:
    action_id = int(action.get("id") or 0)
    meta = _json_loads(action.get("meta_json"), {})
    action_key = str((meta or {}).get("action_key") or action.get("cooldown_key") or "")
    started = _now()

    _call(db, "mark_action", action_id, "running", default=None)
    try:
        if action_key.endswith("create_self_maintenance_goal"):
            title = "Manter autonomia interna, memoria e calibracao de risco"
            desc = (
                "Goal criado pelo ciclo autonomo quando nenhum objetivo interno ativo existia. "
                "Usar sinais de workspace, eventos, acoes e consequencias para preservar capacidade futura de agir."
            )
            gid = _call(db, "create_goal", title, desc, 6, "open", 5, default=None)
            if gid is None:
                gid = _call(db, "upsert_goal", title, desc, 6, default=None)
            observed = f"created_goal:{gid}"
        elif action_key.endswith("trigger_reflexion_review"):
            wid = _call(
                db,
                "publish_workspace",
                module="autonomous_cognition",
                channel="reflexion.trigger",
                payload_json=_json_dumps({
                    "reason": "autonomous_recent_failure_cluster",
                    "source_action_id": action_id,
                    "evidence": (meta or {}).get("evidence", {}),
                }),
                salience=0.86,
                ttl_sec=1200,
                default=None,
            )
            observed = f"published_reflexion_trigger:{wid}"
        elif action_key.endswith("compact_workspace_focus"):
            cleaned = _call(db, "cleanup_workspace", max_items=150, default=0)
            observed = f"workspace_cleanup:{cleaned}"
        elif action_key.endswith("queue_conflict_review"):
            wid = _call(
                db,
                "publish_workspace",
                module="autonomous_cognition",
                channel="conflict.review_needed",
                payload_json=_json_dumps({
                    "reason": "autonomous_open_conflict_pressure",
                    "source_action_id": action_id,
                    "evidence": (meta or {}).get("evidence", {}),
                }),
                salience=0.80,
                ttl_sec=1800,
                default=None,
            )
            observed = f"published_conflict_review:{wid}"
        elif action_key.endswith("prioritize_action_backlog"):
            wid = _call(
                db,
                "publish_workspace",
                module="autonomous_cognition",
                channel="autonomous.action_backlog",
                payload_json=_json_dumps({
                    "reason": "queued_action_backlog",
                    "source_action_id": action_id,
                    "evidence": (meta or {}).get("evidence", {}),
                }),
                salience=0.76,
                ttl_sec=900,
                default=None,
            )
            observed = f"published_backlog_focus:{wid}"
        else:
            observed = "no_op_observe_again"

        duration_ms = int((_now() - started) * 1000)
        _call(db, "mark_action", action_id, "done", policy_allowed=True, policy_score=1.0, default=None)
        return {
            "ok": True,
            "action_id": action_id,
            "action_key": action_key,
            "expected_effect": (meta or {}).get("expected_effect"),
            "observed_effect": observed,
            "duration_ms": duration_ms,
            "risk_score": float((meta or {}).get("risk_score") or 0.0),
            "meta": meta,
        }
    except Exception as exc:
        duration_ms = int((_now() - started) * 1000)
        error = f"{type(exc).__name__}: {str(exc)[:240]}"
        _call(db, "mark_action", action_id, "error", policy_allowed=True, policy_score=0.3, last_error=error, default=None)
        return {
            "ok": False,
            "action_id": action_id,
            "action_key": action_key,
            "expected_effect": (meta or {}).get("expected_effect"),
            "observed_effect": "execution_error",
            "duration_ms": duration_ms,
            "risk_score": float((meta or {}).get("risk_score") or 0.0),
            "error": error,
            "meta": meta,
        }


def execute_one_action(
    snapshot_before: dict[str, Any],
    *,
    store_module: Any = None,
    train_world_model: bool = True,
) -> dict[str, Any]:
    """Execute one queued autonomous internal action and learn from it."""
    db = _db(store_module)
    actions = _internal_actions(db)
    if not actions:
        return {"ok": True, "executed": False, "reason": "no_autonomous_internal_action"}

    action = actions[0]
    result = _execute_internal_action(db, action)
    snapshot_after = observe_internal_state(store_module=db, publish=False)
    consequence = learn_from_consequence(
        snapshot_before,
        snapshot_after,
        result,
        store_module=db,
        train_world_model=train_world_model,
    )
    result["executed"] = True
    result["consequence"] = consequence
    _metrics["actions_executed"] += 1 if result.get("ok") else 0
    return result


def _state_for_world_model(snapshot: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "workspace_count",
        "high_salience_count",
        "unconsumed_high_salience_count",
        "queued_action_count",
        "failed_action_count",
        "active_goal_count",
        "open_conflict_count",
        "recent_error_count",
    )
    return {key: snapshot.get(key) for key in keys}


def learn_from_consequence(
    snapshot_before: dict[str, Any],
    snapshot_after: dict[str, Any],
    action_result: dict[str, Any],
    *,
    store_module: Any = None,
    train_world_model: bool = True,
) -> dict[str, Any]:
    """Record outcome as structured episode and update the local world model."""
    db = _db(store_module)
    predicted_risk = _clip01(float(action_result.get("risk_score") or 0.0))
    observed_failure = 0.0 if bool(action_result.get("ok")) else 1.0
    surprise = round(abs(predicted_risk - observed_failure), 4)
    before_state = _state_for_world_model(snapshot_before)
    after_state = _state_for_world_model(snapshot_after)
    action_key = str(action_result.get("action_key") or "unknown")

    structured = {
        "context_input": before_state,
        "granular_action": {
            "action_key": action_key,
            "action_id": action_result.get("action_id"),
            "expected_effect": action_result.get("expected_effect"),
        },
        "objective_result": {
            "ok": bool(action_result.get("ok")),
            "duration_ms": int(action_result.get("duration_ms") or 0),
            "observed_effect": action_result.get("observed_effect"),
            "error": action_result.get("error", ""),
        },
        "estimated_counterfactual": {
            "noop_expected": "risk persists without internal intervention",
            "counterfactual_delta": round(predicted_risk - observed_failure, 4),
        },
        "computed_surprise": surprise,
        "instantiated_invariant": "perceive_predict_act_learn",
        "state_after": after_state,
    }

    event_id = _call(
        db,
        "add_event",
        "autonomous_cognition_consequence",
        f"action={action_key} ok={bool(action_result.get('ok'))} surprise={surprise}",
        _json_dumps(structured),
        default=None,
    )
    episode_id = _call(
        db,
        "add_episodic_episode",
        episode_type="autonomous_cognition",
        session_id="autonomous:internal",
        source="autonomous_cognition",
        title=f"Internal loop consequence: {action_key}",
        summary=(
            f"Expected {action_result.get('expected_effect')}; observed "
            f"{action_result.get('observed_effect')}; surprise={surprise}"
        ),
        user_text="internal autonomous cycle",
        assistant_text=str(action_result.get("observed_effect") or ""),
        outcome="success" if bool(action_result.get("ok")) else "failure",
        salience=0.62 + min(0.25, surprise * 0.25),
        structured_json=_json_dumps(structured),
        refs=[{"table": "events", "id": str(event_id), "relation": "audit", "weight": 0.8}] if event_id else [],
        meta_json=_json_dumps({"action_result": action_result}),
        default=None,
    )
    if surprise >= 0.45:
        _call(
            db,
            "add_autobiographical_memory",
            text=f"[autonomous_cognition] Surpresa {surprise}: {action_key} -> {action_result.get('observed_effect')}",
            memory_type="learning",
            importance=0.70 + min(0.2, surprise * 0.2),
            decay_rate=0.01,
            content_json=_json_dumps({"episode_id": episode_id, "structured": structured}),
            default=None,
        )

    if train_world_model:
        try:
            from ultronpro import local_world_models

            local_world_models.train_local_model(
                "cognitive_architecture",
                before_state,
                action_key,
                after_state,
                "success" if bool(action_result.get("ok")) else "failure",
                {"surprise_delta": surprise, "predicted_risk": predicted_risk},
            )
        except Exception:
            pass

    _call(
        db,
        "publish_workspace",
        module="autonomous_cognition",
        channel="autonomous.consequence",
        payload_json=_json_dumps({
            "episode_id": episode_id,
            "event_id": event_id,
            "action_key": action_key,
            "surprise": surprise,
            "ok": bool(action_result.get("ok")),
        }),
        salience=0.70 + min(0.2, surprise * 0.2),
        ttl_sec=1800,
        default=None,
    )
    _metrics["consequences_learned"] += 1
    return {
        "ok": True,
        "event_id": event_id,
        "episode_id": episode_id,
        "surprise": surprise,
        "structured": structured,
    }


def tick(
    *,
    stage: str = "full",
    store_module: Any = None,
    train_world_model: bool = True,
) -> dict[str, Any]:
    """Run one autonomous cognition cycle.

    stage values:
    - perceive: observe and publish perception only;
    - deliberate: perceive, predict risks and enqueue suggestions;
    - act/full: also execute one safe internal action and learn from outcome.
    """
    stage = str(stage or "full").strip().lower()
    if stage not in {"perceive", "deliberate", "act", "full"}:
        stage = "full"
    snapshot = observe_internal_state(store_module=store_module, publish=True)
    result: dict[str, Any] = {
        "ok": True,
        "stage": stage,
        "snapshot": snapshot,
        "risks": [],
        "suggestions": [],
        "action": {"executed": False},
    }
    if stage == "perceive":
        _finish_cycle(result)
        return result

    risks = predict_risks(snapshot, store_module=store_module, publish=True)
    suggestions = suggest_actions(snapshot, risks, store_module=store_module, enqueue=True, publish=True)
    result["risks"] = risks
    result["suggestions"] = suggestions
    if stage == "deliberate":
        _finish_cycle(result)
        return result

    executed = []
    for _ in range(MAX_ACTIONS_PER_TICK):
        action_result = execute_one_action(
            snapshot,
            store_module=store_module,
            train_world_model=train_world_model,
        )
        if not action_result.get("executed"):
            break
        executed.append(action_result)
    result["action"] = executed[0] if executed else {"executed": False, "reason": "no_action_executed"}
    result["actions"] = executed
    _finish_cycle(result)
    return result


def _finish_cycle(result: dict[str, Any]) -> None:
    global _last_cycle
    _metrics["ticks"] += 1
    _metrics["last_error"] = None
    _last_cycle = result


async def _run_forever() -> None:
    global _running
    await asyncio.sleep(max(1, _env_int("ULTRON_AUTONOMOUS_COGNITION_START_DELAY_SEC", 15)))
    while _running:
        try:
            await asyncio.to_thread(tick, stage="full")
        except Exception as exc:
            _metrics["last_error"] = f"{type(exc).__name__}: {str(exc)[:240]}"
        await asyncio.sleep(INTERVAL_SEC)


def start_background_loop() -> dict[str, Any]:
    global _task, _running
    if not ENABLED:
        return {"ok": True, "started": False, "reason": "disabled"}
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return {"ok": False, "started": False, "reason": "no_running_event_loop"}
    if _task and not _task.done():
        return {"ok": True, "started": False, "reason": "already_running"}
    _running = True
    _task = loop.create_task(_run_forever())
    return {"ok": True, "started": True, "interval_sec": INTERVAL_SEC}


def stop_background_loop() -> dict[str, Any]:
    global _running
    _running = False
    if _task and not _task.done():
        _task.cancel()
        return {"ok": True, "stopped": True}
    return {"ok": True, "stopped": False, "reason": "not_running"}


def status() -> dict[str, Any]:
    return {
        "ok": True,
        "enabled": ENABLED,
        "interval_sec": INTERVAL_SEC,
        "running": bool(_task and not _task.done()),
        "metrics": dict(_metrics),
        "last_cycle": _last_cycle,
    }
