import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def test_recording_ports_capture_side_effects_without_store_or_llm():
    from ultronpro.core.ports import StaticLLMClient, payload_to_json, recording_ports

    llm = StaticLLMClient(response='{"answer":"A"}')
    ports, events, workspace, memory = recording_ports(
        actions=[{"status": "done"}, {"status": "error"}],
        llm=llm,
    )

    event_id = ports.events.add_event("kind", "text", meta={"x": 1})
    workspace_id = ports.workspace.publish("mod", "chan", {"payload": True}, salience=0.7, ttl_sec=30)
    exp_id = ports.memory.add_experience(text="experience", source_id="src", modality="test")
    insight_id = ports.memory.add_insight(kind="kind", title="title", text="insight", meta={"m": 2})
    actions = ports.actions.list_actions(limit=10)
    response = ports.llm.complete("choose", json_mode=True)

    assert event_id == 1
    assert workspace_id == 1
    assert exp_id == 1
    assert insight_id == 1
    assert events.rows[0]["meta"] == {"x": 1}
    assert workspace.rows[0]["payload"] == {"payload": True}
    assert memory.experiences[0]["source_id"] == "src"
    assert len(actions) == 2
    assert response == '{"answer":"A"}'
    assert llm.calls[0]["kwargs"]["json_mode"] is True
    assert payload_to_json({"ok": True}) == '{"ok": true}'


def test_active_investigation_probes_use_injected_read_ports():
    from ultronpro import active_investigation
    from ultronpro.core.ports import recording_ports

    ports, _, _, _ = recording_ports(
        triples=[{
            "subject": "deploy pipeline",
            "predicate": "requires",
            "object": "rollback guard",
            "note": "deploy rollback evidence",
        }],
        insights=[{
            "kind": "ops",
            "title": "deploy rollback",
            "text": "rollback guard avoids partial release",
        }],
        experiences=[{
            "id": 7,
            "source_id": "exp_7",
            "text": "pipeline deploy rollback observed after guard",
        }],
        workspace_rows=[{
            "module": "tester",
            "channel": "causal.note",
            "salience": 0.6,
            "payload_json": {"query": "deploy rollback"},
        }],
    )

    store_probe = active_investigation._probe_store("deploy rollback", ports=ports)
    workspace_probe = active_investigation._probe_workspace(ports=ports)

    assert store_probe["ok"] is True
    assert store_probe["triples"][0]["object"] == "rollback guard"
    assert store_probe["insights"][0]["title"] == "deploy rollback"
    assert store_probe["experiences"][0]["source_id"] == "exp_7"
    assert workspace_probe["ok"] is True
    assert workspace_probe["items"][0]["module"] == "tester"


def test_episodic_compiler_uses_injected_llm_and_workspace(tmp_path, monkeypatch):
    from ultronpro import episodic_compiler
    from ultronpro.core.ports import StaticLLMClient, recording_ports

    monkeypatch.delenv("BENCHMARK_MODE", raising=False)
    monkeypatch.setattr(episodic_compiler, "ABSTRACTIONS_PATH", tmp_path / "causal_abstractions_v2.json")
    llm = StaticLLMClient(
        response=(
            '{"name":"InjectedInvariant",'
            '"causal_structure":"guard before action",'
            '"applicability_conditions":"rollback present",'
            '"testable_prediction":"success improves on guarded release",'
            '"generalization_suggestion":"apply through equivalent guard structure"}'
        )
    )
    ports, _, workspace, _ = recording_ports(llm=llm)

    record = episodic_compiler.compile_causal_invariant(
        "deploy",
        "release",
        {"action": "release", "outcome": "ok", "guards": {"rollback": True}},
        surprise_score=0.1,
        ports=ports,
    )

    assert record is not None
    assert record["name"] == "InjectedInvariant"
    assert llm.calls
    assert "deploy" in llm.calls[0]["prompt"]
    assert workspace.rows[0]["channel"] == "causal.hypothesis_proposed"
    assert workspace.rows[0]["payload"]["name"] == "InjectedInvariant"


def test_workspace_bus_publish_sync_uses_ports_and_working_memory(monkeypatch):
    from ultronpro import working_memory
    from ultronpro.core import workspace_bus
    from ultronpro.core.ports import recording_ports

    ports, _, workspace, _ = recording_ports()
    working_memory_calls = []
    monkeypatch.setattr(
        working_memory,
        "add_to_working_memory",
        lambda **kwargs: working_memory_calls.append(kwargs) or 1,
    )

    workspace_id = workspace_bus.publish_sync(
        "runtime_test",
        "causal.note",
        {"ok": True},
        salience=0.8,
        ttl_sec=45,
        ports=ports,
    )

    assert workspace_id == 1
    assert workspace.rows[0]["module"] == "runtime_test"
    assert workspace.rows[0]["channel"] == "causal.note"
    assert workspace.rows[0]["payload"] == {"ok": True}
    assert working_memory_calls[0]["metadata"]["workspace_id"] == 1
