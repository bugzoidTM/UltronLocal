import urllib.request, json, sys

def get(path):
    try:
        r = urllib.request.urlopen("http://localhost:8000" + path, timeout=10)
        return json.loads(r.read())
    except Exception as e:
        return {"_err": str(e)[:100]}

def post(path, body):
    try:
        data = json.dumps(body).encode()
        req = urllib.request.Request("http://localhost:8000" + path, data=data,
                                     headers={"Content-Type": "application/json"})
        r = urllib.request.urlopen(req, timeout=10)
        return json.loads(r.read())
    except Exception as e:
        return {"_err": str(e)[:100]}

sc = get("/api/roadmap/scorecard")
print("=== ROADMAP SCORES ===")
for f in sc.get("front_scores", []):
    print(f"  {f['score']}% | {f['title'][:50]}")
print(f"  overall: {sc.get('overall_percent')}%")

print("\n=== DRIVES (gap = quanto falta) ===")
ut = get("/api/utility/status")
for d in ut.get("drives", []):
    print(f"  {d['drive']:<12} gap={d['gap']:.3f}  satisfaction={d['satisfaction']:.3f}  weight={d['weight']:.3f}")
print(f"  utility total: {ut.get('utility'):.4f}")

print("\n=== RL POLICY (convergencia) ===")
rl = get("/api/rl/policy")
print(f"  global_updates={rl.get('global_updates')}  total_arms={rl.get('total_arms')}")
for arm in rl.get("arms", []):
    print(f"  {arm['kind']}|{arm['context']}: mean={arm['mean']:.3f} alpha={arm['alpha']:.2f} beta={arm['beta']:.2f}")

print("\n=== AUTONOMOUS COGNITION (ciclos vivos) ===")
ac = get("/api/autonomous/cognition/status")
m = ac.get("metrics", {})
print(f"  ticks={m.get('ticks')}  perceptions={m.get('perceptions')}  actions={m.get('actions_executed')}")
print(f"  consequences_learned={m.get('consequences_learned')}  surprise_events={m.get('surprise_events', 'N/A')}")

print("\n=== INTEGRATION PROXY (subscores) ===")
ip = get("/api/integration-proxy/status")
print(f"  score={ip.get('integration_proxy_score'):.4f}  level={ip.get('integration_level')}")
for k, v in ip.get("subscores", {}).items():
    print(f"  {k:<30} = {v:.4f}")

print("\n=== CAUSAL GRAPH ===")
cg = get("/api/causal-graph/status")
print(f"  nodes={cg.get('nodes')}  edges={cg.get('edges')}")
cm = get("/api/causal/model")
print(f"  causal/model nodes={cm.get('nodes')}  edges={cm.get('edges')}")

print("\n=== SELF MODEL ===")
sm = get("/api/self-model/status")
identity = sm.get("identity", {})
caps = sm.get("capabilities", sm.get("known_capabilities", {}))
print(f"  name={identity.get('name')}  trust_score={sm.get('self_trust_score', sm.get('trust_score', 'N/A'))}")
print(f"  capabilities keys: {list(caps.keys())[:8] if isinstance(caps, dict) else 'list'}")

print("\n=== EXTERNAL EVAL (ultimo run) ===")
eb = get("/api/evals/external/runs")
items = eb.get("items", [])
if items:
    last = items[0]
    print(f"  run_id={last.get('run_id')}  accuracy={last.get('overall_accuracy')}  predictor={last.get('predictor')}")
    print(f"  comparability={last.get('comparability_note', 'N/A')[:80]}")

print("\n=== HOMEOSTASIS ===")
hs = get("/api/homeostasis/status")
print(f"  mode={hs.get('mode')}  ok={hs.get('ok')}")
for k, v in hs.get("vitals", {}).items():
    print(f"  {k:<30} = {v:.4f}")

print("\n=== EPISTEMIC GAPS ===")
gaps = post("/api/plasticity/gap-detector/selftest", {})
print(json.dumps(gaps)[:600])
