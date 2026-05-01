"""
Testes para o Operational Memory System do UltronPro
"""

import sys
import os
import tempfile
import shutil
sys.path.insert(0, r'F:\sistemas\UltronPro\backend')


def test_memory_creation():
    """Testa criação de memória operacional."""
    print("=== Test: Memory Creation ===")
    
    from ultronpro.operational_memory import (
        OperationalMemory, MemoryContext, MemoryScope, MemoryLayer
    )
    
    context = MemoryContext(
        project_path=tempfile.gettempdir(),
        environment="test",
    )
    
    mem = OperationalMemory(context)
    
    print(f"  Project hash: {context.project_hash}")
    print(f"  Memory root: {context.get_scope_path(MemoryScope.GLOBAL)}")
    
    return mem is not None


def test_human_memory():
    """Testa memória humana."""
    print("\n=== Test: Human Memory ===")
    
    from ultronpro.operational_memory import OperationalMemory, MemoryContext, MemoryScope
    
    with tempfile.TemporaryDirectory() as tmpdir:
        context = MemoryContext(project_path=tmpdir, environment="test")
        mem = OperationalMemory(context)
        
        content = "# Test Instructions\n- Use Python 3.11+\n- Run tests before commit"
        
        success = mem.write_human_memory(content, scope=MemoryScope.PROJECT)
        print(f"  Write success: {success}")
        
        read = mem.read_human_memory(scope=MemoryScope.PROJECT)
        print(f"  Read length: {len(read)} chars")
        print(f"  Contains 'Python': {'Python' in read}")
        
        return success and "Python" in read


def test_learned_memory():
    """Testa memória de aprendizados."""
    print("\n=== Test: Learned Memory ===")
    
    from ultronpro.operational_memory import OperationalMemory, MemoryContext, MemoryScope
    
    with tempfile.TemporaryDirectory() as tmpdir:
        context = MemoryContext(project_path=tmpdir, environment="test")
        mem = OperationalMemory(context)
        
        content = "This command takes 5s on average\nOptimize with caching"
        
        success = mem.write_learned_memory(
            content,
            scope=MemoryScope.PROJECT,
            tags=["performance"],
            source="benchmark"
        )
        print(f"  Write success: {success}")
        
        read = mem.read_learned_memory(scope=MemoryScope.PROJECT)
        print(f"  Contains 'command': {'command' in read}")
        
        return success and "command" in read


def test_auto_memory():
    """Testa memória automática."""
    print("\n=== Test: Auto Memory ===")
    
    from ultronpro.operational_memory import OperationalMemory, MemoryContext, MemoryScope
    
    with tempfile.TemporaryDirectory() as tmpdir:
        context = MemoryContext(project_path=tmpdir, environment="test")
        mem = OperationalMemory(context)
        
        entry_id = mem.add_auto_entry(
            content="npm install takes 30s without cache",
            scope=MemoryScope.PROJECT,
            tags=["command", "npm"],
            source="observation"
        )
        print(f"  Entry ID: {entry_id}")
        
        entries = mem.read_auto_memory(scope=MemoryScope.PROJECT)
        print(f"  Entries count: {len(entries)}")
        
        return entry_id is not None and len(entries) > 0


def test_scope_isolation():
    """Testa isolamento por escopo."""
    print("\n=== Test: Scope Isolation ===")
    
    from ultronpro.operational_memory import OperationalMemory, MemoryContext, MemoryScope
    
    with tempfile.TemporaryDirectory() as tmpdir:
        context = MemoryContext(project_path=tmpdir, environment="test")
        mem = OperationalMemory(context)
        
        mem.write_human_memory("GLOBAL content", scope=MemoryScope.GLOBAL)
        mem.write_human_memory("PROJECT content", scope=MemoryScope.PROJECT)
        mem.write_human_memory("ENV content", scope=MemoryScope.ENVIRONMENT)
        
        global_read = mem.read_human_memory(scope=MemoryScope.GLOBAL)
        project_read = mem.read_human_memory(scope=MemoryScope.PROJECT)
        env_read = mem.read_human_memory(scope=MemoryScope.ENVIRONMENT)
        
        print(f"  Global has 'GLOBAL': {'GLOBAL' in global_read}")
        print(f"  Project has 'PROJECT': {'PROJECT' in project_read}")
        print(f"  Env has 'ENV': {'ENV' in env_read}")
        print(f"  Global has 'PROJECT': {'PROJECT' in global_read}")
        
        return ("GLOBAL" in global_read and "PROJECT" in project_read and 
                "ENV" in env_read and "PROJECT" not in global_read)


def test_query():
    """Testa busca de memória."""
    print("\n=== Test: Query ===")
    
    from ultronpro.operational_memory import OperationalMemory, MemoryContext, MemoryScope
    
    with tempfile.TemporaryDirectory() as tmpdir:
        context = MemoryContext(project_path=tmpdir, environment="test")
        mem = OperationalMemory(context)
        
        mem.write_learned_memory(
            "Python 3.11 has 15% performance improvement over 3.10",
            scope=MemoryScope.PROJECT,
            tags=["python", "performance"]
        )
        
        mem.add_auto_entry(
            "pytest runs 100 tests in 5 seconds",
            scope=MemoryScope.PROJECT,
            tags=["testing", "pytest"]
        )
        
        results = mem.query("python performance")
        print(f"  Results count: {len(results)}")
        print(f"  Top score: {results[0]['score'] if results else 0:.2f}")
        
        return len(results) > 0


def test_learn_convenience():
    """Testa método learn()."""
    print("\n=== Test: Learn Convenience ===")
    
    from ultronpro.operational_memory import OperationalMemory, MemoryContext, MemoryScope
    
    with tempfile.TemporaryDirectory() as tmpdir:
        context = MemoryContext(project_path=tmpdir, environment="test")
        mem = OperationalMemory(context)
        
        success = mem.learn(
            "Run linter before commit\nUse ruff instead of flake8",
            category="code_style"
        )
        print(f"  Learn success: {success}")
        
        read = mem.read_learned_memory(scope=MemoryScope.PROJECT)
        print(f"  Contains 'linter': {'linter' in read}")
        
        return success and "linter" in read


def test_learn_command():
    """Testa aprendizado de comando."""
    print("\n=== Test: Learn Command ===")
    
    from ultronpro.operational_memory import OperationalMemory, MemoryContext, MemoryScope
    
    with tempfile.TemporaryDirectory() as tmpdir:
        context = MemoryContext(project_path=tmpdir, environment="test")
        mem = OperationalMemory(context)
        
        entry_id = mem.learn_command(
            command="npm run build",
            working_dir=tmpdir,
            success=True,
            output="Build completed in 10s"
        )
        print(f"  Entry ID: {entry_id}")
        
        entries = mem.read_auto_memory(scope=MemoryScope.PROJECT)
        print(f"  Entries: {len(entries)}")
        print(f"  Has 'npm': {any('npm' in e.content for e in entries)}")
        
        return entry_id is not None


def test_build_context():
    """Testa construção de contexto."""
    print("\n=== Test: Build Context ===")
    
    from ultronpro.operational_memory import OperationalMemory, MemoryContext, MemoryScope
    
    with tempfile.TemporaryDirectory() as tmpdir:
        context = MemoryContext(project_path=tmpdir, environment="test")
        mem = OperationalMemory(context)
        
        mem.write_human_memory("# Human\nAlways run tests", scope=MemoryScope.GLOBAL)
        mem.write_learned_memory("## Learned\nDocker is faster than podman", scope=MemoryScope.PROJECT)
        
        context_str = mem.build_session_context(max_chars=1000)
        print(f"  Context length: {len(context_str)} chars")
        print(f"  Contains 'Human': {'Human' in context_str}")
        print(f"  Contains 'Learned': {'Learned' in context_str}")
        
        return "Human" in context_str and "Learned" in context_str


def test_session_lifecycle():
    """Testa ciclo de vida de sessão."""
    print("\n=== Test: Session Lifecycle ===")
    
    from ultronpro.operational_memory import get_operational_memory, end_session
    
    with tempfile.TemporaryDirectory() as tmpdir:
        mem = get_operational_memory(project_path=tmpdir, environment="test")
        
        start_result = mem.session_start()
        print(f"  Session ID: {start_result['session_id']}")
        print(f"  Loaded scopes: {list(start_result['loaded'].keys())}")
        
        end_result = end_session()
        print(f"  End status: {end_result['status']}")
        
        return start_result['session_id'] and end_result['status'] == 'ended'


def test_stats():
    """Testa estatísticas."""
    print("\n=== Test: Stats ===")
    
    from ultronpro.operational_memory import OperationalMemory, MemoryContext, MemoryScope
    
    with tempfile.TemporaryDirectory() as tmpdir:
        context = MemoryContext(project_path=tmpdir, environment="test")
        mem = OperationalMemory(context)
        
        mem.write_human_memory("# Test", scope=MemoryScope.GLOBAL)
        mem.write_learned_memory("Test learned", scope=MemoryScope.GLOBAL)
        mem.add_auto_entry("Test entry", scope=MemoryScope.GLOBAL)
        
        stats = mem.get_stats(scope=MemoryScope.GLOBAL)
        print(f"  Global stats: {stats.get('global', {})}")
        
        return stats.get('global', {}).get('human_chars', 0) > 0


if __name__ == "__main__":
    print("=" * 60)
    print("ULTRONPRO OPERATIONAL MEMORY - TESTS")
    print("=" * 60)
    
    results = []
    
    results.append(("Memory Creation", test_memory_creation()))
    results.append(("Human Memory", test_human_memory()))
    results.append(("Learned Memory", test_learned_memory()))
    results.append(("Auto Memory", test_auto_memory()))
    results.append(("Scope Isolation", test_scope_isolation()))
    results.append(("Query", test_query()))
    results.append(("Learn Convenience", test_learn_convenience()))
    results.append(("Learn Command", test_learn_command()))
    results.append(("Build Context", test_build_context()))
    results.append(("Session Lifecycle", test_session_lifecycle()))
    results.append(("Stats", test_stats()))
    
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
        print("\n*** ULTRONPRO OPERATIONAL MEMORY - OPERATIONAL ***")
