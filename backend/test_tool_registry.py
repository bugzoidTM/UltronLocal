"""
Testes para o Tool Registry do UltronPro
"""

import sys
sys.path.insert(0, r'F:\sistemas\UltronPro\backend')


def test_registry_creation():
    """Testa criação do registry."""
    print("=== Test: Registry Creation ===")
    
    from ultronpro.tool_registry import get_tool_registry
    
    registry = get_tool_registry()
    print(f"  Tools registered: {len(registry._tools)}")
    print(f"  Categories: {registry.get_categories()}")
    
    return len(registry._tools) > 0


def test_tool_specs():
    """Testa specs de ferramentas."""
    print("\n=== Test: Tool Specs ===")
    
    from ultronpro.tool_registry import get_tool_registry
    from ultronpro.tool_registry_specs import ToolCategory, RiskLevel
    
    registry = get_tool_registry()
    
    web_search = registry.get("web.search")
    if web_search:
        print(f"  web.search: cost={web_search.cost.max_seconds}s, risk={web_search.risk.level.value}")
    
    bash_run = registry.get("bash.run")
    if bash_run:
        print(f"  bash.run: requires_confirm={bash_run.requires_approval}")
    
    return web_search is not None and bash_run is not None


def test_tool_search():
    """Testa busca de ferramentas."""
    print("\n=== Test: Tool Search ===")
    
    from ultronpro.tool_registry import get_tool_registry
    from ultronpro.tool_registry_specs import ToolCategory
    
    registry = get_tool_registry()
    
    results = registry.find(category=ToolCategory.WEB)
    print(f"  Web tools: {len(results)}")
    for t in results[:3]:
        print(f"    - {t.name}")
    
    results = registry.find(query="memory")
    print(f"  Memory tools: {len(results)}")
    
    return len(results) > 0


def test_tool_suggestion():
    """Testa sugestão de ferramentas."""
    print("\n=== Test: Tool Suggestion ===")
    
    from ultronpro.tool_registry import get_tool_registry
    
    registry = get_tool_registry()
    
    tests = [
        ("buscar na web", ["web.search"]),
        ("ler arquivo", ["file.read"]),
        ("executar bash", ["bash.run"]),
        ("memória", ["memory.rag", "memory.graph"]),
    ]
    
    passed = 0
    for task, expected in tests:
        suggested = registry.suggest(task)
        names = [s.name for s in suggested]
        print(f"  '{task}' -> {names[:2]}")
        
        if any(e in names for e in expected):
            passed += 1
    
    return passed >= 3


def test_authorization():
    """Testa autorização de ferramentas."""
    print("\n=== Test: Authorization ===")
    
    from ultronpro.tool_registry import get_tool_registry
    
    registry = get_tool_registry()
    
    safe_auth = registry.check_authorization("web.search")
    print(f"  web.search: allowed={safe_auth.allowed}")
    
    bash_auth = registry.check_authorization("bash.run")
    print(f"  bash.run: allowed={bash_auth.allowed}, requires_confirm={bash_auth.requires_confirmation}")
    
    return safe_auth.allowed and not bash_auth.allowed


def test_tool_execution():
    """Testa execução de ferramentas."""
    print("\n=== Test: Tool Execution ===")
    
    import asyncio
    from ultronpro.tool_registry import get_tool_registry
    
    registry = get_tool_registry()
    
    async def run():
        result = await registry.execute("memory.cache", {"query": "test"})
        print(f"  memory.cache: ok={result.get('ok')}")
        return result.get("ok", False)
    
    return asyncio.run(run())


def test_stats():
    """Testa estatísticas."""
    print("\n=== Test: Stats ===")
    
    from ultronpro.tool_registry import get_tool_registry
    
    registry = get_tool_registry()
    
    stats = registry.get_stats()
    print(f"  Tools with stats: {len(stats)}")
    
    web_stats = registry.get_stats("web.search")
    if web_stats:
        print(f"  web.search stats: {web_stats.get('stats', {})}")
    
    return len(stats) > 0


def test_builtin_tools():
    """Testa tools builtin integradas."""
    print("\n=== Test: Builtin Tools ===")
    
    import asyncio
    from ultronpro.tool_registry import get_tool_registry
    
    registry = get_tool_registry()
    
    async def run():
        result = await registry.execute("web.search", {"query": "test"})
        print(f"  web.search: ok={result.get('ok')}")
        return result.get("ok", False)
    
    return asyncio.run(run())


if __name__ == "__main__":
    print("=" * 60)
    print("ULTRONPRO TOOL REGISTRY - TESTS")
    print("=" * 60)
    
    results = []
    
    results.append(("Registry Creation", test_registry_creation()))
    results.append(("Tool Specs", test_tool_specs()))
    results.append(("Tool Search", test_tool_search()))
    results.append(("Tool Suggestion", test_tool_suggestion()))
    results.append(("Authorization", test_authorization()))
    results.append(("Tool Execution", test_tool_execution()))
    results.append(("Stats", test_stats()))
    results.append(("Builtin Tools", test_builtin_tools()))
    
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
        print("\n*** ULTRONPRO TOOL REGISTRY - OPERATIONAL ***")
