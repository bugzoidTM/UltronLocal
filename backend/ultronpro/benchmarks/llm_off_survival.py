import os
import sys
import json
import time

# Set up paths for importing ultronpro
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

# Force LLM Off mode for this run
os.environ['ULTRON_DISABLE_CLOUD_PROVIDERS'] = '1'
os.environ['ULTRON_PRIMARY_LOCAL_PROVIDER'] = 'llama_cpp'

from ultronpro import llm

def run_survival_test():
    suite_path = os.path.join(os.path.dirname(__file__), "llm_off_suite.json")
    if not os.path.exists(suite_path):
        print(f"Error: Suite file not found at {suite_path}")
        return

    with open(suite_path, "r", encoding="utf-8") as f:
        suite = json.load(f)

    print(f"--- Running LLM-OFF Survival Benchmark v{suite.get('version', 1)} ---")
    
    results = []
    for case in suite.get("cases", []):
        cid = case.get("id")
        query = case.get("query")
        print(f"Testing Case {cid}: {query[:50]}...")
        
        start = time.time()
        try:
            # We use the 'ollama_gemma' strategy which we mapped to llama_cpp
            resp = llm.router.complete(query, strategy="ollama_gemma", max_tokens=256)
            latency = time.time() - start
            
            success = len(resp.strip()) > 10
            # Simple heuristic for coherence based on keywords if provided
            coherence = 1.0 if success else 0.0
            
            results.append({
                "id": cid,
                "resp": resp,
                "latency_sec": round(latency, 3),
                "success": success,
                "score": coherence
            })
            print(f"  [OK] Latency: {latency:.2f}s | Success: {success}")
        except Exception as e:
            print(f"  [FAIL] Error: {e}")
            results.append({
                "id": cid,
                "error": str(e),
                "success": False,
                "score": 0.0
            })

    total = len(results)
    passed = sum(1 for r in results if r['success'])
    avg_latency = sum(r.get('latency_sec', 0) for r in results) / max(1, len(results))
    
    report = {
        "suite": suite.get("suite"),
        "ts": int(time.time()),
        "survival_rate": round(passed / total, 2) if total > 0 else 0,
        "avg_latency": round(avg_latency, 3),
        "results": results
    }
    
    report_path = os.path.join(BACKEND_DIR, "data", "benchmark_llm_off.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    
    print(f"--- Benchmark Complete ---")
    print(f"Survival Rate: {report['survival_rate']*100}%")
    print(f"Avg Latency: {report['avg_latency']}s")
    print(f"Results saved to {report_path}")

if __name__ == "__main__":
    run_survival_test()
