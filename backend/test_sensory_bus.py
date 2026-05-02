from pathlib import Path
import asyncio
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))


class FakeDB:
    def __init__(self):
        self.events = []
        self.experiences = []
        self.memories = []

    def add_event(self, kind, text, meta_json=None):
        self.events.append({"kind": kind, "text": text, "meta_json": meta_json})
        return len(self.events)

    def add_experience(self, user_id, text, source_id=None, modality="text", blob_path=None, mime=None, embedding_json=None):
        self.experiences.append({
            "user_id": user_id,
            "text": text,
            "source_id": source_id,
            "modality": modality,
            "blob_path": blob_path,
            "mime": mime,
            "embedding_json": embedding_json,
        })
        return len(self.experiences)

    def add_autobiographical_memory(self, text, memory_type="short_term", importance=0.5, decay_rate=0.01, content_json=None):
        self.memories.append({
            "text": text,
            "memory_type": memory_type,
            "importance": importance,
            "decay_rate": decay_rate,
            "content_json": content_json,
        })
        return len(self.memories)


class FakeStore:
    def __init__(self):
        self.db = FakeDB()
        self.workspace = []

    def publish_workspace(self, module, channel, payload_json, salience=0.5, ttl_sec=900):
        self.workspace.append({
            "module": module,
            "channel": channel,
            "payload_json": payload_json,
            "salience": salience,
            "ttl_sec": ttl_sec,
        })
        return len(self.workspace)


def test_normalizes_all_supported_sources_with_consent_scope():
    from ultronpro import sensory_bus

    for source_type in sorted(sensory_bus.SOURCE_TYPES):
        event = sensory_bus.normalize_event(source_type=source_type, payload={"text": f"{source_type} payload"})
        assert event.source_type == source_type
        assert event.consent_scope in sensory_bus.CONSENT_SCOPES
        assert event.event_id.startswith("se_")
        assert event.content_text


def test_queue_persists_auditable_event_and_workspace_publication():
    from ultronpro import sensory_bus

    fake = FakeStore()
    bus = sensory_bus.SensoryBus(store_module=fake)

    async def run():
        await bus.submit(
            source_type="tool",
            source="unit_tool",
            payload={"text": "token=supersecret12345 tool finished"},
            consent_scope="tool_output",
            salience=0.7,
        )
        return await bus.drain()

    results = asyncio.run(run())

    assert results[0]["ok"] is True
    assert fake.db.events[0]["kind"] == "sensory_tool"
    assert "supersecret12345" not in fake.db.events[0]["meta_json"]
    assert fake.db.experiences[0]["modality"] == "tool"
    assert fake.db.memories
    assert fake.workspace[0]["channel"] == "sensory.tool"
    payload = json.loads(fake.workspace[0]["payload_json"])
    assert payload["consent"]["scope"] == "tool_output"
    assert payload["redacted"] is True


def test_restricted_consent_keeps_audit_but_skips_workspace():
    from ultronpro import sensory_bus

    fake = FakeStore()
    bus = sensory_bus.SensoryBus(store_module=fake)

    async def run():
        await bus.submit(
            source_type="audio",
            payload={"transcript": "private utterance"},
            consent_scope="restricted",
            allow_persist=False,
        )
        return await bus.drain()

    results = asyncio.run(run())

    assert results[0]["audit_event_id"] == 1
    assert results[0]["experience_id"] is None
    assert results[0]["workspace_id"] is None
    assert fake.db.events[0]["kind"] == "sensory_audio"
    assert "private utterance" not in fake.db.events[0]["meta_json"]
    assert "NOT_PERSISTED_BY_CONSENT" in fake.db.events[0]["meta_json"]
    assert fake.db.experiences == []
    assert fake.workspace == []
