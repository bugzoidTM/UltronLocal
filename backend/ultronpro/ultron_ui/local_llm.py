from __future__ import annotations

import os
import concurrent.futures
from typing import Any

import httpx

from ultronpro import qwen_runtime
from .config import load_config, provider_label


FREE_PROVIDERS = {"free_auto", "pollinations", "g4f"}


class LocalQwenClient:
    """Small OpenAI-compatible client for the local llama-server only."""

    def __init__(self, *, base_url: str | None = None, timeout_sec: float | None = None) -> None:
        config = load_config().get("local", {})
        self.base_url = str(base_url or config.get("base_url") or os.getenv("ULTRON_UI_QWEN_URL") or qwen_runtime.endpoint_url()).rstrip("/")
        self.timeout_sec = float(timeout_sec or float(config.get("timeout_sec") or os.getenv("ULTRON_UI_QWEN_TIMEOUT_SEC", "9") or 9))
        self.model = os.getenv("ULTRON_UI_QWEN_MODEL", qwen_runtime.MODEL_ALIAS)

    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int = 160,
        temperature: float = 0.25,
    ) -> str:
        try:
            qwen_runtime.ensure_server_started(reason="ultron_ui", wait_health_sec=0)
        except Exception:
            pass

        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": str(system)})
        messages.append({"role": "user", "content": str(prompt or "")})
        body = {
            "model": self.model,
            "messages": messages,
            "temperature": float(temperature),
            "max_tokens": max(16, min(1024, int(max_tokens or 160))),
            "stream": False,
        }
        with httpx.Client(timeout=max(4.0, self.timeout_sec)) as client:
            response = client.post(self.base_url + "/v1/chat/completions", json=body)
            response.raise_for_status()
            data = response.json() if response.text else {}
        return _extract_chat_text(data)

    def voice_reply(self, command: str) -> str:
        system = (
            "Você é UltronPro, um assistente local. Responda sempre em português brasileiro, "
            "sem depender de APIs externas. Seja curto, prático e natural para voz."
        )
        prompt = f"Comando de voz do usuário: {command}\nResponda em no máximo duas frases."
        return self.complete(prompt, system=system, max_tokens=48, temperature=0.2)


class CloudFallbackClient:
    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = dict(config or {})
        self.provider = str(self.config.get("provider") or "cloud").strip().lower()
        self.base_url = str(self.config.get("base_url") or "").strip().rstrip("/")
        self.model = str(self.config.get("model") or "").strip()
        self.api_key = str(self.config.get("api_key") or "").strip()
        self.timeout_sec = float(self.config.get("timeout_sec") or 18)
        self.max_tokens = int(self.config.get("max_tokens") or 160)

    def enabled(self) -> bool:
        if self.provider in FREE_PROVIDERS:
            return bool(self.config.get("enabled"))
        return bool(self.config.get("enabled")) and bool(self.base_url and self.model and self.api_key)

    def missing_fields(self) -> list[str]:
        missing = []
        if not self.base_url:
            missing.append("base_url")
        if not self.model:
            missing.append("model")
        if not self.api_key:
            missing.append("api_key")
        return missing

    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int = 160,
        temperature: float = 0.25,
    ) -> str:
        if not self.enabled():
            missing = ",".join(self.missing_fields()) or "disabled"
            raise RuntimeError(f"cloud_fallback_not_configured:{missing}")
        if self.provider == "free_auto":
            return self._complete_free_rotation(prompt, system=system, max_tokens=max_tokens, temperature=temperature)
        if self.provider == "pollinations":
            return self._complete_pollinations(prompt, system=system, max_tokens=max_tokens, temperature=temperature)
        if self.provider == "g4f":
            return self._complete_g4f_rotation(prompt, system=system, max_tokens=max_tokens, temperature=temperature)
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": str(system)})
        messages.append({"role": "user", "content": str(prompt or "")})
        body = {
            "model": self.model,
            "messages": messages,
            "temperature": float(temperature),
            "max_tokens": max(16, min(self.max_tokens, int(max_tokens or self.max_tokens))),
            "stream": False,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if self.provider == "openrouter":
            headers["HTTP-Referer"] = "http://localhost/ultron-ui"
            headers["X-Title"] = "Ultron UI"
        with httpx.Client(timeout=max(6.0, self.timeout_sec)) as client:
            response = client.post(self.base_url + "/chat/completions", json=body, headers=headers)
            _raise_for_status_with_body(response)
            data = response.json() if response.text else {}
        return _extract_chat_text(data)

    def _messages(self, prompt: str, system: str | None) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": str(system)})
        messages.append({"role": "user", "content": str(prompt or "")})
        return messages

    def _complete_free_rotation(
        self,
        prompt: str,
        *,
        system: str | None,
        max_tokens: int,
        temperature: float,
    ) -> str:
        errors: list[str] = []
        for label, func in (
            ("pollinations", self._complete_pollinations),
            ("g4f", self._complete_g4f_rotation),
        ):
            try:
                text = func(prompt, system=system, max_tokens=max_tokens, temperature=temperature)
                if _is_usable_reply(text):
                    self.provider = label
                    return text
                errors.append(f"{label}:empty")
            except Exception as exc:
                errors.append(f"{label}:{type(exc).__name__}:{str(exc)[:140]}")
        raise RuntimeError("; ".join(errors) or "free_rotation_failed")

    def _complete_pollinations(
        self,
        prompt: str,
        *,
        system: str | None,
        max_tokens: int,
        temperature: float,
    ) -> str:
        base = (self.base_url if self.provider == "pollinations" and self.base_url else "https://text.pollinations.ai").rstrip("/")
        model = self.model if self.provider == "pollinations" and self.model else "openai"
        body = {
            "model": model,
            "messages": self._messages(prompt, system),
            "temperature": float(temperature),
            "max_tokens": max(16, min(self.max_tokens, int(max_tokens or self.max_tokens))),
            "stream": False,
        }
        with httpx.Client(timeout=max(6.0, self.timeout_sec)) as client:
            response = client.post(base + "/v1/chat/completions", json=body)
            _raise_for_status_with_body(response)
            data = response.json() if response.text else {}
        text = _extract_chat_text(data)
        if not _is_usable_reply(text):
            raise RuntimeError("pollinations_empty_or_unusable_reply")
        self.model = model
        return text

    def _complete_g4f_rotation(
        self,
        prompt: str,
        *,
        system: str | None,
        max_tokens: int,
        temperature: float,
    ) -> str:
        attempts = [
            ("PollinationsAI", "openai"),
            ("CohereForAI_C4AI_Command", ""),
            ("Yqcloud", ""),
            ("OpenRouterFree", "gpt-4o-mini"),
        ]
        errors: list[str] = []
        for provider_name, model in attempts:
            try:
                text = _run_g4f_once(
                    provider_name=provider_name,
                    model=model,
                    messages=self._messages(prompt, system),
                    max_tokens=max(16, min(self.max_tokens, int(max_tokens or self.max_tokens))),
                    timeout_sec=max(8.0, min(self.timeout_sec, 28.0)),
                )
                if _is_usable_reply(text):
                    self.provider = f"g4f/{provider_name}"
                    self.model = model or provider_name
                    return text
                errors.append(f"{provider_name}:empty")
            except Exception as exc:
                errors.append(f"{provider_name}:{type(exc).__name__}:{str(exc)[:100]}")
        raise RuntimeError("; ".join(errors) or "g4f_rotation_failed")


class UltronLLMClient:
    def __init__(self) -> None:
        self.local = LocalQwenClient()
        self.last_route = ""
        self.last_model = ""
        self.last_error = ""

    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int = 160,
        temperature: float = 0.25,
    ) -> str:
        config = load_config()
        errors: list[str] = []
        if (config.get("local") or {}).get("enabled", True):
            try:
                self.local = LocalQwenClient()
                text = self.local.complete(prompt, system=system, max_tokens=max_tokens, temperature=temperature)
                self.last_route = "local"
                self.last_model = self.local.model
                self.last_error = ""
                return text
            except Exception as exc:
                errors.append(f"local:{type(exc).__name__}:{str(exc)[:120]}")

        cloud_config = config.get("cloud") or {}
        if cloud_config.get("enabled"):
            try:
                cloud = CloudFallbackClient(cloud_config)
                text = cloud.complete(prompt, system=system, max_tokens=max_tokens, temperature=temperature)
                self.last_route = f"cloud:{provider_label(cloud.provider)}"
                self.last_model = cloud.model or cloud.provider
                self.last_error = ""
                return text
            except Exception as exc:
                errors.append(f"cloud:{type(exc).__name__}:{str(exc)[:180]}")
        elif errors:
            errors.append("cloud:disabled")

        self.last_route = "unavailable"
        self.last_model = ""
        self.last_error = "; ".join(errors) or "no_provider_enabled"
        raise RuntimeError(self.last_error)

    def voice_reply(self, command: str) -> str:
        """
        Motor de resposta da UI. Hierarquia:
        1. Cerebro causal do backend, ja responsavel por sintetizar texto final
           e expor o traco causal em metadados estruturados.
        2. Fallback puro ao Qwen se o backend estiver offline.
        """
        brain_answer: str | None = None
        brain_data: dict = {}

        # Tenta o Cérebro Causal (Motor Unificado) com sessão persistente
        try:
            with httpx.Client(timeout=50.0) as client:
                res = client.post(
                    "http://127.0.0.1:8000/api/chat",
                    json={"message": command, "session_id": "ui_voice_session"},
                )
                if res.status_code == 200:
                    brain_data = res.json()
                    ans = brain_data.get("synthesized_text") or brain_data.get("answer") or ""
                    if ans:
                        brain_answer = ans
        except Exception:
            pass

        # O backend e o dono da orquestracao: a UI consome apenas o texto final.
        # Evidencias/trace causal ficam nos metadados da API, sem segunda inferencia local.
        if brain_answer is not None:
            trace = brain_data.get("trace_causal") or brain_data.get("causal_trace") or {}
            module = trace.get("source_module") if isinstance(trace, dict) else None
            self.last_route = f"causal_brain (via {module or brain_data.get('module') or 'backend'})"
            return brain_answer

        # Backend offline — Qwen puro como fallback
        system = (
            "Você é UltronPro, um assistente de voz. Responda em português brasileiro. "
            "Seja curto, prático e natural para voz."
        )
        prompt = f"Comando de voz do usuário: {command}\nResponda em no máximo duas frases."
        self.last_route = "local_llm_fallback"
        return self.complete(prompt, system=system, max_tokens=64, temperature=0.25)

    def runtime_description(self) -> str:
        if self.last_route:
            model = self.last_model or "modelo não informado pelo provedor"
            return f"Na última resposta usei {self.last_route}, com modelo ou alias {model}."
        config = load_config()
        local_enabled = bool((config.get("local") or {}).get("enabled", True))
        cloud = config.get("cloud") or {}
        if local_enabled and cloud.get("enabled"):
            return "Estou configurado para tentar Qwen local primeiro e usar nuvem grátis automática como fallback."
        if local_enabled:
            return "Estou configurado para usar o Qwen local."
        if cloud.get("enabled"):
            return "Estou configurado para usar nuvem grátis automática."
        return "Nenhuma rota LLM está habilitada agora."


def _extract_chat_text(payload: Any) -> str:
    choices = payload.get("choices") if isinstance(payload, dict) else []
    if not choices:
        return ""
    first = choices[0] or {}
    message = first.get("message") or {}
    content = message.get("content") or first.get("text") or ""
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
            else:
                parts.append(str(item or ""))
        content = "".join(parts)
    return str(content or "").strip()


def _raise_for_status_with_body(response: httpx.Response) -> None:
    try:
        response.raise_for_status()
        return
    except httpx.HTTPStatusError as exc:
        body = ""
        try:
            data = response.json() if response.text else {}
            if isinstance(data, dict):
                err = data.get("error")
                if isinstance(err, dict):
                    body = str(err.get("message") or err.get("code") or err)
                else:
                    body = str(err or data)
            else:
                body = str(data)
        except Exception:
            body = (response.text or "").strip()
        if body:
            raise RuntimeError(f"HTTP {response.status_code}: {body[:300]}") from exc
        raise


def _is_usable_reply(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return False
    low = value.lower()
    bad_markers = (
        "cadastre-se",
        "sign up",
        "api key",
        "unauthorized",
        "forbidden",
        "request limit",
        "rate limit",
    )
    return not any(marker in low for marker in bad_markers)


def _run_g4f_once(
    *,
    provider_name: str,
    model: str,
    messages: list[dict[str, str]],
    max_tokens: int,
    timeout_sec: float,
) -> str:
    def _call() -> str:
        from g4f import Provider
        from g4f.client import Client

        provider = getattr(Provider, provider_name)
        response = Client().chat.completions.create(
            model=model,
            provider=provider,
            messages=messages,
            stream=False,
            max_tokens=max_tokens,
        )
        return str(response.choices[0].message.content or "").strip()

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = executor.submit(_call)
    try:
        return future.result(timeout=max(3.0, float(timeout_sec)))
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
