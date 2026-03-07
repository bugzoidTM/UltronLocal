#!/usr/bin/env python3
import json, random
from pathlib import Path

SRC = Path('/root/.openclaw/workspace/UltronPro/backend/data/finetune_dataset.jsonl')
OUT = Path('/root/.openclaw/workspace/UltronPro/backend/data/finetune_dataset_v_final_shuffled.jsonl')

TARGET = 700
MIX = {
    'conversation_ptbr': 0.50,
    'metacog_state_action': 0.35,
    'guardrail': 0.15,
}

rows = []
for ln in SRC.read_text(encoding='utf-8', errors='ignore').splitlines():
    if not ln.strip():
        continue
    try:
        rows.append(json.loads(ln))
    except Exception:
        pass

by = {'conversation_ptbr': [], 'metacog_state_action': [], 'guardrail': []}
for r in rows:
    tt = str(r.get('task_type') or '')
    if tt in by:
        by[tt].append(r)

# dedup by exact assistant content
for k in by:
    seen = set(); keep=[]
    for r in by[k]:
        msgs=r.get('messages') or []
        ans = str((msgs[-1].get('content') if msgs else '') or '').strip().lower()
        if not ans or ans in seen:
            continue
        seen.add(ans); keep.append(r)
    by[k]=keep

out=[]
for k,p in MIX.items():
    n = int(TARGET * p)
    pool = by[k]
    if not pool:
        continue
    if len(pool) >= n:
        out.extend(random.sample(pool, n))
    else:
        out.extend(pool)
        while len([x for x in out if x.get('task_type')==k]) < n:
            out.append(random.choice(pool))

random.shuffle(out)
OUT.write_text(''.join(json.dumps(r, ensure_ascii=False)+'\n' for r in out), encoding='utf-8')
print({'ok': True, 'out': str(OUT), 'rows': len(out), 'counts': {k: sum(1 for r in out if r.get('task_type')==k) for k in MIX}})
