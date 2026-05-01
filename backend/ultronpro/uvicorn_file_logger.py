from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from threading import RLock
from typing import Any


DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DEFAULT_LOG_PATH = DATA_DIR / "logs" / "uvicorn_live.log"
DEFAULT_MAX_BYTES = 25 * 1024 * 1024
DEFAULT_KEEP_BYTES = 8 * 1024 * 1024

_HANDLER: "CompactingSingleFileHandler | None" = None
_CONFIG_LOCK = RLock()


def _env_int(name: str, default: int) -> int:
    try:
        value = int(str(os.getenv(name, "") or "").strip())
        return value if value > 0 else default
    except Exception:
        return default


def _log_path() -> Path:
    raw = str(os.getenv("ULTRON_UVICORN_FILE_LOG_PATH", "") or "").strip()
    return Path(raw) if raw else DEFAULT_LOG_PATH


class CompactingSingleFileHandler(logging.FileHandler):
    """A single editable log file that compacts itself in place.

    The handler intentionally avoids multi-file rotation. When the file gets too
    large, it keeps the newest tail and prepends a small compaction marker.
    """

    def __init__(self, filename: str | Path, *, max_bytes: int, keep_bytes: int):
        path = Path(filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.max_bytes = max(1024, int(max_bytes or DEFAULT_MAX_BYTES))
        requested_keep = max(256, int(keep_bytes or DEFAULT_KEEP_BYTES))
        self.keep_bytes = min(requested_keep, max(256, self.max_bytes // 2))
        self._compact_lock = RLock()
        super().__init__(path, mode="a", encoding="utf-8", delay=False)

    def emit(self, record: logging.LogRecord) -> None:
        marker = "_ultronpro_uvicorn_file_logged"
        if getattr(record, marker, False):
            return
        setattr(record, marker, True)
        try:
            self._compact_if_needed()
        except Exception:
            self.handleError(record)
        super().emit(record)

    def _compact_if_needed(self) -> None:
        path = Path(self.baseFilename)
        try:
            size = path.stat().st_size
        except FileNotFoundError:
            return
        if size < self.max_bytes:
            return

        with self._compact_lock:
            try:
                size = path.stat().st_size
            except FileNotFoundError:
                return
            if size < self.max_bytes:
                return

            if self.stream:
                self.stream.flush()
                self.stream.close()
                self.stream = None

            with path.open("rb") as fh:
                start = max(0, size - self.keep_bytes)
                fh.seek(start)
                tail = fh.read()
            if start > 0:
                newline = tail.find(b"\n")
                if newline >= 0:
                    tail = tail[newline + 1 :]

            header = (
                f"--- compacted_at={time.strftime('%Y-%m-%d %H:%M:%S')} "
                f"original_size_bytes={size} kept_tail_bytes={len(tail)} ---\n"
            ).encode("utf-8")
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_bytes(header + tail)
            tmp.replace(path)
            self.stream = self._open()


def configure_uvicorn_file_logging(
    *,
    path: str | Path | None = None,
    max_bytes: int | None = None,
    keep_bytes: int | None = None,
) -> dict[str, Any]:
    if str(os.getenv("ULTRON_UVICORN_FILE_LOG_ENABLED", "1") or "1").strip().lower() in {"0", "false", "no", "off"}:
        return {"enabled": False, "reason": "disabled_by_env"}

    global _HANDLER
    with _CONFIG_LOCK:
        final_path = Path(path) if path else _log_path()
        final_max = int(max_bytes or _env_int("ULTRON_UVICORN_FILE_LOG_MAX_BYTES", DEFAULT_MAX_BYTES))
        final_keep = int(keep_bytes or _env_int("ULTRON_UVICORN_FILE_LOG_KEEP_BYTES", DEFAULT_KEEP_BYTES))
        if _HANDLER is None or Path(_HANDLER.baseFilename) != final_path.resolve():
            _HANDLER = CompactingSingleFileHandler(final_path, max_bytes=final_max, keep_bytes=final_keep)
            _HANDLER.setLevel(logging.INFO)
            _HANDLER.setFormatter(
                logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
            )

        for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
            log = logging.getLogger(name)
            log.setLevel(logging.INFO)
            if _HANDLER not in log.handlers:
                log.addHandler(_HANDLER)

        return {
            "enabled": True,
            "path": str(final_path.resolve()),
            "max_bytes": _HANDLER.max_bytes,
            "keep_bytes": _HANDLER.keep_bytes,
            "logger_names": ["uvicorn", "uvicorn.error", "uvicorn.access"],
        }


def status() -> dict[str, Any]:
    path = _log_path()
    size = 0
    try:
        size = path.stat().st_size
    except Exception:
        pass
    return {
        "enabled": _HANDLER is not None,
        "path": str(path.resolve()),
        "size_bytes": size,
        "max_bytes": _HANDLER.max_bytes if _HANDLER else _env_int("ULTRON_UVICORN_FILE_LOG_MAX_BYTES", DEFAULT_MAX_BYTES),
        "keep_bytes": _HANDLER.keep_bytes if _HANDLER else _env_int("ULTRON_UVICORN_FILE_LOG_KEEP_BYTES", DEFAULT_KEEP_BYTES),
    }
