from __future__ import annotations
import json
import logging
from typing import Any

logger = logging.getLogger("uvicorn")

def reflect_on_failure(goal: dict[str, Any], attempt: dict[str, Any], history: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Analisa uma tentativa fracassada e sugere mudanças.
    Usa um modelo mental para diagnosticar se o problema foi:
    1. Erro de sintaxe/ambiente
    2. Plano mal formulado
    3. Premissa errada (Modelo de mundo desatualizado)
    """
    error = attempt.get('error_text', 'Erro desconhecido')
    plan = attempt.get('plan_json', '{}')
    
    # Heurística local simples (Lane-0)
    diagnosis = "Incerteza operacional alta."
    suggestion = "Tentar abordagem alternativa ou revisar parâmetros."
    
    if 'timeout' in error.lower():
        diagnosis = "Gargalo de latência ou rede."
        suggestion = "Aumentar timeout e adicionar backoff."
    elif 'syntax' in error.lower() or 'not defined' in error.lower():
        diagnosis = "Erro de codificação/lógica no plano gerado."
        suggestion = "Refinar prompt do planejador para ser mais rigoroso com a sintaxe Python."
        
    # Se tivermos lane-1 (LLM rápido), usamos para reflexão profunda
    try:
        from ultronpro import llm
        prompt = f"""
        OBJETIVO: {goal.get('title')}
        DESCRIÇÃO: {goal.get('description')}
        PLANO EXECUTADO: {plan}
        ERRO RECEBIDO: {error}
        HISTÓRIO DE TENTATIVAS: {len(history)}
        
        Como diagnosticador do UltronPro, analise o erro acima.
        Responda em JSON:
        {{
            "diagnosis": "...",
            "suggestion": "...",
            "retry_strategy": "adjust_parameters | change_logic | abort"
        }}
        """
        # Usamos lane_1 (Groq/Llama-70b ou similar)
        res_text = llm.generate_lane_1(prompt, system_prompt="Você é o componente REFLECTOR do UltronPro AGI.")
        res = json.loads(res_text)
        return res
    except Exception as e:
        logger.warning(f"Reflector: Lane-1 reflection failed, using heuristics: {e}")
        return {
            'diagnosis': diagnosis,
            'suggestion': suggestion,
            'retry_strategy': 'adjust_parameters'
        }
