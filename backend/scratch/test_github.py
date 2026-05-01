import sys
from pathlib import Path
sys.path.append(str(Path.cwd()))
from ultronpro import llm

print("Testing GitHub provider...")
try:
    c = llm.router._get_client("github")
    if not c:
        print("GitHub client not initialized (maybe disabled or key missing)")
    else:
        # We need to manually call _call_openai_compat since complete() uses high-level routing
        resp = llm.router._call_openai_compat(c, "gpt-4o-mini", "Respond concisely: Are you working?", None, False, provider="github")
        print(f"Response: {resp}")
except Exception as e:
    print(f"Error: {e}")
