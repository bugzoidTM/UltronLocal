import os
import sys
from pathlib import Path

# Add backend to path and set env vars
BACKEND_DIR = Path(__file__).resolve().parent
sys.path.append(str(BACKEND_DIR))
os.environ['ULTRONPRO_DB_PATH'] = str(BACKEND_DIR / 'data' / 'ultron.db')
os.environ['ULTRON_PRIMARY_LOCAL_PROVIDER'] = 'llama_cpp'

from ultronpro import llm

def test_local():
    print("Testing llama_cpp provider...")
    try:
        ans = llm.complete("Say 'YES' if you can hear me.", strategy="ollama_gemma", max_tokens=10)
        print(f"Response: '{ans}'")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_local()
