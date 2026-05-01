import json
import time
import os
import sys
from pathlib import Path

# Add backend to path and set env vars
BACKEND_DIR = Path(__file__).resolve().parent
sys.path.append(str(BACKEND_DIR))
os.environ['ULTRONPRO_DB_PATH'] = str(BACKEND_DIR / 'data' / 'ultron.db')

from ultronpro import compositional_engine

COMPOSITIONAL_TASKS = [
    {
        "id": "comp_001",
        "name": "Rotated Symmetry (Depth 2)",
        "description": "Rotate 90 CW AND THEN Reflect Horizontally.",
        "examples": [
            {"input": "[[1,0], [0,0]]", "output": "[[1,0], [0,0]]"},
            {"input": "[[1,2], [0,0]]", "output": "[[1,0], [2,0]]"}
        ],
        "test": {"input": "[[2,2], [0,0]]", "expected": "[[2,0], [2,0]]"}
    },
    {
        "id": "comp_002",
        "name": "Inverted Expansion (Depth 2)",
        "description": "Scale 2x AND THEN Invert Colors.",
        "examples": [
            {"input": "[[1,0], [0,0]]", "output": "[[0,0,1,1], [0,0,1,1], [1,1,1,1], [1,1,1,1]]"},
            {"input": "[[0,1], [0,0]]", "output": "[[1,1,0,0], [1,1,0,0], [1,1,1,1], [1,1,1,1]]"}
        ],
        "test": {"input": "[[0,0], [1,0]]", "expected": "[[1,1,1,1], [1,1,1,1], [0,0,1,1], [0,0,1,1]]"}
    },
    {
        "id": "comp_003",
        "name": "Border Rotation (Depth 2)",
        "description": "Extract Border AND THEN Rotate 90 CW.",
        "examples": [
            {"input": "[[1,1,1], [1,1,1], [1,1,1]]", "output": "[[1,1,1], [1,0,1], [1,1,1]]"},
            {"input": "[[2,2,0], [2,2,0], [0,0,0]]", "output": "[[0,2,2], [0,2,2], [0,0,0]]"}
        ],
        "test": {"input": "[[4,4], [4,4]]", "expected": "[[4,4], [4,4]]"}
    }
]

def run_comp_benchmark():
    print(f"Starting Compositional Depth Benchmark (Depth 2/3)...")
    results = []
    
    for i, task in enumerate(COMPOSITIONAL_TASKS):
        print(f"[{i+1}/{len(COMPOSITIONAL_TASKS)}] Task: {task['name']}")
        
        t0 = time.time()
        # Search depth 2 (as specified in engine.py v3)
        res = compositional_engine.solve_compositionally(
            problem=f"Compose rule for {task['name']}",
            examples=task['examples'],
            test_input=task['test']['input']
        )
        dt = time.time() - t0
        
        output_grid = res.get('output_grid', [])
        success = str(output_grid).replace(" ","") == str(task['test']['expected']).replace(" ","")
        
        results.append({
            "id": task['id'],
            "name": task['name'],
            "success": success,
            "plan": res.get('plan'),
            "time": dt
        })
        
        print(f"  -> Result: {'OK' if success else 'FAIL'} | Plan={res.get('plan')} ({dt:.3f}s)")

    # Summary
    wins = sum(1 for r in results if r['success'])
    print(f"\n--- DEPTH BENCHMARK SUMMARY ---")
    print(f"Score: {wins}/{len(COMPOSITIONAL_TASKS)}")
    
    if wins == len(COMPOSITIONAL_TASKS):
        print("\n[VERDICT] COMPOSITIONALITY VALIDATED: The engine successfully chains multiple primitives.")
    else:
        print("\n[VERDICT] PARTIAL SUCCESS: Check primitives or search depth.")

if __name__ == "__main__":
    run_comp_benchmark()
