from __future__ import annotations

import json
import re
import time
import uuid
import ast
from pathlib import Path
from typing import Any

SUITE_PATH = Path(__file__).resolve().parent / 'benchmarks' / 'external_public_eval_v1.json'
RUNS_PATH = Path(__file__).resolve().parent.parent / 'data' / 'external_benchmarks/public_eval_runs.jsonl'
BASELINE_PATH = Path(__file__).resolve().parent.parent / 'data' / 'external_benchmarks/public_eval_baseline.json'
HINDSIGHT_PATH = Path(__file__).resolve().parent.parent / 'data' / 'external_benchmarks/hindsight_replay.jsonl'
CROSS_MODAL_PATH = Path(__file__).resolve().parent.parent / 'data' / 'external_benchmarks/cross_modal_validations.jsonl'

FACTUAL_CORRECT_SCORE = 0.975
FACTUAL_INCORRECT_SCORE = 0.1
CROSS_MODAL_FAILURE_CAP = 0.35

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
    s = str(text or '').strip()
    try:
        obj = json.loads(s)
        if isinstance(obj, dict):
            # Case-insensitive key lookup
            d = {str(k).lower(): v for k, v in obj.items()}
            s = str(d.get('answer') or d.get('choice') or '').strip().upper()
    except Exception:
        s = s.upper()
    m = re.search(r'\b([ABCD])\b', s)
    if m:
        return m.group(1)
    m = re.search(r'"?([ABCD])"?', s)
    if m:
        return m.group(1)
    return ''


def _safe_jsonish(value: Any) -> Any:
    if isinstance(value, (dict, list, int, float, bool)) or value is None:
        return value
    text = str(value or '').strip()
    if not text:
        return ''
    try:
        return json.loads(text)
    except Exception:
        pass
    try:
        return ast.literal_eval(text)
    except Exception:
        return value


def _norm_text(value: Any) -> str:
    return re.sub(r'\s+', ' ', str(value or '').strip()).upper()


def _choice_text(item: dict[str, Any], label: str) -> str:
    lab = str(label or '').strip().upper()
    for choice in (item.get('choices') or []):
        if not isinstance(choice, dict):
            continue
        if str(choice.get('label') or '').strip().upper() == lab:
            return str(choice.get('text') or '').strip()
    return ''


def resolve_external_ground_truth(query: str = '', context_meta: dict[str, Any] | None = None) -> dict[str, Any]:
    """Resolve a factual anchor from explicit meta or the public benchmark suite."""
    meta = context_meta if isinstance(context_meta, dict) else {}
    for key in ('ground_truth', 'gold_answer', 'expected_answer'):
        if key in meta and meta.get(key) not in (None, ''):
            return {
                'ok': True,
                'has_ground_truth': True,
                'ground_truth': meta.get(key),
                'source': key,
                'item': meta.get('benchmark_item') if isinstance(meta.get('benchmark_item'), dict) else {},
            }

    item = meta.get('external_benchmark_item') or meta.get('benchmark_item')
    if isinstance(item, dict) and item.get('answer') not in (None, ''):
        annotated = _annotate_item(item)
        return {
            'ok': True,
            'has_ground_truth': True,
            'ground_truth': annotated.get('answer'),
            'source': 'benchmark_item',
            'item': annotated,
        }

    bench_id = str(meta.get('external_benchmark_id') or meta.get('benchmark_id') or meta.get('case_id') or '').strip()
    if bench_id:
        try:
            suite = _load_suite()
            for raw in suite.get('items') or []:
                if not isinstance(raw, dict):
                    continue
                if str(raw.get('id') or '') == bench_id:
                    annotated = _annotate_item(raw)
                    return {
                        'ok': True,
                        'has_ground_truth': True,
                        'ground_truth': annotated.get('answer'),
                        'source': 'external_public_eval_v1',
                        'item': annotated,
                    }
        except Exception as e:
            return {'ok': False, 'has_ground_truth': False, 'error': f'ground_truth_lookup_failed:{type(e).__name__}'}

    return {'ok': True, 'has_ground_truth': False, 'ground_truth': None, 'source': None, 'item': {}}


def evaluate_answer_against_ground_truth(
    *,
    query: str,
    answer: Any,
    ground_truth: Any = None,
    context_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Score an answer against an external factual anchor, independent of style."""
    meta = context_meta if isinstance(context_meta, dict) else {}
    resolved = resolve_external_ground_truth(query=query, context_meta=meta)
    item = resolved.get('item') if isinstance(resolved.get('item'), dict) else {}
    gold = ground_truth if ground_truth not in (None, '') else resolved.get('ground_truth')
    if gold in (None, ''):
        return {'ok': True, 'has_ground_truth': False, 'factual_correct': None, 'factual_score': None}

    parsed_answer = _safe_jsonish(answer)
    kind = 'exact'
    predicted: Any = parsed_answer
    correct = False

    if isinstance(gold, list) and (not gold or isinstance(gold[0], list)):
        kind = 'grid'
        predicted = parsed_answer
        correct = bool(predicted == gold)
    elif isinstance(gold, str) and len(str(gold).strip()) == 1:
        kind = 'mcq'
        predicted = _extract_choice_letter(str(answer))
        correct = bool(predicted and predicted == str(gold).strip().upper())
    else:
        predicted = parsed_answer
        correct = _norm_text(predicted) == _norm_text(gold)

    gold_label = str(gold or '').strip().upper() if kind == 'mcq' else gold
    expected_text = _choice_text(item, str(gold_label)) if kind == 'mcq' and item else ''
    score = FACTUAL_CORRECT_SCORE if correct else FACTUAL_INCORRECT_SCORE
    alerts = [] if correct else ['factual_error_against_ground_truth', 'ground_truth_mismatch']
    return {
        'ok': True,
        'has_ground_truth': True,
        'kind': kind,
        'factual_correct': bool(correct),
        'factual_score': score,
        'predicted_answer': predicted,
        'gold_answer': gold_label,
        'expected_answer': expected_text or gold_label,
        'ground_truth_source': resolved.get('source') or ('provided' if ground_truth not in (None, '') else None),
        'benchmark_id': item.get('id'),
        'benchmark': item.get('benchmark'),
        'family': item.get('family'),
        'split': item.get('split'),
        'comparability_tier': item.get('comparability_tier'),
        'alerts': alerts,
    }


def _compact_trajectory(context_meta: dict[str, Any], tool_outputs: list[dict[str, Any]] | None) -> dict[str, Any]:
    meta = context_meta if isinstance(context_meta, dict) else {}
    trajectory = meta.get('trajectory')
    if not isinstance(trajectory, (dict, list)):
        trajectory = meta.get('planner_trace') or meta.get('steps') or meta.get('plan')
    return {
        'trajectory': trajectory if isinstance(trajectory, (dict, list)) else None,
        'tool_outputs': [
            {
                'tool': str((row or {}).get('tool') or '')[:80],
                'status': str((row or {}).get('status') or '')[:40],
                'output': str((row or {}).get('output') or '')[:500],
            }
            for row in (tool_outputs or [])[:12]
            if isinstance(row, dict)
        ],
    }


def build_hindsight_example(
    *,
    query: str,
    answer: Any,
    factual_eval: dict[str, Any],
    context_meta: dict[str, Any] | None = None,
    tool_outputs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not bool((factual_eval or {}).get('has_ground_truth')):
        return {}
    correct = bool((factual_eval or {}).get('factual_correct'))
    return {
        'ts': _now(),
        'kind': 'hindsight_retro_label',
        'query': str(query or '')[:1200],
        'observed_answer': str(answer or '')[:2000],
        'predicted_answer': (factual_eval or {}).get('predicted_answer'),
        'gold_answer': (factual_eval or {}).get('gold_answer'),
        'correct_solution': (factual_eval or {}).get('expected_answer') or (factual_eval or {}).get('gold_answer'),
        'factual_correct': correct,
        'surprise_score': 0.0 if correct else 1.0,
        'negative_label': None if correct else 'avoid_observed_answer',
        'positive_label': 'replay_with_external_ground_truth',
        'benchmark_id': (factual_eval or {}).get('benchmark_id'),
        'benchmark': (factual_eval or {}).get('benchmark'),
        'family': (factual_eval or {}).get('family'),
        'trajectory': _compact_trajectory(context_meta or {}, tool_outputs),
    }


def record_hindsight_failure(
    *,
    query: str,
    answer: Any,
    factual_eval: dict[str, Any],
    context_meta: dict[str, Any] | None = None,
    tool_outputs: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    if not bool((factual_eval or {}).get('has_ground_truth')) or bool((factual_eval or {}).get('factual_correct')):
        return None
    row = build_hindsight_example(
        query=query,
        answer=answer,
        factual_eval=factual_eval,
        context_meta=context_meta,
        tool_outputs=tool_outputs,
    )
    if not row:
        return None
    _ensure_parent(HINDSIGHT_PATH)
    with HINDSIGHT_PATH.open('a', encoding='utf-8') as f:
        f.write(json.dumps(row, ensure_ascii=False) + '\n')
    return row


def _append_cross_modal(row: dict[str, Any]) -> None:
    _ensure_parent(CROSS_MODAL_PATH)
    with CROSS_MODAL_PATH.open('a', encoding='utf-8') as f:
        f.write(json.dumps(row, ensure_ascii=False) + '\n')


def _code_validation_modality(spec: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(spec, dict) or not spec:
        return None
    result = spec.get('sandbox_result') if isinstance(spec.get('sandbox_result'), dict) else None
    language = str(spec.get('language') or 'python').strip().lower()
    code = str(spec.get('code') or spec.get('command') or '')
    if result is None and code.strip():
        try:
            from ultronpro import sandbox_client
            if language in ('bash', 'shell', 'sh'):
                result = sandbox_client.execute_bash(code, timeout_sec=int(spec.get('timeout_sec') or 10))
            else:
                result = sandbox_client.execute_python(code, timeout_sec=int(spec.get('timeout_sec') or 10))
        except Exception as e:
            result = {'ok': False, 'error': f'sandbox_error:{type(e).__name__}', 'returncode': -1, 'stdout': '', 'stderr': str(e)[:600]}
    if result is None:
        return {'modality': 'code_sandbox', 'status': 'unavailable', 'surprise': 0.35, 'reason': 'missing_code_or_result'}

    err = str(result.get('error') or '')
    if err.startswith('sandbox_unreachable:'):
        return {'modality': 'code_sandbox', 'status': 'unavailable', 'surprise': 0.55, 'reason': err, 'result': result}

    expected_rc = int(spec.get('expected_returncode') if spec.get('expected_returncode') is not None else 0)
    rc_ok = int(result.get('returncode') or 0) == expected_rc
    stdout = str(result.get('stdout') or '')
    contains = spec.get('expected_stdout_contains')
    stdout_ok = True if contains in (None, '') else str(contains) in stdout
    passed = rc_ok and stdout_ok and bool(result.get('ok', rc_ok))
    return {
        'modality': 'code_sandbox',
        'status': 'passed' if passed else 'failed',
        'surprise': 0.0 if passed else 0.9,
        'reason': 'execution_matched_expectation' if passed else 'sandbox_result_mismatch',
        'result': {
            'ok': bool(result.get('ok')),
            'returncode': int(result.get('returncode') or 0),
            'stdout': stdout[:1000],
            'stderr': str(result.get('stderr') or '')[:1000],
            'error': err[:300],
        },
    }


def _source_validation_modality(query: str, factual_eval: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(spec, dict) or not spec:
        return None
    sources = spec.get('sources') or spec.get('independent_sources') or []
    if not isinstance(sources, list):
        sources = []
    allow_network = bool(spec.get('allow_network'))
    fetched_sources: list[dict[str, Any]] = []
    if not sources and allow_network:
        try:
            from ultronpro import web_browser
            search = web_browser.search_web(str(query or ''), top_k=int(spec.get('top_k') or 3))
            for item in (search.get('items') or [])[:3]:
                if isinstance(item, dict):
                    fetched_sources.append({'title': item.get('title'), 'url': item.get('url'), 'text': item.get('snippet') or ''})
        except Exception:
            fetched_sources = []
    sources = [x for x in (sources or fetched_sources) if isinstance(x, dict)]
    if not sources:
        return {'modality': 'independent_sources', 'status': 'unavailable', 'surprise': 0.35, 'reason': 'missing_sources'}

    expected = str((factual_eval or {}).get('expected_answer') or (factual_eval or {}).get('gold_answer') or '').strip()
    required_terms = [str(x).strip().lower() for x in (spec.get('required_terms') or []) if str(x).strip()]
    if not required_terms and expected:
        required_terms = [expected.lower()]
    min_sources = max(1, int(spec.get('min_sources') or 2))
    hits = 0
    checked = []
    for source in sources[:8]:
        text = str(source.get('text') or source.get('snippet') or source.get('title') or '')
        low = text.lower()
        supported = bool(required_terms) and all(term in low for term in required_terms)
        if supported:
            hits += 1
        checked.append({
            'url': str(source.get('url') or '')[:300],
            'title': str(source.get('title') or '')[:200],
            'supported': supported,
        })

    passed = hits >= min_sources
    return {
        'modality': 'independent_sources',
        'status': 'passed' if passed else 'failed',
        'surprise': 0.0 if passed else 0.85,
        'reason': 'source_consensus_met' if passed else 'source_consensus_missing',
        'hits': hits,
        'min_sources': min_sources,
        'checked_sources': checked,
        'required_terms': required_terms[:10],
    }


def validate_cross_modal(
    *,
    query: str,
    answer: Any,
    context_meta: dict[str, Any] | None = None,
    tool_outputs: list[dict[str, Any]] | None = None,
    factual_eval: dict[str, Any] | None = None,
    record: bool = False,
) -> dict[str, Any]:
    meta = context_meta if isinstance(context_meta, dict) else {}
    factual = factual_eval or evaluate_answer_against_ground_truth(query=query, answer=answer, context_meta=meta)
    modalities: list[dict[str, Any]] = []
    if bool(factual.get('has_ground_truth')):
        modalities.append({
            'modality': 'external_ground_truth',
            'status': 'passed' if bool(factual.get('factual_correct')) else 'failed',
            'surprise': 0.0 if bool(factual.get('factual_correct')) else 1.0,
            'reason': 'gold_answer_match' if bool(factual.get('factual_correct')) else 'gold_answer_mismatch',
            'gold_answer': factual.get('gold_answer'),
            'predicted_answer': factual.get('predicted_answer'),
        })

    code_spec = meta.get('code_validation') if isinstance(meta.get('code_validation'), dict) else {}
    code_mod = _code_validation_modality(code_spec)
    if code_mod:
        modalities.append(code_mod)

    source_spec = meta.get('source_validation') if isinstance(meta.get('source_validation'), dict) else {}
    if not source_spec and isinstance(meta.get('independent_sources'), list):
        source_spec = {'sources': meta.get('independent_sources')}
    source_mod = _source_validation_modality(query, factual, source_spec)
    if source_mod:
        modalities.append(source_mod)

    passed_count = sum(1 for m in modalities if str(m.get('status')) == 'passed')
    failed_count = sum(1 for m in modalities if str(m.get('status')) == 'failed')
    unavailable_count = sum(1 for m in modalities if str(m.get('status')) == 'unavailable')
    surprise = round(max([float(m.get('surprise') or 0.0) for m in modalities] or [0.0]), 4)
    row = {
        'ok': failed_count == 0,
        'validated': bool(modalities),
        'ts': _now(),
        'query': str(query or '')[:1200],
        'passed_count': passed_count,
        'failed_count': failed_count,
        'unavailable_count': unavailable_count,
        'surprise_score': surprise,
        'needs_revision': failed_count > 0,
        'modalities': modalities,
    }
    if record and modalities:
        _append_cross_modal(row)
    return row


def verify_response_against_reality(
    *,
    query: str,
    answer: Any,
    context_meta: dict[str, Any] | None = None,
    tool_outputs: list[dict[str, Any]] | None = None,
    record: bool = False,
) -> dict[str, Any]:
    meta = context_meta if isinstance(context_meta, dict) else {}
    factual = evaluate_answer_against_ground_truth(query=query, answer=answer, context_meta=meta)
    cross = validate_cross_modal(
        query=query,
        answer=answer,
        context_meta=meta,
        tool_outputs=tool_outputs,
        factual_eval=factual,
        record=record,
    )
    hindsight = record_hindsight_failure(
        query=query,
        answer=answer,
        factual_eval=factual,
        context_meta=meta,
        tool_outputs=tool_outputs,
    ) if record else None
    result = {
        'ok': True,
        'factual_eval': factual,
        'cross_modal': cross,
        'hindsight_replay': hindsight,
    }
    if record:
        try:
            from ultronpro import epistemic_ledger
            result['epistemic_ledger'] = epistemic_ledger.record_external_verification(
                query=query,
                answer=answer,
                verification=result,
            )
        except Exception as e:
            result['epistemic_ledger'] = {'ok': False, 'error': f'ledger_record_failed:{type(e).__name__}'}
    return result


def patch_requires_external_anchor(patch: dict[str, Any]) -> bool:
    text = ' '.join([
        str(patch.get('problem_pattern') or ''),
        str(patch.get('hypothesis') or ''),
        json.dumps(patch.get('benchmark_before') or {}, ensure_ascii=False, default=str),
        json.dumps(patch.get('proposed_change') or {}, ensure_ascii=False, default=str),
    ]).lower()
    terms = (
        'ground_truth',
        'gold',
        'gabarito',
        'factual',
        'mcq',
        'mmlu',
        'arc_easy',
        'hellaswag',
        'academic_mcq',
        'science_qa',
        'commonsense_next_step',
        'external_public_eval',
    )
    return any(term in text for term in terms)


def evaluate_patch_external_factual_evidence(patch: dict[str, Any]) -> dict[str, Any]:
    patch = patch if isinstance(patch, dict) else {}
    shadow_metrics = patch.get('shadow_metrics') if isinstance(patch.get('shadow_metrics'), dict) else {}
    benchmark_after = patch.get('benchmark_after') if isinstance(patch.get('benchmark_after'), dict) else {}
    shadow_eval = benchmark_after.get('shadow_eval') if isinstance(benchmark_after.get('shadow_eval'), dict) else {}
    cases = [c for c in (shadow_eval.get('cases') or []) if isinstance(c, dict)]
    factual_cases = [
        c for c in cases
        if c.get('ground_truth') not in (None, '') or c.get('candidate_factual_correct') is not None
    ]

    cases_total = int(shadow_metrics.get('factual_cases_total') or len(factual_cases) or 0)
    candidate_correct = int(shadow_metrics.get('candidate_factual_correct') or 0)
    baseline_correct = int(shadow_metrics.get('baseline_factual_correct') or 0)
    if factual_cases and not candidate_correct:
        candidate_correct = sum(1 for c in factual_cases if bool(c.get('candidate_factual_correct')))
    if factual_cases and not baseline_correct:
        baseline_correct = sum(1 for c in factual_cases if bool(c.get('baseline_factual_correct')))
    candidate_failures = int(shadow_metrics.get('external_anchor_failures') or max(0, cases_total - candidate_correct))
    candidate_accuracy = round(candidate_correct / max(1, cases_total), 4) if cases_total else 0.0
    baseline_accuracy = round(baseline_correct / max(1, cases_total), 4) if cases_total else 0.0

    return {
        'ok': True,
        'requires_external_anchor': patch_requires_external_anchor(patch),
        'has_external_anchor': cases_total > 0,
        'cases_total': cases_total,
        'candidate_factual_correct': candidate_correct,
        'baseline_factual_correct': baseline_correct,
        'candidate_factual_accuracy': candidate_accuracy,
        'baseline_factual_accuracy': baseline_accuracy,
        'factual_delta': round(candidate_accuracy - baseline_accuracy, 4) if cases_total else 0.0,
        'external_anchor_failures': candidate_failures,
        'case_ids': [str(c.get('case_id') or '') for c in factual_cases[:20]],
    }


def _predict_with_llm(question: str, choices: list[dict[str, Any]], benchmark: str, strategy: str = 'cheap') -> dict[str, Any]:
    if str(strategy or '').strip().lower() in {'local', 'no_cloud', 'deterministic'}:
        try:
            from ultronpro import local_mcq_reasoner

            local = local_mcq_reasoner.solve_mcq(question, choices)
            if bool(local.get('ok')):
                return {
                    'raw': local.get('raw') or json.dumps({'answer': local.get('answer')}, ensure_ascii=False),
                    'answer': str(local.get('answer') or ''),
                    'source': 'local_mcq_reasoner',
                    'confidence': local.get('confidence'),
                    'scores': local.get('scores'),
                }
            return {
                'raw': local.get('raw') or json.dumps({'answer': ''}, ensure_ascii=False),
                'answer': '',
                'source': 'local_mcq_reasoner',
                'confidence': local.get('confidence'),
                'scores': local.get('scores'),
            }
        except Exception as e:
            return {'raw': f'local_mcq_reasoner_error:{type(e).__name__}', 'answer': '', 'source': 'local_mcq_reasoner'}

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
    elif str(predictor or '').strip().lower() in {'local', 'local_mcq', 'local_reasoner'}:
        from ultronpro import local_mcq_reasoner

        local = local_mcq_reasoner.solve_mcq(
            str(item.get('question') or ''),
            item.get('choices') if isinstance(item.get('choices'), list) else [],
        )
        pred = {
            'raw': local.get('raw') or json.dumps({'answer': local.get('answer')}, ensure_ascii=False),
            'answer': str(local.get('answer') or ''),
            'source': 'local_mcq_reasoner',
            'confidence': local.get('confidence'),
            'scores': local.get('scores'),
        }
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
        'prediction_source': str(pred.get('source') or predictor),
        'prediction_confidence': pred.get('confidence'),
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
