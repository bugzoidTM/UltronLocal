from __future__ import annotations

import json
import os
import secrets
import time
import uuid
from typing import Any

import httpx
from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ultronpro import qwen_runtime


MODEL_ALIAS = os.getenv("ULTRON_OPENAI_COMPAT_MODEL", qwen_runtime.MODEL_ALIAS)
DEFAULT_TIMEOUT_SEC = float(os.getenv("ULTRON_OPENAI_COMPAT_TIMEOUT_SEC", "60") or 60)

router = APIRouter(tags=["OpenAI Compatible Qwen"])


class ChatMessage(BaseModel):
    role: str
    content: Any


class ChatCompletionRequest(BaseModel):
    model: str = MODEL_ALIAS
    messages: list[ChatMessage]
    max_tokens: int | None = None
    temperature: float | None = None
    stream: bool = False


class UpstreamInferenceError(RuntimeError):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = int(status_code)
        self.detail = str(detail)


def _configured_keys() -> list[str]:
    raw = str(os.getenv("ULTRON_OPENAI_COMPAT_API_KEYS", "") or "")
    return [part.strip() for part in raw.split(",") if part.strip()]


def _auth_ok(authorization: str | None) -> bool:
    keys = _configured_keys()
    if not keys:
        return str(os.getenv("ULTRON_OPENAI_COMPAT_ALLOW_NO_AUTH", "0")).strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
    incoming = str(authorization or "").strip()
    if incoming.lower().startswith("bearer "):
        incoming = incoming[7:].strip()
    return any(secrets.compare_digest(incoming, key) for key in keys)


def _error(status_code: int, message: str, error_type: str, code: str | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "message": message,
                "type": error_type,
                "param": None,
                "code": code,
            }
        },
    )


def _content_to_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") in (None, "text"):
                    parts.append(str(item.get("text") or ""))
            else:
                parts.append(str(item))
        return "\n".join(part for part in parts if part)
    return json.dumps(content, ensure_ascii=False)


def compile_messages(messages: list[ChatMessage]) -> tuple[str | None, str]:
    system_parts: list[str] = []
    turns: list[str] = []
    for msg in messages:
        role = str(msg.role or "user").strip().lower()
        text = _content_to_text(msg.content).strip()
        if not text:
            continue
        if role == "system":
            system_parts.append(text)
        elif role == "assistant":
            turns.append(f"Assistant: {text}")
        elif role == "tool":
            turns.append(f"Tool: {text}")
        else:
            turns.append(f"User: {text}")
    turns.append("Assistant:")
    system = "\n\n".join(system_parts).strip() or None
    return system, "\n".join(turns).strip()


def _qwen_url() -> str:
    return str(
        os.getenv("ULTRON_OPENAI_COMPAT_QWEN_URL")
        or os.getenv("ULTRON_LOCAL_INFER_URL")
        or qwen_runtime.endpoint_url()
    ).rstrip("/")


def _qwen_headers() -> dict[str, str]:
    token = str(
        os.getenv("ULTRON_OPENAI_COMPAT_QWEN_TOKEN")
        or os.getenv("ULTRON_LOCAL_INFER_TOKEN")
        or ""
    ).strip()
    return {"x-api-key": token} if token else {}


async def call_qwen_generate(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SEC) as client:
            response = await client.post(f"{_qwen_url()}/generate", json=payload, headers=_qwen_headers())
    except httpx.TimeoutException as exc:
        raise UpstreamInferenceError(504, "inference_timeout") from exc
    except httpx.HTTPError as exc:
        raise UpstreamInferenceError(502, str(exc)[:500]) from exc

    if response.status_code >= 400:
        detail = response.text[:500] or f"upstream_status_{response.status_code}"
        raise UpstreamInferenceError(response.status_code, detail)

    data = response.json()
    if not isinstance(data, dict):
        raise UpstreamInferenceError(502, "invalid_upstream_response")
    return data


@router.get("/v1/models")
async def list_models(authorization: str | None = Header(default=None)):
    if not _auth_ok(authorization):
        return _error(401, "Invalid or missing API key.", "authentication_error", "invalid_api_key")
    return {
        "object": "list",
        "data": [
            {
                "id": MODEL_ALIAS,
                "object": "model",
                "created": 0,
                "owned_by": "ultronpro",
            }
        ],
    }


@router.post("/v1/chat/completions")
async def chat_completions(req: ChatCompletionRequest, authorization: str | None = Header(default=None)):
    if not _auth_ok(authorization):
        return _error(401, "Invalid or missing API key.", "authentication_error", "invalid_api_key")
    if req.stream:
        return _error(400, "Streaming is not enabled for this endpoint.", "invalid_request_error", "stream_not_supported")
    if not req.messages:
        return _error(400, "At least one message is required.", "invalid_request_error", "messages_required")

    system, prompt = compile_messages(req.messages)
    payload = {
        "prompt": prompt,
        "system": system,
        "max_new_tokens": int(req.max_tokens or qwen_runtime.generation_defaults().get("max_tokens") or 512),
        "temperature": float(req.temperature if req.temperature is not None else qwen_runtime.generation_defaults().get("temperature") or 0.3),
        "mode": "balanced",
    }

    try:
        upstream = await call_qwen_generate(payload)
    except UpstreamInferenceError as exc:
        return _error(exc.status_code, exc.detail, "upstream_error", "upstream_inference_error")

    text = str(upstream.get("text") or "").strip()
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": MODEL_ALIAS,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        },
    }
