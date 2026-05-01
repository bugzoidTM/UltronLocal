import sys
from pathlib import Path
sys.path.append(str(Path.cwd()))
from ultronpro import llm_adapter
import json

print("Quarantine Status:")
print(json.dumps(llm_adapter.quarantine_status(), indent=2))
