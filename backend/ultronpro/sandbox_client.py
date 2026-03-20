from __future__ import annotations

from typing import Any
import os
import re
import httpx


SANDBOX_URL = os.getenv('ULTRON_SANDBOX_URL', 'http://ultron-sandbox:9000')
SANDBOX_TIMEOUT_SEC = int(os.getenv('ULTRON_SANDBOX_TIMEOUT_SEC', '12') or 12)


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
        return {
            'ok': False,
            'error': f'sandbox_unreachable:{type(e).__name__}',
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
