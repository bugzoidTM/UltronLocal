from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path
from typing import Any

SUITE_PATH = Path(__file__).resolve().parent / 'benchmarks' / 'external_public_eval_v1.json'
RUNS_PATH = Path('/app/data/external_benchmarks/public_eval_runs.jsonl')
BASELINE_PATH = Path('/app/data/external_benchmarks/public_eval_baseline.json')

_BENCHMARK_FAMILIES = {
    'arc_easy_partial': 'science_qa',
    'hellaswag_partial': 'commonsense_next_step',
    'mmlu_partial': 'academic_mcq',
}

_BENCHMARK_LINEAGE = {
    'arc_easy_partial': 'ARC-Easy-inspired public subset',
    'hellaswag_partial': 'HellaSwag-inspired public subset',
    'mmlu_partial': 'MMLU-inspired public subset',
}


def _now() -> int:
    return int(time.time())


def _ensure_parent(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)


def _load_suite(path: Path | None = None) -> dict[str, Any]:
    p = path or SUITE_PATH
    return json.loads(Path(p).read_text(encoding='utf-8'))


def _annotate_item(item: dict[str, Any]) -> dict[str, Any]:
    bench = str(item.get('benchmark') or 'unknown')
    out = dict(item)
    out.setdefault('family', _BENCHMARK_FAMILIES.get(bench, 'unknown'))
    out.setdefault('lineage', _BENCHMARK_LINEAGE.get(bench, 'manual_public_subset'))
    out.setdefault('license_note', 'manual/publicly inspired subset; not official benchmark payload')
    out.setdefault('comparability_tier', 'proxy_subset')
    return out


def list_suite() -> dict[str, Any]:
    suite = _load_suite()
    items = [_annotate_item(x) for x in (suite.get('items') or []) if isinstance(x, dict)]
    by_benchmark: dict[str, int] = {}
    by_family: dict[str, int] = {}
    by_split: dict[str, int] = {}
    for item in items:
        key = str(item.get('benchmark') or 'unknown')
        fam = str(item.get('family') or 'unknown')
        spl = str(item.get('split') or 'dev')
        by_benchmark[key] = by_benchmark.get(key, 0) + 1
        by_family[fam] = by_family.get(fam, 0) + 1
        by_split[spl] = by_split.get(spl, 0) + 1
    return {
        'ok': True,
        'suite': suite.get('suite') or 'external_public_eval_v1',
        'version': suite.get('version') or 1,
        'benchmark_counts': by_benchmark,
        'family_counts': by_family,
        'split_counts': by_split,
        'count': len(items),
        'path': str(SUITE_PATH),
        'comparability_note': suite.get('comparability_note') or '',
        'comparability_tier': 'proxy_subset',
        'officiality': 'non_official_subset',
    }


def _extract_choice_letter(text: str) -> str:
    s = str(text or '').strip().upper()
    try:
        obj = json.loads(s)
        if isinstance(obj, dict):
            s = str(obj.get('answer') or obj.get('choice') or '').strip().upper()
    except Exception:
        pass
    m = re.search(r'\b([ABCD])\b', s)
    if m:
        return m.group(1)
    m = re.search(r'"?([ABCD])"?', s)
    if m:
        return m.group(1)
    return ''


def _predict_with_llm(question: str, choices: list[dict[str, Any]], benchmark: str, strategy: str = 'cheap') -> dict[str, Any]:
    from ultronpro import llm

    choice_lines = []
    for c in choices:
        choice_lines.append(f"{str(c.get('label') or '').strip()}: {str(c.get('text') or '').strip()}")
    prompt = (
        'Escolha a melhor alternativa para a questão a seguir. '
        'Responda SOMENTE em JSON válido no formato {"answer":"A"}. '
        'Sem explicações.\n\n'
        f'Benchmark: {benchmark}\n'
        f'Pergunta: {question}\n'
        'Alternativas:\n' + '\n'.join(choice_lines)
    )
    raw = llm.complete(prompt, strategy=strategy, json_mode=True, inject_persona=False, max_tokens=40, input_class='benchmark_mcq')
    answer = _extract_choice_letter(raw)
    return {'raw': raw, 'answer': answer}


def _predict_oracle(item: dict[str, Any]) -> dict[str, Any]:
    return {'raw': json.dumps({'answer': item.get('answer')}, ensure_ascii=False), 'answer': str(item.get('answer') or '')}


def _select_items(
    items: list[dict[str, Any]],
    benchmark_ids: list[str] | None = None,
    limit_per_benchmark: int | None = None,
    families: list[str] | None = None,
    splits: list[str] | None = None,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    bench_filter = set(str(x) for x in (benchmark_ids or []) if str(x).strip())
    family_filter = set(str(x) for x in (families or []) if str(x).strip())
    split_filter = set(str(x) for x in (splits or []) if str(x).strip())
    counts: dict[str, int] = {}
    for raw in items:
        item = _annotate_item(raw)
        bench = str(item.get('benchmark') or 'unknown')
        family = str(item.get('family') or 'unknown')
        split = str(item.get('split') or 'dev')
        if bench_filter and bench not in bench_filter:
            continue
        if family_filter and family not in family_filter:
            continue
        if split_filter and split not in split_filter:
            continue
        if limit_per_benchmark is not None and counts.get(bench, 0) >= int(limit_per_benchmark):
            continue
        counts[bench] = counts.get(bench, 0) + 1
        selected.append(item)
    return selected


def _score_item(item: dict[str, Any], predictor: str = 'llm', strategy: str = 'cheap') -> dict[str, Any]:
    if predictor == 'oracle':
        pred = _predict_oracle(item)
    else:
        pred = _predict_with_llm(
            str(item.get('question') or ''),
            item.get('choices') if isinstance(item.get('choices'), list) else [],
            str(item.get('benchmark') or 'unknown'),
            strategy=strategy,
        )
    gold = str(item.get('answer') or '').strip().upper()
    got = str(pred.get('answer') or '').strip().upper()
    return {
        'id': str(item.get('id') or ''),
        'benchmark': str(item.get('benchmark') or 'unknown'),
        'family': str(item.get('family') or 'unknown'),
        'split': str(item.get('split') or 'dev'),
        'comparability_tier': str(item.get('comparability_tier') or 'proxy_subset'),
        'correct': bool(gold and got == gold),
        'gold_answer': gold,
        'predicted_answer': got,
        'raw_response': str(pred.get('raw') or '')[:600],
    }


def _aggregate_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    by_benchmark: dict[str, dict[str, Any]] = {}
    by_family: dict[str, dict[str, Any]] = {}
    by_split: dict[str, dict[str, Any]] = {}
    for row in results:
        bench = str(row.get('benchmark') or 'unknown')
        fam = str(row.get('family') or 'unknown')
        spl = str(row.get('split') or 'dev')
        for bucket, key in ((by_benchmark, bench), (by_family, fam), (by_split, spl)):
            slot = bucket.setdefault(key, {'total': 0, 'correct': 0, 'accuracy': 0.0})
            slot['total'] += 1
            slot['correct'] += 1 if bool(row.get('correct')) else 0
    for bucket in (by_benchmark, by_family, by_split):
        for _, slot in bucket.items():
            slot['accuracy'] = round(float(slot['correct']) / max(1, int(slot['total'])), 4)
    return {
        'by_benchmark': by_benchmark,
        'by_family': by_family,
        'by_split': by_split,
    }


def run_suite(*, benchmark_ids: list[str] | None = None, limit_per_benchmark: int | None = None, strategy: str = 'cheap', predictor: str = 'llm', tag: str | None = None, families: list[str] | None = None, splits: list[str] | None = None) -> dict[str, Any]:
    suite = _load_suite()
    items = suite.get('items') or []
    selected = _select_items(items, benchmark_ids=benchmark_ids, limit_per_benchmark=limit_per_benchmark, families=families, splits=splits)
    results = [_score_item(item, predictor=predictor, strategy=strategy) for item in selected]
    aggr = _aggregate_results(results)

    total = len(results)
    correct = sum(1 for row in results if bool(row.get('correct')))
    report = {
        'ok': True,
        'run_id': f"extb_{uuid.uuid4().hex[:10]}",
        'ts': _now(),
        'suite': suite.get('suite') or 'external_public_eval_v1',
        'version': suite.get('version') or 1,
        'predictor': predictor,
        'strategy': strategy,
        'tag': str(tag or '')[:120] or None,
        'comparability_note': suite.get('comparability_note') or '',
        'comparability_tier': 'proxy_subset',
        'officiality': 'non_official_subset',
        'selection': {
            'benchmarks': sorted((aggr.get('by_benchmark') or {}).keys()),
            'families': sorted((aggr.get('by_family') or {}).keys()),
            'splits': sorted((aggr.get('by_split') or {}).keys()),
            'limit_per_benchmark': limit_per_benchmark,
            'count': total,
        },
        'overall_accuracy': round(float(correct) / max(1, total), 4),
        'total': total,
        'correct': correct,
        'by_benchmark': aggr.get('by_benchmark') or {},
        'by_family': aggr.get('by_family') or {},
        'by_split': aggr.get('by_split') or {},
        'items': results,
    }
    _ensure_parent(RUNS_PATH)
    with RUNS_PATH.open('a', encoding='utf-8') as f:
        f.write(json.dumps(report, ensure_ascii=False) + '\n')
    return report


def freeze_baseline(*, benchmark_ids: list[str] | None = None, limit_per_benchmark: int | None = None, strategy: str = 'cheap', predictor: str = 'llm', label: str | None = None, families: list[str] | None = None, splits: list[str] | None = None) -> dict[str, Any]:
    report = run_suite(benchmark_ids=benchmark_ids, limit_per_benchmark=limit_per_benchmark, strategy=strategy, predictor=predictor, tag=label or 'baseline', families=families, splits=splits)
    baseline = {
        'ok': True,
        'ts': _now(),
        'label': str(label or 'baseline')[:120],
        'suite': report.get('suite'),
        'version': report.get('version'),
        'predictor': report.get('predictor'),
        'strategy': report.get('strategy'),
        'overall_accuracy': report.get('overall_accuracy'),
        'total': report.get('total'),
        'correct': report.get('correct'),
        'selection': report.get('selection'),
        'by_benchmark': report.get('by_benchmark'),
        'by_family': report.get('by_family'),
        'by_split': report.get('by_split'),
        'source_run_id': report.get('run_id'),
        'comparability_note': report.get('comparability_note'),
        'comparability_tier': report.get('comparability_tier'),
        'officiality': report.get('officiality'),
    }
    _ensure_parent(BASELINE_PATH)
    BASELINE_PATH.write_text(json.dumps(baseline, ensure_ascii=False, indent=2), encoding='utf-8')
    return baseline


def recent_runs(limit: int = 10) -> dict[str, Any]:
    rows = []
    if RUNS_PATH.exists():
        for line in RUNS_PATH.read_text(encoding='utf-8', errors='ignore').splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    rows.append(obj)
            except Exception:
                continue
    rows = rows[-max(1, min(200, int(limit or 10))):]
    return {'ok': True, 'items': rows, 'count': len(rows), 'path': str(RUNS_PATH), 'baseline_path': str(BASELINE_PATH)}


def _load_baseline() -> dict[str, Any] | None:
    if not BASELINE_PATH.exists():
        return None
    try:
        data = json.loads(BASELINE_PATH.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def compare_to_baseline(run_id: str | None = None) -> dict[str, Any]:
    baseline = _load_baseline()
    if not baseline:
        return {'ok': False, 'error': 'baseline_not_found'}
    runs = recent_runs(limit=200).get('items') or []
    target = None
    if run_id:
        for row in reversed(runs):
            if str(row.get('run_id') or '') == str(run_id):
                target = row
                break
    if not target:
        target = runs[-1] if runs else None
    if not target:
        return {'ok': False, 'error': 'run_not_found'}

    def _delta(curr: dict[str, Any], base: dict[str, Any], key: str) -> dict[str, Any]:
        out = {}
        all_keys = sorted(set((curr.get(key) or {}).keys()) | set((base.get(key) or {}).keys()))
        for name in all_keys:
            c = float((((curr.get(key) or {}).get(name) or {}).get('accuracy') or 0.0))
            b = float((((base.get(key) or {}).get(name) or {}).get('accuracy') or 0.0))
            out[name] = {'current': round(c, 4), 'baseline': round(b, 4), 'delta': round(c - b, 4)}
        return out

    compatible = (
        str(target.get('suite') or '') == str(baseline.get('suite') or '') and
        int(target.get('version') or 0) == int(baseline.get('version') or 0) and
        dict(target.get('selection') or {}) == dict(baseline.get('selection') or {})
    )
    return {
        'ok': True,
        'compatible': compatible,
        'run_id': target.get('run_id'),
        'baseline_label': baseline.get('label'),
        'overall_accuracy': {
            'current': round(float(target.get('overall_accuracy') or 0.0), 4),
            'baseline': round(float(baseline.get('overall_accuracy') or 0.0), 4),
            'delta': round(float(target.get('overall_accuracy') or 0.0) - float(baseline.get('overall_accuracy') or 0.0), 4),
        },
        'by_benchmark_delta': _delta(target, baseline, 'by_benchmark'),
        'by_family_delta': _delta(target, baseline, 'by_family'),
        'by_split_delta': _delta(target, baseline, 'by_split'),
        'comparability_note': 'delta confiável somente quando compatible=true',
    }


def suite_audit() -> dict[str, Any]:
    suite = _load_suite()
    items = [_annotate_item(x) for x in (suite.get('items') or []) if isinstance(x, dict)]
    ids = [str(x.get('id') or '') for x in items]
    duplicate_ids = sorted({x for x in ids if ids.count(x) > 1})
    malformed = []
    answer_out_of_range = []
    benchmark_lineage = {}
    for item in items:
        labels = [str((c or {}).get('label') or '').strip().upper() for c in (item.get('choices') or []) if isinstance(c, dict)]
        gold = str(item.get('answer') or '').strip().upper()
        if not item.get('question') or len(labels) < 2:
            malformed.append(str(item.get('id') or ''))
        if gold not in labels:
            answer_out_of_range.append(str(item.get('id') or ''))
        benchmark_lineage[str(item.get('benchmark') or 'unknown')] = {
            'family': item.get('family'),
            'lineage': item.get('lineage'),
            'comparability_tier': item.get('comparability_tier'),
        }
    return {
        'ok': not duplicate_ids and not malformed and not answer_out_of_range,
        'count': len(items),
        'duplicate_ids': duplicate_ids,
        'malformed_items': malformed,
        'answer_out_of_range': answer_out_of_range,
        'benchmark_lineage': benchmark_lineage,
        'comparability_tier': 'proxy_subset',
        'officiality': 'non_official_subset',
    }


def status() -> dict[str, Any]:
    info = list_suite()
    recent = recent_runs(limit=5)
    baseline = _load_baseline()
    audit = suite_audit()
    latest_compare = compare_to_baseline() if baseline and (recent.get('count') or 0) > 0 else None
    return {
        'ok': True,
        'suite': info,
        'baseline': baseline,
        'audit': audit,
        'latest_compare': latest_compare,
        'recent_runs_count': recent.get('count') or 0,
        'runs_path': str(RUNS_PATH),
    }


def run_selftest() -> dict[str, Any]:
    audit = suite_audit()
    report = run_suite(predictor='oracle', tag='selftest')
    ok = bool(report.get('total')) and float(report.get('overall_accuracy') or 0.0) == 1.0 and bool(audit.get('ok'))
    return {'ok': ok, 'audit': audit, 'report': report}
