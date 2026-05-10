from ultronpro import intrinsic_utility
import json

print("Ticking utility...")
res = intrinsic_utility.tick()
print("Utility tick:", json.dumps(res, indent=2)[:300])

print("\nStatus:")
st = intrinsic_utility.status()
for d in st.get("drives", []):
    print(f"  {d['drive']}: satisfaction={d['satisfaction']:.3f} gap={d['gap']:.3f} obs={d['observed']:.3f} des={d['desired']:.3f}")
