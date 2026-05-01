from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from ultronpro import explicit_abstractions, structural_mapper

DATA_PATH = Path(__file__).resolve().parent.parent / 'data' / 'transfer_benchmarks.jsonl'

_SCENARIOS: list[dict[str, Any]] = [
    {
        'id': 'debugging_regression_fix',
        'target_domain': 'debugging',
        'target_text': 'Há um bug com regressão após correção parcial; preciso reduzir o erro sem criar nova falha e com passos incrementais.',
        'expected_keywords': ['regressão', 'causa raiz', 'reavaliar'],
        'baseline_keywords': ['investigar', 'corrigir'],
    },
    {
        'id': 'infra_timeout_incident',
        'target_domain': 'infra',
        'target_text': 'Incidente com timeout, fila crescendo e serviço degradado; precisamos restaurar serviço sem ampliar indisponibilidade.',
        'expected_keywords': ['incidente', 'serviço', 'reavaliar'],
        'baseline_keywords': ['reiniciar', 'monitorar'],
    },
    {
        'id': 'pipeline_retry_failure',
        'target_domain': 'pipeline',
        'target_text': 'Pipeline ETL falhando com retries repetidos; precisamos normalizar o fluxo sem quebrar estágios anteriores.',
        'expected_keywords': ['pipeline', 'quebra', 'reavaliar'],
        'baseline_keywords': ['retry', 'verificar'],
    },
    {
        'id': 'planning_deadline_constraints',
        'target_domain': 'planning',
        'target_text': 'Plano com deadline curto e recursos limitados; precisamos avançar sem violar restrições principais.',
        'expected_keywords': ['restrição', 'plano', 'reavaliar'],
        'baseline_keywords': ['priorizar', 'executar'],
    },
]


def _now() -> int:
    return int(time.time())


def _ensure_parent(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)


def _norm(text: str) -> str:
    return str(text or '').strip().lower()


def scenarios() -> dict[str, Any]:
    return {'ok': True, 'items': list(_SCENARIOS), 'count': len(_SCENARIOS)}


def _baseline_plan(target_domain: str) -> list[str]:
    dom = _norm(target_domain)
    if dom == 'debugging':
        return ['investigar erro atual', 'corrigir bug principal']
    if dom == 'infra':
        return ['monitorar serviço', 'reiniciar componente afetado']
    if dom == 'pipeline':
        return ['verificar logs do job', 'executar retry']
    if dom == 'planning':
        return ['priorizar tarefas', 'executar plano inicial']
    return ['analisar problema', 'agir']


def _score_plan(steps: list[str], expected_keywords: list[str], baseline_keywords: list[str] | None = None) -> dict[str, Any]:
    text = ' '.join(str(x) for x in (steps or []))
    low = _norm(text)
    expected_hits = [k for k in (expected_keywords or []) if _norm(k) in low]
    baseline_hits = [k for k in (baseline_keywords or []) if _norm(k) in low]
    step_count = len(steps or [])
    coverage = len(expected_hits) / max(1, len(expected_keywords or []))
    procedural_depth = min(1.0, step_count / 5.0)
    baseline_shallowness = min(1.0, len(baseline_hits) / max(1, len(baseline_keywords or [])))
    score = round((0.55 * coverage) + (0.35 * procedural_depth) + (0.10 * baseline_shallowness), 4)
    return {
        'score': score,
        'coverage': round(coverage, 4),
        'procedural_depth': round(procedural_depth, 4),
        'expected_hits': expected_hits,
        'baseline_hits': baseline_hits,
    }


def benchmark_abstraction(abstraction_id: str, scenario_ids: list[str] | None = None) -> dict[str, Any] | None:
    abstraction = explicit_abstractions.get_abstraction(abstraction_id)
    if not abstraction:
        return None
    selected = [s for s in _SCENARIOS if not scenario_ids or s['id'] in scenario_ids]
    results = []
    for s in selected:
        mapped = structural_mapper.apply_mapped_abstraction(abstraction_id, s['target_domain'], s['target_text'])
        if not mapped:
            continue
        mapped_steps = ((mapped.get('application_plan') or {}).get('steps') or [])
        mapped_score = _score_plan(mapped_steps, s.get('expected_keywords') or [], s.get('baseline_keywords') or [])
        baseline_steps = _baseline_plan(s['target_domain'])
        baseline_score = _score_plan(baseline_steps, s.get('expected_keywords') or [], s.get('baseline_keywords') or [])
        improvement = round(float(mapped_score['score']) - float(baseline_score['score']), 4)
        explicit_abstractions.update_transfer_history(
            abstraction_id,
            target_domain=s['target_domain'],
            outcome='success' if improvement > 0 else 'failure',
            evidence_ref=f"transfer_benchmark:{s['id']}",
            score=max(0.0, min(1.0, 0.5 + improvement)),
            notes=f"scenario={s['id']} mapped={mapped_score['score']} baseline={baseline_score['score']}",
        )
        results.append({
            'scenario_id': s['id'],
            'target_domain': s['target_domain'],
            'structural_similarity': ((mapped.get('mapping') or {}).get('structural_similarity')),
            'recommended': ((mapped.get('mapping') or {}).get('recommended')),
            'mapped_plan_score': mapped_score,
            'baseline_plan_score': baseline_score,
            'improvement': improvement,
        })

    avg_improvement = round(sum(float(x.get('improvement') or 0.0) for x in results) / max(1, len(results)), 4)
    zero_shot_win_rate = round(sum(1 for x in results if float(x.get('improvement') or 0.0) > 0.0) / max(1, len(results)), 4)
    report = {
        'id': f"tb_{uuid.uuid4().hex[:10]}",
        'ts': _now(),
        'abstraction_id': abstraction_id,
        'scenarios': len(results),
        'avg_improvement': avg_improvement,
        'zero_shot_win_rate': zero_shot_win_rate,
        'results': results,
    }
    _ensure_parent(DATA_PATH)
    with DATA_PATH.open('a', encoding='utf-8') as f:
        f.write(json.dumps(report, ensure_ascii=False) + '\n')
    consolidated = explicit_abstractions.consolidate_abstraction(
        abstraction_id,
        benchmark_summary={
            'avg_improvement': avg_improvement,
            'zero_shot_win_rate': zero_shot_win_rate,
            'scenarios': len(results),
        },
        note=f"auto_consolidated_from_benchmark:{report['id']}",
    )
    return {'ok': True, **report, 'consolidated_item': consolidated, 'path': str(DATA_PATH)}


def consolidate_from_latest(abstraction_id: str) -> dict[str, Any] | None:
    reports = recent_reports(limit=200).get('items') or []
    for row in reversed(reports):
        if str(row.get('abstraction_id') or '') == str(abstraction_id):
            item = explicit_abstractions.consolidate_abstraction(
                abstraction_id,
                benchmark_summary={
                    'avg_improvement': row.get('avg_improvement'),
                    'zero_shot_win_rate': row.get('zero_shot_win_rate'),
                    'scenarios': row.get('scenarios'),
                },
                note=f"transfer_benchmark:{str(row.get('id') or '')}",
            )
            if not item:
                return None
            return {'ok': True, 'item': item, 'source_report_id': row.get('id')}
    return None


def recent_reports(limit: int = 20) -> dict[str, Any]:
    rows = []
    if DATA_PATH.exists():
        for line in DATA_PATH.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    rows.append(obj)
            except Exception:
                continue
    rows = rows[-max(1, min(200, int(limit or 20))):]
    return {'ok': True, 'items': rows, 'count': len(rows), 'path': str(DATA_PATH)}
