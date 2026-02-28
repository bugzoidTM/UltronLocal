#!/usr/bin/env python3
import json, time, subprocess, base64
from pathlib import Path

OUT = Path('/root/.openclaw/workspace/UltronPro/tools/burnin_report.jsonl')
ALERT = Path('/root/.openclaw/workspace/UltronPro/tools/burnin_alerts.jsonl')


def sh(cmd: str) -> str:
    return subprocess.check_output(['bash', '-lc', cmd], text=True, stderr=subprocess.STDOUT).strip()


def append(path: Path, row: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as f:
        f.write(json.dumps(row, ensure_ascii=False) + '\n')


def main():
    ts = int(time.time())
    row = {'ts': ts}

    try:
        cid = sh("docker ps --filter name=ultronpro_ultronpro -q | head -n1")
        row['container'] = cid
        py_code = """
import json, urllib.request
base='http://127.0.0.1:8000'
out={}
for u in ['/api/runtime/health','/api/plasticity/finetune/status?limit=50','/api/projects/run_state']:
    try:
        with urllib.request.urlopen(base+u, timeout=20) as r:
            out[u]=json.loads(r.read().decode('utf-8','ignore'))
    except Exception as e:
        out[u]={'_error': str(e)}
print(json.dumps(out,ensure_ascii=False))
""".strip()
        b64 = base64.b64encode(py_code.encode()).decode()
        payload = sh(f"docker exec {cid} python -c \"import base64;exec(base64.b64decode('{b64}'))\"")
        data = json.loads(payload)
        st = data.get('/api/plasticity/finetune/status?limit=50', {})
        jobs = st.get('jobs', [])
        statuses = {}
        for j in jobs:
            s = str(j.get('status') or 'unknown')
            statuses[s] = statuses.get(s, 0) + 1
        row['finetune_statuses_recent'] = statuses
        row['runtime_health'] = data.get('/api/runtime/health', {})
        row['run_state_steps'] = len((data.get('/api/projects/run_state', {}) or {}).get('steps') or [])

        # db size + container memory
        db_size = sh(f"docker exec {cid} sh -lc \"stat -c%s /app/data/ultron.db 2>/dev/null || echo 0\"")
        mem = sh(f"docker exec {cid} sh -lc \"cat /sys/fs/cgroup/memory.current 2>/dev/null || echo 0\"")
        row['db_size_bytes'] = int(db_size or 0)
        row['container_mem_bytes'] = int(mem or 0)

        append(OUT, row)

        # simple alerts
        q = statuses.get('queued_remote_wait', 0)
        rerr = statuses.get('remote_error', 0)
        if q >= 8:
            append(ALERT, {'ts': ts, 'level': 'warn', 'code': 'queue_depth_high', 'queued_remote_wait': q})
        if rerr >= 10:
            append(ALERT, {'ts': ts, 'level': 'warn', 'code': 'remote_error_high_recent', 'remote_error': rerr})
        if row['container_mem_bytes'] > 3_500_000_000:
            append(ALERT, {'ts': ts, 'level': 'warn', 'code': 'container_mem_high', 'mem_bytes': row['container_mem_bytes']})

    except Exception as e:
        append(ALERT, {'ts': ts, 'level': 'error', 'code': 'burnin_monitor_error', 'error': str(e)[:500]})


if __name__ == '__main__':
    main()
