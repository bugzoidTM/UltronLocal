import json
import sys
import tempfile
import time
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

sys.path.insert(0, r"F:\sistemas\UltronPro\backend")


def _fake_sandbox_execute(code: str, timeout_sec: int = 10):
    namespace = {}
    captured = StringIO()
    with redirect_stdout(captured):
        exec(code, namespace, namespace)
    return {
        "ok": True,
        "returncode": 0,
        "stdout": captured.getvalue(),
        "stderr": "",
    }


def test_self_healer_sandbox_tests_and_applies_fix():
    from ultronpro import code_self_healer, mental_simulation, sandbox_client

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        module_path = root / "buggy.py"
        module_path.write_text(
            "def read_value(data):\n"
            "    return data.get('x')\n",
            encoding="utf-8",
        )

        old_values = (
            code_self_healer.ULTRONPRO_DIR,
            code_self_healer.HISTORY_PATH,
            code_self_healer.BACKUPS_DIR,
            code_self_healer._healer,
            mental_simulation.imagine,
            sandbox_client.execute_python,
        )
        code_self_healer.ULTRONPRO_DIR = root
        code_self_healer.HISTORY_PATH = root / "heal_history.json"
        code_self_healer.BACKUPS_DIR = root / "backups"
        code_self_healer.BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
        code_self_healer._healer = None
        mental_simulation.imagine = lambda *args, **kwargs: {"recommended_posture": "proceed", "risk_score": 0.1}
        sandbox_client.execute_python = _fake_sandbox_execute

        try:
            healer = code_self_healer.CodeSelfHealer()
            error = code_self_healer.TrackedError(
                id="err_none_get",
                timestamp=int(time.time()),
                module="buggy.py",
                function="read_value",
                lineno=2,
                exception_type="AttributeError",
                message="'NoneType' object has no attribute 'get'",
                traceback_lines=[],
                source_context=["def read_value(data):", "    return data.get('x')"],
                frequency=2,
            )
            healer.tracked_errors[error.id] = error

            result = healer.autorun_pending(limit=1)

            assert result["applied"] == 1
            fixed = module_path.read_text(encoding="utf-8")
            assert "(data or {}).get('x')" in fixed

            attempt = list(healer.heal_history)[-1]
            assert attempt.sandbox_validated is True
            assert attempt.tests_passed is True
            assert attempt.applied is True
            assert attempt.rolled_back is False

            saved = json.loads(code_self_healer.HISTORY_PATH.read_text(encoding="utf-8"))
            assert saved["history"][-1]["sandbox_validated"] is True
            assert saved["history"][-1]["tests_passed"] is True
        finally:
            (
                code_self_healer.ULTRONPRO_DIR,
                code_self_healer.HISTORY_PATH,
                code_self_healer.BACKUPS_DIR,
                code_self_healer._healer,
                mental_simulation.imagine,
                sandbox_client.execute_python,
            ) = old_values
