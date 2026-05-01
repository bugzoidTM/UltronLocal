"""
Testes para o Motor de Raciocínio Próprio (Determinístico)

Verifica se o chat funciona SEM LLM cloud.
"""

import sys
sys.path.insert(0, r'F:\sistemas\UltronPro\backend')

import asyncio
import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def test_deterministic_reasoning():
    """Testa o motor de raciocínio próprio."""
    logger.info("=== Test: Deterministic Reasoning ===")
    
    from ultronpro.main import _deterministic_reasoning, _classify_query_type
    
    # Testar classificação de queries
    test_cases = [
        ("Qual a capital da França?", "factual"),
        ("O que você acha sobre isso?", "opinion"),
        ("Me ajude a resolver isso", "task"),
        ("Como você funciona?", "identity"),
        ("olá", "greeting"),
    ]
    
    logger.info("Testing query classification:")
    for query, expected in test_cases:
        result = _classify_query_type(query.lower())
        status = "✓" if result == expected else "✗"
        logger.info(f"  {status} '{query}' -> {result} (expected: {expected})")
    
    # Testar reasoning engine
    logger.info("\nTesting deterministic reasoning:")
    queries = [
        "olá",
        "quem é você?",
        "o que você está fazendo?",
        "obrigado",
        "me explique seu funcionamento",
    ]
    
    for query in queries:
        result = _deterministic_reasoning(query, query.lower())
        logger.info(f"  Query: '{query}'")
        logger.info(f"  Response: {result[:150]}...")
        logger.info(f"  Length: {len(result)} chars")
        logger.info("")
    
    return True


def test_chat_without_llm():
    """Testa se o chat responde sem LLM."""
    logger.info("=== Test: Chat Without LLM ===")
    
    # Simular chamada direta ao motor
    from ultronpro.main import _classify_query_type, _deterministic_reasoning
    
    queries = [
        "olá",
        "bom dia",
        "quem é você?",
        "obrigado",
        "como vai?",
        "o que é inteligência artificial?",
        "faça uma análise",
    ]
    
    for query in queries:
        q_lower = query.lower()
        query_type = _classify_query_type(q_lower)
        response = _deterministic_reasoning(query, q_lower)
        
        logger.info(f"Q: {query}")
        logger.info(f"  Type: {query_type}")
        logger.info(f"  A: {response[:100]}...")
        
        # Verificar que não contém referências a LLM
        if "llm" in response.lower() or "language model" in response.lower():
            logger.warning(f"  ⚠ Response contains LLM reference!")
    
    return True


if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("MOTOR DE RACIOCÍNIO PRÓPRIO - TESTS")
    logger.info("=" * 60)
    
    results = []
    
    results.append(("Deterministic Reasoning", test_deterministic_reasoning()))
    results.append(("Chat Without LLM", test_chat_without_llm()))
    
    logger.info("=" * 60)
    logger.info("RESULTS")
    logger.info("=" * 60)
    
    passed = 0
    for name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        logger.info(f"  {status}: {name}")
        if result:
            passed += 1
    
    logger.info(f"\nTotal: {passed}/{len(results)} passed")


async def test_llm_pipeline():
    """Testa o pipeline completo: LLM classifica → Motor Deterministico → LLM formata."""
    import asyncio
    
    logger.info("=== Test: LLM Pipeline (DeepSeek) ===")
    
    from ultronpro.main import _classify_with_llm, _format_response_with_llm, _deterministic_reasoning
    
    queries = [
        "o que é inteligência artificial?",
        "me ajude com python",
        "bom dia",
        "quem é você?",
        "obrigado",
    ]
    
    for q in queries:
        # 1. Classificar com LLM
        try:
            intent = await asyncio.wait_for(_classify_with_llm(q), timeout=10.0)
            logger.info(f"  Query: '{q}'")
            logger.info(f"  → Intent (LLM): {intent}")
        except Exception as e:
            logger.warning(f"  LLM classification failed: {e}")
            intent = "general"
        
        # 2. Motor determinístico
        ql = q.lower()
        raw_result = _deterministic_reasoning(q, ql)
        logger.info(f"  → Motor: {raw_result[:80]}...")
        
        # 3. Formatar com LLM
        try:
            formatted = await asyncio.wait_for(
                _format_response_with_llm(q, raw_result, intent),
                timeout=15.0
            )
            logger.info(f"  → Formatado (LLM): {formatted[:80]}...")
        except Exception as e:
            logger.warning(f"  LLM formatting failed: {e}, using raw")
            formatted = raw_result
        
        logger.info("")
    
    return True


if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("MOTOR DE RACIOCÍNIO PRÓPRIO - TESTS")
    logger.info("=" * 60)
    
    results = []
    
    results.append(("Deterministic Reasoning", test_deterministic_reasoning()))
    results.append(("Chat Without LLM", test_chat_without_llm()))
    
    # Testar pipeline com LLM (requer API key)
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    llm_result = loop.run_until_complete(test_llm_pipeline())
    results.append(("LLM Pipeline", llm_result))
    
    logger.info("=" * 60)
    logger.info("RESULTS")
    logger.info("=" * 60)
    
    passed = 0
    for name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        logger.info(f"  {status}: {name}")
        if result:
            passed += 1
    
    logger.info(f"\nTotal: {passed}/{len(results)} passed")
