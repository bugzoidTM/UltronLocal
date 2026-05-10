import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _isolate(tmp_path, monkeypatch):
    from ultronpro import procedural_induction, store

    monkeypatch.setattr(procedural_induction, "PROCEDURAL_CONTRACTS_PATH", tmp_path / "procedural_contracts.json")
    monkeypatch.setattr(store, "DB_PATH", str(tmp_path / "ultron.db"))
    monkeypatch.setattr(store, "db", store.Store(store.DB_PATH))
    return procedural_induction, store


def _procedure(store):
    return store.add_procedure(
        name="Deploy rollback verifier",
        goal="Verify deploy safety before release",
        steps_json=json.dumps(["check guard", "validate rollback", "emit report"]),
        domain="deploy",
        proc_type="analysis",
        preconditions="legacy textual precondition",
        success_criteria="validated rollback ready",
    )


def _positive_input(idx: int = 0) -> str:
    return json.dumps({
        "task": "deploy",
        "guard": "rollback",
        "sandbox": True,
        "sample": idx,
    })


def _positive_output(idx: int = 0) -> str:
    return json.dumps({
        "status": "validated",
        "rollback_ready": True,
        "report": f"plan_{idx}",
    })


def test_induces_verified_pre_and_post_conditions_from_runs(tmp_path, monkeypatch):
    procedural_induction, store = _isolate(tmp_path, monkeypatch)
    pid = _procedure(store)

    for idx, score in enumerate([0.88, 0.91, 0.86]):
        store.add_procedure_run(
            pid,
            _positive_input(idx),
            _positive_output(idx),
            score=score,
            success=True,
            notes="observed success",
        )
    store.add_procedure_run(
        pid,
        json.dumps({"task": "deploy", "guard": "none", "sandbox": True}),
        json.dumps({"status": "error", "rollback_ready": False}),
        score=0.21,
        success=False,
        notes="missing rollback guard",
    )

    contract = procedural_induction.induce_and_persist(pid)

    assert contract["schema"] == procedural_induction.CONTRACT_SCHEMA
    assert contract["status"] == "verified"
    assert contract["positive_runs"] == 3
    assert contract["negative_runs"] == 1
    assert any(p["kind"] == "json_value" and p.get("path") == "guard" and p.get("value") == "rollback" for p in contract["preconditions"])
    assert any(p["kind"] == "json_value" and p.get("path") == "status" and p.get("value") == "validated" for p in contract["postconditions"])
    assert contract["verification"]["covered_runs"] == 3
    assert contract["verification"]["applicability_precision"] == 1.0

    persisted = procedural_induction.load_contract(pid)
    assert persisted["contract_id"] == contract["contract_id"]
    events = store.db.list_events(0, 20)
    assert any(row["kind"] == "procedure.contract_induced" for row in events)
    workspace = store.db.read_workspace(channels=["procedure.contract_induced"], include_expired=True)
    assert workspace


def test_contract_verification_checks_new_input_and_output(tmp_path, monkeypatch):
    procedural_induction, store = _isolate(tmp_path, monkeypatch)
    pid = _procedure(store)
    for idx in range(2):
        store.add_procedure_run(pid, _positive_input(idx), _positive_output(idx), score=0.88, success=True)
    store.add_procedure_run(
        pid,
        json.dumps({"task": "deploy", "guard": "none", "sandbox": True}),
        json.dumps({"status": "error", "rollback_ready": False}),
        score=0.20,
        success=False,
    )
    contract = procedural_induction.induce_and_persist(pid, publish=False)

    ok = procedural_induction.verify_contract(
        contract,
        input_text=json.dumps({"task": "deploy", "guard": "rollback", "sandbox": True}),
        output_text=json.dumps({"status": "validated", "rollback_ready": True, "report": "fresh"}),
        score=0.9,
    )
    blocked = procedural_induction.verify_contract(
        contract,
        input_text=json.dumps({"task": "deploy", "guard": "none", "sandbox": True}),
        output_text=json.dumps({"status": "validated", "rollback_ready": True, "report": "fresh"}),
        score=0.9,
    )
    app = procedural_induction.score_applicability(
        pid,
        json.dumps({"task": "deploy", "guard": "rollback", "sandbox": True}),
    )

    assert ok["pre_ok"] is True
    assert ok["post_ok"] is True
    assert blocked["pre_ok"] is False
    assert blocked["applicable"] is False
    assert app["available"] is True
    assert app["applicable"] is True
    assert app["score"] == 1.0


def test_insufficient_runs_emit_explicit_learning_gap(tmp_path, monkeypatch):
    procedural_induction, store = _isolate(tmp_path, monkeypatch)
    pid = _procedure(store)
    store.add_procedure_run(pid, _positive_input(), _positive_output(), score=0.88, success=True)

    contract = procedural_induction.induce_and_persist(pid)
    runs = store.list_procedure_runs(pid)

    assert contract["status"] == "insufficient_data"
    assert contract["learning_gap"]["missing"] == "positive_runs"
    assert contract["learning_gap"]["required"] == procedural_induction.MIN_POSITIVE_RUNS
    assert len(runs) == 1
    workspace = store.db.read_workspace(channels=["procedure.contract_gap"], include_expired=True)
    assert workspace
