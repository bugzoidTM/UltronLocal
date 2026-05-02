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


def test_extract_triples_accepts_single_dict_payload(monkeypatch):
    calls = {"n": 0}

    def fake_complete(*args, **kwargs):
        calls["n"] += 1
        return '{"s":"UltronPro","p":"usa","o":"memoria de skills"}'

    monkeypatch.setattr(extract.llm, "complete", fake_complete)

    out = extract.extract_triples(
        "UltronPro usa memoria de skills para economizar chamadas LLM.",
        max_retries=3,
    )

    assert calls["n"] == 1
    assert out == [("UltronPro", "usa", "memoria de skills", 0.85)]


def test_extract_triples_unwraps_nested_string_payload(monkeypatch):
    calls = {"n": 0}

    def fake_complete(*args, **kwargs):
        calls["n"] += 1
        return '{"result":"[{\\"subject\\":\\"Chat\\",\\"predicate\\":\\"aprende\\",\\"object\\":\\"rotas\\",\\"confidence\\":0.7}]"}'

    monkeypatch.setattr(extract.llm, "complete", fake_complete)

    out = extract.extract_triples(
        "Chat aprende rotas reutilizaveis depois de interacoes bem-sucedidas.",
        max_retries=3,
    )

    assert calls["n"] == 1
    assert out == [("Chat", "aprende", "rotas", 0.7)]
