import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _obs(priority: float = 0.8, coherence: float = 0.6):
    return {
        "context": "normal",
        "vitals": {
            "coherence_score": coherence,
            "uncertainty_load": 0.55,
            "contradiction_stress": 0.30,
        },
        "top_gap": {
            "id": "causal_graph_interventional_coverage",
            "label": "causal coverage gap",
            "domain": "causal_graph",
            "metric": "coverage",
            "priority": priority,
            "next_experiment": "learn from trusted source",
        },
        "patch_stats": {"proposed": 0, "evaluating": 0, "evaluated": 0},
        "rl_policy": {},
    }


def _isolate(tmp_path, monkeypatch):
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
        lambda *args, **kwargs: {"ok": True, "feedback": kwargs},
    )
    monkeypatch.setattr(
        online_rl_loop.intrinsic_utility,
        "adjust_drive_weights",
        lambda drive, reward: {"ok": True, "drive": drive, "reward": reward},
    )
    ports, events, workspace, memory = recording_ports()
    return online_rl_loop, rl_policy, ports, events, workspace, memory


def test_online_rl_cycle_updates_policy_from_real_consequence(tmp_path, monkeypatch):
    online_rl_loop, rl_policy, ports, events, workspace, _ = _isolate(tmp_path, monkeypatch)
    observations = [_obs(priority=0.8, coherence=0.60), _obs(priority=0.62, coherence=0.67)]
    monkeypatch.setattr(online_rl_loop, "_observe_environment", lambda: observations.pop(0))
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

    result = online_rl_loop.run_once(force_kind="trusted_acquisition", include_cooldown=True, ports=ports)
    summary = rl_policy.policy_summary(limit=10)

    assert result["schema"] == online_rl_loop.RUN_SCHEMA
    assert result["non_llm"] is True
    assert result["selection"]["selected"]["kind"] == "trusted_acquisition"
    assert result["reward"]["reward"] > 0.5
    assert result["policy_updates"]["rl_policy"]["ok"] is True
    assert summary["global_updates"] == 1
    assert summary["arms"][0]["kind"] == "trusted_acquisition"
    assert summary["arms"][0]["n_total"] == 1
    assert summary["arms"][0]["n_real"] + summary["arms"][0]["n_synthetic"] == 1
    assert events.rows[0]["kind"] == "online_rl.consequence"
    assert workspace.rows[0]["channel"] == "online_rl.consequence"


def test_selection_respects_cooldown_even_when_policy_prefers_action(tmp_path, monkeypatch):
    online_rl_loop, _, _, _, _, _ = _isolate(tmp_path, monkeypatch)
    state = {
        "schema": online_rl_loop.RUN_SCHEMA,
        "last_action_ts": {"trusted_acquisition": online_rl_loop._now()},
        "cycle_count": 1,
    }
    online_rl_loop._save_state(state)
    monkeypatch.setattr(
        online_rl_loop.rl_policy,
        "sample_priority",
        lambda kind, context: 5 if kind == "trusted_acquisition" else 0,
    )

    selected = online_rl_loop.select_action(_obs(), include_cooldown=False)

    assert selected["ok"] is True
    assert selected["selected"]["kind"] != "trusted_acquisition"
    trusted = [item for item in online_rl_loop.candidate_actions(_obs(), include_cooldown=True) if item["kind"] == "trusted_acquisition"][0]
    assert trusted["cooldown_remaining_sec"] > 0


def test_reward_penalizes_failed_intervention():
    from ultronpro import online_rl_loop

    candidate = {"kind": "trusted_acquisition", "context": "normal"}
    result = {"ok": False, "error": "source_unavailable", "gaps_remaining": ["trusted_source_missing"]}
    reward = online_rl_loop.compute_reward(
        candidate=candidate,
        result=result,
        before=_obs(priority=0.8, coherence=0.60),
        after=_obs(priority=0.8, coherence=0.58),
        duration_ms=2000,
    )

    assert reward["reward"] < 0.5
    assert reward["ok"] is False
    assert reward["components"]["result_ok"] is False
