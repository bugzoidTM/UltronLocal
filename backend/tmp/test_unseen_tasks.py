import sys, os
import json
from pathlib import Path
sys.path.insert(0, str(Path("f:/sistemas/UltronPro/backend").resolve()))

from ultronpro.visual_inductor import VisualInductor
from ultronpro.arc_executor import ARCExecutor

def test_unseen_tasks():
    print("=== Testing VisualInductor on Unseen ARC Tasks ===")
    
    tasks = ['0b148d64', '1f0c79e5', '2013d3e2', '3bdb4ada', '4093f84a']
    results = []

    for t_id in tasks:
        path = f"f:/sistemas/UltronPro/backend/data/novo_{t_id}.json"
        with open(path, 'r') as f:
            data = json.load(f)
        
        train_pairs = data['train']
        test_input = data['test'][0]['input']
        expected_output = data['test'][0]['output']
        
        print(f"\nProcessing Task {t_id}...")
        try:
            # RUN INDUCTOR (Zero API - max_depth 2 as implemented)
            seq = VisualInductor.infer_sequence(train_pairs, max_depth=2)
            
            if seq or seq == []:
                actual_output = ARCExecutor.execute_plan(test_input, seq)
                is_correct = actual_output == expected_output
                print(f"  Result: {'SOLVED' if is_correct else 'WRONG'} | Sequence: {seq}")
                results.append(is_correct)
            else:
                print(f"  Result: NO SEQUENCE FOUND")
                results.append(False)
        except Exception as e:
            import traceback
            print(f"  Result: ERROR ({e})")
            traceback.print_exc()
            results.append(False)

    score = sum(results)
    print(f"\n=== Final Score: {score}/{len(tasks)} ===")
    if score >= 2:
        print("VERDICT: GENERALIZATION CONFIRMED.")
    else:
        print("VERDICT: POOL-SPECIFIC CALIBRATION/OVERFITTING DETECTED.")

if __name__ == "__main__":
    test_unseen_tasks()
