import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _seed_active_investigation(active_investigation, tmp_path):
    report = {
        "ok": True,
        "resolved": True,
        "investigation_id": "inv_curriculum_gap",
        "ts": int(time.time()),
        "status": "needs_experiment",
        "reason": "no_structured_coverage",
        "task_type": "causal_validation",
        "query": "Como validar uma hipotese causal sem depender de correlacao visual?",
        "coverage": {"score": 0.18},
        "missing_slots": ["aresta_causal_relevante", "validacao_externa"],
        "next_experiment": {
            "kind": "causal_graph_enrichment",
            "target_route": "causal_validation",
            "query_terms": ["causal", "validar", "visual"],
            "action": "executar contrafactual de causa ausente e comparar o outcome",
            "acceptance": "o resultado deve separar causa real de correlacao espuria",
        },
    }
    active_investigation.INVESTIGATION_STATE_PATH.write_text(
        json.dumps(report, ensure_ascii=False),
        encoding="utf-8",
    )
    return report


def test_auto_curriculum_uses_active_investigation_and_progresses_difficulty(tmp_path):
    from ultronpro import active_investigation, auto_curriculum

    old_paths = (
        active_investigation.INVESTIGATION_LOG_PATH,
        active_investigation.INVESTIGATION_STATE_PATH,
        active_investigation.INVESTIGATION_EXECUTION_LOG_PATH,
        active_investigation.INVESTIGATION_EXECUTION_STATE_PATH,
        auto_curriculum.CURRICULUM_LOG_PATH,
        auto_curriculum.CURRICULUM_STATE_PATH,
    )
    active_investigation.INVESTIGATION_LOG_PATH = tmp_path / "active.jsonl"
    active_investigation.INVESTIGATION_STATE_PATH = tmp_path / "active_state.json"
    active_investigation.INVESTIGATION_EXECUTION_LOG_PATH = tmp_path / "active_exec.jsonl"
    active_investigation.INVESTIGATION_EXECUTION_STATE_PATH = tmp_path / "active_exec_state.json"
    auto_curriculum.CURRICULUM_LOG_PATH = tmp_path / "curriculum.jsonl"
    auto_curriculum.CURRICULUM_STATE_PATH = tmp_path / "curriculum_state.json"
    try:
        _seed_active_investigation(active_investigation, tmp_path)

        curriculum = auto_curriculum.generate_curriculum(limit=5, include_active_discovery=False)
        levels = [task["difficulty"] for task in curriculum["tasks"]]

        assert curriculum["ok"] is True
        assert curriculum["source_count"] == 1
        assert levels == sorted(levels)
        assert levels[0] == 1
        assert levels[-1] == 5
        assert all(task["self_relative"] is True for task in curriculum["tasks"])
        assert any("validacao_externa" in task["missing_slots"] for task in curriculum["tasks"])
        assert auto_curriculum.CURRICULUM_STATE_PATH.exists()

        next_tasks = auto_curriculum.next_tasks(limit=2, max_difficulty=2)
        assert next_tasks["count"] == 2
        assert all(task["difficulty"] <= 2 for task in next_tasks["tasks"])
    finally:
        (
            active_investigation.INVESTIGATION_LOG_PATH,
            active_investigation.INVESTIGATION_STATE_PATH,
            active_investigation.INVESTIGATION_EXECUTION_LOG_PATH,
            active_investigation.INVESTIGATION_EXECUTION_STATE_PATH,
            auto_curriculum.CURRICULUM_LOG_PATH,
            auto_curriculum.CURRICULUM_STATE_PATH,
        ) = old_paths


def test_self_predictive_model_forecasts_degradation_and_preventive_action():
    from ultronpro import self_predictive_model

    result = self_predictive_model.run_selftest()
    prediction = result["prediction"]

    assert result["passed"] is True
    assert prediction["degradation_risk"] >= 0.45
    assert prediction["recommendation"] in {"enter_conservative_mode", "request_human_help"}
    assert "success_rate_decline" in prediction["leading_indicators"]


def test_longitudinal_harness_runs_three_axes_and_feeds_predictor(tmp_path):
    from ultronpro import active_investigation, auto_curriculum, longitudinal_harness, self_predictive_model

    old_paths = (
        active_investigation.INVESTIGATION_LOG_PATH,
        active_investigation.INVESTIGATION_STATE_PATH,
        active_investigation.INVESTIGATION_EXECUTION_LOG_PATH,
        active_investigation.INVESTIGATION_EXECUTION_STATE_PATH,
        auto_curriculum.CURRICULUM_LOG_PATH,
        auto_curriculum.CURRICULUM_STATE_PATH,
        longitudinal_harness.HARNESS_LOG_PATH,
        longitudinal_harness.HARNESS_STATE_PATH,
        self_predictive_model.PREDICTIVE_LOG_PATH,
        self_predictive_model.PREDICTIVE_STATE_PATH,
    )
    active_investigation.INVESTIGATION_LOG_PATH = tmp_path / "active.jsonl"
    active_investigation.INVESTIGATION_STATE_PATH = tmp_path / "active_state.json"
    active_investigation.INVESTIGATION_EXECUTION_LOG_PATH = tmp_path / "active_exec.jsonl"
    active_investigation.INVESTIGATION_EXECUTION_STATE_PATH = tmp_path / "active_exec_state.json"
    auto_curriculum.CURRICULUM_LOG_PATH = tmp_path / "curriculum.jsonl"
    auto_curriculum.CURRICULUM_STATE_PATH = tmp_path / "curriculum_state.json"
    longitudinal_harness.HARNESS_LOG_PATH = tmp_path / "harness.jsonl"
    longitudinal_harness.HARNESS_STATE_PATH = tmp_path / "harness_state.json"
    self_predictive_model.PREDICTIVE_LOG_PATH = tmp_path / "predictive.jsonl"
    self_predictive_model.PREDICTIVE_STATE_PATH = tmp_path / "predictive_state.json"
    try:
        _seed_active_investigation(active_investigation, tmp_path)

        result = longitudinal_harness.run_cycle(curriculum_limit=8, persist=True)

        assert result["ok"] is True
        assert result["generalization"]["axis"] == "generalization"
        assert result["resilience"]["axis"] == "resilience"
        assert result["drift"]["axis"] == "capacity_drift"
        assert result["curriculum"]["task_count"] >= 5
        assert result["metrics"]["zero_shot_task_count"] >= 1
        assert result["predictive_model"]["prediction"]["ok"] is True
        assert longitudinal_harness.HARNESS_STATE_PATH.exists()
        assert self_predictive_model.PREDICTIVE_LOG_PATH.exists()
    finally:
        (
            active_investigation.INVESTIGATION_LOG_PATH,
            active_investigation.INVESTIGATION_STATE_PATH,
            active_investigation.INVESTIGATION_EXECUTION_LOG_PATH,
            active_investigation.INVESTIGATION_EXECUTION_STATE_PATH,
            auto_curriculum.CURRICULUM_LOG_PATH,
            auto_curriculum.CURRICULUM_STATE_PATH,
            longitudinal_harness.HARNESS_LOG_PATH,
            longitudinal_harness.HARNESS_STATE_PATH,
            self_predictive_model.PREDICTIVE_LOG_PATH,
            self_predictive_model.PREDICTIVE_STATE_PATH,
        ) = old_paths


def test_curriculum_harness_and_predictor_api_endpoints():
    from ultronpro.api import benchmarks

    curriculum = asyncio.run(benchmarks.benchmark_auto_curriculum())
    harness = asyncio.run(benchmarks.benchmark_longitudinal_harness())
    predictor = asyncio.run(benchmarks.benchmark_self_predictive_model())

    assert curriculum["ok"] is True
    assert curriculum["task_count"] >= 1
    assert harness["ok"] is True
    assert harness["generalization"]["axis"] == "generalization"
    assert predictor["ok"] is True
    assert predictor["passed"] is True


def test_longitudinal_harness_background_loop_starts_and_stops(monkeypatch):
    from ultronpro import longitudinal_harness

    monkeypatch.setenv("ULTRON_LONGITUDINAL_HARNESS_ENABLED", "1")
    monkeypatch.setenv("ULTRON_LONGITUDINAL_HARNESS_START_DELAY_SEC", "3600")

    async def _run():
        started = longitudinal_harness.start_background_loop()
        assert started["ok"] is True
        assert started["started"] is True
        assert longitudinal_harness.status()["background_active"] is True
        stopped = longitudinal_harness.stop_background_loop()
        assert stopped["ok"] is True
        assert stopped["stopped"] is True

    asyncio.run(_run())
