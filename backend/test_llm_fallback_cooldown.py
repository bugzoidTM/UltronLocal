import sys
import types
import uuid
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

from ultronpro import llm


def test_fallback_provider_error_marks_cooldown(monkeypatch):
    router = llm.LLMRouter()
    prompt = f"cooldown smoke {uuid.uuid4()}"

    monkeypatch.setattr(
        llm.llm_adapter,
        "route_provider",
        lambda **kwargs: {"provider": "gemini", "model": "gemini-test"},
    )
    monkeypatch.setattr(
        llm.llm_adapter,
        "provider_priority",
        lambda **kwargs: ["gemini", "openrouter"],
    )
    monkeypatch.setattr(llm.llm_adapter, "maybe_quarantine_provider", lambda *args, **kwargs: {"ok": True})
    monkeypatch.setattr(router, "_get_client", lambda provider: {"provider": provider})
    monkeypatch.setattr(
        router,
        "_call_gemini",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("429 Too Many Requests")),
    )
    monkeypatch.setattr(
        router,
        "_call_openai_compat",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("429 Too Many Requests")),
    )

    assert router.complete(prompt, strategy="default", inject_persona=False) == ""
    assert router._provider_cooldown_active("gemini")
    assert router._provider_cooldown_active("openrouter")
