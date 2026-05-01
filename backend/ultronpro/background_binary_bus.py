from __future__ import annotations

import json
import os
import queue
import struct
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ultronpro import binary_protocol


def _env_flag(name: str, default: str = "1") -> bool:
    return str(os.getenv(name, default)).strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    try:
        return int(float(os.getenv(name, str(default)) or default))
    except Exception:
        return default


DATA_DIR = Path(os.getenv("ULTRON_BACKGROUND_BINARY_DATA_DIR", str(Path(__file__).resolve().parent.parent / "data")))
BINLOG_PATH = DATA_DIR / "background_bus.binlog"
STATE_PATH = DATA_DIR / "background_bus_state.json"
GUARD_STATE_PATH = DATA_DIR / "background_guard.json"

ENABLED = _env_flag("ULTRON_BACKGROUND_BINARY_BUS_ENABLED", "1")
ASYNC_WORKSPACE_ENABLED = _env_flag("ULTRON_BACKGROUND_BINARY_WORKSPACE_ENABLED", "1")
ASYNC_RUNTIME_HEALTH_ENABLED = _env_flag("ULTRON_BACKGROUND_BINARY_RUNTIME_HEALTH_ENABLED", "1")
ASYNC_GUARD_STATE_ENABLED = _env_flag("ULTRON_BACKGROUND_BINARY_GUARD_STATE_ENABLED", "1")
MAX_QUEUE = max(64, _env_int("ULTRON_BACKGROUND_BINARY_QUEUE_SIZE", 2048))
MAX_SUMMARY_BYTES = max(128, _env_int("ULTRON_BACKGROUND_BINARY_SUMMARY_BYTES", 2048))
MAX_JOURNAL_BYTES = max(0, _env_int("ULTRON_BACKGROUND_BINARY_JOURNAL_MAX_BYTES", 5 * 1024 * 1024))
STATE_FLUSH_EVERY = max(1, _env_int("ULTRON_BACKGROUND_BINARY_STATE_FLUSH_EVERY", 32))
STATE_FLUSH_SEC = max(1, _env_int("ULTRON_BACKGROUND_BINARY_STATE_FLUSH_SEC", 2))

_KEY = binary_protocol.protocol_key(os.getenv("ULTRON_BACKGROUND_BINARY_KEY", ""))
_NONCE = int.from_bytes(os.urandom(8), "big")
_queue: queue.Queue["_BusItem"] = queue.Queue(maxsize=MAX_QUEUE)
_stop_event = threading.Event()
_lock = threading.Lock()
_worker_thread: threading.Thread | None = None
_sequence = 0
_workspace_sink: Callable[..., int] | None = None
_runtime_health_sink: Callable[[dict[str, Any]], None] | None = None

_state: dict[str, Any] = {
    "enabled": ENABLED,
    "started_at": 0.0,
    "processed": 0,
    "dropped": 0,
    "sink_errors": 0,
    "last_event": None,
    "last_error": None,
}


@dataclass
class _BusItem:
    kind: str
    loop_name: str
    event: str
    payload: Any = None
    severity: str = "info"
    sink_payload: Any = None
    enqueued_at: float = 0.0


def register_workspace_sink(fn: Callable[..., int] | None) -> None:
    global _workspace_sink
    _workspace_sink = fn


def register_runtime_health_sink(fn: Callable[[dict[str, Any]], None] | None) -> None:
    global _runtime_health_sink
    _runtime_health_sink = fn


def snapshot() -> dict[str, Any]:
    with _lock:
        out = dict(_state)
    out["queue_size"] = _queue.qsize()
    out["worker_alive"] = bool(_worker_thread and _worker_thread.is_alive())
    out["binlog_path"] = str(BINLOG_PATH)
    return out


def start() -> bool:
    global _worker_thread
    if not ENABLED:
        return False
    with _lock:
        if _worker_thread and _worker_thread.is_alive():
            return True
        _stop_event.clear()
        _worker_thread = threading.Thread(target=_worker_loop, name="ultron-background-binary-bus", daemon=True)
        _worker_thread.start()
        _state["started_at"] = time.time()
    return True


def stop(timeout_sec: float = 2.0) -> None:
    _stop_event.set()
    worker = _worker_thread
    if worker and worker.is_alive():
        worker.join(timeout=max(0.1, float(timeout_sec)))


def flush(timeout_sec: float = 5.0) -> bool:
    deadline = time.time() + max(0.1, float(timeout_sec))
    while time.time() < deadline:
        if getattr(_queue, "unfinished_tasks", 0) == 0:
            return True
        time.sleep(0.02)
    return getattr(_queue, "unfinished_tasks", 0) == 0


def publish_loop_event(
    loop_name: str,
    event: str,
    payload: Any = None,
    *,
    severity: str = "info",
) -> bool:
    return _enqueue(
        _BusItem(
            kind="event",
            loop_name=str(loop_name or "background"),
            event=str(event or "tick"),
            payload=payload,
            severity=severity,
            enqueued_at=time.time(),
        )
    )


def publish_workspace_task(
    *,
    loop_name: str,
    module: str,
    channel: str,
    payload: dict[str, Any] | None,
    salience: float = 0.5,
    ttl_sec: int = 900,
) -> bool:
    if not ASYNC_WORKSPACE_ENABLED:
        return False
    payload_dict = payload if isinstance(payload, dict) else {}
    summary = {
        "module": module,
        "channel": channel,
        "salience": round(float(salience), 4),
        "ttl_sec": int(ttl_sec),
        "payload_keys": list(payload_dict.keys())[:16],
    }
    return _enqueue(
        _BusItem(
            kind="workspace",
            loop_name=str(loop_name or "background"),
            event="workspace_publish",
            payload=summary,
            severity="info",
            sink_payload={
                "module": module,
                "channel": channel,
                "payload": payload_dict,
                "salience": salience,
                "ttl_sec": ttl_sec,
            },
            enqueued_at=time.time(),
        )
    )


def publish_runtime_health(
    *,
    loop_name: str,
    snapshot: dict[str, Any],
    reason: str | None = None,
) -> bool:
    if not ASYNC_RUNTIME_HEALTH_ENABLED:
        return False
    extra = snapshot.get("extra") if isinstance(snapshot, dict) else {}
    if reason is None and isinstance(extra, dict):
        reason = str(extra.get("reason") or "")
    summary = {
        "reason": reason or "runtime_health",
        "extra_keys": list(extra.keys())[:16] if isinstance(extra, dict) else [],
    }
    return _enqueue(
        _BusItem(
            kind="runtime_health",
            loop_name=str(loop_name or "background"),
            event="runtime_health_write",
            payload=summary,
            severity="info",
            sink_payload=snapshot,
            enqueued_at=time.time(),
        )
    )


def publish_guard_state(state: dict[str, Any]) -> bool:
    if not ASYNC_GUARD_STATE_ENABLED:
        return False
    summary = {
        "state": state.get("state"),
        "paused": bool(state.get("paused")),
        "lag_sec": state.get("lag_sec"),
        "blocked_loops": state.get("blocked_loops"),
        "last_pause_reason": state.get("last_pause_reason"),
    }
    return _enqueue(
        _BusItem(
            kind="guard_state",
            loop_name="runtime_guard",
            event="guard_state_write",
            payload=summary,
            severity="warning" if state.get("paused") else "info",
            sink_payload=state,
            enqueued_at=time.time(),
        )
    )


def _enqueue(item: _BusItem) -> bool:
    if not ENABLED:
        return False
    if item.enqueued_at <= 0:
        item.enqueued_at = time.time()
    if not start():
        return False
    try:
        _queue.put_nowait(item)
        return True
    except queue.Full:
        with _lock:
            _state["dropped"] = int(_state.get("dropped") or 0) + 1
            _state["last_error"] = "queue_full"
        return False


def _worker_loop() -> None:
    last_state_write = 0.0
    while not _stop_event.is_set() or not _queue.empty():
        try:
            item = _queue.get(timeout=0.2)
        except queue.Empty:
            continue
        try:
            _process_item(item)
            processed = _mark_processed(item)
            now = time.time()
            if processed % STATE_FLUSH_EVERY == 0 or (now - last_state_write) >= STATE_FLUSH_SEC:
                _write_bus_state()
                last_state_write = now
        except Exception as exc:
            _mark_error(exc)
        finally:
            try:
                _queue.task_done()
            except Exception:
                pass
    _write_bus_state()


def _process_item(item: _BusItem) -> None:
    _write_binary_journal(item)
    if item.kind == "workspace":
        _run_workspace_sink(item)
    elif item.kind == "runtime_health":
        _run_runtime_health_sink(item)
    elif item.kind == "guard_state":
        _write_json(GUARD_STATE_PATH, item.sink_payload if isinstance(item.sink_payload, dict) else {})


def _run_workspace_sink(item: _BusItem) -> None:
    sink = _workspace_sink
    if sink is None:
        return
    data = item.sink_payload if isinstance(item.sink_payload, dict) else {}
    try:
        sink(
            module=str(data.get("module") or "background"),
            channel=str(data.get("channel") or "general"),
            payload=data.get("payload") if isinstance(data.get("payload"), dict) else {},
            salience=float(data.get("salience") or 0.5),
            ttl_sec=int(data.get("ttl_sec") or 900),
        )
    except Exception as exc:
        _mark_sink_error(exc)


def _run_runtime_health_sink(item: _BusItem) -> None:
    sink = _runtime_health_sink
    if sink is None:
        return
    try:
        sink(item.sink_payload if isinstance(item.sink_payload, dict) else {})
    except Exception as exc:
        _mark_sink_error(exc)


def _write_binary_journal(item: _BusItem) -> None:
    global _sequence
    BINLOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if MAX_JOURNAL_BYTES and BINLOG_PATH.exists():
        try:
            if BINLOG_PATH.stat().st_size > MAX_JOURNAL_BYTES:
                BINLOG_PATH.write_bytes(b"")
        except Exception:
            pass
    with _lock:
        _sequence = (_sequence + 1) & 0xFFFFFFFF
        sequence = _sequence
    payload = binary_protocol.encode_loop_event(
        loop_name=item.loop_name,
        event=item.event,
        payload=_summarize_payload(item.payload),
        kind=item.kind,
        severity=item.severity,
        ts_ms=int(item.enqueued_at * 1000),
    )
    frame = binary_protocol.encode_frame(
        binary_protocol.OP_LOOP_EVENT,
        payload,
        nonce=_NONCE,
        key=_KEY,
        sequence=sequence,
    )
    with BINLOG_PATH.open("ab") as fh:
        fh.write(struct.pack("!I", len(frame)))
        fh.write(frame)


def _write_bus_state() -> None:
    _write_json(STATE_PATH, snapshot())


def _write_json(path: Path, data: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _mark_processed(item: _BusItem) -> int:
    with _lock:
        processed = int(_state.get("processed") or 0) + 1
        _state["processed"] = processed
        _state["last_event"] = {
            "kind": item.kind,
            "loop": item.loop_name,
            "event": item.event,
            "at": item.enqueued_at,
        }
        return processed


def _mark_error(exc: Exception) -> None:
    with _lock:
        _state["last_error"] = str(exc)[:240]


def _mark_sink_error(exc: Exception) -> None:
    with _lock:
        _state["sink_errors"] = int(_state.get("sink_errors") or 0) + 1
        _state["last_error"] = str(exc)[:240]


def _summarize_payload(payload: Any) -> str:
    try:
        if payload is None:
            text = ""
        elif isinstance(payload, bytes):
            raw = payload[:MAX_SUMMARY_BYTES]
            return raw.decode("utf-8", errors="replace")
        elif isinstance(payload, dict):
            text = json.dumps(_summarize_dict(payload), ensure_ascii=False, separators=(",", ":"))
        elif isinstance(payload, (list, tuple)):
            text = json.dumps([_short_value(v) for v in list(payload)[:16]], ensure_ascii=False, separators=(",", ":"))
        else:
            text = str(payload)
    except Exception:
        text = repr(payload)
    raw = text.encode("utf-8", errors="replace")
    if len(raw) <= MAX_SUMMARY_BYTES:
        return text
    return raw[:MAX_SUMMARY_BYTES].decode("utf-8", errors="replace") + "...truncated"


def _summarize_dict(payload: dict[Any, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for idx, (key, value) in enumerate(payload.items()):
        if idx >= 16:
            out["_more_keys"] = max(0, len(payload) - idx)
            break
        out[str(key)[:80]] = _short_value(value)
    return out


def _short_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value if len(value) <= 160 else value[:160] + "...truncated"
    if isinstance(value, bytes):
        return f"bytes[{len(value)}]"
    if isinstance(value, dict):
        return f"dict[{len(value)}]"
    if isinstance(value, (list, tuple, set)):
        return f"list[{len(value)}]"
    return str(value)[:160]
