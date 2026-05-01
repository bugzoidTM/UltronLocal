import sys, os
from pathlib import Path
sys.path.insert(0, str(Path("f:/sistemas/UltronPro/backend").resolve()))
from ultronpro.llm import router
import json
strategies = {'gemini': 'default', 'groq': 'cheap', 'nvidia': 'creative'}
results = {}
for p, st in strategies.items():
    try:
        print(f"Checking {p} with strategy {st}...")
        res = router.complete("OK", strategy=st, cloud_fallback=False, max_tokens=10)
        results[p] = res or "EMPTY/TIMEOUT"
    except Exception as e:
        results[p] = f"ERROR: {e}"

with open("f:/sistemas/UltronPro/backend/data/provider_health.json", "w") as f:
    import json
    json.dump(results, f, indent=2)
print("Health check done.")
