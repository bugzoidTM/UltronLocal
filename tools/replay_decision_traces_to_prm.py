#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
import urllib.request
from typing import Iterable

DEFAULT_BASE = 'https://ultronpro.nutef.com'


def _http_json(method: str, url: str, payload: dict | None = None, timeout: int = 60) -> dict:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode('utf-8')
        headers['Content-Type'] = 'application/json'
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode('utf-8', 'ignore')
    return json.loads(raw) if raw else {}


def _find_control_container() -> str:
    cmd = "docker ps --format '{{.Names}}' | grep -E '^ultronpro_ultronpro\\.1\\.' | head -n1"
    out = subprocess.check_output(cmd, shell=True, text=True).strip()
    if not out:
        raise RuntimeError('control container not found')
    return out


def _list_trace_files(container: str, trace_dir: str) -> list[str]:
    py = (
        "import glob, json;"
        f"arr=sorted(glob.glob('{trace_dir.rstrip('/') }/*.jsonl'));"
        "print(json.dumps(arr))"
    )
    cmd = f"docker exec {container} python3 -c \"{py}\""
    out = subprocess.check_output(cmd, shell=True, text=True).strip()
    return list(json.loads(out or '[]'))


def _iter_inputs_from_file(container: str, path: str) -> Iterable[str]:
    py = (
        "import json,sys;"
        f"p='{path}';"
        "f=open(p,encoding='utf-8',errors='ignore');"
        "\nfor ln in f:\n"
        " ln=ln.strip()\n"
        " if not ln: continue\n"
        " try:\n"
        "  o=json.loads(ln)\n"
        " except Exception:\n"
        "  continue\n"
        " q=str(o.get('input') or '').strip()\n"
        " if q: print(q)"
    )
    cmd = f"docker exec {container} python3 -c \"{py}\""
    p = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert p.stdout is not None
    for line in p.stdout:
        q = line.strip()
        if q:
            yield q
    p.wait(timeout=120)


def main():
    ap = argparse.ArgumentParser(description='Replay decision traces into /api/metacognition/ask to populate PRM-lite.')
    ap.add_argument('--base', default=DEFAULT_BASE)
    ap.add_argument('--trace-dir', default='/app/data/decision_traces')
    ap.add_argument('--limit', type=int, default=500)
    ap.add_argument('--sleep-ms', type=int, default=40)
    ap.add_argument('--no-dedupe', action='store_true')
    args = ap.parse_args()

    before = _http_json('GET', args.base.rstrip('/') + '/api/prm/status')

    container = _find_control_container()
    files = _list_trace_files(container, args.trace_dir)
    if not files:
        print(json.dumps({'ok': False, 'error': 'no_trace_files'}))
        return

    sent = 0
    ok = 0
    err = 0
    seen = set()
    started = time.time()

    for fp in files:
        for q in _iter_inputs_from_file(container, fp):
            if sent >= max(1, int(args.limit)):
                break
            h = hashlib.md5(q.strip().lower().encode('utf-8', errors='ignore')).hexdigest()
            if (not args.no_dedupe) and h in seen:
                continue
            seen.add(h)
            sent += 1
            try:
                out = _http_json('POST', args.base.rstrip('/') + '/api/metacognition/ask', {'message': q}, timeout=90)
                if bool(out.get('ok')):
                    ok += 1
                else:
                    err += 1
            except Exception:
                err += 1
            if args.sleep_ms > 0:
                time.sleep(max(0.0, args.sleep_ms / 1000.0))
        if sent >= max(1, int(args.limit)):
            break

    after = _http_json('GET', args.base.rstrip('/') + '/api/prm/status')

    print(json.dumps({
        'ok': True,
        'container': container,
        'files': len(files),
        'sent': sent,
        'ok_calls': ok,
        'errors': err,
        'elapsed_sec': round(time.time() - started, 2),
        'prm_before': {
            'count': ((before.get('stats') or {}).get('count')),
            'avg_score': ((before.get('stats') or {}).get('avg_score')),
        },
        'prm_after': {
            'count': ((after.get('stats') or {}).get('count')),
            'avg_score': ((after.get('stats') or {}).get('avg_score')),
        },
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
