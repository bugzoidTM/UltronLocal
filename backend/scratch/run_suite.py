import sys, os
sys.path.insert(0, os.path.abspath("."))
from ultronpro import external_benchmarks as eb
import json

print("Running full suite with symbolic predictor...")
result = eb.run_suite(predictor="symbolic", strategy="non_llm",
                      tag="gap2_expansion_v2_60items")

print(f"Items:    {result['total']}")
print(f"Correct:  {result['correct']}")
print(f"Accuracy: {result['overall_accuracy']:.1%}")
print(f"Tier:     {result['comparability_tier']}")
print()
print("By family:")
for fam, v in sorted(result.get("by_family", {}).items()):
    print(f"  {fam:<30} {v['correct']}/{v['total']}  ({v['accuracy']:.0%})")
print()
wrong = [r for r in result.get("items", []) if not r["correct"]]
print(f"Wrong ({len(wrong)}):")
for r in wrong:
    print(f"  [{r['benchmark']}] gold={r['gold_answer']} pred={r['predicted_answer']} raw={r['raw_response'][:60]}")
