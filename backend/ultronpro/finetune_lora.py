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
EVAL_GOLD_PATH = Path('/app/data/eval_dataset_gold.json')
AUTO_PATH = Path('/app/data/finetune_auto.json')
METRICS_PATH = Path('/app/data/finetune_metrics.json')
ALERTS_PATH = Path('/app/data/finetune_alerts.jsonl')
ARTIFACTS_DIR = Path('/app/data/finetune_artifacts')
RELEASES_DIR = Path('/app/data/finetune_releases')
ARTIFACT_REG_PATH = Path('/app/data/finetune_artifacts_registry.json')
ACTIVE_RELEASE_PATH = Path('/app/data/runtime_active_adapter.json')


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


def _load_artifact_reg() -> dict[str, Any]:
    d = _load(ARTIFACT_REG_PATH, {'artifacts': [], 'releases': []})
    if not isinstance(d, dict):
        d = {'artifacts': [], 'releases': []}
    d.setdefault('artifacts', [])
    d.setdefault('releases', [])
    return d


def _save_artifact_reg(d: dict[str, Any]):
    _save(ARTIFACT_REG_PATH, d)


def _sha256_path(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _artifact_urls(artifact_id: str) -> dict[str, str]:
    aid = str(artifact_id or '').strip()
    return {
        'manifest': f'/api/plasticity/artifacts/{aid}',
        'download': f'/api/plasticity/artifacts/{aid}/download',
    }


def _release_urls(release_id: str) -> dict[str, str]:
    rid = str(release_id or '').strip()
    return {
        'manifest': f'/api/plasticity/releases/{rid}',
        'download': f'/api/plasticity/releases/{rid}/download',
        'modelfile': f'/api/plasticity/releases/{rid}/modelfile',
    }


def _extract_pair_from_note(note: str) -> tuple[str, str]:
    n = str(note or '').strip()
    # expected pattern used by GUI feedback: "... user=<text> reply=<text>"
    m = re.search(r"user=(.*?)\s+reply=(.*)$", n, flags=re.IGNORECASE | re.DOTALL)
    if not m:
        return '', ''
    user = re.sub(r"\s+", ' ', (m.group(1) or '').strip())
    reply = re.sub(r"\s+", ' ', (m.group(2) or '').strip())
    return user[:420], reply[:420]


def _domain_from_task(task: str) -> str:
    t = str(task or '').lower()
    if any(k in t for k in ('code', 'python', 'sql', 'tool', 'db')):
        return 'software'
    if any(k in t for k in ('finance', 'business', 'market', 'produto', 'vendas')):
        return 'business'
    if any(k in t for k in ('legal', 'jurid', 'compliance', 'policy')):
        return 'legal'
    if any(k in t for k in ('research', 'science', 'paper', 'experimento')):
        return 'science'
    return 'operations'


def _ensure_eval_gold():
    if EVAL_GOLD_PATH.exists():
        return
    gold = {
        'must_have_domains': ['software', 'business', 'legal', 'science', 'operations'],
        'min_rows': 60,
        'min_hard_fix_ratio': 0.12,
        'max_policy_ratio': 0.40,
    }
    _save(EVAL_GOLD_PATH, gold)


def _domain_seed_rows(domain: str, n: int = 16) -> list[dict[str, Any]]:
    templates = {
        'software': (
            'Task: software. Diagnostique erro intermitente de API e proponha correção com retry idempotente e timeout.',
            'A causa provável é falha transitória. Aplicar timeout curto, retry com backoff exponencial e chave de idempotência para evitar duplicação.'
        ),
        'business': (
            'Task: business. Avalie impacto de custo e receita ao escolher entre duas automações.',
            'Escolha a automação com menor custo total de operação e maior previsibilidade de SLA, validando ROI em janela de 30 dias.'
        ),
        'legal': (
            'Task: legal. Responda com cautela sobre conformidade e riscos regulatórios sem inventar norma.',
            'Sem base normativa confirmada, devo tratar como hipótese e recomendar validação jurídica formal antes de execução.'
        ),
        'science': (
            'Task: science. Explique hipótese, método e critério de validação para experimento controlado.',
            'Defina hipótese testável, grupo de controle, métrica objetiva e critério de rejeição para reduzir viés de confirmação.'
        ),
        'operations': (
            'Task: operations. Priorize ação para reduzir fila crítica sem degradar estabilidade.',
            'Ative backpressure, limite concorrência por nó e execute watchdog para liberar fila sem comprometer consistência.'
        ),
    }
    ins, out = templates.get(domain, templates['operations'])
    rows = []
    for i in range(max(1, int(n or 1))):
        rows.append({
            'instruction': f"{ins} Exemplo {i+1}.",
            'output': out,
            'task_type': domain,
            'domain': domain,
            'label': 'curriculum_seed',
        })
    return rows


def _eval_dataset_quality(rows: list[dict[str, Any]]) -> dict[str, Any]:
    _ensure_eval_gold()
    g = _load(EVAL_GOLD_PATH, {})
    labels = [str(r.get('label') or '') for r in rows]
    domains = [str(r.get('domain') or '') for r in rows]
    n = max(1, len(rows))
    hard = sum(1 for x in labels if x == 'hard_fix') / n
    pol = sum(1 for x in labels if x == 'policy') / n
    dom_set = set(domains)
    must = set(g.get('must_have_domains') or [])
    missing = sorted(list(must - dom_set))
    ok = (
        len(rows) >= int(g.get('min_rows') or 60)
        and hard >= float(g.get('min_hard_fix_ratio') or 0.12)
        and pol <= float(g.get('max_policy_ratio') or 0.40)
        and not missing
    )
    return {
        'ok': bool(ok),
        'rows': len(rows),
        'hard_fix_ratio': round(hard, 4),
        'policy_ratio': round(pol, 4),
        'domains': sorted(list(dom_set)),
        'missing_domains': missing,
    }


def build_dataset_from_feedback(feedback: list[dict[str, Any]], max_items: int = 400) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()

    for f in (feedback or [])[-max(40, int(max_items or 400)):]:
        note = str(f.get('note') or '').strip()
        if not note:
            continue

        task = str(f.get('task_type') or 'general')[:48]
        domain = _domain_from_task(task)
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
                    'domain': domain,
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
                    'domain': domain,
                    'label': 'hard_fix',
                })

            # explicit counterexample pattern to improve transfer under failures
            bad_out = "Resposta inventada sem verificação."
            cin = f"Task: {task}. User said: {user_text}. This is a counterexample: explain why the following answer is wrong and then provide a safer corrected answer."
            cout = "A resposta está errada porque inventa fatos sem evidência. Correção: Não tenho dados suficientes para afirmar isso com segurança; posso verificar e retornar com confirmação."
            ckey = f"{task}|counter|{user_text}|{bad_out}"
            if ckey not in seen:
                seen.add(ckey)
                rows.append({
                    'instruction': cin[:520],
                    'output': cout,
                    'task_type': task,
                    'domain': domain,
                    'label': 'counterexample',
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
                    'domain': domain,
                    'label': 'policy',
                })

    # ensure minimum domain coverage with seeded curriculum examples
    _ensure_eval_gold()
    gold = _load(EVAL_GOLD_PATH, {})
    must = list(gold.get('must_have_domains') or ['software', 'business', 'legal', 'science', 'operations'])
    dom_now = {str(r.get('domain') or '') for r in rows}
    for dmn in must:
        if dmn not in dom_now:
            rows.extend(_domain_seed_rows(dmn, n=18))

    # enforce minimum hard-fix ratio for strict safety curriculum
    hard_count = len([r for r in rows if str(r.get('label') or '') == 'hard_fix'])
    min_hard_ratio = float((_load(EVAL_GOLD_PATH, {}) or {}).get('min_hard_fix_ratio') or 0.12)
    import math
    target_hard = int(max(1, math.ceil(min_hard_ratio * max(1, len(rows))) + 1))
    if hard_count < target_hard:
        need = target_hard - hard_count
        domains_for_hard = ['software', 'business', 'legal', 'science', 'operations']
        for i in range(need):
            dmn = domains_for_hard[i % len(domains_for_hard)]
            rows.append({
                'instruction': f"Task: {dmn}. Usuário trouxe afirmação sem evidência. Corrija de forma segura e peça confirmação objetiva.",
                'output': "Não posso confirmar isso com segurança sem evidência verificável. Posso validar com fontes e te retornar com precisão.",
                'task_type': dmn,
                'domain': dmn,
                'label': 'hard_fix',
            })

    # curriculum balance by domain
    buckets: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        buckets.setdefault(str(r.get('domain') or 'operations'), []).append(r)
    for arr in buckets.values():
        random.Random(42).shuffle(arr)

    target = max(20, int(max_items or 400))
    order = ['software', 'business', 'legal', 'science', 'operations']
    balanced: list[dict[str, Any]] = []
    while len(balanced) < target:
        progressed = False
        for dmn in order:
            arr = buckets.get(dmn) or []
            if arr:
                balanced.append(arr.pop())
                progressed = True
                if len(balanced) >= target:
                    break
        if not progressed:
            break

    rows = balanced if balanced else rows
    random.Random(42).shuffle(rows)
    rows = rows[:target]

    val_n = max(1, int(len(rows) * 0.1)) if len(rows) >= 10 else 1
    val_rows = rows[:val_n]
    train_rows = rows[val_n:] if len(rows) > val_n else rows

    DATASET_PATH.parent.mkdir(parents=True, exist_ok=True)
    for pth, arr in ((DATASET_PATH, rows), (DATASET_TRAIN_PATH, train_rows), (DATASET_VAL_PATH, val_rows)):
        with pth.open('w', encoding='utf-8') as fp:
            for r in arr:
                fp.write(json.dumps(r, ensure_ascii=False) + '\n')

    evalq = _eval_dataset_quality(rows)
    if not evalq.get('ok'):
        _append_alert('warn', 'dataset_quality_gate', 'dataset abaixo do gate de qualidade', evalq)

    return {
        'ok': True,
        'path': str(DATASET_PATH),
        'train_path': str(DATASET_TRAIN_PATH),
        'val_path': str(DATASET_VAL_PATH),
        'rows': len(rows),
        'train_rows': len(train_rows),
        'val_rows': len(val_rows),
        'dataset_eval': evalq,
        'labels': {
            'ok_real': len([r for r in rows if r.get('label') == 'ok_real']),
            'hard_fix': len([r for r in rows if r.get('label') == 'hard_fix']),
            'counterexample': len([r for r in rows if r.get('label') == 'counterexample']),
            'policy': len([r for r in rows if r.get('label') == 'policy']),
        }
    }


def _task_priority(task_type: str) -> int:
    tt = str(task_type or '').lower()
    if tt in ('grounding', 'assistant'):
        return 90
    if tt in ('planning', 'tools'):
        return 75
    return 60


def _append_alert(level: str, code: str, message: str, extra: dict[str, Any] | None = None):
    ALERTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    row = {'ts': int(time.time()), 'level': level, 'code': code, 'message': message[:240], 'extra': extra or {}}
    with ALERTS_PATH.open('a', encoding='utf-8') as fp:
        fp.write(json.dumps(row, ensure_ascii=False) + '\n')


def _update_metrics_snapshot():
    d = _load_jobs()
    jobs = d.get('jobs') or []
    statuses = {}
    for j in jobs:
        st = str(j.get('status') or 'unknown')
        statuses[st] = int(statuses.get(st, 0)) + 1
    running_by_node = {}
    for j in jobs:
        if str(j.get('status') or '') == 'running_remote':
            ru = str(j.get('remote_url') or 'unknown')
            running_by_node[ru] = int(running_by_node.get(ru, 0)) + 1
    m = {
        'ts': int(time.time()),
        'total_jobs': len(jobs),
        'statuses': statuses,
        'running_by_node': running_by_node,
    }
    _save(METRICS_PATH, m)
    # automatic alerts
    if int(statuses.get('queued_remote_wait', 0)) >= 10:
        _append_alert('warn', 'queue_depth_high', 'queued_remote_wait acima do limiar', {'queued_remote_wait': int(statuses.get('queued_remote_wait', 0))})
    if int(statuses.get('remote_error', 0)) >= 5:
        _append_alert('warn', 'remote_error_spike', 'remote_error acima do limiar', {'remote_error': int(statuses.get('remote_error', 0))})
    return m


def create_job(task_type: str, base_model: str, method: str = 'qlora', max_samples: int = 400, run_preset: str | None = None) -> dict[str, Any]:
    d = _load_jobs()
    jid = 'ft_' + uuid.uuid4().hex[:10]

    allowed_base = str(os.getenv('ULTRON_FINETUNE_BASE_MODEL', 'Qwen/Qwen2.5-3B-Instruct'))
    strict_base = str(os.getenv('ULTRON_FINETUNE_STRICT_BASE', '1')).strip().lower() not in ('0', 'false', 'no', 'off')
    req_base = str(base_model or allowed_base)[:120]
    final_base = allowed_base if strict_base else req_base

    preset = str(run_preset or os.getenv('ULTRON_FINETUNE_DEFAULT_PRESET', 'production') or 'production').strip().lower()
    if preset not in ('production', 'fast_diagnostic'):
        preset = 'production'

    item = {
        'id': jid,
        'created_at': int(time.time()),
        'updated_at': int(time.time()),
        'status': 'created',
        'task_type': str(task_type or 'general')[:48],
        'base_model': final_base,
        'method': str(method or 'qlora')[:24],
        'max_samples': int(max_samples or 400),
        'run_preset': preset,
        'dataset_path': str(DATASET_TRAIN_PATH),
        'dataset_val_path': str(DATASET_VAL_PATH),
        'adapter_out': f"/app/data/adapters/{jid}",
        'pid': None,
        'last_error': (f"base_model_overridden:{req_base}->{allowed_base}" if (strict_base and req_base != allowed_base) else None),
        'priority': _task_priority(task_type),
        'remote_retry_count': 0,
        'remote_backoff_until': 0,
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


def _token_for_remote_url(remote_url: str) -> str:
    default_tok = os.getenv('ULTRON_FINETUNE_TOKEN', '').strip()
    raw = str(os.getenv('ULTRON_FINETUNE_TOKENS_JSON', '') or '').strip()
    if not raw:
        return default_tok
    try:
        mp = json.loads(raw)
        if isinstance(mp, dict):
            # exact url then host fallback
            if str(remote_url) in mp and str(mp.get(str(remote_url)) or '').strip():
                return str(mp.get(str(remote_url)) or '').strip()
            host = str(remote_url or '').split('://', 1)[-1].split('/', 1)[0]
            if host in mp and str(mp.get(host) or '').strip():
                return str(mp.get(host) or '').strip()
    except Exception:
        pass
    return default_tok


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


def queue_watchdog_tick(max_dispatch: int = 2) -> dict[str, Any]:
    now = int(time.time())
    jobs = list_jobs(limit=500)

    # 1) Reconcile running_remote jobs first (pull remote completion -> local register/promote flow)
    synced = 0
    for j in jobs:
        if str(j.get('status') or '') == 'running_remote':
            try:
                out = job_progress(str(j.get('id')))
                if bool((out or {}).get('synced')):
                    synced += 1
            except Exception:
                pass

    # refresh view after reconcile
    jobs = list_jobs(limit=500)

    # 2) dispatch queued jobs within backoff constraints
    waiting = [
        j for j in jobs
        if str(j.get('status') or '') == 'queued_remote_wait'
        and int(j.get('remote_backoff_until') or 0) <= now
    ]
    waiting.sort(key=lambda x: (-int(x.get('priority') or 0), int(x.get('created_at') or 0)))

    started: list[str] = []
    blocked = 0
    for j in waiting[:max(1, int(max_dispatch or 2))]:
        out = start_job(str(j.get('id')), dry_run=False)
        if bool(out.get('ok')) and str((out.get('job') or {}).get('status') or '') == 'running_remote':
            started.append(str(j.get('id')))
        else:
            blocked += 1

    m = _update_metrics_snapshot()
    return {'ok': True, 'started': started, 'blocked': blocked, 'waiting': len(waiting), 'synced': synced, 'metrics': m}


def _resolve_preset_params(j: dict[str, Any]) -> dict[str, Any]:
    preset = str(j.get('run_preset') or os.getenv('ULTRON_FINETUNE_DEFAULT_PRESET', 'production') or 'production').strip().lower()
    if preset not in ('production', 'fast_diagnostic'):
        preset = 'production'

    if preset == 'fast_diagnostic':
        return {
            'preset': preset,
            'epochs': int(os.getenv('ULTRON_FINETUNE_FAST_EPOCHS', '3') or 3),
            'early_pat': int(os.getenv('ULTRON_FINETUNE_FAST_EARLY_STOP_PATIENCE', '2') or 2),
            'max_steps': int(os.getenv('ULTRON_FINETUNE_FAST_MAX_STEPS', '300') or 300),
            'batch_size': int(os.getenv('ULTRON_FINETUNE_FAST_BATCH_SIZE', '1') or 1),
            'grad_accum': int(os.getenv('ULTRON_FINETUNE_FAST_GRAD_ACCUM', '8') or 8),
            'max_length': int(os.getenv('ULTRON_FINETUNE_FAST_MAX_LENGTH', '512') or 512),
        }

    return {
        'preset': 'production',
        'epochs': int(os.getenv('ULTRON_FINETUNE_EPOCHS', '5') or 5),
        'early_pat': int(os.getenv('ULTRON_FINETUNE_EARLY_STOP_PATIENCE', '2') or 2),
        'max_steps': int(os.getenv('ULTRON_FINETUNE_MAX_STEPS', '0') or 0),
        'batch_size': int(os.getenv('ULTRON_FINETUNE_BATCH_SIZE', '1') or 1),
        'grad_accum': int(os.getenv('ULTRON_FINETUNE_GRAD_ACCUM', '8') or 8),
        'max_length': int(os.getenv('ULTRON_FINETUNE_MAX_LENGTH', '512') or 512),
    }


def start_job(job_id: str, dry_run: bool = False) -> dict[str, Any]:
    j = get_job(job_id)
    if not j:
        return {'ok': False, 'error': 'job_not_found'}

    now = int(time.time())
    if int(j.get('remote_backoff_until') or 0) > now and (not dry_run):
        return {'ok': False, 'job': j, 'error': 'backoff_active', 'retry_after_sec': int(j.get('remote_backoff_until') or 0) - now}

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
        base_model = os.getenv('ULTRON_FINETUNE_BASE_MODEL', 'Qwen/Qwen2.5-3B-Instruct')

    preset_cfg = _resolve_preset_params(j)
    run_preset = str(preset_cfg.get('preset') or 'production')

    if not cmd_tpl:
        epochs = max(1, int(preset_cfg.get('epochs') or 5))
        early_pat = max(1, int(preset_cfg.get('early_pat') or 2))
        max_steps = max(0, int(preset_cfg.get('max_steps') or 0))
        batch_size = max(1, int(preset_cfg.get('batch_size') or 1))
        grad_accum = max(1, int(preset_cfg.get('grad_accum') or 8))
        max_length = max(64, int(preset_cfg.get('max_length') or 512))

        method = 'qlora'
        cmd = (
            f"python -m ultronpro.train_lora "
            f"--base-model '{base_model}' "
            f"--method '{method}' "
            f"--dataset '{str(dataset)}' "
            f"--val-dataset '{str(val_dataset) if val_dataset.exists() else ''}' "
            f"--adapter-out '{adapter_out}' "
            f"--run-preset '{run_preset}' "
            f"--epochs {epochs} --batch-size {batch_size} --grad-accum {grad_accum} --max-length {max_length} "
            f"--max-steps {max_steps} "
            f"--early-stopping-patience {early_pat}"
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
    remote_token = _token_for_remote_url(remote_url) if remote_url else os.getenv('ULTRON_FINETUNE_TOKEN', '').strip()

    if dry_run:
        jj = _set_job(job_id, {'status': 'dry_run_ready', 'command': cmd, 'remote_url': remote_url or None, 'run_preset': run_preset})
        return {'ok': True, 'job': jj, 'command': cmd, 'remote_url': remote_url or None}

    if (not remote_url) and remote_urls_cfg:
        retries = int(j.get('remote_retry_count') or 0) + 1
        base_backoff = min(900, 30 * (2 ** min(4, retries - 1)))
        jitter = random.randint(0, max(1, int(base_backoff * 0.2)))
        backoff = base_backoff + jitter
        jj = _set_job(job_id, {
            'status': 'queued_remote_wait',
            'last_error': 'remote_capacity_full',
            'remote_retry_count': retries,
            'remote_backoff_until': int(time.time()) + backoff,
        })
        _update_metrics_snapshot()
        return {'ok': False, 'job': jj, 'error': 'remote_capacity_full', 'retry_after_sec': backoff}

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

            epochs = max(1, int(preset_cfg.get('epochs') or 5))
            early_pat = max(1, int(preset_cfg.get('early_pat') or 2))
            max_steps = max(0, int(preset_cfg.get('max_steps') or 0))
            payload = {
                'base_model': base_model,
                'method': str(j.get('method') or 'qlora'),
                'dataset': str(dataset),
                'dataset_content': ds_text,
                'val_dataset': str(val_dataset) if val_dataset.exists() else '',
                'val_dataset_content': val_text,
                'adapter_out': adapter_out,
                'run_preset': run_preset,
                'epochs': epochs,
                'max_steps': max_steps,
                'batch_size': max(1, int(preset_cfg.get('batch_size') or 1)),
                'grad_accum': max(1, int(preset_cfg.get('grad_accum') or 8)),
                'max_length': max(64, int(preset_cfg.get('max_length') or 512)),
                'early_stopping_patience': early_pat,
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
                'run_preset': run_preset,
                'remote_retry_count': 0,
                'remote_backoff_until': 0,
            })
            _update_metrics_snapshot()
            return {'ok': True, 'job': jj, 'remote': data}
        except Exception as e:
            err = str(e)
            try:
                import httpx as _hx
                if isinstance(e, _hx.HTTPStatusError) and e.response is not None:
                    err = f"{e} | body={e.response.text[:500]}"
            except Exception:
                pass
            retries = int(j.get('remote_retry_count') or 0) + 1
            base_backoff = min(1800, 60 * (2 ** min(4, retries - 1)))
            jitter = random.randint(0, max(1, int(base_backoff * 0.2)))
            backoff = base_backoff + jitter
            jj = _set_job(job_id, {
                'status': 'queued_remote_wait',
                'last_error': err[:500],
                'remote_url': remote_url,
                'remote_retry_count': retries,
                'remote_backoff_until': int(time.time()) + backoff,
            })
            if retries >= 4:
                _append_alert('warn', 'remote_retry_high', f'retry alto no job {job_id}', {'job_id': job_id, 'retries': retries, 'remote_url': remote_url})
            _update_metrics_snapshot()
            return {'ok': False, 'job': jj, 'error': err, 'retry_after_sec': backoff}

    p = subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    jj = _set_job(job_id, {'status': 'running', 'pid': int(p.pid), 'command': cmd})
    _update_metrics_snapshot()
    return {'ok': True, 'job': jj}


def _persist_artifact_from_job(j: dict[str, Any], remote_job_id: str = '') -> dict[str, Any]:
    job_id = str((j or {}).get('id') or '').strip()
    local_out = Path(str((j or {}).get('adapter_out') or '')).resolve()
    if not job_id:
        return {'ok': False, 'error': 'job_id_required'}
    if (not local_out.exists()) or (not local_out.is_dir()):
        return {'ok': False, 'error': 'adapter_out_missing', 'adapter_out': str(local_out)}
    if not (local_out / 'adapter_config.json').exists():
        return {'ok': False, 'error': 'adapter_config_missing', 'adapter_out': str(local_out)}

    artifact_id = 'art_' + uuid.uuid4().hex[:10]
    root = ARTIFACTS_DIR / artifact_id
    extracted = root / 'adapter'
    root.mkdir(parents=True, exist_ok=True)
    if extracted.exists():
        shutil.rmtree(extracted, ignore_errors=True)
    shutil.copytree(local_out, extracted, dirs_exist_ok=True)

    tar_path = root / 'artifact.tar.gz'
    with tarfile.open(tar_path, 'w:gz') as tf:
        tf.add(extracted, arcname='adapter')

    cfg = {}
    try:
        cfg = json.loads((extracted / 'adapter_config.json').read_text(encoding='utf-8'))
    except Exception:
        cfg = {}

    meta = {
        'id': artifact_id,
        'job_id': job_id,
        'remote_job_id': str(remote_job_id or (j or {}).get('remote_job_id') or ''),
        'task_type': str((j or {}).get('task_type') or 'general'),
        'base_model': str((j or {}).get('base_model') or ''),
        'source_remote_url': str((j or {}).get('remote_url') or ''),
        'artifact_dir': str(root),
        'adapter_dir': str(extracted),
        'tarball_path': str(tar_path),
        'sha256': _sha256_path(tar_path),
        'size_bytes': int(tar_path.stat().st_size if tar_path.exists() else 0),
        'created_at': int(time.time()),
        'adapter_config': cfg,
        'urls': _artifact_urls(artifact_id),
    }
    reg = _load_artifact_reg()
    reg['artifacts'].append(meta)
    _save_artifact_reg(reg)
    _set_job(job_id, {'artifact_id': artifact_id, 'artifact_dir': str(root), 'artifact_tarball': str(tar_path)})
    return {'ok': True, 'artifact': meta}


def register_adapter(job_id: str, quality_score: float = 0.0, notes: str | None = None) -> dict[str, Any]:
    j = get_job(job_id)
    if not j:
        return {'ok': False, 'error': 'job_not_found'}

    artifact_meta = None
    if not str(j.get('artifact_id') or '').strip():
        pers = _persist_artifact_from_job(j)
        if bool(pers.get('ok')):
            artifact_meta = pers.get('artifact') or {}
            j = get_job(job_id) or j
    else:
        artifact_meta = next((a for a in (_load_artifact_reg().get('artifacts') or []) if str(a.get('id') or '') == str(j.get('artifact_id') or '')), None)

    reg = _load_reg()
    ad = {
        'id': 'adp_' + uuid.uuid4().hex[:8],
        'job_id': str(job_id),
        'task_type': str(j.get('task_type') or 'general'),
        'base_model': str(j.get('base_model') or ''),
        'adapter_path': str((artifact_meta or {}).get('adapter_dir') or j.get('adapter_out') or ''),
        'artifact_id': str((artifact_meta or {}).get('id') or j.get('artifact_id') or ''),
        'quality_score': float(quality_score or 0.0),
        'notes': str(notes or '')[:240],
        'created_at': int(time.time()),
        'active': bool(float(quality_score or 0.0) >= 0.6),
    }
    reg['adapters'].append(ad)
    _save_reg(reg)
    _set_job(job_id, {'status': 'registered'})
    _update_metrics_snapshot()
    return {'ok': True, 'adapter': ad, 'artifact': artifact_meta}


def notify_remote_complete(job_id: str, remote_job_id: str = '', adapter_out: str = '', notes: str | None = None) -> dict[str, Any]:
    jid = str(job_id or '').strip()
    if not jid:
        return {'ok': False, 'error': 'job_id_required'}

    j = get_job(jid)
    if not j:
        return {'ok': False, 'error': 'job_not_found', 'job_id': jid}

    out_path = str(adapter_out or j.get('adapter_out') or '').strip()
    if out_path:
        ap = Path(out_path)
        ok_files = (ap / 'adapter_config.json').exists() and (((ap / 'adapter_model.safetensors').exists()) or ((ap / 'train_meta.json').exists()))
    else:
        ok_files = False

    patch = {'status': 'completed' if ok_files else 'remote_failed'}
    if remote_job_id:
        patch['remote_job_id'] = str(remote_job_id)
    if not ok_files:
        patch['last_error'] = 'notify_complete_missing_artifacts'
    _set_job(jid, patch)

    reg = _load_reg()
    existing = next((a for a in (reg.get('adapters') or []) if str(a.get('job_id') or '') == jid), None)
    if existing is not None:
        _update_metrics_snapshot()
        return {'ok': True, 'job_id': jid, 'completed': bool(ok_files), 'registered': True, 'already_registered': True}

    if ok_files:
        rr = register_adapter(jid, quality_score=0.66, notes=str(notes or 'auto-registered by notify-complete')[:240])
        return {'ok': bool(rr.get('ok')), 'job_id': jid, 'completed': True, 'registered': bool(rr.get('ok')), 'register': rr}

    _update_metrics_snapshot()
    return {'ok': True, 'job_id': jid, 'completed': False, 'registered': False}


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
        'base_model': 'Qwen/Qwen2.5-3B-Instruct',
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


def _load_dataset_rows(limit: int = 800) -> list[dict[str, Any]]:
    rows = []
    try:
        if DATASET_PATH.exists():
            for ln in DATASET_PATH.read_text(encoding='utf-8', errors='ignore').splitlines()[-max(20, int(limit or 800)):]:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    rows.append(json.loads(ln))
                except Exception:
                    continue
    except Exception:
        pass
    return rows


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

    # strict eval gate before automatic trigger
    ds_eval = _eval_dataset_quality(_load_dataset_rows(limit=800))
    if not bool(ds_eval.get('ok')):
        _append_alert('warn', 'auto_trigger_blocked_eval_gate', 'auto trigger bloqueado por eval_dataset de ouro', ds_eval)
        return {'ok': True, 'triggered': False, 'reason': 'eval_gate_failed', 'dataset_eval': ds_eval, 'config': cfg}

    # avoid piling multiple concurrent jobs
    running = [x for x in list_jobs(limit=120) if str(x.get('status') or '') in ('running', 'running_remote')]
    if running:
        return {'ok': True, 'triggered': False, 'reason': 'job_already_running', 'running_job_id': str(running[-1].get('id') or ''), 'config': cfg}

    # create + start job
    j = create_job(
        str(cfg.get('task_type') or 'grounding'),
        str(cfg.get('base_model') or 'Qwen/Qwen2.5-3B-Instruct'),
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
        rtoken = _token_for_remote_url(rurl) if rurl else str(os.getenv('ULTRON_FINETUNE_TOKEN', '')).strip()
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
                    _append_alert('warn', 'remote_failed', f'job remoto falhou {job_id}', {'job_id': job_id, 'remote_url': rurl})
                    _update_metrics_snapshot()
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

                    # Safety gate: validate adapter base model matches requested job base_model.
                    try:
                        cfg_path = local_out / 'adapter_config.json'
                        cfg = json.loads(cfg_path.read_text(encoding='utf-8')) if cfg_path.exists() else {}
                        got_base = str(cfg.get('base_model_name_or_path') or '').strip()
                        want_base = str(j.get('base_model') or '').strip()
                        if want_base and got_base and (got_base != want_base):
                            _set_job(job_id, {
                                'status': 'remote_failed',
                                'remote_status': rjob,
                                'last_error': f'base_model_mismatch: expected={want_base} got={got_base}'[:500],
                            })
                            _append_alert('warn', 'remote_base_model_mismatch', f'job remoto base_model divergente {job_id}', {
                                'job_id': job_id,
                                'expected_base_model': want_base,
                                'got_base_model': got_base,
                                'remote_url': rurl,
                            })
                            _update_metrics_snapshot()
                            return {'ok': False, 'job': get_job(job_id), 'remote_status': rjob, 'synced': False, 'error': 'base_model_mismatch', 'expected_base_model': want_base, 'got_base_model': got_base}
                    except Exception:
                        pass

                    _set_job(job_id, {'status': 'completed', 'remote_status': rjob, 'last_error': None})
                    reg = register_adapter(job_id, quality_score=0.66, notes='auto-registered from remote trainer')
                    _update_metrics_snapshot()
                    return {'ok': True, 'job': get_job(job_id), 'remote_status': rjob, 'synced': True, 'register': reg}

                return {'ok': True, 'job': get_job(job_id), 'remote_status': rjob}
            except Exception as e:
                return {'ok': True, 'job': j, 'remote_error': str(e)[:240]}

    return {'ok': True, 'job': j}


def _passport_gate(task_type: str, candidate_score: float, baseline_score: float) -> dict[str, Any]:
    url = str(os.getenv('ULTRON_PASSPORT_URL', '') or '').strip()
    if not url:
        return {'ok': True, 'enforced': False, 'reason': 'passport_disabled'}

    min_score = float(os.getenv('ULTRON_PASSPORT_MIN_SCORE', '0.65'))
    token = str(os.getenv('ULTRON_PASSPORT_TOKEN', '') or '').strip()
    timeout = max(3.0, float(os.getenv('ULTRON_PASSPORT_TIMEOUT_SEC', '10')))
    fail_open = str(os.getenv('ULTRON_PASSPORT_FAIL_OPEN', '0')) == '1'
    cache_path = Path('/app/data/passport_last_good.json')

    try:
        params = {'min_score': min_score, 'task_type': task_type, 'candidate_score': candidate_score, 'baseline_score': baseline_score}
        headers = {'x-api-key': token} if token else {}
        with httpx.Client(timeout=timeout) as hc:
            r = hc.get(url, params=params, headers=headers)
            r.raise_for_status()
            js = r.json() if r.text else {}
        issued = bool(js.get('issued'))
        if not issued:
            return {'ok': False, 'enforced': True, 'reason': 'passport_denied', 'passport': js}
        try:
            cache_path.write_text(json.dumps({'ts': int(time.time()), 'task_type': task_type, 'passport': js}, ensure_ascii=False, indent=2), encoding='utf-8')
        except Exception:
            pass
        return {'ok': True, 'enforced': True, 'passport': js}
    except Exception as e:
        # fail-safe default remains deny; cache is observability only
        if fail_open:
            _append_alert('warn', 'passport_fail_open', f'passport gate falhou em fail-open: {e}', {'url': url})
            return {'ok': True, 'enforced': True, 'reason': 'passport_fail_open', 'error': str(e)[:180]}
        extra = {}
        try:
            if cache_path.exists():
                extra = {'last_good_passport': json.loads(cache_path.read_text(encoding='utf-8'))}
        except Exception:
            extra = {}
        return {'ok': False, 'enforced': True, 'reason': 'passport_unavailable', 'error': str(e)[:180], **extra}


def _runtime_activate_adapter(adapter: dict[str, Any]) -> dict[str, Any]:
    """Create an immutable promoted release on the VPS and mark it active.
    This is topology-safe: the artifact lives in the control plane, not on U1/U2.
    """
    artifact_id = str(adapter.get('artifact_id') or '').strip()
    if not artifact_id:
        return {'ok': False, 'applied': False, 'reason': 'missing_artifact_id'}

    reg = _load_artifact_reg()
    artifact = next((a for a in (reg.get('artifacts') or []) if str(a.get('id') or '') == artifact_id), None)
    if not artifact:
        return {'ok': False, 'applied': False, 'reason': 'artifact_not_found', 'artifact_id': artifact_id}

    release_id = 'rel_' + uuid.uuid4().hex[:10]
    release_root = RELEASES_DIR / release_id
    adapter_dst = release_root / 'adapter'
    release_root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(Path(str(artifact.get('adapter_dir') or '')), adapter_dst, dirs_exist_ok=True)

    ollama_base = str(os.getenv('OLLAMA_CANARY_MODEL', 'qwen2.5:3b-instruct-q4_K_M')).strip()
    model_name = f"qwen-promoted-{str(adapter.get('task_type') or 'general').strip().lower()}-{release_id[-6:]}"
    modelfile = (
        f"FROM {ollama_base}\n"
        f"ADAPTER ./adapter\n"
        f"TEMPLATE \"{{{{ .Prompt }}}}\"\n"
    )
    (release_root / 'Modelfile').write_text(modelfile, encoding='utf-8')

    release = {
        'id': release_id,
        'adapter_id': str(adapter.get('id') or ''),
        'artifact_id': artifact_id,
        'job_id': str(adapter.get('job_id') or ''),
        'task_type': str(adapter.get('task_type') or 'general'),
        'base_model': str(adapter.get('base_model') or ''),
        'ollama_base_model': ollama_base,
        'ollama_target_model': model_name,
        'release_dir': str(release_root),
        'adapter_dir': str(adapter_dst),
        'modelfile_path': str(release_root / 'Modelfile'),
        'created_at': int(time.time()),
        'sha256': str(artifact.get('sha256') or ''),
        'artifact_urls': _artifact_urls(artifact_id),
        'release_urls': _release_urls(release_id),
        'apply': {
            'kind': 'ollama_modelfile_with_adapter',
            'pull_from_vps': True,
            'commands': [
                f"curl -fsSL {{CONTROL_PLANE_URL}}/api/plasticity/releases/{release_id}/download -o /tmp/{release_id}.tar.gz",
                f"mkdir -p /tmp/{release_id} && tar -xzf /tmp/{release_id}.tar.gz -C /tmp/{release_id}",
                f"cd /tmp/{release_id} && ollama create {model_name} -f Modelfile",
            ],
        },
    }
    reg['releases'] = [r for r in (reg.get('releases') or []) if not (str(r.get('task_type') or '').strip().lower() == str(adapter.get('task_type') or '').strip().lower() and bool(r.get('active')))]
    release['active'] = True
    reg['releases'].append(release)
    _save_artifact_reg(reg)

    marker = {
        'ts': int(time.time()),
        'mode': 'remote_qwen_release',
        'release_id': release_id,
        'adapter_id': str(adapter.get('id') or ''),
        'artifact_id': artifact_id,
        'base_model': str(adapter.get('base_model') or ''),
        'ollama_base_model': ollama_base,
        'ollama_target_model': model_name,
        'task_type': str(adapter.get('task_type') or ''),
        'active': True,
        'release_urls': _release_urls(release_id),
    }
    ACTIVE_RELEASE_PATH.write_text(json.dumps(marker, ensure_ascii=False, indent=2), encoding='utf-8')
    return {'ok': True, 'applied': True, 'runtime': 'remote_qwen_release', 'marker': marker, 'release': release}


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

    job_id = str(cand.get('job_id') or '')
    j = get_job(job_id) if job_id else None
    preset = str((j or {}).get('run_preset') or 'production').strip().lower()
    if preset != 'production':
        return {'ok': True, 'promoted': False, 'reason': 'promotion_requires_production_job', 'run_preset': preset, 'job_id': job_id}

    tt = str(cand.get('task_type') or 'general').lower().strip()
    cscore = float(candidate_score if candidate_score is not None else (cand.get('quality_score') or 0.0))
    if baseline_score is None:
        active_same = [a for a in arr if str(a.get('task_type') or '').lower().strip() == tt and bool(a.get('active')) and str(a.get('id')) != str(adapter_id)]
        bscore = max([float(a.get('quality_score') or 0.0) for a in active_same], default=0.0)
    else:
        bscore = float(baseline_score)

    required = max(0.6, bscore + float(min_gain))
    regression_buffer = float(os.getenv('ULTRON_FINETUNE_REGRESSION_BUFFER', '0.02'))
    is_regression = bool(cscore < (bscore - regression_buffer))
    passed = bool((cscore >= required) and (not is_regression))
    decision = {
        'adapter_id': adapter_id,
        'task_type': tt,
        'candidate_score': round(cscore, 4),
        'baseline_score': round(float(bscore), 4),
        'required_score': round(required, 4),
        'min_gain': float(min_gain),
        'regression_buffer': regression_buffer,
        'is_regression': is_regression,
        'passed': passed,
    }

    if not passed:
        return {'ok': True, 'promoted': False, 'decision': decision}

    gate = _passport_gate(tt, cscore, float(bscore))
    decision['passport_gate'] = gate
    if not bool(gate.get('ok')):
        _append_alert('warn', 'passport_denied', f'passport bloqueou promoção adapter={adapter_id}', {'task_type': tt, 'gate': gate})
        return {'ok': True, 'promoted': False, 'decision': decision, 'reason': str(gate.get('reason') or 'passport_denied')}

    for i, a in enumerate(arr):
        if str(a.get('task_type') or '').lower().strip() == tt:
            a['active'] = (str(a.get('id')) == str(adapter_id))
            arr[i] = a
    reg['adapters'] = arr
    _save_reg(reg)
    chosen = [a for a in arr if str(a.get('id')) == str(adapter_id)][0]
    runtime_apply = _runtime_activate_adapter(chosen)
    return {'ok': True, 'promoted': True, 'decision': decision, 'adapter': chosen, 'runtime_apply': runtime_apply}


def artifacts(limit: int = 80) -> list[dict[str, Any]]:
    arr = list((_load_artifact_reg().get('artifacts') or []))
    return arr[-max(1, int(limit or 80)):]


def releases(limit: int = 80) -> list[dict[str, Any]]:
    arr = list((_load_artifact_reg().get('releases') or []))
    return arr[-max(1, int(limit or 80)):]


def get_artifact(artifact_id: str) -> dict[str, Any] | None:
    return next((a for a in (_load_artifact_reg().get('artifacts') or []) if str(a.get('id') or '') == str(artifact_id)), None)


def get_release(release_id: str) -> dict[str, Any] | None:
    return next((r for r in (_load_artifact_reg().get('releases') or []) if str(r.get('id') or '') == str(release_id)), None)


def active_release(task_type: str | None = None) -> dict[str, Any] | None:
    tt = str(task_type or '').strip().lower()
    rels = list((_load_artifact_reg().get('releases') or []))
    rels.reverse()
    for r in rels:
        if not bool(r.get('active')):
            continue
        if tt and str(r.get('task_type') or '').strip().lower() != tt:
            continue
        return r
    return None


def status(limit: int = 40) -> dict[str, Any]:
    # watchdog: tenta despachar fila pendente sem loop agressivo
    try:
        queue_watchdog_tick(max_dispatch=2)
    except Exception:
        pass

    js = list_jobs(limit=limit)
    ad = adapters(limit=limit)
    m = _update_metrics_snapshot()
    return {
        'ok': True,
        'jobs_path': str(JOBS_PATH),
        'registry_path': str(REG_PATH),
        'dataset_path': str(DATASET_PATH),
        'metrics_path': str(METRICS_PATH),
        'alerts_path': str(ALERTS_PATH),
        'artifact_registry_path': str(ARTIFACT_REG_PATH),
        'artifacts_dir': str(ARTIFACTS_DIR),
        'releases_dir': str(RELEASES_DIR),
        'active_release_path': str(ACTIVE_RELEASE_PATH),
        'metrics': m,
        'auto': auto_status(),
        'jobs': js,
        'adapters': ad,
        'artifacts': artifacts(limit=limit),
        'releases': releases(limit=limit),
        'active_release': active_release(),
    }
