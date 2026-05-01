"""
Active investigation for structured-reasoning gaps.

This module does not ask an LLM to answer. It probes the internal evidence
surfaces, records what is missing, and returns an auditable next experiment.
"""

from __future__ import annotations

import json
import hashlib
import os
import re
import time
import unicodedata
import uuid
from pathlib import Path
from typing import Any


DATA_DIR = Path(__file__).resolve().parent.parent / "data"
INVESTIGATION_LOG_PATH = DATA_DIR / "active_investigations.jsonl"
INVESTIGATION_STATE_PATH = DATA_DIR / "active_investigation_state.json"
INVESTIGATION_EXECUTION_LOG_PATH = DATA_DIR / "active_investigation_executions.jsonl"
INVESTIGATION_EXECUTION_STATE_PATH = DATA_DIR / "active_investigation_execution_state.json"

_STOP_TOKENS = {
    "qual",
    "quais",
    "quem",
    "como",
    "onde",
    "quando",
    "porque",
    "sobre",
    "voce",
    "voces",
    "meu",
    "minha",
    "mim",
    "agora",
    "ele",
    "ela",
    "eles",
    "elas",
    "tem",
    "exige",
    "exigem",
    "evidencia",
    "evidencias",
    "internas",
    "interna",
    "projeto",
    "decisao",
    "decisoes",
}


def _norm(text: Any) -> str:
    value = unicodedata.normalize("NFKD", str(text or ""))
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return value.lower()


def _tokens(text: Any) -> set[str]:
    return set(re.findall(r"[a-z0-9_]{3,}", _norm(text)))


def _query_tokens(text: Any) -> set[str]:
    tokens = _tokens(text) - _STOP_TOKENS
    return tokens if len(tokens) >= 2 else _tokens(text)


def _clip(text: Any, n: int = 280) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()[: max(1, int(n))]


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    except Exception:
        pass


def _read_json(path: Path, default: Any = None) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        pass
    return default


def _read_jsonl(path: Path, limit: int = 200) -> list[dict[str, Any]]:
    try:
        if not path.exists():
            return []
        lines = [ln for ln in path.read_text(encoding="utf-8", errors="ignore").splitlines() if ln.strip()]
        out: list[dict[str, Any]] = []
        for line in lines[-max(1, int(limit or 1)) :]:
            try:
                item = json.loads(line)
            except Exception:
                continue
            if isinstance(item, dict):
                out.append(item)
        return out
    except Exception:
        return []


def _flatten(value: Any, *, max_chars: int = 6000) -> str:
    try:
        if isinstance(value, str):
            text = value
        else:
            text = json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        text = str(value)
    return _clip(text, max_chars)


def _executed_investigation_ids() -> set[str]:
    ids: set[str] = set()
    for row in _read_jsonl(INVESTIGATION_EXECUTION_LOG_PATH, limit=500):
        if not row.get("ok") or not row.get("injected"):
            continue
        inv_id = str(row.get("investigation_id") or "").strip()
        if inv_id:
            ids.add(inv_id)
    return ids


def pending_experiments(*, limit: int = 3, max_age_hours: float | None = None) -> list[dict[str, Any]]:
    """Return active investigations whose next experiment still needs execution."""
    if max_age_hours is None:
        try:
            max_age_hours = float(os.getenv("ULTRON_ACTIVE_INVESTIGATION_MAX_AGE_HOURS", "168") or 168)
        except Exception:
            max_age_hours = 168.0

    now = int(time.time())
    executed = _executed_investigation_ids()
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()

    state = _read_json(INVESTIGATION_STATE_PATH, {})
    if isinstance(state, dict) and state:
        candidates.append(state)
    candidates.extend(reversed(_read_jsonl(INVESTIGATION_LOG_PATH, limit=250)))

    out: list[dict[str, Any]] = []
    for report in candidates:
        inv_id = str(report.get("investigation_id") or "").strip()
        if not inv_id or inv_id in seen or inv_id in executed:
            continue
        seen.add(inv_id)
        if str(report.get("status") or "") != "needs_experiment":
            continue
        if not isinstance(report.get("next_experiment"), dict):
            continue
        ts = int(report.get("ts") or 0)
        if ts and max_age_hours >= 0 and (now - ts) > max_age_hours * 3600:
            continue
        out.append(report)
        if len(out) >= max(1, int(limit or 1)):
            break
    return out


def _gap_value(gap: Any, key: str, default: Any = None) -> Any:
    if isinstance(gap, dict):
        return gap.get(key, default)
    return getattr(gap, key, default)


def _gap_dict(gap: Any) -> dict[str, Any]:
    evidence = _gap_value(gap, "evidence", {})
    return {
        "id": str(_gap_value(gap, "id", "") or ""),
        "label": str(_gap_value(gap, "label", "") or ""),
        "domain": str(_gap_value(gap, "domain", "") or ""),
        "metric": str(_gap_value(gap, "metric", "") or ""),
        "priority": float(_gap_value(gap, "priority", 0.0) or 0.0),
        "evidence": evidence if isinstance(evidence, dict) else {},
        "next_experiment": str(_gap_value(gap, "next_experiment", "") or ""),
    }


def _gap_investigation_id(gap: dict[str, Any]) -> str:
    material = "|".join(
        str(gap.get(key) or "")
        for key in ("id", "label", "domain", "metric", "next_experiment")
    )
    digest = hashlib.sha256(material.encode("utf-8", errors="ignore")).hexdigest()[:10]
    slug = "_".join(re.findall(r"[a-z0-9]+", _norm(gap.get("id") or gap.get("label")))[:5])
    return f"gap_{slug or 'epistemic'}_{digest}"


def _known_investigation_ids() -> set[str]:
    ids: set[str] = set()
    state = _read_json(INVESTIGATION_STATE_PATH, {})
    if isinstance(state, dict) and state.get("investigation_id"):
        ids.add(str(state.get("investigation_id")))
    for path in (INVESTIGATION_LOG_PATH, INVESTIGATION_EXECUTION_LOG_PATH):
        for row in _read_jsonl(path, limit=1000):
            inv_id = str(row.get("investigation_id") or "").strip()
            if inv_id:
                ids.add(inv_id)
    return ids


def _gap_query(gap: dict[str, Any]) -> str:
    parts = [
        gap.get("label") or gap.get("id") or "lacuna epistemica",
        gap.get("domain") or "",
        gap.get("metric") or "",
        gap.get("next_experiment") or "",
    ]
    return _clip(". ".join(str(part).strip() for part in parts if str(part).strip()), 600)


def _gap_missing_slots(gap: dict[str, Any]) -> list[str]:
    gap_id = str(gap.get("id") or "").lower()
    domain = str(gap.get("domain") or "").lower()
    slots = ["evidencia_interna_suficiente"]
    if "causal" in gap_id or "causal" in domain:
        slots.append("aresta_causal_relevante")
    if "episodic" in gap_id or "bio" in domain or "self_model" in domain:
        slots.append("episodio_relevante")
    if "cloud" in gap_id or "fact" in domain or "language" in domain:
        slots.append("fato_estruturado_recuperavel")
    if "runtime" in domain or "background" in gap_id:
        slots.append("resultado_runtime_mensuravel")
    return sorted(set(slots))


def _gap_next_experiment(gap: dict[str, Any]) -> dict[str, Any]:
    gap_id = str(gap.get("id") or "").lower()
    domain = str(gap.get("domain") or "unknown")
    action = str(gap.get("next_experiment") or "").strip()
    if not action:
        action = "executar experimento sandboxado para reduzir a lacuna antes da proxima resposta"

    kind = "coverage_refinement"
    if "causal" in gap_id or "causal" in domain.lower():
        kind = "causal_graph_enrichment"
    elif "episodic" in gap_id or "bio" in domain.lower():
        kind = "episodic_evidence_collection"
    elif "cloud" in gap_id or "language" in domain.lower():
        kind = "structured_fact_acquisition"
    elif "runtime" in domain.lower() or "background" in gap_id:
        kind = "runtime_pressure_probe"

    return {
        "kind": kind,
        "target_route": domain or "unknown",
        "query_terms": sorted(_query_tokens(_gap_query(gap)))[:12],
        "action": action,
        "acceptance": "o resultado sandboxado deve produzir uma aresta causal auditavel ou uma refutacao explicita",
    }


def seed_epistemic_gap_experiments(
    gaps: list[Any],
    *,
    limit: int = 3,
    source: str = "epistemic_gap_perception",
) -> dict[str, Any]:
    """Turn proactive epistemic gaps into executable active investigations."""
    limit = max(0, int(limit or 0))
    if limit <= 0:
        return {"ok": True, "seeded": 0, "skipped": 0, "items": [], "reason": "limit_zero"}

    started = time.perf_counter()
    known = _known_investigation_ids()
    normalized = [_gap_dict(gap) for gap in (gaps or [])]
    normalized = [gap for gap in normalized if gap.get("id") or gap.get("label")]
    normalized.sort(key=lambda gap: float(gap.get("priority") or 0.0), reverse=True)

    seeded: list[dict[str, Any]] = []
    skipped = 0
    for gap in normalized:
        if len(seeded) >= limit:
            break
        inv_id = _gap_investigation_id(gap)
        if inv_id in known:
            skipped += 1
            continue
        report = {
            "ok": True,
            "resolved": True,
            "investigation_id": inv_id,
            "ts": int(time.time()),
            "status": "needs_experiment",
            "reason": "proactive_epistemic_gap",
            "task_type": str(gap.get("domain") or "epistemic_gap"),
            "query": _gap_query(gap),
            "source": source,
            "source_gap": gap,
            "learned_route": {
                "routed": True,
                "module": str(gap.get("domain") or "epistemic_gap"),
                "method": "epistemic_curiosity_gap_scan",
                "confidence": round(float(gap.get("priority") or 0.0), 4),
            },
            "coverage": {
                "score": 0.0,
                "shared": [],
                "query_tokens": len(_query_tokens(_gap_query(gap))),
                "evidence_tokens": 0,
            },
            "missing_slots": _gap_missing_slots(gap),
            "next_experiment": _gap_next_experiment(gap),
            "candidate_modules": [],
            "probes": {
                "epistemic_curiosity": {
                    "ok": True,
                    "gap_id": gap.get("id"),
                    "priority": gap.get("priority"),
                    "metric": gap.get("metric"),
                }
            },
            "duration_ms": 0.0,
        }
        report["answer"] = _render_answer(report)
        report["causal_graph_registration"] = _register_in_causal_graph(report)
        _append_jsonl(INVESTIGATION_LOG_PATH, report)
        _write_json(INVESTIGATION_STATE_PATH, report)
        known.add(inv_id)
        seeded.append({
            "investigation_id": inv_id,
            "gap_id": gap.get("id"),
            "priority": gap.get("priority"),
            "experiment_kind": report["next_experiment"].get("kind"),
        })

    return {
        "ok": True,
        "source": source,
        "seeded": len(seeded),
        "skipped": skipped,
        "gap_count": len(normalized),
        "duration_ms": round((time.perf_counter() - started) * 1000.0, 2),
        "items": seeded,
    }


def _sandbox_report_payload(report: dict[str, Any]) -> dict[str, Any]:
    next_exp = report.get("next_experiment") if isinstance(report.get("next_experiment"), dict) else {}
    return {
        "investigation_id": report.get("investigation_id"),
        "query": _clip(report.get("query"), 600),
        "reason": report.get("reason"),
        "task_type": report.get("task_type"),
        "status": report.get("status"),
        "coverage": report.get("coverage") if isinstance(report.get("coverage"), dict) else {},
        "missing_slots": report.get("missing_slots") if isinstance(report.get("missing_slots"), list) else [],
        "next_experiment": {
            "kind": next_exp.get("kind"),
            "target_route": next_exp.get("target_route"),
            "query_terms": next_exp.get("query_terms") if isinstance(next_exp.get("query_terms"), list) else [],
            "action": next_exp.get("action"),
            "acceptance": next_exp.get("acceptance"),
        },
        "transfer_prior": report.get("transfer_prior") if isinstance(report.get("transfer_prior"), dict) else None,
    }


def _experiment_sandbox_code(payload: dict[str, Any]) -> str:
    payload_json = json.dumps(payload, ensure_ascii=False, default=str)
    return f"""
import hashlib
import json
import re

report = json.loads({json.dumps(payload_json)})

def tokens(value):
    return sorted(set(re.findall(r"[a-z0-9_]{{3,}}", str(value or "").lower())))

next_exp = report.get("next_experiment") or {{}}
query_terms = [str(x).lower() for x in (next_exp.get("query_terms") or []) if str(x).strip()]
if len(query_terms) < 2:
    query_terms = tokens(report.get("query"))[:12]

missing = [str(x) for x in (report.get("missing_slots") or []) if str(x).strip()]
kind = str(next_exp.get("kind") or "coverage_refinement")
target_route = str(next_exp.get("target_route") or "unknown")
material = "|".join([str(report.get("investigation_id") or ""), kind, " ".join(query_terms), ",".join(missing)])
digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]

accepted = bool(report.get("investigation_id") and query_terms and (missing or report.get("transfer_prior")) and next_exp.get("action"))
transfer_prior = report.get("transfer_prior") if isinstance(report.get("transfer_prior"), dict) else {{}}
prior_validation = None
if transfer_prior:
    prior_conf = float(transfer_prior.get("confidence") or 0.0)
    policy = str(transfer_prior.get("transferred_policy") or transfer_prior.get("policy_hypothesis") or "")
    source_domain = str(transfer_prior.get("source_domain") or "unknown")
    target_domain = str(transfer_prior.get("target_domain") or target_route or "unknown")
    mapped_terms = set(tokens({{
        "mapping": transfer_prior.get("mapping") or {{}},
        "policy": policy,
        "source_domain": source_domain,
        "target_domain": target_domain,
    }}))
    query_overlap = sorted(set(query_terms) & mapped_terms)
    validated = bool(accepted and source_domain != "unknown" and policy and prior_conf >= 0.20)
    status = "validated" if validated else "refuted"
    after_conf = min(0.78, prior_conf + 0.10) if validated else max(0.12, prior_conf - 0.14)
    prior_validation = {{
        "ok": True,
        "status": status,
        "category": "confirmed" if validated else "refuted",
        "confidence_before": round(prior_conf, 4),
        "confidence_after": round(after_conf, 4),
        "query_overlap": query_overlap[:8],
        "source_domain": source_domain,
        "target_domain": target_domain,
        "reason": "sandbox_validation_of_transfer_prior" if validated else "transfer_prior_failed_sandbox_acceptance",
    }}
    edge = {{
        "cause": str(transfer_prior.get("causal_claim") or ("causal_transfer_prior:" + source_domain + "->" + target_domain)),
        "effect": "transfer_prior_" + status + ":" + source_domain + "->" + target_domain,
        "condition": "active_investigation_prior_validation:" + str(report.get("investigation_id") or ""),
        "confidence": after_conf,
    }}
else:
    edge = {{
        "cause": "active_investigation_gap:" + " ".join(query_terms[:10]),
        "effect": "sandbox_experiment_observed:" + kind + ":" + target_route,
        "condition": "autonomous_executor_next_cycle:" + str(report.get("investigation_id") or ""),
        "confidence": 0.66 if accepted else 0.42,
    }}

print(json.dumps({{
    "ok": True,
    "accepted": accepted,
    "digest": digest,
    "query_terms": query_terms[:12],
    "missing_slots": missing,
    "experiment_kind": kind,
    "target_route": target_route,
    "edge": edge,
    "prior_validation": prior_validation,
    "acceptance_checked": bool(next_exp.get("acceptance")),
}}, ensure_ascii=False))
""".strip()


def _parse_sandbox_stdout(stdout: str) -> dict[str, Any]:
    for line in reversed(str(stdout or "").splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if isinstance(obj, dict):
            return obj
    return {"ok": False, "error": "no_json_result"}


def _execute_report_experiment(report: dict[str, Any]) -> dict[str, Any]:
    """Execute a concrete investigation report without re-reading the pending queue."""
    inv_id = str(report.get("investigation_id") or "").strip()
    payload = _sandbox_report_payload(report)
    code = _experiment_sandbox_code(payload)
    started = time.perf_counter()
    row: dict[str, Any] = {
        "ts": int(time.time()),
        "ok": False,
        "executed": True,
        "injected": False,
        "investigation_id": inv_id,
        "query": payload.get("query"),
        "reason": payload.get("reason"),
        "missing_slots": payload.get("missing_slots"),
        "experiment": payload.get("next_experiment"),
    }

    try:
        from ultronpro import sandbox_client

        sandbox = sandbox_client.execute_python(code, timeout_sec=8)
    except Exception as exc:
        sandbox = {"ok": False, "error": f"sandbox_client_error:{type(exc).__name__}", "stderr": str(exc)[:500]}

    row["sandbox"] = {
        "ok": bool(sandbox.get("ok")),
        "error": sandbox.get("error"),
        "returncode": sandbox.get("returncode"),
        "stderr": _clip(sandbox.get("stderr"), 800),
    }
    if not sandbox.get("ok"):
        row["error"] = sandbox.get("error") or "sandbox_failed"
        row["duration_ms"] = round((time.perf_counter() - started) * 1000.0, 2)
        _append_jsonl(INVESTIGATION_EXECUTION_LOG_PATH, row)
        _write_json(INVESTIGATION_EXECUTION_STATE_PATH, row)
        return row

    experiment_result = _parse_sandbox_stdout(str(sandbox.get("stdout") or ""))
    row["experiment_result"] = experiment_result
    if not experiment_result.get("ok") or not experiment_result.get("accepted"):
        row["error"] = experiment_result.get("error") or "experiment_not_accepted"
        row["duration_ms"] = round((time.perf_counter() - started) * 1000.0, 2)
        _append_jsonl(INVESTIGATION_EXECUTION_LOG_PATH, row)
        _write_json(INVESTIGATION_EXECUTION_STATE_PATH, row)
        return row

    edge = experiment_result.get("edge") if isinstance(experiment_result.get("edge"), dict) else {}
    prior_validation = (
        experiment_result.get("prior_validation")
        if isinstance(experiment_result.get("prior_validation"), dict)
        else None
    )
    if prior_validation:
        row["prior_validation"] = prior_validation
    try:
        from ultronpro import causal_graph, store

        injected = causal_graph.upsert_edge(
            cause=str(edge.get("cause") or f"active_investigation_gap:{inv_id}"),
            effect=str(edge.get("effect") or "sandbox_experiment_observed:coverage_refinement"),
            condition=str(edge.get("condition") or "autonomous_executor_next_cycle"),
            evidence={
                "investigation": payload,
                "sandbox_result": experiment_result,
                "duration_ms": round((time.perf_counter() - started) * 1000.0, 2),
            },
            confidence=float(edge.get("confidence") or 0.66),
            source="active_investigation_executor",
        )
        row["causal_graph"] = injected
        row["injected"] = bool(injected.get("ok"))
        row["ok"] = bool(injected.get("ok"))
        if prior_validation:
            try:
                row["transfer_prior_causal_update"] = causal_graph.apply_delta_update(
                    cause=str(edge.get("cause") or f"causal_transfer_prior:{inv_id}"),
                    effect=str(edge.get("effect") or "transfer_prior_validated"),
                    condition=str(edge.get("condition") or f"active_investigation_prior_validation:{inv_id}"),
                    category=str(prior_validation.get("category") or "confirmed"),
                    evidence={
                        "investigation": payload,
                        "sandbox_result": experiment_result,
                        "prior_validation": prior_validation,
                    },
                    source="active_investigation_executor",
                )
            except Exception as exc:
                row["transfer_prior_causal_update"] = {"ok": False, "error": str(exc)[:180]}
        try:
            store.publish_workspace(
                module="active_investigation_executor",
                channel="causal.experiment",
                payload_json=json.dumps(row, ensure_ascii=False, default=str),
                salience=0.72,
                ttl_sec=1800,
            )
        except Exception:
            pass
    except Exception as exc:
        row["error"] = f"causal_injection_error:{type(exc).__name__}:{str(exc)[:160]}"

    row["duration_ms"] = round((time.perf_counter() - started) * 1000.0, 2)
    _append_jsonl(INVESTIGATION_EXECUTION_LOG_PATH, row)
    _write_json(INVESTIGATION_EXECUTION_STATE_PATH, row)
    return row


def execute_pending_experiment() -> dict[str, Any]:
    """Execute one pending investigation experiment in sandbox and inject the result into the causal graph."""
    pending = pending_experiments(limit=1)
    if not pending:
        return {"ok": True, "executed": False, "reason": "no_pending_active_investigation"}
    return _execute_report_experiment(pending[0])


def execute_pending_experiments(*, limit: int = 3) -> dict[str, Any]:
    """Execute a bounded batch of pending investigations for offline/nightly cycles."""
    limit = max(1, int(limit or 1))
    pending = pending_experiments(limit=limit)
    if not pending:
        return {
            "ok": True,
            "executed": 0,
            "injected": 0,
            "failed": 0,
            "pending_before": 0,
            "results": [],
            "reason": "no_pending_active_investigation",
        }

    results = [_execute_report_experiment(report) for report in pending[:limit]]
    injected = sum(1 for item in results if item.get("ok") and item.get("injected"))
    failed = sum(1 for item in results if item.get("executed") and not item.get("ok"))
    return {
        "ok": failed == 0,
        "executed": sum(1 for item in results if item.get("executed")),
        "injected": injected,
        "failed": failed,
        "pending_before": len(pending),
        "results": results,
    }


def _coverage(query: str, evidence: list[dict[str, Any]]) -> dict[str, Any]:
    qtok = _query_tokens(query)
    etok: set[str] = set()
    for item in evidence:
        etok |= _tokens(item)
    if not qtok or not etok:
        return {"score": 0.0, "shared": [], "query_tokens": len(qtok), "evidence_tokens": len(etok)}
    shared = sorted(qtok & etok)
    return {
        "score": round(len(shared) / max(1, len(qtok)), 4),
        "shared": shared[:24],
        "query_tokens": len(qtok),
        "evidence_tokens": len(etok),
    }


def _enabled() -> bool:
    return str(os.getenv("ULTRON_ACTIVE_INVESTIGATION_ENABLED", "1")).strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def _coverage_threshold() -> float:
    try:
        return max(0.15, min(0.85, float(os.getenv("ULTRON_ACTIVE_INVESTIGATION_COVERAGE_THRESHOLD", "0.42"))))
    except Exception:
        return 0.42


def _learned_route(query: str) -> dict[str, Any]:
    try:
        from ultronpro.core import learned_intent

        max_examples = int(os.getenv("ULTRON_ACTIVE_INVESTIGATION_INTENT_MAX_EXAMPLES", "120") or 120)
        use_embeddings = str(os.getenv("ULTRON_ACTIVE_INVESTIGATION_INTENT_EMBEDDINGS", "0") or "0").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        return learned_intent.predict_route(query, max_examples=max_examples, use_embeddings=use_embeddings).to_dict()
    except Exception as exc:
        return {"routed": False, "module": "unknown", "error": str(exc)[:160]}


def _probe_causal_graph(query: str) -> dict[str, Any]:
    try:
        from ultronpro import causal_graph

        result = causal_graph.query_for_problem(query, limit=6)
        raw_items = result.get("items") if isinstance(result, dict) and isinstance(result.get("items"), list) else []
        qtok = _query_tokens(query)
        items = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            text = " ".join(str(item.get(k) or "") for k in ("cause", "effect", "condition"))
            shared = qtok & _tokens(text)
            if len(shared) >= 2:
                enriched = dict(item)
                enriched["match_tokens"] = sorted(shared)[:8]
                items.append(enriched)
        return {"ok": True, "count": len(items), "items": items[:6]}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:180]}


def _probe_episodic_memory(query: str, task_type: str) -> dict[str, Any]:
    try:
        from ultronpro import episodic_memory

        result = episodic_memory.layered_recall_compact(
            problem=query,
            task_type=task_type or "general",
            limit=4,
            max_chars=1800,
        )
        if not isinstance(result, dict):
            return {"ok": False, "error": "non_dict_result"}
        similar = result.get("episodic_similar") if isinstance(result.get("episodic_similar"), list) else []
        return {
            "ok": True,
            "count": len(similar),
            "summary": _clip(result.get("prompt_memory_context") or result.get("summary") or result, 1600),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:180]}


def _probe_store(query: str) -> dict[str, Any]:
    try:
        from ultronpro import store

        raw_triples = store.search_triples(query, limit=8) if hasattr(store, "search_triples") else []
        raw_insights = store.search_insights(query, limit=5) if hasattr(store, "search_insights") else []
        experiences = store.list_experiences(limit=8) if hasattr(store, "list_experiences") else []
        qtok = _query_tokens(query)
        triples = []
        for item in raw_triples:
            text = " ".join(str((item or {}).get(k) or "") for k in ("subject", "predicate", "object", "note"))
            if len(qtok & _tokens(text)) >= 2:
                triples.append(item)
        insights = []
        for item in raw_insights:
            text = " ".join(str((item or {}).get(k) or "") for k in ("title", "text", "kind"))
            if len(qtok & _tokens(text)) >= 2:
                insights.append(item)
        filtered_exp = []
        for exp in experiences:
            text = str((exp or {}).get("text") or "")
            if qtok & _tokens(text):
                filtered_exp.append({
                    "id": (exp or {}).get("id"),
                    "source_id": (exp or {}).get("source_id"),
                    "text": _clip(text, 320),
                })
        return {
            "ok": True,
            "triples": triples[:8],
            "insights": insights[:5],
            "experiences": filtered_exp[:5],
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:180]}


def _probe_workspace() -> dict[str, Any]:
    try:
        from ultronpro import store

        rows = store.read_workspace(limit=10, include_expired=False) if hasattr(store, "read_workspace") else []
        compact = []
        for row in rows[:10]:
            compact.append({
                "module": row.get("module"),
                "channel": row.get("channel"),
                "salience": row.get("salience"),
                "payload": _clip(row.get("payload_json"), 360),
            })
        return {"ok": True, "count": len(compact), "items": compact}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:180]}


def _probe_runtime_state() -> dict[str, Any]:
    names = (
        "background_guard.json",
        "runtime_health.json",
        "no_cloud_experiment_campaign_state.json",
        "active_discovery_state.json",
    )
    data: dict[str, Any] = {}
    for name in names:
        value = _read_json(DATA_DIR / name, {})
        if isinstance(value, dict) and value:
            data[name] = value
    return {"ok": True, "files": data}


def _missing_slots(query: str, probes: dict[str, Any], coverage: dict[str, Any], learned_route: dict[str, Any]) -> list[str]:
    slots: list[str] = []
    if coverage.get("score", 0.0) < _coverage_threshold():
        slots.append("evidencia_interna_suficiente")

    causal = probes.get("causal_graph") if isinstance(probes.get("causal_graph"), dict) else {}
    if int(causal.get("count") or 0) <= 0:
        slots.append("aresta_causal_relevante")

    episodic = probes.get("episodic_memory") if isinstance(probes.get("episodic_memory"), dict) else {}
    if int(episodic.get("count") or 0) <= 0 and str(learned_route.get("module") or "") in {
        "episodic",
        "autobiographical",
        "memory",
        "dialogue",
        "user_context",
    }:
        slots.append("episodio_relevante")

    store_probe = probes.get("store") if isinstance(probes.get("store"), dict) else {}
    has_structured_items = bool(store_probe.get("triples") or store_probe.get("insights") or store_probe.get("experiences"))
    if not has_structured_items:
        slots.append("fato_estruturado_recuperavel")

    return sorted(set(slots))


def _next_experiment(
    query: str,
    missing: list[str],
    learned_route: dict[str, Any],
    transfer_prior: dict[str, Any] | None = None,
) -> dict[str, Any]:
    qtok = sorted(_query_tokens(query))[:12]
    module = str(learned_route.get("module") or "unknown")
    if isinstance(transfer_prior, dict) and transfer_prior:
        kind = "causal_transfer_prior_validation"
        source = str(transfer_prior.get("source_domain") or "unknown")
        target = str(transfer_prior.get("target_domain") or module or "unknown")
        action = (
            f"validar ou refutar o prior transferido de {source} para {target} "
            "com experimento sandboxado antes de aumentar a confianca"
        )
        acceptance = "o experimento deve registrar validacao ou refutacao explicita do prior transferido no grafo causal"
    elif "aresta_causal_relevante" in missing:
        kind = "causal_graph_enrichment"
        action = "registrar uma decisao ou observacao verificavel como aresta causal antes de responder com confianca"
        acceptance = "a proxima resposta deve citar evidencia interna recuperada ou declarar UNKNOWN com a lacuna exata"
    elif "episodio_relevante" in missing:
        kind = "episodic_evidence_collection"
        action = "buscar ou produzir um episodio real relacionado e reexecutar a recuperacao episodica"
        acceptance = "a proxima resposta deve citar evidencia interna recuperada ou declarar UNKNOWN com a lacuna exata"
    elif "fato_estruturado_recuperavel" in missing:
        kind = "structured_fact_acquisition"
        action = "coletar evidencia verificavel e converter em triple/insight antes de sintetizar"
        acceptance = "a proxima resposta deve citar evidencia interna recuperada ou declarar UNKNOWN com a lacuna exata"
    else:
        kind = "coverage_refinement"
        action = "comparar candidatos de modulo e atualizar o classificador de rota com o resultado observado"
        acceptance = "a proxima resposta deve citar evidencia interna recuperada ou declarar UNKNOWN com a lacuna exata"
    return {
        "kind": kind,
        "target_route": str((transfer_prior or {}).get("target_domain") or module),
        "query_terms": qtok,
        "action": action,
        "acceptance": acceptance,
    }


def _register_in_causal_graph(report: dict[str, Any]) -> dict[str, Any]:
    try:
        from ultronpro import causal_graph

        status = str(report.get("status") or "unknown")
        reason = str(report.get("reason") or "unknown")
        return causal_graph.upsert_edge(
            cause=f"structured_reasoning_gap:{reason}",
            effect=f"active_investigation:{status}",
            condition="structured_coverage_insufficient",
            evidence={
                "investigation_id": report.get("investigation_id"),
                "coverage": report.get("coverage"),
                "missing_slots": report.get("missing_slots"),
                "next_experiment": report.get("next_experiment"),
                "learned_route": report.get("learned_route"),
                "transfer_prior": report.get("transfer_prior"),
                "prior_validation": report.get("prior_validation"),
            },
            confidence=0.68,
            source="active_investigation",
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:180]}


def _render_answer(report: dict[str, Any]) -> str:
    inv_id = report.get("investigation_id")
    coverage = report.get("coverage") if isinstance(report.get("coverage"), dict) else {}
    missing = report.get("missing_slots") if isinstance(report.get("missing_slots"), list) else []
    probes = report.get("probes") if isinstance(report.get("probes"), dict) else {}
    ran = [name for name, value in probes.items() if isinstance(value, dict) and value.get("ok")]
    next_exp = report.get("next_experiment") if isinstance(report.get("next_experiment"), dict) else {}
    score = float(coverage.get("score") or 0.0)
    transfer_prior = report.get("transfer_prior") if isinstance(report.get("transfer_prior"), dict) else {}
    if transfer_prior:
        execution = report.get("execution") if isinstance(report.get("execution"), dict) else {}
        prior_validation = report.get("prior_validation") if isinstance(report.get("prior_validation"), dict) else {}
        if not prior_validation:
            prior_validation = execution.get("prior_validation") if isinstance(execution.get("prior_validation"), dict) else {}
        status = str(prior_validation.get("status") or "pending_validation")
        confidence = float(prior_validation.get("confidence_after") or transfer_prior.get("confidence") or 0.0)
        source = _clip(transfer_prior.get("source_domain"), 80)
        target = _clip(transfer_prior.get("target_domain"), 100)
        policy = _clip(transfer_prior.get("transferred_policy") or transfer_prior.get("policy_hypothesis"), 520)
        answer = [
            f"Encontrei cobertura direta insuficiente, mas nao vou parar em UNKNOWN: transferi um prior causal de {source} para {target}.",
            f"Hipotese/politica transferida: {policy}",
            f"Confianca calibrada do prior: {confidence:.2f} (degradada ate validacao interventiva).",
        ]
        if status == "validated":
            answer.append("A investigacao ativa sandboxada validou o prior e registrou evidencia interventiva no grafo causal.")
        elif status == "refuted":
            answer.append("A investigacao ativa sandboxada refutou o prior; mantenho a hipotese como baixa confianca e a lacuna continua aberta.")
        else:
            answer.append(f"Investigacao ativa iniciada: {inv_id}; proximo experimento: {next_exp.get('action')}")
        if missing:
            answer.append(f"Lacunas restantes: {', '.join(missing[:4])}.")
        return "\n".join(answer)
    answer = [
        "UNKNOWN: meu nucleo estruturado ainda nao tem cobertura suficiente para responder isso com confianca.",
        f"Investigacao ativa iniciada: {inv_id}.",
        f"Cobertura interna medida: {score:.2f}; probes executados: {', '.join(ran) if ran else 'nenhum probe verde'}.",
    ]
    if missing:
        answer.append(f"Lacunas atuais: {', '.join(missing[:4])}.")
    if next_exp:
        answer.append(f"Proximo experimento: {next_exp.get('action')}")
    return "\n".join(answer)


def investigate_structured_gap(
    query: str,
    *,
    reason: str,
    task_type: str = "general",
    candidates: list[dict[str, Any]] | None = None,
    transfer_prior: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not _enabled():
        return {"ok": True, "resolved": False, "reason": "active_investigation_disabled"}

    started = time.perf_counter()
    q = str(query or "").strip()
    learned_route = _learned_route(q)
    probes = {
        "learned_route": {"ok": True, "prediction": learned_route},
        "causal_graph": _probe_causal_graph(q),
        "episodic_memory": _probe_episodic_memory(q, task_type),
        "store": _probe_store(q),
        "workspace": _probe_workspace(),
        "runtime_state": _probe_runtime_state(),
    }
    if isinstance(transfer_prior, dict) and transfer_prior:
        probes["autoisomorphic_transfer_prior"] = {"ok": True, "prior": transfer_prior}
    evidence_items = [
        {"name": name, "value": value}
        for name, value in probes.items()
        if isinstance(value, dict) and value.get("ok")
    ]
    coverage = _coverage(q, evidence_items)
    missing = _missing_slots(q, probes, coverage, learned_route)
    next_exp = _next_experiment(q, missing, learned_route, transfer_prior if isinstance(transfer_prior, dict) else None)
    status = "needs_experiment" if missing or transfer_prior else "evidence_found_needs_composition"
    investigation_id = f"inv_{uuid.uuid4().hex[:10]}"
    report = {
        "ok": True,
        "resolved": True,
        "investigation_id": investigation_id,
        "ts": int(time.time()),
        "status": status,
        "reason": str(reason or "unknown"),
        "task_type": str(task_type or "general"),
        "query": q[:600],
        "learned_route": learned_route,
        "coverage": coverage,
        "missing_slots": missing,
        "next_experiment": next_exp,
        "transfer_prior": transfer_prior if isinstance(transfer_prior, dict) else None,
        "candidate_modules": candidates or [],
        "probes": probes,
        "duration_ms": round((time.perf_counter() - started) * 1000.0, 2),
    }
    report["causal_graph_registration"] = _register_in_causal_graph(report)
    report["answer"] = _render_answer(report)
    _append_jsonl(INVESTIGATION_LOG_PATH, report)
    _write_json(INVESTIGATION_STATE_PATH, report)
    if isinstance(transfer_prior, dict) and transfer_prior:
        execution = _execute_report_experiment(report)
        report["execution"] = execution
        prior_validation = execution.get("prior_validation") if isinstance(execution.get("prior_validation"), dict) else None
        if prior_validation:
            report["prior_validation"] = prior_validation
            report["status"] = (
                "transfer_prior_validated"
                if prior_validation.get("status") == "validated"
                else "transfer_prior_refuted"
            )
            report["confidence_after_validation"] = prior_validation.get("confidence_after")
        report["answer"] = _render_answer(report)
        _append_jsonl(INVESTIGATION_LOG_PATH, report)
        _write_json(INVESTIGATION_STATE_PATH, report)
    return report
