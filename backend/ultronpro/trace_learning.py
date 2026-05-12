from __future__ import annotations

import hashlib
import json
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


DATA_DIR = Path(__file__).resolve().parent.parent / "data"
TRACE_LEARNING_PATH = DATA_DIR / "trace_learning.jsonl"
TRACE_LEARNING_STATE_PATH = DATA_DIR / "trace_learning_state.json"

SIMPLE_ROUTES = {
    "translation",
    "stable_fact",
    "session_memory",
    "math",
    "basic_logic",
    "creative",
    "programming_fact",
    "language_nuance",
    "safety",
    "self_limits",
}


@dataclass(frozen=True)
class TraceLearningDecision:
    action: str
    target: str
    confidence: float
    reason: str
    patch_candidate: str
    requires_self_modification_gate: bool


def _now() -> int:
    return int(time.time())


def _safe(value: Any, limit: int = 500) -> str:
    return " ".join(str(value or "").strip().split())[:limit]


def _hash(value: Any) -> str:
    try:
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:
        raw = str(value)
    return hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()[:12]


def _read_json(path: Path) -> dict[str, Any]:
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {"ok": True, "version": 1, "updated_at": 0, "routes": {}, "actions": {}}


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = _now()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def _trace_rag_summary(trace: Any) -> dict[str, Any]:
    if not isinstance(trace, dict):
        return {"present": False}
    sources = trace.get("sources") if isinstance(trace.get("sources"), list) else []
    out = {
        "present": True,
        "rag_type": _safe(trace.get("rag_type"), 80),
        "evidence_count": int(trace.get("evidence_count") or len(sources) or 0),
        "source_count": len(sources),
        "lookup_query_hash": _hash(trace.get("lookup_query") or ""),
        "errors": [str(x)[:120] for x in (trace.get("errors") or [])[:4]] if isinstance(trace.get("errors"), list) else [],
    }
    if sources:
        out["top_sources"] = [
            {
                "source": _safe(src.get("source") or src.get("source_id"), 120) if isinstance(src, dict) else _safe(src, 120),
                "score": src.get("score") if isinstance(src, dict) else None,
                "rag_type": _safe(src.get("rag_type"), 80) if isinstance(src, dict) else "",
            }
            for src in sources[:3]
        ]
    return out


def _decision_summary(item: dict[str, Any]) -> dict[str, Any]:
    decision = item.get("route_decision") if isinstance(item.get("route_decision"), dict) else {}
    return {
        "intent": _safe(decision.get("intent") or item.get("actual_intent"), 80),
        "route": _safe(decision.get("route") or item.get("actual_route"), 80),
        "confidence": decision.get("confidence"),
        "should_use_causal": bool(decision.get("should_use_causal")),
        "reason": _safe(decision.get("reason"), 180),
    }


def _strategy_route(strategy: str) -> str:
    s = _safe(strategy, 120).lower()
    if s.startswith("pre_causal_"):
        return s.removeprefix("pre_causal_")
    if s.startswith("intent_"):
        return s.removeprefix("intent_")
    return s


def _actual_route(item: dict[str, Any]) -> str:
    route = _safe(item.get("actual_route"), 80)
    if route:
        return route
    decision = item.get("route_decision") if isinstance(item.get("route_decision"), dict) else {}
    route = _safe(decision.get("route"), 80)
    if route:
        return route
    return _strategy_route(str(item.get("actual_strategy") or ""))


def _expected_route(item: dict[str, Any]) -> str:
    return _safe(item.get("expected_route"), 80) or "unknown"


def _actual_intent(item: dict[str, Any]) -> str:
    decision = item.get("route_decision") if isinstance(item.get("route_decision"), dict) else {}
    return _safe(item.get("actual_intent") or decision.get("intent"), 80)


def _expected_intent(item: dict[str, Any]) -> str:
    return _safe(item.get("expected_intent"), 80) or "unknown"


def _is_undue_causal(item: dict[str, Any]) -> bool:
    expected = _expected_route(item)
    actual = _actual_route(item).lower()
    strategy = _safe(item.get("actual_strategy"), 160).lower()
    decision = item.get("route_decision") if isinstance(item.get("route_decision"), dict) else {}
    if expected in {"causal", "causal_reasoning"}:
        return False
    if actual in {"causal", "causal_reasoning"}:
        return True
    if bool(decision.get("should_use_causal")) and _safe(decision.get("route"), 80).lower() in {"causal", "none"}:
        return expected in SIMPLE_ROUTES
    if strategy.startswith("pre_causal_"):
        return False
    return any(marker in strategy for marker in ("causal_transfer", "causal_fallback", "active_investigation", "non_llm_causal"))


def _answer_issue_text(item: dict[str, Any]) -> str:
    issues = item.get("answer_issues") if isinstance(item.get("answer_issues"), list) else []
    return ", ".join(str(x) for x in issues[:5]) or "answer_quality"


def classify_trace_item(item: dict[str, Any]) -> TraceLearningDecision:
    expected_route = _expected_route(item)
    actual_route = _actual_route(item) or "unknown"
    expected_intent = _expected_intent(item)
    actual_intent = _actual_intent(item) or "unknown"
    route_ok = bool(item.get("route_ok"))
    answer_ok = bool(item.get("answer_ok"))
    strategy_ok = bool(item.get("strategy_ok", route_ok))

    if _is_undue_causal(item):
        return TraceLearningDecision(
            action="add_fast_path",
            target=f"route:{expected_route}",
            confidence=0.94,
            reason="causal_route_used_for_simple_expected_route",
            patch_candidate=(
                f"Add a generic fast path or local-router training example for intent '{expected_intent}' "
                f"to route '{expected_route}' before causal fallback. Do not hardcode the final answer."
            ),
            requires_self_modification_gate=True,
        )
    if route_ok and answer_ok and strategy_ok:
        return TraceLearningDecision(
            action="reinforce_competence",
            target=f"route:{expected_route}",
            confidence=0.9,
            reason="route_and_answer_validated",
            patch_candidate=(
                f"Reinforce route '{expected_route}' for intent '{expected_intent}' as a validated competence."
            ),
            requires_self_modification_gate=False,
        )
    if route_ok and not answer_ok:
        return TraceLearningDecision(
            action="improve_resolver",
            target=f"resolver:{expected_route}",
            confidence=0.86,
            reason=f"route_correct_answer_failed:{_answer_issue_text(item)}",
            patch_candidate=(
                f"Improve resolver for route '{expected_route}' and issue(s) {_answer_issue_text(item)}. "
                "Keep knowledge retrieval/tooling separate from route selection and avoid fixed answers."
            ),
            requires_self_modification_gate=True,
        )
    if not route_ok and not answer_ok:
        return TraceLearningDecision(
            action="improve_router",
            target=f"router:{expected_intent}",
            confidence=0.88,
            reason=f"wrong_route:{actual_intent}->{actual_route}; expected:{expected_intent}->{expected_route}",
            patch_candidate=(
                f"Teach the router that generic intent '{expected_intent}' should use route '{expected_route}', "
                f"not '{actual_route}'. Use generic patterns or local classifier training, not a benchmark answer."
            ),
            requires_self_modification_gate=True,
        )
    if not route_ok and answer_ok:
        return TraceLearningDecision(
            action="calibrate_router",
            target=f"router:{expected_intent}",
            confidence=0.74,
            reason=f"answer_succeeded_with_wrong_route:{actual_route}",
            patch_candidate=(
                f"Calibrate router labels for intent '{expected_intent}' so future traces report route "
                f"'{expected_route}' instead of lucky route '{actual_route}'."
            ),
            requires_self_modification_gate=True,
        )
    if route_ok and not strategy_ok:
        return TraceLearningDecision(
            action="align_strategy",
            target=f"route:{expected_route}",
            confidence=0.78,
            reason="route_label_ok_strategy_label_failed",
            patch_candidate=(
                f"Align strategy naming/contract for route '{expected_route}' so telemetry and resolver behavior match."
            ),
            requires_self_modification_gate=True,
        )
    return TraceLearningDecision(
        action="observe",
        target=f"route:{expected_route}",
        confidence=0.45,
        reason="insufficient_trace_signal",
        patch_candidate="Keep observing this trace class until enough labeled evidence exists.",
        requires_self_modification_gate=False,
    )


def _action_id(run_id: str, item: dict[str, Any], action: str) -> int:
    key = "|".join([str(run_id), _safe(item.get("case_id"), 80), _safe(item.get("prompt"), 300), action])
    return int(hashlib.sha1(key.encode("utf-8", errors="ignore")).hexdigest()[:8], 16)


def _record_route_examples(item: dict[str, Any], decision: TraceLearningDecision, *, dry_run: bool) -> list[dict[str, Any]]:
    if dry_run:
        return [{"ok": True, "dry_run": True, "kind": "route_examples"}]
    out: list[dict[str, Any]] = []
    query = _safe(item.get("prompt"), 2500)
    if not query:
        return [{"ok": False, "reason": "empty_query"}]
    expected_route = _expected_route(item)
    actual_route = _actual_route(item)
    strategy = _safe(item.get("actual_strategy"), 120)
    meta = {
        "learned_from": "trace_learning",
        "trace_learning_action": decision.action,
        "expected_intent": _expected_intent(item),
        "expected_route": expected_route,
        "actual_intent": _actual_intent(item),
        "actual_route": actual_route,
        "route_decision": _decision_summary(item),
        "trace_rag": _trace_rag_summary(item.get("trace_rag")),
        "case_id": _safe(item.get("case_id"), 120),
        "do_not_hardcode_answer": True,
    }
    try:
        from ultronpro.core.learned_intent import record_route_episode

        if decision.action in {"reinforce_competence", "improve_resolver", "align_strategy"}:
            out.append(record_route_episode(
                query,
                module=expected_route,
                strategy=strategy or f"route_{expected_route}",
                ok=True,
                latency_ms=int(item.get("latency_ms") or 0),
                source=f"trace_learning.{decision.action}",
                outcome="validated_route",
                meta=meta,
            ))
        elif decision.action in {"improve_router", "add_fast_path", "calibrate_router"}:
            if actual_route and actual_route != expected_route:
                out.append(record_route_episode(
                    query,
                    module=actual_route,
                    strategy=strategy or f"route_{actual_route}",
                    ok=False,
                    latency_ms=int(item.get("latency_ms") or 0),
                    source=f"trace_learning.{decision.action}.negative",
                    outcome="wrong_route",
                    meta=meta,
                ))
            out.append(record_route_episode(
                query,
                module=expected_route,
                strategy=f"correct_route_{expected_route}",
                ok=True,
                latency_ms=int(item.get("latency_ms") or 0),
                source=f"trace_learning.{decision.action}.positive",
                outcome="corrective_route_label",
                meta=meta,
            ))
    except Exception as exc:
        out.append({"ok": False, "error": f"{type(exc).__name__}:{str(exc)[:200]}"})
    return out


def _record_failure_episode(item: dict[str, Any], decision: TraceLearningDecision, *, run_id: str, dry_run: bool) -> dict[str, Any]:
    if decision.action in {"reinforce_competence", "observe"}:
        return {"ok": True, "skipped": True}
    episode = {
        "query": _safe(item.get("prompt"), 500),
        "action": decision.action,
        "target": decision.target,
        "correct_route": _expected_route(item),
        "predicted_route": _actual_route(item),
        "patch_candidate": decision.patch_candidate,
        "requires_self_modification_gate": decision.requires_self_modification_gate,
        "do_not_hardcode_answer": True,
    }
    if dry_run:
        return {"ok": True, "dry_run": True, "episode": episode}
    try:
        from ultronpro import episodic_memory

        episodic_memory.append_episode(
            action_id=_action_id(run_id, item, decision.action),
            kind=f"trace_learning.{decision.action}",
            text=f"run={run_id} case={_safe(item.get('case_id'), 80)}: {_safe(item.get('prompt'), 420)}",
            task_type=f"trace_learning:{_expected_route(item)}",
            strategy=_safe(item.get("actual_strategy") or _actual_route(item) or "trace_learning", 120),
            ok=False,
            latency_ms=max(1, int(item.get("latency_ms") or 1)),
            error=decision.reason,
            meta={
                **episode,
                "run_id": run_id,
                "case_id": _safe(item.get("case_id"), 120),
                "route_decision": _decision_summary(item),
                "trace_rag": _trace_rag_summary(item.get("trace_rag")),
                "answer_issues": item.get("answer_issues") if isinstance(item.get("answer_issues"), list) else [],
            },
            authorship_origin="trace_learning",
        )
        return {"ok": True, "episode": episode}
    except Exception as exc:
        return {"ok": False, "episode": episode, "error": f"{type(exc).__name__}:{str(exc)[:200]}"}


def _record_procedural_hint(item: dict[str, Any], decision: TraceLearningDecision, *, dry_run: bool) -> dict[str, Any]:
    if decision.action == "observe":
        return {"ok": True, "skipped": True}
    if dry_run:
        return {"ok": True, "dry_run": True}
    try:
        from ultronpro import episodic_memory

        heuristic = decision.patch_candidate
        if decision.action == "reinforce_competence":
            heuristic = (
                f"Validated route '{_expected_route(item)}' for intent '{_expected_intent(item)}' "
                "when the route decision and final answer both pass evaluation."
            )
        return episodic_memory.append_procedural_learning(
            task_type=f"trace_learning:{_expected_route(item)}",
            heuristic=heuristic,
            bottleneck_step=decision.action,
            outcome="validated" if decision.action == "reinforce_competence" else "needs_improvement",
            confidence=decision.confidence,
            meta={
                "source": "trace_learning",
                "case_id": _safe(item.get("case_id"), 120),
                "route_decision": _decision_summary(item),
                "trace_rag": _trace_rag_summary(item.get("trace_rag")),
                "do_not_hardcode_answer": True,
            },
        )
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}:{str(exc)[:200]}"}


def _proposal_title(action: str, route: str) -> str:
    labels = {
        "add_fast_path": "Add generic fast path",
        "improve_router": "Improve router",
        "improve_resolver": "Improve resolver",
        "calibrate_router": "Calibrate router",
        "align_strategy": "Align strategy contract",
    }
    return f"{labels.get(action, 'Improve trace policy')} for {route}"


def _append_learning_proposals(groups: dict[tuple[str, str], list[dict[str, Any]]], *, dry_run: bool) -> list[dict[str, Any]]:
    proposals: list[dict[str, Any]] = []
    for (action, route), rows in sorted(groups.items()):
        if action in {"reinforce_competence", "observe"} or not rows:
            continue
        first = rows[0]["item"]
        first_decision: TraceLearningDecision = rows[0]["decision"]
        details = {
            "action": action,
            "route": route,
            "intent": _expected_intent(first),
            "samples": [
                {
                    "case_id": _safe(row["item"].get("case_id"), 120),
                    "query": _safe(row["item"].get("prompt"), 240),
                    "actual_route": _actual_route(row["item"]),
                    "expected_route": _expected_route(row["item"]),
                    "route_decision": _decision_summary(row["item"]),
                    "trace_rag": _trace_rag_summary(row["item"].get("trace_rag")),
                }
                for row in rows[:6]
            ],
            "patch_candidate": first_decision.patch_candidate,
            "requires_self_modification_gate": first_decision.requires_self_modification_gate,
            "do_not_hardcode_answer": True,
        }
        if dry_run:
            proposals.append({"ok": True, "dry_run": True, "title": _proposal_title(action, route), "details": details})
            continue
        try:
            from ultronpro import episodic_memory

            proposals.append(episodic_memory.append_learning_proposal(
                kind=f"trace_learning.{action}",
                title=_proposal_title(action, route),
                details=details,
            ))
        except Exception as exc:
            proposals.append({"ok": False, "title": _proposal_title(action, route), "error": f"{type(exc).__name__}:{str(exc)[:200]}"})
    return proposals


def _update_state(rows: list[dict[str, Any]]) -> None:
    state = _read_json(TRACE_LEARNING_STATE_PATH)
    routes = state.setdefault("routes", {})
    actions = state.setdefault("actions", {})
    for row in rows:
        route = _safe(row.get("expected_route"), 80) or "unknown"
        action = _safe(row.get("action"), 80) or "unknown"
        r = routes.setdefault(route, {"total": 0, "actions": {}, "last_seen": 0, "recent_cases": []})
        r["total"] = int(r.get("total") or 0) + 1
        r["last_seen"] = _now()
        r_actions = r.setdefault("actions", {})
        r_actions[action] = int(r_actions.get(action) or 0) + 1
        recent = r.setdefault("recent_cases", [])
        recent.append({
            "case_id": _safe(row.get("case_id"), 120),
            "action": action,
            "prompt_hash": row.get("prompt_hash"),
            "ok": bool(row.get("ok")),
        })
        r["recent_cases"] = recent[-20:]
        a = actions.setdefault(action, {"total": 0, "routes": {}, "last_seen": 0})
        a["total"] = int(a.get("total") or 0) + 1
        a["last_seen"] = _now()
        a_routes = a.setdefault("routes", {})
        a_routes[route] = int(a_routes.get(route) or 0) + 1
    _write_json(TRACE_LEARNING_STATE_PATH, state)


def learn_from_route_eval_report(
    report: dict[str, Any],
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    run_id = _safe(report.get("run_id"), 120) or _hash(report)
    learned_rows: list[dict[str, Any]] = []
    route_records: list[dict[str, Any]] = []
    episode_records: list[dict[str, Any]] = []
    procedural_records: list[dict[str, Any]] = []
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}

    for item in report.get("items") or []:
        if not isinstance(item, dict):
            continue
        decision = classify_trace_item(item)
        row = {
            "ts": _now(),
            "run_id": run_id,
            "case_id": _safe(item.get("case_id"), 120),
            "prompt_hash": _hash(item.get("prompt")),
            "expected_intent": _expected_intent(item),
            "actual_intent": _actual_intent(item),
            "expected_route": _expected_route(item),
            "actual_route": _actual_route(item),
            "route_ok": bool(item.get("route_ok")),
            "answer_ok": bool(item.get("answer_ok")),
            "strategy_ok": bool(item.get("strategy_ok", item.get("route_ok"))),
            "ok": bool(item.get("ok")),
            "action": decision.action,
            "target": decision.target,
            "confidence": decision.confidence,
            "reason": decision.reason,
            "patch_candidate": decision.patch_candidate,
            "requires_self_modification_gate": decision.requires_self_modification_gate,
            "route_decision": _decision_summary(item),
            "trace_rag": _trace_rag_summary(item.get("trace_rag")),
            "do_not_hardcode_answer": True,
        }
        learned_rows.append(row)
        grouped.setdefault((decision.action, _expected_route(item)), []).append({"item": item, "decision": decision})
        route_records.extend(_record_route_examples(item, decision, dry_run=dry_run))
        episode_records.append(_record_failure_episode(item, decision, run_id=run_id, dry_run=dry_run))
        procedural_records.append(_record_procedural_hint(item, decision, dry_run=dry_run))
        if not dry_run:
            _append_jsonl(TRACE_LEARNING_PATH, row)

    if not dry_run and learned_rows:
        _update_state(learned_rows)
    proposals = _append_learning_proposals(grouped, dry_run=dry_run)
    actions: dict[str, int] = {}
    for row in learned_rows:
        action = str(row.get("action") or "unknown")
        actions[action] = actions.get(action, 0) + 1

    return {
        "ok": all(bool(x.get("ok", True)) for x in route_records + episode_records + procedural_records + proposals),
        "dry_run": dry_run,
        "source": "route_eval.trace",
        "run_id": run_id,
        "items": len(learned_rows),
        "actions": actions,
        "route_records": sum(1 for x in route_records if x.get("ok") and not x.get("dry_run")),
        "episodes_recorded": sum(1 for x in episode_records if x.get("ok") and not x.get("dry_run") and not x.get("skipped")),
        "procedural_records": sum(1 for x in procedural_records if x.get("ok") and not x.get("dry_run") and not x.get("skipped")),
        "learning_proposals": proposals,
        "path": str(TRACE_LEARNING_PATH),
        "state_path": str(TRACE_LEARNING_STATE_PATH),
    }


def status() -> dict[str, Any]:
    state = _read_json(TRACE_LEARNING_STATE_PATH)
    recent: list[dict[str, Any]] = []
    try:
        if TRACE_LEARNING_PATH.exists():
            lines = TRACE_LEARNING_PATH.read_text(encoding="utf-8", errors="ignore").splitlines()
            for line in lines[-20:]:
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                if isinstance(row, dict):
                    recent.append(row)
    except Exception:
        pass
    return {
        "ok": True,
        "path": str(TRACE_LEARNING_PATH),
        "state_path": str(TRACE_LEARNING_STATE_PATH),
        "routes": state.get("routes") or {},
        "actions": state.get("actions") or {},
        "recent": recent,
    }


def run_selftest() -> dict[str, Any]:
    old_trace = TRACE_LEARNING_PATH
    old_state = TRACE_LEARNING_STATE_PATH
    with tempfile.TemporaryDirectory(prefix="trace-learning-") as td:
        base = Path(td)
        globals()["TRACE_LEARNING_PATH"] = base / "trace_learning.jsonl"
        globals()["TRACE_LEARNING_STATE_PATH"] = base / "trace_learning_state.json"
        from ultronpro import episodic_memory
        from ultronpro.core import learned_intent

        old_route_path = learned_intent.ROUTE_EPISODES_PATH
        old_episode_path = episodic_memory.EPISODIC_PATH
        old_procedural_path = episodic_memory.PROCEDURAL_PATH
        old_proposal_path = episodic_memory.LEARNING_PROPOSALS_PATH
        learned_intent.ROUTE_EPISODES_PATH = base / "intent_route_episodes.jsonl"
        episodic_memory.EPISODIC_PATH = base / "episodic_memory.jsonl"
        episodic_memory.PROCEDURAL_PATH = base / "procedural_memory.jsonl"
        episodic_memory.LEARNING_PROPOSALS_PATH = base / "learning_proposals.jsonl"
        try:
            learned_intent._cached_examples.cache_clear()
        except Exception:
            pass
        try:
            report = {
                "run_id": "selftest",
                "items": [
                    {
                        "case_id": "ok_translation",
                        "prompt": "Como se diz obrigado em frances?",
                        "expected_intent": "translation",
                        "actual_intent": "translation",
                        "expected_route": "translation",
                        "actual_route": "translation",
                        "actual_strategy": "pre_causal_translation",
                        "route_ok": True,
                        "answer_ok": True,
                        "strategy_ok": True,
                        "ok": True,
                        "route_decision": {"intent": "translation", "route": "translation", "confidence": 0.9, "should_use_causal": False},
                    },
                    {
                        "case_id": "bad_resolver",
                        "prompt": "Quem escreveu Dom Casmurro?",
                        "expected_intent": "stable_fact",
                        "actual_intent": "stable_fact",
                        "expected_route": "stable_fact",
                        "actual_route": "stable_fact",
                        "actual_strategy": "pre_causal_stable_fact",
                        "route_ok": True,
                        "answer_ok": False,
                        "strategy_ok": True,
                        "ok": False,
                        "answer_issues": ["missing_trace_rag"],
                        "route_decision": {"intent": "stable_fact", "route": "stable_fact", "confidence": 0.86, "should_use_causal": False},
                        "trace_rag": {"rag_type": "rag_facts", "evidence_count": 0, "sources": []},
                    },
                    {
                        "case_id": "causal_indev",
                        "prompt": "Quanto e raiz quadrada de 144 dividida por 2?",
                        "expected_intent": "math_expression",
                        "actual_intent": "causal_reasoning",
                        "expected_route": "math",
                        "actual_route": "causal",
                        "actual_strategy": "causal_transfer_engine",
                        "route_ok": False,
                        "answer_ok": False,
                        "strategy_ok": False,
                        "ok": False,
                        "route_decision": {"intent": "open_chat", "route": "none", "confidence": 0.35, "should_use_causal": True},
                    },
                ],
            }
            out = learn_from_route_eval_report(report, dry_run=False)
            st = status()
            actions = out.get("actions") or {}
            return {
                "ok": (
                    out.get("items") == 3
                    and actions.get("reinforce_competence") == 1
                    and actions.get("improve_resolver") == 1
                    and actions.get("add_fast_path") == 1
                    and out.get("route_records") == 4
                    and out.get("episodes_recorded") == 2
                    and out.get("procedural_records") == 3
                    and len(out.get("learning_proposals") or []) == 2
                    and (st.get("actions") or {}).get("reinforce_competence", {}).get("total") == 1
                    and TRACE_LEARNING_PATH.exists()
                    and learned_intent.ROUTE_EPISODES_PATH.exists()
                    and episodic_memory.PROCEDURAL_PATH.exists()
                    and episodic_memory.LEARNING_PROPOSALS_PATH.exists()
                ),
                "result": out,
                "status": st,
            }
        finally:
            globals()["TRACE_LEARNING_PATH"] = old_trace
            globals()["TRACE_LEARNING_STATE_PATH"] = old_state
            learned_intent.ROUTE_EPISODES_PATH = old_route_path
            episodic_memory.EPISODIC_PATH = old_episode_path
            episodic_memory.PROCEDURAL_PATH = old_procedural_path
            episodic_memory.LEARNING_PROPOSALS_PATH = old_proposal_path
            try:
                learned_intent._cached_examples.cache_clear()
            except Exception:
                pass
