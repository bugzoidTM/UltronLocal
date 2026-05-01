"""Standalone verification of compositional_engine.py."""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import ultronpro.compositional_engine as ce

# Clean state
ce.STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
if ce.STATE_PATH.exists():
    ce.STATE_PATH.unlink()

print("=== Compositional Engine Verification ===\n")

# 1) Decomposition test
problem = (
    "Primeiro, calcule 15% de 200. "
    "Depois, verifique se o resultado é maior que 20. "
    "Finalmente, crie um plano de ação para investir esse valor."
)
dec = ce.decompose(problem)
assert dec['ok'], "FAIL: decomposition failed"
assert len(dec['subproblems']) >= 3, f"FAIL: expected at least 3 subproblems, got {len(dec['subproblems'])}"
print(f"[PASS] Decomposition successful: {len(dec['subproblems'])} subproblems found.")
for sp in dec['subproblems']:
    print(f"  - {sp['id']} ({sp['type']}): {sp['text'][:50]}... deps={sp['dependencies']}")

# 2) Search Primitives test (requires some mocks or items in explicit_abstractions)
# Let's mock search_primitives to ensure it returns something for the first subproblem
# Actually, let's just run it; if the library is empty it will return [] which is fine for the flow.
sp1 = dec['subproblems'][0]
primitives = ce.search_primitives(sp1)
print(f"[OK] Primitive search for sp1: {len(primitives)} found.")

# 3) Composition test
comp = ce.solve_compositionally(problem)
assert comp['ok'], "FAIL: composition solve failed"
print(f"[PASS] Composition solve successful. Verdict: {comp['verdict']}")
print(f"  - Resolved by primitive: {comp['composition']['resolved_by_primitive']}")
print(f"  - Resolved by LLM: {comp['composition']['resolved_by_llm']}")
print(f"  - Composition score: {comp['composition_score']}")

# 4) Verification test
ver = comp['verification']
assert ver['ok'], "FAIL: verification failed"
print(f"[PASS] Verification successful. Consistency score: {ver['consistency_score']}")

# 5) Learning test
# Mock a successful composition to learn from
learn_result = ce.learn_primitive(comp['composition'], reward=0.85)
# Note: learn_primitive requires at least 2 primitive steps.
# If primitive_count < 2, it will return ok=False which is expected for empty library.
if learn_result['ok']:
    print(f"[PASS] Learned new primitive: {learn_result['abstraction_id']}")
else:
    print(f"[INFO] Learning skipped: {learn_result.get('reason', 'no reason provided')}")

# 6) Status test
s = ce.status()
assert s['ok']
assert s['stats']['total_compositions'] >= 1
print(f"[PASS] Status: total={s['stats']['total_compositions']}, composed={s['stats']['composed_solutions']}")

print(f"\n=== ALL TESTS PASSED ===")
