from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel
import subprocess
import tempfile
import os
import time

app = FastAPI(title='Ultron Sandbox', version='0.1.0')


class PythonExecReq(BaseModel):
    code: str
    timeout_sec: int = 10


class BashExecReq(BaseModel):
    command: str
    timeout_sec: int = 10


def _run(cmd: list[str], *, cwd: str, timeout_sec: int) -> dict:
    started = time.time()
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=max(1, min(10, int(timeout_sec or 10))),
            env={
                'PATH': '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
                'PYTHONUNBUFFERED': '1',
                'PYTHONNOUSERSITE': '1',
            },
        )
        return {
            'ok': proc.returncode == 0,
            'returncode': int(proc.returncode),
            'stdout': str(proc.stdout or '')[:12000],
            'stderr': str(proc.stderr or '')[:12000],
            'elapsed_sec': round(time.time() - started, 3),
        }
    except subprocess.TimeoutExpired as e:
        return {
            'ok': False,
            'returncode': -9,
            'stdout': (e.stdout or '')[:12000] if isinstance(e.stdout, str) else '',
            'stderr': (e.stderr or '')[:12000] if isinstance(e.stderr, str) else '',
            'elapsed_sec': round(time.time() - started, 3),
            'error': 'timeout',
        }
    except Exception as e:
        return {
            'ok': False,
            'returncode': -1,
            'stdout': '',
            'stderr': str(e)[:12000],
            'elapsed_sec': round(time.time() - started, 3),
            'error': f'run_error:{type(e).__name__}',
        }


@app.get('/health')
def health():
    return {'ok': True, 'service': 'ultron-sandbox'}


@app.post('/execute/python')
def execute_python(req: PythonExecReq):
    td = tempfile.mkdtemp(prefix='ultron_sb_')
    fp = os.path.join(td, 'main.py')
    with open(fp, 'w', encoding='utf-8') as f:
        f.write(req.code or '')
    return _run(['python3', '-I', fp], cwd=td, timeout_sec=req.timeout_sec)


@app.post('/execute/bash')
def execute_bash(req: BashExecReq):
    td = tempfile.mkdtemp(prefix='ultron_sb_')
    return _run(['/bin/bash', '-lc', req.command or ''], cwd=td, timeout_sec=req.timeout_sec)
