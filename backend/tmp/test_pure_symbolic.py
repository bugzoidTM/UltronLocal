import sys, os
from pathlib import Path
sys.path.insert(0, str(Path("f:/sistemas/UltronPro/backend").resolve()))

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
from ultronpro import symbolic_reasoner

def run_tests():
    print("=== Testing Purely Symbolic Reasoning (Phase 7.1) ===")
    
    # Test 1: Sequence Induction (Arithmetic)
    q1 = "Qual o próximo número na sequência: 2, 4, 6, 8?"
    res1 = symbolic_reasoner.solve(q1)
    print(f"\nQ1: {q1}")
    print(f"A1: {res1.get('answer', 'FAILED')}")
    assert "10" in res1.get('answer', '')
    
    # Test 2: Sequence Induction (Quadratic)
    q2 = "Qual o próximo número na sequência: 1, 4, 9, 16?"
    res2 = symbolic_reasoner.solve(q2)
    print(f"\nQ2: {q2}")
    print(f"A2: {res2.get('answer', 'FAILED')}")
    assert "25" in res2.get('answer', '')

    # Test 3: Math (Square Root)
    q3 = "Qual a raiz quadrada de 144?"
    res3 = symbolic_reasoner.solve(q3)
    print(f"\nQ3: {q3}")
    print(f"A3: {res3.get('answer', 'FAILED')}")
    assert "12" in res3.get('answer', '')

    # Test 4: Percentages
    q4 = "Quanto é 15% de 200?"
    res4 = symbolic_reasoner.solve(q4)
    print(f"\nQ4: {q4}")
    print(f"A4: {res4.get('answer', 'FAILED')}")
    assert "30" in res4.get('answer', '')

    # Test 5: Quadratic Equation (via SymPy)
    q5 = "Resolva a equação x^2 - 5x + 6 = 0"
    res5 = symbolic_reasoner.solve(q5)
    print(f"\nQ5: {q5}")
    print(f"A5: {res5.get('answer', 'FAILED')}")
    assert "2" in res5.get('answer', '') and "3" in res5.get('answer', '')

    print("\n=== All SYMBOLIC tests passed! (Zero API calls involved) ===")

if __name__ == "__main__":
    run_tests()
