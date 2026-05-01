from __future__ import annotations

import os
from typing import Any

from ultronpro import knowledge_bridge


DOMAIN_PROFILES: dict[str, dict[str, Any]] = {
    'factual': {
        'query_prefix': 'fatos, documentação e evidências sobre: ',
        'preferred_task_types': ['research', 'general'],
        'top_k': 4,
    },
    'runtime': {
        'query_prefix': 'runtime, incidentes, latência, health, workers, filas e operação sobre: ',
        'preferred_task_types': ['operations', 'coding'],
        'top_k': 4,
    },
    'memory': {
        'query_prefix': 'histórico, continuidade, episódios, decisões anteriores sobre: ',
        'preferred_task_types': ['conversation_ptbr', 'planning', 'general'],
        'top_k': 3,
    },
    'code': {
        'query_prefix': 'código, api, bug, stacktrace, funções, classes e implementação sobre: ',
        'preferred_task_types': ['coding', 'operations'],
        'top_k': 4,
    },
    'planning': {
        'query_prefix': 'roadmap, milestones, prioridades, estratégia e plano para: ',
        'preferred_task_types': ['planning', 'research'],
        'top_k': 3,
    },
    'safety': {
        'query_prefix': 'segurança, políticas, compliance, guardrails e riscos sobre: ',
        'preferred_task_types': ['safety_guardrails', 'operations'],
        'top_k': 3,
    },
}

TASK_TO_DOMAINS = {
    'debug': ['runtime', 'code', 'factual'],
    'code': ['code', 'runtime', 'factual'],
    'summarization': ['factual'],
    'planning': ['planning', 'factual', 'memory'],
    'memory': ['memory', 'planning'],
    'tool_action': ['runtime', 'code'],
    'general': ['factual', 'planning'],
}


def infer_domains(query: str, task_type: str = 'general') -> list[str]:
    q = str(query or '').lower()
    if any(k in q for k in ['erro', 'falha', 'bug', 'traceback', 'stack', 'timeout', 'latência', 'latencia', '503', '502', '500']):
        return ['runtime', 'code', 'factual']
    if any(k in q for k in ['memória', 'memoria', 'continuar', 'continuidade', 'antes', 'ontem', 'decisão', 'decisao']):
        return ['memory', 'planning']
    if any(k in q for k in ['plano', 'planejar', 'estratégia', 'estrategia', 'roadmap', 'milestone', 'prioridade']):
        return ['planning', 'factual']
    if any(k in q for k in ['segurança', 'seguranca', 'compliance', 'guardrail', 'risco', 'política', 'politica']):
        return ['safety', 'factual']
    return list(TASK_TO_DOMAINS.get(str(task_type or 'general'), ['factual']))


def _score_doc(doc: dict[str, Any], *, domain: str, query: str) -> float:
    base = float(doc.get('score') or 0.0)
    task_type = str(doc.get('task_type') or 'general')
    preferred = DOMAIN_PROFILES.get(domain, {}).get('preferred_task_types') or []
    preference_bonus = 0.12 if task_type in preferred else 0.0
    lexical_bonus = 0.08 if any(tok in str(doc.get('text') or '').lower() for tok in str(query or '').lower().split()[:4]) else 0.0
    return round(base + preference_bonus + lexical_bonus, 4)


def _source_key(doc: dict[str, Any]) -> str:
    return str(doc.get('source_id') or 'unknown')


def _domain_key(doc: dict[str, Any]) -> str:
    return str(doc.get('domain') or 'unknown')


def _lexical_signature(text: str) -> set[str]:
    return {t for t in str(text or '').lower().split() if len(t) >= 5}


def _text_similarity(a: str, b: str) -> float:
    aa = _lexical_signature(a)
    bb = _lexical_signature(b)
    if not aa or not bb:
        return 0.0
    return len(aa & bb) / max(1, len(aa | bb))


def _compute_selection_metrics(*, selected: list[dict[str, Any]], candidates: list[dict[str, Any]], requested_domains: list[str]) -> dict[str, Any]:
    sel_n = len(selected)
    candidate_domains = {str(x.get('domain') or 'unknown') for x in candidates}
    selected_domains = {str(x.get('domain') or 'unknown') for x in selected}
    candidate_sources = {str(x.get('source_id') or 'unknown') for x in candidates}
    selected_sources = {str(x.get('source_id') or 'unknown') for x in selected}

    domain_diversity = len(selected_domains) / max(1, len(candidate_domains or requested_domains or ['factual']))
    source_diversity = len(selected_sources) / max(1, sel_n)

    redundancy_samples: list[float] = []
    for i, a in enumerate(selected):
        for b in selected[i + 1:]:
            redundancy_samples.append(_text_similarity(str(a.get('text') or ''), str(b.get('text') or '')))
    redundancy_score = (sum(redundancy_samples) / len(redundancy_samples)) if redundancy_samples else 0.0

    coverage_inputs = [
        domain_diversity,
        source_diversity,
        max(0.0, 1.0 - redundancy_score),
        min(1.0, sel_n / max(1, len(requested_domains) + 1)),
    ]
    coverage_score = sum(coverage_inputs) / len(coverage_inputs)

    return {
        'coverage_score': round(coverage_score, 4),
        'source_diversity': round(source_diversity, 4),
        'domain_diversity': round(domain_diversity, 4),
        'redundancy_score': round(redundancy_score, 4),
        'selected_count': sel_n,
        'candidate_count': len(candidates),
        'selected_domains': sorted(selected_domains),
        'selected_sources': sorted(selected_sources),
    }


def _diversity_select(results: list[dict[str, Any]], top_k: int, homeostasis_mode: str = 'normal') -> tuple[list[dict[str, Any]], dict[str, Any]]:
    source_cap = max(1, int(os.getenv('ULTRON_RAG_SOURCE_CAP', '2') or 2))
    domain_penalty = float(os.getenv('ULTRON_RAG_DOMAIN_PENALTY', '0.08') or 0.08)
    source_penalty = float(os.getenv('ULTRON_RAG_SOURCE_PENALTY', '0.12') or 0.12)
    lexical_dup_penalty = float(os.getenv('ULTRON_RAG_LEXICAL_DUP_PENALTY', '0.04') or 0.04)
    new_domain_bonus = float(os.getenv('ULTRON_RAG_NEW_DOMAIN_BONUS', '0.06') or 0.06)
    new_source_bonus = float(os.getenv('ULTRON_RAG_NEW_SOURCE_BONUS', '0.05') or 0.05)
    semantic_dup_penalty = float(os.getenv('ULTRON_RAG_SEMANTIC_DUP_PENALTY', '0.12') or 0.12)

    if homeostasis_mode == 'repair':
        domain_penalty = 0.02
        source_penalty = 0.02
        new_source_bonus = 0.01
        new_domain_bonus = 0.01
        semantic_dup_penalty = 0.05  # favorece convergência e informações confirmadas
        top_k = max(1, top_k - 1)
    elif homeostasis_mode in ('investigative', 'curious'):
        domain_penalty = 0.20
        source_penalty = 0.20
        new_source_bonus = 0.15
        new_domain_bonus = 0.15
        semantic_dup_penalty = 0.25  # força exploração ampla de contexto
        top_k = min(12, top_k + 2)

    source_counts: dict[str, int] = {}
    domain_counts: dict[str, int] = {}
    chosen: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    selection_trace: list[dict[str, Any]] = []
    pool = [dict(r) for r in results]

    while pool and len(chosen) < max(1, int(top_k or 5)):
        rescored: list[dict[str, Any]] = []
        for item in pool:
            source = _source_key(item)
            domain = _domain_key(item)
            scount = source_counts.get(source, 0)
            dcount = domain_counts.get(domain, 0)
            base = float(item.get('router_score') or item.get('score') or 0.0)
            adjusted = base - (scount * source_penalty) - (dcount * domain_penalty)
            reasons: list[str] = [f'base={round(base,4)}']
            if scount == 0:
                adjusted += new_source_bonus
                reasons.append('new_source_bonus')
            if dcount == 0:
                adjusted += new_domain_bonus
                reasons.append('new_domain_bonus')
            if scount >= source_cap:
                adjusted -= 0.5
                reasons.append('source_cap_soft_block')
            text = str(item.get('text') or '').lower()
            if chosen and any(text[:160] == str(c.get('text') or '').lower()[:160] for c in chosen):
                adjusted -= lexical_dup_penalty
                reasons.append('lexical_dup_penalty')
            sim_max = max((_text_similarity(text, str(c.get('text') or '').lower()) for c in chosen), default=0.0)
            if sim_max >= 0.55:
                adjusted -= semantic_dup_penalty * sim_max
                reasons.append(f'semantic_dup_penalty={round(sim_max,4)}')
            rescored.append({**item, 'adjusted_router_score': round(adjusted, 4), 'selection_reasons': reasons})

        rescored.sort(key=lambda x: float(x.get('adjusted_router_score') or 0.0), reverse=True)
        best = rescored[0]
        pool = [p for p in pool if not (str(p.get('source_id')) == str(best.get('source_id')) and str(p.get('text')) == str(best.get('text')))]
        if float(best.get('adjusted_router_score') or 0.0) < 0.05:
            rejected.append(best)
            selection_trace.append({
                'decision': 'reject',
                'source_id': _source_key(best),
                'domain': _domain_key(best),
                'adjusted_router_score': float(best.get('adjusted_router_score') or 0.0),
                'reasons': best.get('selection_reasons') or [],
            })
            continue
        chosen.append(best)
        source_counts[_source_key(best)] = source_counts.get(_source_key(best), 0) + 1
        domain_counts[_domain_key(best)] = domain_counts.get(_domain_key(best), 0) + 1
        selection_trace.append({
            'decision': 'select',
            'source_id': _source_key(best),
            'domain': _domain_key(best),
            'adjusted_router_score': float(best.get('adjusted_router_score') or 0.0),
            'reasons': best.get('selection_reasons') or [],
        })

    return chosen, {
        'source_cap': source_cap,
        'domain_penalty': domain_penalty,
        'source_penalty': source_penalty,
        'lexical_dup_penalty': lexical_dup_penalty,
        'new_domain_bonus': new_domain_bonus,
        'new_source_bonus': new_source_bonus,
        'semantic_dup_penalty': semantic_dup_penalty,
        'source_counts': source_counts,
        'domain_counts': domain_counts,
        'rejected_count': len(rejected),
        'selection_trace': selection_trace,
    }


async def search_routed(query: str, task_type: str = 'general', top_k: int = 5, homeostasis_mode: str = 'normal') -> dict[str, Any]:
    domains = infer_domains(query=query, task_type=task_type)
    max_domains = max(1, min(int(top_k or 5), int(os.getenv('ULTRON_RAG_MAX_DOMAINS', '2') or 2)))
    domains = domains[:max_domains]
    results: list[dict[str, Any]] = []
    search_plan: list[dict[str, Any]] = []

    for domain in domains:
        profile = DOMAIN_PROFILES.get(domain) or DOMAIN_PROFILES['factual']
        q = f"{profile.get('query_prefix')}{str(query or '').strip()}".strip()
        domain_top_k = max(1, min(int(profile.get('top_k') or top_k), int(top_k or 5)))
        docs = await knowledge_bridge.search_knowledge(q, top_k=domain_top_k)
        for d in docs or []:
            item = dict(d or {})
            item['domain'] = domain
            item['router_score'] = _score_doc(item, domain=domain, query=query)
            results.append(item)
        search_plan.append({'domain': domain, 'query': q[:300], 'top_k': domain_top_k, 'hits': len(docs or [])})

    deduped: list[dict[str, Any]] = []
    seen = set()
    for d in sorted(results, key=lambda x: float(x.get('router_score') or x.get('score') or 0.0), reverse=True):
        sig = (str(d.get('source_id') or ''), str(d.get('text') or '')[:240])
        if sig in seen:
            continue
        seen.add(sig)
        deduped.append(d)

    selected, diversity = _diversity_select(deduped, top_k=max(1, int(top_k or 5)), homeostasis_mode=homeostasis_mode)
    diversity.update(_compute_selection_metrics(selected=selected, candidates=deduped, requested_domains=domains))
    return {
        'domains': domains,
        'search_plan': search_plan,
        'diversity': diversity,
        'results': selected,
    }
