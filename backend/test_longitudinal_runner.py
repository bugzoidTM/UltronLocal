import json
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
