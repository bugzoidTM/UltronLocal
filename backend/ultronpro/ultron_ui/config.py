from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from . import paths


CONFIG_PATH = paths.DATA_DIR / "ultron_ui_config.json"

PROVIDER_PRESETS: dict[str, dict[str, str]] = {
    "free_auto": {
        "label": "Automático grátis (sem chave)",
        "base_url": "https://text.pollinations.ai",
        "model": "openai",
    },
    "pollinations": {
        "label": "Pollinations grátis",
        "base_url": "https://text.pollinations.ai",
        "model": "openai",
    },
    "g4f": {
        "label": "g4f grátis",
        "base_url": "",
        "model": "auto",
    },
    "openrouter": {
        "label": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "model": "openai/gpt-4o-mini",
    },
    "groq": {
        "label": "Groq",
        "base_url": "https://api.groq.com/openai/v1",
        "model": "llama-3.3-70b-versatile",
    },
    "openai": {
        "label": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
    },
    "deepseek": {
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
    },
    "custom": {
        "label": "Custom OpenAI-compatible",
        "base_url": "",
        "model": "",
    },
}


def default_config() -> dict[str, Any]:
    return {
        "local": {
            "enabled": True,
            "base_url": os.getenv("ULTRON_UI_QWEN_URL", "http://127.0.0.1:8025"),
            "timeout_sec": int(os.getenv("ULTRON_UI_QWEN_TIMEOUT_SEC", "9") or 9),
        },
        "cloud": {
            "enabled": False,
            "provider": "free_auto",
            "base_url": PROVIDER_PRESETS["free_auto"]["base_url"],
            "model": PROVIDER_PRESETS["free_auto"]["model"],
            "api_key": "",
            "timeout_sec": 18,
            "max_tokens": 160,
        },
    }


def load_config() -> dict[str, Any]:
    config = default_config()
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            _deep_update(config, data)
    except Exception:
        pass
    _apply_env_overrides(config)
    _fill_cloud_preset_defaults(config)
    return config


def save_config(config: dict[str, Any]) -> dict[str, Any]:
    merged = default_config()
    _deep_update(merged, config if isinstance(config, dict) else {})
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(CONFIG_PATH, 0o600)
    except Exception:
        pass
    return merged


def provider_label(provider: str) -> str:
    preset = PROVIDER_PRESETS.get(str(provider or "").strip().lower())
    return str((preset or {}).get("label") or provider or "cloud")


def preset_for(provider: str) -> dict[str, str]:
    return dict(PROVIDER_PRESETS.get(str(provider or "").strip().lower()) or PROVIDER_PRESETS["custom"])


def redacted(config: dict[str, Any]) -> dict[str, Any]:
    out = json.loads(json.dumps(config or {}))
    cloud = out.get("cloud") if isinstance(out, dict) else None
    if isinstance(cloud, dict) and cloud.get("api_key"):
        key = str(cloud.get("api_key") or "")
        cloud["api_key"] = key[:4] + "..." + key[-4:] if len(key) >= 10 else "***"
    return out


def validate_cloud_config(config: dict[str, Any]) -> tuple[bool, str]:
    cloud = (config or {}).get("cloud") or {}
    if not cloud.get("enabled"):
        return True, ""
    provider = str(cloud.get("provider") or "free_auto").strip().lower()
    if provider in {"free_auto", "pollinations", "g4f"}:
        return True, ""
    missing = []
    if not str(cloud.get("base_url") or "").strip():
        missing.append("Base URL")
    if not str(cloud.get("model") or "").strip():
        missing.append("Modelo")
    if not str(cloud.get("api_key") or "").strip():
        missing.append("API key")
    if missing:
        return False, "Campos obrigatórios do fallback: " + ", ".join(missing)
    return True, ""


def _deep_update(target: dict[str, Any], source: dict[str, Any]) -> None:
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_update(target[key], value)
        else:
            target[key] = value


def _apply_env_overrides(config: dict[str, Any]) -> None:
    local = config.setdefault("local", {})
    cloud = config.setdefault("cloud", {})
    if os.getenv("ULTRON_UI_QWEN_URL"):
        local["base_url"] = os.getenv("ULTRON_UI_QWEN_URL")
    if os.getenv("ULTRON_UI_QWEN_TIMEOUT_SEC"):
        local["timeout_sec"] = int(os.getenv("ULTRON_UI_QWEN_TIMEOUT_SEC") or local.get("timeout_sec") or 9)
    if os.getenv("ULTRON_UI_CLOUD_ENABLED"):
        cloud["enabled"] = str(os.getenv("ULTRON_UI_CLOUD_ENABLED") or "").strip().lower() in {"1", "true", "yes", "on"}
    if os.getenv("ULTRON_UI_CLOUD_PROVIDER"):
        cloud["provider"] = os.getenv("ULTRON_UI_CLOUD_PROVIDER")
    if os.getenv("ULTRON_UI_CLOUD_BASE_URL"):
        cloud["base_url"] = os.getenv("ULTRON_UI_CLOUD_BASE_URL")
    if os.getenv("ULTRON_UI_CLOUD_MODEL"):
        cloud["model"] = os.getenv("ULTRON_UI_CLOUD_MODEL")
    if os.getenv("ULTRON_UI_CLOUD_API_KEY"):
        cloud["api_key"] = os.getenv("ULTRON_UI_CLOUD_API_KEY")


def _fill_cloud_preset_defaults(config: dict[str, Any]) -> None:
    cloud = config.setdefault("cloud", {})
    provider = str(cloud.get("provider") or "free_auto").strip().lower()
    if provider not in {"free_auto", "pollinations", "g4f"} and not str(os.getenv("ULTRON_UI_ALLOW_KEYED_CLOUD", "")).strip():
        provider = "free_auto"
        cloud["provider"] = provider
        cloud["api_key"] = ""
    preset = preset_for(provider)
    if provider in {"free_auto", "pollinations", "g4f"}:
        cloud["base_url"] = preset.get("base_url", "")
        cloud["model"] = preset.get("model", "")
        cloud["api_key"] = ""
        return
    if not str(cloud.get("base_url") or "").strip() and preset.get("base_url"):
        cloud["base_url"] = preset["base_url"]
    if not str(cloud.get("model") or "").strip() and preset.get("model"):
        cloud["model"] = preset["model"]
