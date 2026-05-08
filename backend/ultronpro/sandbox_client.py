from __future__ import annotations

from typing import Any
import os
import re
import subprocess
import sys
import tempfile
import httpx


SANDBOX_URL = os.getenv('ULTRON_SANDBOX_URL', 'http://ultron-sandbox:9000')
SANDBOX_TIMEOUT_SEC = int(os.getenv('ULTRON_SANDBOX_TIMEOUT_SEC', '12') or 12)
LOCAL_PYTHON_FALLBACK = str(os.getenv('ULTRON_SANDBOX_LOCAL_PYTHON_FALLBACK', '1')).strip().lower() in {
    '1', 'true', 'yes', 'on'
}


_BLOCK_PATTERNS = [
    r'\brm\s+-rf\b',
    r'\bdd\s+if=',
    r'\bmkfs\b',
    r'\bshutdown\b',
    r'\breboot\b',
    r'\bpoweroff\b',
    r'/app/data',
    r'/var/run/docker.sock',
    r'\bdocker\b',
    r'\bcurl\b\s+http',
    r'\bwget\b\s+http',
    r'\brequests\.',
    r'\burllib\.',
    r'\bsocket\b',
    r'\bsubprocess\b.*\b(curl|wget|nc|ncat|telnet)\b',
]

_LOCAL_PYTHON_BLOCK_PATTERNS = _BLOCK_PATTERNS + [
    r'\bimport\s+os\b',
    r'\bfrom\s+os\b',
    r'\bopen\s*\(',
    r'\bpathlib\b',
    r'\bshutil\b',
    r'\bimport\s+sys\b',
    r'\bfrom\s+sys\b',
    r'\beval\s*\(',
    r'\bexec\s*\(',
]


def _guardrails_ok(text: str) -> tuple[bool, str | None]:
    src = str(text or '')
    if not src.strip():
        return False, 'empty_payload'
    if len(src) > 20000:
        return False, 'payload_too_large'
    for pat in _BLOCK_PATTERNS:
        if re.search(pat, src, flags=re.IGNORECASE | re.DOTALL):
            return False, f'blocked_pattern:{pat}'
    return True, None


def _local_python_guardrails_ok(code: str) -> tuple[bool, str | None]:
    ok, err = _guardrails_ok(code)
    if not ok:
        return ok, err
    src = str(code or '')
    for pat in _LOCAL_PYTHON_BLOCK_PATTERNS:
        if re.search(pat, src, flags=re.IGNORECASE | re.DOTALL):
            return False, f'local_blocked_pattern:{pat}'
    return True, None


def _local_python_fallback(code: str, timeout_sec: int = 10, *, remote_error: str = '') -> dict[str, Any]:
    ok, err = _local_python_guardrails_ok(code)
    if not ok:
        return {'ok': False, 'error': err, 'stdout': '', 'stderr': remote_error[:12000], 'returncode': -2}
    timeout = max(1, min(30, int(timeout_sec or 10)))
    try:
        with tempfile.TemporaryDirectory(prefix='ultron-sandbox-') as td:
            proc = subprocess.run(
                [sys.executable, '-I', '-c', str(code or '')],
                cwd=td,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        return {
            'ok': proc.returncode == 0,
            'stdout': str(proc.stdout or '')[:12000],
            'stderr': str(proc.stderr or '')[:12000],
            'returncode': int(proc.returncode),
            'sandbox_mode': 'local_python_fallback',
            'remote_error': remote_error[:500],
        }
    except subprocess.TimeoutExpired as exc:
        return {
            'ok': False,
            'error': 'local_sandbox_timeout',
            'stdout': str(exc.stdout or '')[:12000],
            'stderr': str(exc.stderr or '')[:12000],
            'returncode': -1,
            'sandbox_mode': 'local_python_fallback',
            'remote_error': remote_error[:500],
        }
    except Exception as exc:
        return {
            'ok': False,
            'error': f'local_sandbox_error:{type(exc).__name__}',
            'stdout': '',
            'stderr': str(exc)[:12000],
            'returncode': -1,
            'sandbox_mode': 'local_python_fallback',
            'remote_error': remote_error[:500],
        }


def _safe_post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    url = SANDBOX_URL.rstrip('/') + path
    try:
        with httpx.Client(timeout=max(3.0, float(SANDBOX_TIMEOUT_SEC))) as hc:
            rr = hc.post(url, json=payload)
            body = rr.json() if rr.text else {}
        if rr.status_code >= 400:
            return {
                'ok': False,
                'status': rr.status_code,
                'error': str((body or {}).get('error') or f'http_{rr.status_code}'),
                'stdout': str((body or {}).get('stdout') or '')[:12000],
                'stderr': str((body or {}).get('stderr') or '')[:12000],
                'returncode': int((body or {}).get('returncode') or -1),
            }
        if not isinstance(body, dict):
            body = {'ok': False, 'error': 'invalid_json'}
        body.setdefault('ok', bool(body.get('returncode', 1) == 0))
        body['stdout'] = str(body.get('stdout') or '')[:12000]
        body['stderr'] = str(body.get('stderr') or '')[:12000]
        body['returncode'] = int(body.get('returncode') or 0)
        return body
    except Exception as e:
        remote_error = f'sandbox_unreachable:{type(e).__name__}'
        if path == '/execute/python' and LOCAL_PYTHON_FALLBACK:
            return _local_python_fallback(
                str((payload or {}).get('code') or ''),
                timeout_sec=int((payload or {}).get('timeout_sec') or 10),
                remote_error=f'{remote_error}:{str(e)[:500]}',
            )
        return {
            'ok': False,
            'error': remote_error,
            'stdout': '',
            'stderr': str(e)[:12000],
            'returncode': -1,
        }


def execute_python(code: str, timeout_sec: int = 10) -> dict[str, Any]:
    ok, err = _guardrails_ok(code)
    if not ok:
        return {'ok': False, 'error': err, 'stdout': '', 'stderr': '', 'returncode': -2}
    return _safe_post('/execute/python', {'code': str(code or ''), 'timeout_sec': int(timeout_sec or 10)})


def execute_bash(command: str, timeout_sec: int = 10) -> dict[str, Any]:
    ok, err = _guardrails_ok(command)
    if not ok:
        return {'ok': False, 'error': err, 'stdout': '', 'stderr': '', 'returncode': -2}
    return _safe_post('/execute/bash', {'command': str(command or ''), 'timeout_sec': int(timeout_sec or 10)})
