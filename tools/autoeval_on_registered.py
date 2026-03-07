#!/usr/bin/env python3
import json
import subprocess
import time
from pathlib import Path
import urllib.request
import sys

BASE = 'https://ultronpro.nutef.com'
TOOLS = Path('/root/.openclaw/workspace/UltronPro/tools')

JOB_ID = sys.argv[1] if len(sys.argv) > 1 else ''
if not JOB_ID:
    raise SystemExit('usage: autoeval_on_registered.py <job_id>')

STATE = TOOLS / f'autoeval_{JOB_ID}.state.json'
LOG = TOOLS / f'autoeval_{JOB_ID}.log'


def get_json(path: str):
    with urllib.request.urlopen(BASE + path, timeout=40) as r:
        return json.loads(r.read().decode('utf-8', 'ignore'))


def log(msg: str):
    with LOG.open('a', encoding='utf-8') as f:
        f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")


def save_state(st):
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding='utf-8')


def fetch_epoch_metrics(job_obj: dict):
    ru = str(job_obj.get('remote_url') or '')
    rid = str(job_obj.get('remote_job_id') or '')
    if not ru or not rid:
        return []
    base = ru.rsplit('/train', 1)[0] if '/train' in ru else ru.rsplit('/', 1)[0]
    url = f"{base}/jobs/{rid}/metrics"
    req = urllib.request.Request(url, headers={'x-api-key': 'TOKEN_FORTE_123'})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            txt = r.read().decode('utf-8', 'ignore')
        rows = []
        for ln in txt.splitlines():
            ln = ln.strip()
            if not ln:
                continue
            try:
                rows.append(json.loads(ln))
            except Exception:
                pass
        return rows
    except Exception:
        return []


def main():
    st = {'job_id': JOB_ID, 'done': False, 'last_status': None, 'runs': []}
    save_state(st)

    # wait up to ~3h
    for _ in range(180):
        js = get_json('/api/plasticity/finetune/status?limit=250')
        job = next((j for j in (js.get('jobs') or []) if str(j.get('id')) == JOB_ID), None)
        status = str((job or {}).get('status') or '')
        st['last_status'] = status
        save_state(st)
        log(f'status={status}')

        if status in ('registered', 'completed'):
            # fetch epoch curve first
            metrics = fetch_epoch_metrics(job or {})
            if metrics:
                mp = TOOLS / f'metrics_{JOB_ID}.jsonl'
                mp.write_text(''.join(json.dumps(x, ensure_ascii=False) + '\n' for x in metrics), encoding='utf-8')
                # summarize first worsening epoch
                first_worsen = None
                for m in metrics:
                    if int(m.get('bad_val_streak') or 0) >= 1:
                        first_worsen = m.get('epoch')
                        break
                st['metrics'] = {
                    'path': str(mp),
                    'points': len(metrics),
                    'first_val_worsen_epoch': first_worsen,
                }
                save_state(st)
                log(f"metrics_fetched points={len(metrics)} first_worsen={first_worsen}")

            log('trigger_eval_batteries')
            p = subprocess.run(['/root/.openclaw/workspace/UltronPro/tools/eval_battery_runner.py'], capture_output=True, text=True)
            tail = (p.stdout or '').strip().splitlines()[-6:]
            st['runs'].append({'ts': int(time.time()), 'rc': p.returncode, 'stdout_tail': tail})
            st['done'] = True
            save_state(st)
            log(f'eval_done rc={p.returncode}')
            return

        if status in ('failed', 'remote_failed'):
            log('job_failed_abort')
            save_state(st)
            return

        time.sleep(60)

    log('timeout_waiting_registered')
    save_state(st)


if __name__ == '__main__':
    main()
