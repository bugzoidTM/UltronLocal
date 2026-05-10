import json

# Verify JSON file is valid and count items
with open("ultronpro/benchmarks/external_public_eval_v1.json", "r", encoding="utf-8") as f:
    d = json.load(f)

items = d.get("items", [])
print(f"Total items: {len(items)}")
print(f"Version: {d.get('version')}")
print(f"Comparability tier: {d.get('comparability_tier')}")

families = {}
benchmarks = {}
difficulties = {}
for i in items:
    fam = i.get("family", "?")
    bench = i.get("benchmark", "?")
    diff = i.get("difficulty", "?")
    families[fam] = families.get(fam, 0) + 1
    benchmarks[bench] = benchmarks.get(bench, 0) + 1
    difficulties[diff] = difficulties.get(diff, 0) + 1

print("\nFamilies:")
for k, v in sorted(families.items()):
    print(f"  {k}: {v}")

print("\nBenchmarks:")
for k, v in sorted(benchmarks.items()):
    print(f"  {k}: {v}")

print("\nDifficulties:")
for k, v in sorted(difficulties.items()):
    print(f"  {k}: {v}")
