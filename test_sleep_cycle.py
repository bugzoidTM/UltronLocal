import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, 'backend')

print("=== SLEEP CYCLE v2 - Final Validation ===\n")

from ultronpro.sleep_cycle import _load_recent_action_episodes, _group_episodes, MIN_GROUP_FOR_COMPILATION
from ultronpro.episodic_compiler import get_lifecycle_summary
import json

# Step 1: verify correct episode source
eps = _load_recent_action_episodes(hours=48)
print(f"[1] Action episodes loaded (last 48h): {len(eps)}")
if eps:
    print(f"    Sources: {set(e.get('source') for e in eps)}")
    print(f"    Sample keys: {list(eps[0].keys())}")
    print(f"    Sample: tool={eps[0].get('tool','?')} outcome={eps[0].get('outcome','?')} quality={eps[0].get('quality','?')}")

# Step 2: groups
groups = _group_episodes(eps)
print(f"\n[2] Groups formed: {len(groups)}")
compilable = [(k, v) for k, v in groups.items() if len(v) >= MIN_GROUP_FOR_COMPILATION]
print(f"    Compilable (>={MIN_GROUP_FOR_COMPILATION} eps): {len(compilable)}")
for k, v in sorted(compilable, key=lambda x: -len(x[1]))[:8]:
    print(f"      {k:55s} n={len(v)}")

# Step 3: run cycle
print("\n[3] Running sleep cycle...")
from ultronpro.sleep_cycle import run_cycle
result = run_cycle(retention_days=14, max_active_rows=3000)
print("\n    Result:")
for k, v in result.items():
    if k not in ('paths',):
        print(f"      {k}: {v}")

# Step 4: lifecycle
print("\n[4] Abstractions lifecycle:")
print(json.dumps(get_lifecycle_summary(), indent=4, ensure_ascii=False))
