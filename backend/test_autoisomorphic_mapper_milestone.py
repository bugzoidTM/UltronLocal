import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _valid_iso():
    return {
        "domain_source": "fs_guard",
        "domain_target": "api_guard",
        "raw_score": 0.94,
        "p_value": 0.01,
        "transfer_improvement": 0.14,
        "features_compared": 3,
        "mapping": {
            "guarded": "auth_ok",
            "validated": "schema_ok",
            "reversible": "rollback_ready",
        },
        "transfer_test": {
            "ok": True,
            "reason": "holdout_transfer_test",
            "baseline_accuracy": 0.5,
            "transfer_accuracy": 0.64,
            "improvement": 0.14,
            "holdout_size": 14,
            "passed": True,
        },
    }


def _isolate(tmp_path, monkeypatch):
    from ultronpro import autoisomorphic_mapper, store, structural_mapper

    monkeypatch.setattr(
        autoisomorphic_mapper,
        "ISOMORPHISM_VALIDATION_LOG_PATH",
        tmp_path / "cognitive_isomorphism_validations.jsonl",
    )
    monkeypatch.setattr(
        autoisomorphic_mapper,
        "FIRST_ISOMORPHISM_MILESTONE_PATH",
        tmp_path / "first_cognitive_isomorphism_validated.json",
    )
    monkeypatch.setattr(structural_mapper, "CROSS_SKILLS_PATH", tmp_path / "cross_domain_skills.json")
    monkeypatch.setattr(store, "DB_PATH", str(tmp_path / "ultron.db"))
    monkeypatch.setattr(store, "db", store.Store(store.DB_PATH))
    return autoisomorphic_mapper, store, structural_mapper


def test_records_first_legitimate_cognitive_isomorphism_event(tmp_path, monkeypatch):
    autoisomorphic_mapper, store, _ = _isolate(tmp_path, monkeypatch)
    mapper = autoisomorphic_mapper.AutoIsomorphicMapper()

    result = mapper.record_validated_isomorphism(
        _valid_iso(),
        skill={"id": "zshot_test", "name": "Isomorfismo Validado: fs_guard <-> api_guard"},
        validation_evidence={"source": "unit_test"},
    )

    assert result["ok"] is True
    assert result["recorded"] is True
    assert result["milestone_recorded"] is True
    event = result["event"]
    assert event["schema"] == autoisomorphic_mapper.ISOMORPHISM_EVENT_SCHEMA
    assert event["type"] == "cognitive.isomorphism_validated"
    assert event["legitimate"] is True
    assert len(event["filters"]) == 4
    assert all(item["passed"] for item in event["filters"])
    assert event["structural_checks"]["bijective_mapping"] is True
    assert event["transfer_test"]["improvement"] == 0.14

    logged = [
        json.loads(line)
        for line in autoisomorphic_mapper.ISOMORPHISM_VALIDATION_LOG_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert logged[0]["id"] == result["validation_id"]

    milestone = json.loads(autoisomorphic_mapper.FIRST_ISOMORPHISM_MILESTONE_PATH.read_text(encoding="utf-8"))
    assert milestone["milestone_type"] == "first_cognitive_isomorphism_validated"
    assert milestone["id"] == result["validation_id"]

    events = store.db.list_events(0, 10)
    assert any(row["kind"] == "cognitive.isomorphism_validated" for row in events)
    workspace = store.db.read_workspace(channels=["cognitive.isomorphism_validated"], include_expired=True)
    assert len(workspace) == 1


def test_records_validated_isomorphism_through_injected_ports(tmp_path, monkeypatch):
    autoisomorphic_mapper, _, _ = _isolate(tmp_path, monkeypatch)
    from ultronpro.core.ports import recording_ports

    ports, events, workspace, _ = recording_ports()
    mapper = autoisomorphic_mapper.AutoIsomorphicMapper(ports=ports)

    result = mapper.record_validated_isomorphism(_valid_iso())

    assert result["ok"] is True
    assert result["recorded"] is True
    assert events.rows[0]["kind"] == "cognitive.isomorphism_validated"
    assert workspace.rows[0]["module"] == "autoisomorphic_mapper"
    assert workspace.rows[0]["channel"] == "cognitive.isomorphism_validated"
    assert workspace.rows[0]["payload"]["id"] == result["validation_id"]


def test_rejects_isomorphism_event_without_transfer_gain(tmp_path, monkeypatch):
    autoisomorphic_mapper, store, _ = _isolate(tmp_path, monkeypatch)
    mapper = autoisomorphic_mapper.AutoIsomorphicMapper()
    iso = _valid_iso()
    iso["transfer_improvement"] = 0.01
    iso["transfer_test"]["improvement"] = 0.01
    iso["transfer_test"]["passed"] = False

    result = mapper.record_validated_isomorphism(iso)

    assert result["ok"] is True
    assert result["recorded"] is False
    assert result["reason"] == "validation_filters_failed"
    assert "transfer_utility" in result["event"]["rejection"]["failed_filters"]
    assert not autoisomorphic_mapper.ISOMORPHISM_VALIDATION_LOG_PATH.exists()
    assert not autoisomorphic_mapper.FIRST_ISOMORPHISM_MILESTONE_PATH.exists()
    assert store.db.list_events(0, 10) == []


def test_compile_validated_skill_attaches_event_contract(tmp_path, monkeypatch):
    autoisomorphic_mapper, _, structural_mapper = _isolate(tmp_path, monkeypatch)
    mapper = autoisomorphic_mapper.AutoIsomorphicMapper()

    mapper._compile_validated_skills([_valid_iso()])

    skills = json.loads(structural_mapper.CROSS_SKILLS_PATH.read_text(encoding="utf-8"))
    assert len(skills["skills"]) == 1
    skill = skills["skills"][0]
    assert skill["validation_event_id"].startswith("iso_")
    assert skill["isomorphism_event_schema"] == autoisomorphic_mapper.ISOMORPHISM_EVENT_SCHEMA
    assert len(skill["filter_results"]) == 4
    assert all(item["passed"] for item in skill["filter_results"])
