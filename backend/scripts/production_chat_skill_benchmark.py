from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from typing import Any

import httpx


SEED_PROMPTS = [
    "calcule soma inteira 12 mais 30",
    "calcule soma inteira 7 mais 19",
    "calcule produto inteiro 6 vezes 8",
    "calcule produto inteiro 9 vezes 9",
    "resolva expressao inteira 40 menos 11",
    "resolva expressao inteira 18 mais 24",
    "calcule resultado numerico 13 mais 17",
    "calcule resultado numerico 21 mais 34",
    "calcule diferenca inteira 100 menos 45",
    "calcule diferenca inteira 77 menos 29",
    "calcule multiplicacao inteira 5 vezes 12",
    "calcule multiplicacao inteira 11 vezes 6",
    "calcule soma operacional 31 mais 12",
    "calcule soma operacional 42 mais 13",
    "calcule soma operacional 53 mais 14",
    "calcule soma operacional 64 mais 15",
    "calcule soma operacional 75 mais 16",
    "calcule soma operacional 86 mais 17",
    "calcule soma operacional 97 mais 18",
    "calcule soma operacional 108 mais 19",
    "calcule produto operacional 7 vezes 8",
    "calcule produto operacional 8 vezes 9",
    "calcule produto operacional 9 vezes 10",
    "calcule produto operacional 10 vezes 11",
    "calcule diferenca operacional 120 menos 45",
    "calcule diferenca operacional 131 menos 46",
    "calcule diferenca operacional 142 menos 47",
    "calcule diferenca operacional 153 menos 48",
    "calcule resultado simples 22 mais 33",
    "calcule resultado simples 44 mais 55",
]


def _post_json(client: httpx.Client, path: str, payload: dict[str, Any] | None = None, timeout: float = 30.0) -> dict[str, Any]:
    r = client.post(path, json=payload or {}, timeout=timeout)
    r.raise_for_status()
    try:
        return r.json()
    except Exception:
        return {"ok": False, "raw": r.text[:1000]}


def _get_json(client: httpx.Client, path: str, timeout: float = 30.0) -> dict[str, Any]:
    r = client.get(path, timeout=timeout)
    r.raise_for_status()
    return r.json()


def _stream_chat(client: httpx.Client, message: str, session_id: str, timeout: float = 45.0) -> dict[str, Any]:
    started = time.time()
    done: dict[str, Any] = {}
    progress = 0
    try:
        with client.stream(
            "POST",
            "/api/chat/stream",
            json={"message": message, "session_id": session_id},
            timeout=timeout,
        ) as r:
            r.raise_for_status()
            buffer = ""
            for chunk in r.iter_text():
                buffer += chunk
                while "\n\n" in buffer:
                    line, buffer = buffer.split("\n\n", 1)
                    if not line.startswith("data: "):
                        continue
                    try:
                        payload = json.loads(line[6:])
                    except Exception:
                        continue
                    if payload.get("type") == "progress":
                        progress += 1
                    if payload.get("type") == "done":
                        done = payload
                        break
                if done:
                    break
    except Exception as exc:
        return {
            "ok": False,
            "latency_ms": int((time.time() - started) * 1000),
            "progress_events": progress,
            "payload": {},
            "message": message,
            "error": str(exc)[:240],
        }
    return {
        "ok": bool(done),
        "latency_ms": int((time.time() - started) * 1000),
        "progress_events": progress,
        "payload": done,
        "message": message,
    }


def _production_use_prompts(status: dict[str, Any], limit: int = 12) -> list[str]:
    out: list[str] = []
    for cand in status.get("recent_candidates") or []:
        if cand.get("status") != "promoted":
            continue
        q = str(((cand.get("source_episode") or {}).get("query")) or "").strip()
        if not q:
            continue
        out.append("teste producao skill gerada: " + q)
        if len(out) >= limit:
            break
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    ap.add_argument("--rounds", type=int, default=30)
    ap.add_argument("--production-uses", type=int, default=12)
    ap.add_argument("--timeout", type=float, default=45.0)
    args = ap.parse_args()

    session_id = "prod_skill_benchmark_" + str(int(time.time()))
    seed_results: list[dict[str, Any]] = []
    use_results: list[dict[str, Any]] = []
    provider_probe: dict[str, Any] = {}

    with httpx.Client(base_url=args.base_url) as client:
        _get_json(client, "/api/status", timeout=20)

        for prompt in SEED_PROMPTS[: max(1, min(args.rounds, len(SEED_PROMPTS)))]:
            seed_results.append(_stream_chat(client, prompt, session_id, timeout=args.timeout))

        generated = _post_json(client, "/api/skills/evolution/generate?limit=800&target=30", timeout=60)
        promoted = _post_json(client, "/api/skills/evolution/replay-promote?max_promotions=20", timeout=60)
        _post_json(client, "/api/skills/reload", timeout=30)
        status = _get_json(client, "/api/skills/evolution/status?limit=80", timeout=30)

        for prompt in _production_use_prompts(status, limit=args.production_uses):
            use_results.append(_stream_chat(client, prompt, session_id, timeout=args.timeout))

        transfer = _post_json(client, "/api/skills/evolution/validate-transfer?max_validations=8", timeout=60)
        final_status = _get_json(client, "/api/skills/evolution/status?limit=80", timeout=30)

        try:
            provider_probe = _get_json(client, "/api/llm/health?provider=provider_inexistente", timeout=12)
        except Exception as exc:
            provider_probe = {"ok": False, "handled": True, "error": str(exc)[:180]}

        simple_latencies = [r["latency_ms"] for r in use_results if r.get("ok")]
        seed_latencies = [r["latency_ms"] for r in seed_results if r.get("ok")]
        run = {
            "seed_rounds": len(seed_results),
            "seed_ok": len([r for r in seed_results if r.get("ok")]),
            "seed_mean_latency_ms": round(statistics.mean(seed_latencies), 2) if seed_latencies else 0,
            "production_use_rounds": len(use_results),
            "production_use_ok": len([r for r in use_results if r.get("ok")]),
            "production_use_mean_latency_ms": round(statistics.mean(simple_latencies), 2) if simple_latencies else 0,
            "generated": generated,
            "promoted": promoted,
            "transfer": transfer,
            "provider_unavailable_probe": provider_probe,
            "final_metrics": final_status,
        }
        recorded = _post_json(client, "/api/skills/evolution/benchmark-record", run, timeout=30)

    print(json.dumps({"ok": True, "run": run, "recorded": recorded}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
