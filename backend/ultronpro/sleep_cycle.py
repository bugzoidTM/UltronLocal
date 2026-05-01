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
import os
import time
from pathlib import Path
from typing import Any

EPISODIC_PATH = Path(__file__).resolve().parent.parent / 'data' / 'episodic_memory.jsonl'
EPISODIC_ARCHIVE_PATH = Path(__file__).resolve().parent.parent / 'data' / 'episodic_memory_archive.jsonl'
ABSTRACTIONS_PATH = Path(__file__).resolve().parent.parent / 'data' / 'episodic_abstractions.json'
REPORT_PATH = Path(__file__).resolve().parent.parent / 'data' / 'sleep_cycle_report.json'
AUDIT_PATH = Path(__file__).resolve().parent.parent / 'data' / 'episodic_audit.jsonl'

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

def run_cycle(retention_days: int = 14, max_active_rows: int = 3000) -> dict[str, Any]:
    now = int(time.time())
    keep_after = now - max(1, int(retention_days)) * 86400
    abstractions_compiled = 0
    abstractions_tested = 0

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

    # 4. Investigacao ativa: lacunas causais pendentes viram experimentos sandboxados
    # e, quando aceitas, novas arestas no grafo causal.
    causal_gap_investigation = _run_active_investigation_cycle()

    rep = {
        'ok': True,
        'ts': now,
        'episodes_total': len(eps),
        'active_after': len(fresh_jsonl),
        'pruned': pruned,
        'abstracted': abstractions_compiled,
        'abstractions_tested': abstractions_tested,
        'sql_consolidation': sql_consolidation,
        'causal_gap_investigation': causal_gap_investigation,
        'epistemic_gap_perception': causal_gap_investigation.get('epistemic_gap_perception', {}),
        'coverage_delta_edges': causal_gap_investigation.get('coverage_delta_edges', 0),
        'coverage_gained': bool(causal_gap_investigation.get('coverage_gained')),
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
                f"{causal_gap_investigation.get('injected', 0)} injetada(s)."
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
                'causal_gap_investigation': causal_gap_investigation,
            },
        )
    except Exception:
        pass

    return rep
