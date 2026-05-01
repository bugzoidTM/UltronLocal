from typing import List, Tuple, Any
import numpy as np
from scipy.ndimage import label, binary_erosion, binary_fill_holes
from scipy.stats import mode

class ARCExecutor:
    """Functional executor for ARC-style grid transformations."""
    
    @staticmethod
    def to_grid(data: Any) -> np.ndarray:
        if isinstance(data, str):
            import json
            data = json.loads(data)
        return np.array(data)

    @staticmethod
    def from_grid(grid: np.ndarray) -> List[List[int]]:
        return grid.tolist()

    # --- Primitives ---

    @staticmethod
    def rotate_90_cw(grid: np.ndarray) -> np.ndarray:
        return np.rot90(grid, k=-1)

    @staticmethod
    def reflect_vertical(grid: np.ndarray) -> np.ndarray:
        return np.flipud(grid)

    @staticmethod
    def reflect_horizontal(grid: np.ndarray) -> np.ndarray:
        return np.fliplr(grid)

    @staticmethod
    def crop_to_content(grid: np.ndarray) -> np.ndarray:
        """Crops the grid to the bounding box of non-zero pixels."""
        coords = np.argwhere(grid > 0)
        if coords.size == 0:
            return grid
        x0, y0 = coords.min(axis=0)
        x1, y1 = coords.max(axis=0) + 1
        return grid[x0:x1, y0:y1]

    @staticmethod
    def scale(grid: np.ndarray, factor: int) -> np.ndarray:
        return np.repeat(np.repeat(grid, factor, axis=0), factor, axis=1)

    @staticmethod
    def fill_color(grid: np.ndarray, target_color: int, replacement_color: int) -> np.ndarray:
        new_grid = grid.copy()
        new_grid[new_grid == target_color] = replacement_color
        return new_grid

    @staticmethod
    def invert_colors(grid: np.ndarray) -> np.ndarray:
        """Simple inversion: non-zero becomes 0, 0 becomes 1."""
        max_c = np.max(grid) if np.max(grid) > 0 else 1
        new_grid = np.zeros_like(grid)
        new_grid[grid == 0] = max_c
        return new_grid

    @staticmethod
    def extract_border(grid: np.ndarray) -> np.ndarray:
        """Keeps only the outermost non-zero pixels."""
        mask = grid > 0
        eroded = binary_erosion(mask)
        border_mask = mask & ~eroded
        return np.where(border_mask, grid, 0)

    @staticmethod
    def remove_background(grid: np.ndarray) -> np.ndarray:
        """Finds the most frequent color and sets it to 0."""
        m = mode(grid, axis=None).mode
        new_grid = grid.copy()
        new_grid[new_grid == m] = 0
        return new_grid

    @staticmethod
    def segment_by_color(grid: np.ndarray, connectivity: int = 4) -> List[dict]:
        """
        Segments the grid into distinct objects based on color and connectivity.
        Each object is a dictionary with metadata.
        """
        unique_colors = np.unique(grid)
        objects = []
        
        for color in unique_colors:
            if color == 0: continue # Skip background
            
            mask = (grid == color)
            labeled, num_features = label(mask) # Connectivity is handled by structure
            
            for i in range(1, num_features + 1):
                obj_mask = (labeled == i)
                coords = np.argwhere(obj_mask)
                if coords.size == 0: continue
                
                x0, y0 = coords.min(axis=0)
                x1, y1 = coords.max(axis=0) + 1
                
                # Extract relative mask within bbox
                rel_mask = obj_mask[x0:x1, y0:y1]
                
                objects.append({
                    "color": int(color),
                    "bbox": (int(x0), int(y0), int(x1), int(y1)),
                    "mask": rel_mask.tolist(),
                    "size": int(np.sum(obj_mask)),
                    "centroid": (float(np.mean(coords[:, 0])), float(np.mean(coords[:, 1])))
                })
        return objects

    @staticmethod
    def gravity_until_collision(grid: np.ndarray, direction: str = "down", stop_colors: List[int] = None) -> np.ndarray:
        """
        Moves all non-zero pixels in the specified direction until they hit 
        an edge or a pixel of a color in stop_colors (default: any non-zero).
        """
        new_grid = np.zeros_like(grid)
        rows, cols = grid.shape
        stop_colors = set(stop_colors) if stop_colors else set()

        if direction == "down":
            for c in range(cols):
                pixels = []
                for r in range(rows):
                    if grid[r, c] > 0:
                        pixels.append((r, grid[r, c]))
                
                # Reverse to process from bottom
                for r_orig, color in reversed(pixels):
                    curr_r = r_orig
                    while curr_r + 1 < rows:
                        next_val = grid[curr_r + 1, c]
                        if not stop_colors:
                            if next_val > 0: break
                        else:
                            if next_val in stop_colors: break
                        curr_r += 1
                    new_grid[curr_r, c] = color
        
        elif direction == "up":
            for c in range(cols):
                pixels = []
                for r in range(rows):
                    if grid[r, c] > 0:
                        pixels.append((r, grid[r, c]))
                
                for r_orig, color in pixels:
                    curr_r = r_orig
                    while curr_r - 1 >= 0:
                        next_val = grid[curr_r - 1, c]
                        if not stop_colors:
                            if next_val > 0: break
                        else:
                            if next_val in stop_colors: break
                        curr_r -= 1
                    new_grid[curr_r, c] = color
                    
        return new_grid

    @staticmethod
    def detect_grid_lines(grid: np.ndarray) -> dict:
        """Identifies full rows or columns of a single color (separators)."""
        rows, cols = grid.shape
        grid_rows = []
        grid_cols = []
        for r in range(rows):
            if np.all(grid[r, :] == grid[r, 0]) and grid[r, 0] > 0:
                grid_rows.append({"index": r, "color": int(grid[r, 0])})
        for c in range(cols):
            if np.all(grid[:, c] == grid[0, c]) and grid[0, c] > 0:
                grid_cols.append({"index": c, "color": int(grid[0, c])})
        return {"rows": grid_rows, "cols": grid_cols}

    @staticmethod
    def spread_color_from_seed(grid: np.ndarray, seed_color: int, target_color: int) -> np.ndarray:
        """Propagates target_color to all non-zero pixels connected to pixels of seed_color."""
        from collections import deque
        new_grid = grid.copy()
        rows, cols = grid.shape
        seeds = np.argwhere(grid == seed_color)
        if seeds.size == 0: return grid
        
        q = deque([tuple(s) for s in seeds])
        visited = set([tuple(s) for s in seeds])
        
        while q:
            r, c = q.popleft()
            new_grid[r, c] = target_color
            for dr, dc in [(0,1), (0,-1), (1,0), (-1,0)]:
                nr, nc = r+dr, c+dc
                if 0 <= nr < rows and 0 <= nc < cols and (nr, nc) not in visited:
                    # Propagate to any non-zero pixel or specific mask?
                    # ARC tasks usually propagate to ANY non-zero pixel of the original grid 
                    # that represents the 'path'.
                    if grid[nr, nc] > 0:
                        visited.add((nr, nc))
                        q.append((nr, nc))
        return new_grid

    @staticmethod
    def label_objects(grid: np.ndarray) -> np.ndarray:
        """Labels connected components with unique colors (1, 2, 3...)."""
        mask = grid > 0
        labeled, num_features = label(mask)
        return labeled.astype(int)

    @staticmethod
    def fractal_expand(grid: np.ndarray) -> np.ndarray:
        """Replaces each non-zero pixel with the original grid pattern."""
        rows, cols = grid.shape
        if rows * rows > 1000 or cols * cols > 1000:
            return grid
        new_grid = np.zeros((rows*rows, cols*cols), dtype=int)
        for r in range(rows):
            for c in range(cols):
                if grid[r, c] > 0:
                    new_grid[r*rows:(r+1)*rows, c*cols:(c+1)*cols] = grid
        return new_grid

    @staticmethod
    def gravity_down(grid: np.ndarray) -> np.ndarray:
        """Shifts all non-zero pixels to the bottom of their respective columns."""
        new_grid = np.zeros_like(grid)
        rows, cols = grid.shape
        for c in range(cols):
            # Get non-zero pixels in this column
            col_data = grid[:, c]
            non_zeros = col_data[col_data > 0]
            # Place them at the bottom
            new_grid[rows - len(non_zeros):, c] = non_zeros
        return new_grid

    @staticmethod
    def fill_holes(grid: np.ndarray) -> np.ndarray:
        """Fills enclosed 0-pixel holes with the most frequent non-zero color."""
        mask = grid > 0
        filled_mask = binary_fill_holes(mask)
        holes = filled_mask & ~mask
        if not np.any(holes):
            return grid
        # Get background color to fill (mode)
        m = mode(grid[grid > 0], axis=None).mode
        new_grid = grid.copy()
        new_grid[holes] = m
        return new_grid

    @staticmethod
    def keep_max_color(grid: np.ndarray) -> np.ndarray:
        """Keeps only pixels of the color that appears most frequently (non-zero)."""
        counts = np.bincount(grid.flatten())
        if len(counts) <= 1: return grid
        # Ignore color 0
        counts[0] = 0
        max_c = np.argmax(counts)
        new_grid = np.zeros_like(grid)
        new_grid[grid == max_c] = max_c
        return new_grid

    @staticmethod
    def map_to_objects(grid: np.ndarray, primitive_name: str) -> np.ndarray:
        """Segments grid into blobs and applies primitive to each one individually."""
        mask = grid > 0
        labeled, num_features = label(mask)
        new_grid = np.zeros_like(grid)
        
        for i in range(1, num_features + 1):
            obj_mask = (labeled == i)
            coords = np.argwhere(obj_mask)
            x0, y0 = coords.min(axis=0)
            x1, y1 = coords.max(axis=0) + 1
            
            # Extract patch
            patch = grid[x0:x1, y0:y1].copy()
            # Set pixels not in THIS object to 0 (to isolate it)
            patch_mask = obj_mask[x0:x1, y0:y1]
            patch[~patch_mask] = 0
            
            # Apply primitive to patch
            transformed_patch = ARCExecutor._apply_single_primitive(patch, primitive_name)
            
            # Reconstruct (centering logic or absolute placement)
            # For ARC, we usually place it back in the same bbox
            # If size changed (e.g. scale), we might need an offset
            th, tw = transformed_patch.shape
            # Ensure it fits
            rh = min(th, grid.shape[0] - x0)
            rw = min(tw, grid.shape[1] - y0)
            new_grid[x0:x0+rh, y0:y0+rw] += transformed_patch[:rh, :rw]
            
        return new_grid

    @staticmethod
    def map_to_quadrants(grid: np.ndarray, primitive_name: str) -> np.ndarray:
        """Splits grid by the most common 'line' color (separators) and transforms each part."""
        # Find separator color (must be a full line or column)
        rows, cols = grid.shape
        sep_color = -1
        sep_rows = [r for r in range(rows) if np.all(grid[r, :] == grid[r, 0]) and grid[r,0] > 0]
        sep_cols = [c for c in range(cols) if np.all(grid[:, c] == grid[0, c]) and grid[0,c] > 0]
        
        if not sep_rows and not sep_cols: return grid
        
        # Use first separator color found
        if sep_rows: sep_color = grid[sep_rows[0], 0]
        else: sep_color = grid[0, sep_cols[0]]
        
        new_grid = grid.copy()
        
        # This is a simplified quadrant split
        # We find blocks of 0s separated by the sep_color
        # For each block, we apply the primitive
        mask = grid != sep_color
        labeled, num_features = label(mask)
        
        for i in range(1, num_features + 1):
            quad_mask = (labeled == i)
            coords = np.argwhere(quad_mask)
            if coords.size == 0: continue
            x0, y0 = coords.min(axis=0)
            x1, y1 = coords.max(axis=0) + 1
            
            patch = grid[x0:x1, y0:y1]
            transformed = ARCExecutor._apply_single_primitive(patch, primitive_name)
            
            # Reconstruct
            th, tw = transformed.shape
            rh, rw = min(th, x1-x0), min(tw, y1-y0)
            new_grid[x0:x0+rh, y0:y0+rw] = transformed[:rh, :rw]
            
        return new_grid

    @staticmethod
    def _apply_single_primitive(grid: np.ndarray, name: str) -> np.ndarray:
        """Internal helper for selective application."""
        if name == "rotate_90": return ARCExecutor.rotate_90_cw(grid)
        if name == "reflect_v": return ARCExecutor.reflect_vertical(grid)
        if name == "reflect_h": return ARCExecutor.reflect_horizontal(grid)
        if name == "fill": return ARCExecutor.fill_holes(grid)
        if name == "keep_max": return ARCExecutor.keep_max_color(grid)
        if name == "invert": return ARCExecutor.invert_colors(grid)
        if name == "gravity": return ARCExecutor.gravity_down(grid)
        return grid

    @staticmethod
    def execute_plan(input_grid_data: Any, code_sequence: List[str]) -> List[List[int]]:
        """Executes a list of primitive calls."""
        grid = ARCExecutor.to_grid(input_grid_data)
        for step in code_sequence:
            try:
                # Meta-primitives
                if "obj_" in step:
                    prim = step.replace("obj_", "")
                    grid = ARCExecutor.map_to_objects(grid, prim)
                elif "quad_" in step:
                    prim = step.replace("quad_", "")
                    grid = ARCExecutor.map_to_quadrants(grid, prim)
                # Standard Global Primitives
                elif "rotate_90" in step: grid = ARCExecutor.rotate_90_cw(grid)
                elif "reflect_v" in step: grid = ARCExecutor.reflect_vertical(grid)
                elif "reflect_h" in step: grid = ARCExecutor.reflect_horizontal(grid)
                elif "crop" in step: grid = ARCExecutor.crop_to_content(grid)
                elif "scale_2" in step: grid = ARCExecutor.scale(grid, 2)
                elif "scale_3" in step: grid = ARCExecutor.scale(grid, 3)
                elif "invert" in step: grid = ARCExecutor.invert_colors(grid)
                elif "border" in step: grid = ARCExecutor.extract_border(grid)
                elif "remove" in step: grid = ARCExecutor.remove_background(grid)
                elif "label" in step: grid = ARCExecutor.label_objects(grid)
                elif "fractal" in step: grid = ARCExecutor.fractal_expand(grid)
                elif "gravity_v" in step: grid = ARCExecutor.gravity_until_collision(grid, "down")
                elif "gravity_up" in step: grid = ARCExecutor.gravity_until_collision(grid, "up")
                elif "gravity" in step: grid = ARCExecutor.gravity_down(grid)
                elif "fill" in step: grid = ARCExecutor.fill_holes(grid)
                elif "keep_max" in step: grid = ARCExecutor.keep_max_color(grid)
                elif "spread_" in step:
                    # Format: spread_seedColor_targetColor
                    parts = step.split("_")
                    if len(parts) == 3:
                        grid = ARCExecutor.spread_color_from_seed(grid, int(parts[1]), int(parts[2]))
            except Exception:
                continue
        return ARCExecutor.from_grid(grid)
