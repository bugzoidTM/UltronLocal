from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))


def test_autonomous_loop_records_reward_state(tmp_path, monkeypatch):
    from ultronpro import autonomous_loop

    monkeypatch.setattr(autonomous_loop, "AUTONOMY_STATE_PATH", tmp_path / "autonomy_state.json")
    loop = autonomous_loop.AutonomousGoalLoop()

    out = loop.record_action("contract_probe", "closed-loop check", True, 120, 0.9)

    assert out["ok"] is True
    assert out["reward"] > 0.8
    assert loop.reward_weights["contract_probe"] > 0.5
    assert loop.get_status()["history_size"] == 1
    assert (tmp_path / "autonomy_state.json").exists()


def test_autonomous_loop_suggests_recovery_actions_on_risk(tmp_path, monkeypatch):
    from ultronpro import autonomous_loop

    monkeypatch.setattr(autonomous_loop, "AUTONOMY_STATE_PATH", tmp_path / "autonomy_state.json")
    loop = autonomous_loop.AutonomousGoalLoop()

    suggestions = loop.suggest_actions(
        {"metrics": {"error_rate": 0.3, "surprise_score": 0.2}, "homeostasis": {"mode": "normal"}},
        {"prediction": {"degradation_risk": 0.8, "leading_indicators": ["error_rate_increase"]}},
    )

    assert suggestions[0]["kind"] == "deliberate_task"
    assert suggestions[0]["priority"] >= 9
    assert any(item["reason"] == "error_rate_increase" for item in suggestions)


def test_goal_plan_uses_actual_title_and_description():
    from ultronpro import planner

    plan = planner.propose_goal_plan({"id": 123, "title": "Fechar loop", "description": "testar memoria"})

    assert plan.objective == "Fechar loop: testar memoria"
    assert "{title}" not in plan.objective
