import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _isolate(tmp_path, monkeypatch):
    from ultronpro import local_world_models, store

    monkeypatch.setenv("BENCHMARK_MODE", "1")
    monkeypatch.setattr(local_world_models, "LOCAL_WORLD_MODELS_PATH", tmp_path / "local_world_models.json")
    monkeypatch.setattr(local_world_models, "_manager", None)
    monkeypatch.setattr(store, "DB_PATH", str(tmp_path / "ultron.db"))
    monkeypatch.setattr(store, "db", store.Store(store.DB_PATH))
    return local_world_models, store


def _train_success(manager, family: str, action: str, n: int = 4):
    for idx in range(n):
        manager.train_transition(
            family,
            {"guard": {"present": True}, "sample": idx},
            action,
            {"guard": {"present": True}, "done": True, "sample": idx},
            "success",
            {"surprise_delta": 0.0},
        )


def test_manual_transfer_bridge_predicts_when_target_family_has_no_coverage(tmp_path, monkeypatch):
    local_world_models, store = _isolate(tmp_path, monkeypatch)
    manager = local_world_models.LocalWorldModelManager()
    _train_success(manager, "fs_guard", "delete_with_rollback", n=4)

    bridge = manager.register_transfer_bridge(
        "fs_guard",
        "api_guard",
        feature_map={"auth.ok": "guard.present"},
        action_map={"deploy_with_rollback": "delete_with_rollback"},
        confidence=0.82,
        evidence={"source": "unit_test_manual_bridge"},
    )

    prediction = manager.predict("api_guard", {"auth": {"ok": True}}, "deploy_with_rollback")

    assert bridge["source_family"] == "fs_guard"
    assert prediction["composition_mode"] == "cross_family_transfer"
    assert prediction["predicted_outcome"] == "success"
    assert prediction["confidence"] > 0.6
    assert prediction["local_prediction"]["predicted_outcome"] == "unknown"
    assert prediction["local_gap"]["reason"].startswith("Zero")
    assert prediction["transfers"][0]["source_action"] == "delete_with_rollback"
    assert prediction["transfers"][0]["feature_map"] == {"auth.ok": "guard.present"}

    events = store.db.list_events(0, 20)
    assert any(row["kind"] == "world_model.transfer_bridge" for row in events)
    assert any(row["kind"] == "world_model.transfer_prediction" for row in events)
    workspace = store.db.read_workspace(channels=["world_model.transfer_prediction"], include_expired=True)
    assert workspace


def test_empirical_policy_composition_builds_cross_family_bridges(tmp_path, monkeypatch):
    local_world_models, _ = _isolate(tmp_path, monkeypatch)
    manager = local_world_models.LocalWorldModelManager()

    _train_success(manager, "fs_guard", "rollback_guard", n=4)
    _train_success(manager, "api_guard", "rollback_guard", n=4)
    result = manager.compose_family_graph()

    assert result["ok"] is True
    assert result["bridge_count"] >= 2
    bridges = manager.transfer_status()["bridges"]
    empirical = [b for b in bridges if b["relation_type"] == "empirical_policy_composition"]
    pairs = {(b["source_family"], b["target_family"]) for b in empirical}
    assert ("fs_guard", "api_guard") in pairs
    assert ("api_guard", "fs_guard") in pairs
    assert all(b["action_map"].get("rollback_guard") == "rollback_guard" for b in empirical)

    prediction = manager.predict("api_guard", {"guard": {"present": True}}, "rollback_guard")

    assert prediction["predicted_outcome"] == "success"
    assert prediction["confidence"] >= 0.55
    assert prediction["composition"]["composition_mode"] == "cross_family_transfer"
    assert prediction["composition"]["transfers"][0]["source_family"] == "fs_guard"


def test_transfer_graph_persists_with_structural_features(tmp_path, monkeypatch):
    local_world_models, _ = _isolate(tmp_path, monkeypatch)
    manager = local_world_models.LocalWorldModelManager()
    manager.get_model("source").structural_features = ["guard.present"]
    manager.register_transfer_bridge(
        "source",
        "target",
        feature_map={"auth.ok": "guard.present"},
        action_map={"deploy": "delete"},
        confidence=0.7,
    )

    reloaded = local_world_models.LocalWorldModelManager()
    status = reloaded.transfer_status()

    assert status["bridge_count"] == 1
    assert reloaded.get_model("source").structural_features == ["guard.present"]
    assert status["bridges"][0]["feature_map"] == {"auth.ok": "guard.present"}
