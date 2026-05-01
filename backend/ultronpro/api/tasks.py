"""
Task system routes.
"""
from __future__ import annotations

from fastapi import APIRouter

from ultronpro import task_manager, task_types

router = APIRouter(tags=["Tasks"])


# ==================== TASK SYSTEM ENDPOINTS ====================

@router.get("/api/tasks/status")
async def tasks_status():
    """Status do sistema de tarefas."""
    try:
        tm = task_manager.get_task_manager()
        return tm.get_status()
    except Exception as e:
        return {"error": str(e)}


@router.get("/api/tasks/list")
async def tasks_list(status: str = None, limit: int = 50):
    """Lista tarefas."""
    try:
        tm = task_manager.get_task_manager()
        task_status = task_types.TaskStatus(status) if status else None
        tasks = tm.list_tasks(status=task_status, limit=limit)
        return {"ok": True, "tasks": [t.to_dict() for t in tasks], "count": len(tasks)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/api/tasks/submit")
async def tasks_submit(
    task_type: str = "local_agent",
    description: str = "",
    payload: dict = None,
    priority: int = 5,
    max_seconds: float = 60.0,
):
    """Submete uma nova tarefa."""
    try:
        tm = task_manager.get_task_manager()
        tt = task_types.TaskType(task_type)
        task = task_types.Task(
            type=tt,
            description=description,
            payload=payload or {},
            priority=task_types.TaskPriority(priority),
            budget=task_types.TaskBudget(max_seconds=max_seconds),
        )
        submitted = tm.submit(task)
        return {"ok": True, "task": submitted.to_dict()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/api/tasks/execute/{task_id}")
async def tasks_execute(task_id: str):
    """Executa uma tarefa."""
    try:
        tm = task_manager.get_task_manager()
        task = tm.get_task(task_id)
        if not task:
            return {"ok": False, "error": "Task not found"}
        
        tm.start(task)
        result = await tm.execute(task)
        completed = tm.complete(task, result)
        return {"ok": completed.success, "result": completed.to_dict()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/api/tasks/{task_id}")
async def tasks_get(task_id: str):
    """ObtÃ©m detalhes de uma tarefa."""
    try:
        tm = task_manager.get_task_manager()
        task = tm.get_task(task_id)
        if not task:
            return {"ok": False, "error": "Task not found"}
        return {"ok": True, "task": task.to_dict()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/api/tasks/{task_id}/cancel")
async def tasks_cancel(task_id: str):
    """Cancela uma tarefa."""
    try:
        tm = task_manager.get_task_manager()
        success = tm.cancel(task_id)
        return {"ok": success}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/api/tasks/budget/{owner_id}")
async def tasks_budget(owner_id: str, team_id: str = "default"):
    """Status de budget de um owner."""
    try:
        tm = task_manager.get_task_manager()
        return tm.get_budget_status(owner_id, team_id)
    except Exception as e:
        return {"error": str(e)}


@router.get("/api/tasks/metrics")
async def tasks_metrics():
    """MÃ©tricas do sistema de tarefas."""
    try:
        tm = task_manager.get_task_manager()
        return tm.get_metrics()
    except Exception as e:
        return {"error": str(e)}

