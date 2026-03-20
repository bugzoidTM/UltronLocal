from __future__ import annotations

import json
import time
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any

DATA_PATH = Path('/app/data/explicit_abstractions.json')


def _now() -> int:
    return int(time.time())


def _ensure_parent(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)


def _load() -> dict[str, Any]:
    if not DATA_PATH.exists():
        return {'items': []}
    try:
        data = json.loads(DATA_PATH.read_text(encoding='utf-8'))
        if isinstance(data, dict):
            data['items'] = data.get('items') if isinstance(data.get('items'), list) else []
            return data
    except Exception:
        pass
    return {'items': []}


def _save(data: dict[str, Any]) -> dict[str, Any]:
    _ensure_parent(DATA_PATH)
    DATA_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    return data


def _norm(value: str | None) -> str:
    return str(value or '').strip().lower()


def _compute_fragility(item: dict[str, Any]) -> dict[str, Any]:
    history = item.get('transfer_history') if isinstance(item.get('transfer_history'), list) else []
    total = len(history)
    wins = 0
    losses = 0
    scores = []
    domains = set()
    for row in history:
        if not isinstance(row, dict):
            continue
        outcome = _norm(row.get('outcome'))
        if outcome in ('success', 'validated', 'win', 'good_transfer'):
            wins += 1
        elif outcome in ('failure', 'fragile', 'bad_transfer', 'loss'):
            losses += 1
        if row.get('score') is not None:
            try:
                scores.append(float(row.get('score')))
            except Exception:
                pass
        dom = _norm(row.get('target_domain'))
        if dom:
            domains.add(dom)
    avg_score = sum(scores) / max(1, len(scores)) if scores else 0.0
    volatility = 0.0
    if scores:
        mean = avg_score
        volatility = sum(abs(s - mean) for s in scores) / max(1, len(scores))
    conflict_ratio = losses / max(1, total)
    fragility_score = round(max(0.0, min(1.0, (0.45 * conflict_ratio) + (0.35 * volatility) + (0.20 * (1.0 if len(domains) <= 1 and total >= 2 else 0.0)))), 4)
    flags = []
    if losses >= max(2, wins + 1):
        flags.append('failure_dominant')
    if volatility >= 0.25:
        flags.append('score_volatile')
    if len(domains) <= 1 and total >= 2:
        flags.append('single_domain_bias')
    return {
        'fragility_score': fragility_score,
        'conflict_ratio': round(conflict_ratio, 4),
        'score_volatility': round(volatility, 4),
        'wins': wins,
        'losses': losses,
        'tested_domains': sorted(domains),
        'flags': flags,
        'avg_transfer_score': round(avg_score, 4),
    }


def list_abstractions(limit: int = 50, domain: str | None = None) -> dict[str, Any]:
    data = _load()
    items = list(data.get('items') or [])
    dom = str(domain or '').strip().lower()
    if dom:
        items = [x for x in items if dom in [str(y).strip().lower() for y in (x.get('source_domains') or [])]]
    items = items[-max(1, min(500, int(limit or 50))):]
    return {'ok': True, 'items': items, 'count': len(items), 'path': str(DATA_PATH)}


def get_abstraction(abstraction_id: str) -> dict[str, Any] | None:
    aid = str(abstraction_id or '').strip()
    if not aid:
        return None
    for item in reversed((_load().get('items') or [])):
        if str(item.get('id') or '') == aid:
            return item
    return None


def _compute_generality(item: dict[str, Any]) -> float:
    domains = len(set(str(x).strip().lower() for x in (item.get('source_domains') or []) if str(x).strip()))
    transfers = len(item.get('transfer_history') or [])
    confidence = float(item.get('confidence') or 0.0)
    fragility = float(((item.get('fragility') or {}).get('fragility_score')) or 0.0)
    score = (min(4, domains) * 0.17) + (min(6, transfers) * 0.07) + (confidence * 0.36) - (fragility * 0.18)
    return round(max(0.0, min(1.0, score)), 4)


def _derive_status(item: dict[str, Any]) -> str:
    confidence = float(item.get('confidence') or 0.0)
    transfers = len(item.get('transfer_history') or [])
    fragility = float(((item.get('fragility') or {}).get('fragility_score')) or 0.0)
    if fragility >= 0.65 and transfers >= 2:
        return 'fragile'
    if confidence >= 0.75 and transfers >= 2:
        return 'validated'
    if confidence >= 0.45:
        return 'candidate'
    return 'draft'


def _next_version(previous: dict[str, Any] | None = None) -> int:
    if not isinstance(previous, dict):
        return 1
    return max(1, int(previous.get('version') or 1) + 1)


def _find_existing_variant(principle: str) -> dict[str, Any] | None:
    p = _norm(principle)
    if not p:
        return None
    for item in reversed((_load().get('items') or [])):
        if _norm(item.get('principle')) == p:
            return item
    return None


def create_abstraction(
    principle: str,
    source_domains: list[str] | None = None,
    applicability_conditions: list[str] | None = None,
    procedure_template: list[str] | None = None,
    evidence: list[dict[str, Any]] | None = None,
    confidence: float = 0.5,
    transfer_history: list[dict[str, Any]] | None = None,
    notes: str | None = None,
    structural_pattern: dict[str, Any] | None = None,
    parent_abstraction_id: str | None = None,
):
    data = _load()
    previous = _find_existing_variant(principle)
    item = {
        'id': f"abs_{uuid.uuid4().hex[:10]}",
        'created_at': _now(),
        'updated_at': _now(),
        'version': _next_version(previous),
        'parent_abstraction_id': str(parent_abstraction_id or (previous or {}).get('id') or '') or None,
        'principle': str(principle or '').strip()[:500],
        'source_domains': [str(x)[:120] for x in (source_domains or []) if str(x).strip()][:20],
        'applicability_conditions': [str(x)[:200] for x in (applicability_conditions or []) if str(x).strip()][:30],
        'procedure_template': [str(x)[:200] for x in (procedure_template or []) if str(x).strip()][:30],
        'evidence': (evidence or [])[:100],
        'confidence': round(max(0.0, min(1.0, float(confidence or 0.0))), 4),
        'transfer_history': (transfer_history or [])[:100],
        'notes': str(notes or '')[:1200],
        'structural_pattern': structural_pattern if isinstance(structural_pattern, dict) else {},
        'generality_score': 0.0,
        'fragility': {},
        'status': 'draft',
    }
    item['fragility'] = _compute_fragility(item)
    item['generality_score'] = _compute_generality(item)
    item['status'] = _derive_status(item)
    data['items'] = (data.get('items') or [])[-2000:] + [item]
    _save(data)
    return item


def update_transfer_history(abstraction_id: str, target_domain: str, outcome: str, evidence_ref: str | None = None, score: float | None = None, notes: str | None = None) -> dict[str, Any] | None:
    data = _load()
    items = data.get('items') or []
    for idx, item in enumerate(items):
        if str(item.get('id') or '') != str(abstraction_id):
            continue
        hist = item.get('transfer_history') if isinstance(item.get('transfer_history'), list) else []
        hist.append({
            'ts': _now(),
            'target_domain': str(target_domain or '')[:120],
            'outcome': str(outcome or '')[:60],
            'evidence_ref': str(evidence_ref or '')[:200] or None,
            'score': None if score is None else round(max(0.0, min(1.0, float(score))), 4),
            'notes': str(notes or '')[:400],
        })
        item['transfer_history'] = hist[-100:]
        item['updated_at'] = _now()
        item['fragility'] = _compute_fragility(item)
        item['generality_score'] = _compute_generality(item)
        item['status'] = _derive_status(item)
        items[idx] = item
        data['items'] = items
        _save(data)
        return item
    return None


def extract_from_ultronbody_episode(episode: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(episode, dict):
        return []
    steps = episode.get('steps') if isinstance(episode.get('steps'), list) else []
    if not steps:
        return []
    env_name = str(episode.get('env_name') or 'unknown')
    total_reward = float(episode.get('total_reward') or 0.0)
    done_reason = str(episode.get('done_reason') or '')
    actions = [str((s or {}).get('action') or '') for s in steps if isinstance(s, dict)]
    structural_pattern = {
        'episode_length': len(steps),
        'action_histogram': {a: actions.count(a) for a in sorted(set(actions)) if a},
        'done_reason': done_reason,
    }
    rules: list[dict[str, Any]] = []

    if done_reason == 'goal_reached' and 'wait' not in actions:
        rules.append({
            'principle': 'Em ambiente sequencial simples, progresso dirigido ao objetivo supera inação prolongada.',
            'source_domains': [env_name, 'grid_navigation'],
            'applicability_conditions': ['objetivo_posicional_explícito', 'ação_discreta', 'custo_de_tempo_por_passo'],
            'procedure_template': ['observar_posição_atual', 'estimar_ação_que_reduz_distância_ao_objetivo', 'evitar_risco_obvio', 'executar_passo', 'reavaliar'],
            'evidence': [{'episode_id': episode.get('episode_id'), 'done_reason': done_reason, 'total_reward': total_reward}],
            'confidence': 0.72,
            'notes': 'Regra induzida de episódio bem-sucedido no ultronbody.',
            'structural_pattern': structural_pattern,
        })

    if any('trap' in [str(x) for x in ((s or {}).get('events') or [])] for s in steps if isinstance(s, dict)):
        rules.append({
            'principle': 'Ações com alta chance de entrar em área de risco devem ser preteridas por rotas ligeiramente mais longas porém seguras.',
            'source_domains': [env_name, 'risk_avoidance'],
            'applicability_conditions': ['há_zonas_de_risco', 'existe_rota_alternativa', 'objetivo_permanece_alcançável'],
            'procedure_template': ['identificar_ação_de_maior_risco', 'comparar_com_alternativa_segura', 'preferir_maior_utilidade_esperada'],
            'evidence': [{'episode_id': episode.get('episode_id'), 'done_reason': done_reason, 'total_reward': total_reward}],
            'confidence': 0.68,
            'notes': 'Regra induzida de episódio com exposição a risco.',
            'structural_pattern': structural_pattern,
        })

    if done_reason == 'max_steps' or all(a == 'wait' for a in actions if a):
        rules.append({
            'principle': 'Quando há custo por passo, inação repetida degrada desempenho mesmo sem falha catastrófica imediata.',
            'source_domains': [env_name, 'resource_bounded_planning'],
            'applicability_conditions': ['há_penalidade_por_tempo', 'inação_repetida', 'objetivo_não_atingido'],
            'procedure_template': ['detectar_estagnação', 'comparar_com_ação_de_progresso', 'trocar_para_política_orientada_a_meta'],
            'evidence': [{'episode_id': episode.get('episode_id'), 'done_reason': done_reason, 'total_reward': total_reward}],
            'confidence': 0.77,
            'notes': 'Regra induzida de episódio estagnado.',
            'structural_pattern': structural_pattern,
        })

    return rules


def ingest_ultronbody_episode(episode: dict[str, Any]) -> dict[str, Any]:
    rules = extract_from_ultronbody_episode(episode)
    created = []
    for rule in rules:
        created.append(create_abstraction(**rule))
    return {'ok': True, 'created': created, 'count': len(created), 'path': str(DATA_PATH)}


def batch_extract_from_ultronbody_episodes(episodes: list[dict[str, Any]], min_cluster_size: int = 2) -> dict[str, Any]:
    usable = [e for e in (episodes or []) if isinstance(e, dict) and isinstance(e.get('steps'), list) and e.get('steps')]
    clusters: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for ep in usable:
        steps = ep.get('steps') or []
        actions = [str((s or {}).get('action') or '') for s in steps if isinstance(s, dict)]
        action_types = ','.join(sorted(set(a for a in actions if a)))[:120]
        key = f"{_norm(ep.get('done_reason'))}|{_norm(ep.get('env_name'))}|{action_types}"
        clusters[key].append(ep)

    created = []
    summaries = []
    for key, rows in clusters.items():
        if len(rows) < max(1, int(min_cluster_size or 2)):
            continue
        done_reason = _norm(rows[0].get('done_reason'))
        envs = sorted(set(_norm(r.get('env_name')) for r in rows if _norm(r.get('env_name'))))
        actions = []
        rewards = []
        evidence = []
        for r in rows:
            steps = r.get('steps') or []
            actions.extend([str((s or {}).get('action') or '') for s in steps if isinstance(s, dict)])
            rewards.append(float(r.get('total_reward') or 0.0))
            evidence.append({'episode_id': r.get('episode_id'), 'done_reason': r.get('done_reason'), 'env_name': r.get('env_name'), 'total_reward': r.get('total_reward')})
        principle = 'Padrão estrutural recorrente detectado em episódios similares.'
        applicability = ['há_múltiplos_epísodios_semelhantes', f'done_reason={done_reason}']
        procedure = ['identificar_padrão_reincidente', 'extrair_estrutura_compartilhada', 'reaplicar_template', 'reavaliar_no_domínio_alvo']
        notes = f'Cluster estrutural com {len(rows)} episódios.'
        confidence = min(0.92, 0.48 + (0.08 * len(rows)))
        if done_reason == 'goal_reached':
            principle = 'Estratégias que mantêm progresso incremental e reavaliação tendem a transferir melhor do que ações estáticas.'
            applicability.append('sucesso_recorrente')
            procedure = ['detectar_objetivo', 'escolher_passo_de_progresso', 'evitar_regressão/risco', 'executar', 'reavaliar']
        elif done_reason == 'trap':
            principle = 'Falhas recorrentes por risco indicam estrutura transferível de evasão: detectar estado perigoso cedo e redirecionar antes do colapso.'
            applicability.append('falha_por_risco_recorrente')
            procedure = ['detectar_sinal_de_risco', 'comparar_rota_mais_segura', 'preferir_desvio_controlado', 'monitorar_recorrência']
        elif done_reason == 'max_steps':
            principle = 'Estagnação recorrente revela padrão estrutural de baixa exploração eficaz: trocar cedo para política orientada a progresso melhora transferibilidade.'
            applicability.append('estagnação_recorrente')
            procedure = ['medir_estagnação', 'selecionar_ação_com_progresso', 'abandonar_loop_ineficiente', 'reavaliar']
        pattern = {
            'cluster_key': key,
            'episodes': len(rows),
            'envs': envs,
            'avg_reward': round(sum(rewards) / max(1, len(rewards)), 4),
            'dominant_actions': sorted({a for a in actions if a})[:12],
        }
        item = create_abstraction(
            principle=principle,
            source_domains=envs + ['ultronbody_cluster'],
            applicability_conditions=applicability,
            procedure_template=procedure,
            evidence=evidence[:50],
            confidence=confidence,
            notes=notes,
            structural_pattern=pattern,
        )
        created.append(item)
        summaries.append(pattern)
    return {'ok': True, 'clusters': len(clusters), 'created_count': len(created), 'created': created, 'cluster_summaries': summaries, 'path': str(DATA_PATH)}


def consolidate_abstraction(
    abstraction_id: str,
    benchmark_summary: dict[str, Any] | None = None,
    note: str | None = None,
) -> dict[str, Any] | None:
    data = _load()
    items = data.get('items') or []
    for idx, item in enumerate(items):
        if str(item.get('id') or '') != str(abstraction_id):
            continue
        benchmark_summary = benchmark_summary if isinstance(benchmark_summary, dict) else {}
        avg_improvement = float(benchmark_summary.get('avg_improvement') or 0.0)
        zero_shot_win_rate = float(benchmark_summary.get('zero_shot_win_rate') or 0.0)
        scenarios = int(benchmark_summary.get('scenarios') or 0)
        fragility_penalty = float(((item.get('fragility') or {}).get('fragility_score')) or 0.0)
        benchmark_score = round(max(0.0, min(1.0, (0.50 * max(0.0, avg_improvement)) + (0.35 * zero_shot_win_rate) + (0.15 * max(0.0, 1.0 - fragility_penalty)))), 4)
        transfer_history = item.get('transfer_history') if isinstance(item.get('transfer_history'), list) else []
        domain_count = len(set(str((x or {}).get('target_domain') or '').strip().lower() for x in transfer_history if str((x or {}).get('target_domain') or '').strip()))

        prior_status = str(item.get('status') or 'draft')
        if scenarios >= 3 and zero_shot_win_rate >= 0.75 and avg_improvement >= 0.2 and fragility_penalty < 0.45:
            item['status'] = 'validated'
        elif avg_improvement < 0.05 and scenarios >= 2:
            item['status'] = 'fragile'
        elif float(item.get('confidence') or 0.0) >= 0.45 or benchmark_score >= 0.45:
            item['status'] = 'candidate'
        else:
            item['status'] = 'draft'

        confidence = float(item.get('confidence') or 0.0)
        adjusted_confidence = confidence
        if item['status'] == 'validated':
            adjusted_confidence = min(1.0, confidence + 0.08)
        elif item['status'] == 'fragile':
            adjusted_confidence = max(0.0, confidence - 0.12)
        item['confidence'] = round(adjusted_confidence, 4)
        item['benchmark_summary'] = {
            'avg_improvement': round(avg_improvement, 4),
            'zero_shot_win_rate': round(zero_shot_win_rate, 4),
            'scenarios': scenarios,
            'benchmark_score': benchmark_score,
            'domains_seen': domain_count,
        }
        item['updated_at'] = _now()
        item['fragility'] = _compute_fragility(item)
        item['generality_score'] = _compute_generality(item)
        item['notes'] = ((str(item.get('notes') or '') + '\n' if item.get('notes') else '') + f"consolidation: prior_status={prior_status}; new_status={item['status']}; note={str(note or '')[:200]}")[:1200]
        items[idx] = item
        data['items'] = items
        _save(data)
        return item
    return None


def portfolio_summary() -> dict[str, Any]:
    items = _load().get('items') or []
    statuses: dict[str, int] = {}
    benchmarked = 0
    avg_generality = 0.0
    avg_fragility = 0.0
    top_items = []
    for item in items:
        st = str(item.get('status') or 'draft')
        statuses[st] = int(statuses.get(st, 0)) + 1
        if isinstance(item.get('benchmark_summary'), dict):
            benchmarked += 1
        avg_generality += float(item.get('generality_score') or 0.0)
        avg_fragility += float(((item.get('fragility') or {}).get('fragility_score') or 0.0))
        top_items.append({
            'id': item.get('id'),
            'version': item.get('version'),
            'status': item.get('status'),
            'generality_score': item.get('generality_score'),
            'fragility_score': ((item.get('fragility') or {}).get('fragility_score')) if isinstance(item.get('fragility'), dict) else None,
            'benchmark_score': ((item.get('benchmark_summary') or {}).get('benchmark_score')) if isinstance(item.get('benchmark_summary'), dict) else None,
            'principle': item.get('principle'),
        })
    top_items = sorted(top_items, key=lambda x: (float(x.get('benchmark_score') or 0.0), float(x.get('generality_score') or 0.0), -float(x.get('fragility_score') or 0.0)), reverse=True)[:10]
    return {
        'ok': True,
        'count': len(items),
        'benchmarked_count': benchmarked,
        'avg_generality_score': round(avg_generality / max(1, len(items)), 4),
        'avg_fragility_score': round(avg_fragility / max(1, len(items)), 4),
        'statuses': statuses,
        'top_items': top_items,
        'path': str(DATA_PATH),
    }


def stats() -> dict[str, Any]:
    return portfolio_summary()
