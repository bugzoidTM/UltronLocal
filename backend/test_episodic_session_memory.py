from pathlib import Path
import json
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))


def test_chat_turns_become_structured_store_episodes_and_compact(tmp_path):
    from ultronpro import episodic_memory, store

    db = store.Store(tmp_path / "episodic.db")
    store_module = SimpleNamespace(db=db, publish_workspace=db.publish_workspace)

    for idx in range(7):
        out = episodic_memory.record_chat_turn(
            session_id="unit-session",
            user_text=f"pedido {idx}: explique a etapa anterior e mantenha contexto detalhado " * 3,
            assistant_text=f"resposta {idx}: vou manter a continuidade da conversa e responder em texto " * 3,
            strategy="unit_chat",
            source="chat_stream",
            store_module=store_module,
            context_limit_chars=900,
            keep_recent=2,
        )
        assert out["ok"] is True
        assert out["episode_id"].startswith("ep_chat_")

    session = db.get_chat_session("unit-session")
    assert session is not None
    assert int(session["compacted_turns"]) > 0

    raw_turns = json.loads(session["raw_context_json"])
    assert len(raw_turns) <= 2
    assert "pedido 0" in session["compact_context"]

    episodes = db.list_episodic_episodes(session_id="unit-session", episode_type="chat_turn", limit=10)
    assert len(episodes) == 7
    structured = json.loads(episodes[0]["structured_json"])
    assert structured["schema"] == "ultronpro.episodic.chat_turn.v1"
    assert structured["context"]["compacted_turns"] > 0

    events = db.list_events(0, 20)
    assert any(event["kind"] == "episodic_chat_turn" for event in events)

    workspace = db.read_workspace(channels=["memory.episode.chat"], limit=20, include_expired=True)
    assert workspace

    prompt_context = episodic_memory.chat_session_prompt_context(
        "unit-session",
        max_chars=1200,
        store_module=store_module,
    )
    assert "Resumo compactado da sessao" in prompt_context
    assert "Turnos recentes" in prompt_context
