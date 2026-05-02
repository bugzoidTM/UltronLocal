import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _store(tmp_path):
    from ultronpro import store

    return store.Store(tmp_path / "autonomous_cognition.db")


def test_stage_1_perceives_internal_state_and_publishes_workspace(tmp_path):
    from ultronpro import autonomous_cognition

    db = _store(tmp_path)
    db.add_event("runtime_error", "timeout while testing autonomous perception")
    db.publish_workspace(
        module="unit",
        channel="integrity.alert",
        payload_json='{"reason":"unit high salience"}',
        salience=0.9,
        ttl_sec=300,
    )

    result = autonomous_cognition.tick(store_module=db, stage="perceive", train_world_model=False)

    assert result["ok"] is True
    assert result["snapshot"]["recent_error_count"] >= 1
    assert result["snapshot"]["unconsumed_high_salience_count"] >= 1
    ws = db.read_workspace(channels=["autonomous.perception"], limit=5)
    assert ws


def test_stage_2_predicts_risks_and_enqueues_safe_internal_action(tmp_path):
    from ultronpro import autonomous_cognition

    db = _store(tmp_path)
    for idx in range(3):
        db.add_event("tool_error", f"failed autonomous operation {idx}")

    result = autonomous_cognition.tick(store_module=db, stage="deliberate", train_world_model=False)

    risk_ids = {risk["risk_id"] for risk in result["risks"]}
    assert "recent_failure_cluster" in risk_ids
    assert "goal_starvation" in risk_ids
    assert result["suggestions"]
    actions = db.list_actions(limit=20)
    assert any(a["kind"] == "autonomous_internal" and a["status"] == "queued" for a in actions)
    assert db.read_workspace(channels=["autonomous.risk_forecast"], limit=5)
    assert db.read_workspace(channels=["autonomous.action_suggestions"], limit=5)


def test_stage_3_executes_action_and_records_consequence_episode(tmp_path):
    from ultronpro import autonomous_cognition

    db = _store(tmp_path)
    result = autonomous_cognition.tick(store_module=db, stage="act", train_world_model=False)

    assert result["action"]["executed"] is True
    assert result["action"]["ok"] is True
    actions = db.list_actions(limit=20)
    assert any(a["kind"] == "autonomous_internal" and a["status"] == "done" for a in actions)
    episodes = db.list_episodic_episodes(
        session_id="autonomous:internal",
        episode_type="autonomous_cognition",
        limit=10,
    )
    assert episodes
    assert "perceive_predict_act_learn" in str(episodes[0].get("structured_json") or "")
    assert db.read_workspace(channels=["autonomous.consequence"], limit=5)
