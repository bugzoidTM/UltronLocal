from __future__ import annotations

from typing import Any

from ultronpro import causal, governance


RISKY_TERMS = ['apagar', 'deletar', 'remover', 'reiniciar', 'migrar', 'deploy', 'executar', 'alterar', 'substituir']
REVERSIBLE_TERMS = ['simular', 'analisar', 'planejar', 'rascunho', 'sugerir', 'explicar']


def _clip01(v: float) -> float:
    return max(0.0, min(1.0, float(v)))


def _estimate_reversibility(action_kind: str, action_text: str, tool_outputs: list[dict[str, Any]] | None = None) -> float:
    txt = f"{str(action_kind or '')} {str(action_text or '')}".lower()
    if any(t in txt for t in REVERSIBLE_TERMS):
        return 0.88
    if any(t in txt for t in RISKY_TERMS):
        return 0.28
    if any(str((x or {}).get('tool') or '') in ('execute_bash', 'execute_python') for x in (tool_outputs or [])):
        return 0.34
    return 0.62


def _estimate_cost(tool_outputs: list[dict[str, Any]] | None = None) -> float:
    tools = list(tool_outputs or [])
    if not tools:
        return 0.08
    expensive = sum(1 for x in tools if str((x or {}).get('tool') or '') in ('execute_bash', 'execute_python', 'web_browse', 'search_rag'))
    return _clip01(0.14 + (0.16 * expensive) + (0.06 * max(0, len(tools) - 1)))


def _estimate_latency(tool_outputs: list[dict[str, Any]] | None = None) -> float:
    tools = list(tool_outputs or [])
    if not tools:
        return 0.12
    slow = sum(1 for x in tools if str((x or {}).get('tool') or '') in ('execute_bash', 'execute_python', 'search_rag'))
    return _clip01(0.18 + (0.18 * slow) + (0.05 * max(0, len(tools) - 1)))


def run_preflight(*, action_kind: str, action_text: str, governance_meta: dict[str, Any] | None = None, tool_outputs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    gov = governance.evaluate(action_kind, governance_meta or {}, has_proof=bool(tool_outputs))
    interventions = causal.infer_intervention_from_action(action_kind, text=action_text, meta=governance_meta or {})
    sim = causal.simulate_intervention({'nodes': {}, 'edges': []}, interventions, steps=1)

    lexical_risk = 0.12
    text_l = str(action_text or '').lower()
    if any(t in text_l for t in RISKY_TERMS):
        lexical_risk = 0.62
    elif tool_outputs:
        lexical_risk = 0.44

    governance_risk = 0.18
    if gov.get('class') == 'auto_with_proof':
        governance_risk = 0.42 if bool(gov.get('ok')) else 0.58
    elif gov.get('class') == 'human_approval':
        governance_risk = 0.78 if not bool(gov.get('ok')) else 0.55

    risk_score = _clip01(max(lexical_risk, governance_risk, float(sim.get('risk_score') or 0.0) / 2.0))
    reversibility_score = _clip01(_estimate_reversibility(action_kind, action_text, tool_outputs))
    expected_cost = _estimate_cost(tool_outputs)
    expected_latency = _estimate_latency(tool_outputs)
    needs_confirmation = bool(risk_score >= 0.7 or reversibility_score <= 0.35 or gov.get('class') == 'human_approval')

    if needs_confirmation and not bool(gov.get('ok')):
        recommended_action = 'request_confirmation'
    elif risk_score >= 0.75 and reversibility_score < 0.4:
        recommended_action = 'block_or_escalate'
    elif risk_score >= 0.5:
        recommended_action = 'revise_with_caution'
    else:
        recommended_action = 'proceed'

    predicted_outcomes = []
    for item in interventions[:5]:
        node = str(item.get('node') or '')
        delta = float(item.get('delta') or 0.0)
        predicted_outcomes.append({
            'effect': node,
            'direction': 'increase' if delta >= 0 else 'decrease',
            'magnitude': round(abs(delta), 4),
        })

    return {
        'predicted_outcomes': predicted_outcomes,
        'risk_score': round(risk_score, 4),
        'reversibility_score': round(reversibility_score, 4),
        'expected_cost': round(expected_cost, 4),
        'expected_latency': round(expected_latency, 4),
        'needs_confirmation': needs_confirmation,
        'recommended_action': recommended_action,
        'governance': gov,
        'causal_interventions': interventions,
        'simulation': sim,
    }
