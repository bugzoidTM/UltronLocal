from __future__ import annotations

from pathlib import Path
from typing import Any
import json
import time
import uuid
import subprocess
import os
import re
import random
import httpx
import tarfile
import tempfile
import shutil

JOBS_PATH = Path('/app/data/finetune_jobs.json')
REG_PATH = Path('/app/data/adapter_registry.json')
DATASET_PATH = Path('/app/data/finetune_dataset.jsonl')
DATASET_TRAIN_PATH = Path('/app/data/finetune_dataset_train.jsonl')
DATASET_VAL_PATH = Path('/app/data/finetune_dataset_val.jsonl')
AUTO_PATH = Path('/app/data/finetune_auto.json')


def _load(path: Path, default):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        pass
    return default


def _save(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def _load_jobs() -> dict[str, Any]:
    d = _load(JOBS_PATH, {'jobs': []})
    if not isinstance(d, dict):
        d = {'jobs': []}
    d.setdefault('jobs', [])
    return d


def _save_jobs(d: dict[str, Any]):
    _save(JOBS_PATH, d)


def _load_reg() -> dict[str, Any]:
    d = _load(REG_PATH, {'adapters': []})
    if not isinstance(d, dict):
        d = {'adapters': []}
    d.setdefault('adapters', [])
    return d


def _save_reg(d: dict[str, Any]):
    _save(REG_PATH, d)


def _extract_pair_from_note(note: str) -> tuple[str, str]:
    n = str(note or '').strip()
    # expected pattern used by GUI feedback: "... user=<text> reply=<text>"
    m = re.search(r"user=(.*?)\s+reply=(.*)$", n, flags=re.IGNORECASE | re.DOTALL)
    if not m:
        return '', ''
    user = re.sub(r"\s+", ' ', (m.group(1) or '').strip())
    reply = re.sub(r"\s+", ' ', (m.group(2) or '').strip())
    return user[:420], reply[:420]


def build_dataset_from_feedback(feedback: list[dict[str, Any]], max_items: int = 400) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()

    for f in (feedback or [])[-max(40, int(max_items or 400)):]:
        note = str(f.get('note') or '').strip()
        if not note:
            continue

        task = str(f.get('task_type') or 'general')[:48]
        hall = bool(f.get('hallucination'))
        suc = bool(f.get('success'))
        user_text, reply_text = _extract_pair_from_note(note)

        # Primary supervised sample (real pair)
        if user_text and reply_text and suc and (not hall):
            ins = (
                f"Task: {task}. User said: {user_text}. "
                f"Respond in pt-BR, concise, natural, and grounded."
            )
            out = reply_text
            key = f"{task}|ok|{user_text}|{out}"
            if key not in seen:
                seen.add(key)
                rows.append({
                    'instruction': ins[:520],
                    'output': out[:320],
                    'task_type': task,
                    'label': 'ok_real',
                })

        # Hard-negative -> corrected target
        if user_text and (hall or (not suc)):
            ins = (
                f"Task: {task}. User said: {user_text}. "
                f"Avoid hallucinations and avoid claiming access to private data/tools. "
                f"If unsure, say uncertainty clearly and ask one short clarification."
            )
            out = "Não tenho certeza com os dados atuais. Posso confirmar se você quer que eu verifique isso agora?"
            key = f"{task}|hard|{user_text}|{out}"
            if key not in seen:
                seen.add(key)
                rows.append({
                    'instruction': ins[:520],
                    'output': out,
                    'task_type': task,
                    'label': 'hard_fix',
                })

        # policy/style sample fallback when no parsable pair exists
        if not user_text:
            ins = f"Task: {task}. Failure pattern: {note}. Produce safe and grounded response with explicit uncertainty when needed."
            out = "Resposta curta, correta, sem invenção e com limites claros."
            key = f"{task}|policy|{ins}|{out}"
            if key not in seen:
                seen.add(key)
                rows.append({
                    'instruction': ins[:520],
                    'output': out,
                    'task_type': task,
                    'label': 'policy',
                })

    # limit + deterministic shuffle for split
    random.Random(42).shuffle(rows)
    rows = rows[:max(20, int(max_items or 400))]

    val_n = max(1, int(len(rows) * 0.1)) if len(rows) >= 10 else 1
    val_rows = rows[:val_n]
    train_rows = rows[val_n:] if len(rows) > val_n else rows

    DATASET_PATH.parent.mkdir(parents=True, exist_ok=True)
    for pth, arr in ((DATASET_PATH, rows), (DATASET_TRAIN_PATH, train_rows), (DATASET_VAL_PATH, val_rows)):
        with pth.open('w', encoding='utf-8') as fp:
            for r in arr:
                fp.write(json.dumps(r, ensure_ascii=False) + '\n')

    return {
        'ok': True,
        'path': str(DATASET_PATH),
        'train_path': str(DATASET_TRAIN_PATH),
        'val_path': str(DATASET_VAL_PATH),
        'rows': len(rows),
        'train_rows': len(train_rows),
        'val_rows': len(val_rows),
        'labels': {
            'ok_real': len([r for r in rows if r.get('label') == 'ok_real']),
            'hard_fix': len([r for r in rows if r.get('label') == 'hard_fix']),
            'policy': len([r for r in rows if r.get('label') == 'policy']),
        }
    }


def create_job(task_type: str, base_model: str, method: str = 'qlora', max_samples: int = 400) -> dict[str, Any]:
    d = _load_jobs()
    jid = 'ft_' + uuid.uuid4().hex[:10]
    item = {
        'id': jid,
        'created_at': int(time.time()),
        'updated_at': int(time.time()),
        'status': 'created',
        'task_type': str(task_type or 'general')[:48],
        'base_model': str(base_model or 'llama3.2:1b')[:120],
        'method': str(method or 'qlora')[:24],
        'max_samples': int(max_samples or 400),
        'dataset_path': str(DATASET_TRAIN_PATH),
        'dataset_val_path': str(DATASET_VAL_PATH),
        'adapter_out': f"/app/data/adapters/{jid}",
        'pid': None,
        'last_error': None,
    }
    d['jobs'].append(item)
    _save_jobs(d)
    return item


def list_jobs(limit: int = 50) -> list[dict[str, Any]]:
    d = _load_jobs()
    return (d.get('jobs') or [])[-max(1, int(limit or 50)):]


def get_job(job_id: str) -> dict[str, Any] | None:
    for j in _load_jobs().get('jobs') or []:
        if str(j.get('id')) == str(job_id):
            return j
    return None


def _set_job(job_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
    d = _load_jobs()
    for i, j in enumerate(d.get('jobs') or []):
        if str(j.get('id')) == str(job_id):
            j = {**j, **(patch or {}), 'updated_at': int(time.time())}
            d['jobs'][i] = j
            _save_jobs(d)
            return j
    return None


def _toolchain_ready() -> tuple[bool, str]:
    try:
        import torch  # type: ignore
        import transformers  # type: ignore
        import peft  # type: ignore
        import datasets  # type: ignore
        return True, 'ok'
    except Exception as e:
        return False, f'missing_toolchain: {e}'


def _configured_remote_urls() -> list[str]:
    urls_env = str(os.getenv('ULTRON_FINETUNE_URLS', '') or '').strip()
    if urls_env:
        urls = [u.strip() for u in urls_env.split(',') if u.strip()]
    else:
        urls = []

    single = str(os.getenv('ULTRON_FINETUNE_URL', '') or '').strip()
    if single and single not in urls:
        urls.append(single)
    return urls


def _pick_remote_url(job_id: str | None = None) -> str:
    urls = _configured_remote_urls()

    if not urls:
        return ''

    max_per = max(1, int(os.getenv('ULTRON_FINETUNE_MAX_CONCURRENCY_PER_NODE', '1')))
    jobs = (_load_jobs().get('jobs') or [])

    # current load per remote_url considering active remote jobs
    active = [j for j in jobs if str(j.get('status') or '') in ('running_remote',)]
    load = {u: 0 for u in urls}
    for j in active:
        ru = str(j.get('remote_url') or '')
        if ru in load:
            load[ru] += 1

    # candidates with available slots
    candidates = [u for u in urls if load.get(u, 0) < max_per]
    if not candidates:
        return ''
    if len(candidates) == 1:
        return candidates[0]

    # pick least loaded first, then stable hash tie-break
    min_load = min(load.get(u, 0) for u in candidates)
    least = [u for u in candidates if load.get(u, 0) == min_load]
    if len(least) == 1:
        return least[0]

    key = str(job_id or uuid.uuid4().hex)
    idx = sum(ord(ch) for ch in key) % len(least)
    return least[idx]


def start_job(job_id: str, dry_run: bool = False) -> dict[str, Any]:
    j = get_job(job_id)
    if not j:
        return {'ok': False, 'error': 'job_not_found'}

    cmd_tpl = os.getenv('ULTRON_FINETUNE_CMD', '').strip()
    remote_urls_cfg = _configured_remote_urls()
    remote_url_pre = _pick_remote_url(job_id)
    if (not cmd_tpl) and (not remote_urls_cfg):
        ready, why = _toolchain_ready()
        if not ready:
            jj = _set_job(job_id, {'status': 'blocked_toolchain', 'last_error': why})
            return {'ok': False, 'job': jj, 'error': why, 'hint': 'Set ULTRON_FINETUNE_URLS/ULTRON_FINETUNE_URL/ULTRON_FINETUNE_CMD for external trainer, or install torch+transformers+peft+datasets locally.'}

    dataset = Path(str(j.get('dataset_path') or DATASET_TRAIN_PATH))
    val_dataset = Path(str(j.get('dataset_val_path') or DATASET_VAL_PATH))
    if not dataset.exists():
        jj = _set_job(job_id, {'status': 'blocked_dataset', 'last_error': 'dataset_missing'})
        return {'ok': False, 'job': jj, 'error': 'dataset_missing'}

    adapter_out = str(j.get('adapter_out'))
    os.makedirs(adapter_out, exist_ok=True)

    # external trainer hook (replace with your own command)
    cmd_tpl = os.getenv('ULTRON_FINETUNE_CMD', '').strip()

    base_model = str(j.get('base_model') or '').strip()
    # Ollama tags are not valid HF model ids for transformers trainer
    if ':' in base_model and '/' not in base_model:
        base_model = os.getenv('ULTRON_FINETUNE_BASE_MODEL', 'TinyLlama/TinyLlama-1.1B-Chat-v1.0')

    if not cmd_tpl:
        cmd = (
            f"python -m ultronpro.train_lora "
            f"--base-model '{base_model}' "
            f"--dataset '{str(dataset)}' "
            f"--val-dataset '{str(val_dataset) if val_dataset.exists() else ''}' "
            f"--adapter-out '{adapter_out}' "
            f"--epochs 1 --batch-size 1 --grad-accum 8 --max-length 512"
        )
    else:
        cmd = cmd_tpl.format(
            base_model=base_model,
            dataset=str(dataset),
            adapter_out=adapter_out,
            task_type=j.get('task_type'),
            method=j.get('method'),
            max_samples=j.get('max_samples'),
        )

    remote_url = _pick_remote_url(job_id)
    remote_token = os.getenv('ULTRON_FINETUNE_TOKEN', '').strip()

    if dry_run:
        jj = _set_job(job_id, {'status': 'dry_run_ready', 'command': cmd, 'remote_url': remote_url or None})
        return {'ok': True, 'job': jj, 'command': cmd, 'remote_url': remote_url or None}

    if (not remote_url) and remote_urls_cfg:
        jj = _set_job(job_id, {'status': 'queued_remote_wait', 'last_error': 'remote_capacity_full'})
        return {'ok': False, 'job': jj, 'error': 'remote_capacity_full'}

    if remote_url:
        try:
            ds_text = ''
            val_text = ''
            try:
                ds_text = dataset.read_text(encoding='utf-8', errors='ignore') if dataset.exists() else ''
            except Exception:
                ds_text = ''
            try:
                val_text = val_dataset.read_text(encoding='utf-8', errors='ignore') if val_dataset.exists() else ''
            except Exception:
                val_text = ''

            payload = {
                'base_model': base_model,
                'dataset': str(dataset),
                'dataset_content': ds_text,
                'val_dataset': str(val_dataset) if val_dataset.exists() else '',
                'val_dataset_content': val_text,
                'adapter_out': adapter_out,
                'epochs': 1,
                'batch_size': 2,
                'grad_accum': 2,
                'max_length': 768,
            }
            headers = {}
            if remote_token:
                headers['x-api-key'] = remote_token
            try:
                import requests as _rq
                r = _rq.post(remote_url, json=payload, headers=headers, timeout=30)
                r.raise_for_status()
                data = r.json()
            except Exception:
                with httpx.Client(timeout=30.0) as hc:
                    r = hc.post(remote_url, json=payload, headers=headers)
                    r.raise_for_status()
                    data = r.json()
            jj = _set_job(job_id, {
                'status': 'running_remote',
                'remote': data,
                'remote_job_id': str(data.get('job_id') or ''),
                'command': cmd,
                'remote_url': remote_url,
            })
            return {'ok': True, 'job': jj, 'remote': data}
        except Exception as e:
            err = str(e)
            try:
                import httpx as _hx
                if isinstance(e, _hx.HTTPStatusError) and e.response is not None:
                    err = f"{e} | body={e.response.text[:500]}"
            except Exception:
                pass
            jj = _set_job(job_id, {'status': 'remote_error', 'last_error': err[:500], 'remote_url': remote_url})
            return {'ok': False, 'job': jj, 'error': err}

    p = subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    jj = _set_job(job_id, {'status': 'running', 'pid': int(p.pid), 'command': cmd})
    return {'ok': True, 'job': jj}


def register_adapter(job_id: str, quality_score: float = 0.0, notes: str | None = None) -> dict[str, Any]:
    j = get_job(job_id)
    if not j:
        return {'ok': False, 'error': 'job_not_found'}

    reg = _load_reg()
    ad = {
        'id': 'adp_' + uuid.uuid4().hex[:8],
        'job_id': str(job_id),
        'task_type': str(j.get('task_type') or 'general'),
        'base_model': str(j.get('base_model') or ''),
        'adapter_path': str(j.get('adapter_out') or ''),
        'quality_score': float(quality_score or 0.0),
        'notes': str(notes or '')[:240],
        'created_at': int(time.time()),
        'active': bool(float(quality_score or 0.0) >= 0.6),
    }
    reg['adapters'].append(ad)
    _save_reg(reg)
    _set_job(job_id, {'status': 'registered'})
    return {'ok': True, 'adapter': ad}


def adapters(limit: int = 80) -> list[dict[str, Any]]:
    return (_load_reg().get('adapters') or [])[-max(1, int(limit or 80)):]


def recommend_adapter(task_type: str) -> dict[str, Any]:
    tt = str(task_type or 'general').lower().strip()
    cands = [a for a in adapters(200) if str(a.get('task_type') or '').lower() == tt and bool(a.get('active'))]
    if not cands:
        return {'ok': True, 'task_type': tt, 'adapter': None}
    best = sorted(cands, key=lambda x: float(x.get('quality_score') or 0.0), reverse=True)[0]
    return {'ok': True, 'task_type': tt, 'adapter': best}


def _auto_default() -> dict[str, Any]:
    return {
        'enabled': False,
        'min_feedback': 20,
        'min_failure_rate': 0.2,
        'cooldown_sec': 6 * 3600,
        'task_type': 'grounding',
        'base_model': 'TinyLlama/TinyLlama-1.1B-Chat-v1.0',
        'last_triggered_at': 0,
        'last_job_id': None,
    }


def auto_status() -> dict[str, Any]:
    d = _load(AUTO_PATH, None)
    if not isinstance(d, dict):
        d = _auto_default()
    base = _auto_default()
    for k, v in base.items():
        d.setdefault(k, v)
    return d


def auto_config_patch(patch: dict[str, Any]) -> dict[str, Any]:
    d = auto_status()
    for k in ['enabled', 'min_feedback', 'min_failure_rate', 'cooldown_sec', 'task_type', 'base_model']:
        if k in (patch or {}):
            d[k] = patch[k]
    _save(AUTO_PATH, d)
    return d


def auto_maybe_trigger(plasticity_status: dict[str, Any]) -> dict[str, Any]:
    cfg = auto_status()
    if not bool(cfg.get('enabled')):
        return {'ok': True, 'triggered': False, 'reason': 'disabled', 'config': cfg}

    total = int(plasticity_status.get('feedback_total') or 0)
    fr = float(plasticity_status.get('failure_rate') or 0.0)
    now = int(time.time())
    last = int(cfg.get('last_triggered_at') or 0)
    cooldown = int(cfg.get('cooldown_sec') or 21600)

    # proteção para clock drift / timestamps futuros
    if last > now:
        last = 0
        cfg['last_triggered_at'] = 0

    if cooldown > 0 and (now - last) < cooldown:
        return {
            'ok': True,
            'triggered': False,
            'reason': 'cooldown',
            'retry_after_sec': max(1, cooldown - (now - last)),
            'config': cfg,
        }
    if total < int(cfg.get('min_feedback') or 20):
        return {'ok': True, 'triggered': False, 'reason': 'not_enough_feedback', 'config': cfg}
    if fr < float(cfg.get('min_failure_rate') or 0.2):
        return {'ok': True, 'triggered': False, 'reason': 'failure_rate_low', 'config': cfg}

    # avoid piling multiple concurrent jobs
    running = [x for x in list_jobs(limit=120) if str(x.get('status') or '') in ('running', 'running_remote')]
    if running:
        return {'ok': True, 'triggered': False, 'reason': 'job_already_running', 'running_job_id': str(running[-1].get('id') or ''), 'config': cfg}

    # create + start job
    j = create_job(
        str(cfg.get('task_type') or 'grounding'),
        str(cfg.get('base_model') or 'TinyLlama/TinyLlama-1.1B-Chat-v1.0'),
        method='qlora',
        max_samples=600,
    )
    st = start_job(str(j.get('id')), dry_run=False)

    # só entra em cooldown se realmente iniciou
    started_ok = bool((st.get('ok') is True) and ((st.get('job') or {}).get('status') in ('running', 'running_remote', 'dry_run_ready')))
    if started_ok:
        cfg['last_triggered_at'] = now
        cfg['last_job_id'] = str(j.get('id'))
        _save(AUTO_PATH, cfg)
        return {'ok': True, 'triggered': True, 'job': j, 'start': st, 'config': cfg}

    return {'ok': False, 'triggered': False, 'reason': 'start_failed', 'job': j, 'start': st, 'config': cfg}


def job_progress(job_id: str) -> dict[str, Any]:
    j = get_job(job_id)
    if not j:
        return {'ok': False, 'error': 'job_not_found'}

    st = str(j.get('status') or '')
    if st == 'running_remote':
        rj = str(j.get('remote_job_id') or '')
        rurl = str(j.get('remote_url') or os.getenv('ULTRON_FINETUNE_URL', '')).strip()
        rtoken = str(os.getenv('ULTRON_FINETUNE_TOKEN', '')).strip()
        if rj and rurl:
            try:
                base = rurl.rsplit('/train', 1)[0] if '/train' in rurl else rurl.rsplit('/', 1)[0]
                surl = f"{base}/jobs/{rj}"
                headers = {'x-api-key': rtoken} if rtoken else {}
                with httpx.Client(timeout=20.0) as hc:
                    rr = hc.get(surl, headers=headers)
                    rr.raise_for_status()
                    data = rr.json()
                rjob = (data or {}).get('job') or {}
                rstatus = str(rjob.get('status') or '')

                if rstatus == 'failed':
                    _set_job(job_id, {'status': 'remote_failed', 'remote_status': rjob, 'last_error': str(rjob.get('last_error') or 'remote failed')[:500]})
                    return {'ok': True, 'job': get_job(job_id), 'remote_status': rjob}

                if rstatus == 'completed':
                    # pull adapter artifact from remote and register locally
                    aurl = f"{base}/jobs/{rj}/artifact"
                    local_out = Path(str(j.get('adapter_out') or ''))
                    local_out.mkdir(parents=True, exist_ok=True)
                    with httpx.Client(timeout=120.0) as hc:
                        ar = hc.get(aurl, headers=headers)
                        ar.raise_for_status()
                        with tempfile.NamedTemporaryFile(delete=False, suffix='.tar.gz') as tf:
                            tf.write(ar.content)
                            tpath = tf.name
                    with tempfile.TemporaryDirectory() as td:
                        with tarfile.open(tpath, 'r:gz') as tar:
                            tar.extractall(path=td)
                        root = Path(td)
                        cand = [p for p in root.iterdir() if p.is_dir()]
                        src = cand[0] if cand else root
                        # clear and copy fresh adapter files
                        for ch in local_out.iterdir():
                            if ch.is_dir():
                                shutil.rmtree(ch, ignore_errors=True)
                            else:
                                try:
                                    ch.unlink()
                                except Exception:
                                    pass
                        if src.is_dir():
                            for it in src.iterdir():
                                dst = local_out / it.name
                                if it.is_dir():
                                    shutil.copytree(it, dst, dirs_exist_ok=True)
                                else:
                                    shutil.copy2(it, dst)
                    try:
                        os.remove(tpath)
                    except Exception:
                        pass

                    _set_job(job_id, {'status': 'completed', 'remote_status': rjob, 'last_error': None})
                    reg = register_adapter(job_id, quality_score=0.66, notes='auto-registered from remote Colab trainer')
                    return {'ok': True, 'job': get_job(job_id), 'remote_status': rjob, 'synced': True, 'register': reg}

                return {'ok': True, 'job': get_job(job_id), 'remote_status': rjob}
            except Exception as e:
                return {'ok': True, 'job': j, 'remote_error': str(e)[:240]}

    return {'ok': True, 'job': j}


def promote_adapter(adapter_id: str, min_gain: float = 0.02, baseline_score: float | None = None, candidate_score: float | None = None) -> dict[str, Any]:
    reg = _load_reg()
    arr = list(reg.get('adapters') or [])
    idx = -1
    cand = None
    for i, a in enumerate(arr):
        if str(a.get('id')) == str(adapter_id):
            idx = i
            cand = a
            break
    if idx < 0 or cand is None:
        return {'ok': False, 'error': 'adapter_not_found'}

    tt = str(cand.get('task_type') or 'general').lower().strip()
    cscore = float(candidate_score if candidate_score is not None else (cand.get('quality_score') or 0.0))
    if baseline_score is None:
        active_same = [a for a in arr if str(a.get('task_type') or '').lower().strip() == tt and bool(a.get('active')) and str(a.get('id')) != str(adapter_id)]
        bscore = max([float(a.get('quality_score') or 0.0) for a in active_same], default=0.0)
    else:
        bscore = float(baseline_score)

    passed = bool(cscore >= max(0.6, bscore + float(min_gain)))
    decision = {
        'adapter_id': adapter_id,
        'task_type': tt,
        'candidate_score': round(cscore, 4),
        'baseline_score': round(float(bscore), 4),
        'min_gain': float(min_gain),
        'passed': passed,
    }

    if not passed:
        return {'ok': True, 'promoted': False, 'decision': decision}

    for i, a in enumerate(arr):
        if str(a.get('task_type') or '').lower().strip() == tt:
            a['active'] = (str(a.get('id')) == str(adapter_id))
            arr[i] = a
    reg['adapters'] = arr
    _save_reg(reg)
    return {'ok': True, 'promoted': True, 'decision': decision, 'adapter': [a for a in arr if str(a.get('id')) == str(adapter_id)][0]}


def status(limit: int = 40) -> dict[str, Any]:
    js = list_jobs(limit=limit)
    ad = adapters(limit=limit)
    return {
        'ok': True,
        'jobs_path': str(JOBS_PATH),
        'registry_path': str(REG_PATH),
        'dataset_path': str(DATASET_PATH),
        'auto': auto_status(),
        'jobs': js,
        'adapters': ad,
    }
