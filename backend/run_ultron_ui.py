from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen


BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _backend_ready() -> bool:
    try:
        with urlopen("http://127.0.0.1:8000/api/status", timeout=1.5) as res:
            return 200 <= int(getattr(res, "status", 0)) < 500
    except Exception:
        return False


def _ensure_backend_started() -> subprocess.Popen | None:
    if os.getenv("ULTRON_UI_START_BACKEND", "1").strip().lower() in {"0", "false", "no"}:
        return None
    if _backend_ready():
        return None

    logs = BACKEND_DIR / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    out = (logs / "ultron_ui_backend.out.log").open("a", encoding="utf-8")
    err = (logs / "ultron_ui_backend.err.log").open("a", encoding="utf-8")
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "ultronpro.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8000",
            "--log-level",
            "warning",
        ],
        cwd=str(BACKEND_DIR),
        stdout=out,
        stderr=err,
        creationflags=flags,
    )
    deadline = time.time() + float(os.getenv("ULTRON_UI_BACKEND_WAIT_SEC", "45") or 45)
    while time.time() < deadline:
        if _backend_ready():
            return proc
        if proc.poll() is not None:
            return proc
        time.sleep(0.75)
    return proc


def main() -> int:
    _ensure_backend_started()
    from ultronpro.ultron_ui.app import main as app_main

    return app_main()


if __name__ == "__main__":
    raise SystemExit(main())

