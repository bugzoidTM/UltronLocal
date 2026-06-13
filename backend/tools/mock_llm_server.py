#!/usr/bin/env python3
"""
mock_llm_server.py — Deterministic, dependency-free LLM stub for controlled-env proofs.
=====================================================================================

Purpose
-------
The resilience proofs (`pressure_benchmark`) and the operational proof
(`scratch/operational_proof.py`) need *some* LLM endpoint up. Running a real model
on a free CI runner is slow and flaky, and a "return-the-gold-answer" mock would
fabricate a 100% retention grade — exactly the "telemetria de vaidade" the project
says it abandoned.

So this stub is intentionally **NEUTRAL**: it answers multiple-choice probes by a
deterministic (md5-based) pick over the offered options, with *no knowledge of the
gold answer* and *identical behavior regardless of the stress framing* injected by
the pressure axes. That means:

  * The proofs become **reproducible** end-to-end in any environment.
  * What gets validated is the **harness + routing/fallback plumbing**, NOT the
    production model's robustness. The absolute `maturity_index`/`MATURE` grade
    produced against this mock is a property of the mock and must NOT be read as a
    system-truth claim. Grade the real system by pointing the providers at a real
    inference endpoint (see ULTRON_PROOF_REAL_LLM in the CI runner).

Speaks three wire formats so it works whichever local provider the router picks:
  * Ollama        : POST /api/chat , POST /api/generate , GET /api/tags
  * OpenAI-compat : POST /v1/chat/completions , GET /v1/models
  * Health        : GET /health , GET /

Usage
-----
    python tools/mock_llm_server.py --port 11434
    # or
    MOCK_LLM_PORT=11434 python tools/mock_llm_server.py
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_OPTION_RE = re.compile(r'"([^"]+)"')


def _stable_index(text: str, n: int) -> int:
    """Deterministic index in [0, n) from text (md5 — stable across processes/OS)."""
    if n <= 0:
        return 0
    digest = hashlib.md5(text.encode("utf-8", "replace")).hexdigest()
    return int(digest, 16) % n


def _question_anchor(prompt: str) -> str:
    """Use the text after the last 'Question:' as the deterministic anchor when present."""
    idx = prompt.rfind("Question:")
    return prompt[idx + len("Question:"):].strip() if idx >= 0 else prompt.strip()


def compute_answer(prompt: str, *, json_mode: bool) -> str:
    """
    Deterministic, gold-blind answer policy.

    MCQ probes (pressure_benchmark) ask: 'answer using EXACTLY one of these options:
    "a" | "b" | ...  Reply ONLY with valid JSON: {"answer": "<option>"}'.
    We extract the offered options and pick one by a stable hash of the question.
    NOTE: identical policy under every pressure axis — the stub does not react to
    'memory unavailable' / adversarial decoy framings. That is deliberate: it keeps
    the controlled run honest about measuring plumbing, not model IQ.
    """
    is_mcq = "EXACTLY one of these options" in prompt or '{"answer"' in prompt
    if is_mcq:
        header = prompt.split("Question:", 1)[0]
        options = _OPTION_RE.findall(header)
        # de-dup while preserving order
        seen: list[str] = []
        for opt in options:
            if opt not in seen:
                seen.append(opt)
        if seen:
            choice = seen[_stable_index(_question_anchor(prompt), len(seen))]
            if json_mode or '{"answer"' in prompt:
                return json.dumps({"answer": choice}, ensure_ascii=False)
            return choice
    # Free-form (e.g., operational_proof 'llm'-routed tasks): deterministic, non-empty.
    anchor = _question_anchor(prompt)[:200].replace("\n", " ").strip()
    return (
        "[mock-llm] Resposta determinística de ambiente controlado. "
        f"Pedido reconhecido: {anchor}" if anchor else
        "[mock-llm] Resposta determinística de ambiente controlado."
    )


def _messages_to_prompt(messages: list[dict]) -> tuple[str, str]:
    """Flatten chat messages to (system, user_prompt)."""
    system = ""
    parts: list[str] = []
    for m in messages or []:
        role = str(m.get("role") or "")
        content = str(m.get("content") or "")
        if role == "system":
            system = content
        else:
            parts.append(content)
    return system, "\n".join(parts)


class _Handler(BaseHTTPRequestHandler):
    server_version = "MockLLM/1.0"

    def log_message(self, *_args):  # silence default stderr logging
        return

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8", "replace") or "{}")
        except Exception:
            return {}

    def do_GET(self):  # noqa: N802
        if self.path.startswith("/api/tags"):
            self._send_json({"models": [{"name": "mock-llm", "model": "mock-llm"}]})
        elif self.path.startswith("/v1/models"):
            self._send_json({"object": "list", "data": [{"id": "mock-llm", "object": "model"}]})
        else:  # /health, /, anything else
            self._send_json({"ok": True, "service": "mock-llm", "mode": "controlled_neutral"})

    def do_POST(self):  # noqa: N802
        data = self._read_body()
        json_mode = (
            str(data.get("format") or "").lower() == "json"
            or (isinstance(data.get("response_format"), dict)
                and str(data["response_format"].get("type") or "").lower() == "json_object")
        )

        if self.path.startswith("/api/chat"):
            system, prompt = _messages_to_prompt(data.get("messages") or [])
            answer = compute_answer((system + "\n" + prompt).strip(), json_mode=json_mode)
            self._send_json({
                "model": data.get("model") or "mock-llm",
                "message": {"role": "assistant", "content": answer},
                "done": True,
            })
        elif self.path.startswith("/api/generate"):
            prompt = str(data.get("prompt") or "")
            answer = compute_answer(prompt, json_mode=json_mode)
            self._send_json({"model": data.get("model") or "mock-llm", "response": answer, "done": True})
        elif self.path.startswith("/v1/chat/completions"):
            system, prompt = _messages_to_prompt(data.get("messages") or [])
            answer = compute_answer((system + "\n" + prompt).strip(), json_mode=json_mode)
            self._send_json({
                "id": "mockcmpl-1",
                "object": "chat.completion",
                "model": data.get("model") or "mock-llm",
                "choices": [{
                    "index": 0,
                    "message": {"role": "assistant", "content": answer},
                    "finish_reason": "stop",
                }],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            })
        else:
            self._send_json({"error": f"unknown path {self.path}"}, status=404)


def serve_in_thread(host: str = "127.0.0.1", port: int = 11434):
    """Start the stub on a daemon thread and return (server, base_url). For embedding in CI runners."""
    import threading
    httpd = ThreadingHTTPServer((host, port), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://{host}:{port}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Deterministic neutral LLM stub for controlled-env proofs.")
    parser.add_argument("--host", default=os.getenv("MOCK_LLM_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("MOCK_LLM_PORT", "11434")))
    args = parser.parse_args()
    httpd = ThreadingHTTPServer((args.host, args.port), _Handler)
    print(f"[mock-llm] listening on http://{args.host}:{args.port} (neutral/deterministic)", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
