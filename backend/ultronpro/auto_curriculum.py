from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any


DATA_DIR = Path(__file__).resolve().parent.parent / "data"
CURRICULUM_LOG_PATH = DATA_DIR / "auto_curriculum.jsonl"
CURRICULUM_STATE_PATH = DATA_DIR / "auto_curriculum_state.json"


DIFFICULTY_LADDER = [
    {
        "level": 1,
        "name": "near_transfer",
        "goal": "small variation of a task the system already almost solves",
    },
    {
        "level": 2,
        "name": "controlled_variation",
        "goal": "change one premise or missing slot while preserving the domain",
    },
    {
        "level": 3,
        "name": "causal_intervention",
        "goal": "execute the active experiment that should close the gap",
    },
    {
        "level": 4,
        "name": "zero_shot_bridge",
        "goal": "transfer the skill to an adjacent but unseen domain",
    },
    {
        "level": 5,
        "name": "novel_domain",
        "goal": "force a new domain with explicit external or sandbox validation",
    },
]


def _now() -> int:
    return int(time.time())


def _clip(value: Any, n: int = 320) -> str:
    text = " ".join(str(value or "").split())
    return text[: max(1, int(n or 1))]


def _stable_id(prefix: str, material: Any) -> str:
    try:
        raw = json.dumps(material, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:
        raw = str(material)
    return f"{prefix}_{hashlib.sha256(raw.encode('utf-8', errors='ignore')).hexdigest()[:12]}"


def _read_json(path: Path, default: Any = None) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        pass
    return default


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    except Exception:
        pass


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass


def _difficulty_meta(level: int) -> dict[str, Any]:
    for item in DIFFICULTY_LADDER:
        if int(item["level"]) == int(level):
            return dict(item)
    return dict(DIFFICULTY_LADDER[-1])


def _adjacent_domain(domain: str) -> str:
    d = str(domain or "general").lower()
    if "causal" in d:
        return "counterfactual_transfer"
    if "runtime" in d or "ops" in d or "operation" in d:
        return "provider_resilience"
    if "episod" in d or "memory" in d:
        return "memory_reconstruction"
    if "fact" in d or "language" in d:
        return "external_factual_validation"
    if "visual" in d or "arc" in d:
        return "spurious_visual_causality"
    return f"{d}_zero_shot_bridge"


def _normalize_investigation(report: dict[str, Any]) -> dict[str, Any]:
    next_exp = report.get("next_experiment") if isinstance(report.get("next_experiment"), dict) else {}
    coverage = report.get("coverage") if isinstance(report.get("coverage"), dict) else {}
    missing = report.get("missing_slots") if isinstance(report.get("missing_slots"), list) else []
    priority = 1.0 - float(coverage.get("score") or 0.0)
    priority += min(0.5, len(missing) * 0.12)
    return {
        "source_type": "active_investigation",
        "source_id": str(report.get("investigation_id") or _stable_id("inv", report)),
        "domain": str(report.get("task_type") or next_exp.get("target_route") or "unknown"),
        "query": _clip(report.get("query"), 500),
        "gap_summary": _clip(report.get("reason") or "active investigation needs experiment", 240),
        "missing_slots": [str(x) for x in missing if str(x).strip()],
        "next_experiment": next_exp,
        "priority": round(max(0.05, min(1.5, priority)), 4),
    }


def _normalize_discovery(proposal: Any) -> dict[str, Any]:
    if hasattr(proposal, "__dict__"):
        raw = dict(proposal.__dict__)
    elif isinstance(proposal, dict):
        raw = dict(proposal)
    else:
        raw = {"description": str(proposal)}
    priority = float(raw.get("expected_information_gain") or 0.35)
    return {
        "source_type": "active_discovery",
        "source_id": _stable_id("disc", raw),
        "domain": str(raw.get("domain_family") or "causal_world_model"),
        "query": _clip(raw.get("description") or raw.get("hypothesis") or "causal ambiguity", 500),
        "gap_summary": _clip(raw.get("hypothesis") or "causal ambiguity requires intervention", 300),
        "missing_slots": ["confounder_disambiguation"],
        "next_experiment": {
            "kind": "causal_intervention",
            "target_route": raw.get("domain_family") or "causal_world_model",
            "action": raw.get("action") or "run active discovery intervention",
            "target_state": raw.get("target_state") if isinstance(raw.get("target_state"), dict) else {},
            "acceptance": "outcome must distinguish causal feature from confounder",
        },
        "priority": round(max(0.05, min(1.5, priority)), 4),
    }


def collect_gap_sources(*, limit: int = 8, include_active_discovery: bool = True) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    try:
        from ultronpro import active_investigation

        for report in active_investigation.pending_experiments(limit=max(1, int(limit or 1))):
            if isinstance(report, dict):
                sources.append(_normalize_investigation(report))
    except Exception:
        pass

    if include_active_discovery and len(sources) < max(1, int(limit or 1)):
        try:
            from ultronpro import active_discovery

            proposals = active_discovery.ActiveDiscoveryEngine().scan_causal_ambiguity()
            for proposal in proposals[: max(0, int(limit or 1) - len(sources))]:
                sources.append(_normalize_discovery(proposal))
        except Exception:
            pass

    if not sources:
        sources.append(
            {
                "source_type": "bootstrap",
                "source_id": "bootstrap_generalization",
                "domain": "generalization",
                "query": "bootstrap curriculum from self-observed uncertainty",
                "gap_summary": "no pending active investigations were available",
                "missing_slots": ["fresh_gap_source"],
                "next_experiment": {
                    "kind": "coverage_refinement",
                    "target_route": "generalization",
                    "action": "seed a small verified probe before expanding difficulty",
                    "acceptance": "task must produce an auditable score",
                },
                "priority": 0.25,
            }
        )

    dedup: dict[str, dict[str, Any]] = {}
    for source in sources:
        dedup[source["source_id"]] = source
    ordered = sorted(dedup.values(), key=lambda x: float(x.get("priority") or 0.0), reverse=True)
    return ordered[: max(1, int(limit or 1))]


def _task(source: dict[str, Any], level: int, title: str, objective: str, acceptance: str, *, prereq: str | None = None) -> dict[str, Any]:
    meta = _difficulty_meta(level)
    material = {
        "source_id": source.get("source_id"),
        "level": level,
        "title": title,
        "objective": objective,
    }
    return {
        "task_id": _stable_id("curtask", material),
        "source_id": source.get("source_id"),
        "source_type": source.get("source_type"),
        "domain": source.get("domain"),
        "difficulty": level,
        "stage": meta["name"],
        "stage_goal": meta["goal"],
        "title": _clip(title, 180),
        "objective": _clip(objective, 650),
        "acceptance": _clip(acceptance, 420),
        "missing_slots": list(source.get("missing_slots") or []),
        "prerequisite_task_id": prereq,
        "status": "pending",
        "self_relative": True,
        "created_at": _now(),
    }


def _tasks_for_source(source: dict[str, Any]) -> list[dict[str, Any]]:
    domain = str(source.get("domain") or "general")
    query = source.get("query") or source.get("gap_summary") or "unknown gap"
    missing = ", ".join(source.get("missing_slots") or ["unknown"])
    next_exp = source.get("next_experiment") if isinstance(source.get("next_experiment"), dict) else {}
    action = next_exp.get("action") or "execute a bounded validation probe"
    acceptance = next_exp.get("acceptance") or "result must be scored and auditable"

    t1 = _task(
        source,
        1,
        f"Warm start variation for {domain}",
        f"Restate and solve a close variant of the known gap: {query}. Keep only one missing slot active: {missing}.",
        "success score >= 0.70 and no new anchor failure",
    )
    t2 = _task(
        source,
        2,
        f"Controlled variation for {domain}",
        f"Change one premise or missing slot from the original gap while preserving domain {domain}. Missing slots: {missing}.",
        "the system must explain which premise changed and preserve performance >= level 1 - 0.05",
        prereq=t1["task_id"],
    )
    t3 = _task(
        source,
        3,
        f"Active experiment for {domain}",
        f"Run the proposed active experiment: {action}.",
        acceptance,
        prereq=t2["task_id"],
    )
    adjacent = _adjacent_domain(domain)
    t4 = _task(
        source,
        4,
        f"Zero-shot bridge from {domain} to {adjacent}",
        f"Transfer the learned procedure from {domain} into unseen domain {adjacent} without using stored examples from that domain.",
        "zero-shot score >= 0.60 or a precise new active investigation is opened",
        prereq=t3["task_id"],
    )
    t5 = _task(
        source,
        5,
        f"Novel-domain stress task for {adjacent}",
        f"Create a novel task in {adjacent}, require external or sandbox validation, and compare expected vs observed outcome.",
        "the task must record surprise, validation evidence, and a pass/fail score",
        prereq=t4["task_id"],
    )
    return [t1, t2, t3, t4, t5]


def generate_curriculum(
    *,
    limit: int = 12,
    sources: list[dict[str, Any]] | None = None,
    include_active_discovery: bool = True,
    persist: bool = True,
) -> dict[str, Any]:
    source_rows = sources or collect_gap_sources(limit=max(1, int(limit or 1)), include_active_discovery=include_active_discovery)
    normalized = []
    for item in source_rows:
        if not isinstance(item, dict):
            continue
        if item.get("source_type") == "active_investigation":
            normalized.append(item if item.get("source_id") else _normalize_investigation(item))
        elif item.get("source_type") == "active_discovery":
            normalized.append(item if item.get("source_id") else _normalize_discovery(item))
        else:
            normalized.append(
                {
                    "source_type": str(item.get("source_type") or "manual_gap"),
                    "source_id": str(item.get("source_id") or _stable_id("gap", item)),
                    "domain": str(item.get("domain") or item.get("task_type") or "general"),
                    "query": _clip(item.get("query") or item.get("gap_summary") or item.get("label") or "manual gap"),
                    "gap_summary": _clip(item.get("gap_summary") or item.get("reason") or "manual gap"),
                    "missing_slots": list(item.get("missing_slots") or []),
                    "next_experiment": item.get("next_experiment") if isinstance(item.get("next_experiment"), dict) else {},
                    "priority": float(item.get("priority") or 0.5),
                }
            )

    tasks: list[dict[str, Any]] = []
    for source in sorted(normalized, key=lambda x: float(x.get("priority") or 0.0), reverse=True):
        tasks.extend(_tasks_for_source(source))

    tasks.sort(key=lambda task: (int(task.get("difficulty") or 0), -float(next((s.get("priority") for s in normalized if s.get("source_id") == task.get("source_id")), 0.0))))
    tasks = tasks[: max(1, int(limit or 1))]
    curriculum = {
        "ok": True,
        "curriculum_id": _stable_id("curriculum", {"ts_bucket": _now() // 60, "sources": [s.get("source_id") for s in normalized]}),
        "ts": _now(),
        "source_count": len(normalized),
        "task_count": len(tasks),
        "difficulty_ladder": DIFFICULTY_LADDER,
        "sources": normalized,
        "tasks": tasks,
        "progression": [int(t.get("difficulty") or 0) for t in tasks],
    }
    if persist:
        _write_json(CURRICULUM_STATE_PATH, curriculum)
        _append_jsonl(CURRICULUM_LOG_PATH, curriculum)
    return curriculum


def next_tasks(*, limit: int = 5, max_difficulty: int | None = None) -> dict[str, Any]:
    state = _read_json(CURRICULUM_STATE_PATH, {})
    tasks = state.get("tasks") if isinstance(state, dict) and isinstance(state.get("tasks"), list) else []
    out = []
    for task in tasks:
        if str(task.get("status") or "pending") != "pending":
            continue
        if max_difficulty is not None and int(task.get("difficulty") or 0) > int(max_difficulty):
            continue
        out.append(task)
        if len(out) >= max(1, int(limit or 1)):
            break
    return {
        "ok": True,
        "curriculum_id": state.get("curriculum_id") if isinstance(state, dict) else None,
        "count": len(out),
        "tasks": out,
    }


def record_task_result(task_id: str, *, success: bool, score: float, evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    state = _read_json(CURRICULUM_STATE_PATH, {})
    if not isinstance(state, dict) or not isinstance(state.get("tasks"), list):
        return {"ok": False, "error": "no_curriculum_state"}
    found = None
    for task in state["tasks"]:
        if str(task.get("task_id") or "") == str(task_id):
            found = task
            break
    if not found:
        return {"ok": False, "error": "task_not_found", "task_id": task_id}
    found["status"] = "passed" if success else "failed"
    found["last_score"] = round(max(0.0, min(1.0, float(score or 0.0))), 4)
    found["completed_at"] = _now()
    found["evidence"] = evidence or {}
    state.setdefault("results", []).append(
        {
            "ts": _now(),
            "task_id": task_id,
            "success": bool(success),
            "score": found["last_score"],
            "evidence": evidence or {},
        }
    )
    _write_json(CURRICULUM_STATE_PATH, state)
    _append_jsonl(CURRICULUM_LOG_PATH, {"event": "task_result", **state["results"][-1]})
    return {"ok": True, "task_id": task_id, "status": found["status"], "score": found["last_score"]}


def status() -> dict[str, Any]:
    state = _read_json(CURRICULUM_STATE_PATH, {})
    if not isinstance(state, dict) or not state:
        return {"ok": True, "has_curriculum": False, "task_count": 0}
    tasks = state.get("tasks") if isinstance(state.get("tasks"), list) else []
    return {
        "ok": True,
        "has_curriculum": True,
        "curriculum_id": state.get("curriculum_id"),
        "source_count": state.get("source_count"),
        "task_count": len(tasks),
        "pending": sum(1 for t in tasks if str(t.get("status") or "pending") == "pending"),
        "passed": sum(1 for t in tasks if str(t.get("status") or "") == "passed"),
        "failed": sum(1 for t in tasks if str(t.get("status") or "") == "failed"),
        "max_difficulty": max([int(t.get("difficulty") or 0) for t in tasks] or [0]),
    }
