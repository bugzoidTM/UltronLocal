"""
Testes automáticos para o loop de reforço autônomo

Executa verificação completa do sistema:
1. Server initialization
2. Autonomous loop modules
3. Self-corrector
4. API endpoints
"""

import sys
import time
import asyncio
sys.path.insert(0, r'F:\sistemas\UltronPro\backend')

import httpx
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BASE_URL = "http://127.0.0.1:8000"


def test_imports():
    """Test 1: Verificar se todos os módulos importam corretamente."""
    logger.info("=== Test 1: Module Imports ===")
    
    try:
        from ultronpro.autonomous_loop import get_autonomous_loop
        from ultronpro.autonomous_executor import get_executor
        from ultronpro.self_corrector import get_self_corrector
        from ultronpro import intrinsic_utility
        logger.info("✓ All modules import successfully")
        return True
    except Exception as e:
        logger.error(f"✗ Import failed: {e}")
        return False


def test_autonomous_loop():
    """Test 2: Verificar autonomous_loop."""
    logger.info("=== Test 2: Autonomous Loop ===")
    
    try:
        from ultronpro.autonomous_loop import get_autonomous_loop
        
        aloop = get_autonomous_loop()
        status = aloop.get_status()
        
        logger.info(f"  Enabled: {status.get('enabled')}")
        logger.info(f"  Reward weights: {status.get('reward_weights')}")
        logger.info(f"  Active goals: {status.get('active_goals')}")
        
        # Test reward signal
        aloop.record_action('test_action', 'test_context', True, 100, 0.8)
        logger.info("✓ Reward signal recorded")
        
        return True
    except Exception as e:
        logger.error(f"✗ Autonomous loop failed: {e}")
        return False


def test_intrinsic_utility():
    """Test 3: Verificar intrinsic_utility (objetivos emergentes)."""
    logger.info("=== Test 3: Intrinsic Utility ===")
    
    try:
        from ultronpro import intrinsic_utility
        
        # Get current state
        state = intrinsic_utility._load()
        logger.info(f"  Drives: {list(state.get('drives', {}).keys())}")
        logger.info(f"  Utility: {state.get('utility', 0):.2f}")
        logger.info(f"  Tick count: {state.get('tick_count', 0)}")
        
        # Run tick to derive goal
        result = intrinsic_utility.tick()
        logger.info(f"  Tick result - utility: {result.get('utility', 0):.2f}")
        
        goal = result.get('active_emergent_goal')
        if goal:
            logger.info(f"  Active goal: {goal.get('title', 'No title')}")
            logger.info(f"  Goal drive: {goal.get('drive', 'unknown')}")
        else:
            logger.info("  No active goal (all drives satisfied)")
        
        logger.info("✓ Intrinsic utility working")
        return True
    except Exception as e:
        logger.error(f"✗ Intrinsic utility failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_self_corrector():
    """Test 4: Verificar self_corrector."""
    logger.info("=== Test 4: Self Corrector ===")
    
    try:
        from ultronpro.self_corrector import get_self_corrector, learn_from_error, record_success
        
        corrector = get_self_corrector()
        status = corrector.get_status()
        
        logger.info(f"  Patterns tracked: {status.get('patterns_tracked', 0)}")
        logger.info(f"  Lessons learned: {status.get('lessons_learned', 0)}")
        logger.info(f"  Overall success rate: {status.get('overall_success_rate', 0):.0%}")
        
        # Record a test failure
        result = learn_from_error(
            action='test_action',
            context='test_context',
            error='Test error for validation'
        )
        logger.info(f"  Learn result: correction_applied={result.get('correction_applied')}")
        
        # Record success
        record_success('test_action', 'test_context')
        logger.info("✓ Self corrector working")
        
        return True
    except Exception as e:
        logger.error(f"✗ Self corrector failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_autonomous_executor():
    """Test 5: Verificar autonomous_executor."""
    logger.info("=== Test 5: Autonomous Executor ===")
    
    try:
        from ultronpro.autonomous_executor import get_executor
        import asyncio
        
        executor = get_executor()
        status = executor.get_status()
        
        logger.info(f"  Enabled: {status.get('enabled')}")
        logger.info(f"  Current goal: {status.get('current_goal')}")
        logger.info(f"  Subtasks pending: {status.get('subtasks_pending', 0)}")
        
        # Run a cycle
        async def run_cycle():
            return await executor.execute_autonomous_cycle()
        
        result = asyncio.run(run_cycle())
        logger.info(f"  Cycle result: completed={result.get('completed')}, score={result.get('overall_score', 0):.0%}")
        logger.info(f"  Cycle feedback: {result.get('feedback', 'N/A')[:100]}")
        
        logger.info("✓ Autonomous executor working")
        return True
    except Exception as e:
        logger.error(f"✗ Autonomous executor failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_api_endpoints():
    """Test 6: Verificar API endpoints."""
    logger.info("=== Test 6: API Endpoints ===")
    
    try:
        client = httpx.Client(timeout=10.0)
        
        # Test status endpoint
        r = client.get(f"{BASE_URL}/api/autonomous/status")
        logger.info(f"  GET /api/autonomous/status: {r.status_code}")
        if r.status_code != 200:
            logger.error(f"    Failed: {r.text[:200]}")
            return False
        
        # Test emergent goal endpoint
        r = client.get(f"{BASE_URL}/api/autonomous/emergent-goal")
        logger.info(f"  GET /api/autonomous/emergent-goal: {r.status_code}")
        
        # Test executor status
        r = client.get(f"{BASE_URL}/api/autonomous/executor/status")
        logger.info(f"  GET /api/autonomous/executor/status: {r.status_code}")
        
        # Test self-corrector status
        r = client.get(f"{BASE_URL}/api/autonomous/self-corrector/status")
        logger.info(f"  GET /api/autonomous/self-corrector/status: {r.status_code}")
        
        client.close()
        logger.info("✓ API endpoints working")
        return True
    except httpx.ConnectError:
        logger.error("✗ Cannot connect to server - is it running on port 8000?")
        return False
    except Exception as e:
        logger.error(f"✗ API test failed: {e}")
        return False


def run_all_tests():
    """Executa todos os testes."""
    logger.info("=" * 60)
    logger.info("AUTONOMOUS LOOP - AUTOMATED TESTS")
    logger.info("=" * 60)
    
    results = []
    
    results.append(("Module Imports", test_imports()))
    results.append(("Autonomous Loop", test_autonomous_loop()))
    results.append(("Intrinsic Utility", test_intrinsic_utility()))
    results.append(("Self Corrector", test_self_corrector()))
    results.append(("Autonomous Executor", test_autonomous_executor()))
    results.append(("API Endpoints", test_api_endpoints()))
    
    logger.info("=" * 60)
    logger.info("TEST RESULTS")
    logger.info("=" * 60)
    
    passed = 0
    for name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        logger.info(f"  {status}: {name}")
        if result:
            passed += 1
    
    logger.info(f"\nTotal: {passed}/{len(results)} passed")
    
    return passed == len(results)


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
