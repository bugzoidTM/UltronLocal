import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _isolate(tmp_path, monkeypatch):
    from ultronpro import auto_specification, procedural_induction, self_model, store

    monkeypatch.setattr(auto_specification, "AUTO_SPEC_PATH", tmp_path / "self_specification_revisions.json")
    monkeypatch.setattr(auto_specification, "_collect_roadmap_limitations", lambda: [])
    monkeypatch.setattr(auto_specification, "_collect_sleep_limitations", lambda: [])
    monkeypatch.setattr(procedural_induction, "PROCEDURAL_CONTRACTS_PATH", tmp_path / "procedural_contracts.json")
    monkeypatch.setattr(self_model, "PATH", tmp_path / "self_model.json")
    monkeypatch.setattr(store, "DB_PATH", str(tmp_path / "ultron.db"))
    monkeypatch.setattr(store, "db", store.Store(store.DB_PATH))
    return auto_specification, procedural_induction, self_model, store


def test_rewrites_high_level_objectives_from_structural_limitations(tmp_path, monkeypatch):
    auto_specification, procedural_induction, self_model, store = _isolate(tmp_path, monkeypatch)
    sm = self_model.load()
    sm.setdefault("operational", {}).setdefault("weaknesses", []).append(
        "Aprendizado procedural ainda manual, sem precondicoes e poscondicoes verificaveis."
    )
    sm["operational"].setdefault("confidence_by_domain", {})["procedural_learning"] = 0.31
    self_model.save(sm)

    procedural_induction.PROCEDURAL_CONTRACTS_PATH.write_text(
        json.dumps({
            "version": 1,
            "contracts": {
                "7": {
                    "procedure_id": 7,
                    "procedure_name": "Deploy verifier",
                    "status": "insufficient_data",
                    "learning_gap": {"missing": "positive_runs", "required": 2, "observed": 1},
                }
            },
        }),
        encoding="utf-8",
    )
    store.db.add_event(
        "procedure.contract_gap",
        "procedure contract pid=7 status=insufficient_data pre=0 post=0",
        meta_json=json.dumps({"procedure_id": 7, "missing": "positive_runs"}),
    )

    revision = auto_specification.rewrite_high_level_objectives(apply=True, force=True)

    assert revision["status"] == "rewritten"
    assert revision["trigger"] == "structural_limitation_reflection"
    assert any(obj["dimension"] == "procedural_learning" for obj in revision["objectives"])
    procedural_obj = next(obj for obj in revision["objectives"] if obj["dimension"] == "procedural_learning")
    assert "contrato" in procedural_obj["title"].lower()
    assert procedural_obj["derived_from_limitations"]
    assert revision["limitations"][0]["dimension"] == "procedural_learning"

    updated_self = self_model.load()
    assert updated_self["self_specification"]["current_revision_id"] == revision["revision_id"]
    assert "Focos atuais" in updated_self["identity"]["mission"]

    goals = store.db.list_goals(status=None, limit=20)
    assert any(str(g["title"]).startswith("[SELF-SPEC]") for g in goals)
    events = store.db.list_events(0, 20)
    assert any(row["kind"] == "self.specification_rewritten" for row in events)
    workspace = store.db.read_workspace(channels=["self.specification_rewritten"], include_expired=True)
    assert workspace


def test_rewrite_respects_cooldown_after_applied_revision(tmp_path, monkeypatch):
    auto_specification, _, self_model, _ = _isolate(tmp_path, monkeypatch)
    sm = self_model.load()
    sm.setdefault("operational", {}).setdefault("failure_patterns", []).append("coverage gap recorrente em perguntas novas")
    self_model.save(sm)

    first = auto_specification.rewrite_high_level_objectives(apply=True, force=True)
    second = auto_specification.rewrite_high_level_objectives(apply=True, force=False)

    assert first["status"] == "rewritten"
    assert second["status"] == "cooldown"
    assert second["current"]["revision_id"] == first["revision_id"]


def test_no_rewrite_without_structural_limitations(tmp_path, monkeypatch):
    auto_specification, _, _, _ = _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(auto_specification, "_collect_self_model_limitations", lambda: [])
    monkeypatch.setattr(auto_specification, "_collect_event_limitations", lambda: [])
    monkeypatch.setattr(auto_specification, "_collect_contract_limitations", lambda: [])
    monkeypatch.setattr(auto_specification, "_collect_sleep_limitations", lambda: [])
    monkeypatch.setattr(auto_specification, "_collect_roadmap_limitations", lambda: [])

    result = auto_specification.rewrite_high_level_objectives(apply=True, force=True)

    assert result["status"] == "no_structural_limitations"
    assert result["limitations"] == []
    assert auto_specification.status()["revision_count"] == 0
