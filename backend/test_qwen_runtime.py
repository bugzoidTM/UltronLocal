from __future__ import annotations

import json

from ultronpro import qwen_runtime


def test_auto_profile_selects_cpu_or_light_from_memory(monkeypatch):
    monkeypatch.delenv("ULTRON_QWEN_PROFILE", raising=False)

    cpu = qwen_runtime.choose_profile(
        hardware={
            "available_ram_gb": 4.0,
            "total_ram_gb": 8.0,
            "gpus": [],
            "gpu_backend_available": False,
        }
    )
    light = qwen_runtime.choose_profile(
        hardware={
            "available_ram_gb": 1.2,
            "total_ram_gb": 8.0,
            "gpus": [],
            "gpu_backend_available": False,
        }
    )

    assert cpu.name == "cpu_8k"
    assert cpu.ctx == 8192
    assert cpu.cache_k == "q8_0"
    assert light.name == "light_4k"
    assert light.ctx == 4096
    assert light.cache_k == "q4_0"


def test_llama_server_args_include_stability_and_kv_flags(monkeypatch, tmp_path):
    model = tmp_path / "qwen.gguf"
    server = tmp_path / "llama-server.exe"
    model.write_text("", encoding="utf-8")
    server.write_text("", encoding="utf-8")
    monkeypatch.setenv("ULTRON_QWEN_MODEL_PATH", str(model))
    monkeypatch.setenv("ULTRON_LLAMA_SERVER_PATH", str(server))

    args = qwen_runtime.llama_server_args(
        qwen_runtime.PROFILES["cpu_8k"],
        port=8025,
        threads=2,
        include_mlock=True,
    )

    assert args[0] == str(server)
    assert args[args.index("-m") + 1] == str(model)
    assert args[args.index("--ctx-size") + 1] == "8192"
    assert args[args.index("-ngl") + 1] == "0"
    assert "--no-mmap" in args
    assert args[args.index("-ctk") + 1] == "q8_0"
    assert args[args.index("-ctv") + 1] == "q8_0"
    assert args[args.index("--parallel") + 1] == "1"
    assert args[args.index("--cache-ram") + 1] == "512"
    assert "--mlock" in args


def test_generation_defaults_follow_active_state(monkeypatch, tmp_path):
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"profile": "light_4k", "status": "running"}), encoding="utf-8")
    monkeypatch.setenv("ULTRON_QWEN_RUNTIME_STATE", str(state))

    defaults = qwen_runtime.generation_defaults()

    assert defaults["profile"]["name"] == "light_4k"
    assert defaults["max_tokens"] == 384
    assert defaults["temperature"] == 0.3


def test_stopped_state_does_not_pin_active_profile(monkeypatch, tmp_path):
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"profile": "light_4k", "status": "stopped"}), encoding="utf-8")
    monkeypatch.setenv("ULTRON_QWEN_RUNTIME_STATE", str(state))
    monkeypatch.delenv("ULTRON_QWEN_PROFILE", raising=False)
    monkeypatch.setattr(
        qwen_runtime,
        "hardware_snapshot",
        lambda: {
            "available_ram_gb": 4.0,
            "total_ram_gb": 8.0,
            "gpus": [],
            "gpu_backend_available": False,
        },
    )

    assert qwen_runtime.active_profile_name() == "cpu_8k"


def test_autostart_can_be_disabled_without_touching_server(monkeypatch):
    monkeypatch.setenv("ULTRON_QWEN_AUTOSTART", "0")

    result = qwen_runtime.ensure_server_started(reason="unit_test")

    assert result["ok"] is True
    assert result["started"] is False
    assert result["reason"] == "autostart_disabled"


def test_endpoint_host_port_uses_local_infer_url(monkeypatch):
    monkeypatch.setenv("ULTRON_LOCAL_INFER_URL", "http://127.0.0.1:8025")

    assert qwen_runtime.endpoint_host_port() == ("127.0.0.1", 8025)
