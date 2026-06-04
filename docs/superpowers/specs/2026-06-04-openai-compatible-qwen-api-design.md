# OpenAI-Compatible Qwen API Design

## Goal

Expose the Qwen model running behind UltronPRO VPS through a public HTTPS API that other applications can configure with a base URL and API key.

## Public Contract

- Base URL: `https://ultronpro.nutef.com/v1`
- Chat endpoint: `POST /v1/chat/completions`
- Models endpoint: `GET /v1/models`
- Authentication: `Authorization: Bearer <key>`
- Primary model name: `qwen2.5-1.5b-instruct-q4_k_m`

The chat response follows the common OpenAI-compatible shape:

```json
{
  "id": "chatcmpl-...",
  "object": "chat.completion",
  "created": 1780590000,
  "model": "qwen2.5-1.5b-instruct-q4_k_m",
  "choices": [
    {
      "index": 0,
      "message": {"role": "assistant", "content": "..."},
      "finish_reason": "stop"
    }
  ],
  "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
}
```

## Architecture

Add a focused FastAPI router at `backend/ultronpro/api/openai_compat.py`. The router validates Bearer tokens from `ULTRON_OPENAI_COMPAT_API_KEYS`, translates OpenAI chat messages into the prompt/system format expected by the internal Qwen runtime, forwards to the internal `/generate` endpoint, then translates the result back to OpenAI-compatible JSON.

The router is included from `backend/ultronpro/main.py`, keeping the large main module mostly untouched.

## Key Handling

`ULTRON_OPENAI_COMPAT_API_KEYS` contains one or more comma-separated keys. The implementation uses constant-time comparison and accepts no requests when the variable is empty, unless `ULTRON_OPENAI_COMPAT_ALLOW_NO_AUTH=1` is explicitly set for local development.

## Non-Goals

- Streaming compatibility is not included in this first cut.
- Embeddings, images, tools/function-calling, and model fine-tuning APIs are not included.
- The direct internal inference port is not exposed as the recommended public integration surface.

## Verification

Tests cover authentication, models listing, successful chat proxying, and upstream error translation.
