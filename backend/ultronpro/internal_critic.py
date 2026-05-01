from __future__ import annotations

from typing import Any

from ultronpro import governance


def _clip01(v: float) -> float:
    return max(0.0, min(1.0, float(v)))


def _has_gap_language(answer: str) -> bool:
    a = str(answer or '').lower()
    return any(x in a for x in ['não sei', 'nao sei', 'falt', 'incerteza', 'não encontrei', 'nao encontrei', 'lacuna'])


def _selected_rag_items(context_meta: dict[str, Any]) -> list[dict[str, Any]]:
    selected = context_meta.get('selected_contexts') if isinstance(context_meta.get('selected_contexts'), list) else []
    out: list[dict[str, Any]] = []
    for block in selected:
        if str(block.get('source') or '') != 'rag':
            continue
        items = block.get('items') if isinstance(block.get('items'), list) else []
        for item in items:
            if isinstance(item, dict):
                out.append(item)
    return out


def critique_epistemic(*, query: str, answer: str, context_meta: dict[str, Any] | None = None) -> dict[str, Any]:
    meta = dict(context_meta or {})
    rag_items = _selected_rag_items(meta)
    fallback = meta.get('fallback') if isinstance(meta.get('fallback'), dict) else {}
    diversity = meta.get('rag_diversity') if isinstance(meta.get('rag_diversity'), dict) else {}

    answer_l = str(answer or '').lower()
    query_terms = {t for t in str(query or '').lower().split() if len(t) >= 4}
    answer_terms = {t for t in answer_l.split() if len(t) >= 4}

    overlap = (len(query_terms & answer_terms) / max(1, len(query_terms))) if query_terms else 0.0
    grounding_ok = bool(rag_items) or ('fonte:' in answer_l)
    gap_disclosure_ok = (not bool(fallback.get('needed'))) or _has_gap_language(answer)

    contradiction_risk = 0.15
    if fallback.get('needed') and not _has_gap_language(answer):
        contradiction_risk = 0.72
    elif not grounding_ok and answer:
        contradiction_risk = 0.58
    elif grounding_ok and gap_disclosure_ok:
        contradiction_risk = 0.18

    confidence_style = 'calibrated'
    if not grounding_ok and answer and not _has_gap_language(answer):
        confidence_style = 'overconfident'
    elif _has_gap_language(answer):
        confidence_style = 'explicit_uncertainty'

    diversity_low = float(diversity.get('coverage_score') or 0.0) < 0.45 if diversity else False
    needs_revision = bool(
        (answer and overlap < 0.18)
        or not gap_disclosure_ok
        or contradiction_risk >= 0.6
        or diversity_low
    )

    return {
        'grounding_ok': grounding_ok,
        'gap_disclosure_ok': gap_disclosure_ok,
        'contradiction_risk': round(_clip01(contradiction_risk), 4),
        'confidence_style': confidence_style,
        'query_answer_overlap': round(_clip01(overlap), 4),
        'needs_revision': needs_revision,
        'revision_reason': (
            'missing_gap_disclosure' if not gap_disclosure_ok else
            'low_grounding_or_high_contradiction_risk' if contradiction_risk >= 0.6 else
            'low_query_alignment' if (answer and overlap < 0.18) else
            'rag_coverage_low' if diversity_low else
            'none'
        ),
    }


def critique_operational(*, draft: str, kind: str = 'generate_questions', meta: dict[str, Any] | None = None, has_proof: bool = False) -> dict[str, Any]:
    from ultronpro import store
    mm = dict(meta or {})
    gov = governance.evaluate(kind, mm, has_proof=has_proof)
    draft_l = str(draft or '').lower()

    # Base risk defined by governance
    base_risk = 0.18
    if gov.get('class') == 'auto_with_proof':
        base_risk = 0.45
    if gov.get('class') == 'human_approval':
        base_risk = 0.72
    
    # Destructive keywords risk
    if any(x in draft_l for x in ['apagar', 'deletar', 'substituir', 'executar', 'deploy', 'reiniciar', 'migrar']):
        base_risk = min(0.92, base_risk + 0.12)

    # REINFORCEMENT: Semantic memory consulting
    semantic_penalty = 0.0
    reflections = []
    try:
        # Busca memórias semânticas ou episódicas de falha (importância alta)
        memories = store.list_autobiographical_memories(min_importance=0.6, limit=10)
        for mem in memories:
            m_text = mem.get('text', '').lower()
            # Se a memória contiver "falha" e palavras-chave do rascunho atual
            if 'falha' in m_text or 'erro' in m_text:
                # Verificação simples de overlap de palavras-chave
                common_terms = [t for t in draft_l.split() if len(t) > 5 and t in m_text]
                if common_terms:
                    semantic_penalty += 0.15 * len(common_terms)
                    reflections.append(f"Alerta: contexto similar ao erro detectado em memória: {common_terms}")
    except Exception:
        pass

    # 3. UNCERTAINTY: Probabilistic calibration penalty
    uncertainty_penalty = 0.0
    u_info = {}
    try:
        from ultronpro import self_model
        u_info = self_model.get_domain_uncertainty(kind, domain_type='task')
        if u_info.get('uncertainty', 0.0) > 0.45:
            # Penaliza risco por falta de dados ou alta variância
            uncertainty_penalty = 0.22 * u_info['uncertainty']
            reflections.append(f"Incerteza alta no domínio {kind}: {u_info['uncertainty']}. O sistema possui poucos dados robustos.")
    except Exception:
        pass

    final_risk = _clip01(base_risk + semantic_penalty + uncertainty_penalty)

    safe_to_execute = bool(gov.get('ok')) and final_risk < 0.75
    recommended_mode = 'respond'
    if gov.get('class') == 'auto_with_proof' and not bool(gov.get('ok')):
        recommended_mode = 'request_proof'
    elif gov.get('class') == 'human_approval' and not bool(gov.get('ok')):
        recommended_mode = 'request_human_approval'
    elif not safe_to_execute:
        recommended_mode = 'revise_or_abort'

    return {
        'action_risk': round(final_risk, 4),
        'base_risk': round(base_risk, 4),
        'uncertainty_calibration': u_info,
        'semantic_reflections': reflections[:4],
        'requires_proof': gov.get('class') == 'auto_with_proof' and not bool(gov.get('ok')),
        'requires_human_approval': gov.get('class') == 'human_approval' and not bool(gov.get('ok')),
        'safe_to_execute': safe_to_execute,
        'recommended_mode': recommended_mode,
        'governance': gov,
    }




def validate_plan_coherence(*, plan_steps: list[dict], context_meta: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    Cross-module coherence (Fase 5.5).
    Valida se os passos do plano fazem sentido com as predições do World Model.
    """
    from ultronpro import world_model
    
    coherence_report = []
    total_confidence = 0.0
    valid_steps = 0
    
    for step in plan_steps:
        kind = step.get('kind', 'logic')
        # Tenta simular a ação baseada no tipo
        sim = world_model.simulate_action(kind, step)
        
        step_ok = True
        reason = "Ação coerente com histórico/fisica do sistema."
        
        # Se a simulação prever falha com confiança razoável
        if sim.get('predicted_outcome') == 'failure' and sim.get('confidence', 0) > 0.6:
            step_ok = False
            reason = f"World Model prevê FALHA para '{kind}' com confiança {sim.get('confidence')}. Razão: {sim.get('warning')}"
        
        coherence_report.append({
            'step': step.get('text', kind),
            'kind': kind,
            'coherent': step_ok,
            'reason': reason,
            'confidence': sim.get('confidence', 0.5)
        })
        
        total_confidence += float(sim.get('confidence', 0.5))
        valid_steps += 1
    
    avg_coherence = sum(1 for r in coherence_report if r['coherent']) / max(1, len(coherence_report))
    avg_confidence = total_confidence / max(1, valid_steps)
    
    return {
        'ok': avg_coherence >= 0.8,
        'coherence_score': round(avg_coherence, 4),
        'avg_confidence': round(avg_confidence, 4),
        'report': coherence_report,
        'needs_revision': avg_coherence < 0.8
    }


def critique_response(*, query: str, answer: str, context_meta: dict[str, Any] | None = None, action_kind: str = 'generate_questions', governance_meta: dict[str, Any] | None = None, has_proof: bool = False) -> dict[str, Any]:
    epistemic = critique_epistemic(query=query, answer=answer, context_meta=context_meta)
    operational = critique_operational(draft=answer, kind=action_kind, meta=governance_meta, has_proof=has_proof)
    
    # Se houver passos de plano no meta, validamos coerência cruzada
    coherence = {'ok': True, 'coherence_score': 1.0}
    if governance_meta and 'plan_steps' in governance_meta:
        coherence = validate_plan_coherence(plan_steps=governance_meta['plan_steps'], context_meta=context_meta)

    overall_needs_revision = (
        bool(epistemic.get('needs_revision')) 
        or (not bool(operational.get('safe_to_execute')) and operational.get('recommended_mode') == 'revise_or_abort')
        or coherence.get('needs_revision', False)
    )
    
    return {
        'epistemic': epistemic,
        'operational': operational,
        'coherence': coherence,
        'needs_revision': overall_needs_revision,
    }
