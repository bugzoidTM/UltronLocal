"""Compositional Generalization Engine v3 (Symbolic Search).

Decomposes novel problems, searches a library of abstractions,
and can INDUCE rules from examples by systematic search over primitives.
"""
from __future__ import annotations

import itertools
import json
import re
import time
from pathlib import Path
from typing import Any, List, Optional
import numpy as np

try:
    from ultronpro.arc_executor import ARCExecutor
except ImportError:
    # Minimal mock if not found during import test
    class ARCExecutor:
        @staticmethod
        def execute_plan(input_grid, code_sequence): return input_grid

STATE_PATH = Path(__file__).resolve().parent.parent / 'data' / 'compositional_engine_state.json'

# --- Config ---
PRIMITIVES = [
    "rotate_90",
    "reflect_v",
    "reflect_h",
    "crop",
    "scale_2",
    "scale_3",
    "invert",
    "border",
    "label",
    "fractal",
    "gravity",
    "fill",
    "keep_max",
    "obj_rotate_90",
    "obj_reflect_v",
    "obj_reflect_h",
    "obj_fill",
    "obj_invert",
    "quad_rotate_90",
    "quad_reflect_v",
    "quad_reflect_h",
    "quad_fill",
    "quad_keep_max"
]

def search_induction(examples: List[dict], max_depth: int = 2) -> dict:
    """Systematically tries combinations of primitives to find rule."""
    if not examples:
        return {"ok": False, "error": "no_examples"}

    # Optimization: pre-parse example grids
    parsed_ex = []
    for ex in examples:
        parsed_ex.append({
            "in": str(ex['input']).replace(" ", ""),
            "out": str(ex['output']).replace(" ", "")
        })

    # Search space: empty, 1-step, 2-steps... 
    for depth in range(1, max_depth + 1):
        for combo in itertools.product(PRIMITIVES, repeat=depth):
            steps = list(combo)
            
            # Verify on all examples
            all_match = True
            for ex in examples:
                try:
                    res = ARCExecutor.execute_plan(ex['input'], steps)
                    res_str = str(res).replace(" ", "")
                    # Match check
                    match_case = parsed_ex[examples.index(ex)]
                    if res_str != match_case['out']:
                        all_match = False
                        break
                except Exception:
                    all_match = False
                    break
            
            if all_match:
                return {"ok": True, "steps": steps, "verdict": "synthesized_via_search"}

    return {"ok": False, "verdict": "not_found", "depth_searched": max_depth}

# --- Pipeline ---

def solve_compositionally(problem: str, examples: Optional[List[dict]] = None, test_input: Optional[Any] = None) -> dict[str, Any]:
    """Inductive search if examples present, else symbolic matching."""
    
    # ARC Inductive Mode
    if examples:
        print(f"[Engine] Starting Inductive Search (max_depth=2) for {len(examples)} examples...")
        result = search_induction(examples, max_depth=2)
        
        if result.get('ok') and test_input:
            final_grid = ARCExecutor.execute_plan(test_input, result['steps'])
            return {
                "ok": True,
                "output_grid": final_grid,
                "plan": result['steps'],
                "method": "inductive_search",
                "score": 1.0
            }
        
    return {
        "ok": False,
        "method": "compositional_fallback",
        "score": 0.0,
        "note": "Induction failed or no test input."
    }
