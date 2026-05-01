import sys
from pathlib import Path
sys.path.append(str(Path.cwd()))
from ultronpro import llm

print("Testing GitHub provider...")
try:
    resp = llm.router.complete("Olá, você está funcionando?", strategy="lane_2_workhorse", cloud_fallback=True)
    print(f"Response: {resp}")
except Exception as e:
    print(f"Error: {e}")
