from ultronpro.ultron_ui import local_llm
from ultronpro.ultron_ui.config import default_config, save_config, load_config, preset_for, validate_cloud_config


def test_config_roundtrip_cloud_fallback(tmp_path, monkeypatch):
    cfg_path = tmp_path / "ultron_ui_config.json"
    monkeypatch.setattr("ultronpro.ultron_ui.config.CONFIG_PATH", cfg_path)

    cfg = default_config()
    cfg["cloud"].update(
        {
            "enabled": True,
            "provider": "free_auto",
            "base_url": "https://text.pollinations.ai",
            "model": "openai",
            "api_key": "",
        }
    )

    save_config(cfg)
    loaded = load_config()

    assert loaded["cloud"]["enabled"] is True
    assert loaded["cloud"]["provider"] == "free_auto"
    assert loaded["cloud"]["model"] == "openai"
    assert loaded["cloud"]["api_key"] == ""


def test_ultron_llm_uses_cloud_when_local_fails(monkeypatch):
    class FakeLocal:
        def complete(self, *args, **kwargs):
            raise TimeoutError("local busy")

    class FakeCloud:
        def __init__(self, config):
            self.provider = "free_auto"
            self.model = "openai"

        def complete(self, *args, **kwargs):
            return "resposta cloud"

    monkeypatch.setattr(local_llm, "LocalQwenClient", lambda: FakeLocal())
    monkeypatch.setattr(local_llm, "CloudFallbackClient", FakeCloud)
    monkeypatch.setattr(
        local_llm,
        "load_config",
        lambda: {
            "local": {"enabled": True},
            "cloud": {
                "enabled": True,
                "provider": "free_auto",
                "base_url": "https://text.pollinations.ai",
                "model": "openai",
                "api_key": "",
            },
        },
    )
    client = local_llm.UltronLLMClient()

    assert client.complete("ola") == "resposta cloud"
    assert client.last_route == "cloud:Automático grátis (sem chave)"
    assert client.last_model == "openai"
    assert "openai" in client.runtime_description()


def test_voice_reply_uses_backend_synthesized_text_without_local_resynthesis(monkeypatch):
    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "answer": "Encontrei cobertura direta insuficiente. Lacunas restantes: aresta_causal_relevante.",
                "synthesized_text": "Ainda nao tenho evidencia suficiente para fechar isso com seguranca.",
                "trace_causal": {"source_module": "causal_transfer_engine"},
            }

    class FakeHttpClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(local_llm.httpx, "Client", FakeHttpClient)
    client = local_llm.UltronLLMClient()
    monkeypatch.setattr(
        client,
        "complete",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("local synthesis should not run")),
    )

    assert client.voice_reply("teste") == "Ainda nao tenho evidencia suficiente para fechar isso com seguranca."
    assert client.last_route == "causal_brain (via causal_transfer_engine)"


def test_free_auto_preset_needs_no_key_and_openrouter_still_requires_key():
    assert preset_for("free_auto")["model"] == "openai"

    cfg = default_config()
    cfg["cloud"].update({"enabled": True, "provider": "free_auto", "api_key": "", "model": ""})
    ok, err = validate_cloud_config(cfg)

    assert ok is True
    assert err == ""

    cfg["cloud"].update(
        {
            "enabled": True,
            "provider": "openrouter",
            "base_url": "https://openrouter.ai/api/v1",
            "model": "openai/gpt-4o-mini",
            "api_key": "",
        }
    )
    ok, err = validate_cloud_config(cfg)

    assert ok is False
    assert "API key" in err
