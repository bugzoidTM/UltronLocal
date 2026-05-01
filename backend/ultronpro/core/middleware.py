"""
ultronpro.core.middleware
=========================
HTTP middleware registration for the UltronPro FastAPI app.
"""
from __future__ import annotations

import logging
import os
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ultronpro import code_self_healer, runtime_guard, store

logger = logging.getLogger("uvicorn")


async def ui_cache_bust_headers(request: Request, call_next):
    started = time.monotonic()
    path = request.url.path or "/"
    foreground = False
    try:
        foreground = runtime_guard.begin_foreground(path)
    except Exception:
        foreground = False
    try:
        response = await call_next(request)
    except RuntimeError as e:
        p = request.url.path or ""
        if "No response returned" in str(e) and p in ("/api/metacognition/ask", "/api/chat"):
            return JSONResponse({
                "ok": True,
                "answer": "O servidor não conseguiu gerar uma resposta a tempo. Tente novamente.",
                "strategy": "middleware_fallback",
                "latency_ms": 0,
                "error": "no_response_returned",
            }, status_code=200)
        raise
    finally:
        if foreground:
            try:
                runtime_guard.end_foreground(path, time.monotonic() - started)
            except Exception:
                pass
    runtime_guard.record_request(path, time.monotonic() - started)
    if request.method == "GET" and (path == "/" or path == "/index.html" or path.endswith(".html")):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


async def ui_lite_api_guard(request: Request, call_next):
    if os.getenv("ULTRON_UI_LITE_API", "1") == "1" and request.method == "GET":
        p = request.url.path or ""
        if p.startswith("/api/goals"):
            return JSONResponse({"goals": []})
        if p.startswith("/api/tom/status"):
            return JSONResponse({"items": [], "stats": {}})
        if p.startswith("/api/horizon/missions"):
            return JSONResponse({"missions": []})
        if p.startswith("/api/persona/status"):
            return JSONResponse({"status": "lite"})
        if p.startswith("/api/persona/examples"):
            return JSONResponse({"examples": []})
        if p.startswith("/api/conflicts"):
            return JSONResponse({"conflicts": []})
        if p.startswith("/api/mission/tasks"):
            return JSONResponse({"tasks": []})
        if p.startswith("/api/mission/activities"):
            return JSONResponse({"activities": []})
        if p.startswith("/api/llm/usage"):
            return JSONResponse({"window": [], "summary": {}})
        if p.startswith("/api/plasticity/finetune/status"):
            return JSONResponse({"ok": True, "running": False})
        if p.startswith("/api/turbo/report"):
            return JSONResponse({"report": {}})
    try:
        return await call_next(request)
    except RuntimeError as e:
        p = request.url.path or ""
        if "No response returned" in str(e) and p in ("/api/metacognition/ask", "/api/chat"):
            return JSONResponse({
                "ok": True,
                "answer": "O servidor não conseguiu gerar uma resposta a tempo. Tente novamente.",
                "strategy": "middleware_fallback",
                "latency_ms": 0,
                "error": "no_response_returned",
            }, status_code=200)
        raise


async def self_healer_middleware(request: Request, call_next):
    """Capture 500 exceptions and feed the Code Self-Healer."""
    try:
        response = await call_next(request)
        return response
    except Exception as exc:
        import traceback as _tb_mod
        tb_str = _tb_mod.format_exc()
        try:
            result = code_self_healer.heal(exc, tb_str)
            if result.get('applied'):
                logger.info(
                    f"🩹 Self-Healer: auto-fix applied for {result.get('module')}:"
                    f"{result.get('function')} ({result.get('strategy')})"
                )
                store.db.add_event(
                    'self_healer_fix',
                    f"🩹 Auto-fix: {result.get('module')} — {result.get('description', '')[:120]}",
                )
        except Exception as heal_err:
            logger.debug(f"Self-Healer middleware error: {heal_err}")
        raise


def register_middlewares(app: FastAPI) -> None:
    """Register HTTP middlewares in the same order as the old decorators."""
    app.middleware("http")(ui_cache_bust_headers)
    app.middleware("http")(ui_lite_api_guard)
    app.middleware("http")(self_healer_middleware)
