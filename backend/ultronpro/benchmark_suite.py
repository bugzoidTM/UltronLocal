from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path
from typing import Any

from ultronpro import quality_eval

SUITE_PATH = Path(__file__).resolve().parent / 'benchmarks' / 'domain_suite_v1.json'
BASELINE_PATH = Path(__file__).resolve().parent.parent / 'data' / 'benchmark_baselines/domain_suite_v1_baseline.json'
RUNS_PATH = Path(__file__).resolve().parent.parent / 'data' / 'benchmark_runs/domain_suite_v1_runs.jsonl'


def _now() -> int:
    return int(time.time())


def _ensure_parent(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)


def _load_suite(path: Path | None = None) -> dict[str, Any]:
    p = path or SUITE_PATH
    return json.loads(Path(p).read_text(encoding='utf-8'))


def _score(query: str, answer: str, *, fallback_needed: bool = False, has_rag: bool = False) -> dict[str, Any]:
    ctx = {
        'fallback': {'needed': fallback_needed},
        'selected_contexts': ([{'source': 'rag', 'items': [{'id': 'doc1'}]}] if has_rag else []),
        'excluded_contexts': [],
        'rag_diversity': ({'coverage_score': 0.72, 'source_diversity': 0.68, 'redundancy_score': 0.18} if has_rag else {}),
    }
    return quality_eval.evaluate_response(query=query, answer=answer, context_meta=ctx, tool_outputs=[])


def run_suite(path: Path | None = None) -> dict[str, Any]:
    suite = _load_suite(path)
    per_domain: dict[str, dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []
    for case in suite.get('cases') or []:
        domain = str(case.get('domain') or 'general')
        query = str(case.get('query') or '')
        baseline_eval = _score(query, str(case.get('baseline_answer') or ''), fallback_needed=bool(case.get('fallback_needed')), has_rag=bool(case.get('has_rag')))
        candidate_eval = _score(query, str(case.get('candidate_answer') or ''), fallback_needed=bool(case.get('fallback_needed')), has_rag=bool(case.get('has_rag')))
        b = float(baseline_eval.get('composite_score') or 0.0)
        c = float(candidate_eval.get('composite_score') or 0.0)
        row = {
            'case_id': str(case.get('case_id') or ''),
            'domain': domain,
            'baseline_score': round(b, 4),
            'candidate_score': round(c, 4),
            'delta': round(c - b, 4),
            'baseline_alerts': baseline_eval.get('alerts') or [],
            'candidate_alerts': candidate_eval.get('alerts') or [],
        }
        rows.append(row)
        item = per_domain.setdefault(domain, {'cases': 0, 'baseline_sum': 0.0, 'candidate_sum': 0.0, 'improved': 0, 'regressed': 0})
        item['cases'] += 1
        item['baseline_sum'] += b
        item['candidate_sum'] += c
        if c > b:
            item['improved'] += 1
        elif c < b:
            item['regressed'] += 1
    domain_report: dict[str, Any] = {}
    baseline_total = 0.0
    candidate_total = 0.0
    total_cases = 0
    for domain, item in per_domain.items():
        cases = max(1, int(item['cases']))
        baseline_avg = round(float(item['baseline_sum']) / cases, 4)
        candidate_avg = round(float(item['candidate_sum']) / cases, 4)
        domain_report[domain] = {
            'cases': cases,
            'baseline_avg': baseline_avg,
            'candidate_avg': candidate_avg,
            'delta': round(candidate_avg - baseline_avg, 4),
            'improved': int(item['improved']),
            'regressed': int(item['regressed']),
        }
        baseline_total += float(item['baseline_sum'])
        candidate_total += float(item['candidate_sum'])
        total_cases += cases
    result = {
        'ok': True,
        'suite': suite.get('suite') or 'domain_suite_v1',
        'version': suite.get('version') or 1,
        'ts': _now(),
        'total_cases': total_cases,
        'baseline_avg': round(baseline_total / max(1, total_cases), 4),
        'candidate_avg': round(candidate_total / max(1, total_cases), 4),
        'delta': round((candidate_total - baseline_total) / max(1, total_cases), 4),
        'domain_report': domain_report,
        'cases': rows,
    }
    _ensure_parent(RUNS_PATH)
    with RUNS_PATH.open('a', encoding='utf-8') as f:
        f.write(json.dumps(result, ensure_ascii=False) + '\n')
    return result


def freeze_baseline(path: Path | None = None) -> dict[str, Any]:
    suite = _load_suite(path)
    baseline: dict[str, Any] = {
        'suite': suite.get('suite') or 'domain_suite_v1',
        'version': suite.get('version') or 1,
        'ts': _now(),
        'domains': {},
    }
    domain_cases: dict[str, list[float]] = {}
    for case in suite.get('cases') or []:
        domain = str(case.get('domain') or 'general')
        query = str(case.get('query') or '')
        ev = _score(query, str(case.get('baseline_answer') or ''), fallback_needed=bool(case.get('fallback_needed')), has_rag=bool(case.get('has_rag')))
        domain_cases.setdefault(domain, []).append(float(ev.get('composite_score') or 0.0))
    for domain, values in domain_cases.items():
        baseline['domains'][domain] = {
            'cases': len(values),
            'baseline_avg': round(sum(values) / max(1, len(values)), 4),
        }
    _ensure_parent(BASELINE_PATH)
    BASELINE_PATH.write_text(json.dumps(baseline, ensure_ascii=False, indent=2), encoding='utf-8')
    return baseline


def run_selftest() -> dict[str, Any]:
    old_baseline = BASELINE_PATH
    old_runs = RUNS_PATH
    with tempfile.TemporaryDirectory(prefix='benchmark-suite-') as td:
        base = Path(td)
        globals()['BASELINE_PATH'] = base / 'baseline.json'
        globals()['RUNS_PATH'] = base / 'runs.jsonl'
        try:
            baseline = freeze_baseline()
            result = run_suite()
            return {
                'ok': True,
                'baseline': baseline,
                'result': result,
                'baseline_exists': BASELINE_PATH.exists(),
                'runs_exists': RUNS_PATH.exists(),
            }
        finally:
            globals()['BASELINE_PATH'] = old_baseline
            globals()['RUNS_PATH'] = old_runs
