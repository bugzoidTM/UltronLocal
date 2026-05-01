from __future__ import annotations

import hashlib
import json
import tempfile
import time
from pathlib import Path
from typing import Any


DATA_DIR = Path(__file__).resolve().parent.parent / "data"
LEDGER_LOG_PATH = DATA_DIR / "epistemic_ledger.jsonl"
LEDGER_STATE_PATH = DATA_DIR / "epistemic_ledger_state.json"

PASS_STATUSES = {"passed", "correct", "validated", "ok", "promoted", "ready"}
FAIL_STATUSES = {"failed", "incorrect", "rejected", "blocked", "needs_revision"}

DEFAULT_REQUIREMENTS: dict[str, set[str]] = {
    "factual_claim": {"external"},
    "patch": {"external", "counterfactual", "longitudinal"},
    "competency": {"external", "counterfactual", "longitudinal"},
    "causal_rule": {"external", "counterfactual", "longitudinal"},
    "system_capability": {"external", "counterfactual", "longitudinal"},
}


def _now() -> int:
    return int(time.time())


def _clip(value: Any, n: int = 900) -> str:
    return " ".join(str(value or "").split())[: max(1, int(n or 1))]


def _hash(value: Any) -> str:
    try:
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:
        raw = str(value)
    return hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()[:16]


def artifact_id_for(kind: str, material: Any) -> str:
    return f"{kind}_{_hash(material)}"


def _artifact_key(kind: str, artifact_id: str) -> str:
    return f"{kind}:{artifact_id}"


def _read_state() -> dict[str, Any]:
    try:
        if LEDGER_STATE_PATH.exists():
            data = json.loads(LEDGER_STATE_PATH.read_text(encoding="utf-8", errors="ignore"))
            if isinstance(data, dict):
                data.setdefault("artifacts", {})
                return data
    except Exception:
        pass
    return {"ok": True, "version": 1, "updated_at": 0, "artifacts": {}}


def _write_state(state: dict[str, Any]) -> None:
    try:
        LEDGER_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        state["updated_at"] = _now()
        LEDGER_STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    except Exception:
        pass


def _append_log(row: dict[str, Any]) -> None:
    try:
        LEDGER_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LEDGER_LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass


def _passed(status: str, score: float | None = None) -> bool:
    s = str(status or "").strip().lower()
    if s in FAIL_STATUSES:
        return False
    if s in PASS_STATUSES:
        return True
    if score is not None:
        return float(score) >= 0.6
    return False


def _requirements(kind: str, required: set[str] | list[str] | None = None) -> set[str]:
    if required is not None:
        return {str(x) for x in required if str(x).strip()}
    return set(DEFAULT_REQUIREMENTS.get(str(kind), {"external"}))


def _summarize_evidence(evidence: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for ev in evidence:
        ev_type = str(ev.get("evidence_type") or "unknown")
        bucket = out.setdefault(ev_type, {"passed": 0, "failed": 0, "latest_status": None, "best_score": 0.0})
        score = float(ev.get("score") or 0.0)
        bucket["best_score"] = max(float(bucket.get("best_score") or 0.0), score)
        bucket["latest_status"] = ev.get("status")
        if bool(ev.get("passed")):
            bucket["passed"] += 1
        else:
            bucket["failed"] += 1
    return out


def assess_artifact(
    artifact_kind: str,
    artifact_id: str,
    *,
    required: set[str] | list[str] | None = None,
    state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    st = state or _read_state()
    key = _artifact_key(artifact_kind, artifact_id)
    artifact = (st.get("artifacts") or {}).get(key) or {}
    evidence = artifact.get("evidence") if isinstance(artifact.get("evidence"), list) else []
    summary = _summarize_evidence(evidence)
    req = _requirements(artifact_kind, required)
    satisfied = sorted(ev_type for ev_type in req if int((summary.get(ev_type) or {}).get("passed") or 0) > 0)
    missing = sorted(ev_type for ev_type in req if ev_type not in satisfied)
    failed_required = sorted(
        ev_type
        for ev_type in req
        if int((summary.get(ev_type) or {}).get("failed") or 0) > 0
        and int((summary.get(ev_type) or {}).get("passed") or 0) <= 0
    )
    blockers = [f"missing_{x}_evidence" for x in missing] + [f"failed_{x}_evidence" for x in failed_required]
    return {
        "ok": True,
        "artifact_kind": artifact_kind,
        "artifact_id": artifact_id,
        "required_evidence": sorted(req),
        "satisfied_evidence": satisfied,
        "missing_evidence": missing,
        "failed_required_evidence": failed_required,
        "promotion_ready": not blockers,
        "blockers": blockers,
        "evidence_summary": summary,
        "evidence_count": len(evidence),
        "claim": artifact.get("claim"),
        "metadata": artifact.get("metadata") if isinstance(artifact.get("metadata"), dict) else {},
    }


def record_evidence(
    *,
    artifact_kind: str,
    artifact_id: str,
    evidence_type: str,
    status: str,
    score: float | None = None,
    source: str = "unknown",
    claim: str | None = None,
    payload: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    required: set[str] | list[str] | None = None,
) -> dict[str, Any]:
    st = _read_state()
    artifacts = st.setdefault("artifacts", {})
    key = _artifact_key(artifact_kind, artifact_id)
    artifact = artifacts.setdefault(
        key,
        {
            "artifact_kind": artifact_kind,
            "artifact_id": artifact_id,
            "claim": claim or "",
            "metadata": {},
            "created_at": _now(),
            "evidence": [],
        },
    )
    if claim:
        artifact["claim"] = _clip(claim, 1200)
    if metadata:
        existing = artifact.get("metadata") if isinstance(artifact.get("metadata"), dict) else {}
        existing.update(metadata)
        artifact["metadata"] = existing

    ev = {
        "evidence_id": f"ev_{_now()}_{_hash([artifact_kind, artifact_id, evidence_type, source, payload])[:8]}",
        "ts": _now(),
        "evidence_type": str(evidence_type),
        "status": str(status),
        "passed": _passed(str(status), score),
        "score": None if score is None else round(max(0.0, min(1.0, float(score))), 4),
        "source": str(source),
        "payload": payload or {},
    }
    evidence = artifact.setdefault("evidence", [])
    evidence.append(ev)
    artifact["evidence"] = evidence[-80:]
    assessment = assess_artifact(artifact_kind, artifact_id, required=required, state=st)
    artifact["last_assessment"] = assessment
    _write_state(st)
    _append_log({"event": "evidence_recorded", **ev, "artifact_kind": artifact_kind, "artifact_id": artifact_id})
    return assessment


def record_external_verification(
    *,
    query: str,
    answer: Any,
    verification: dict[str, Any],
    artifact_id: str | None = None,
) -> dict[str, Any]:
    art_id = artifact_id or artifact_id_for("factual_claim", {"query": query, "answer": answer})
    factual = verification.get("factual_eval") if isinstance(verification.get("factual_eval"), dict) else {}
    cross = verification.get("cross_modal") if isinstance(verification.get("cross_modal"), dict) else {}
    result = None
    if factual.get("has_ground_truth"):
        result = record_evidence(
            artifact_kind="factual_claim",
            artifact_id=art_id,
            evidence_type="external",
            status="passed" if factual.get("factual_correct") else "failed",
            score=float(factual.get("factual_score") or (1.0 if factual.get("factual_correct") else 0.0)),
            source=str(factual.get("ground_truth_source") or "ground_truth"),
            claim=_clip(query, 700),
            payload={"query": _clip(query), "answer": str(answer)[:1000], "factual_eval": factual},
        )
    if cross:
        status = "failed" if cross.get("needs_revision") else ("passed" if int(cross.get("passed_count") or 0) > 0 else "unavailable")
        result = record_evidence(
            artifact_kind="factual_claim",
            artifact_id=art_id,
            evidence_type="cross_modal",
            status=status,
            score=1.0 - min(1.0, float(cross.get("surprise_score") or 0.0)),
            source="cross_modal_validation",
            claim=_clip(query, 700),
            payload={"cross_modal": cross},
        )
    return result or assess_artifact("factual_claim", art_id)


def record_patch_promotion_evidence(
    patch: dict[str, Any],
    *,
    factual_gate: dict[str, Any],
    shadow_metrics: dict[str, Any],
    canary_state: dict[str, Any],
    domain_regression: dict[str, Any] | None = None,
) -> dict[str, Any]:
    patch_id = str(patch.get("id") or patch.get("patch_id") or artifact_id_for("patch", patch))
    claim = _clip(patch.get("hypothesis") or patch.get("problem_pattern") or patch_id, 700)
    cases_total = int(shadow_metrics.get("cases_total") or 0)
    delta = float(shadow_metrics.get("delta") or 0.0)
    factual_cases = int(factual_gate.get("cases_total") or 0)
    factual_accuracy = float(factual_gate.get("candidate_factual_accuracy") or 0.0)
    factual_failures = int(factual_gate.get("external_anchor_failures") or 0)

    if factual_cases > 0:
        ext_status = "passed" if factual_accuracy >= 1.0 and factual_failures == 0 else "failed"
        ext_score = factual_accuracy
        ext_source = "external_factual_anchor"
    else:
        ext_status = "passed" if cases_total > 0 and delta >= 0.0 else "failed"
        ext_score = max(0.0, min(1.0, 0.6 + delta)) if ext_status == "passed" else 0.0
        ext_source = "external_behavior_shadow_eval"

    record_evidence(
        artifact_kind="patch",
        artifact_id=patch_id,
        evidence_type="external",
        status=ext_status,
        score=ext_score,
        source=ext_source,
        claim=claim,
        payload={"factual_gate": factual_gate, "shadow_metrics": shadow_metrics},
    )
    record_evidence(
        artifact_kind="patch",
        artifact_id=patch_id,
        evidence_type="counterfactual",
        status="passed" if cases_total > 0 and delta >= 0.0 else "failed",
        score=max(0.0, min(1.0, 0.5 + delta)),
        source="shadow_baseline_vs_candidate",
        claim=claim,
        payload={"shadow_metrics": shadow_metrics, "domain_regression": domain_regression or {}},
    )
    return record_evidence(
        artifact_kind="patch",
        artifact_id=patch_id,
        evidence_type="longitudinal",
        status="passed" if bool(canary_state.get("enabled")) and int(canary_state.get("rollout_pct") or 0) > 0 else "failed",
        score=min(1.0, max(0.0, int(canary_state.get("rollout_pct") or 0) / 100.0 + 0.5)),
        source="canary_rollout",
        claim=claim,
        payload={"canary_state": canary_state},
    )


def record_competency_evidence(
    *,
    artifact_id: str,
    claim: str,
    actual_success: bool,
    alternatives_count: int,
    longitudinal_support: int,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    record_evidence(
        artifact_kind="competency",
        artifact_id=artifact_id,
        evidence_type="external",
        status="passed" if actual_success else "failed",
        score=1.0 if actual_success else 0.0,
        source="observed_outcome",
        claim=claim,
        payload=payload or {},
    )
    record_evidence(
        artifact_kind="competency",
        artifact_id=artifact_id,
        evidence_type="counterfactual",
        status="passed" if alternatives_count >= 1 else "failed",
        score=min(1.0, 0.5 + alternatives_count * 0.1),
        source="hypothesis_alternatives",
        claim=claim,
        payload={"alternatives_count": alternatives_count, **(payload or {})},
    )
    return record_evidence(
        artifact_kind="competency",
        artifact_id=artifact_id,
        evidence_type="longitudinal",
        status="passed" if longitudinal_support >= 1 else "failed",
        score=min(1.0, 0.55 + longitudinal_support * 0.1),
        source="repeated_scenario_success",
        claim=claim,
        payload={"longitudinal_support": longitudinal_support, **(payload or {})},
    )


def record_causal_rule_evidence(
    *,
    artifact_id: str,
    claim: str,
    compression_report: dict[str, Any],
) -> dict[str, Any]:
    support = int(((compression_report.get("compressed_power") or {}).get("support")) or compression_report.get("support") or 0)
    retained = float(compression_report.get("predictive_power_retained") or 0.0)
    gain = float(compression_report.get("compression_gain") or 0.0)
    dropped = compression_report.get("dropped_dimensions") or compression_report.get("dropped_dimension") or []
    record_evidence(
        artifact_kind="causal_rule",
        artifact_id=artifact_id,
        evidence_type="external",
        status="passed" if retained >= 0.6 and support >= 2 else "failed",
        score=retained,
        source="world_model_transition_history",
        claim=claim,
        payload=compression_report,
    )
    record_evidence(
        artifact_kind="causal_rule",
        artifact_id=artifact_id,
        evidence_type="counterfactual",
        status="passed" if dropped and gain > 0 else "failed",
        score=min(1.0, 0.5 + gain),
        source="kolmogorov_premise_ablation",
        claim=claim,
        payload=compression_report,
    )
    return record_evidence(
        artifact_kind="causal_rule",
        artifact_id=artifact_id,
        evidence_type="longitudinal",
        status="passed" if support >= 2 else "failed",
        score=min(1.0, support / 10.0),
        source="repeated_transition_support",
        claim=claim,
        payload={"support": support, "compression_report": compression_report},
    )


def record_longitudinal_harness(result: dict[str, Any]) -> dict[str, Any]:
    metrics = result.get("metrics") if isinstance(result.get("metrics"), dict) else {}
    success_rate = float(metrics.get("success_rate") or 0.0)
    artifact_id = "ultronpro_cognitive_core"
    record_evidence(
        artifact_kind="system_capability",
        artifact_id=artifact_id,
        evidence_type="external",
        status="passed" if success_rate >= 0.6 else "failed",
        score=success_rate,
        source="longitudinal_harness_generalization",
        claim="UltronPro cognitive core maintains externally checked capabilities",
        payload={"generalization": result.get("generalization")},
    )
    record_evidence(
        artifact_kind="system_capability",
        artifact_id=artifact_id,
        evidence_type="counterfactual",
        status="passed" if float((result.get("resilience") or {}).get("success_rate") or 0.0) >= 0.6 else "failed",
        score=float((result.get("resilience") or {}).get("success_rate") or 0.0),
        source="resilience_failure_simulation",
        claim="UltronPro cognitive core handles counterfactual failure modes",
        payload={"resilience": result.get("resilience")},
    )
    return record_evidence(
        artifact_kind="system_capability",
        artifact_id=artifact_id,
        evidence_type="longitudinal",
        status="passed" if float((result.get("drift") or {}).get("drift_score") or 1.0) <= 0.2 else "failed",
        score=1.0 - min(1.0, float((result.get("drift") or {}).get("drift_score") or 1.0)),
        source="capacity_drift_monitor",
        claim="UltronPro cognitive core preserves older capabilities over time",
        payload={"drift": result.get("drift"), "metrics": metrics},
    )


def status(limit: int = 20) -> dict[str, Any]:
    st = _read_state()
    artifacts = st.get("artifacts") if isinstance(st.get("artifacts"), dict) else {}
    rows = list(artifacts.values())
    rows.sort(key=lambda row: int(row.get("created_at") or 0), reverse=True)
    ready = sum(1 for row in rows if bool((row.get("last_assessment") or {}).get("promotion_ready")))
    return {
        "ok": True,
        "artifact_count": len(rows),
        "promotion_ready": ready,
        "blocked": len(rows) - ready,
        "items": rows[: max(1, int(limit or 1))],
        "state_path": str(LEDGER_STATE_PATH),
        "log_path": str(LEDGER_LOG_PATH),
    }


def run_selftest() -> dict[str, Any]:
    old_log_path = LEDGER_LOG_PATH
    old_state_path = LEDGER_STATE_PATH
    with tempfile.TemporaryDirectory(prefix="epistemic-ledger-") as td:
        globals()["LEDGER_LOG_PATH"] = Path(td) / "epistemic_ledger.jsonl"
        globals()["LEDGER_STATE_PATH"] = Path(td) / "epistemic_ledger_state.json"
        try:
            art_id = artifact_id_for("patch", {"selftest": "epistemic_ledger"})
            patch = {"id": art_id, "hypothesis": "external, counterfactual and longitudinal evidence must agree"}
            gate = record_patch_promotion_evidence(
                patch,
                factual_gate={"has_external_anchor": True, "cases_total": 1, "candidate_factual_accuracy": 1.0, "external_anchor_failures": 0},
                shadow_metrics={"cases_total": 2, "delta": 0.08},
                canary_state={"enabled": True, "rollout_pct": 10},
                domain_regression={},
            )
            blocked_id = artifact_id_for("patch", {"selftest": "blocked"})
            blocked = record_evidence(
                artifact_kind="patch",
                artifact_id=blocked_id,
                evidence_type="external",
                status="passed",
                score=1.0,
                source="selftest",
                claim="missing counterfactual and longitudinal evidence should block promotion",
            )
            return {
                "ok": True,
                "ready_gate": gate,
                "blocked_gate": blocked,
                "passed": bool(gate.get("promotion_ready")) and not bool(blocked.get("promotion_ready")),
            }
        finally:
            globals()["LEDGER_LOG_PATH"] = old_log_path
            globals()["LEDGER_STATE_PATH"] = old_state_path
