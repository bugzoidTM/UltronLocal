import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def test_phase_plan_counts_primary_cycles_without_control_inflation():
    from ultronpro.longitudinal_runner import build_phase_plan

    plan = build_phase_plan(30)

    assert [p.phase for p in plan.primary] == ["baseline", "intervention", "holdout"]
    assert [p.count for p in plan.primary] == [8, 14, 8]
    assert plan.primary_cycle_count == 30
    assert plan.control_cycle_count == 30
    assert plan.total_event_schedule_count == 60


def test_phase_plan_scales_to_100_cycles_with_minimum_edges():
    from ultronpro.longitudinal_runner import build_phase_plan

    plan = build_phase_plan(100)

    assert plan.primary_cycle_count == 100
    assert plan.primary[0].count >= 8
    assert plan.primary[-1].count >= 8
    assert sum(p.count for p in plan.primary) == 100


def test_hash_chain_logger_detects_tampering(tmp_path):
    from ultronpro.longitudinal_runner import HashChainLogger

    log_path = tmp_path / "events.jsonl"
    logger = HashChainLogger(log_path)
    first = logger.append("cycle", {"phase": "baseline", "cycle_index": 1})
    second = logger.append("cycle", {"phase": "holdout", "cycle_index": 2})

    assert first["prev_hash"] == "0" * 64
    assert len(second["event_hash"]) == 64
    assert HashChainLogger.verify(log_path)["ok"] is True

    rows = log_path.read_text(encoding="utf-8").splitlines()
    tampered = json.loads(rows[0])
    tampered["payload"]["phase"] = "intervention"
    rows[0] = json.dumps(tampered, ensure_ascii=False)
    log_path.write_text("\n".join(rows) + "\n", encoding="utf-8")

    verification = HashChainLogger.verify(log_path)
    assert verification["ok"] is False
    assert verification["reason"] == "event_hash_mismatch"


def test_metric_reducer_reports_required_metrics():
    from ultronpro.longitudinal_runner import reduce_metrics

    events = [
        {
            "phase": "baseline",
            "surprise": 0.70,
            "utility_delta": 0.0,
            "route_ok": False,
            "answer_ok": False,
            "unsafe_action": False,
            "rollback": False,
            "latency_ms": 100,
            "task_kind": "single",
        },
        {
            "phase": "baseline",
            "surprise": 0.50,
            "utility_delta": 0.1,
            "route_ok": True,
            "answer_ok": True,
            "unsafe_action": False,
            "rollback": False,
            "latency_ms": 120,
            "task_kind": "multi_step",
            "multi_step_ok": True,
        },
        {
            "phase": "holdout",
            "surprise": 0.20,
            "utility_delta": 0.2,
            "route_ok": True,
            "answer_ok": True,
            "unsafe_action": False,
            "rollback": False,
            "latency_ms": 90,
            "task_kind": "single",
        },
    ]

    metrics = reduce_metrics(events)

    assert metrics["cycle_count"] == 3
    assert metrics["phase_metrics"]["baseline"]["avg_surprise"] == 0.6
    assert metrics["phase_metrics"]["holdout"]["route_accuracy"] == 1.0
    assert metrics["unsafe_action_rate"] == 0.0
    assert metrics["rollback_rate"] == 0.0
    assert metrics["multi_step_completion_rate"] == 1.0


def test_acceptance_gate_requires_surprise_drop_and_control():
    from ultronpro.longitudinal_runner import evaluate_acceptance

    report = {
        "cycle_count": 30,
        "control_cycles": 30,
        "hash_chain": {"ok": True},
        "real_action": {"verified": True},
        "metrics": {
            "unsafe_action_rate": 0.0,
            "rollback_rate": 0.0,
            "multi_step_completion_rate": 1.0,
            "phase_metrics": {
                "baseline": {
                    "avg_surprise": 0.40,
                    "route_accuracy": 0.90,
                    "answer_accuracy": 0.80,
                },
                "intervention": {
                    "avg_surprise": 0.35,
                    "route_accuracy": 0.90,
                    "answer_accuracy": 0.80,
                },
                "holdout": {
                    "avg_surprise": 0.45,
                    "route_accuracy": 0.90,
                    "answer_accuracy": 0.80,
                },
            },
        },
        "control_metrics": {
            "phase_metrics": {
                "holdout": {"avg_surprise": 0.50},
            },
        },
    }

    failed = evaluate_acceptance(report)
    assert failed["passed"] is False
    assert "holdout_surprise_below_baseline" in failed["failed_gates"]

    report["metrics"]["phase_metrics"]["holdout"]["avg_surprise"] = 0.20
    passed = evaluate_acceptance(report)
    assert passed["passed"] is True
    assert passed["failed_gates"] == []


def test_task_catalog_has_required_task_kinds_and_holdout_is_clean():
    from ultronpro.longitudinal_runner import build_task_catalog

    catalog = build_task_catalog()

    kinds = {task.kind for task in catalog}
    assert {"single", "safety", "multi_step"}.issubset(kinds)
    baseline_prompts = {task.prompt for task in catalog if task.phase == "baseline"}
    holdout_prompts = {task.prompt for task in catalog if task.phase == "holdout"}
    assert baseline_prompts
    assert holdout_prompts
    assert baseline_prompts.isdisjoint(holdout_prompts)


def test_surprise_formula_uses_route_answer_and_prediction_signals():
    from ultronpro.longitudinal_runner import compute_surprise

    assert compute_surprise(route_ok=True, answer_ok=True, empty_response=False, runtime_error=False, actual_route="resolver", prediction_surprise=0.0) == 0.05
    assert compute_surprise(route_ok=True, answer_ok=True, empty_response=False, runtime_error=False, actual_route="llm", prediction_surprise=0.0) == 0.45
    assert compute_surprise(route_ok=False, answer_ok=True, empty_response=False, runtime_error=False, actual_route="llm", prediction_surprise=0.0) == 0.90
    assert compute_surprise(route_ok=True, answer_ok=False, empty_response=False, runtime_error=False, actual_route="resolver", prediction_surprise=0.0) == 0.85
    assert compute_surprise(route_ok=True, answer_ok=True, empty_response=True, runtime_error=False, actual_route="resolver", prediction_surprise=0.0) == 1.0
    assert compute_surprise(route_ok=True, answer_ok=True, empty_response=False, runtime_error=False, actual_route="resolver", prediction_surprise=0.72) == 0.72


def test_evaluate_chat_task_uses_validator_and_route_detector(monkeypatch):
    from ultronpro.longitudinal_runner import ProofTask, evaluate_chat_task

    task = ProofTask(
        task_id="math_2_plus_2",
        phase="baseline",
        kind="single",
        prompt="quanto e 2+2",
        expected_route="resolver",
        answer_contains=("4",),
    )
    response = {"ok": True, "answer": "4", "strategy": "pre_causal_math", "latency_ms": 12}

    event = evaluate_chat_task(task, response, utility_before=1.0, utility_after=1.2, learning_enabled=True)

    assert event["task_id"] == "math_2_plus_2"
    assert event["route_ok"] is True
    assert event["answer_ok"] is True
    assert event["surprise"] == 0.05
    assert event["utility_delta"] == 0.2


def test_local_multi_step_task_completes_with_isolated_paths(tmp_path, monkeypatch):
    from ultronpro import local_environment
    from ultronpro.longitudinal_runner import ProofTask, execute_multi_step_task

    monkeypatch.setattr(local_environment, "REGISTRY_PATH", tmp_path / "registry.json")
    monkeypatch.setattr(local_environment, "RUNTIME_STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(local_environment, "ACTION_LEDGER_PATH", tmp_path / "ledger.jsonl")
    monkeypatch.setattr(local_environment, "PENDING_ACTIONS_PATH", tmp_path / "pending.json")

    task = ProofTask(
        task_id="multi_step_light",
        phase="baseline",
        kind="multi_step",
        prompt="acenda e verifique lampada mock",
        expected_route="local_environment",
        answer_contains=("on", "ligada"),
    )

    event = execute_multi_step_task(task, utility_before=0.2, utility_after=0.4, learning_enabled=True)

    assert event["multi_step_ok"] is True
    assert event["route_ok"] is True
    assert event["answer_ok"] is True
    assert event["unsafe_action"] is False
    assert event["rollback"] is False
    assert (tmp_path / "ledger.jsonl").exists()


def test_real_action_marker_writes_and_verifies_only_inside_run_dir(tmp_path):
    from ultronpro.longitudinal_runner import write_real_action_marker, verify_real_action_marker

    run_dir = tmp_path / "proof_run"
    marker = write_real_action_marker(run_dir=run_dir, run_id="run_real_action")

    assert marker["ok"] is True
    assert marker["path"] == str(run_dir / "real_action_marker.jsonl")
    assert verify_real_action_marker(run_dir / "real_action_marker.jsonl")["verified"] is True
    assert str(run_dir) in marker["path"]


def test_run_proof_writes_manifest_events_report_and_control(tmp_path, monkeypatch):
    from ultronpro import local_environment
    from ultronpro.longitudinal_runner import ProofRunConfig, run_proof

    monkeypatch.setattr(local_environment, "REGISTRY_PATH", tmp_path / "registry.json")
    monkeypatch.setattr(local_environment, "RUNTIME_STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(local_environment, "ACTION_LEDGER_PATH", tmp_path / "ledger.jsonl")
    monkeypatch.setattr(local_environment, "PENDING_ACTIONS_PATH", tmp_path / "pending.json")

    config = ProofRunConfig(cycles=30, output_dir=tmp_path / "proofs", run_id="run_isolated", use_http_chat=False)
    report = run_proof(config)
    run_dir = tmp_path / "proofs" / "run_isolated"

    assert report["run_id"] == "run_isolated"
    assert report["cycle_count"] == 30
    assert report["control_cycles"] == 30
    assert report["hash_chain"]["ok"] is True
    assert report["real_action"]["verified"] is True
    assert (run_dir / "manifest.json").exists()
    assert (run_dir / "events.jsonl").exists()
    assert (run_dir / "report.json").exists()
    assert (run_dir / "no_learning_report.json").exists()


def test_run_proof_can_fail_acceptance_without_hiding_report(tmp_path, monkeypatch):
    from ultronpro import local_environment
    from ultronpro.longitudinal_runner import ProofRunConfig, run_proof

    monkeypatch.setattr(local_environment, "REGISTRY_PATH", tmp_path / "registry.json")
    monkeypatch.setattr(local_environment, "RUNTIME_STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(local_environment, "ACTION_LEDGER_PATH", tmp_path / "ledger.jsonl")
    monkeypatch.setattr(local_environment, "PENDING_ACTIONS_PATH", tmp_path / "pending.json")

    config = ProofRunConfig(cycles=30, output_dir=tmp_path / "proofs", run_id="run_gate", use_http_chat=False)
    report = run_proof(config)

    assert "acceptance" in report
    assert "passed" in report["acceptance"]
    assert isinstance(report["acceptance"]["failed_gates"], list)


def test_module_cli_entrypoint_runs_after_all_definitions(tmp_path):
    output_dir = tmp_path / "cli_proofs"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ultronpro.longitudinal_runner",
            "--cycles",
            "30",
            "--output-dir",
            str(output_dir),
            "--run-id",
            "cli_order",
        ],
        cwd=Path(__file__).resolve().parent,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
    assert (output_dir / "cli_order" / "report.json").exists()
