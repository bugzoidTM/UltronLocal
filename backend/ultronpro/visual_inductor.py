import numpy as np
from typing import List, Dict, Tuple, Any
from ultronpro.arc_executor import ARCExecutor

class VisualInductor:
    """Infers symbolic transformation rules for ARC grids based on structural analysis."""

    @staticmethod
    def analyze_grid(grid: np.ndarray) -> Dict[str, Any]:
        """Extracts metadata from a single grid."""
        h, w = grid.shape
        unique_colors = np.unique(grid)
        color_counts = {int(c): int(np.sum(grid == c)) for c in unique_colors}
        non_zero_coords = np.argwhere(grid > 0)
        
        has_content = non_zero_coords.size > 0
        bbox = None
        if has_content:
            min_y, min_x = non_zero_coords.min(axis=0)
            max_y, max_x = non_zero_coords.max(axis=0)
            bbox = (int(min_y), int(min_x), int(max_y), int(max_x))

        return {
            "shape": (h, w),
            "colors": set(color_counts.keys()),
            "color_counts": color_counts,
            "has_content": has_content,
            "bbox": bbox,
            "total_pixels": h * w,
            "non_zero_count": int(np.sum(grid > 0))
        }

    @staticmethod
    def score_primitives(in_meta: Dict[str, Any], out_meta: Dict[str, Any]) -> List[Tuple[str, float]]:
        """Heuristic scoring of primitives based on input/output metadata differences."""
        scores = []
        h_in, w_in = in_meta["shape"]
        h_out, w_out = out_meta["shape"]

        # --- Pruning Heuristics ---
        shape_changed = (h_in != h_out or w_in != w_out)
        colors_changed = (in_meta["colors"] != out_meta["colors"])
        pixels_identical = (in_meta["non_zero_count"] == out_meta["non_zero_count"])
        
        # 1. Identity
        if not shape_changed and in_meta["color_counts"] == out_meta["color_counts"]:
            scores.append(("identity", 0.95))

        # 2. Scaling (Only if dimensions are multiples)
        if h_out == h_in * 2 and w_out == w_in * 2:
            scores.append(("scale_2", 1.0))
        if h_out == h_in * 3 and w_out == w_in * 3:
            scores.append(("scale_3", 1.0))

        # 3. Rotation/Reflection (Only if shape is preserved or swapped)
        if not shape_changed or (h_out == w_in and w_out == h_in):
            # Only if color histogram is identical
            if in_meta["color_counts"] == out_meta["color_counts"]:
                scores.append(("rotate_90", 0.8))
                scores.append(("reflect_v", 0.8))
                scores.append(("reflect_h", 0.8))

        # 4. Crop (Only if size decreases)
        if h_out < h_in or w_out < w_in:
            if out_meta["has_content"]:
                scores.append(("crop", 0.85))

        # 5. Global Inversion/Fill (Only if colors change)
        if colors_changed and not shape_changed:
            scores.append(("invert", 0.5))
            scores.append(("remove", 0.4))
            scores.append(("fill", 0.3))

        # 6. Objects & Gravity
        if not shape_changed:
            scores.append(("obj_fill", 0.2))
            scores.append(("gravity_v", 0.4))
            scores.append(("gravity_up", 0.3))
            scores.append(("gravity", 0.2))

        # 7. Color Spread (Relational Search)
        # Search specifically for colors that appear in out but not in in
        missing_in_out = out_meta["colors"] - in_meta["colors"]
        if missing_in_out and not shape_changed:
            for seed in in_meta["colors"]:
                for target in missing_in_out:
                    scores.append((f"spread_{seed}_{target}", 0.7))

        return sorted(scores, key=lambda x: x[1], reverse=True)

    @classmethod
    def infer_sequence(cls, train_pairs: List[Dict[str, Any]], max_depth: int = 3) -> List[str]:
        """Finds a sequence of primitives that works for all training pairs."""
        if not train_pairs:
            return []

        # Analyze first pair for initial heuristics
        p0 = train_pairs[0]
        in_grid = ARCExecutor.to_grid(p0["input"])
        out_grid = ARCExecutor.to_grid(p0["output"])
        
        in_meta = cls.analyze_grid(in_grid)
        out_meta = cls.analyze_grid(out_grid)
        
        scored = cls.score_primitives(in_meta, out_meta)
        candidate_primitives = [p[0] for p in scored if p[1] > 0.05]

        # Depth 1 Search
        for prim in candidate_primitives:
            if prim == "identity":
                if cls.validate_sequence([], train_pairs): return []
                continue
                
            if cls.validate_sequence([prim], train_pairs):
                return [prim]

        # Depth 2 Search
        if max_depth >= 2:
            for p1 in candidate_primitives:
                for p2 in candidate_primitives:
                    if p1 == p2: continue
                    if cls.validate_sequence([p1, p2], train_pairs):
                        return [p1, p2]

        # Depth 3 Search
        if max_depth >= 3:
            for p1 in candidate_primitives:
                for p2 in candidate_primitives:
                    for p3 in candidate_primitives:
                        # Avoid obvious redundancies (like rotate_90, rotate_90, rotate_90)
                        if p1 == p2 or p2 == p3: continue
                        if cls.validate_sequence([p1, p2, p3], train_pairs):
                            return [p1, p2, p3]

        return None

    @staticmethod
    def validate_sequence(sequence: List[str], train_pairs: List[Dict[str, Any]]) -> bool:
        """Checks if a sequence correctly transforms ALL training inputs to outputs."""
        for pair in train_pairs:
            input_grid = pair["input"]
            expected_output = pair["output"]
            
            try:
                actual_output = ARCExecutor.execute_plan(input_grid, sequence)
                if actual_output != expected_output:
                    return False
            except Exception:
                return False
        return True
