import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _isolate(tmp_path, monkeypatch):
    from ultronpro import action_prediction

    monkeypatch.setattr(action_prediction, "STATE_PATH", tmp_path / "action_prediction_state.json")
    monkeypatch.setattr(action_prediction, "TRACE_PATH", tmp_path / "action_predictions.jsonl")
    return action_prediction


def test_unknown_action_uses_uniform_prior(tmp_path, monkeypatch):
    ap = _isolate(tmp_path, monkeypatch)

    prediction = ap.predict({"kind": "trusted_acquisition", "context": "normal"})

    assert prediction["predicted_reward"] == ap.PRIOR_REWARD
    assert prediction["confidence"] == ap.PRIOR_CONFIDENCE
    assert prediction["basis"] == "uniform_prior"
    assert prediction["n_prior"] == 0


def test_prediction_error_falls_with_consistent_consequences(tmp_path, monkeypatch):
    ap = _isolate(tmp_path, monkeypatch)
    candidate = {"kind": "trusted_acquisition", "context": "normal"}

    surprises = []
    for _ in range(10):
        prediction = ap.predict(candidate)
        settlement = ap.settle(prediction, 0.8)
        surprises.append(settlement["surprise"])

    # O mundo é estável (reward 0.8): a previsão converge e a surpresa cai.
    assert surprises[-1] < surprises[0]
    final = ap.predict(candidate)
    assert abs(final["predicted_reward"] - 0.8) < 0.1
    assert final["confidence"] > 0.5
    assert final["basis"] == "arm_ema_mean_reward"

    report = ap.learning_report()
    assert report["improving"] is True
    assert report["trend"] == "improving"


def test_high_surprise_is_flagged_and_traced(tmp_path, monkeypatch):
    ap = _isolate(tmp_path, monkeypatch)
    candidate = {"kind": "sleep_digest", "context": "normal"}

    prediction = ap.predict(candidate)
    settlement = ap.settle(prediction, 1.0)

    assert settlement["surprise"] == 0.5
    assert settlement["high_surprise"] is True
    rows = [json.loads(line) for line in (tmp_path / "action_predictions.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rows[0]["high_surprise"] is True
    assert rows[0]["actual_reward"] == 1.0


def test_exploration_bonus_favors_poorly_understood_actions(tmp_path, monkeypatch):
    ap = _isolate(tmp_path, monkeypatch)

    # Arm calibrado: previsões repetidamente corretas.
    calibrated = {"kind": "homeostasis_tune", "context": "normal"}
    for _ in range(8):
        ap.settle(ap.predict(calibrated), 0.5)

    # Arm caótico: consequências alternam entre extremos.
    chaotic = {"kind": "sleep_digest", "context": "normal"}
    for i in range(8):
        ap.settle(ap.predict(chaotic), 1.0 if i % 2 == 0 else 0.0)

    bonus_unknown = ap.exploration_bonus("never_run", "normal")
    bonus_calibrated = ap.exploration_bonus("homeostasis_tune", "normal")
    bonus_chaotic = ap.exploration_bonus("sleep_digest", "normal")

    assert bonus_chaotic > bonus_calibrated
    assert bonus_unknown == 0.08
    assert bonus_calibrated < 0.05


def test_persistent_miscalibration_becomes_epistemic_gap(tmp_path, monkeypatch):
    ap = _isolate(tmp_path, monkeypatch)
    chaotic = {"kind": "sleep_digest", "context": "normal"}
    for i in range(6):
        ap.settle(ap.predict(chaotic), 1.0 if i % 2 == 0 else 0.0)

    gap = ap.miscalibration_gap()

    assert gap is not None
    assert gap["gap_id"] == "action_model_miscalibrated_sleep_digest"
    assert gap["domain"] == "action_consequence_model"
    assert gap["severity"] > 0.3
    assert "sleep_digest" in gap["next_experiment"]


def test_no_gap_when_model_is_calibrated(tmp_path, monkeypatch):
    ap = _isolate(tmp_path, monkeypatch)
    calibrated = {"kind": "homeostasis_tune", "context": "normal"}
    for _ in range(8):
        ap.settle(ap.predict(calibrated), 0.5)

    assert ap.miscalibration_gap() is None


def test_run_once_predicts_then_settles_against_real_consequence(tmp_path, monkeypatch):
    from ultronpro import action_prediction, online_rl_loop, rl_policy
    from ultronpro.core.ports import recording_ports

    monkeypatch.setattr(online_rl_loop, "RUN_LOG_PATH", tmp_path / "online_rl_runs.jsonl")
    monkeypatch.setattr(online_rl_loop, "STATE_PATH", tmp_path / "online_rl_state.json")
    monkeypatch.setattr(rl_policy, "STATE_PATH", tmp_path / "rl_policy_state.json")
    monkeypatch.setattr(action_prediction, "STATE_PATH", tmp_path / "action_prediction_state.json")
    monkeypatch.setattr(action_prediction, "TRACE_PATH", tmp_path / "action_predictions.jsonl")
    monkeypatch.setattr(
        online_rl_loop.continuous_learning,
        "record_learning_feedback",
        lambda *args, **kwargs: {"ok": True},
    )
    monkeypatch.setattr(
        online_rl_loop.intrinsic_utility,
        "adjust_drive_weights",
        lambda drive, reward: {"ok": True},
    )
    observation = {
        "context": "normal",
        "vitals": {"coherence_score": 0.6, "uncertainty_load": 0.55, "contradiction_stress": 0.30},
        "top_gap": {"id": "g", "label": "gap", "domain": "causal", "metric": "m", "priority": 0.8},
        "patch_stats": {},
        "rl_policy": {},
    }
    monkeypatch.setattr(online_rl_loop, "_observe_environment", lambda: dict(observation))
    monkeypatch.setattr(
        online_rl_loop,
        "_execute_candidate",
        lambda candidate, ports=None: {
            "ok": True,
            "extraction": {"useful": [{"confidence": 0.7}]},
            "application": {"ok": True, "mode": "knowledge"},
            "sources": {"trusted": [{"url": "https://docs.python.org/3/"}]},
            "gaps_remaining": [],
        },
    )
    ports, _, _, _ = recording_ports()

    first = online_rl_loop.run_once(force_kind="trusted_acquisition", include_cooldown=True, ports=ports)
    second = online_rl_loop.run_once(force_kind="trusted_acquisition", include_cooldown=True, ports=ports)

    assert first["prediction"]["basis"] == "uniform_prior"
    assert first["prediction_settlement"]["ok"] is True
    assert first["prediction_settlement"]["actual_reward"] == first["reward"]["reward"]
    assert first["policy_updates"]["action_prediction"]["surprise"] == first["prediction_settlement"]["surprise"]

    # Segunda execução: o sistema já tem um modelo da ação e prevê com base nele.
    assert second["prediction"]["basis"] == "arm_ema_mean_reward"
    assert second["prediction"]["n_prior"] == 1
    assert second["prediction_settlement"]["surprise"] < first["prediction_settlement"]["surprise"]

    # O bônus de curiosidade aparece nos candidatos avaliados.
    candidates = second["selection"]["candidates"]
    assert all("prediction_curiosity_bonus" in c for c in candidates)


def test_selftest_is_deterministic(tmp_path, monkeypatch):
    ap = _isolate(tmp_path, monkeypatch)

    result = ap.run_selftest()

    assert result["ok"] is True
    assert result["non_llm"] is True
