import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def test_quality_eval_anchors_to_external_benchmark_and_records_her(tmp_path):
    from ultronpro import external_benchmarks, quality_eval

    old_hindsight = external_benchmarks.HINDSIGHT_PATH
    old_cross = external_benchmarks.CROSS_MODAL_PATH
    external_benchmarks.HINDSIGHT_PATH = tmp_path / "hindsight.jsonl"
    external_benchmarks.CROSS_MODAL_PATH = tmp_path / "cross.jsonl"
    try:
        wrong = quality_eval.evaluate_response(
            query="Na logica proposicional, negacao de P e Q?",
            answer=json.dumps({"answer": "A"}),
            context_meta={"external_benchmark_id": "mmlu_001"},
        )
        assert wrong["composite_score"] == 0.1
        assert wrong["is_anchor_failure"] is True
        assert wrong["factual_eval"]["gold_answer"] == "B"
        assert wrong["hindsight_replay"]["correct_solution"]
        assert external_benchmarks.HINDSIGHT_PATH.exists()

        correct = quality_eval.evaluate_response(
            query="Na logica proposicional, negacao de P e Q?",
            answer=json.dumps({"answer": "B"}),
            context_meta={"external_benchmark_id": "mmlu_001"},
        )
        assert correct["composite_score"] >= 0.97
        assert correct["threshold_breached"] is False
        assert correct["factual_eval"]["factual_correct"] is True
    finally:
        external_benchmarks.HINDSIGHT_PATH = old_hindsight
        external_benchmarks.CROSS_MODAL_PATH = old_cross


def test_shadow_eval_feeds_factual_evidence_to_promotion_gate(tmp_path):
    from ultronpro import cognitive_patches, epistemic_ledger, promotion_gate, shadow_eval

    old_ledger_log = epistemic_ledger.LEDGER_LOG_PATH
    old_ledger_state = epistemic_ledger.LEDGER_STATE_PATH
    old_patch_path = cognitive_patches.PATCHES_PATH
    old_state_path = cognitive_patches.STATE_PATH
    old_shadow_log = shadow_eval.LOG_PATH
    old_canary_log = shadow_eval.CANARY_LOG_PATH
    epistemic_ledger.LEDGER_LOG_PATH = tmp_path / "epistemic_ledger.jsonl"
    epistemic_ledger.LEDGER_STATE_PATH = tmp_path / "epistemic_ledger_state.json"
    cognitive_patches.PATCHES_PATH = tmp_path / "patches.jsonl"
    cognitive_patches.STATE_PATH = tmp_path / "patches_state.json"
    shadow_eval.LOG_PATH = tmp_path / "shadow.jsonl"
    shadow_eval.CANARY_LOG_PATH = tmp_path / "canary.jsonl"
    try:
        patch = cognitive_patches.create_patch({
            "kind": "heuristic_patch",
            "source": "test",
            "problem_pattern": "academic_mcq: mmlu factual correction",
            "hypothesis": "Use external gold answers for MCQ validation.",
            "status": "evaluating",
        })
        shadow_eval.compare_patch_candidate(patch["id"], [{
            "case_id": "mmlu_001_anchor",
            "domain": "academic_mcq",
            "query": "Na logica proposicional, a negacao de P e Q?",
            "baseline_answer": json.dumps({"answer": "A"}),
            "candidate_answer": json.dumps({"answer": "B"}),
            "ground_truth": "B",
        }])
        shadow_eval.start_canary(patch["id"], rollout_pct=10, domains=["academic_mcq"])

        gate = promotion_gate.evaluate_patch_for_promotion(patch["id"])

        assert gate["decision"] == "promote"
        assert "external_factual_accuracy_ok" in gate["reasons"]
        assert gate["summary"]["external_factual"]["candidate_factual_accuracy"] == 1.0
    finally:
        epistemic_ledger.LEDGER_LOG_PATH = old_ledger_log
        epistemic_ledger.LEDGER_STATE_PATH = old_ledger_state
        cognitive_patches.PATCHES_PATH = old_patch_path
        cognitive_patches.STATE_PATH = old_state_path
        shadow_eval.LOG_PATH = old_shadow_log
        shadow_eval.CANARY_LOG_PATH = old_canary_log


def test_cross_modal_code_failure_caps_quality_with_surprise(tmp_path):
    from ultronpro import external_benchmarks, quality_eval

    old_cross = external_benchmarks.CROSS_MODAL_PATH
    external_benchmarks.CROSS_MODAL_PATH = tmp_path / "cross.jsonl"
    try:
        result = quality_eval.evaluate_response(
            query="Este codigo executa com sucesso?",
            answer="Sim, executa com sucesso.",
            context_meta={
                "code_validation": {
                    "language": "python",
                    "sandbox_result": {
                        "ok": False,
                        "returncode": 1,
                        "stdout": "",
                        "stderr": "AssertionError",
                    },
                    "expected_returncode": 0,
                }
            },
        )

        assert result["composite_score"] <= 0.35
        assert result["threshold_breached"] is True
        assert "cross_modal_validation_failed" in result["alerts"]
        assert result["cross_modal"]["surprise_score"] >= 0.9
    finally:
        external_benchmarks.CROSS_MODAL_PATH = old_cross


def test_quality_persistence_updates_rl_with_external_grounded_reward(tmp_path):
    from ultronpro import quality_eval, rl_policy

    old_log = quality_eval.LOG_PATH
    old_state = rl_policy.STATE_PATH
    quality_eval.LOG_PATH = tmp_path / "quality.jsonl"
    rl_policy.STATE_PATH = tmp_path / "rl_state.json"
    try:
        bad = quality_eval.evaluate_response(
            query="De Morgan",
            answer=json.dumps({"answer": "A"}),
            context_meta={"ground_truth": "B"},
        )
        quality_eval.persist_eval({
            "strategy": "mcq_solver",
            "task_type": "academic_mcq",
            "quality_eval": bad,
        })

        good = quality_eval.evaluate_response(
            query="De Morgan",
            answer=json.dumps({"answer": "B"}),
            context_meta={"ground_truth": "B"},
        )
        quality_eval.persist_eval({
            "strategy": "mcq_solver",
            "task_type": "academic_mcq",
            "quality_eval": good,
        })
        quality_eval.persist_eval({
            "strategy": "mcq_solver",
            "task_type": "academic_mcq",
            "quality_eval": good,
        })

        state = json.loads(rl_policy.STATE_PATH.read_text(encoding="utf-8"))
        arm = state["arms"]["mcq_solver|academic_mcq"]
        assert arm["n"] == 3
        assert arm["last_reward"] >= 0.97
        assert arm["alpha"] > arm["beta"]
    finally:
        quality_eval.LOG_PATH = old_log
        rl_policy.STATE_PATH = old_state


def test_rl_observe_alias_keeps_mental_simulation_learning_hook_live(tmp_path):
    from ultronpro import rl_policy

    old_state = rl_policy.STATE_PATH
    rl_policy.STATE_PATH = tmp_path / "rl_state.json"
    try:
        result = rl_policy.observe("hypothesis", "mental_simulation", 0.8)
        assert result["ok"] is True
        assert result["key"] == "hypothesis|mental_simulation"
        assert result["arm"]["last_reward"] == 0.8
    finally:
        rl_policy.STATE_PATH = old_state


def test_mental_simulation_longitudinal_probe_consolidates_competency():
    from ultronpro import mental_simulation

    result = mental_simulation.longitudinal_probe(cycles=6, persist=False)

    assert result["ok"] is True
    assert result["isolated"] is True
    assert result["passed"] is True
    assert result["reusable_competencies"] >= 1
    assert result["second_half_avg_surprise"] <= result["first_half_avg_surprise"]
