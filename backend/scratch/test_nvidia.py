import sys
from pathlib import Path
sys.path.append(str(Path.cwd()))
from ultronpro import llm

print("Testing Nvidia provider...")
try:
    c = llm.router._get_client("nvidia")
    if not c:
        print("Nvidia client not initialized")
    else:
        resp = llm.router._call_openai_compat(c, "meta/llama-3.1-8b-instruct", "Respond concisely: Are you working?", None, False, provider="nvidia")
        print(f"Response: {resp}")
except Exception as e:
    print(f"Error: {e}")
