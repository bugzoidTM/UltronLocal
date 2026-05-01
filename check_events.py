import sys, io
sys.path.insert(0, 'backend')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
import sqlite3

conn = sqlite3.connect('backend/data/ultron.db')
c = conn.cursor()

# Find the actions table - look at events with kinds that represent executed actions
print("=== EVENTS kind distribution (top 20) ===")
rows = c.execute(
    "SELECT kind, COUNT(*) as n FROM events GROUP BY kind ORDER BY n DESC LIMIT 20"
).fetchall()
for r in rows:
    print(f"  {r[0]:40s} {r[1]}")

# Sample the action-related events
print("\n=== Sample events with action/execute kinds ===")
for kind in ['autonomy_action', 'action', 'tool_call', 'executor', 'autonomous_action',
             'mission', 'task', 'competency', 'tool']:
    row = c.execute(
        "SELECT id, created_at, kind, text FROM events WHERE kind=? LIMIT 1", (kind,)
    ).fetchone()
    if row:
        print(f"\n  kind={row[2]}")
        print(f"  text={str(row[3])[:300]}")

# Look at episodic_audit.jsonl which may be the real episode store
print("\n=== episodic_audit.jsonl sample ===")
import json, pathlib
audit = pathlib.Path('backend/data/episodic_audit.jsonl')
lines = audit.read_text(encoding='utf-8', errors='replace').splitlines()
print(f"  Total lines: {len(lines)}")
if lines:
    for ln in lines[-3:]:
        try:
            d = json.loads(ln)
            print(f"  keys: {list(d.keys())}")
            print(f"  domain: {d.get('domain')} | action: {d.get('action','')[:60]} | outcome: {d.get('outcome','')[:40]}")
        except Exception:
            pass
