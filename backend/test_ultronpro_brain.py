"""
Testes para o Motor de Raciocínio Próprio - UltronPro Brain

Verifica se o chat funciona SEM LLM cloud.
O cérebro é o motor determinístico, não a API externa.
"""

import sys
sys.path.insert(0, r'F:\sistemas\UltronPro\backend')

import os

# Configure UTF-8 encoding
os.environ['PYTHONIOENCODING'] = 'utf-8'
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')


def test_classification():
    """Testa classificação determinística de intents."""
    print("=== Test: Intent Classification ===")
    
    from ultronpro.main import _classify_query_type
    
    test_cases = [
        ("bom dia", "greeting"),
        ("olá", "greeting"),
        ("como vai?", "greeting"),
        ("quem é você?", "identity"),
        ("como você funciona?", "identity"),
        ("o que é isso?", "factual"),
        ("qual a capital?", "factual"),
        ("obrigado", "thanks"),
        ("me ajude", "task"),
        ("faça uma análise", "task"),
        ("você acha que...", "opinion"),
    ]
    
    passed = 0
    for query, expected in test_cases:
        result = _classify_query_type(query.lower())
        status = "OK" if result == expected else "FAIL"
        if result == expected:
            passed += 1
            print(f"  [{status}] '{query}' -> {result}")
        else:
            print(f"  [{status}] '{query}' -> {result} (expected: {expected})")
    
    print(f"Classification: {passed}/{len(test_cases)} passed")
    return passed >= len(test_cases) - 1


def test_identity_response():
    """Testa resposta de identidade (sem LLM)."""
    print("\n=== Test: Identity Response ===")
    
    from ultronpro.main import _classify_query_type
    
    q = "quem é você?"
    intent = _classify_query_type(q.lower())
    
    print(f"  Query: '{q}'")
    print(f"  Intent: {intent}")
    
    if intent == 'identity':
        print("  OK - Identity intent correctly detected")
        return True
    
    return False


def test_greeting_response():
    """Testa resposta de saudação contextual."""
    print("\n=== Test: Greeting Response ===")
    
    from ultronpro.main import _classify_query_type
    from datetime import datetime
    
    queries = ["olá", "bom dia", "boa noite", "oi"]
    
    for q in queries:
        intent = _classify_query_type(q.lower())
        print(f"  '{q}' -> {intent}")
        if intent != 'greeting':
            print(f"    FAIL - Expected greeting")
            return False
    
    hour = datetime.now().hour
    print(f"  Current hour: {hour}")
    print("  OK - All greetings correctly classified")
    return True


def test_reasoning_engine():
    """Testa motor de raciocínio."""
    print("\n=== Test: Reasoning Engine ===")
    
    from ultronpro.main import _reasoning_engine
    
    q = "teste de raciocínio"
    ql = q.lower()
    
    try:
        result = _reasoning_engine(q, ql)
        print(f"  Query: '{q}'")
        print(f"  Response length: {len(result)} chars")
        
        if len(result) > 20:
            print("  OK - Reasoning engine returns valid response")
            return True
    except Exception as e:
        print(f"  FAIL - Error: {e}")
    
    return False


if __name__ == "__main__":
    print("=" * 60)
    print("ULTRONPRO BRAIN - TESTS")
    print("=" * 60)
    
    results = []
    
    results.append(("Intent Classification", test_classification()))
    results.append(("Identity Response", test_identity_response()))
    results.append(("Greeting Response", test_greeting_response()))
    results.append(("Reasoning Engine", test_reasoning_engine()))
    
    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)
    
    passed = 0
    for name, result in results:
        status = "PASS" if result else "FAIL"
        print(f"  [{status}] {name}")
        if result:
            passed += 1
    
    print(f"\nTotal: {passed}/{len(results)} passed")
    
    if passed == len(results):
        print("\n*** ULTRONPRO BRAIN - OPERACIONAL ***")
