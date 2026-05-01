import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    import pydantic  # noqa: F401
except ModuleNotFoundError:
    pydantic_stub = types.ModuleType("pydantic")

    class BaseModel:
        pass

    pydantic_stub.BaseModel = BaseModel
    sys.modules["pydantic"] = pydantic_stub

from ultronpro import extract


def test_extract_triples_stops_after_empty_llm(monkeypatch):
    calls = {"n": 0}

    def fake_complete(*args, **kwargs):
        calls["n"] += 1
        return ""

    def fail_sleep(*args, **kwargs):
        raise AssertionError("extract_triples must not block the event loop with sleep")

    monkeypatch.setattr(extract.llm, "complete", fake_complete)
    monkeypatch.setattr(extract.time, "sleep", fail_sleep)

    out = extract.extract_triples(
        "Texto sem relacao estruturada suficiente para extrair triplas locais.",
        max_retries=3,
    )

    assert out == []
    assert calls["n"] == 1
