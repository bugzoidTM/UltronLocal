from __future__ import annotations

import json
import time
import hashlib
from pathlib import Path
from typing import Any
import tempfile

from ultronpro import cognitive_patches

QUALITY_LOG_PATH = Path(__file__).resolve().parent.parent / 'data' / 'quality_eval.jsonl'
STATE_PATH = Path(__file__).resolve().parent.parent / 'data' / 'gap_detector_state.json'

DEFAULT_STATE: dict[str, Any] = {
    'version': 1,
    'last_scan_ts': 0,
    'last_scan_rows': 0,
    'last_alert_counts': {},
    'recent_patch_ids': {},
    'auto_scan': {
        'every_n_rows': 5,
        'last_auto_scan_row_count': 0,
    },
}

DEFAULT_THRESHOLDS: dict[str, int] = {
    'quality_score_below_threshold': 3,
    'groundedness_low': 3,
    'relevance_low': 3,
    'missing_gap_disclosure': 2,
    'rag_coverage_low': 3,
    'rag_diversity_low': 3,
    'rag_redundancy_high': 3,
    'critic_revision_needed': 3,
    'critic_overconfident': 2,
}


def _now() -> int:
    return int(time.time())


def _ensure_parent(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)


def _load_state() -> dict[str, Any]:
    try:
        if STATE_PATH.exists():
            d = json.loads(STATE_PATH.read_text(encoding='utf-8'))
            if isinstance(d, dict):
                out = dict(DEFAULT_STATE)
                out.update(d)
                return out
    except Exception:
        pass
    return dict(DEFAULT_STATE)


def _save_state(d: dict[str, Any]):
    _ensure_parent(STATE_PATH)
    out = dict(DEFAULT_STATE)
    out.update(d or {})
    out['last_scan_ts'] = _now()
    STATE_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        for ln in path.read_text(encoding='utf-8', errors='ignore').splitlines():
            ln = ln.strip()
            if not ln:
                continue
            try:
                row = json.loads(ln)
            except Exception:
                continue
            if isinstance(row, dict):
                rows.append(row)
    except Exception:
        return []
    return rows


def _problem_key(task_type: str, alert: str) -> str:
    raw = f'{task_type}|{alert}'
    return hashlib.sha1(raw.encode('utf-8', errors='ignore')).hexdigest()[:12]


def _cluster_key(task_type: str, cluster: str) -> str:
    raw = f'{task_type}|cluster|{cluster}'
    return hashlib.sha1(raw.encode('utf-8', errors='ignore')).hexdigest()[:12]


def _summarize_problem(task_type: str, alert: str) -> dict[str, Any]:
    mapping = {
        'quality_score_below_threshold': ('quality_score baixo recorrente', 'heuristic_patch', 0.8),
        'groundedness_low': ('groundedness baixa recorrente', 'heuristic_patch', 0.85),
        'relevance_low': ('relevance baixa recorrente', 'heuristic_patch', 0.65),
        'missing_gap_disclosure': ('incerteza não explicitada quando fallback era necessário', 'confidence_patch', 0.92),
        'rag_coverage_low': ('cobertura RAG baixa recorrente', 'routing_patch', 0.78),
        'rag_diversity_low': ('diversidade RAG baixa recorrente', 'routing_patch', 0.72),
        'rag_redundancy_high': ('redundância RAG alta recorrente', 'routing_patch', 0.68),
        'critic_revision_needed': ('respostas exigindo revisão epistêmica recorrente', 'planner_patch', 0.74),
        'critic_overconfident': ('estilo sobreconfiante recorrente', 'confidence_patch', 0.95),
    }
    title, kind, severity = mapping.get(alert, (f'falha recorrente: {alert}', 'heuristic_patch', 0.6))
    return {'title': title, 'kind': kind, 'severity': severity}


def _priority_score(*, count: int, avg_score: float, severity: float) -> float:
    frequency_factor = min(1.0, float(count) / 6.0)
    impact_factor = 1.0 - max(0.0, min(1.0, float(avg_score)))
    score = (0.45 * frequency_factor) + (0.35 * float(severity)) + (0.20 * impact_factor)
    return round(max(0.0, min(1.0, score)), 4)


def _alert_cluster(alert: str) -> str:
    a = str(alert or '').strip().lower()
    if a in {'critic_overconfident', 'critic_revision_needed', 'missing_gap_disclosure', 'groundedness_low', 'quality_score_below_threshold'}:
        return 'epistemic_grounding'
    if a in {'rag_coverage_low', 'rag_diversity_low', 'rag_redundancy_high'}:
        return 'rag_routing'
    if a in {'relevance_low'}:
        return 'task_focus'
    return a or 'general'


def _canonical_alert_for_cluster(items: list[dict[str, Any]]) -> str:
    priority_order = [
        'critic_overconfident',
        'missing_gap_disclosure',
        'groundedness_low',
        'quality_score_below_threshold',
        'critic_revision_needed',
        'rag_coverage_low',
        'rag_diversity_low',
        'rag_redundancy_high',
        'relevance_low',
    ]
    seen = {str(x.get('alert') or '') for x in items}
    for a in priority_order:
        if a in seen:
            return a
    return str((items[0] or {}).get('alert') or 'unknown')


def _find_open_cluster_patch(task_type: str, cluster: str) -> dict[str, Any] | None:
    rows = cognitive_patches.list_patches(limit=500)
    for row in rows:
        status = str(row.get('status') or 'proposed')
        if status in {'rejected', 'rolled_back', 'archived'}:
            continue
        pc = row.get('proposed_change') if isinstance(row.get('proposed_change'), dict) else {}
        if str(pc.get('task_type') or '') == str(task_type) and str(pc.get('cluster') or '') == str(cluster):
            return row
    return None


def _merge_unique_str(existing: list[Any], extra: list[Any], limit: int = 30, prefix: str = '', suffix: str = '') -> list[str]:
    out: list[str] = []
    for src in [existing or [], extra or []]:
        for x in src:
            s = f'{prefix}{str(x)}{suffix}' if prefix or suffix else str(x)
            s = s[:200]
            if s and s not in out:
                out.append(s)
    return out[:max(1, int(limit))]


def consolidate_open_cluster_duplicates() -> dict[str, Any]:
    raw_rows = cognitive_patches.list_patches(limit=500)
    latest_by_id: dict[str, dict[str, Any]] = {}
    for row in raw_rows:
        pid = str(row.get('id') or '')
        if not pid:
            continue
        prev = latest_by_id.get(pid)
        if prev is None or int(row.get('updated_at') or row.get('created_at') or 0) >= int(prev.get('updated_at') or prev.get('created_at') or 0):
            latest_by_id[pid] = row
    rows = list(latest_by_id.values())
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        status = str(row.get('status') or 'proposed')
        if status in {'rejected', 'rolled_back', 'archived', 'promoted'}:
            continue
        pc = row.get('proposed_change') if isinstance(row.get('proposed_change'), dict) else {}
        task_type = str(pc.get('task_type') or '')
        cluster = str(pc.get('cluster') or _alert_cluster(str(pc.get('alert') or '')))
        if not task_type or not cluster:
            continue
        grouped.setdefault(f'{task_type}|{cluster}', []).append(row)

    consolidated = []
    rejected = []
    for key, items in grouped.items():
        if len(items) <= 1:
            continue
        def _rank(x: dict[str, Any]):
            pc = x.get('proposed_change') if isinstance(x.get('proposed_change'), dict) else {}
            bb = x.get('benchmark_before') if isinstance(x.get('benchmark_before'), dict) else {}
            return (
                float(pc.get('priority_score') or bb.get('priority_score') or 0.0),
                int(pc.get('count') or bb.get('observed_count') or 0),
                int(x.get('updated_at') or x.get('created_at') or 0),
            )
        items = sorted(items, key=_rank, reverse=True)
        keeper = items[0]
        keeper_pc = keeper.get('proposed_change') if isinstance(keeper.get('proposed_change'), dict) else {}
        keeper_bb = keeper.get('benchmark_before') if isinstance(keeper.get('benchmark_before'), dict) else {}
        merged_alerts = _merge_unique_str(keeper_pc.get('supporting_alerts') or [], [keeper_pc.get('alert')], limit=20)
        merged_evidence = _merge_unique_str(keeper.get('evidence_refs') or [], [], limit=40)
        merged_queries = _merge_unique_str(keeper_bb.get('sample_queries') or [], [], limit=5)
        reasons = _merge_unique_str(([keeper.get('notes')] if keeper.get('notes') else []), [], limit=20)
        max_count = int(keeper_pc.get('count') or keeper_bb.get('observed_count') or 0)
        max_priority = float(keeper_pc.get('priority_score') or keeper_bb.get('priority_score') or 0.0)
        min_avg = float(keeper_bb.get('avg_composite_score') or 1.0)
        for dup in items[1:]:
            pc = dup.get('proposed_change') if isinstance(dup.get('proposed_change'), dict) else {}
            bb = dup.get('benchmark_before') if isinstance(dup.get('benchmark_before'), dict) else {}
            merged_alerts = _merge_unique_str(merged_alerts, (pc.get('supporting_alerts') or []) + [pc.get('alert')], limit=20)
            merged_evidence = _merge_unique_str(merged_evidence, dup.get('evidence_refs') or [], limit=40)
            merged_queries = _merge_unique_str(merged_queries, bb.get('sample_queries') or [], limit=5)
            reasons = _merge_unique_str(reasons, ([dup.get('notes')] if dup.get('notes') else []), limit=20)
            max_count = max(max_count, int(pc.get('count') or bb.get('observed_count') or 0))
            max_priority = max(max_priority, float(pc.get('priority_score') or bb.get('priority_score') or 0.0))
            min_avg = min(min_avg, float(bb.get('avg_composite_score') or 1.0))
        keeper_pc = dict(keeper_pc)
        keeper_pc.update({'cluster': str(keeper_pc.get('cluster') or _alert_cluster(str(keeper_pc.get('alert') or ''))), 'supporting_alerts': merged_alerts, 'count': max_count, 'priority_score': max_priority})
        keeper_bb = dict(keeper_bb)
        keeper_bb.update({'sample_queries': merged_queries, 'observed_count': max_count, 'avg_composite_score': min_avg, 'priority_score': max_priority, 'supporting_alerts': merged_alerts})
        kept = cognitive_patches.append_revision(str(keeper.get('id') or ''), {
            'proposed_change': keeper_pc,
            'benchmark_before': keeper_bb,
            'evidence_refs': merged_evidence,
            'tags': _merge_unique_str(keeper.get('tags') or [], [f'cluster:{keeper_pc.get("cluster")}', 'deduped_cluster'], limit=20),
            'notes': '; '.join(reasons)[:1200],
        })
        consolidated.append({'patch_id': (kept or keeper).get('id'), 'group': key, 'duplicates': len(items) - 1})
        kept_id = str((kept or keeper).get('id') or '')
        for dup in items[1:]:
            dup_id = str(dup.get('id') or '')
            if not dup_id or dup_id == kept_id:
                continue
            rr = cognitive_patches.reject_patch(dup_id, reason=f'duplicate_cluster:{key}', evidence_refs=[f'deduped_into:{kept_id}'])
            if rr:
                rejected.append({'patch_id': rr.get('id'), 'group': key, 'kept_patch_id': kept_id})
    return {'ok': True, 'consolidated_groups': consolidated, 'duplicates_rejected': rejected}


def scan_recent_failures(limit: int = 80, thresholds: dict[str, int] | None = None):
    rows = _read_jsonl(QUALITY_LOG_PATH)
    rows = rows[-max(1, int(limit)):]
    state = _load_state()
    th = dict(DEFAULT_THRESHOLDS)
    th.update(thresholds or {})

    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        task_type = str(row.get('task_type') or 'unknown')[:80]
        qeval = row.get('quality_eval') if isinstance(row.get('quality_eval'), dict) else {}
        critic = row.get('internal_critic') if isinstance(row.get('internal_critic'), dict) else {}
        alerts = list(qeval.get('alerts') or [])
        ep = critic.get('epistemic') if isinstance(critic.get('epistemic'), dict) else {}
        if bool(critic.get('needs_revision')):
            alerts.append('critic_revision_needed')
        if str(ep.get('confidence_style') or '') == 'overconfident':
            alerts.append('critic_overconfident')
        for alert in alerts:
            key = f'{task_type}|{alert}'
            g = grouped.setdefault(key, {
                'task_type': task_type,
                'alert': str(alert),
                'count': 0,
                'episode_ids': [],
                'sample_queries': [],
                'composite_scores': [],
                'reasons': [],
            })
            g['count'] += 1
            eid = str(row.get('episode_id') or '')
            if eid and eid not in g['episode_ids']:
                g['episode_ids'].append(eid)
            q = str(row.get('query') or '')[:180]
            if q and q not in g['sample_queries'] and len(g['sample_queries']) < 5:
                g['sample_queries'].append(q)
            score = ((qeval.get('composite_score') if isinstance(qeval, dict) else None))
            try:
                if score is not None:
                    g['composite_scores'].append(float(score))
            except Exception:
                pass
            rev_reason = str(ep.get('revision_reason') or '')
            if rev_reason and rev_reason not in g['reasons']:
                g['reasons'].append(rev_reason)

    proposals: list[dict[str, Any]] = []
    merged_into_existing: list[dict[str, Any]] = []
    recent_ids = state.get('recent_patch_ids') if isinstance(state.get('recent_patch_ids'), dict) else {}
    recent_cluster_ids = state.get('recent_cluster_patch_ids') if isinstance(state.get('recent_cluster_patch_ids'), dict) else {}

    eligible_items: list[dict[str, Any]] = []
    for item in grouped.values():
        threshold = int(th.get(item['alert']) or 3)
        if int(item['count']) < threshold:
            continue
        scores = item.get('composite_scores') or []
        avg_score = round(sum(scores) / max(1, len(scores)), 4) if scores else 0.0
        problem = _summarize_problem(item['task_type'], item['alert'])
        cluster = _alert_cluster(item['alert'])
        enriched = dict(item)
        enriched['avg_composite_score'] = avg_score
        enriched['severity'] = float(problem['severity'])
        enriched['priority_score'] = _priority_score(count=int(item['count']), avg_score=avg_score, severity=float(problem['severity']))
        enriched['cluster'] = cluster
        enriched['problem'] = problem
        eligible_items.append(enriched)

    cluster_groups: dict[str, list[dict[str, Any]]] = {}
    for item in eligible_items:
        cluster_key = f"{item['task_type']}|{item['cluster']}"
        cluster_groups.setdefault(cluster_key, []).append(item)

    for cluster_items in cluster_groups.values():
        cluster_items.sort(key=lambda x: (float(x.get('priority_score') or 0.0), int(x.get('count') or 0)), reverse=True)
        canonical_alert = _canonical_alert_for_cluster(cluster_items)
        canonical = next((x for x in cluster_items if str(x.get('alert') or '') == canonical_alert), cluster_items[0])
        task_type = str(canonical.get('task_type') or 'unknown')
        cluster = str(canonical.get('cluster') or 'general')
        dedupe_key = _problem_key(task_type, canonical_alert)
        cluster_dedupe_key = _cluster_key(task_type, cluster)
        existing = _find_open_cluster_patch(task_type, cluster)
        if existing is None and recent_ids.get(dedupe_key):
            existing = cognitive_patches.get_patch(str(recent_ids.get(dedupe_key) or ''))
        if existing is None and recent_cluster_ids.get(cluster_dedupe_key):
            existing = cognitive_patches.get_patch(str(recent_cluster_ids.get(cluster_dedupe_key) or ''))

        cluster_evidence = []
        cluster_queries = []
        cluster_reasons = []
        cluster_count = 0
        weighted_scores: list[float] = []
        supporting_alerts: list[str] = []
        for item in cluster_items:
            cluster_count += int(item.get('count') or 0)
            weighted_scores.extend(item.get('composite_scores') or [])
            cluster_evidence = _merge_unique_str(cluster_evidence, [f"episode:{x}" for x in (item.get('episode_ids') or [])], limit=20)
            cluster_queries = _merge_unique_str(cluster_queries, item.get('sample_queries') or [], limit=5)
            cluster_reasons = _merge_unique_str(cluster_reasons, item.get('reasons') or [], limit=10)
            supporting_alerts = _merge_unique_str(supporting_alerts, [item.get('alert')], limit=10)
        cluster_avg_score = round(sum(weighted_scores) / max(1, len(weighted_scores)), 4) if weighted_scores else float(canonical.get('avg_composite_score') or 0.0)
        cluster_priority = max(float(x.get('priority_score') or 0.0) for x in cluster_items)
        problem = canonical.get('problem') or _summarize_problem(task_type, canonical_alert)

        if existing:
            existing_pc = existing.get('proposed_change') if isinstance(existing.get('proposed_change'), dict) else {}
            merged_pc = dict(existing_pc)
            merged_pc.update({
                'detector': 'gap_detector',
                'task_type': task_type,
                'alert': canonical_alert,
                'cluster': cluster,
                'count': max(int(existing_pc.get('count') or 0), cluster_count),
                'candidate_action': 'investigate_and_patch',
                'priority_score': max(float(existing_pc.get('priority_score') or 0.0), cluster_priority),
                'severity': max(float(existing_pc.get('severity') or 0.0), float(problem.get('severity') or 0.0)),
                'supporting_alerts': supporting_alerts,
            })
            existing_before = existing.get('benchmark_before') if isinstance(existing.get('benchmark_before'), dict) else {}
            merged_before = dict(existing_before)
            merged_before.update({
                'observed_count': max(int(existing_before.get('observed_count') or 0), cluster_count),
                'avg_composite_score': min(float(existing_before.get('avg_composite_score') or 1.0), cluster_avg_score),
                'sample_queries': _merge_unique_str(existing_before.get('sample_queries') or [], cluster_queries, limit=5),
                'priority_score': max(float(existing_before.get('priority_score') or 0.0), cluster_priority),
                'cluster': cluster,
                'supporting_alerts': supporting_alerts,
            })
            revised = cognitive_patches.append_revision(str(existing.get('id') or ''), {
                'hypothesis': (
                    f"Cluster recorrente detectado ({cluster_count} ocorrências agregadas) em task_type={task_type}, "
                    f"cluster={cluster}, alerta canônico={canonical_alert}."
                )[:1200],
                'problem_pattern': f"{task_type}: {problem['title']}",
                'proposed_change': merged_pc,
                'evidence_refs': _merge_unique_str(existing.get('evidence_refs') or [], cluster_evidence, limit=30),
                'benchmark_before': merged_before,
                'tags': _merge_unique_str(existing.get('tags') or [], ['auto-gap', task_type, canonical_alert, f'cluster:{cluster}'], limit=20),
                'notes': '; '.join(_merge_unique_str(([existing.get('notes')] if existing.get('notes') else []), cluster_reasons, limit=10))[:1200],
            })
            if revised:
                merged_into_existing.append({'patch_id': revised.get('id'), 'cluster': cluster, 'task_type': task_type, 'supporting_alerts': supporting_alerts})
                recent_ids[dedupe_key] = revised.get('id')
                recent_cluster_ids[cluster_dedupe_key] = revised.get('id')
            continue

        payload = {
            'kind': problem['kind'],
            'source': 'gap_detector',
            'problem_pattern': f"{task_type}: {problem['title']}",
            'hypothesis': (
                f"Cluster recorrente detectado ({cluster_count} ocorrências agregadas) em task_type={task_type}, "
                f"cluster={cluster}, alerta canônico={canonical_alert}."
            ),
            'proposed_change': {
                'detector': 'gap_detector',
                'task_type': task_type,
                'alert': canonical_alert,
                'cluster': cluster,
                'count': cluster_count,
                'candidate_action': 'investigate_and_patch',
                'priority_score': cluster_priority,
                'severity': float(problem['severity']),
                'supporting_alerts': supporting_alerts,
            },
            'expected_gain': 'Reduzir recorrência do alerta, melhorar qualidade composta e reduzir revisões internas.',
            'risk_level': 'medium',
            'status': 'proposed',
            'evidence_refs': cluster_evidence,
            'benchmark_before': {
                'observed_count': cluster_count,
                'avg_composite_score': cluster_avg_score,
                'sample_queries': cluster_queries[:3],
                'priority_score': cluster_priority,
                'cluster': cluster,
                'supporting_alerts': supporting_alerts,
            },
            'tags': ['auto-gap', task_type, canonical_alert, f'cluster:{cluster}'],
            'notes': '; '.join(cluster_reasons)[:1000],
        }
        created = cognitive_patches.create_patch(payload)
        proposals.append(created)
        recent_ids[dedupe_key] = created.get('id')
        recent_cluster_ids[cluster_dedupe_key] = created.get('id')

    state['last_scan_rows'] = len(rows)
    state['last_alert_counts'] = {k: int(v.get('count') or 0) for k, v in grouped.items()}
    state['recent_patch_ids'] = recent_ids
    state['recent_cluster_patch_ids'] = recent_cluster_ids
    _save_state(state)
    dedupe = consolidate_open_cluster_duplicates()

    ranked_items = []
    for item in grouped.values():
        scores = item.get('composite_scores') or []
        avg_score = round(sum(scores) / max(1, len(scores)), 4) if scores else 0.0
        problem = _summarize_problem(item['task_type'], item['alert'])
        enriched = dict(item)
        enriched['avg_composite_score'] = avg_score
        enriched['severity'] = float(problem['severity'])
        enriched['priority_score'] = _priority_score(count=int(item.get('count') or 0), avg_score=avg_score, severity=float(problem['severity']))
        ranked_items.append(enriched)
    ranked = sorted(ranked_items, key=lambda x: (float(x.get('priority_score') or 0.0), int(x.get('count') or 0)), reverse=True)
    return {
        'ok': True,
        'rows_scanned': len(rows),
        'groups_found': len(grouped),
        'eligible_groups': len(eligible_items),
        'thresholds': th,
        'top_patterns': ranked[:10],
        'proposals_created': proposals,
        'merged_into_existing': merged_into_existing,
        'dedupe': dedupe,
        'state_path': str(STATE_PATH),
        'quality_log_path': str(QUALITY_LOG_PATH),
    }


def maybe_auto_scan(limit: int = 80) -> dict[str, Any]:
    rows = _read_jsonl(QUALITY_LOG_PATH)
    state = _load_state()
    auto = state.get('auto_scan') if isinstance(state.get('auto_scan'), dict) else {}
    every_n_rows = max(1, int(auto.get('every_n_rows') or 5))
    last_auto_scan_row_count = int(auto.get('last_auto_scan_row_count') or 0)
    row_count = len(rows)
    if row_count <= 0:
        return {'ok': True, 'triggered': False, 'reason': 'no_rows'}
    if (row_count - last_auto_scan_row_count) < every_n_rows:
        return {
            'ok': True,
            'triggered': False,
            'reason': 'debounced',
            'row_count': row_count,
            'last_auto_scan_row_count': last_auto_scan_row_count,
            'every_n_rows': every_n_rows,
        }
    result = scan_recent_failures(limit=limit)
    state = _load_state()
    auto = state.get('auto_scan') if isinstance(state.get('auto_scan'), dict) else {}
    auto['every_n_rows'] = every_n_rows
    auto['last_auto_scan_row_count'] = row_count
    state['auto_scan'] = auto
    _save_state(state)
    return {'ok': True, 'triggered': True, 'row_count': row_count, 'result': result}


def run_selftest() -> dict[str, Any]:
    global QUALITY_LOG_PATH, STATE_PATH
    old_quality = QUALITY_LOG_PATH
    old_state = STATE_PATH
    old_patch_path = cognitive_patches.PATCHES_PATH
    old_patch_state = cognitive_patches.STATE_PATH
    with tempfile.TemporaryDirectory(prefix='gap-detector-') as td:
        base = Path(td)
        QUALITY_LOG_PATH = base / 'quality_eval.jsonl'
        STATE_PATH = base / 'gap_detector_state.json'
        cognitive_patches.PATCHES_PATH = base / 'cognitive_patches.jsonl'
        cognitive_patches.STATE_PATH = base / 'cognitive_patches_state.json'
        try:
            rows = [
                {
                    'ts': _now(),
                    'query': 'Como corrigir timeout no planner?',
                    'task_type': 'planning',
                    'episode_id': 'ep1',
                    'quality_eval': {
                        'composite_score': 0.41,
                        'alerts': ['quality_score_below_threshold', 'groundedness_low'],
                    },
                    'internal_critic': {
                        'needs_revision': True,
                        'epistemic': {
                            'confidence_style': 'overconfident',
                            'revision_reason': 'low_grounding_or_high_contradiction_risk',
                        },
                    },
                },
                {
                    'ts': _now(),
                    'query': 'Como corrigir timeout no planner em produção?',
                    'task_type': 'planning',
                    'episode_id': 'ep2',
                    'quality_eval': {
                        'composite_score': 0.39,
                        'alerts': ['quality_score_below_threshold', 'groundedness_low'],
                    },
                    'internal_critic': {
                        'needs_revision': True,
                        'epistemic': {
                            'confidence_style': 'overconfident',
                            'revision_reason': 'low_grounding_or_high_contradiction_risk',
                        },
                    },
                },
                {
                    'ts': _now(),
                    'query': 'Planner ainda responde com confiança alta sem base?',
                    'task_type': 'planning',
                    'episode_id': 'ep3',
                    'quality_eval': {
                        'composite_score': 0.36,
                        'alerts': ['quality_score_below_threshold'],
                    },
                    'internal_critic': {
                        'needs_revision': True,
                        'epistemic': {
                            'confidence_style': 'overconfident',
                            'revision_reason': 'missing_gap_disclosure',
                        },
                    },
                },
            ]
            QUALITY_LOG_PATH.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows), encoding='utf-8')
            result = scan_recent_failures(limit=20)
            created = result.get('proposals_created') if isinstance(result.get('proposals_created'), list) else []
            patches = cognitive_patches.list_patches(limit=20)
            return {
                'ok': True,
                'rows_seeded': len(rows),
                'proposals_created': len(created),
                'created_patch_ids': [str(x.get('id') or '') for x in created],
                'top_patterns': result.get('top_patterns') or [],
                'registry_count': len(patches),
            }
        finally:
            QUALITY_LOG_PATH = old_quality
            STATE_PATH = old_state
            cognitive_patches.PATCHES_PATH = old_patch_path
            cognitive_patches.STATE_PATH = old_patch_state
