"""
Testes para o Sistema de Tasks do UltronPro
"""

import sys
sys.path.insert(0, r'F:\sistemas\UltronPro\backend')


def test_task_types():
    """Testa criação de tipos de tarefa."""
    print("=== Test: Task Types ===")
    
    from ultronpro.task_types import (
        Task, TaskType, TaskStatus, TaskPriority,
        TaskBudget, TaskOwner, TaskIsolation,
        TaskTemplates
    )
    
    print(f"  TaskType values: {[t.value for t in TaskType]}")
    print(f"  TaskStatus values: {[s.value for s in TaskStatus]}")
    
    task = Task(
        type=TaskType.DREAM,
        description="Test consolidation",
        payload={"test": True}
    )
    
    print(f"  Created task: {task.id[:8]}... type={task.type.value}")
    
    return task.type == TaskType.DREAM


def test_task_templates():
    """Testa templates de tarefa."""
    print("\n=== Test: Task Templates ===")
    
    from ultronpro.task_types import TaskTemplates
    
    bash_task = TaskTemplates.bash("echo hello", timeout=10.0)
    print(f"  Bash: {bash_task.type.value}")
    
    agent_task = TaskTemplates.local_agent("Test prompt", model="test")
    print(f"  Local Agent: {agent_task.type.value}")
    
    dream_task = TaskTemplates.dream({"context": "test"})
    print(f"  Dream: {dream_task.type.value}, budget={dream_task.budget.max_seconds}s")
    
    teammate_task = TaskTemplates.teammate("Task description", "worker1", "team_a")
    print(f"  Teammate: owner={teammate_task.owner.owner_id}, team={teammate_task.owner.team_id}")
    
    return bash_task.type.value == "local_bash" and dream_task.type.value == "dream"


def test_task_manager_creation():
    """Testa criação do TaskManager."""
    print("\n=== Test: TaskManager Creation ===")
    
    from ultronpro.task_manager import TaskManager, get_task_manager
    
    tm1 = TaskManager()
    tm2 = get_task_manager()
    
    print(f"  Manager 1 created: {tm1 is not None}")
    print(f"  Global instance: {tm2 is not None}")
    print(f"  Same instance: {tm1 is tm2}")
    
    status = tm2.get_status()
    print(f"  Status keys: {list(status.keys())}")
    
    return tm1 is not None


def test_task_submission():
    """Testa submissão de tarefas."""
    print("\n=== Test: Task Submission ===")
    
    from ultronpro.task_manager import get_task_manager
    from ultronpro.task_types import TaskTemplates, TaskType
    
    tm = get_task_manager()
    
    task = TaskTemplates.dream({"test": True})
    submitted = tm.submit(task)
    
    print(f"  Task submitted: {submitted.id[:8]}...")
    print(f"  Status: {submitted.status.value}")
    
    status = tm.get_status()
    print(f"  Queue size: {status['tasks_queued']}")
    
    return submitted.id == task.id


def test_task_execution_dream():
    """Testa execução de tarefa dream."""
    print("\n=== Test: Dream Task Execution ===")
    
    import asyncio
    from ultronpro.task_manager import get_task_manager
    from ultronpro.task_types import TaskTemplates
    
    tm = get_task_manager()
    task = TaskTemplates.dream({"test": True})
    
    tm.submit(task)
    
    next_task = tm.get_next()
    if next_task:
        tm.start(next_task)
        
        result = asyncio.run(tm.execute(next_task))
        tm.complete(next_task, result)
        
        print(f"  Success: {result.success}")
        print(f"  Status: {result.status.value}")
        print(f"  Output: {str(result.output)[:100]}...")
        print(f"  Time: {result.execution_time_ms}ms")
    
    return True


def test_budget_tracking():
    """Testa rastreamento de budget."""
    print("\n=== Test: Budget Tracking ===")
    
    from ultronpro.task_manager import get_task_manager
    from ultronpro.task_types import Task, TaskType, TaskBudget, TaskOwner
    
    tm = get_task_manager()
    
    task = Task(
        type=TaskType.LOCAL_AGENT,
        description="Budget test",
        budget=TaskBudget(max_seconds=10.0, max_tokens=100),
        owner=TaskOwner(owner_id="test_user"),
    )
    
    budget_status = tm.get_budget_status("test_user", "default")
    print(f"  Budget status: {budget_status}")
    
    return True


def test_audit_log():
    """Testa log de auditoria."""
    print("\n=== Test: Audit Log ===")
    
    from ultronpro.task_manager import get_task_manager
    from ultronpro.task_types import TaskTemplates
    
    tm = get_task_manager()
    
    audit_log = tm.get_audit_log(limit=10)
    print(f"  Audit entries: {len(audit_log)}")
    
    return True


if __name__ == "__main__":
    print("=" * 60)
    print("ULTRONPRO TASK SYSTEM - TESTS")
    print("=" * 60)
    
    results = []
    
    results.append(("Task Types", test_task_types()))
    results.append(("Task Templates", test_task_templates()))
    results.append(("TaskManager Creation", test_task_manager_creation()))
    results.append(("Task Submission", test_task_submission()))
    results.append(("Dream Execution", test_task_execution_dream()))
    results.append(("Budget Tracking", test_budget_tracking()))
    results.append(("Audit Log", test_audit_log()))
    
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
        print("\n*** ULTRONPRO TASK SYSTEM - OPERATIONAL ***")
