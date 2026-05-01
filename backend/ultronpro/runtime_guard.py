"""Runtime backpressure guard for background loops.

The guard keeps autonomous loops enabled, but pauses their next ticks when the
FastAPI event loop shows sustained lag or when normal HTTP requests become slow.
It cannot interrupt a synchronous call that is already running, but it prevents
the next wave of background work from piling onto an unhealthy server.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from contextvars import ContextVar
from pathlib import Path
from typing import Any

logger = logging.getLogger("uvicorn")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
STATE_PATH = DATA_DIR / "background_guard.json"


def _env_flag(name: str, default: str = "1") -> bool:
    return str(os.getenv(name, default)).strip().lower() in ("1", "true", "yes", "on")


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)) or default)
    except Exception:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(float(os.getenv(name, str(default)) or default))
    except Exception:
        return default


ENABLED = _env_flag("ULTRON_BACKGROUND_GUARD_ENABLED", "1")
INTERVAL_SEC = max(0.5, _env_float("ULTRON_BACKGROUND_GUARD_INTERVAL_SEC", 2.0))
LAG_WARN_SEC = max(0.1, _env_float("ULTRON_BACKGROUND_GUARD_LAG_WARN_SEC", 0.75))
LAG_PAUSE_SEC = max(LAG_WARN_SEC, _env_float("ULTRON_BACKGROUND_GUARD_LAG_PAUSE_SEC", 2.0))
PAUSE_SEC = max(5, _env_int("ULTRON_BACKGROUND_GUARD_PAUSE_SEC", 90))
POLL_SEC = max(1, _env_int("ULTRON_BACKGROUND_GUARD_POLL_SEC", 10))
MAX_CONSECUTIVE_LAG = max(1, _env_int("ULTRON_BACKGROUND_GUARD_MAX_CONSECUTIVE_LAG", 2))
REQUEST_SLOW_SEC = max(0.2, _env_float("ULTRON_BACKGROUND_GUARD_REQUEST_SLOW_SEC", 4.0))
FOREGROUND_PAUSE_SEC = max(0.0, _env_float("ULTRON_BACKGROUND_GUARD_FOREGROUND_PAUSE_SEC", 20.0))
FOREGROUND_POLL_SEC = max(0.25, _env_float("ULTRON_BACKGROUND_GUARD_FOREGROUND_POLL_SEC", 2.0))

STATE: dict[str, Any] = {
    "enabled": ENABLED,
    "state": "healthy",
    "lag_sec": 0.0,
    "max_lag_sec": 0.0,
    "consecutive_lag": 0,
    "paused_until": 0.0,
    "last_pause_reason": None,
    "last_pause_at": 0.0,
    "last_slow_request": None,
    "blocked_loops": 0,
    "last_blocked_loop": None,
    "last_log_at": 0.0,
    "foreground_active": 0,
    "last_foreground_path": None,
    "last_foreground_at": 0.0,
    "last_foreground_elapsed_sec": 0.0,
}

_CURRENT_LOOP: ContextVar[str | None] = ContextVar("ultron_background_loop_name", default=None)


def current_loop_name() -> str | None:
    return _CURRENT_LOOP.get()


def is_foreground_path(path: str) -> bool:
    p = str(path or "")
    return p in ("/api/chat", "/api/chat/stream", "/api/metacognition/ask") or p.startswith("/api/voice")


def begin_foreground(path: str) -> bool:
    if not ENABLED or not is_foreground_path(path):
        return False
    STATE["foreground_active"] = int(STATE.get("foreground_active") or 0) + 1
    STATE["last_foreground_path"] = str(path or "")[:160]
    STATE["last_foreground_at"] = time.time()
    _emit_loop_event(
        "runtime_guard",
        "foreground_begin",
        {"path": STATE.get("last_foreground_path"), "active": STATE.get("foreground_active")},
        severity="info",
    )
    return True


def end_foreground(path: str, elapsed_sec: float = 0.0) -> None:
    if not ENABLED or not is_foreground_path(path):
        return
    STATE["foreground_active"] = max(0, int(STATE.get("foreground_active") or 0) - 1)
    STATE["last_foreground_path"] = str(path or "")[:160]
    STATE["last_foreground_at"] = time.time()
    STATE["last_foreground_elapsed_sec"] = round(float(elapsed_sec or 0.0), 3)
    _emit_loop_event(
        "runtime_guard",
        "foreground_end",
        {
            "path": STATE.get("last_foreground_path"),
            "active": STATE.get("foreground_active"),
            "elapsed_sec": STATE.get("last_foreground_elapsed_sec"),
        },
        severity="info",
    )


def foreground_active() -> bool:
    if not ENABLED:
        return False
    if int(STATE.get("foreground_active") or 0) > 0:
        return True
    last_at = float(STATE.get("last_foreground_at") or 0.0)
    return FOREGROUND_PAUSE_SEC > 0 and (time.time() - last_at) <= FOREGROUND_PAUSE_SEC


def _emit_loop_event(loop_name: str, event: str, payload: dict[str, Any] | None = None, *, severity: str = "info") -> None:
    try:
        from ultronpro import background_binary_bus

        background_binary_bus.publish_loop_event(loop_name, event, payload or {}, severity=severity)
    except Exception:
        pass


def snapshot() -> dict[str, Any]:
    out = dict(STATE)
    out["paused"] = is_paused()
    out["paused_for_sec"] = max(0.0, float(out.get("paused_until") or 0.0) - time.time())
    return out


def _write_state() -> None:
    data = snapshot()
    try:
        from ultronpro import background_binary_bus

        if background_binary_bus.publish_guard_state(data):
            return
    except Exception:
        pass
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def is_paused() -> bool:
    return ENABLED and time.time() < float(STATE.get("paused_until") or 0.0)


def pause(reason: str, *, seconds: int | None = None, details: dict[str, Any] | None = None) -> None:
    if not ENABLED:
        return
    now = time.time()
    pause_for = int(seconds or PAUSE_SEC)
    STATE["paused_until"] = max(float(STATE.get("paused_until") or 0.0), now + pause_for)
    STATE["state"] = "paused"
    STATE["last_pause_reason"] = reason
    STATE["last_pause_at"] = now
    if details:
        STATE["last_pause_details"] = details
    _emit_loop_event(
        "runtime_guard",
        "pause",
        {"reason": reason, "seconds": pause_for, "details": details or {}},
        severity="warning",
    )
    _write_state()


def record_request(path: str, elapsed_sec: float) -> None:
    if not ENABLED:
        return
    path = str(path or "")
    if path.startswith("/api/stream") or is_foreground_path(path):
        return
    if elapsed_sec >= REQUEST_SLOW_SEC:
        details = {"path": path[:160], "elapsed_sec": round(float(elapsed_sec), 3)}
        STATE["last_slow_request"] = details
        pause("slow_request", details=details)


async def checkpoint(loop_name: str) -> bool:
    """Return True when a loop should skip this tick and sleep briefly."""
    try:
        _CURRENT_LOOP.set(str(loop_name or "background_loop"))
    except Exception:
        pass
    if foreground_active():
        now = time.time()
        STATE["blocked_loops"] = int(STATE.get("blocked_loops") or 0) + 1
        STATE["last_blocked_loop"] = loop_name
        STATE["state"] = "foreground_throttle"
        last_log_at = float(STATE.get("last_log_at") or 0.0)
        if now - last_log_at >= 30:
            logger.warning(
                "Background guard: foreground throttle loop %s (path=%s active=%s)",
                loop_name,
                STATE.get("last_foreground_path"),
                STATE.get("foreground_active"),
            )
            STATE["last_log_at"] = now
        _emit_loop_event(
            str(loop_name or "background_loop"),
            "checkpoint_foreground_throttle",
            {"path": STATE.get("last_foreground_path"), "active": STATE.get("foreground_active")},
            severity="info",
        )
        _write_state()
        await asyncio.sleep(FOREGROUND_POLL_SEC)
        return True
    if not is_paused():
        return False

    now = time.time()
    remaining = max(0.0, float(STATE.get("paused_until") or 0.0) - now)
    STATE["blocked_loops"] = int(STATE.get("blocked_loops") or 0) + 1
    STATE["last_blocked_loop"] = loop_name
    last_log_at = float(STATE.get("last_log_at") or 0.0)
    if now - last_log_at >= 30:
        logger.warning(
            "Background guard: pausing loop %s for %.1fs (reason=%s)",
            loop_name,
            remaining,
            STATE.get("last_pause_reason"),
        )
        STATE["last_log_at"] = now
    _emit_loop_event(
        str(loop_name or "background_loop"),
        "checkpoint_paused",
        {"remaining_sec": round(remaining, 3), "reason": STATE.get("last_pause_reason")},
        severity="warning",
    )
    _write_state()
    await asyncio.sleep(min(POLL_SEC, max(1.0, remaining)))
    return True


async def monitor_loop() -> None:
    if not ENABLED:
        return

    logger.info(
        "Background guard started (lag_pause=%.2fs, pause=%ss, slow_request=%.2fs)",
        LAG_PAUSE_SEC,
        PAUSE_SEC,
        REQUEST_SLOW_SEC,
    )
    expected = time.monotonic() + INTERVAL_SEC

    while True:
        try:
            await asyncio.sleep(INTERVAL_SEC)
            now_mono = time.monotonic()
            lag = max(0.0, now_mono - expected)
            expected = now_mono + INTERVAL_SEC

            STATE["lag_sec"] = round(lag, 4)
            STATE["max_lag_sec"] = round(max(float(STATE.get("max_lag_sec") or 0.0), lag), 4)

            if lag >= LAG_WARN_SEC:
                STATE["consecutive_lag"] = int(STATE.get("consecutive_lag") or 0) + 1
                _emit_loop_event(
                    "runtime_guard",
                    "event_loop_lag",
                    {"lag_sec": round(lag, 4), "consecutive_lag": int(STATE.get("consecutive_lag") or 0)},
                    severity="warning",
                )
            else:
                STATE["consecutive_lag"] = 0
                if not is_paused():
                    STATE["state"] = "healthy"

            if lag >= LAG_PAUSE_SEC or int(STATE.get("consecutive_lag") or 0) >= MAX_CONSECUTIVE_LAG:
                pause(
                    "event_loop_lag",
                    details={
                        "lag_sec": round(lag, 3),
                        "consecutive_lag": int(STATE.get("consecutive_lag") or 0),
                    },
                )

            if not is_paused() and STATE.get("state") == "paused":
                STATE["state"] = "healthy"

            _write_state()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.debug("Background guard error: %s", exc)
            await asyncio.sleep(max(5.0, INTERVAL_SEC))
