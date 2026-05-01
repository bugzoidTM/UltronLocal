import json
import struct
import sys
import tempfile
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent))


def test_loop_event_binary_payload_roundtrip():
    from ultronpro import binary_protocol

    payload = binary_protocol.encode_loop_event(
        loop_name="roadmap_v5_loop",
        event="background_call_ok",
        payload='{"label":"tick"}',
        kind="event",
        severity="info",
        ts_ms=12345,
    )
    decoded = binary_protocol.decode_loop_event(payload)

    assert decoded["loop_name"] == "roadmap_v5_loop"
    assert decoded["event"] == "background_call_ok"
    assert decoded["kind"] == "event"
    assert decoded["severity"] == "info"
    assert decoded["payload"] == '{"label":"tick"}'


def test_background_binary_bus_writes_journal_and_dispatches_workspace():
    from ultronpro import background_binary_bus, binary_protocol

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        original = {
            "binlog": background_binary_bus.BINLOG_PATH,
            "state": background_binary_bus.STATE_PATH,
            "guard": background_binary_bus.GUARD_STATE_PATH,
            "enabled": background_binary_bus.ENABLED,
            "workspace_enabled": background_binary_bus.ASYNC_WORKSPACE_ENABLED,
        }
        background_binary_bus.stop()
        try:
            background_binary_bus.BINLOG_PATH = tmp_path / "background_bus.binlog"
            background_binary_bus.STATE_PATH = tmp_path / "background_bus_state.json"
            background_binary_bus.GUARD_STATE_PATH = tmp_path / "background_guard.json"
            background_binary_bus.ENABLED = True
            background_binary_bus.ASYNC_WORKSPACE_ENABLED = True

            calls = []

            def sink(**kwargs):
                calls.append(kwargs)
                return 123

            background_binary_bus.register_workspace_sink(sink)
            assert background_binary_bus.publish_loop_event("autonomy_loop", "tick", {"ok": True})
            assert background_binary_bus.publish_workspace_task(
                loop_name="autonomy_loop",
                module="test",
                channel="workspace.test",
                payload={"fact": "value"},
                salience=0.7,
                ttl_sec=60,
            )
            assert background_binary_bus.publish_guard_state({"state": "paused", "paused": True, "lag_sec": 2.5})
            assert background_binary_bus.flush(3.0)
            background_binary_bus.stop()

            assert calls and calls[0]["module"] == "test"
            assert calls[0]["payload"] == {"fact": "value"}
            assert json.loads(background_binary_bus.GUARD_STATE_PATH.read_text(encoding="utf-8"))["state"] == "paused"

            raw = background_binary_bus.BINLOG_PATH.read_bytes()
            size = struct.unpack("!I", raw[:4])[0]
            frame = binary_protocol.decode_frame(
                raw[4 : 4 + size],
                key=background_binary_bus._KEY,
                expected_nonce=background_binary_bus._NONCE,
            )
            decoded = binary_protocol.decode_loop_event(frame.payload)
            assert frame.opcode == binary_protocol.OP_LOOP_EVENT
            assert decoded["loop_name"] == "autonomy_loop"
        finally:
            background_binary_bus.stop()
            background_binary_bus.BINLOG_PATH = original["binlog"]
            background_binary_bus.STATE_PATH = original["state"]
            background_binary_bus.GUARD_STATE_PATH = original["guard"]
            background_binary_bus.ENABLED = original["enabled"]
            background_binary_bus.ASYNC_WORKSPACE_ENABLED = original["workspace_enabled"]
            background_binary_bus.register_workspace_sink(None)
