from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from ultronpro import cognitive_patches, benchmark_suite

CORRELATION_LOG_PATH = Path(__file__).resolve().parent.parent / 'data' / 'benchmark_correlations.jsonl'


def _now() -> int:
    return int(time.time())


def _ensure_parent(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)


def measure_patch_external_correlation() -> dict[str, Any]:
    """
    Mede a correlacao entre:
    1. O delta predito pelo benchmark do patch (shadow_eval)
    2. O delta medido no benchmark geral/externo (benchmark_suite)
    """
    patches = cognitive_patches.list_patches(status='promoted')
    
    # Run the external benchmark suite to get current external delta
    external_run = benchmark_suite.run_suite()
    external_delta = float(external_run.get('delta', 0.0))
    external_cases = external_run.get('cases', [])
    
    # We will correlate the domain deltas
    domain_external_deltas = {}
    for dom, dom_data in external_run.get('domain_report', {}).items():
        domain_external_deltas[dom] = float(dom_data.get('delta', 0.0))
        
    matches = 0
    mismatches = 0
    patch_reports = []
    
    for p in patches:
        shadow_metrics = p.get('shadow_metrics') or {}
        patch_delta = float(shadow_metrics.get('delta') or 0.0)
        
        domain_regression = p.get('domain_regression') or {}
        
        # Check alignment at global level
        global_alignment = (patch_delta > 0 and external_delta > 0) or (patch_delta <= 0 and external_delta <= 0)
        
        # Check alignment at domain level
        domain_matches = 0
        domain_mismatches = 0
        for dom, dom_metrics in domain_regression.items():
            pd = float(dom_metrics.get('delta') or 0.0)
            ed = domain_external_deltas.get(dom, 0.0)
            
            if (pd > 0 and ed > 0) or (pd <= 0 and ed <= 0):
                domain_matches += 1
            else:
                domain_mismatches += 1
                
        if global_alignment:
            matches += 1
        else:
            mismatches += 1
            
        patch_reports.append({
            'patch_id': p['id'],
            'patch_global_delta': patch_delta,
            'external_global_delta': external_delta,
            'global_aligned': global_alignment,
            'domain_matches': domain_matches,
            'domain_mismatches': domain_mismatches
        })
        
    total_evals = matches + mismatches
    correlation_score = (matches / total_evals) if total_evals > 0 else 1.0
    
    report = {
        'ts': _now(),
        'total_analyzed_patches': len(patch_reports),
        'correlation_score': round(correlation_score, 4),
        'patches': patch_reports
    }
    
    _ensure_parent(CORRELATION_LOG_PATH)
    with CORRELATION_LOG_PATH.open('a', encoding='utf-8') as f:
        f.write(json.dumps(report, ensure_ascii=False) + '\n')
        
    return report

def run_selftest() -> dict[str, Any]:
    return measure_patch_external_correlation()

if __name__ == '__main__':
    print("Testing Patch <-> External Benchmark Correlation:")
    res = measure_patch_external_correlation()
    print(json.dumps(res, indent=2))
