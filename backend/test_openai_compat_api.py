import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ultronpro.api.openai_compat import MODEL_ALIAS, UpstreamInferenceError, router


def _client(monkeypatch, keys="sk-test-key"):
    monkeypatch.setenv("ULTRON_OPENAI_COMPAT_API_KEYS", keys)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_models_requires_bearer_key(monkeypatch):
    client = _client(monkeypatch)

    response = client.get("/v1/models")

    assert response.status_code == 401
    assert response.json()["error"]["type"] == "authentication_error"


def test_models_lists_qwen_model_with_bearer_key(monkeypatch):
    client = _client(monkeypatch)

    response = client.get("/v1/models", headers={"Authorization": "Bearer sk-test-key"})

    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "list"
    assert body["data"][0]["id"] == MODEL_ALIAS
    assert body["data"][0]["object"] == "model"


def test_chat_completion_forwards_messages_to_qwen_and_returns_openai_shape(monkeypatch):
    captured = {}

    async def fake_generate(payload):
        captured.update(payload)
        return {"ok": True, "text": "Resposta do Qwen", "base_model": "qwen-test"}

    monkeypatch.setattr("ultronpro.api.openai_compat.call_qwen_generate", fake_generate)
    client = _client(monkeypatch)

    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer sk-test-key"},
        json={
            "model": MODEL_ALIAS,
            "messages": [
                {"role": "system", "content": "Responda em portugues."},
                {"role": "user", "content": "Oi"},
                {"role": "assistant", "content": "Ola!"},
                {"role": "user", "content": "Diga uma frase curta."},
            ],
            "max_tokens": 64,
            "temperature": 0.1,
        },
    )

    assert response.status_code == 200
    assert captured["system"] == "Responda em portugues."
    assert "User: Oi" in captured["prompt"]
    assert "Assistant: Ola!" in captured["prompt"]
    assert captured["prompt"].endswith("Assistant:")
    assert captured["max_new_tokens"] == 64
    assert captured["temperature"] == 0.1

    body = response.json()
    assert body["object"] == "chat.completion"
    assert body["model"] == MODEL_ALIAS
    assert body["choices"][0]["message"] == {"role": "assistant", "content": "Resposta do Qwen"}
    assert body["choices"][0]["finish_reason"] == "stop"


def test_chat_completion_translates_upstream_errors(monkeypatch):
    async def fake_generate(payload):
        raise UpstreamInferenceError(429, "inference_busy_retry")

    monkeypatch.setattr("ultronpro.api.openai_compat.call_qwen_generate", fake_generate)
    client = _client(monkeypatch)

    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer sk-test-key"},
        json={
            "model": MODEL_ALIAS,
            "messages": [{"role": "user", "content": "teste"}],
        },
    )

    assert response.status_code == 429
    assert response.json()["error"]["type"] == "upstream_error"


def test_main_registers_openai_compat_router():
    main_path = Path(__file__).resolve().parent / "ultronpro" / "main.py"
    text = main_path.read_text(encoding="utf-8")

    assert "openai_compat_router" in text
    assert "app.include_router(openai_compat_router)" in text
