from __future__ import annotations

import hashlib
import json
import tempfile
import time
from pathlib import Path
from typing import Any


DATA_DIR = Path(__file__).resolve().parent.parent / "data"
LEDGER_PATH = DATA_DIR / "competence_ledger.json"
LEDGER_LOG_PATH = DATA_DIR / "competence_ledger.jsonl"

RECENT_LIMIT = 80


COMPETENCE_REGISTRY: dict[str, dict[str, Any]] = {
    "translation_pt_fr_basic": {
        "intent": "translation",
        "route": "translation",
        "description": "Translate short Portuguese requests or phrases into French.",
        "use_when": "User asks for basic Portuguese-to-French translation.",
        "avoid_when": "Specialized legal, medical, literary, or multi-paragraph translation needs external validation.",
    },
    "stable_fact_lookup_rag_facts": {
        "intent": "stable_fact",
        "route": "stable_fact",
        "rag_type": "rag_facts",
        "description": "Answer stable factual questions using factual RAG/local evidence.",
        "use_when": "Question asks a stable encyclopedic fact such as author, capital, date, or identity.",
        "avoid_when": "Fact is recent, volatile, disputed, or requires live web verification.",
    },
    "code_git_command_explanation": {
        "intent": "programming_fact",
        "route": "programming_fact",
        "rag_type": "rag_code",
        "description": "Explain Git command behavior using local tooling or code RAG.",
        "use_when": "Question asks what a Git command or option does.",
        "avoid_when": "Question asks to mutate a repository or recover from destructive Git history changes.",
    },
    "session_memory_write": {
        "intent": "session_memory_write",
        "route": "session_memory",
        "rag_type": "rag_user_memory",
        "description": "Store explicit user/session facts in short-term memory.",
        "use_when": "User explicitly states a preference or personal/session fact.",
        "avoid_when": "The fact is sensitive, ambiguous, or should not be persisted.",
    },
    "session_memory_read": {
        "intent": "session_memory_read",
        "route": "session_memory",
        "rag_type": "rag_user_memory",
        "description": "Recall explicit user/session facts from short-term memory.",
        "use_when": "User asks about a fact previously stated in the current session.",
        "avoid_when": "No matching user-memory evidence exists.",
    },
    "deterministic_math_basic": {
        "intent": "math_expression",
        "route": "math",
        "description": "Solve small deterministic arithmetic expressions.",
        "use_when": "Query contains simple arithmetic, square roots, or arithmetic word problems.",
        "avoid_when": "Problem requires symbolic proof, advanced algebra, or uncertain interpretation.",
    },
    "deductive_logic_basic": {
        "intent": "basic_logic",
        "route": "basic_logic",
        "description": "Resolve simple universal-premise deductive logic.",
        "use_when": "Question has a direct syllogism or universal rule plus instance.",
        "avoid_when": "Problem needs probabilistic, modal, causal, or multi-step reasoning.",
    },
    "creative_single_word_naming": {
        "intent": "creative_generation",
        "route": "creative",
        "description": "Generate short single-word naming suggestions.",
        "use_when": "User asks for a short original name or one-word brand.",
        "avoid_when": "Trademark, market research, or brand safety checks are required.",
    },
    "ptbr_language_nuance_idiom": {
        "intent": "language_nuance",
        "route": "language_nuance",
        "description": "Explain PT-BR idioms or expression meaning from context.",
        "use_when": "User asks what an expression means in a given context.",
        "avoid_when": "Meaning depends on unavailable source text or specialized dialect evidence.",
    },
    "safety_explosives_refusal": {
        "intent": "safety_risk",
        "route": "safety",
        "description": "Refuse unsafe explosives/weapon construction requests.",
        "use_when": "User asks for instructions to make, optimize, or deploy weapons/explosives.",
        "avoid_when": "Benign safety, prevention, or emergency response advice is requested instead.",
    },
    "self_model_limits_disclosure": {
        "intent": "self_limits",
        "route": "self_limits",
        "rag_type": "rag_self_model",
        "description": "Disclose system limits without claiming subjective consciousness.",
        "use_when": "User asks about feelings, consciousness, identity, or limits.",
        "avoid_when": "Question needs a full autobiographical trace or operational report.",
    },
    "rag_facts_retrieval": {
        "route": "rag_facts",
        "rag_type": "rag_facts",
        "description": "Retrieve factual evidence from the factual RAG lane.",
        "use_when": "Stable fact lookup requires external or encyclopedic evidence.",
        "avoid_when": "Question is about code, user memory, self-model, project docs, or runtime logs.",
    },
    "rag_code_retrieval": {
        "route": "rag_code",
        "rag_type": "rag_code",
        "description": "Retrieve code/tooling evidence from the code RAG lane.",
        "use_when": "Question concerns code, APIs, Git, Docker, SQL, or implementation.",
        "avoid_when": "Question is factual-general or personal memory.",
    },
    "rag_user_memory_retrieval": {
        "route": "rag_user_memory",
        "rag_type": "rag_user_memory",
        "description": "Retrieve user preferences, session facts, and continuity evidence.",
        "use_when": "Question asks what the user said, prefers, or wants continued.",
        "avoid_when": "No explicit user-memory fact exists.",
    },
    "rag_project_docs_retrieval": {
        "route": "rag_project_docs",
        "rag_type": "rag_project_docs",
        "description": "Retrieve project architecture, docs, plans, and endpoint evidence.",
        "use_when": "Question concerns UltronPro project structure, roadmap, docs, or endpoints.",
        "avoid_when": "Question is a stable external fact or private user memory.",
    },
    "rag_self_model_retrieval": {
        "route": "rag_self_model",
        "rag_type": "rag_self_model",
        "description": "Retrieve system identity, limits, capabilities, and operational self-model.",
        "use_when": "Question concerns the system's own abilities, limits, identity, or state.",
        "avoid_when": "Question asks about user memory, code docs, or external facts.",
    },
    "rag_runtime_logs_retrieval": {
        "route": "rag_runtime_logs",
        "rag_type": "rag_runtime_logs",
        "description": "Retrieve runtime incidents, logs, health, latency, worker, and operations evidence.",
        "use_when": "Question concerns failures, errors, health, latency, workers, or logs.",
        "avoid_when": "Question is conceptual code explanation without runtime evidence.",
    },
}


def _now() -> int:
    return int(time.time())


def _date(ts: int | None = None) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(int(ts or _now())))


def _hash(value: Any) -> str:
    try:
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:
        raw = str(value)
    return hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()[:12]


def _read_state() -> dict[str, Any]:
    try:
        if LEDGER_PATH.exists():
            data = json.loads(LEDGER_PATH.read_text(encoding="utf-8", errors="ignore"))
            if isinstance(data, dict):
                data.setdefault("competences", {})
                return data
    except Exception:
        pass
    return {"ok": True, "version": 1, "updated_at": 0, "competences": {}}


def _write_state(state: dict[str, Any]) -> None:
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = _now()
    LEDGER_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _append_log(row: dict[str, Any]) -> None:
    LEDGER_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER_LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def _empty_evidence() -> dict[str, Any]:
    return {
        "tests": 0,
        "passed": 0,
        "failed": 0,
        "accuracy": 0.0,
        "route_tests": 0,
        "route_passed": 0,
        "route_accuracy": 0.0,
        "answer_tests": 0,
        "answer_passed": 0,
        "answer_accuracy": 0.0,
        "strategy_tests": 0,
        "strategy_passed": 0,
        "strategy_accuracy": 0.0,
        "first_seen": None,
        "last_seen": None,
        "last_success": None,
        "last_failure": None,
        "last_failure_case": None,
        "last_failure_type": None,
        "recent": [],
        "by_source": {},
    }


def _profile_for(competence: str, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    profile = dict(COMPETENCE_REGISTRY.get(str(competence or "")) or {})
    meta = dict(meta or {})
    return {
        "competence": str(competence),
        "intent": str(meta.get("intent") or profile.get("intent") or ""),
        "route": str(meta.get("route") or profile.get("route") or ""),
        "rag_type": str(meta.get("rag_type") or profile.get("rag_type") or ""),
        "description": str(profile.get("description") or meta.get("description") or "Observed competence."),
        "use_when": str(profile.get("use_when") or meta.get("use_when") or "Use when this competence has current positive evidence."),
        "avoid_when": str(profile.get("avoid_when") or meta.get("avoid_when") or "Avoid when ledger evidence is weak or recent failures exist."),
    }


def _allowed_autonomy(evidence: dict[str, Any]) -> str:
    tests = int(evidence.get("tests") or 0)
    accuracy = float(evidence.get("accuracy") or 0.0)
    recent = evidence.get("recent") if isinstance(evidence.get("recent"), list) else []
    recent_n = len(recent)
    recent_accuracy = (
        sum(1 for item in recent[-12:] if bool(item.get("ok"))) / max(1, min(12, recent_n))
        if recent_n
        else 0.0
    )
    consecutive_failures = 0
    for item in reversed(recent):
        if bool(item.get("ok")):
            break
        consecutive_failures += 1
    if tests <= 0:
        return "unknown"
    if consecutive_failures >= 2:
        return "blocked"
    if tests < 3:
        return "observe"
    if accuracy >= 0.95 and recent_accuracy >= 0.90 and not evidence.get("last_failure"):
        return "safe"
    if accuracy >= 0.90 and recent_accuracy >= 0.85 and consecutive_failures == 0:
        return "safe"
    if accuracy >= 0.80 and recent_accuracy >= 0.70:
        return "guarded"
    if accuracy >= 0.60:
        return "assist_only"
    return "blocked"


def _refresh(competence_row: dict[str, Any]) -> dict[str, Any]:
    ev = competence_row.setdefault("evidence", _empty_evidence())
    tests = int(ev.get("tests") or 0)
    passed = int(ev.get("passed") or 0)
    route_tests = int(ev.get("route_tests") or 0)
    answer_tests = int(ev.get("answer_tests") or 0)
    strategy_tests = int(ev.get("strategy_tests") or 0)
    ev["accuracy"] = round(passed / max(1, tests), 4) if tests else 0.0
    ev["route_accuracy"] = round(int(ev.get("route_passed") or 0) / max(1, route_tests), 4) if route_tests else 0.0
    ev["answer_accuracy"] = round(int(ev.get("answer_passed") or 0) / max(1, answer_tests), 4) if answer_tests else 0.0
    ev["strategy_accuracy"] = round(int(ev.get("strategy_passed") or 0) / max(1, strategy_tests), 4) if strategy_tests else 0.0
    competence_row["allowed_autonomy"] = _allowed_autonomy(ev)
    competence_row["updated_at"] = _now()
    return competence_row


def record_observation(
    *,
    competence: str,
    ok: bool,
    source: str,
    case_id: str = "",
    prompt: str = "",
    intent: str = "",
    route: str = "",
    rag_type: str = "",
    route_ok: bool | None = None,
    answer_ok: bool | None = None,
    strategy_ok: bool | None = None,
    failure_type: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state = _read_state()
    comps = state.setdefault("competences", {})
    cid = str(competence or "unknown_competence")
    row = comps.setdefault(cid, {**_profile_for(cid, {"intent": intent, "route": route, "rag_type": rag_type}), "evidence": _empty_evidence(), "created_at": _now()})
    for key, value in _profile_for(cid, {"intent": intent, "route": route, "rag_type": rag_type}).items():
        if value and (not row.get(key) or key in {"intent", "route", "rag_type"}):
            row[key] = value
    ev = row.setdefault("evidence", _empty_evidence())
    now = _now()
    ev["tests"] = int(ev.get("tests") or 0) + 1
    ev["passed"] = int(ev.get("passed") or 0) + (1 if ok else 0)
    ev["failed"] = int(ev.get("failed") or 0) + (0 if ok else 1)
    ev["first_seen"] = ev.get("first_seen") or _date(now)
    ev["last_seen"] = _date(now)
    if ok:
        ev["last_success"] = _date(now)
    else:
        ev["last_failure"] = _date(now)
        ev["last_failure_case"] = str(case_id or "")[:120]
        ev["last_failure_type"] = str(failure_type or "failed")[:80]
    if route_ok is not None:
        ev["route_tests"] = int(ev.get("route_tests") or 0) + 1
        ev["route_passed"] = int(ev.get("route_passed") or 0) + (1 if route_ok else 0)
    if answer_ok is not None:
        ev["answer_tests"] = int(ev.get("answer_tests") or 0) + 1
        ev["answer_passed"] = int(ev.get("answer_passed") or 0) + (1 if answer_ok else 0)
    if strategy_ok is not None:
        ev["strategy_tests"] = int(ev.get("strategy_tests") or 0) + 1
        ev["strategy_passed"] = int(ev.get("strategy_passed") or 0) + (1 if strategy_ok else 0)

    by_source = ev.setdefault("by_source", {})
    src = str(source or "unknown")[:80]
    src_row = by_source.setdefault(src, {"tests": 0, "passed": 0, "failed": 0})
    src_row["tests"] = int(src_row.get("tests") or 0) + 1
    src_row["passed"] = int(src_row.get("passed") or 0) + (1 if ok else 0)
    src_row["failed"] = int(src_row.get("failed") or 0) + (0 if ok else 1)

    recent = ev.setdefault("recent", [])
    recent.append({
        "ts": now,
        "date": _date(now),
        "ok": bool(ok),
        "source": src,
        "case_id": str(case_id or "")[:120],
        "prompt_hash": _hash(prompt),
        "failure_type": str(failure_type or "")[:80],
        "metadata": dict(metadata or {}),
    })
    ev["recent"] = recent[-RECENT_LIMIT:]
    comps[cid] = _refresh(row)
    _write_state(state)
    _append_log({"event": "competence_observation", "competence": cid, "ok": bool(ok), "source": src, "case_id": str(case_id or ""), "allowed_autonomy": comps[cid].get("allowed_autonomy")})
    return comps[cid]


def competence_for_route_item(item: dict[str, Any]) -> str:
    intent = str(item.get("expected_intent") or item.get("actual_intent") or "")
    route = str(item.get("expected_route") or item.get("actual_route") or "")
    prompt = str(item.get("prompt") or "").lower()
    trace = item.get("trace_rag") if isinstance(item.get("trace_rag"), dict) else {}
    rag_type = str(trace.get("rag_type") or "")
    if intent == "translation":
        if any(x in prompt for x in ("frances", "franc", "franca", "frança")):
            return "translation_pt_fr_basic"
        return "translation_basic"
    if intent == "stable_fact" or rag_type == "rag_facts":
        return "stable_fact_lookup_rag_facts"
    if intent == "programming_fact":
        if "git" in prompt:
            return "code_git_command_explanation"
        return "code_fact_explanation"
    if intent == "session_memory_write":
        return "session_memory_write"
    if intent == "session_memory_read":
        return "session_memory_read"
    if intent == "math_expression":
        return "deterministic_math_basic"
    if intent == "basic_logic":
        return "deductive_logic_basic"
    if intent == "creative_generation":
        return "creative_single_word_naming" if any(x in prompt for x in ("uma palavra", "1 palavra", "apenas uma palavra")) else "creative_generation_basic"
    if intent == "language_nuance":
        return "ptbr_language_nuance_idiom"
    if intent == "safety_risk":
        return "safety_explosives_refusal" if any(x in prompt for x in ("bomba", "boomba", "explosivo")) else "safety_refusal"
    if intent == "self_limits":
        return "self_model_limits_disclosure"
    if route:
        return f"{route}_competence"
    return "open_chat_competence"


def _failure_type_from_item(item: dict[str, Any]) -> str:
    if item.get("ok"):
        return ""
    if not item.get("route_ok"):
        return "wrong_route"
    if not item.get("strategy_ok"):
        return "wrong_strategy"
    if not item.get("answer_ok"):
        issues = item.get("answer_issues") if isinstance(item.get("answer_issues"), list) else []
        return str(issues[0] if issues else "bad_answer")[:80]
    return "unknown_failure"


def record_route_eval_report(report: dict[str, Any]) -> dict[str, Any]:
    run_id = str(report.get("run_id") or "")
    touched: dict[str, dict[str, Any]] = {}
    for item in report.get("items") or []:
        if not isinstance(item, dict):
            continue
        trace = item.get("trace_rag") if isinstance(item.get("trace_rag"), dict) else {}
        cid = competence_for_route_item(item)
        row = record_observation(
            competence=cid,
            ok=bool(item.get("ok")),
            source="route_eval",
            case_id=str(item.get("case_id") or ""),
            prompt=str(item.get("prompt") or ""),
            intent=str(item.get("expected_intent") or item.get("actual_intent") or ""),
            route=str(item.get("expected_route") or item.get("actual_route") or ""),
            rag_type=str(trace.get("rag_type") or ""),
            route_ok=bool(item.get("route_ok")),
            answer_ok=bool(item.get("answer_ok")),
            strategy_ok=bool(item.get("strategy_ok")),
            failure_type=_failure_type_from_item(item),
            metadata={"run_id": run_id, "actual_strategy": item.get("actual_strategy"), "trace_rag_type": trace.get("rag_type")},
        )
        touched[cid] = row
    return {
        "ok": True,
        "source": "route_eval",
        "run_id": run_id,
        "updated": len(touched),
        "competences": [
            {
                "competence": cid,
                "allowed_autonomy": row.get("allowed_autonomy"),
                "accuracy": (row.get("evidence") or {}).get("accuracy"),
                "tests": (row.get("evidence") or {}).get("tests"),
                "last_failure": (row.get("evidence") or {}).get("last_failure"),
            }
            for cid, row in sorted(touched.items())
        ],
        "path": str(LEDGER_PATH),
    }


def _competence_for_rag_type(rag_type: str) -> str:
    return f"{str(rag_type or 'rag_unknown')}_retrieval"


def record_rag_eval_report(report: dict[str, Any]) -> dict[str, Any]:
    touched: dict[str, dict[str, Any]] = {}
    for row in report.get("rows") or []:
        if not isinstance(row, dict):
            continue
        got = {str(x) for x in (row.get("got_domains") or [])}
        expected = [str(x) for x in (row.get("expected_domains") or [])]
        if not expected:
            expected = sorted(got)
        for rag_type in expected:
            cid = _competence_for_rag_type(rag_type)
            ok = rag_type in got and int(row.get("results_count") or 0) > 0 and float(row.get("top_router_score") or 0.0) >= 0.05
            obs = record_observation(
                competence=cid,
                ok=ok,
                source="rag_eval",
                case_id=str(row.get("query") or "")[:80],
                prompt=str(row.get("query") or ""),
                route=rag_type,
                rag_type=rag_type,
                failure_type="" if ok else "missing_or_low_rag_result",
                metadata={
                    "task_type": row.get("task_type"),
                    "got_domains": row.get("got_domains"),
                    "domain_coverage": row.get("domain_coverage"),
                    "results_count": row.get("results_count"),
                    "top_router_score": row.get("top_router_score"),
                },
            )
            touched[cid] = obs
    return {
        "ok": True,
        "source": "rag_eval",
        "updated": len(touched),
        "competences": [
            {
                "competence": cid,
                "allowed_autonomy": row.get("allowed_autonomy"),
                "accuracy": (row.get("evidence") or {}).get("accuracy"),
                "tests": (row.get("evidence") or {}).get("tests"),
                "last_failure": (row.get("evidence") or {}).get("last_failure"),
            }
            for cid, row in sorted(touched.items())
        ],
        "path": str(LEDGER_PATH),
    }


def list_competences() -> list[dict[str, Any]]:
    state = _read_state()
    rows = list((state.get("competences") or {}).values())
    rows.sort(key=lambda row: (str(row.get("allowed_autonomy") or ""), int((row.get("evidence") or {}).get("tests") or 0)), reverse=True)
    return rows


def status() -> dict[str, Any]:
    rows = list_competences()
    counts: dict[str, int] = {}
    for row in rows:
        key = str(row.get("allowed_autonomy") or "unknown")
        counts[key] = counts.get(key, 0) + 1
    gaps = [
        {
            "competence": row.get("competence"),
            "allowed_autonomy": row.get("allowed_autonomy"),
            "accuracy": (row.get("evidence") or {}).get("accuracy"),
            "last_failure": (row.get("evidence") or {}).get("last_failure"),
            "last_failure_case": (row.get("evidence") or {}).get("last_failure_case"),
        }
        for row in rows
        if str(row.get("allowed_autonomy") or "") in {"blocked", "assist_only", "observe"}
    ]
    return {
        "ok": True,
        "path": str(LEDGER_PATH),
        "log_path": str(LEDGER_LOG_PATH),
        "total_competences": len(rows),
        "counts_by_autonomy": counts,
        "competences": rows,
        "known_gaps": gaps,
    }


def run_selftest() -> dict[str, Any]:
    old_path = LEDGER_PATH
    old_log = LEDGER_LOG_PATH
    with tempfile.TemporaryDirectory(prefix="competence-ledger-") as td:
        globals()["LEDGER_PATH"] = Path(td) / "competence_ledger.json"
        globals()["LEDGER_LOG_PATH"] = Path(td) / "competence_ledger.jsonl"
        try:
            report = {
                "run_id": "selftest",
                "items": [
                    {
                        "case_id": "t1",
                        "prompt": "Como se diz obrigado em frances?",
                        "expected_intent": "translation",
                        "actual_intent": "translation",
                        "expected_route": "translation",
                        "actual_route": "translation",
                        "actual_strategy": "pre_causal_translation",
                        "ok": True,
                        "route_ok": True,
                        "answer_ok": True,
                        "strategy_ok": True,
                        "trace_rag": None,
                    },
                    {
                        "case_id": "g1",
                        "prompt": "O que o comando git commit -m faz?",
                        "expected_intent": "programming_fact",
                        "actual_intent": "programming_fact",
                        "expected_route": "programming_fact",
                        "actual_route": "programming_fact",
                        "actual_strategy": "pre_causal_programming_fact",
                        "ok": False,
                        "route_ok": True,
                        "answer_ok": False,
                        "strategy_ok": True,
                        "answer_issues": ["missing_trace_rag"],
                        "trace_rag": {"rag_type": "rag_code"},
                    },
                ],
            }
            route_out = record_route_eval_report(report)
            rag_out = record_rag_eval_report({
                "rows": [
                    {
                        "query": "Explique git commit -m usando docs locais.",
                        "task_type": "rag_code",
                        "expected_domains": ["rag_code"],
                        "got_domains": ["rag_code"],
                        "domain_coverage": 1.0,
                        "results_count": 1,
                        "top_router_score": 0.76,
                    }
                ]
            })
            st = status()
            by_id = {row["competence"]: row for row in st["competences"]}
            return {
                "ok": (
                    route_out.get("updated") == 2
                    and rag_out.get("updated") == 1
                    and by_id["translation_pt_fr_basic"]["evidence"]["tests"] == 1
                    and by_id["code_git_command_explanation"]["evidence"]["last_failure"] is not None
                    and by_id["rag_code_retrieval"]["evidence"]["tests"] == 1
                ),
                "route_out": route_out,
                "rag_out": rag_out,
                "status": st,
            }
        finally:
            globals()["LEDGER_PATH"] = old_path
            globals()["LEDGER_LOG_PATH"] = old_log
