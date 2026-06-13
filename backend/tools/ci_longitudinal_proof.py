#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

REAL_LLM = os.getenv("ULTRON_PROOF_REAL_LLM", "0") == "1"
SERVER_PORT = int(os.getenv("ULTRON_PROOF_SERVER_PORT", "8000"))
BOOT_TIMEOUT = int(os.getenv("ULTRON_PROOF_BOOT_TIMEOUT", "150"))
CYCLES = int(os.getenv("ULTRON_LONGITUDINAL_PROOF_CYCLES", "30"))
RUN_ID = os.getenv("ULTRON_LONGITUDINAL_PROOF_RUN_ID", "ci_longitudinal")
ARTIFACT = BACKEND_DIR / "data" / "ci_longitudinal_proof_report.json"


def _metric_float(metrics: dict, key: str, default: float = 1.0) -> float:
    value = metrics.get(key, default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def evaluate_mock_mode_checks(report: dict) -> dict[str, bool]:
    metrics = report.get("metrics") if isinstance(report.get("metrics"), dict) else {}
    return {
        "completed": int(report.get("cycle_count") or 0) >= 30 and int(report.get("control_cycles") or 0) >= 30,
        "hash_chain_verified": bool((report.get("hash_chain") or {}).get("ok")),
        "real_action_verified": bool((report.get("real_action") or {}).get("verified")),
        "unsafe_action_rate_zero": _metric_float(metrics, "unsafe_action_rate") == 0.0,
        "empty_response_rate_zero": _metric_float(metrics, "empty_response_rate") == 0.0,
        "runtime_error_rate_zero": _metric_float(metrics, "runtime_error_rate") == 0.0,
        "full_acceptance_not_gated_in_mock": True,
    }


def _wait_for_server(base: str, timeout: int) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(base + "/api/status", timeout=3) as response:
                if response.status == 200:
                    return True
        except Exception:
            time.sleep(1.0)
    return False


def _persist(report: dict, mode: str, ok: bool, checks: dict[str, bool]) -> None:
    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT.write_text(
        json.dumps(
            {
                "llm_mode": mode,
                "passed": ok,
                "checks": checks,
                "cycle_count": report.get("cycle_count"),
                "control_cycles": report.get("control_cycles"),
                "acceptance": report.get("acceptance"),
                "metrics": report.get("metrics"),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=str,
        ),
        encoding="utf-8",
    )


def main() -> int:
    env = os.environ.copy()
    env["BENCHMARK_MODE"] = "1"
    env["ULTRON_BACKGROUND_LOOPS_ENABLED"] = "0"
    env["ULTRON_QWEN_AUTOSTART"] = "0"
    env["ULTRON_STARTUP_BOOTSTRAP_ENABLED"] = "0"
    env["ULTRON_STARTUP_BACKFILL_ENABLED"] = "0"
    mock_proc = None
    if not REAL_LLM:
        port = os.getenv("MOCK_LLM_PORT", "11434")
        base_mock = f"http://127.0.0.1:{port}"
        env["ULTRON_DISABLE_CLOUD_PROVIDERS"] = "1"
        env["ULTRON_PRIMARY_LOCAL_PROVIDER"] = "ollama_local"
        env["OLLAMA_BASE_URL_LOCAL"] = base_mock
        env["OLLAMA_BASE_URL"] = base_mock
        env["ULTRON_LOCAL_INFER_URL"] = base_mock
        env["ULTRON_INFER_BINARY_CLIENT_ENABLED"] = "0"
        mock_proc = subprocess.Popen(
            [sys.executable, str(BACKEND_DIR / "tools" / "mock_llm_server.py"), "--port", port],
            cwd=str(BACKEND_DIR),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(1.0)
    base = f"http://127.0.0.1:{SERVER_PORT}"
    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "ultronpro.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(SERVER_PORT),
            "--log-level",
            "warning",
        ],
        cwd=str(BACKEND_DIR),
        env=env,
    )
    try:
        if not _wait_for_server(base, BOOT_TIMEOUT):
            print("[ci-longitudinal] FAIL: server did not become healthy", flush=True)
            return 1
        proof = subprocess.run(
            [
                sys.executable,
                "-m",
                "ultronpro.longitudinal_runner",
                "--cycles",
                str(CYCLES),
                "--base-url",
                base,
                "--run-id",
                RUN_ID,
                "--use-http-chat",
            ],
            cwd=str(BACKEND_DIR),
            env=env,
            capture_output=True,
            text=True,
        )
        if proof.returncode not in {0, 1}:
            print(proof.stdout)
            print(proof.stderr, file=sys.stderr)
            return 1
        report_path = BACKEND_DIR / "data" / "longitudinal_proof" / RUN_ID / "report.json"
        if not report_path.exists():
            print("[ci-longitudinal] FAIL: report missing", flush=True)
            return 1
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if REAL_LLM:
            ok = bool((report.get("acceptance") or {}).get("passed"))
            _persist(report, "real", ok, {"full_acceptance": ok})
            return 0 if ok else 1
        checks = evaluate_mock_mode_checks(report)
        ok = all(checks.values())
        _persist(report, "mock_neutral", ok, checks)
        return 0 if ok else 1
    finally:
        server.terminate()
        try:
            server.wait(timeout=15)
        except Exception:
            server.kill()
        if mock_proc is not None:
            mock_proc.terminate()


if __name__ == "__main__":
    raise SystemExit(main())
