from __future__ import annotations

from typing import Any
import time


def _score(text: str, kws: list[str]) -> int:
    t = (text or '').lower()
    return sum(1 for k in kws if k in t)


def infer_user_intent(experiences: list[dict[str, Any]]) -> dict[str, Any]:
    """Inferência leve de intenção do usuário (empatia cognitiva funcional).

    Labels:
    - confused: usuário busca explicação/clareza
    - testing: usuário está testando robustez/capacidade
    - urgent: quer resultado rápido/prioritário
    - exploratory: exploração aberta/estratégica
    """
    recent = experiences[-12:] if experiences else []
    txt = "\n".join((e.get('text') or '')[:300] for e in recent)
    tl = txt.lower()

    s_confused = _score(tl, ['não entendi', 'confuso', 'explica', 'por quê', 'porque', 'como funciona', 'diferença'])
    s_testing = _score(tl, ['teste', 'prova', 'benchmark', 'robusto', 'falha', 'quero ver', 'stress'])
    s_urgent = _score(tl, ['rápido', 'agora', 'urgente', 'imediato', 'pra já', 'sem enrolação'])
    s_explore = _score(tl, ['mapear', 'explorar', 'pesquisar', 'visão geral', 'currículo', 'roadmap', 'longo prazo'])

    scores = {
        'confused': s_confused,
        'testing': s_testing,
        'urgent': s_urgent,
        'exploratory': s_explore,
    }

    label = max(scores, key=lambda k: scores[k])
    raw = scores[label]

    # prior neutro quando não há sinal claro
    if raw <= 0:
        label = 'exploratory'
        conf = 0.35
    else:
        total = sum(scores.values())
        conf = min(0.95, max(0.4, raw / max(1, total)))

    # Estimate cognitive load and trust from experience history
    # Simple proxies: frequency of "not understood" vs successful turns
    user_load = min(1.0, (s_confused * 0.2) + (len(recent) * 0.05))
    user_trust = max(0.2, 0.8 - (s_testing * 0.1) - (s_confused * 0.05))

    rationale_map = {
        'confused': 'sinal de dúvida/clareza conceitual',
        'testing': 'sinal de avaliação de robustez',
        'urgent': 'sinal de prioridade temporal',
        'exploratory': 'sinal de exploração aberta e aprendizado amplo',
    }

    return {
        'label': label,
        'confidence': round(conf, 3),
        'scores': scores,
        'rationale': rationale_map.get(label),
        'evidence_excerpt': txt[:260],
        'user_model': {
            'intent': label,
            'cognitive_load': round(user_load, 2),
            'trust_level': round(user_trust, 2),
            'last_seen': int(time.time()),
        }
    }


def predict_reaction(
    *,
    user_model: dict[str, Any],
    action_kind: str,
    action_risk: float,
    causal_outcomes: list[dict[str, Any]]
) -> dict[str, Any]:
    """Simulação mental pré-ação: como o usuário reagirá ao resultado causal previsto?"""
    
    intent = user_model.get('intent', 'exploratory')
    load = float(user_model.get('cognitive_load', 0.5))
    trust = float(user_model.get('trust_level', 0.8))
    
    reaction_valence = 0.0  # Positive or negative impact on user satisfaction
    reaction_arousal = 0.2  # Intensity of reaction
    
    # Heuristics for reaction based on intent and predicted outcomes
    # 1. Urgent users hate high latency/complexity
    if intent == 'urgent':
        for o in causal_outcomes:
            if 'latency' in o['effect'] or 'cost' in o['effect']:
                reaction_valence -= 0.3
                reaction_arousal += 0.4

    # 2. Confused users hate high cognitive load or ambiguous interventions
    if intent == 'confused':
        if load > 0.7:
             reaction_valence -= 0.2
        reaction_arousal += 0.2

    # 3. Risky actions without explanation hurt trust
    if action_risk > 0.6:
        reaction_valence -= (action_risk * 0.5)
        reaction_arousal += 0.5
        
    # 4. Positive causal effects (benefit) improve valence
    for o in causal_outcomes:
        if o['direction'] == 'increase' and o['magnitude'] > 0.4:
            # Assume beneficial nodes (this should be refined with actual benefit scores)
            reaction_valence += 0.1
    
    # Clip results
    predicted_satisfaction_delta = round(max(-1.0, min(1.0, reaction_valence)), 2)
    predicted_arousal = round(max(0.0, min(1.0, reaction_arousal)), 2)
    
    if predicted_satisfaction_delta < -0.4:
        posture = 'apologetic_and_transparent'
    elif predicted_satisfaction_delta > 0.3:
        posture = 'confident_and_reinforcing'
    else:
        posture = 'neutral_informative'

    return {
        'satisfaction_delta': predicted_satisfaction_delta,
        'arousal': predicted_arousal,
        'recommended_posture': posture,
        'rationale': f"Previsão de reação para intenção '{intent}' diante de risco {action_risk:.2f}"
    }
