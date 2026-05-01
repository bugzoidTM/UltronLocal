import sys
from pathlib import Path
sys.path.append(str(Path.cwd()))
from ultronpro import llm

router = llm.router
print("Usage Status:")
import json
print(json.dumps(router.usage_status(), indent=2))

print("\nCircuit Breaker Status:")
print(json.dumps(router.get_circuit_breaker_status(), indent=2))

print("\nLast Call Meta:")
print(json.dumps(router.last_call_meta, indent=2))
