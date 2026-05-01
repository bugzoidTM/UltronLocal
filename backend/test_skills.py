"""
Testes para o Sistema de Skills do UltronPro
"""

import sys
sys.path.insert(0, r'F:\sistemas\UltronPro\backend')


def test_skill_loader():
    """Testa carregamento de skills."""
    print("=== Test: Skill Loader ===")
    
    from ultronpro import skill_loader
    
    loader = skill_loader.SkillLoader()
    skills = loader.load_all()
    
    print(f"  Loaded {len(skills)} skills:")
    for name, skill in skills.items():
        print(f"    - {name}: {skill.risk_level} risk, {len(skill.allowed_tools)} tools")
    
    return len(skills) >= 4


def test_skill_structure():
    """Testa estrutura de um skill."""
    print("\n=== Test: Skill Structure ===")
    
    from ultronpro import skill_loader
    
    skill = skill_loader.get_skill('web_search')
    
    if not skill:
        print("  FAIL - web_search skill not found")
        return False
    
    print(f"  Name: {skill.name}")
    print(f"  Risk: {skill.risk_level}")
    print(f"  Budget: {skill.get_budget_limit()}s")
    print(f"  Tools: {skill.allowed_tools}")
    print(f"  Tags: {skill.tags}")
    print(f"  Enabled: {skill.enabled}")
    
    return skill.name == 'web_search' and skill.risk_level == 'low'


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
            print(f"  [FAIL] '{task}' -> no suggestion (expected: {expected})")
    
    return passed >= 3


def test_skill_status():
    """Testa status dos skills."""
    print("\n=== Test: Skill Status ===")
    
    from ultronpro import skill_loader
    
    status = skill_loader.get_skill_loader().get_status()
    
    print(f"  Total: {status['total']}")
    print(f"  Enabled: {status['enabled']}")
    print(f"  By Risk: {status['by_risk']}")
    print(f"  Tags: {status['tags']}")
    
    return status['total'] >= 4 and status['enabled'] >= 4


if __name__ == "__main__":
    print("=" * 60)
    print("ULTRONPRO SKILLS - TESTS")
    print("=" * 60)
    
    results = []
    
    results.append(("Skill Loader", test_skill_loader()))
    results.append(("Skill Structure", test_skill_structure()))
    results.append(("Skill Suggestion", test_skill_suggestion()))
    results.append(("Skill Status", test_skill_status()))
    
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
        print("\n*** ULTRONPRO SKILLS - OPERATIONAL ***")
