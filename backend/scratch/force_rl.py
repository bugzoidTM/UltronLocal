import urllib.request, json, time

def post(p, b):
    d = json.dumps(b).encode()
    req = urllib.request.Request("http://localhost:8000" + p, data=d, headers={"Content-Type": "application/json"})
    r = urllib.request.urlopen(req, timeout=30)
    return json.loads(r.read())

print("Forcing RL to use new arms to register them in policy and drive up autonomy...")
for kind in ["autonomous_cognition_tick", "reflexion_tick"]:
    for _ in range(2):
        print(f"Running {kind}...")
        res = post(f"/api/rl/online/run?force_kind={kind}", {})
        print(f"  ok={res.get('ok')} reward={res.get('reward', {}).get('reward')}")
        time.sleep(1)

print("\nChecking RL Policy...")
r = urllib.request.urlopen("http://localhost:8000/api/rl/policy", timeout=10)
rl = json.loads(r.read())
for arm in rl.get("arms", []):
    print(f"  {arm['kind']} | {arm['context']}: mean={arm['mean']:.3f} alpha={arm['alpha']:.2f}")

print("\nChecking Utility Drives...")
r = urllib.request.urlopen("http://localhost:8000/api/utility/status", timeout=10)
ut = json.loads(r.read())
for d in ut.get("drives", []):
    print(f"  {d['drive']}: satisfaction={d['satisfaction']:.3f} gap={d['gap']:.3f}")
