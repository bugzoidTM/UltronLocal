import json
import os

filepath = "data/online_rl_runs.jsonl"
if not os.path.exists(filepath):
    print("No log file found")
else:
    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.readlines()
    for l in lines[-4:]:
        try:
            run = json.loads(l)
            sel = run.get("selection", {}).get("selected", {})
            kind = sel.get("kind")
            ok = run.get("ok")
            updates = run.get("policy_updates", {})
            print(f"{kind} ok={ok} rl={updates.get('rl_policy')} drive={updates.get('intrinsic_drive')}")
        except Exception as e:
            print("Error parsing line:", e)
