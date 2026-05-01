import os
import time
from ultronpro import llm

def test_local_gemma():
    print("Testing local Gemma via llama-server...")
    prompt = "Reply with 'Hello from Gemma' only."
    try:
        # Force llama_cpp strategy
        res = llm.router.complete(prompt, strategy="ollama_gemma", inject_persona=False)
        print(f"Response: {res}")
        if "Gemma" in res:
            print("SUCCESS: Local inference is working!")
        else:
            print("WARNING: Unexpected response, but communication was successful.")
    except Exception as e:
        print(f"FAILED: {e}")

if __name__ == "__main__":
    # Ensure current directory is backend
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    test_local_gemma()
