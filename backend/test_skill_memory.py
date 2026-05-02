import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ultronpro import skill_memory


def test_skill_memory_learns_promotes_and_matches_chat_intent(tmp_path, monkeypatch):
    monkeypatch.setenv("ULTRON_SKILL_MEMORY_PROMOTE_SUCCESSES", "2")
    db_path = tmp_path / "skills.sqlite"
    skills_dir = tmp_path / "learned_skills"

    first = skill_memory.learn_from_chat_turn(
        "tu ta bao?",
        "To bem sim; pronto para continuar.",
        strategy="intent_greeting",
        ok=True,
        latency_ms=120,
        source="chat_test",
        db_path=db_path,
        skills_dir=skills_dir,
    )
    assert first["ok"] is True
    assert first["skill"]["status"] == "candidate"

    second = skill_memory.learn_from_chat_turn(
        "vc ta bem?",
        "To bem sim; sigo acompanhando o contexto.",
        strategy="intent_greeting",
        ok=True,
        latency_ms=95,
        source="chat_test",
        db_path=db_path,
        skills_dir=skills_dir,
    )

    assert second["skill"]["status"] == "promoted"
    assert (skills_dir / "chat-intent-greeting.md").exists()
    assert (skills_dir / "chat-intent-greeting.meta.json").exists()

    hits = skill_memory.search("tu ta bao?", db_path=db_path)
    assert hits
    assert hits[0]["action_kind"] == "intent_greeting"

    learned = skill_memory.deterministic_chat_intent("tu ta bao?", db_path=db_path)
    assert learned
    assert learned["intent"] == "greeting"


def test_skill_memory_does_not_promote_failed_chat_turn(tmp_path):
    out = skill_memory.learn_from_chat_turn(
        "pergunta sem resposta",
        "[AVISO: a LLM local nao retornou resposta]",
        strategy="local_llm_unavailable",
        ok=False,
        db_path=tmp_path / "skills.sqlite",
        skills_dir=tmp_path / "learned_skills",
    )

    assert out["ok"] is False
