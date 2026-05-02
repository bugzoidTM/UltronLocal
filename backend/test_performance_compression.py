import os
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse, StreamingResponse
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent))


def test_pack_text_is_lossless_and_bypasses_random_like_payload():
    from ultronpro import performance_compression as pc

    text = ("episodic context " * 600).strip()
    packed = pc.pack_text(text, min_bytes=64)
    assert packed.startswith(pc.ENVELOPE_PREFIX)
    assert pc.unpack_text(packed) == text

    randomish = bytes(range(256)) * 8
    packed_bytes, decision = pc.gzip_decision(randomish, content_type="application/octet-stream", min_bytes=64)
    assert packed_bytes == randomish
    assert decision.compress is False
    assert decision.reason in {"content_type_bypass", "high_entropy", "insufficient_gain"}


def test_entropy_aware_http_middleware_compresses_text_and_skips_sse():
    from ultronpro.performance_compression import EntropyAwareCompressionMiddleware

    app = FastAPI()
    app.add_middleware(EntropyAwareCompressionMiddleware, min_bytes=128)

    @app.get("/large")
    def large():
        return PlainTextResponse("UltronPro compression test\n" * 400)

    @app.get("/events")
    def events():
        return StreamingResponse(iter([b"data: hello\n\n"]), media_type="text/event-stream")

    client = TestClient(app)
    large = client.get("/large", headers={"accept-encoding": "gzip"})
    assert large.headers.get("content-encoding") == "gzip"
    assert large.headers.get("x-ultron-compression", "").startswith("gzip")

    # TestClient returns the decoded body, so use the header only for behavior.
    assert "UltronPro compression test" in large.text

    events = client.get("/events", headers={"accept-encoding": "gzip"})
    assert events.headers.get("content-encoding") is None
    assert events.text == "data: hello\n\n"


def test_storage_compression_envelope_is_decoded_by_store(tmp_path):
    os.environ["ULTRON_STORAGE_COMPRESSION_MIN_BYTES"] = "128"

    from ultronpro import episodic_memory, store

    db = store.Store(tmp_path / "compressed_store.db")
    long_user = "pedido com muita repeticao para forcar compressao interna " * 20
    long_answer = "resposta estruturada tambem repetitiva para reduzir I/O SQLite " * 20

    episodic_memory.record_chat_turn(
        session_id="compression-session",
        user_text=long_user,
        assistant_text=long_answer,
        strategy="unit",
        store_module=db,
        context_limit_chars=600,
        keep_recent=1,
    )

    with db._conn() as c:
        raw = c.execute("SELECT raw_context_json FROM chat_sessions WHERE session_id=?", ("compression-session",)).fetchone()
    assert raw is not None
    assert str(raw["raw_context_json"]).startswith("ULTRONC1:")

    decoded = db.get_chat_session("compression-session")
    assert decoded is not None
    assert "pedido com muita repeticao" in decoded["raw_context_json"]
