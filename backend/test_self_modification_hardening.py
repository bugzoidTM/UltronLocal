import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _isolated_engine(tmp_path, monkeypatch):
    from ultronpro import self_modification

    root = tmp_path / "ultronpro"
    root.mkdir()
    (root / "sample.py").write_text("def value(x):\n    return x + 1\n", encoding="utf-8")
    self_mod_dir = tmp_path / "self_modification"
    backups = self_mod_dir / "backups"
    backups.mkdir(parents=True)

    monkeypatch.setattr(self_modification, "ULTRONPRO_DIR", root)
    monkeypatch.setattr(self_modification, "SELF_MOD_PATH", self_mod_dir)
    monkeypatch.setattr(self_modification, "PROPOSALS_PATH", self_mod_dir / "proposals.json")
    monkeypatch.setattr(self_modification, "HISTORY_PATH", self_mod_dir / "history.json")
    monkeypatch.setattr(self_modification, "BACKUPS_PATH", backups)

    return self_modification.SelfModificationEngine(), self_modification, root


def test_self_modification_never_applies_directly_to_runtime(tmp_path, monkeypatch):
    engine, self_modification, root = _isolated_engine(tmp_path, monkeypatch)
    proposal = engine._create_proposal({
        "file": "sample.py",
        "changes": [{
            "type": "replace",
            "line_start": 2,
            "line_end": 2,
            "new_code": "    return x + 2",
        }],
        "rationale": "improve sample behavior",
        "risk_level": "low",
    }, "sample improvement")

    before = (root / "sample.py").read_text(encoding="utf-8")
    direct = self_modification.apply_modification(proposal.id, force=True)
    after = (root / "sample.py").read_text(encoding="utf-8")

    assert direct["blocked"] is True
    assert direct["error"] == "direct_runtime_apply_disabled"
    assert before == after


def test_self_modification_requires_full_reproducible_pipeline_before_canary(tmp_path, monkeypatch):
    engine, _, root = _isolated_engine(tmp_path, monkeypatch)
    proposal = engine._create_proposal({
        "file": "sample.py",
        "changes": [{
            "type": "replace",
            "line_start": 2,
            "line_end": 2,
            "new_code": "    return x + 2",
        }],
        "rationale": "improve sample behavior",
        "risk_level": "low",
    }, "sample improvement")

    blocked = engine.validate_isolated_pipeline(proposal.id)
    assert blocked["promoted"] is False
    assert "reduced_benchmark" in blocked["missing_or_failed_stages"]
    assert "baseline_compare" in blocked["missing_or_failed_stages"]
    assert "canary" in blocked["missing_or_failed_stages"]

    passed = engine.validate_isolated_pipeline(proposal.id, {
        "reduced_benchmark": {"passed": True, "suite": "smoke"},
        "regression_benchmark": {"passed": True, "suite": "regression_smoke"},
        "baseline": {"score": 0.50},
        "candidate": {"score": 0.75},
        "canary": {"passed": True, "rollout_pct": 5},
    })

    assert passed["promoted"] is True
    assert passed["missing_or_failed_stages"] == []
    assert engine.get_proposals()[0]["status"] == "canary_ready"
    assert "return x + 1" in (root / "sample.py").read_text(encoding="utf-8")
