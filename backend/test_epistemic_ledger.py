import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _patch_ledger_paths(epistemic_ledger, tmp_path):
    old = (epistemic_ledger.LEDGER_LOG_PATH, epistemic_ledger.LEDGER_STATE_PATH)
    epistemic_ledger.LEDGER_LOG_PATH = tmp_path / "epistemic_ledger.jsonl"
    epistemic_ledger.LEDGER_STATE_PATH = tmp_path / "epistemic_ledger_state.json"
    return old


def test_epistemic_ledger_blocks_until_external_counterfactual_and_longitudinal_exist(tmp_path):
    from ultronpro import epistemic_ledger

    old_paths = _patch_ledger_paths(epistemic_ledger, tmp_path)
    try:
        patch_id = "patch_needs_three_evidence_types"
        first = epistemic_ledger.record_evidence(
            artifact_kind="patch",
            artifact_id=patch_id,
            evidence_type="external",
            status="passed",
            score=1.0,
            source="unit_test",
            claim="promotion must not be circular",
        )
        assert first["promotion_ready"] is False
        assert "counterfactual" in first["missing_evidence"]
        assert "longitudinal" in first["missing_evidence"]

        epistemic_ledger.record_evidence(
            artifact_kind="patch",
            artifact_id=patch_id,
            evidence_type="counterfactual",
            status="passed",
            score=0.8,
            source="unit_test",
        )
        ready = epistemic_ledger.record_evidence(
            artifact_kind="patch",
            artifact_id=patch_id,
            evidence_type="longitudinal",
            status="passed",
            score=0.75,
            source="unit_test",
        )

        assert ready["promotion_ready"] is True
        assert ready["satisfied_evidence"] == ["counterfactual", "external", "longitudinal"]
        assert epistemic_ledger.LEDGER_STATE_PATH.exists()
    finally:
        epistemic_ledger.LEDGER_LOG_PATH, epistemic_ledger.LEDGER_STATE_PATH = old_paths


def test_external_verification_records_factual_claim_in_ledger(tmp_path):
    from ultronpro import epistemic_ledger, external_benchmarks, quality_eval

    old_ledger = _patch_ledger_paths(epistemic_ledger, tmp_path)
    old_hindsight = external_benchmarks.HINDSIGHT_PATH
    old_cross = external_benchmarks.CROSS_MODAL_PATH
    external_benchmarks.HINDSIGHT_PATH = tmp_path / "hindsight.jsonl"
    external_benchmarks.CROSS_MODAL_PATH = tmp_path / "cross.jsonl"
    try:
        result = quality_eval.evaluate_response(
            query="De Morgan",
            answer=json.dumps({"answer": "B"}),
            context_meta={"ground_truth": "B"},
        )

        ledger_gate = result["external_verification"]["epistemic_ledger"]
        assert ledger_gate["artifact_kind"] == "factual_claim"
        assert ledger_gate["promotion_ready"] is True
        assert ledger_gate["satisfied_evidence"] == ["external"]
        assert epistemic_ledger.status()["artifact_count"] == 1
    finally:
        epistemic_ledger.LEDGER_LOG_PATH, epistemic_ledger.LEDGER_STATE_PATH = old_ledger
        external_benchmarks.HINDSIGHT_PATH = old_hindsight
        external_benchmarks.CROSS_MODAL_PATH = old_cross


def test_promotion_gate_requires_and_records_epistemic_ledger_evidence(tmp_path):
    from ultronpro import cognitive_patches, epistemic_ledger, promotion_gate, shadow_eval

    old_ledger = _patch_ledger_paths(epistemic_ledger, tmp_path)
    old_patch_path = cognitive_patches.PATCHES_PATH
    old_state_path = cognitive_patches.STATE_PATH
    old_shadow_log = shadow_eval.LOG_PATH
    old_canary_log = shadow_eval.CANARY_LOG_PATH
    cognitive_patches.PATCHES_PATH = tmp_path / "patches.jsonl"
    cognitive_patches.STATE_PATH = tmp_path / "patches_state.json"
    shadow_eval.LOG_PATH = tmp_path / "shadow.jsonl"
    shadow_eval.CANARY_LOG_PATH = tmp_path / "canary.jsonl"
    try:
        patch = cognitive_patches.create_patch({
            "kind": "heuristic_patch",
            "source": "test",
            "problem_pattern": "academic_mcq: factual anchor",
            "hypothesis": "Candidate must use external anchors before promotion.",
            "status": "evaluating",
        })
        shadow_eval.compare_patch_candidate(patch["id"], [{
            "case_id": "anchor_case",
            "domain": "academic_mcq",
            "query": "Qual resposta correta?",
            "baseline_answer": json.dumps({"answer": "A"}),
            "candidate_answer": json.dumps({"answer": "B"}),
            "ground_truth": "B",
        }])
        shadow_eval.start_canary(patch["id"], rollout_pct=10, domains=["academic_mcq"])

        gate = promotion_gate.evaluate_patch_for_promotion(patch["id"])
        ledger_gate = gate["summary"]["epistemic_ledger"]

        assert gate["decision"] == "promote"
        assert "epistemic_ledger_ready" in gate["reasons"]
        assert ledger_gate["promotion_ready"] is True
        assert ledger_gate["satisfied_evidence"] == ["counterfactual", "external", "longitudinal"]
    finally:
        epistemic_ledger.LEDGER_LOG_PATH, epistemic_ledger.LEDGER_STATE_PATH = old_ledger
        cognitive_patches.PATCHES_PATH = old_patch_path
        cognitive_patches.STATE_PATH = old_state_path
        shadow_eval.LOG_PATH = old_shadow_log
        shadow_eval.CANARY_LOG_PATH = old_canary_log


def test_epistemic_ledger_api_selftest(tmp_path):
    from ultronpro import epistemic_ledger
    from ultronpro.api import benchmarks

    old_ledger = _patch_ledger_paths(epistemic_ledger, tmp_path)
    try:
        result = asyncio.run(benchmarks.benchmark_epistemic_ledger())

        assert result["ok"] is True
        assert result["passed"] is True
        assert result["ready_gate"]["promotion_ready"] is True
        assert result["blocked_gate"]["promotion_ready"] is False
    finally:
        epistemic_ledger.LEDGER_LOG_PATH, epistemic_ledger.LEDGER_STATE_PATH = old_ledger
