import sys, os
import json
from pathlib import Path
sys.path.insert(0, str(Path("f:/sistemas/UltronPro/backend").resolve()))

from ultronpro.visual_inductor import VisualInductor
from ultronpro.arc_executor import ARCExecutor

def test_visual_induction():
    print("=== Testing Symbolic Visual Inductor (Zero API) ===")
    
    # Task 1: Mirror (blind_001)
    train_001 = [
        {"input": [[1,2], [0,0]], "output": [[2,1], [0,0]]},
        {"input": [[3,3,4], [0,0,0]], "output": [[4,3,3], [0,0,0]]}
    ]
    seq_001 = VisualInductor.infer_sequence(train_001)
    print(f"Task 001 Sequence: {seq_001}")
    assert "reflect_h" in seq_001 or "reflect_v" in seq_001 # Depends on grid coords
    
    # Task 2: Scaling (blind_012 in official dataset, let's mock it)
    train_scale = [
        {"input": [[1,1], [1,1]], "output": [[1,1,1,1], [1,1,1,1], [1,1,1,1], [1,1,1,1]]}
    ]
    seq_scale = VisualInductor.infer_sequence(train_scale)
    print(f"Task Scale Sequence: {seq_scale}")
    assert "scale_2" in seq_scale

    # Task 3: Composite (Scale + Reflect)
    train_comp = [
        {"input": [[1,0], [0,0]], "output": [[0,0,1,1], [0,0,1,1], [0,0,0,0], [0,0,0,0]]}
    ]
    # Input 2x2. Output 4x4. 
    # Scale 2x -> [[1,1,0,0], [1,1,0,0], [0,0,0,0], [0,0,0,0]]
    # Reflect H -> [[0,0,1,1], [0,0,1,1], [0,0,0,0], [0,0,0,0]]
    seq_comp = VisualInductor.infer_sequence(train_comp, max_depth=2)
    print(f"Task Composite Sequence: {seq_comp}")
    assert "scale_2" in seq_comp and "reflect_h" in seq_comp

    print("\n=== All induction tests passed! ===")

if __name__ == "__main__":
    test_visual_induction()
