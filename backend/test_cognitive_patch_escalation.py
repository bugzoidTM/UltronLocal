import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def test_escalates_promoted_trusted_patch_to_code_proposal(monkeypatch):
    from ultronpro import cognitive_patch_loop as loop
    from ultronpro import self_modification

    calls = {}

    class FakeProposal:
        id = "mod_test_1"

    def fake_generate(module, func, goal, context=""):
        calls["module"] = module
        calls["goal"] = goal
        calls["context"] = context
        return FakeProposal()

    monkeypatch.setattr(self_modification, "generate_modification", fake_generate)
    monkeypatch.setattr(self_modification, "validate_proposal", lambda pid: {"valid": True})

    patch = {
        "id": "cp_x",
        "source": "trusted_acquisition_loop",
        "hypothesis": "Trusted source evidence can reduce gap routing_gap",
        "proposed_change": {
            "domain": "routing",
            "source_url": "https://fastapi.tiangolo.com/tutorial/",
            "key_points": [{"score": 0.5, "text": "Routing coverage should use explicit route metadata."}],
        },
    }

    out = loop._escalate_trusted_patch_to_code(patch)

    assert out["ok"] is True
    assert out["module"] == "rag_router.py"
    assert out["proposal_id"] == "mod_test_1"
    assert out["applied"] is False
    assert out["validation"] == {"valid": True}
    assert "Routing coverage" in calls["context"]
    assert "fastapi.tiangolo.com" in calls["context"]


def test_escalation_skips_unmapped_domain():
    from ultronpro import cognitive_patch_loop as loop

    out = loop._escalate_trusted_patch_to_code({"proposed_change": {"domain": "astrology"}})

    assert out["ok"] is False
    assert out["reason"] == "no_module_mapping"


def test_escalation_reports_generation_error(monkeypatch):
    from ultronpro import cognitive_patch_loop as loop
    from ultronpro import self_modification

    monkeypatch.setattr(self_modification, "generate_modification", lambda *a, **k: {"error": "llm_unavailable"})

    out = loop._escalate_trusted_patch_to_code({
        "proposed_change": {"domain": "memory", "key_points": [], "source_url": "https://docs.python.org/3/"},
    })

    assert out["ok"] is False
    assert out["module"] == "episodic_memory.py"
    assert out["error"] == "llm_unavailable"
