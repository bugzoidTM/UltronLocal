from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any


DATA_DIR = Path(__file__).resolve().parent.parent / "data"
FIRST_MILESTONE_PATH = DATA_DIR / "first_self_learned_answer_milestone.json"
MILESTONE_LOG_PATH = DATA_DIR / "self_learning_milestones.jsonl"


def _now() -> int:
    return int(time.time())


def _ts_label(ts: Any) -> str:
    try:
        return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(float(ts)))
    except Exception:
        return ""


def _clip(value: Any, limit: int = 600) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[: max(1, int(limit))]


def _tokens(value: Any) -> set[str]:
    return set(re.findall(r"[a-zA-ZÀ-ÿ0-9_]{3,}", str(value or "").lower()))


def _similarity(a: Any, b: Any) -> float:
    ta = _tokens(a)
    tb = _tokens(b)
    if not ta or not tb:
        return 0.0
    return round(len(ta & tb) / max(1, len(ta | tb)), 4)


def _read_json(path: Path, default: Any = None) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        pass
    return default


def _read_jsonl(path: Path, limit: int = 500) -> list[dict[str, Any]]:
    try:
        if not path.exists():
            return []
        lines = [ln for ln in path.read_text(encoding="utf-8", errors="ignore").splitlines() if ln.strip()]
    except Exception:
        return []
    out: list[dict[str, Any]] = []
    for line in lines[-max(1, int(limit or 1)) :]:
        try:
            row = json.loads(line)
        except Exception:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")


def _candidate_sections(candidate: Any) -> dict[str, Any]:
    sections = getattr(candidate, "sections", None)
    return sections if isinstance(sections, dict) else {}


def _active_investigation_edges(candidate: Any) -> list[dict[str, Any]]:
    sections = _candidate_sections(candidate)
    edges = sections.get("causal") if isinstance(sections.get("causal"), list) else []
    out: list[dict[str, Any]] = []
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        sources = edge.get("sources") if isinstance(edge.get("sources"), list) else []
        evidence = edge.get("last_evidence") if isinstance(edge.get("last_evidence"), dict) else {}
        if "active_investigation_executor" in sources or evidence.get("investigation"):
            out.append(edge)
    return out


def _investigation_id_from_edge(edge: dict[str, Any]) -> str:
    evidence = edge.get("last_evidence") if isinstance(edge.get("last_evidence"), dict) else {}
    inv = evidence.get("investigation") if isinstance(evidence.get("investigation"), dict) else {}
    inv_id = str(inv.get("investigation_id") or "").strip()
    if inv_id:
        return inv_id
    cond = str(edge.get("condition") or "")
    match = re.search(r"(inv_[a-zA-Z0-9_]+)", cond)
    return match.group(1) if match else ""


def _execution_query(row: dict[str, Any]) -> str:
    if row.get("query"):
        return str(row.get("query") or "")
    evidence = row.get("causal_graph") if isinstance(row.get("causal_graph"), dict) else {}
    edge = evidence.get("edge") if isinstance(evidence.get("edge"), dict) else {}
    last = edge.get("last_evidence") if isinstance(edge.get("last_evidence"), dict) else {}
    inv = last.get("investigation") if isinstance(last.get("investigation"), dict) else {}
    return str(inv.get("query") or "")


def _find_execution(inv_id: str, query: str) -> dict[str, Any]:
    try:
        from ultronpro import active_investigation

        path = active_investigation.INVESTIGATION_EXECUTION_LOG_PATH
    except Exception:
        path = DATA_DIR / "active_investigation_executions.jsonl"
    rows = list(reversed(_read_jsonl(path, limit=1000)))
    for row in rows:
        if inv_id and str(row.get("investigation_id") or "") == inv_id and row.get("ok") and row.get("injected"):
            return row
    best: tuple[float, dict[str, Any]] = (0.0, {})
    for row in rows:
        if not (row.get("ok") and row.get("injected")):
            continue
        sim = _similarity(query, _execution_query(row))
        if sim > best[0]:
            best = (sim, row)
    return best[1] if best[0] >= 0.55 else {}


def _find_investigation_report(inv_id: str) -> dict[str, Any]:
    try:
        from ultronpro import active_investigation

        state_path = active_investigation.INVESTIGATION_STATE_PATH
        log_path = active_investigation.INVESTIGATION_LOG_PATH
    except Exception:
        state_path = DATA_DIR / "active_investigation_state.json"
        log_path = DATA_DIR / "active_investigations.jsonl"

    state = _read_json(state_path, {})
    if isinstance(state, dict) and str(state.get("investigation_id") or "") == inv_id:
        return state
    for row in reversed(_read_jsonl(log_path, limit=1000)):
        if str(row.get("investigation_id") or "") == inv_id:
            return row
    return {}


def _edge_audit(edge: dict[str, Any]) -> dict[str, Any]:
    return {
        "score": edge.get("score"),
        "cause": edge.get("cause"),
        "effect": edge.get("effect"),
        "condition": edge.get("condition"),
        "confidence": edge.get("confidence"),
        "severity": edge.get("severity"),
        "support": edge.get("support"),
        "knowledge_type": edge.get("knowledge_type"),
        "sources": edge.get("sources") if isinstance(edge.get("sources"), list) else [],
        "updated_at": edge.get("updated_at"),
        "last_evidence": edge.get("last_evidence") if isinstance(edge.get("last_evidence"), dict) else {},
    }


def maybe_record_first_self_learned_answer(query: str, response: dict[str, Any], candidate: Any) -> dict[str, Any]:
    """Record the first verified UNKNOWN -> sleep experiment -> grounded answer transition."""
    if not (isinstance(response, dict) and response.get("resolved")):
        return {"ok": True, "recorded": False, "reason": "response_not_resolved"}
    if str(response.get("module") or "") != "symbolic_causal":
        return {"ok": True, "recorded": False, "reason": "response_not_symbolic_causal"}

    edges = _active_investigation_edges(candidate)
    if not edges:
        return {"ok": True, "recorded": False, "reason": "no_active_investigation_edge_used"}

    if FIRST_MILESTONE_PATH.exists():
        previous = _read_json(FIRST_MILESTONE_PATH, {})
        return {
            "ok": True,
            "recorded": False,
            "reason": "first_milestone_already_recorded",
            "milestone_id": previous.get("id") if isinstance(previous, dict) else None,
        }

    edge = edges[0]
    inv_id = _investigation_id_from_edge(edge)
    execution = _find_execution(inv_id, query)
    if not execution:
        return {"ok": True, "recorded": False, "reason": "matching_execution_not_found"}

    original_query = _execution_query(execution)
    sim = _similarity(query, original_query)
    if sim < 0.55:
        return {"ok": True, "recorded": False, "reason": "query_not_same_enough", "similarity": sim}

    if not inv_id:
        inv_id = str(execution.get("investigation_id") or "")
    initial = _find_investigation_report(inv_id)
    ts = _now()
    milestone_id = "ms_self_learned_" + hashlib.sha256(
        f"{inv_id}|{original_query}|{query}|{ts}".encode("utf-8")
    ).hexdigest()[:12]

    milestone = {
        "ok": True,
        "id": milestone_id,
        "type": "first_self_learned_grounded_answer",
        "ts": ts,
        "timestamp_local": _ts_label(ts),
        "claim": "Uma pergunta sem cobertura interna foi registrada como UNKNOWN, consumida por experimento noturno sandboxado e depois respondida com evidencia causal interna.",
        "human_teaching_detected": False,
        "verification": {
            "prior_unknown_status": initial.get("status"),
            "prior_missing_slots": initial.get("missing_slots") if isinstance(initial.get("missing_slots"), list) else [],
            "sandbox_ok": bool((execution.get("sandbox") or {}).get("ok")) if isinstance(execution.get("sandbox"), dict) else False,
            "causal_injected": bool(execution.get("ok") and execution.get("injected")),
            "answer_module": response.get("module"),
            "answer_strategy": response.get("strategy"),
            "same_question_similarity": sim,
            "active_investigation_source_used": True,
        },
        "audit_trail": {
            "initial_unknown": {
                "ts": initial.get("ts"),
                "timestamp_local": _ts_label(initial.get("ts")),
                "investigation_id": inv_id,
                "query": initial.get("query") or original_query,
                "reason": initial.get("reason"),
                "coverage": initial.get("coverage"),
                "missing_slots": initial.get("missing_slots"),
                "next_experiment": initial.get("next_experiment"),
                "answer": _clip(initial.get("answer"), 1200),
            },
            "nightly_experiment": {
                "ts": execution.get("ts"),
                "timestamp_local": _ts_label(execution.get("ts")),
                "investigation_id": execution.get("investigation_id"),
                "query": original_query,
                "reason": execution.get("reason"),
                "missing_slots": execution.get("missing_slots"),
                "experiment": execution.get("experiment"),
                "sandbox": execution.get("sandbox"),
                "experiment_result": execution.get("experiment_result"),
                "causal_graph": execution.get("causal_graph"),
                "duration_ms": execution.get("duration_ms"),
            },
            "grounded_answer": {
                "ts": ts,
                "timestamp_local": _ts_label(ts),
                "query": query,
                "answer": _clip(response.get("answer"), 2000),
                "module": response.get("module"),
                "strategy": response.get("strategy"),
                "confidence": response.get("confidence"),
                "evidence_summary": response.get("evidence_summary"),
                "causal_edges_used": [_edge_audit(item) for item in edges[:4]],
            },
        },
    }

    _write_json(FIRST_MILESTONE_PATH, milestone)
    _append_jsonl(MILESTONE_LOG_PATH, milestone)
    try:
        from ultronpro import store

        store.db.add_event("self_learning_milestone", f"first_self_learned_grounded_answer id={milestone_id} inv={inv_id}")
        try:
            store.publish_workspace(
                module="coverage_milestone",
                channel="identity.milestone",
                payload_json=json.dumps(milestone, ensure_ascii=False, default=str),
                salience=0.95,
                ttl_sec=86400,
            )
        except Exception:
            pass
    except Exception:
        pass
    return {"ok": True, "recorded": True, "milestone_id": milestone_id, "path": str(FIRST_MILESTONE_PATH)}
