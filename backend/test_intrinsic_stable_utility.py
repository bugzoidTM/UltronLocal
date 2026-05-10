import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _isolate(tmp_path, monkeypatch):
    from ultronpro import intrinsic_kernel, intrinsic_utility, self_model, store

    monkeypatch.setattr(intrinsic_kernel, "KERNEL_PATH", tmp_path / "intrinsic_value_kernel.json")
    monkeypatch.setattr(intrinsic_utility, "STATE_PATH", tmp_path / "intrinsic_utility_state.json")
    monkeypatch.setattr(self_model, "PATH", tmp_path / "self_model.json")
    monkeypatch.setattr(store, "DB_PATH", str(tmp_path / "ultron.db"))
    monkeypatch.setattr(store, "db", store.Store(store.DB_PATH))
    return intrinsic_kernel, intrinsic_utility, self_model, store


def test_kernel_updates_from_accepted_operational_evidence_and_persists(tmp_path, monkeypatch):
    intrinsic_kernel, _, self_model, store = _isolate(tmp_path, monkeypatch)
    before = intrinsic_kernel.public_kernel()

    sm = self_model.load()
    sm.setdefault("operational", {}).setdefault("weaknesses", []).append(
        "procedural contract gap without verified preconditions or postconditions"
    )
    sm["operational"].setdefault("confidence_by_domain", {})["procedural_learning"] = 0.28
    self_model.save(sm)
    store.db.add_event(
        "procedure.contract_gap",
        "procedure contract insufficient_data missing positive runs",
        meta_json=json.dumps({"procedure_id": 42, "missing": "positive_runs"}),
    )

    intrinsic_state = {
        "drives": {
            "competence": {"desired": 0.80, "observed": 0.35},
            "coherence": {"desired": 0.76, "observed": 0.74},
            "autonomy": {"desired": 0.72, "observed": 0.70},
            "novelty": {"desired": 0.62, "observed": 0.50},
            "integrity": {"desired": 0.90, "observed": 0.88},
        }
    }

    result = intrinsic_kernel.update_kernel(intrinsic_state=intrinsic_state)
    after = intrinsic_kernel.status(limit=10)

    assert result["status"] == "updated"
    assert result["kernel"]["schema"] == intrinsic_kernel.SCHEMA
    assert result["accepted_evidence_count"] >= 3
    assert result["kernel"]["stability"]["source"] == "emergent_from_accepted_operational_evidence"
    assert after["kernel"]["hash"] == result["kernel"]["hash"]
    assert after["kernel"]["revision"] == before["revision"] + 1
    assert any(ev["source"] in {"self_model", "procedural_contracts"} for ev in after["recent_evidence"])

    old_weights = {k: v["weight"] for k, v in before["values"].items()}
    new_weights = {k: v["weight"] for k, v in result["kernel"]["values"].items()}
    assert any(new_weights[k] != old_weights[k] for k in old_weights)
    for drive in old_weights:
        assert abs(new_weights[drive] - old_weights[drive]) <= intrinsic_kernel.MAX_DELTA_PER_UPDATE + 0.001


def test_kernel_rejects_direct_prompt_manipulation_source(tmp_path, monkeypatch):
    intrinsic_kernel, _, _, _ = _isolate(tmp_path, monkeypatch)
    before = intrinsic_kernel.public_kernel()

    result = intrinsic_kernel.update_kernel(
        reward_event={"source": "user_prompt", "drive": "integrity", "reward": 1.0},
        force=True,
    )
    after = intrinsic_kernel.public_kernel()

    assert result["status"] == "no_evidence"
    assert after["revision"] == before["revision"]
    assert after["hash"] == before["hash"]
    assert after["values"] == before["values"]


def test_kernel_tamper_check_restores_last_valid_values(tmp_path, monkeypatch):
    intrinsic_kernel, _, self_model, store = _isolate(tmp_path, monkeypatch)
    sm = self_model.load()
    sm.setdefault("operational", {}).setdefault("failure_patterns", []).append(
        "coverage gap in new questions"
    )
    self_model.save(sm)
    update = intrinsic_kernel.update_kernel()
    assert update["status"] == "updated"

    raw = json.loads(intrinsic_kernel.KERNEL_PATH.read_text(encoding="utf-8"))
    valid_weight = raw["values"]["competence"]["weight"]
    raw["values"]["competence"]["weight"] = 0.99
    intrinsic_kernel.KERNEL_PATH.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")

    check = intrinsic_kernel.tamper_check()
    restored = json.loads(intrinsic_kernel.KERNEL_PATH.read_text(encoding="utf-8"))

    assert check["tampered"] is True
    assert restored["values"]["competence"]["weight"] == valid_weight
    assert restored["current_hash"] == check["restored_hash"]
    assert any(row["kind"] == "intrinsic_kernel_tamper" for row in store.db.list_events(0, 20))


def test_intrinsic_utility_tick_uses_stable_kernel(tmp_path, monkeypatch):
    intrinsic_kernel, intrinsic_utility, _, _ = _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(
        intrinsic_utility,
        "_collect_signals",
        lambda: {
            "competence": 0.20,
            "coherence": 0.40,
            "autonomy": 0.25,
            "novelty": 0.30,
            "integrity": 0.80,
        },
    )

    result = intrinsic_utility.tick()
    state = intrinsic_utility._load()
    status = intrinsic_utility.status(limit=5)

    assert result["ok"] is True
    assert result["kernel_update"]["status"] == "updated"
    assert result["utility_kernel"]["hash"] == intrinsic_kernel.public_kernel()["hash"]
    assert state["utility_history"][-1]["utility_kernel"]["hash"] == result["utility_kernel"]["hash"]
    assert all(d.get("weight_source") == "stable_intrinsic_kernel" for d in state["drives"].values())
    assert status["utility_kernel"]["kernel"]["hash"] == result["utility_kernel"]["hash"]
    assert result["active_emergent_goal"]["objective_contract"] == "stable_intrinsic_kernel_gap_minimization"
