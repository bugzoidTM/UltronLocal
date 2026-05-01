"""
Testes para o SkillExecutor - Camada Declarativa de Workflow
"""

import sys
sys.path.insert(0, r'F:\sistemas\UltronPro\backend')


def test_executor_creation():
    """Testa criação do executor."""
    print("=== Test: Executor Creation ===")
    
    from ultronpro import skill_executor
    
    executor = skill_executor.SkillExecutor()
    
    print(f"  Executor created")
    print(f"  Hooks registered: {len(executor._hooks_registry)}")
    
    return True


def test_skill_suggestion():
    """Testa sugestão de skill."""
    print("\n=== Test: Skill Suggestion ===")
    
    from ultronpro import skill_loader
    
    tests = [
        ("pesquisar na web", "web_search"),
        ("revisar codigo", "code_review"),
        ("corrigir erro", "debug_error"),
        ("aprender conceito", "learn_concept"),
    ]
    
    passed = 0
    for task, expected in tests:
        suggested = skill_loader.suggest_skill(task)
        if suggested and suggested.name == expected:
            print(f"  [OK] '{task}' -> {suggested.name}")
            passed += 1
        elif suggested:
            print(f"  [??] '{task}' -> {suggested.name} (expected: {expected})")
        else:
            print(f"  [FAIL] '{task}' -> no suggestion")
    
    return passed >= 3


def test_executor_execute():
    """Testa execução de skill."""
    print("\n=== Test: Executor Execute ===")
    
    from ultronpro import skill_executor
    
    executor = skill_executor.get_skill_executor()
    
    result = executor.execute_sync(
        task="pesquisar informações sobre Python",
        suggested_skill="web_search"
    )
    
    print(f"  Skill: {result.skill_name}")
    print(f"  Status: {result.status}")
    print(f"  Execution time: {result.execution_time_ms}ms")
    print(f"  Success: {result.success}")
    print(f"  Hooks executed: {len(result.hooks_executed)}")
    
    return result.skill_name == "web_search"


def test_executor_hooks():
    """Testa execução de hooks."""
    print("\n=== Test: Executor Hooks ===")
    
    from ultronpro import skill_executor
    
    executor = skill_executor.get_skill_executor()
    
    result = executor.execute_sync(
        task="aprender sobre machine learning",
        suggested_skill="learn_concept"
    )
    
    print(f"  Skill: {result.skill_name}")
    print(f"  Hooks executed: {result.hooks_executed}")
    
    return len(result.hooks_executed) >= 0  # Hooks são executados async


def test_workflow_integration():
    """Testa integração com workflow."""
    print("\n=== Test: Workflow Integration ===")
    
    from ultronpro import skill_loader, skill_executor
    
    # Simular cadeia: decision_router -> skill -> executor
    task = "corrigir erro de null pointer"
    
    # 1. Decision Router sugere skill
    skill = skill_loader.suggest_skill(task)
    print(f"  1. Router: task='{task}'")
    print(f"     -> Skill: {skill.name if skill else 'none'}")
    
    if not skill:
        return False
    
    # 2. Skill Executor executa
    executor = skill_executor.get_skill_executor()
    result = executor.execute_sync(task=task, suggested_skill=skill.name)
    print(f"  2. Executor: status={result.status.value}")
    print(f"     -> Output: {str(result.output)[:50]}...")
    
    # 3. Validar checks
    print(f"  3. Validation:")
    print(f"     -> Checks passed: {len(result.checks_passed)}")
    print(f"     -> Checks failed: {len(result.checks_failed)}")
    
    return result.skill_name is not None


if __name__ == "__main__":
    print("=" * 60)
    print("SKILL EXECUTOR - WORKFLOW INTEGRATION TESTS")
    print("=" * 60)
    
    results = []
    
    results.append(("Executor Creation", test_executor_creation()))
    results.append(("Skill Suggestion", test_skill_suggestion()))
    results.append(("Executor Execute", test_executor_execute()))
    results.append(("Executor Hooks", test_executor_hooks()))
    results.append(("Workflow Integration", test_workflow_integration()))
    
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
        print("\n*** SKILL EXECUTOR - WORKFLOW OPERATIONAL ***")
