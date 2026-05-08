"""
Sleep Cycle v2 — Consolidação de Episódios em Conhecimento Causal Real
=======================================================================
Fontes de episódios corrigidas:
  - events(kind='action_done') no SQLite  — 2200+ ações executadas
  - episodic_audit.jsonl                  — 730+ com quality/latency/outcome

O compilador de abstrações causais (episodic_compiler.py) é chamado
diretamente, produzindo hipóteses falsificáveis em vez de regras heurísticas.
"""

import json
import hashlib
import os
import time
from pathlib import Path
from typing import Any

EPISODIC_PATH = Path(__file__).resolve().parent.parent / 'data' / 'episodic_memory.jsonl'
EPISODIC_ARCHIVE_PATH = Path(__file__).resolve().parent.parent / 'data' / 'episodic_memory_archive.jsonl'
ABSTRACTIONS_PATH = Path(__file__).resolve().parent.parent / 'data' / 'episodic_abstractions.json'
REPORT_PATH = Path(__file__).resolve().parent.parent / 'data' / 'sleep_cycle_report.json'
AUDIT_PATH = Path(__file__).resolve().parent.parent / 'data' / 'episodic_audit.jsonl'
SLEEP_DIGEST_LOG_PATH = Path(__file__).resolve().parent.parent / 'data' / 'sleep_episodic_digests.jsonl'
SLEEP_DIGEST_STATE_PATH = Path(__file__).resolve().parent.parent / 'data' / 'sleep_episodic_digest_state.json'

# ── Configuração ──────────────────────────────────────────────────────────────
MIN_GROUP_FOR_COMPILATION = 3      # mínimo de episódios por grupo para compilar
RECENT_HOURS = 48                  # janela de busca de episódios recentes
MAX_NEW_ABSTRACTIONS_PER_CYCLE = 5 # cap para não sobrecarregar LLM

CLOSED_DOMAINS = {
    'sandbox_financeiro', 'fs_com_rollback', 'interacoes_codigo',
    'busca_autonoma', 'fs_operations', 'api_gateway',
    'decision_planning', 'drone_navigation', 'meta_reasoning',
}

MAX_ACTIVE_INVESTIGATION_EXPERIMENTS_PER_CYCLE = 3


# ── Funções de carregamento ───────────────────────────────────────────────────

def _env_int(name: str, default: int, *, low: int = 0, high: int = 50) -> int:
    try:
        value = int(os.getenv(name, str(default)) or default)
    except Exception:
        value = default
    return max(low, min(high, value))


def _causal_edge_count() -> int | None:
    try:
        from ultronpro import causal_graph

        graph = causal_graph.load_graph()
        edges = graph.get('edges') if isinstance(graph, dict) else {}
        return len(edges) if isinstance(edges, dict) else 0
    except Exception:
        return None


def _compact_investigation_result(row: dict[str, Any]) -> dict[str, Any]:
    experiment = row.get('experiment') if isinstance(row.get('experiment'), dict) else {}
    result = row.get('experiment_result') if isinstance(row.get('experiment_result'), dict) else {}
    edge = result.get('edge') if isinstance(result.get('edge'), dict) else {}
    return {
        'investigation_id': row.get('investigation_id'),
        'ok': bool(row.get('ok')),
        'injected': bool(row.get('injected')),
        'error': row.get('error'),
        'experiment_kind': experiment.get('kind') or result.get('experiment_kind'),
        'target_route': experiment.get('target_route') or result.get('target_route'),
        'query_terms': result.get('query_terms') if isinstance(result.get('query_terms'), list) else experiment.get('query_terms'),
        'edge': {
            'cause': edge.get('cause'),
            'effect': edge.get('effect'),
            'condition': edge.get('condition'),
        } if edge else {},
    }


def _run_active_investigation_cycle(max_experiments: int | None = None) -> dict[str, Any]:
    """Consume pending causal-gap experiments during offline consolidation."""
    max_experiments = (
        _env_int(
            'ULTRON_SLEEP_ACTIVE_INVESTIGATION_LIMIT',
            MAX_ACTIVE_INVESTIGATION_EXPERIMENTS_PER_CYCLE,
            low=0,
            high=20,
        )
        if max_experiments is None
        else max(0, min(20, int(max_experiments)))
    )
    if max_experiments <= 0:
        return {
            'ok': True,
            'enabled': False,
            'epistemic_gap_perception': {'ok': True, 'enabled': False, 'seeded': 0},
            'pending_before': 0,
            'executed': 0,
            'injected': 0,
            'failed': 0,
            'coverage_delta_edges': 0,
            'coverage_gained': False,
            'items': [],
        }

    before_edges = _causal_edge_count()
    try:
        from ultronpro import active_investigation

        seed_report = {'ok': True, 'enabled': True, 'seeded': 0, 'reason': 'pending_queue_not_empty'}
        pending_preseed = active_investigation.pending_experiments(limit=max_experiments)
        if not pending_preseed:
            try:
                from ultronpro import epistemic_curiosity

                gaps = epistemic_curiosity.collect_epistemic_gaps(use_cache=False)
                seed_report = active_investigation.seed_epistemic_gap_experiments(
                    gaps,
                    limit=max_experiments,
                    source='sleep_cycle_epistemic_gap_scan',
                )
            except Exception as seed_exc:
                seed_report = {
                    'ok': False,
                    'enabled': True,
                    'seeded': 0,
                    'error': f'{type(seed_exc).__name__}:{str(seed_exc)[:180]}',
                }

        pending_before = active_investigation.pending_experiments(limit=max_experiments)
        batch = active_investigation.execute_pending_experiments(limit=max_experiments)
    except Exception as exc:
        return {
            'ok': False,
            'enabled': True,
            'epistemic_gap_perception': {'ok': False, 'enabled': True, 'seeded': 0, 'error': f'{type(exc).__name__}:{str(exc)[:180]}'},
            'pending_before': 0,
            'executed': 0,
            'injected': 0,
            'failed': 1,
            'coverage_delta_edges': 0,
            'coverage_gained': False,
            'items': [],
            'error': f'{type(exc).__name__}:{str(exc)[:180]}',
        }

    after_edges = _causal_edge_count()
    if before_edges is None or after_edges is None:
        edge_delta = 0
    else:
        edge_delta = max(0, int(after_edges) - int(before_edges))

    raw_results = batch.get('results') if isinstance(batch.get('results'), list) else []
    injected = int(batch.get('injected') or 0)
    return {
        'ok': bool(batch.get('ok')),
        'enabled': True,
        'epistemic_gap_perception': seed_report,
        'pending_before': len(pending_before),
        'executed': int(batch.get('executed') or 0),
        'injected': injected,
        'failed': int(batch.get('failed') or 0),
        'coverage_delta_edges': edge_delta,
        'coverage_gained': injected > 0 or edge_delta > 0,
        'items': [_compact_investigation_result(row) for row in raw_results[:max_experiments]],
        'reason': batch.get('reason'),
    }


def _tokens(text: str) -> set[str]:
    import re
    return {t for t in re.findall(r"[a-zA-ZÀ-ÿ0-9_]{4,}", (text or '').lower())}


def _day_key(ts: float | None = None) -> str:
    tm = time.localtime(ts or time.time())
    return f"{tm.tm_year:04d}-{tm.tm_mon:02d}-{tm.tm_mday:02d}"


def _read_json(path: Path, default: Any = None) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding='utf-8', errors='ignore'))
    except Exception:
        pass
    return default


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding='utf-8')


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as fh:
        fh.write(json.dumps(payload, ensure_ascii=False, default=str) + '\n')


def _load_episodes_from_jsonl() -> list[dict[str, Any]]:
    """Carrega o JSONL legado (usado apenas para pruning, não para abstração)."""
    if not EPISODIC_PATH.exists():
        return []
    out = []
    for ln in EPISODIC_PATH.read_text(encoding='utf-8', errors='ignore').splitlines():
        if not ln.strip():
            continue
        try:
            out.append(json.loads(ln))
        except Exception:
            continue
    return out


def _load_recent_action_episodes(hours: int = RECENT_HOURS) -> list[dict[str, Any]]:
    """
    Carrega episódios de ações realmente executadas de duas fontes:
    1. events(kind='action_done') no SQLite — 2200+ registros com outcome/kind
    2. episodic_audit.jsonl — 730+ registros com tool/task_type/outcome/latency
    """
    episodes = []
    cutoff = time.time() - hours * 3600

    # Fonte 1: events(action_done) no SQLite
    try:
        from ultronpro import store
        import sqlite3
        conn = sqlite3.connect(str(store.DB_PATH))
        c = conn.cursor()
        rows = c.execute(
            "SELECT created_at, kind, text, meta_json FROM events "
            "WHERE kind='action_done' AND created_at >= ? ORDER BY created_at DESC LIMIT 500",
            (cutoff,)
        ).fetchall()
        conn.close()
        for created_at, kind, text, meta_json in rows:
            ep = {'ts': created_at, 'kind': kind, 'text': text, 'source': 'events_db'}
            if meta_json:
                try:
                    ep.update(json.loads(meta_json))
                except Exception:
                    pass
            episodes.append(ep)
    except Exception:
        pass

    # Fonte 2: episodic_audit.jsonl
    try:
        if AUDIT_PATH.exists():
            for ln in AUDIT_PATH.read_text(encoding='utf-8', errors='ignore').splitlines():
                if not ln.strip():
                    continue
                try:
                    d = json.loads(ln)
                    ts = float(d.get('ts') or 0)
                    if ts >= cutoff:
                        d['source'] = 'episodic_audit'
                        episodes.append(d)
                except Exception:
                    continue
    except Exception:
        pass

    return episodes


def _infer_domain(ep: dict) -> str:
    """Infere domínio causal de um episódio a partir de tool/kind/text."""
    tool = str(ep.get('tool') or ep.get('action_kind') or '').lower()
    kind = str(ep.get('kind') or ep.get('task_type') or '').lower()
    text = str(ep.get('text') or '').lower()[:200]

    if any(x in tool for x in ('read_file', 'write_file', 'delete', 'list_dir', 'fs')):
        return 'fs_operations'
    if any(x in tool for x in ('browse', 'web', 'http', 'search', 'fetch', 'url')):
        return 'busca_autonoma'
    if any(x in tool for x in ('run_command', 'bash', 'python', 'code', 'exec', 'terminal')):
        return 'interacoes_codigo'
    if any(x in kind for x in ('review', 'conflict', 'judge', 'reasoning', 'audit')):
        return 'meta_reasoning'
    if any(x in text for x in ('financ', 'mercado', 'cripto', 'trade', 'bolsa')):
        return 'sandbox_financeiro'
    return kind or tool or 'general'


def _outcome_ok(ep: dict) -> bool:
    outcome = str(ep.get('outcome') or ep.get('result') or '').lower()
    if outcome in ('success', 'ok', 'done', 'true', '1', 'increase'):
        return True
    # Parse text field for action_done events (format: "action X: outcome=Y")
    text = str(ep.get('text') or '').lower()
    if 'outcome=success' in text or 'outcome=ok' in text or 'completed' in text:
        return True
    if 'error' in text or 'fail' in text or 'timeout' in text:
        return False
    # accepted field from episodic_audit
    accepted = ep.get('accepted')
    if accepted is not None:
        return bool(accepted)
    return True  # default: assume ok if no signal


_QUALITY_STR_MAP = {
    'excellent': 0.1,  # low surprise (high quality)
    'strong': 0.15,
    'good': 0.2,
    'acceptable': 0.35,
    'weak': 0.6,
    'poor': 0.75,
    'bad': 0.85,
    'failed': 0.95,
}


def _surprise_from_ep(ep: dict) -> float:
    """Converte quality para surpresa (inverso). Tolera strings semanticas."""
    quality = ep.get('quality')
    if quality is not None:
        if isinstance(quality, (int, float)):
            return max(0.0, 1.0 - float(quality))
        # String semantica do avaliador de qualidade
        q_str = str(quality).lower().strip()
        return _QUALITY_STR_MAP.get(q_str, 0.3)
    return float(ep.get('surprise') or ep.get('surprise_score') or 0.25)


def _group_episodes(episodes: list[dict]) -> dict[str, list[dict]]:
    """Agrupa episódios por (domain, tool/kind)."""
    groups: dict[str, list[dict]] = {}
    for ep in episodes:
        domain = _infer_domain(ep)
        tool = str(ep.get('tool') or ep.get('kind') or 'unknown')
        key = f"{domain}|{tool}"
        groups.setdefault(key, []).append(ep)
    return groups


def _append_archive(rows: list[dict[str, Any]]):
    if not rows:
        return
    EPISODIC_ARCHIVE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with EPISODIC_ARCHIVE_PATH.open('a', encoding='utf-8') as fp:
        for r in rows:
            fp.write(json.dumps(r, ensure_ascii=False) + '\n')


# ── Ciclo principal ───────────────────────────────────────────────────────────

def _episode_fingerprint(ep: dict[str, Any]) -> str:
    material = json.dumps(
        {
            'source': ep.get('source'),
            'ts': ep.get('ts') or ep.get('created_at'),
            'kind': ep.get('kind') or ep.get('task_type'),
            'tool': ep.get('tool') or ep.get('action_kind'),
            'text': str(ep.get('text') or ep.get('query') or ep.get('problem') or '')[:420],
            'outcome': ep.get('outcome') or ep.get('result'),
        },
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    return hashlib.sha1(material.encode('utf-8', errors='ignore')).hexdigest()[:16]


def _recent_structured_enrichment_fingerprints(limit: int = 1200) -> set[str]:
    try:
        from ultronpro import episodic_memory

        seen: set[str] = set()
        for row in episodic_memory.recent_structured(limit=limit):
            epi = row.get('episodic_memory') if isinstance(row.get('episodic_memory'), dict) else {}
            ctx = epi.get('contexto_entrada') if isinstance(epi.get('contexto_entrada'), dict) else {}
            fp = str(ctx.get('sleep_enrichment_fingerprint') or '').strip()
            if fp:
                seen.add(fp)
        return seen
    except Exception:
        return set()


def _episode_task_type(ep: dict[str, Any], domain: str) -> str:
    text = f"{ep.get('task_type') or ''} {ep.get('kind') or ''} {domain} {ep.get('text') or ''}".lower()
    if any(x in text for x in ('debug', 'erro', 'falha', 'bug', 'traceback')):
        return 'debug'
    if any(x in text for x in ('deploy', 'rollback', 'fs_', 'arquivo', 'bash', 'python', 'exec', 'command')):
        return 'operations'
    if any(x in text for x in ('planej', 'plano', 'decis', 'policy', 'estrateg')):
        return 'planning'
    return str(ep.get('task_type') or domain or 'general')[:48]


def _episode_summary_text(ep: dict[str, Any]) -> str:
    text = str(ep.get('text') or ep.get('query') or ep.get('problem') or '').strip()
    if not text:
        bits = [
            str(ep.get('tool') or ep.get('action_kind') or ep.get('kind') or '').strip(),
            str(ep.get('outcome') or ep.get('result') or '').strip(),
            str(ep.get('error') or '').strip(),
        ]
        text = ' '.join(x for x in bits if x)
    return text[:620] if text else 'episodio operacional sem texto rico'


def _select_enrichment_candidates(
    *,
    action_episodes: list[dict[str, Any]],
    fresh_jsonl: list[dict[str, Any]],
    limit: int,
) -> tuple[list[dict[str, Any]], int]:
    seen = _recent_structured_enrichment_fingerprints()
    selected: list[dict[str, Any]] = []
    skipped_duplicates = 0
    combined: list[dict[str, Any]] = []
    for ep in action_episodes or []:
        if isinstance(ep, dict):
            combined.append(dict(ep))
    for ep in fresh_jsonl or []:
        if isinstance(ep, dict):
            row = dict(ep)
            row.setdefault('source', 'episodic_memory_jsonl')
            combined.append(row)

    combined.sort(key=lambda item: float(item.get('ts') or item.get('created_at') or 0), reverse=True)
    local_seen: set[str] = set()
    for ep in combined:
        fp = _episode_fingerprint(ep)
        if fp in seen or fp in local_seen:
            skipped_duplicates += 1
            continue
        if len(_tokens(_episode_summary_text(ep))) < 2:
            continue
        local_seen.add(fp)
        ep['sleep_enrichment_fingerprint'] = fp
        selected.append(ep)
        if len(selected) >= limit:
            break
    return selected, skipped_duplicates


def _run_episodic_enrichment_cycle(
    *,
    action_episodes: list[dict[str, Any]],
    fresh_jsonl: list[dict[str, Any]],
    groups: dict[str, list[dict[str, Any]]],
    abstractions_compiled: int,
) -> dict[str, Any]:
    """Create structured recall episodes when causal abstraction would otherwise be silent."""
    enabled = str(os.getenv('ULTRON_SLEEP_EPISODIC_ENRICHMENT_ENABLED', '1')).strip().lower() not in ('0', 'false', 'no', 'off')
    if not enabled:
        return {'ok': True, 'enabled': False, 'records_created': 0, 'reason': 'episodic_enrichment_disabled'}

    max_records = _env_int('ULTRON_SLEEP_EPISODIC_ENRICHMENT_LIMIT', 5, low=0, high=25)
    if max_records <= 0:
        return {'ok': True, 'enabled': True, 'records_created': 0, 'reason': 'episodic_enrichment_limit_zero'}

    force_when_abstracted = str(os.getenv('ULTRON_SLEEP_EPISODIC_ENRICH_WHEN_ABSTRACTED', '0')).strip().lower() in ('1', 'true', 'yes', 'on')
    if abstractions_compiled > 0 and not force_when_abstracted:
        return {
            'ok': True,
            'enabled': True,
            'records_created': 0,
            'reason': 'causal_abstraction_already_progressed',
            'source_episode_count': len(action_episodes or []) + len(fresh_jsonl or []),
            'group_count': len(groups or {}),
        }

    candidates, skipped_duplicates = _select_enrichment_candidates(
        action_episodes=action_episodes,
        fresh_jsonl=fresh_jsonl,
        limit=max_records,
    )
    created = 0
    items: list[dict[str, Any]] = []
    errors: list[str] = []
    try:
        from ultronpro import episodic_memory, store
    except Exception as exc:
        return {
            'ok': False,
            'enabled': True,
            'records_created': 0,
            'error': f'{type(exc).__name__}:{str(exc)[:180]}',
        }

    for ep in candidates:
        try:
            domain = _infer_domain(ep)
            action_kind = str(ep.get('tool') or ep.get('action_kind') or ep.get('kind') or 'observacao_operacional')[:80]
            ok = _outcome_ok(ep)
            surprise = _surprise_from_ep(ep)
            text = _episode_summary_text(ep)
            fp = str(ep.get('sleep_enrichment_fingerprint') or _episode_fingerprint(ep))
            task_type = _episode_task_type(ep, domain)
            outcome = str(ep.get('outcome') or ep.get('result') or ('success' if ok else 'failure'))
            latency_ms = max(1, int(float(ep.get('latency_ms') or ep.get('duration_ms') or 1)))
            problem = f"Consolidar episodio operacional de {domain}: {text}"
            resultado = (
                f"Resultado observado no ciclo de sono: outcome={outcome}; ok={bool(ok)}; "
                f"surpresa={round(float(surprise), 4)}; fonte={ep.get('source') or 'unknown'}."
            )
            hipotese = (
                f"Em {domain}, a acao {action_kind} merece recall futuro quando perguntas compartilham "
                "tokens, risco ou resultado operacional com este episodio."
            )
            episodic_memory.append_structured_episode(
                problem=problem,
                plano_gerado={
                    'source': 'sleep_cycle_episodic_enrichment',
                    'source_episode_fingerprint': fp,
                    'domain': domain,
                    'action_kind': action_kind,
                },
                passos_executados=[
                    {
                        'tool': action_kind,
                        'source': ep.get('source') or 'unknown',
                        'outcome': outcome,
                        'ok': bool(ok),
                    }
                ],
                resultado=resultado,
                prm_score_final=(float(ep.get('prm_score') or ep.get('prm_score_final')) if isinstance(ep.get('prm_score') or ep.get('prm_score_final'), (int, float)) else None),
                hipotese_pos_hoc=hipotese,
                contexto_entrada={
                    'preflight_domain_mode': domain,
                    'sleep_cycle_source': ep.get('source') or 'unknown',
                    'sleep_enrichment_fingerprint': fp,
                    'compiler_group_size': len((groups or {}).get(f'{domain}|{action_kind}', [])),
                    'quiet_gap_context': 'abstracted_zero_fallback',
                },
                acao_granular={
                    'kind': action_kind,
                    'tool': ep.get('tool') or '',
                    'raw_kind': ep.get('kind') or '',
                },
                resultado_objetivo={
                    'ok': bool(ok),
                    'outcome': outcome,
                    'source': ep.get('source') or 'unknown',
                },
                contrafactual_estimado={
                    'if_not_consolidated': 'episodic_recall_remains_static',
                    'expected_effect': 'future_cognitive_core_answers_have_less_episode_diversity',
                },
                surpresa_calculada=float(surprise),
                invariante_instanciado=f'{domain}:{action_kind}:sleep_enriched_recall',
                task_type=task_type,
                strategy='sleep_cycle_episodic_enrichment',
                ok=bool(ok),
                latency_ms=latency_ms,
                work_context={'source': 'sleep_cycle', 'fingerprint': fp, 'domain': domain},
                quality_eval={'sleep_cycle_enrichment': True, 'surprise': float(surprise), 'source_quality': ep.get('quality')},
                memory_governor={
                    'fact': resultado,
                    'hypothesis': hipotese,
                    'plan': 'usar este episodio como evidencia recuperavel, nao como regra universal',
                    'interpretation': 'enriquecimento noturno contra estagnacao episodica',
                },
                authorship_origin='sleep_cycle',
            )
            created += 1
            items.append({'fingerprint': fp, 'domain': domain, 'action_kind': action_kind, 'task_type': task_type, 'ok': bool(ok)})
        except Exception as exc:
            errors.append(f'{type(exc).__name__}:{str(exc)[:160]}')

    if created:
        try:
            store.publish_workspace(
                module='sleep_cycle',
                channel='memory.episodic_enrichment',
                payload_json=json.dumps({'records_created': created, 'items': items[:8]}, ensure_ascii=False),
                salience=0.74,
                ttl_sec=3600,
            )
        except Exception:
            pass

    return {
        'ok': not errors or created > 0,
        'enabled': True,
        'records_created': created,
        'eligible_candidates': len(candidates),
        'skipped_duplicates': skipped_duplicates,
        'source_episode_count': len(action_episodes or []) + len(fresh_jsonl or []),
        'group_count': len(groups or {}),
        'items': items,
        'errors': errors[:5],
        'reason': 'enriched_structured_episodic_memory' if created else 'no_eligible_episodes_for_enrichment',
    }


def _digest_keywords(episodes: list[dict[str, Any]], limit: int = 10) -> list[str]:
    counts: dict[str, int] = {}
    for ep in episodes:
        for token in _tokens(_episode_summary_text(ep)):
            if token in {'action', 'done', 'success', 'unknown', 'episodio', 'operacional'}:
                continue
            counts[token] = counts.get(token, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [token for token, _ in ranked[: max(1, int(limit or 1))]]


def _build_digest_themes(
    *,
    action_episodes: list[dict[str, Any]],
    fresh_jsonl: list[dict[str, Any]],
    groups: dict[str, list[dict[str, Any]]],
    limit: int = 6,
) -> list[dict[str, Any]]:
    combined_groups = dict(groups or {})
    if not combined_groups and fresh_jsonl:
        combined_groups = _group_episodes(fresh_jsonl)

    themes: list[dict[str, Any]] = []
    for group_key, eps in sorted(combined_groups.items(), key=lambda kv: len(kv[1]), reverse=True):
        if not eps:
            continue
        domain, action_kind = (group_key.split('|', 1) + ['unknown'])[:2] if '|' in group_key else (group_key, 'unknown')
        annotated = [(ep, _outcome_ok(ep), _surprise_from_ep(ep)) for ep in eps]
        ok_count = sum(1 for _, ok, _ in annotated if ok)
        surprise_mean = sum(float(surp) for _, _, surp in annotated) / max(1, len(annotated))
        examples = [
            _episode_summary_text(ep)[:180]
            for ep, _, _ in sorted(annotated, key=lambda row: float(row[2]))[:3]
        ]
        themes.append({
            'domain': domain,
            'action_kind': str(action_kind)[:80],
            'episode_count': len(eps),
            'ok_count': ok_count,
            'failure_count': max(0, len(eps) - ok_count),
            'mean_surprise': round(surprise_mean, 4),
            'keywords': _digest_keywords(eps, limit=8),
            'examples': examples,
        })
        if len(themes) >= limit:
            break

    if not themes and action_episodes:
        themes.append({
            'domain': 'general',
            'action_kind': 'mixed_operational_memory',
            'episode_count': len(action_episodes),
            'ok_count': sum(1 for ep in action_episodes if _outcome_ok(ep)),
            'failure_count': sum(1 for ep in action_episodes if not _outcome_ok(ep)),
            'mean_surprise': round(sum(_surprise_from_ep(ep) for ep in action_episodes) / max(1, len(action_episodes)), 4),
            'keywords': _digest_keywords(action_episodes, limit=8),
            'examples': [_episode_summary_text(ep)[:180] for ep in action_episodes[:3]],
        })
    return themes


def _run_nightly_episodic_digest(
    *,
    now: int,
    pruned: int,
    abstractions_compiled: int,
    abstractions_tested: int,
    action_episodes: list[dict[str, Any]],
    fresh_jsonl: list[dict[str, Any]],
    groups: dict[str, list[dict[str, Any]]],
    sql_consolidation: dict[str, Any],
    episodic_enrichment: dict[str, Any],
    causal_gap_investigation: dict[str, Any],
    preliminary_stagnation: dict[str, Any],
) -> dict[str, Any]:
    """Persist a nightly episodic digest as recallable memory, not just a report."""
    enabled = str(os.getenv('ULTRON_SLEEP_NIGHTLY_DIGEST_ENABLED', '1')).strip().lower() not in ('0', 'false', 'no', 'off')
    if not enabled:
        return {'ok': True, 'enabled': False, 'recorded': False, 'reason': 'nightly_digest_disabled'}

    enrichment_count = int((episodic_enrichment or {}).get('records_created') or 0)
    active_executed = int((causal_gap_investigation or {}).get('executed') or 0)
    active_injected = int((causal_gap_investigation or {}).get('injected') or 0)
    promoted = int((sql_consolidation or {}).get('promoted_to_episodic') or 0)
    source_count = (
        len(action_episodes or [])
        + len(fresh_jsonl or [])
        + int(pruned or 0)
        + int(abstractions_compiled or 0)
        + enrichment_count
        + active_executed
        + active_injected
        + promoted
    )
    if source_count <= 0:
        return {
            'ok': True,
            'enabled': True,
            'recorded': False,
            'reason': 'no_episodic_material_for_digest',
            'source_count': 0,
            'stagnation_status': (preliminary_stagnation or {}).get('status'),
        }

    day = _day_key(now)
    themes = _build_digest_themes(
        action_episodes=action_episodes,
        fresh_jsonl=fresh_jsonl,
        groups=groups,
    )
    core = {
        'day': day,
        'pruned': int(pruned or 0),
        'abstracted': int(abstractions_compiled or 0),
        'abstractions_tested': int(abstractions_tested or 0),
        'sql_promoted_to_episodic': promoted,
        'episodic_enrichment_records': enrichment_count,
        'active_investigation_executed': active_executed,
        'active_investigation_injected': active_injected,
        'stagnation_status': (preliminary_stagnation or {}).get('status'),
        'themes': themes,
    }
    checksum = hashlib.sha256(json.dumps(core, ensure_ascii=False, sort_keys=True, default=str).encode('utf-8')).hexdigest()[:16]
    digest_id = f"sleep_digest_{day}_{checksum}"
    previous = _read_json(SLEEP_DIGEST_STATE_PATH, {})
    if isinstance(previous, dict) and previous.get('id') == digest_id and previous.get('structured_episode_id'):
        return {
            'ok': True,
            'enabled': True,
            'recorded': False,
            'reason': 'nightly_digest_already_current',
            'id': digest_id,
            'checksum': checksum,
            'source_count': source_count,
            'theme_count': len(themes),
        }

    digest = {
        'ok': True,
        'id': digest_id,
        'schema': 'ultron.sleep_episodic_digest.v1',
        'ts': now,
        'day': day,
        'checksum': checksum,
        'source_count': source_count,
        **core,
    }
    _append_jsonl(SLEEP_DIGEST_LOG_PATH, digest)
    _write_json(SLEEP_DIGEST_STATE_PATH, digest)

    theme_text = '; '.join(
        f"{t['domain']}/{t['action_kind']} ({t['episode_count']} eps, keywords={', '.join(t.get('keywords') or [])})"
        for t in themes[:4]
    ) or 'sem temas operacionais densos'
    result_text = (
        f"Digest noturno {day}: pruned={pruned}, abstracted={abstractions_compiled}, "
        f"enrichment={enrichment_count}, active_investigation={active_executed}/{active_injected}. "
        f"Temas: {theme_text}."
    )
    structured_episode_id = None
    try:
        from ultronpro import episodic_memory, store

        rec = episodic_memory.append_structured_episode(
            problem=f"Digest noturno da memoria episodica ({day}): {theme_text}",
            plano_gerado={
                'source': 'sleep_cycle_nightly_digest',
                'digest_id': digest_id,
                'checksum': checksum,
                'source_count': source_count,
            },
            passos_executados=[
                {
                    'tool': 'sleep_cycle_digest',
                    'source_count': source_count,
                    'theme_count': len(themes),
                    'stagnation_status': (preliminary_stagnation or {}).get('status'),
                }
            ],
            resultado=result_text,
            prm_score_final=None,
            hipotese_pos_hoc=(
                'Perguntas futuras sobre os temas do ciclo devem recuperar este digest como mapa episodico '
                'antes de responder com o mesmo conjunto antigo de episodios.'
            ),
            contexto_entrada={
                'preflight_domain_mode': 'episodic_memory',
                'sleep_digest_id': digest_id,
                'sleep_digest_checksum': checksum,
                'sleep_day': day,
                'quiet_gap': bool((preliminary_stagnation or {}).get('quiet_gap')),
                'stagnation_status_before_digest': (preliminary_stagnation or {}).get('status'),
            },
            acao_granular={'kind': 'nightly_episodic_digest', 'tool': 'sleep_cycle'},
            resultado_objetivo={
                'ok': True,
                'digest_id': digest_id,
                'themes': themes,
                'source_count': source_count,
            },
            contrafactual_estimado={
                'if_digest_missing': 'episodic_memory_recalls_same_old_episode_set',
                'expected_effect': 'future_non_llm_core_has_richer_recall_surface',
            },
            surpresa_calculada=0.2 if themes else 0.55,
            invariante_instanciado='sleep_cycle:nightly_digest:episodic_recall_enrichment',
            task_type='memory',
            strategy='sleep_cycle_nightly_digest',
            ok=True,
            latency_ms=1,
            work_context={'source': 'sleep_cycle', 'digest_id': digest_id, 'day': day},
            quality_eval={'sleep_digest': True, 'theme_count': len(themes), 'source_count': source_count},
            memory_governor={
                'fact': result_text,
                'hypothesis': 'digest noturno aumenta diversidade de recall episodico',
                'plan': 'usar como mapa de memoria; nao como lei causal universal',
                'interpretation': 'consolidacao noturna contra estagnacao episodica',
            },
            authorship_origin='sleep_cycle',
        )
        structured_episode_id = rec.get('episode_id') if isinstance(rec, dict) else None
        try:
            store.publish_workspace(
                module='sleep_cycle',
                channel='memory.sleep_digest',
                payload_json=json.dumps({'digest_id': digest_id, 'themes': themes[:4], 'source_count': source_count}, ensure_ascii=False),
                salience=0.78,
                ttl_sec=7200,
            )
        except Exception:
            pass
    except Exception as exc:
        digest['structured_episode_error'] = f'{type(exc).__name__}:{str(exc)[:180]}'
        _write_json(SLEEP_DIGEST_STATE_PATH, digest)
        return {
            'ok': False,
            'enabled': True,
            'recorded': True,
            'id': digest_id,
            'checksum': checksum,
            'source_count': source_count,
            'theme_count': len(themes),
            'error': digest['structured_episode_error'],
        }

    digest['structured_episode_id'] = structured_episode_id
    _write_json(SLEEP_DIGEST_STATE_PATH, digest)
    return {
        'ok': True,
        'enabled': True,
        'recorded': True,
        'id': digest_id,
        'checksum': checksum,
        'source_count': source_count,
        'theme_count': len(themes),
        'structured_episode_id': structured_episode_id,
        'themes': themes[:4],
        'reason': 'nightly_episodic_digest_recorded',
    }


def _memory_stagnation_signal(
    *,
    pruned: int,
    abstractions_compiled: int,
    action_episodes: list[dict[str, Any]],
    groups: dict[str, list[dict[str, Any]]],
    episodic_enrichment: dict[str, Any],
    nightly_digest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    quiet = int(pruned or 0) == 0 and int(abstractions_compiled or 0) == 0
    below_min = sum(1 for eps in (groups or {}).values() if len(eps) < MIN_GROUP_FOR_COMPILATION)
    created = int((episodic_enrichment or {}).get('records_created') or 0)
    digest_recorded = bool((nightly_digest or {}).get('recorded'))
    if not quiet:
        status = 'healthy_progress'
    elif created > 0:
        status = 'recovered_by_episodic_enrichment'
    elif digest_recorded:
        status = 'recovered_by_nightly_digest'
    else:
        status = 'stagnant_memory'
    return {
        'ok': status != 'stagnant_memory',
        'status': status,
        'quiet_gap': quiet,
        'reason': 'sleep_cycle_had_no_prune_or_abstraction' if quiet else 'sleep_cycle_produced_prune_or_abstraction',
        'action_episode_count': len(action_episodes or []),
        'group_count': len(groups or {}),
        'groups_below_min': below_min,
        'min_group_episodes': MIN_GROUP_FOR_COMPILATION,
        'episodic_enrichment_records': created,
        'nightly_digest_recorded': digest_recorded,
        'nightly_digest_id': (nightly_digest or {}).get('id'),
        'next_step': (
            'increase_episode_diversity_or_run_active_gap_interventions'
            if status == 'stagnant_memory'
            else 'continue_nightly_consolidation'
        ),
    }


def run_cycle(retention_days: int = 14, max_active_rows: int = 3000) -> dict[str, Any]:
    now = int(time.time())
    keep_after = now - max(1, int(retention_days)) * 86400
    abstractions_compiled = 0
    abstractions_tested = 0
    action_episodes: list[dict[str, Any]] = []
    groups: dict[str, list[dict[str, Any]]] = {}

    # ── 1. Pruning do JSONL legado ────────────────────────────────────────────
    eps = _load_episodes_from_jsonl()
    fresh_jsonl = [e for e in eps if int(e.get('ts') or 0) >= keep_after]
    stale_jsonl = [e for e in eps if int(e.get('ts') or 0) < keep_after]

    # dedupe semântico
    dedup = {}
    for e in fresh_jsonl:
        key = (
            str(e.get('kind') or ''), str(e.get('task_type') or ''),
            tuple(sorted(list(_tokens(str(e.get('text') or ''))))[:8])
        )
        dedup[key] = e
    fresh_jsonl = list(dedup.values())
    fresh_jsonl.sort(key=lambda x: int(x.get('ts') or 0), reverse=True)
    fresh_jsonl = fresh_jsonl[:max(200, int(max_active_rows))]

    _append_archive(stale_jsonl)
    EPISODIC_PATH.write_text(
        '\n'.join(json.dumps(r, ensure_ascii=False) for r in fresh_jsonl) + ('\n' if fresh_jsonl else ''),
        encoding='utf-8'
    )
    pruned = len(stale_jsonl)

    # ── 2. Compilação Causal a partir das fontes reais ────────────────────────
    try:
        from ultronpro import episodic_compiler

        action_episodes = _load_recent_action_episodes(RECENT_HOURS)
        groups = _group_episodes(action_episodes)

        # Prioriza domínios fechados e grupos maiores
        sorted_groups = sorted(
            groups.items(),
            key=lambda kv: (kv[0].split('|')[0] not in CLOSED_DOMAINS, -len(kv[1]))
        )

        for group_key, group_eps in sorted_groups:
            if abstractions_compiled >= MAX_NEW_ABSTRACTIONS_PER_CYCLE:
                break
            if len(group_eps) < MIN_GROUP_FOR_COMPILATION:
                continue

            domain, action_kind = group_key.split('|', 1)

            # Classifica episódios
            annotated = [(ep, _outcome_ok(ep), _surprise_from_ep(ep)) for ep in group_eps]
            good = [(ep, ok, surp) for ep, ok, surp in annotated if ok and surp < 0.5]

            if len(good) >= 2:
                # Compila nova abstração a partir dos episódios bem-sucedidos
                best_ep = min(good, key=lambda x: x[2])[0]
                mean_surprise = sum(s for _, _, s in good) / max(1, len(good))
                ok_rate = len(good) / max(1, len(annotated))

                episode_data = {
                    'domain': domain,
                    'action_kind': action_kind,
                    'group_size': len(group_eps),
                    'success_rate': round(ok_rate, 3),
                    'mean_surprise': round(mean_surprise, 3),
                    'sample_episode': best_ep,
                    'all_outcomes': [str(ep.get('outcome') or '') for ep in group_eps[:10]],
                    'tools_used': list({str(ep.get('tool') or '') for ep in group_eps if ep.get('tool')}),
                }

                result = episodic_compiler.compile_causal_invariant(
                    domain=domain,
                    action_kind=action_kind,
                    episode_data=episode_data,
                    surprise_score=mean_surprise,
                )
                if result:
                    abstractions_compiled += 1

            # Testa abstrações existentes com episódios do grupo (independente de haver novos)
            for ep, ok, surp in annotated[:10]:
                results = episodic_compiler.auto_test_applicable(domain, ep, ok, surp)
                abstractions_tested += len(results)

    except Exception as compiler_err:
        import logging
        logging.getLogger(__name__).warning(f"Episodic compiler error in sleep_cycle: {compiler_err}")

    # ── 3. Consolidação SQL ───────────────────────────────────────────────────
    sql_consolidation = {}
    try:
        from ultronpro import store, episodic_compiler as ec
        sql_consolidation = store.consolidate_memories()

        # Abstrações com falha sistemática → memória semântica de aviso
        lib = ec._load_abstractions()
        for abs_item in lib.get('abstractions', []):
            if (abs_item.get('status') == 'discarded'
                    and abs_item.get('confirmation_rate', 1.0) < 0.3
                    and abs_item.get('test_count', 0) >= 5):
                store.add_autobiographical_memory(
                    text=(f"PADRAO_FALHA: {abs_item.get('name')} — "
                          f"{abs_item.get('causal_structure', '')[:200]}"),
                    memory_type='semantic',
                    importance=0.85,
                    decay_rate=0.001,
                    content_json=json.dumps({
                        'abs_id': abs_item.get('id'),
                        'domain': abs_item.get('domain'),
                        'confirmation_rate': abs_item.get('confirmation_rate'),
                    })
                )
    except Exception:
        pass

    episodic_enrichment = _run_episodic_enrichment_cycle(
        action_episodes=action_episodes,
        fresh_jsonl=fresh_jsonl,
        groups=groups,
        abstractions_compiled=abstractions_compiled,
    )
    memory_stagnation = _memory_stagnation_signal(
        pruned=pruned,
        abstractions_compiled=abstractions_compiled,
        action_episodes=action_episodes,
        groups=groups,
        episodic_enrichment=episodic_enrichment,
    )

    # 4. Investigacao ativa: lacunas causais pendentes viram experimentos sandboxados
    # e, quando aceitas, novas arestas no grafo causal.
    causal_gap_investigation = _run_active_investigation_cycle()
    nightly_digest = _run_nightly_episodic_digest(
        now=now,
        pruned=pruned,
        abstractions_compiled=abstractions_compiled,
        abstractions_tested=abstractions_tested,
        action_episodes=action_episodes,
        fresh_jsonl=fresh_jsonl,
        groups=groups,
        sql_consolidation=sql_consolidation,
        episodic_enrichment=episodic_enrichment,
        causal_gap_investigation=causal_gap_investigation,
        preliminary_stagnation=memory_stagnation,
    )
    memory_stagnation = _memory_stagnation_signal(
        pruned=pruned,
        abstractions_compiled=abstractions_compiled,
        action_episodes=action_episodes,
        groups=groups,
        episodic_enrichment=episodic_enrichment,
        nightly_digest=nightly_digest,
    )
    coverage_gained = bool(
        causal_gap_investigation.get('coverage_gained')
        or int((episodic_enrichment or {}).get('records_created') or 0) > 0
        or bool((nightly_digest or {}).get('recorded'))
        or abstractions_compiled > 0
    )

    rep = {
        'ok': True,
        'ts': now,
        'episodes_total': len(eps),
        'active_after': len(fresh_jsonl),
        'pruned': pruned,
        'abstracted': abstractions_compiled,
        'abstractions_tested': abstractions_tested,
        'sql_consolidation': sql_consolidation,
        'episodic_enrichment': episodic_enrichment,
        'nightly_episodic_digest': nightly_digest,
        'memory_stagnation_signal': memory_stagnation,
        'causal_gap_investigation': causal_gap_investigation,
        'epistemic_gap_perception': causal_gap_investigation.get('epistemic_gap_perception', {}),
        'coverage_delta_edges': causal_gap_investigation.get('coverage_delta_edges', 0),
        'coverage_gained': coverage_gained,
        'episodic_memory_gained': (
            int((episodic_enrichment or {}).get('records_created') or 0) > 0
            or bool((nightly_digest or {}).get('recorded'))
        ),
        'retention_days': retention_days,
        'max_active_rows': max_active_rows,
        'recent_abstraction_hours': RECENT_HOURS,
        'min_group_episodes': MIN_GROUP_FOR_COMPILATION,
        'paths': {
            'episodic_active': str(EPISODIC_PATH),
            'episodic_archive': str(EPISODIC_ARCHIVE_PATH),
            'abstractions': str(ABSTRACTIONS_PATH),
        },
    }
    REPORT_PATH.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding='utf-8')

    # --- Camada 1: ingerir ciclo de sono como episódio autobiográfico ---
    try:
        from ultronpro import autobiographical_router
        autobiographical_router.append_self_event(
            kind='sleep_cycle_completed',
            description=(
                f"Ciclo de sono concluído: {abstractions_compiled} abstração(ões) compilada(s), "
                f"{abstractions_tested} testada(s). {pruned} episódios arquivados. "
                f"Consolidação SQL: {sql_consolidation.get('promoted_to_episodic', 0)} promovidos, "
                f"{sql_consolidation.get('pruned', 0)} podados. "
                f"Investigacao causal: {causal_gap_investigation.get('executed', 0)} executada(s), "
                f"{causal_gap_investigation.get('injected', 0)} injetada(s). "
                f"Enriquecimento episodico: {episodic_enrichment.get('records_created', 0)} registro(s). "
                f"Digest episodico: {'registrado' if nightly_digest.get('recorded') else nightly_digest.get('reason')}. "
                f"Estagnacao: {memory_stagnation.get('status')}."
            ),
            outcome='success',
            module='sleep_cycle',
            importance=0.70,
            extra={
                'abstractions_compiled': abstractions_compiled,
                'abstractions_tested': abstractions_tested,
                'pruned': pruned,
                'active_after': len(fresh_jsonl),
                'sql_consolidation': sql_consolidation,
                'episodic_enrichment': episodic_enrichment,
                'nightly_episodic_digest': nightly_digest,
                'memory_stagnation_signal': memory_stagnation,
                'causal_gap_investigation': causal_gap_investigation,
            },
        )
    except Exception:
        pass

    return rep
