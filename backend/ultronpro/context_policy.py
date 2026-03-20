from __future__ import annotations

import json
from typing import Any

from ultronpro import cognitive_state, episodic_memory


PROFILES: dict[str, dict[str, Any]] = {
    'factual': {
        'allowed_sources': ['rag', 'runtime'],
        'required_sources': ['rag'],
        'max_rag_blocks': 2,
        'max_episodic': 0,
        'include_working_memory': False,
        'include_cognitive_state': False,
        'cognitive_state_chars': 0,
        'max_total_chars': 1400,
        'fallback_mode': 'explicit_gap',
        'cutoff_reason': 'prioritize_factual_evidence_over_memory',
    },
    'debugging': {
        'allowed_sources': ['rag', 'episodic', 'working_memory', 'cognitive_state', 'runtime'],
        'required_sources': [],
        'max_rag_blocks': 3,
        'max_episodic': 1,
        'include_working_memory': True,
        'include_cognitive_state': True,
        'cognitive_state_chars': 900,
        'max_total_chars': 2600,
        'fallback_mode': 'explicit_gap',
        'cutoff_reason': 'prioritize_error_context_and_recent_episode',
    },
    'planejamento': {
        'allowed_sources': ['rag', 'episodic', 'working_memory', 'cognitive_state'],
        'required_sources': [],
        'max_rag_blocks': 2,
        'max_episodic': 2,
        'include_working_memory': True,
        'include_cognitive_state': True,
        'cognitive_state_chars': 800,
        'max_total_chars': 2300,
        'fallback_mode': 'explicit_gap',
        'cutoff_reason': 'prioritize_goal_constraints_and_relevant_examples',
    },
    'memoria_continuidade': {
        'allowed_sources': ['episodic', 'working_memory', 'cognitive_state'],
        'required_sources': ['episodic'],
        'max_rag_blocks': 0,
        'max_episodic': 3,
        'include_working_memory': True,
        'include_cognitive_state': True,
        'cognitive_state_chars': 700,
        'max_total_chars': 2200,
        'fallback_mode': 'explicit_gap',
        'cutoff_reason': 'prioritize_recent_and_longitudinal_memory',
    },
    'acao_com_ferramenta': {
        'allowed_sources': ['rag', 'working_memory', 'cognitive_state', 'runtime'],
        'required_sources': [],
        'max_rag_blocks': 1,
        'max_episodic': 0,
        'include_working_memory': True,
        'include_cognitive_state': True,
        'cognitive_state_chars': 500,
        'max_total_chars': 1600,
        'fallback_mode': 'explicit_gap',
        'cutoff_reason': 'prioritize_operational_clarity_and_constraints',
    },
}

TASK_TYPE_TO_PROFILE = {
    'planning': 'planejamento',
    'debug': 'debugging',
    'summarization': 'factual',
    'code': 'debugging',
    'memory': 'memoria_continuidade',
    'tool_action': 'acao_com_ferramenta',
    'general': 'factual',
}


def classify_profile(query: str, task_type: str = 'general') -> str:
    q = str(query or '').lower()
    tt = str(task_type or 'general').strip().lower()
    if any(k in q for k in ['lembra', 'continuar', 'continuamos', 'ontem', 'antes', 'histórico', 'historico', 'memória', 'memoria']):
        return 'memoria_continuidade'
    if any(k in q for k in ['erro', 'falha', 'debug', 'bug', 'traceback', 'stack trace', 'timeout', 'latência', 'latencia', '500', '502', '503']):
        return 'debugging'
    if any(k in q for k in ['executa', 'rode', 'roda', 'run', 'comando', 'bash', 'python', 'script', 'aplica', 'deploy']):
        return 'acao_com_ferramenta'
    if any(k in q for k in ['planeje', 'planejar', 'plano', 'estratégia', 'estrategia', 'roteiro', 'organize', 'organizar']):
        return 'planejamento'
    return TASK_TYPE_TO_PROFILE.get(tt, 'factual')


def _estimate_chars(obj: Any) -> int:
    try:
        return len(json.dumps(obj, ensure_ascii=False))
    except Exception:
        return len(str(obj or ''))


def build_context(*, query: str, task_type: str = 'general', rag_docs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    profile_name = classify_profile(query=query, task_type=task_type)
    profile = dict(PROFILES.get(profile_name) or PROFILES['factual'])
    selected: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    missing_required: list[str] = []

    rag_docs = list(rag_docs or [])
    rag_blocks = []
    for d in rag_docs[: max(0, int(profile.get('max_rag_blocks') or 0))]:
        rag_blocks.append({
            'source': 'rag',
            'source_id': str(d.get('source_id') or 'rag'),
            'score': d.get('score'),
            'text': str(d.get('text') or '')[:480],
        })
    for d in rag_docs[len(rag_blocks):]:
        excluded.append({'source': 'rag', 'reason': 'budget_exceeded', 'source_id': str(d.get('source_id') or 'rag')})
    if rag_blocks:
        selected.append({'source': 'rag', 'items': rag_blocks})

    mem_policy = episodic_memory.get_task_memory_policy(task_type)
    recall = episodic_memory.layered_recall_compact(
        problem=query,
        task_type=task_type,
        limit=max(1, int(mem_policy.get('episodic_limit') or 3)),
        max_chars=min(int(profile.get('max_total_chars') or 1600), int(mem_policy.get('max_chars') or 1500)),
    )
    episodic_items = (recall.get('episodic_similar') if isinstance(recall, dict) else []) or []
    if 'episodic' in profile.get('allowed_sources', []):
        keep = episodic_items[: max(0, int(profile.get('max_episodic') or 0))]
        if keep:
            selected.append({'source': 'episodic', 'items': keep})
        for _ in episodic_items[len(keep):]:
            excluded.append({'source': 'episodic', 'reason': 'budget_exceeded'})
    elif episodic_items:
        excluded.append({'source': 'episodic', 'reason': 'policy_excluded'})

    wm = (recall.get('working_memory') if isinstance(recall, dict) else {}) or {}
    if profile.get('include_working_memory'):
        selected.append({'source': 'working_memory', 'items': wm})
    elif wm:
        excluded.append({'source': 'working_memory', 'reason': 'policy_excluded'})

    cstate = {}
    if profile.get('include_cognitive_state'):
        cstate = cognitive_state.compact_for_prompt(max_chars=int(profile.get('cognitive_state_chars') or 600))
        selected.append({'source': 'cognitive_state', 'items': cstate})

    selected_chars = sum(_estimate_chars(x) for x in selected)
    budget = int(profile.get('max_total_chars') or 1600)
    while selected and selected_chars > budget:
        removed = selected.pop()
        excluded.append({'source': removed.get('source'), 'reason': 'global_budget_exceeded'})
        selected_chars = sum(_estimate_chars(x) for x in selected)

    selected_sources = {str(x.get('source')) for x in selected}
    for required in profile.get('required_sources', []):
        if required not in selected_sources:
            missing_required.append(str(required))

    fallback = {
        'needed': bool(missing_required),
        'mode': str(profile.get('fallback_mode') or 'explicit_gap'),
        'missing_required_sources': missing_required,
        'message': ('Contexto essencial ausente: ' + ', '.join(missing_required)) if missing_required else '',
    }
    return {
        'profile': profile_name,
        'policy': profile,
        'selected_contexts': selected,
        'excluded_contexts': excluded,
        'fallback': fallback,
        'budget': {
            'max_chars': budget,
            'actual_chars': selected_chars,
        },
        'memory_budget': (recall.get('budget') if isinstance(recall, dict) else {}),
        'cutoff_reason': str(profile.get('cutoff_reason') or ''),
    }
