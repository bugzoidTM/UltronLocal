import sys, os
sys.path.insert(0, os.path.abspath("."))
from ultronpro import external_benchmarks as eb
import json

print("=== Freezing new baseline (60 items, symbolic, v2) ===")
b = eb.freeze_baseline(strategy="non_llm", predictor="symbolic")
print(f"ok:           {b.get('ok')}")
print(f"total:        {b.get('total')}")
print(f"accuracy:     {b.get('overall_accuracy'):.1%}")
print(f"tier:         {b.get('comparability_tier')}")
print(f"officiality:  {b.get('officiality')}")
print()
print("By family:")
for fam, v in sorted((b.get('by_family') or {}).items()):
    print(f"  {fam:<30} {v['correct']}/{v['total']}  ({v['accuracy']:.0%})")
print()
print("=== Suite Audit ===")
audit = eb.suite_audit()
print(f"count:        {audit.get('count')}")
print(f"ok:           {audit.get('ok')}")
print(f"tier:         {audit.get('comparability_tier')}")
