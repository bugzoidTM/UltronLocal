import json
import time
import os
import sys
import urllib.request
from pathlib import Path

# Add backend to path and set env vars
BACKEND_DIR = Path(__file__).resolve().parent
sys.path.append(str(BACKEND_DIR))
os.environ['ULTRONPRO_DB_PATH'] = str(BACKEND_DIR / 'data' / 'ultron.db')

from ultronpro import compositional_engine

# 20 Tasks from ARC-AGI training set (Blind Selection)
TASK_POOL = [
    "00d62c1b", "017c7c7b", "025d127b", "045e512c", "0520fde7",
    "05269061", "05f2a901", "06df4c85", "08ed6ac7", "09629e4f",
    "0962bcdd", "0a938d79", "0b148d64", "0ca9ddb6", "0d3d703e",
    "0dfd9992", "0e206a2e", "10fcaaa3", "11852cab", "1190e5a7"
]

def fetch_task(task_id):
    url = f"https://raw.githubusercontent.com/fchollet/ARC-AGI/master/data/training/{task_id}.json"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as response:
            return json.loads(response.read().decode())
    except Exception:
        return None

def run_clean_benchmark():
    print(f"Starting CLEAN ARC-AGI Generalization Benchmark (Depth 2)...")
    print(f"Frozen Condition: NO code changes allowed.\n")
    
    results = []
    solved_count = 0
    total_tested = 0
    
    for i, tid in enumerate(TASK_POOL):
        if total_tested >= 20: break
        
        print(f"[{total_tested+1}/20] Task {tid}: Fetching...", end=" ", flush=True)
        task_data = fetch_task(tid)
        if not task_data:
            print("SKIP (404/Error)")
            continue
            
        total_tested += 1
        print("OK. Solving...", end=" ", flush=True)
        
        t0 = time.time()
        res = compositional_engine.solve_compositionally(
            problem=f"Clean Test {tid}",
            examples=task_data['train'],
            test_input=task_data['test'][0]['input']
        )
        dt = time.time() - t0
        
        output_grid = res.get('output_grid', [])
        expected_grid = task_data['test'][0]['output']
        success = str(output_grid).replace(" ","") == str(expected_grid).replace(" ","")
        
        if success: solved_count += 1
        
        results.append({
            "id": tid,
            "success": success,
            "plan": res.get('plan'),
            "time": dt
        })
        
        print(f"{'SUCCESS' if success else 'FAIL'} (Plan={res.get('plan')}, {dt:.3f}s)")

    print(f"\n--- CLEAN VALIDATION SUMMARY ---")
    print(f"Total Tested Tasks: {total_tested}")
    print(f"Score: {solved_count}/{total_tested} (Exact Match)")
    
    # Save final report
    report_path = BACKEND_DIR / 'data' / 'clean_arc_validation_report_final.json'
    report_path.write_text(json.dumps(results, indent=2))
    print(f"\nReport saved to: {report_path}")

if __name__ == "__main__":
    run_clean_benchmark()
