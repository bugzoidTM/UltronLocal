import sys
from pathlib import Path
sys.path.append(str(Path.cwd()))
from ultronpro import llm

print("Testing Keyless provider...")
try:
    # Keyless uses _call_keyless_free
    resp = llm.router._call_keyless_free("gpt-4o-mini", "Respond concisely: Are you working?", None, False)
    print(f"Response: {resp}")
except Exception as e:
    print(f"Error: {e}")
