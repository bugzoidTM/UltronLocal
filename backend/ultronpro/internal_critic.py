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
    mm = dict(meta or {})
    gov = governance.evaluate(kind, mm, has_proof=has_proof)
    draft_l = str(draft or '').lower()

    risk = 0.18
    if gov.get('class') == 'auto_with_proof':
        risk = 0.45
    if gov.get('class') == 'human_approval':
        risk = 0.72
    if any(x in draft_l for x in ['apagar', 'deletar', 'substituir', 'executar', 'deploy', 'reiniciar', 'migrar']):
        risk = min(0.92, risk + 0.12)

    safe_to_execute = bool(gov.get('ok')) and risk < 0.75
    recommended_mode = 'respond'
    if gov.get('class') == 'auto_with_proof' and not bool(gov.get('ok')):
        recommended_mode = 'request_proof'
    elif gov.get('class') == 'human_approval' and not bool(gov.get('ok')):
        recommended_mode = 'request_human_approval'
    elif not safe_to_execute:
        recommended_mode = 'revise_or_abort'

    return {
        'action_risk': round(_clip01(risk), 4),
        'requires_proof': gov.get('class') == 'auto_with_proof' and not bool(gov.get('ok')),
        'requires_human_approval': gov.get('class') == 'human_approval' and not bool(gov.get('ok')),
        'safe_to_execute': safe_to_execute,
        'recommended_mode': recommended_mode,
        'governance': gov,
    }


def critique_response(*, query: str, answer: str, context_meta: dict[str, Any] | None = None, action_kind: str = 'generate_questions', governance_meta: dict[str, Any] | None = None, has_proof: bool = False) -> dict[str, Any]:
    epistemic = critique_epistemic(query=query, answer=answer, context_meta=context_meta)
    operational = critique_operational(draft=answer, kind=action_kind, meta=governance_meta, has_proof=has_proof)
    overall_needs_revision = bool(epistemic.get('needs_revision')) or (not bool(operational.get('safe_to_execute')) and operational.get('recommended_mode') == 'revise_or_abort')
    return {
        'epistemic': epistemic,
        'operational': operational,
        'needs_revision': overall_needs_revision,
    }
