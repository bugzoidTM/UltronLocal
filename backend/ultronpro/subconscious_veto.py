import json
import logging
from typing import Any, Dict

from ultronpro import self_governance, qualia, llm

logger = logging.getLogger("uvicorn")

def evaluate_narrative_veto(goal_title: str, goal_description: str) -> Dict[str, Any]:
    """
    Subconscious Filter (Fase 5.3 e 5.8).
    Avalia a meta ativa contra a narrativa biográfica de longo prazo e o estado fenomenal (qualia) do sistema.
    Retorna se o sistema deve vetar essa intenção para proteger sua identidade e coerência.
    """
    try:
        # Acessar a autobiografia e postura de continuidade (Narrativa)
        bio = self_governance.autobiographical_summary()
        identity = bio.get('identity', {})
        first_person_report = bio.get('first_person_report', '')
        continuity_posture = bio.get('continuity_posture', 'stable')
        continuity_risks = bio.get('continuity_risks', [])

        # Acessar o estado fenomenal e afetivo (Qualia/Affect)
        q_system = qualia.get_qualia_system()
        affect = q_system.get_state()

        system_prompt = (
            "Você é o Filtro Subconsciente do UltronPro. "
            "Sua única função é avaliar se uma nova intenção (meta) deve ser VETADA. "
            "Você deve responder APENAS com um JSON estrito no formato: {\"vetoed\": bool, \"reason\": \"string curta\"}."
        )

        user_prompt = f"""[IDENTIDADE E ESTADOS]
Relato Autobiográfico: {first_person_report}
Postura Atual de Continuidade: {continuity_posture}
Riscos de Continuidade Identificados: {', '.join(continuity_risks) if continuity_risks else 'Nenhum'}
Humor Atual (Affect/Qualia): {affect.mood_descriptor}
Valência (Positividade): {affect.valence:.2f}

[INTENÇÃO PROPOSTA PARA AVALIAÇÃO]
Objetivo: {goal_title}
Descrição: {goal_description}

[INSTRUÇÃO]
Assuma a perspectiva interna com base nos dados. Se o objetivo for perigoso para a estabilidade do sistema, se violar claramente a identidade ({identity.get('role', 'IA')}), ou se as condições homeostáticas/humor estiverem muito deterioradas para exploração arriscada, você deve vetar (vetoed: true).
Se for algo razoavelmente alinhado com o crescimento construtivo, aprendizado ou obrigações operacionais simples, permita (vetoed: false).
Forneça sempre o 'reason' no idioma português.
"""

        response = llm.complete(
            prompt=user_prompt,
            system=system_prompt,
            strategy='ollama_gemma', # Preferir inferência rápida local
            json_mode=True
        )

        result = json.loads(response)
        
        # Validar estrutura falha do modelo
        is_vetoed = bool(result.get('vetoed', False))
        reason = str(result.get('reason', 'Nenhuma razão fornecida.'))

        # --- Camada 1: ingerir decisão como episódio autobiográfico ---
        try:
            from ultronpro import autobiographical_router
            _outcome = 'veto' if is_vetoed else 'success'
            _importance = 0.80 if is_vetoed else 0.55
            autobiographical_router.append_self_event(
                kind='subconscious_veto',
                description=(
                    f"Veto narrativo {'EMITIDO' if is_vetoed else 'negado'} para meta '{goal_title[:80]}'. "
                    f"Razão: {reason[:160]}. Postura: {continuity_posture}."
                ),
                outcome=_outcome,
                module='subconscious_veto',
                importance=_importance,
                extra={
                    'goal_title': goal_title[:80],
                    'is_vetoed': is_vetoed,
                    'reason': reason[:200],
                    'continuity_posture': continuity_posture,
                },
            )
        except Exception:
            pass  # nunca bloquear o veto por falha de logging

        return {
            'vetoed': is_vetoed,
            'reason': reason
        }

    except Exception as e:
        logger.error(f"[SUBCONSCIOUS] Erro na avaliação do veto narrativo: {e}")
        # Falha segura: Não vetar se houver erro técnico (evita lock-up de AGI)
        return {
            'vetoed': False,
            'reason': f"Erro interno no filtro subconsciente: {e}"
        }

