from __future__ import annotations

import subprocess
import os
import json
import time
import uuid
from pathlib import Path
from fastapi import FastAPI, HTTPException, Header
from fastapi.responses import FileResponse
from pydantic import BaseModel
import tarfile

app = FastAPI(title='UltronPro Trainer API', version='0.1.0')

JOBS_PATH = Path('/app/data/trainer_jobs.json')
LOG_DIR = Path('/app/data/trainer_logs')
API_TOKEN = os.getenv('TRAINER_API_TOKEN', '').strip()


def _auth_ok(x_api_key: str | None) -> bool:
    if not API_TOKEN:
        return True
    return bool(x_api_key and str(x_api_key).strip() == API_TOKEN)


def _load_jobs() -> dict:
    if JOBS_PATH.exists():
        try:
            d = json.loads(JOBS_PATH.read_text(encoding='utf-8'))
            if isinstance(d, dict):
                d.setdefault('jobs', [])
                return d
        except Exception:
            pass
    return {'jobs': []}


def _save_jobs(d: dict):
    JOBS_PATH.parent.mkdir(parents=True, exist_ok=True)
    JOBS_PATH.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding='utf-8')


def _set_job(job_id: str, patch: dict) -> dict | None:
    d = _load_jobs()
    for i, j in enumerate(d.get('jobs') or []):
        if str(j.get('id')) == str(job_id):
            j = {**j, **(patch or {}), 'updated_at': int(time.time())}
            d['jobs'][i] = j
            _save_jobs(d)
            return j
    return None


def _get_job(job_id: str) -> dict | None:
    for j in _load_jobs().get('jobs') or []:
        if str(j.get('id')) == str(job_id):
            return j
    return None


def _pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except Exception:
        return False


class TrainRequest(BaseModel):
    base_model: str
    dataset: str
    dataset_content: str = ''
    val_dataset: str = ''
    val_dataset_content: str = ''
    adapter_out: str
    run_preset: str = 'production'
    epochs: int = 1
    max_steps: int = 0
    batch_size: int = 1
    grad_accum: int = 8
    max_length: int = 512
    early_stopping_patience: int = 2


@app.get('/health')
async def health():
    return {'ok': True}


@app.get('/jobs')
async def jobs(limit: int = 40, x_api_key: str | None = Header(default=None)):
    if not _auth_ok(x_api_key):
        raise HTTPException(401, 'unauthorized')
    d = _load_jobs()
    arr = (d.get('jobs') or [])[-max(1, int(limit or 40)):]
    return {'ok': True, 'items': arr}


@app.get('/jobs/{job_id}')
async def job_status(job_id: str, x_api_key: str | None = Header(default=None)):
    if not _auth_ok(x_api_key):
        raise HTTPException(401, 'unauthorized')
    j = _get_job(job_id)
    if not j:
        raise HTTPException(404, 'job not found')

    st = str(j.get('status') or '')
    if st == 'running':
        pid = int(j.get('pid') or 0)
        if _pid_alive(pid):
            return {'ok': True, 'job': j}
        # finalize if process ended
        out = Path(str(j.get('adapter_out') or ''))
        ok = (out / 'adapter_config.json').exists() or (out / 'train_meta.json').exists()
        j = _set_job(job_id, {'status': 'completed' if ok else 'failed', 'exit_ok': bool(ok)}) or j
    return {'ok': True, 'job': j}


@app.get('/jobs/{job_id}/metrics')
async def job_metrics(job_id: str, x_api_key: str | None = Header(default=None)):
    if not _auth_ok(x_api_key):
        raise HTTPException(401, 'unauthorized')
    j = _get_job(job_id)
    if not j:
        raise HTTPException(404, 'job not found')

    out = Path(str(j.get('adapter_out') or ''))
    mp = out / 'metrics.jsonl'
    if not mp.exists():
        raise HTTPException(404, 'metrics not found')
    return FileResponse(path=str(mp), media_type='application/x-ndjson', filename=f'{job_id}-metrics.jsonl')


@app.get('/jobs/{job_id}/artifact')
async def job_artifact(job_id: str, x_api_key: str | None = Header(default=None)):
    if not _auth_ok(x_api_key):
        raise HTTPException(401, 'unauthorized')
    j = _get_job(job_id)
    if not j:
        raise HTTPException(404, 'job not found')

    st = str(j.get('status') or '')
    if st not in ('completed', 'registered'):
        raise HTTPException(409, f'job not completed: {st}')

    out = Path(str(j.get('adapter_out') or ''))
    if not out.exists() or not out.is_dir():
        raise HTTPException(404, 'adapter_out not found')

    pkg = Path('/tmp') / f"{job_id}.tar.gz"
    with tarfile.open(pkg, 'w:gz') as tf:
        tf.add(out, arcname=out.name)

    return FileResponse(path=str(pkg), media_type='application/gzip', filename=f'{job_id}.tar.gz')


@app.post('/train')
async def train(req: TrainRequest, x_api_key: str | None = Header(default=None)):
    if not _auth_ok(x_api_key):
        raise HTTPException(401, 'unauthorized')
    ds = Path(req.dataset)
    if (not ds.exists()) and str(req.dataset_content or '').strip():
        ds = Path('/tmp') / f"remote_ds_{uuid.uuid4().hex[:8]}.jsonl"
        ds.write_text(str(req.dataset_content or ''), encoding='utf-8')

    if not ds.exists():
        raise HTTPException(400, f'dataset missing: {req.dataset}')

    val_path = None
    if str(req.val_dataset or '').strip():
        vp = Path(str(req.val_dataset).strip())
        if vp.exists():
            val_path = vp
        elif str(req.val_dataset_content or '').strip():
            val_path = Path('/tmp') / f"remote_val_{uuid.uuid4().hex[:8]}.jsonl"
            val_path.write_text(str(req.val_dataset_content or ''), encoding='utf-8')
    elif str(req.val_dataset_content or '').strip():
        val_path = Path('/tmp') / f"remote_val_{uuid.uuid4().hex[:8]}.jsonl"
        val_path.write_text(str(req.val_dataset_content or ''), encoding='utf-8')

    out = Path(req.adapter_out)
    out.mkdir(parents=True, exist_ok=True)

    cmd = [
        'python', '-m', 'ultronpro.train_lora',
        '--base-model', req.base_model,
        '--dataset', str(ds),
    ]
    if val_path is not None and Path(str(val_path)).exists():
        cmd += ['--val-dataset', str(val_path)]
    cmd += [
        '--adapter-out', req.adapter_out,
        '--run-preset', str(req.run_preset or 'production'),
        '--epochs', str(max(1, int(req.epochs))),
        '--max-steps', str(max(0, int(req.max_steps))),
        '--batch-size', str(max(1, int(req.batch_size))),
        '--grad-accum', str(max(1, int(req.grad_accum))),
        '--max-length', str(max(128, int(req.max_length))),
        '--early-stopping-patience', str(max(1, int(req.early_stopping_patience))),
    ]

    job_id = 'tj_' + uuid.uuid4().hex[:10]
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f'{job_id}.log'
    lf = open(log_path, 'ab')
    p = subprocess.Popen(cmd, stdout=lf, stderr=lf)

    d = _load_jobs()
    item = {
        'id': job_id,
        'created_at': int(time.time()),
        'updated_at': int(time.time()),
        'status': 'running',
        'pid': int(p.pid),
        'base_model': req.base_model,
        'dataset': req.dataset,
        'val_dataset': req.val_dataset,
        'adapter_out': req.adapter_out,
        'run_preset': str(req.run_preset or 'production'),
        'max_steps': int(req.max_steps or 0),
        'log_path': str(log_path),
    }
    d['jobs'].append(item)
    _save_jobs(d)

    return {'ok': True, 'job_id': job_id, 'pid': int(p.pid), 'command': cmd, 'status_url': f'/jobs/{job_id}'}
