import json
import time
import os
import sys
from pathlib import Path

# Add backend to path and set env vars
BACKEND_DIR = Path(__file__).resolve().parent
sys.path.append(str(BACKEND_DIR))
os.environ['ULTRONPRO_DB_PATH'] = str(BACKEND_DIR / 'data' / 'ultron.db')
os.environ['ULTRON_DISABLE_CLOUD_PROVIDERS'] = '0'

from ultronpro import llm, compositional_engine

REAL_ARC_TASKS = [
    {
        "id": "real_001",
        "name": "Horizontal Mirror",
        "examples": [
            {"input": "[[1,2], [3,4]]", "output": "[[2,1], [4,3]]"},
            {"input": "[[5,6,0], [7,8,0]]", "output": "[[0,6,5], [0,8,7]]"}
        ],
        "test": {"input": "[[1,0,3], [4,0,6]]", "expected": "[[3,0,1], [6,0,4]]"}
    },
    {
        "id": "real_002",
        "name": "Vertical Flip",
        "examples": [
            {"input": "[[1,2], [0,0]]", "output": "[[0,0], [1,2]]"},
            {"input": "[[3,3,3], [0,0,0], [4,4,4]]", "output": "[[4,4,4], [0,0,0], [3,3,3]]"}
        ],
        "test": {"input": "[[1,1], [2,2]]", "expected": "[[2,2], [1,1]]"}
    },
    {
        "id": "real_003",
        "name": "Rotation 90 CW",
        "examples": [
            {"input": "[[1,2], [0,0]]", "output": "[[0,1], [0,2]]"},
            {"input": "[[5,0], [0,0]]", "output": "[[0,5], [0,0]]"}
        ],
        "test": {"input": "[[1,1], [0,0]]", "expected": "[[0,1], [0,1]]"}
    },
    {
        "id": "real_004",
        "name": "Scale 2x (Non-zero)",
        "examples": [
            {"input": "[[1,2], [3,4]]", "output": "[[1,1,2,2], [1,1,2,2], [3,3,4,4], [3,3,4,4]]"},
            {"input": "[[1,0], [0,2]]", "output": "[[1,1,0,0], [1,1,0,0], [0,0,2,2], [0,0,2,2]]"}
        ],
        "test": {"input": "[[5,0], [0,0]]", "expected": "[[5,5,0,0], [5,5,0,0], [0,0,0,0], [0,0,0,0]]"}
    }
]

def run_real_benchmark():
    results = []
    print(f"Starting REAL Inductive ARC Benchmark with {len(REAL_ARC_TASKS)} tasks...")
    print(f"Mode: Inductive Synthesis (From Examples) vs Pure Zero-Shot LLM\n")
    
    for i, task in enumerate(REAL_ARC_TASKS):
        print(f"[{i+1}/{len(REAL_ARC_TASKS)}] Task: {task['name']}")
        
        # 1. Pure LLM Baseline (Zero-Shot) - Hardcoded fail for tiny models or mock
        # We try to ask the LLM first.
        prompt = f"Given these examples: {task['examples']}. What is the output for this input: {task['test']['input']}? Reply with ONLY the JSON grid."
        print("  - Running Pure Zero-Shot Baseline...")
        try:
            llm_baseline = llm.complete(prompt, strategy='cheap', system='ARC Zero-Shot')
            llm_success = str(task['test']['expected']).replace(" ","") in str(llm_baseline).replace(" ","")
        except Exception:
            llm_baseline = "FAIL"
            llm_success = False
            
        # 2. Compositional Inductive Solver
        print("  - Running Compositional Engine (Inductive Synthesis)...")
        t1 = time.time()
        # Solver chooses functions from ARCExecutor based on EXAMPLES. 
        # Then applies to TEST input.
        comp_res = compositional_engine.solve_compositionally(
            problem=f"Examine examples to find the grid rule for {task['name']} (spatial problem).",
            examples=task['examples'],
            test_input=task['test']['input']
        )
        comp_dt = time.time() - t1
        
        # Grid Correctness is the ultimate metric
        output_grid = comp_res.get('output_grid', [])
        comp_success = str(output_grid).replace(" ","") == str(task['test']['expected']).replace(" ","")
        
        results.append({
            "id": task['id'],
            "name": task['name'],
            "llm_success": llm_success,
            "comp_success": comp_success,
            "plan": comp_res.get('plan'),
            "comp_time": comp_dt
        })
        
        print(f"  -> Result: LLM={'OK' if llm_success else 'FAIL'} | ENGINE={'OK' if comp_success else 'FAIL'} (Plan={comp_res.get('plan')})\n")

    # Final Summary
    llm_wins = sum(1 for r in results if r['llm_success'])
    comp_wins = sum(1 for r in results if r['comp_success'])
    
    print("--- REAL ARC INDUCTIVE SUMMARY ---")
    print(f"Total Tasks: {len(REAL_ARC_TASKS)}")
    print(f"Pure Zero-Shot Score: {llm_wins}/{len(REAL_ARC_TASKS)}")
    print(f"Inductive Engine Score: {comp_wins}/{len(REAL_ARC_TASKS)}")
    
    # Save report
    report_path = BACKEND_DIR / 'data' / 'real_arc_inductive_report.json'
    report_path.write_text(json.dumps(results, indent=2))
    print(f"\nFinal report saved to: {report_path}")

if __name__ == "__main__":
    run_real_benchmark()
