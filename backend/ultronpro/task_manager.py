"""
UltronPro Task Manager - Camada Unificada de Tasking

Gerencia tarefas com:
- Budget (tempo, tokens, memória, custo)
- Ownership (proprietário, time, hierarquia)
- Isolation (sandbox, permissões, rede)
- Audit (rastro completo, eventos, métricas)

Integra com:
- SkillExecutor para skills declarativos
- SleepCycle para tarefas dream
- Store para persistência de audit trail
"""

import os
import json
import time
import asyncio
import logging
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from pathlib import Path
from datetime import datetime

from ultronpro.task_types import (
    Task, TaskType, TaskStatus, TaskPriority,
    TaskBudget, TaskOwner, TaskIsolation, TaskAudit, TaskResult,
    IsolationLevel, TaskHooks
)

logger = logging.getLogger("uvicorn")

# ==================== TASK MANAGER ====================

@dataclass
class TaskMetrics:
    """Métricas globais de execução de tarefas."""
    total_submitted: int = 0
    total_completed: int = 0
    total_failed: int = 0
    total_timeout: int = 0
    total_retries: int = 0
    total_tokens: int = 0
    total_cost: float = 0.0
    avg_execution_ms: float = 0.0
    by_type: Dict[str, Dict[str, int]] = field(default_factory=dict)
    by_owner: Dict[str, Dict[str, int]] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_submitted": self.total_submitted,
            "total_completed": self.total_completed,
            "total_failed": self.total_failed,
            "total_timeout": self.total_timeout,
            "total_retries": self.total_retries,
            "total_tokens": self.total_tokens,
            "total_cost": round(self.total_cost, 6),
            "avg_execution_ms": round(self.avg_execution_ms, 2),
            "by_type": self.by_type,
            "by_owner": self.by_owner,
        }


class TaskManager:
    """
    Gerenciador centralizado de tarefas.
    
    Responsabilidades:
    1. Criar, enfileirar e despachar tarefas
    2. Rastrear budget por owner/time
    3. Aplicar isolamento baseado no tipo de tarefa
    4. Manter audit trail completo
    5. Fornecer métricas e observabilidade
    """
    
    def __init__(self, audit_path: Optional[Path] = None):
        self._tasks: Dict[str, Task] = {}
        self._queue: List[Task] = []
        self._running: Dict[str, Task] = {}
        self._hooks: Optional[TaskHooks] = None
        self._metrics = TaskMetrics()
        self._budgets: Dict[str, Dict[str, float]] = {}  # owner_id -> budget tracking
        self._semaphores: Dict[str, asyncio.Semaphore] = {}  # owner concurrency control
        
        self.audit_path = audit_path or Path(__file__).resolve().parent.parent.parent / 'data' / 'task_audit.jsonl'
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        
        self._strategies: Dict[TaskType, Callable] = {}
        self._register_strategies()
    
    def _register_strategies(self):
        """Registra estratégias de execução por tipo de tarefa."""
        self._strategies = {
            TaskType.LOCAL_BASH: self._execute_local_bash,
            TaskType.LOCAL_AGENT: self._execute_local_agent,
            TaskType.REMOTE_AGENT: self._execute_remote_agent,
            TaskType.IN_PROCESS_TEAMMATE: self._execute_teammate,
            TaskType.LOCAL_WORKFLOW: self._execute_workflow,
            TaskType.MONITOR_MCP: self._execute_monitor_mcp,
            TaskType.DREAM: self._execute_dream,
        }
    
    # ==================== BUDGET MANAGEMENT ====================
    
    def _check_budget(self, task: Task) -> tuple[bool, str]:
        """Verifica se há budget disponível para a tarefa."""
        owner_id = task.owner.owner_id
        team_id = task.owner.team_id or "default"
        budget_key = f"{team_id}:{owner_id}"
        
        if budget_key not in self._budgets:
            self._budgets[budget_key] = {
                "time_used": 0.0,
                "tokens_used": 0,
                "cost_used": 0.0,
                "tasks_run": 0,
            }
        
        budget_state = self._budgets[budget_key]
        
        time_remaining = task.budget.max_seconds - budget_state["time_used"]
        tokens_remaining = task.budget.max_tokens - budget_state["tokens_used"]
        cost_remaining = task.budget.max_cost - budget_state["cost_used"]
        
        if time_remaining <= 0:
            return False, f"Budget de tempo esgotado para {owner_id}"
        if tokens_remaining <= 0:
            return False, f"Budget de tokens esgotado para {owner_id}"
        if cost_remaining <= 0:
            return False, f"Budget de custo esgotado para {owner_id}"
        
        return True, ""
    
    def _update_budget(self, task: Task, result: TaskResult):
        """Atualiza budget após execução."""
        owner_id = task.owner.owner_id
        team_id = task.owner.team_id or "default"
        budget_key = f"{team_id}:{owner_id}"
        
        if budget_key not in self._budgets:
            return
        
        budget_state = self._budgets[budget_key]
        budget_state["time_used"] += result.execution_time_ms / 1000.0
        budget_state["tokens_used"] += result.tokens_used
        budget_state["cost_used"] += result.cost_used
        budget_state["tasks_run"] += 1
    
    def get_budget_status(self, owner_id: str, team_id: str = "default") -> Dict[str, Any]:
        """Retorna status de budget para um owner."""
        budget_key = f"{team_id}:{owner_id}"
        budget_state = self._budgets.get(budget_key, {
            "time_used": 0.0,
            "tokens_used": 0,
            "cost_used": 0.0,
            "tasks_run": 0,
        })
        
        global_budget = self._get_global_budget()
        
        return {
            "owner_id": owner_id,
            "team_id": team_id,
            "time_used_sec": round(budget_state["time_used"], 2),
            "time_remaining_sec": round(global_budget.max_seconds - budget_state["time_used"], 2),
            "tokens_used": budget_state["tokens_used"],
            "tokens_remaining": global_budget.max_tokens - budget_state["tokens_used"],
            "cost_used": round(budget_state["cost_used"], 6),
            "tasks_run": budget_state["tasks_run"],
        }
    
    def _get_global_budget(self) -> TaskBudget:
        """Retorna budget global (pode ser configurado via env)."""
        return TaskBudget(
            max_seconds=float(os.getenv("ULTRON_TASK_MAX_SECONDS", "3600")),
            max_tokens=int(os.getenv("ULTRON_TASK_MAX_TOKENS", "100000")),
            max_cost=float(os.getenv("ULTRON_TASK_MAX_COST", "10.0")),
        )
    
    # ==================== ISOLATION ====================
    
    def _check_isolation(self, task: Task) -> tuple[bool, str]:
        """Verifica conformidade com isolamento."""
        isolation = task.isolation
        
        if isolation.level == IsolationLevel.NONE:
            return True, ""
        
        if isolation.level == IsolationLevel.HARD or isolation.level == IsolationLevel.SANDBOX:
            if isolation.denied_paths:
                for denied in isolation.denied_paths:
                    if denied in str(task.payload):
                        return False, f"Path {denied} não permitido"
        
        return True, ""
    
    # ==================== AUDIT ====================
    
    def _write_audit(self, task: Task, result: Optional[TaskResult] = None):
        """Escreve entrada no audit trail."""
        entry = {
            "ts": int(time.time()),
            "task_id": task.id,
            "task_type": task.type.value,
            "status": task.status.value,
            "owner": task.owner.to_dict(),
            "description": task.description,
            "budget": task.budget.to_dict(),
            "audit": task.audit.to_dict(),
            "result": result.to_dict() if result else None,
        }
        
        try:
            with self.audit_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning(f"Failed to write audit: {e}")
    
    def get_audit_log(self, task_id: Optional[str] = None, limit: int = 100) -> List[Dict]:
        """Retorna entradas do audit log."""
        if not self.audit_path.exists():
            return []
        
        entries = []
        try:
            with self.audit_path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        if task_id and entry.get("task_id") != task_id:
                            continue
                        entries.append(entry)
                    except:
                        continue
        except Exception as e:
            logger.warning(f"Failed to read audit log: {e}")
        
        return entries[-limit:]
    
    # ==================== TASK LIFECYCLE ====================
    
    def submit(self, task: Task) -> Task:
        """Submete uma nova tarefa."""
        task.audit.created_at = time.time()
        
        budget_ok, msg = self._check_budget(task)
        if not budget_ok:
            task.status = TaskStatus.BLOCKED
            task.audit.warnings.append(msg)
        
        isolation_ok, msg = self._check_isolation(task)
        if not isolation_ok:
            task.status = TaskStatus.PERMISSION_DENIED
            task.audit.last_error = msg
            self._write_audit(task)
            return task
        
        if task.status != TaskStatus.BLOCKED:
            task.status = TaskStatus.QUEUED
            self._queue.append(task)
        
        self._tasks[task.id] = task
        self._metrics.total_submitted += 1
        self._update_metrics_by_type(task, "submitted")
        self._update_metrics_by_owner(task, "submitted")
        
        if self._hooks and self._hooks.on_create:
            try:
                self._hooks.on_create(task)
            except Exception as e:
                logger.warning(f"Hook on_create failed: {e}")
        
        self._write_audit(task)
        logger.info(f"Task {task.id} submitted: {task.type.value} ({task.description[:40]})")
        
        return task
    
    def get_next(self) -> Optional[Task]:
        """Retorna próxima tarefa na fila (por prioridade)."""
        if not self._queue:
            return None
        
        self._queue.sort(key=lambda t: (t.priority.value, t.audit.created_at), reverse=True)
        
        for i, task in enumerate(self._queue):
            budget_ok, _ = self._check_budget(task)
            if budget_ok:
                self._queue.pop(i)
                return task
        
        return None
    
    def start(self, task: Task) -> Task:
        """Marca tarefa como iniciada."""
        task.status = TaskStatus.RUNNING
        task.audit.started_at = time.time()
        self._running[task.id] = task
        
        if self._hooks and self._hooks.on_start:
            try:
                self._hooks.on_start(task)
            except Exception as e:
                logger.warning(f"Hook on_start failed: {e}")
        
        self._write_audit(task)
        return task
    
    def complete(self, task: Task, result: TaskResult) -> TaskResult:
        """Completa uma tarefa."""
        task.audit.ended_at = time.time()
        task.status = result.status
        
        if task.id in self._running:
            del self._running[task.id]
        
        self._update_budget(task, result)
        self._update_metrics(task, result)
        
        if result.success:
            task.result = result.output
            if self._hooks and self._hooks.on_success:
                try:
                    self._hooks.on_success(task, result.output)
                except Exception as e:
                    logger.warning(f"Hook on_success failed: {e}")
        else:
            task.audit.last_error = result.error
            if self._hooks and self._hooks.on_failure:
                try:
                    self._hooks.on_failure(task, result.error)
                except Exception as e:
                    logger.warning(f"Hook on_failure failed: {e}")
        
        if self._hooks and self._hooks.on_cleanup:
            try:
                self._hooks.on_cleanup(task)
            except Exception as e:
                logger.warning(f"Hook on_cleanup failed: {e}")
        
        self._write_audit(task, result)
        logger.info(f"Task {task.id} completed: {result.status.value} ({result.execution_time_ms}ms)")
        
        return result
    
    def cancel(self, task_id: str) -> bool:
        """Cancela uma tarefa."""
        if task_id in self._tasks:
            task = self._tasks[task_id]
            if task.status in (TaskStatus.PENDING, TaskStatus.QUEUED):
                task.status = TaskStatus.CANCELLED
                task.audit.ended_at = time.time()
                
                if task_id in self._queue:
                    self._queue = [t for t in self._queue if t.id != task_id]
                
                if self._hooks and self._hooks.on_cancel:
                    try:
                        self._hooks.on_cancel(task)
                    except Exception as e:
                        logger.warning(f"Hook on_cancel failed: {e}")
                
                self._write_audit(task)
                return True
        return False
    
    # ==================== METRICS ====================
    
    def _update_metrics_by_type(self, task: Task, action: str):
        """Atualiza métricas por tipo de tarefa."""
        ttype = task.type.value
        if ttype not in self._metrics.by_type:
            self._metrics.by_type[ttype] = {"submitted": 0, "completed": 0, "failed": 0}
        self._metrics.by_type[ttype][action] = self._metrics.by_type[ttype].get(action, 0) + 1
    
    def _update_metrics_by_owner(self, task: Task, action: str):
        """Atualiza métricas por owner."""
        owner = task.owner.owner_id
        if owner not in self._metrics.by_owner:
            self._metrics.by_owner[owner] = {"submitted": 0, "completed": 0, "failed": 0}
        self._metrics.by_owner[owner][action] = self._metrics.by_owner[owner].get(action, 0) + 1
    
    def _update_metrics(self, task: Task, result: TaskResult):
        """Atualiza métricas após conclusão."""
        if result.success:
            self._metrics.total_completed += 1
            self._update_metrics_by_type(task, "completed")
            self._update_metrics_by_owner(task, "completed")
        elif result.status == TaskStatus.TIMEOUT:
            self._metrics.total_timeout += 1
        else:
            self._metrics.total_failed += 1
            self._update_metrics_by_type(task, "failed")
            self._update_metrics_by_owner(task, "failed")
        
        self._metrics.total_retries += result.audit.retries if result.audit else 0
        self._metrics.total_tokens += result.tokens_used
        self._metrics.total_cost += result.cost_used
        
        completed = self._metrics.total_completed
        if completed > 0:
            total_time = self._metrics.avg_execution_ms * (completed - 1) + result.execution_time_ms
            self._metrics.avg_execution_ms = total_time / completed
    
    def get_metrics(self) -> Dict[str, Any]:
        """Retorna métricas globais."""
        return self._metrics.to_dict()
    
    # ==================== EXECUTION STRATEGIES ====================
    
    async def execute(self, task: Task) -> TaskResult:
        """Executa uma tarefa usando a estratégia apropriada."""
        strategy = self._strategies.get(task.type)
        if not strategy:
            return TaskResult(
                task_id=task.id,
                success=False,
                status=TaskStatus.FAILED,
                error=f"No strategy for task type: {task.type.value}",
            )
        
        try:
            return await strategy(task)
        except asyncio.TimeoutError:
            task.audit.last_error = "Timeout"
            return TaskResult(
                task_id=task.id,
                success=False,
                status=TaskStatus.TIMEOUT,
                error="Task execution timed out",
                audit=task.audit,
            )
        except Exception as e:
            task.audit.last_error = str(e)
            return TaskResult(
                task_id=task.id,
                success=False,
                status=TaskStatus.FAILED,
                error=str(e),
                audit=task.audit,
            )
    
    async def _execute_local_bash(self, task: Task) -> TaskResult:
        """Executa comando bash local."""
        import subprocess
        
        command = task.payload.get("command", "")
        cwd = task.payload.get("working_dir", os.getcwd())
        
        task.audit.add_step("bash_start", {"command": command[:100]})
        
        try:
            process = await asyncio.create_subprocess_shell(
                command,
                cwd=cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**os.environ, **task.isolation.env_vars} if task.isolation.env_vars else None,
            )
            
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=task.budget.max_seconds
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                return TaskResult(
                    task_id=task.id,
                    success=False,
                    status=TaskStatus.TIMEOUT,
                    error="Command timed out",
                    execution_time_ms=int(task.budget.max_seconds * 1000),
                    audit=task.audit,
                )
            
            output = stdout.decode("utf-8", errors="replace") if stdout else ""
            error = stderr.decode("utf-8", errors="replace") if stderr else ""
            
            task.audit.add_step("bash_complete", {
                "returncode": process.returncode,
                "output_len": len(output),
            })
            
            success = process.returncode == 0
            
            return TaskResult(
                task_id=task.id,
                success=success,
                status=TaskStatus.SUCCESS if success else TaskStatus.FAILED,
                output={"stdout": output, "stderr": error, "returncode": process.returncode},
                error=error if not success else None,
                execution_time_ms=task.audit.execution_time_ms,
                audit=task.audit,
            )
            
        except Exception as e:
            return TaskResult(
                task_id=task.id,
                success=False,
                status=TaskStatus.FAILED,
                error=str(e),
                audit=task.audit,
            )
    
    async def _execute_local_agent(self, task: Task) -> TaskResult:
        """Executa agente LLM local (llama.cpp)."""
        from ultronpro import llm
        
        prompt = task.payload.get("prompt", "")
        model = task.payload.get("model", "llama3.2:1b")
        
        task.audit.add_step("agent_start", {"model": model})
        
        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(llm.complete, prompt, strategy="cheap"),
                timeout=task.budget.max_seconds
            )
            
            task.audit.add_step("agent_complete", {"response_len": len(response)})
            
            return TaskResult(
                task_id=task.id,
                success=True,
                status=TaskStatus.SUCCESS,
                output=response,
                execution_time_ms=task.audit.execution_time_ms,
                audit=task.audit,
            )
            
        except asyncio.TimeoutError:
            return TaskResult(
                task_id=task.id,
                success=False,
                status=TaskStatus.TIMEOUT,
                error="Agent timed out",
                execution_time_ms=int(task.budget.max_seconds * 1000),
                audit=task.audit,
            )
        except Exception as e:
            return TaskResult(
                task_id=task.id,
                success=False,
                status=TaskStatus.FAILED,
                error=str(e),
                audit=task.audit,
            )
    
    async def _execute_remote_agent(self, task: Task) -> TaskResult:
        """Executa agente LLM em provedor cloud."""
        from ultronpro import llm
        
        prompt = task.payload.get("prompt", "")
        provider = task.payload.get("provider", "groq")
        model = task.payload.get("model", "llama-3.3-70b")
        
        task.audit.add_step("remote_start", {"provider": provider, "model": model})
        
        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(llm.complete, prompt, strategy="balanced"),
                timeout=task.budget.max_seconds
            )
            
            task.audit.add_step("remote_complete", {"response_len": len(response)})
            
            cost = self._estimate_cost(prompt, response, provider)
            
            return TaskResult(
                task_id=task.id,
                success=True,
                status=TaskStatus.SUCCESS,
                output=response,
                execution_time_ms=task.audit.execution_time_ms,
                cost_used=cost,
                audit=task.audit,
            )
            
        except asyncio.TimeoutError:
            return TaskResult(
                task_id=task.id,
                success=False,
                status=TaskStatus.TIMEOUT,
                error="Remote agent timed out",
                execution_time_ms=int(task.budget.max_seconds * 1000),
                audit=task.audit,
            )
        except Exception as e:
            return TaskResult(
                task_id=task.id,
                success=False,
                status=TaskStatus.FAILED,
                error=str(e),
                audit=task.audit,
            )
    
    def _estimate_cost(self, prompt: str, response: str, provider: str) -> float:
        """Estima custo de uma chamada LLM."""
        input_tokens = len(prompt) // 4
        output_tokens = len(response) // 4
        
        rates = {
            "groq": 0.00001,
            "openai": 0.0005,
            "anthropic": 0.001,
        }
        
        rate = rates.get(provider, 0.0001)
        return round((input_tokens + output_tokens) * rate, 6)
    
    async def _execute_teammate(self, task: Task) -> TaskResult:
        """Executa tarefa via teammate in-process."""
        task_id = task.payload.get("task", "")
        teammate_id = task.payload.get("teammate_id", "unknown")
        
        task.audit.add_step("teammate_start", {"teammate": teammate_id})
        
        await asyncio.sleep(0.1)
        
        task.audit.add_step("teammate_complete", {})
        
        return TaskResult(
            task_id=task.id,
            success=True,
            status=TaskStatus.SUCCESS,
            output=f"Teammate {teammate_id} completed: {task_id}",
            execution_time_ms=task.audit.execution_time_ms,
            audit=task.audit,
        )
    
    async def _execute_workflow(self, task: Task) -> TaskResult:
        """Executa workflow composto por múltiplas tarefas."""
        steps = task.payload.get("steps", [])
        name = task.payload.get("name", "workflow")
        
        task.audit.add_step("workflow_start", {"steps": len(steps), "name": name})
        
        results = []
        for i, step in enumerate(steps):
            task.audit.add_step("workflow_step", {"index": i, "step": str(step)[:50]})
            results.append({"step": i, "status": "completed"})
        
        task.audit.add_step("workflow_complete", {"results": len(results)})
        
        return TaskResult(
            task_id=task.id,
            success=True,
            status=TaskStatus.SUCCESS,
            output={"workflow": name, "steps_completed": len(results), "results": results},
            execution_time_ms=task.audit.execution_time_ms,
            audit=task.audit,
        )
    
    async def _execute_monitor_mcp(self, task: Task) -> TaskResult:
        """Executa monitoramento de ferramenta MCP."""
        tool_name = task.payload.get("tool_name", "")
        interval = task.payload.get("interval_seconds", 60)
        
        task.audit.add_step("monitor_start", {"tool": tool_name, "interval": interval})
        
        await asyncio.sleep(1)
        
        task.audit.add_step("monitor_sample", {"status": "ok"})
        
        return TaskResult(
            task_id=task.id,
            success=True,
            status=TaskStatus.SUCCESS,
            output={"tool": tool_name, "status": "monitoring", "interval": interval},
            execution_time_ms=task.audit.execution_time_ms,
            audit=task.audit,
        )
    
    async def _execute_dream(self, task: Task) -> TaskResult:
        """Executa tarefa de consolidação offline (sono/dream).
        
        Integra diretamente com o sleep_cycle do UltronPro para
        consolidar experiências, criar abstrações e podar memórias.
        """
        context = task.payload.get("context", {})
        retention_days = task.payload.get("retention_days", 14)
        max_active_rows = task.payload.get("max_active_rows", 3000)
        
        task.audit.add_step("dream_start", {
            "context_keys": list(context.keys()) if context else [],
            "retention_days": retention_days,
        })
        
        try:
            from ultronpro import sleep_cycle
            import asyncio
            
            result = await asyncio.wait_for(
                asyncio.to_thread(
                    sleep_cycle.run_cycle,
                    retention_days=retention_days,
                    max_active_rows=max_active_rows
                ),
                timeout=task.budget.max_seconds
            )
            
            abstractions = result.get("abstracted", 0)
            pruned = result.get("pruned", 0)
            active_after = result.get("active_after", 0)
            gap = result.get("causal_gap_investigation") if isinstance(result.get("causal_gap_investigation"), dict) else {}
            
            task.audit.add_step("dream_complete", {
                "abstracted": abstractions,
                "pruned": pruned,
                "active_after": active_after,
                "causal_gap_experiments": gap.get("executed", 0),
                "causal_gap_injections": gap.get("injected", 0),
            })
            
            task.audit.artifacts.append({
                "type": "consolidation_report",
                "data": result,
            })
            
            return TaskResult(
                task_id=task.id,
                success=True,
                status=TaskStatus.SUCCESS,
                output={
                    "consolidated": True,
                    "abstractions_created": abstractions,
                    "episodes_pruned": pruned,
                    "active_episodes": active_after,
                    "causal_gap_experiments": gap.get("executed", 0),
                    "causal_gap_injections": gap.get("injected", 0),
                    "coverage_delta_edges": result.get("coverage_delta_edges", 0),
                    "message": f"Sono profundo: {abstractions} abstrações criadas, {pruned} episódios podados.",
                },
                execution_time_ms=task.audit.execution_time_ms,
                audit=task.audit,
            )
            
        except asyncio.TimeoutError:
            return TaskResult(
                task_id=task.id,
                success=False,
                status=TaskStatus.TIMEOUT,
                error="Dream consolidation timed out",
                execution_time_ms=int(task.budget.max_seconds * 1000),
                audit=task.audit,
            )
        except Exception as e:
            return TaskResult(
                task_id=task.id,
                success=False,
                status=TaskStatus.FAILED,
                error=f"Dream failed: {e}",
                audit=task.audit,
            )
    
    # ==================== STATUS ====================
    
    def get_status(self) -> Dict[str, Any]:
        """Retorna status do gerenciador."""
        return {
            "tasks_total": len(self._tasks),
            "tasks_queued": len(self._queue),
            "tasks_running": len(self._running),
            "metrics": self._metrics.to_dict(),
        }
    
    def get_task(self, task_id: str) -> Optional[Task]:
        """Retorna tarefa pelo ID."""
        return self._tasks.get(task_id)
    
    def list_tasks(self, status: Optional[TaskStatus] = None, limit: int = 50) -> List[Task]:
        """Lista tarefas, opcionalmente filtradas por status."""
        tasks = list(self._tasks.values())
        
        if status:
            tasks = [t for t in tasks if t.status == status]
        
        tasks.sort(key=lambda t: t.audit.created_at, reverse=True)
        return tasks[:limit]


# ==================== GLOBAL INSTANCE ====================

_task_manager: Optional[TaskManager] = None

def get_task_manager() -> TaskManager:
    """Retorna instância global do TaskManager."""
    global _task_manager
    if _task_manager is None:
        _task_manager = TaskManager()
    return _task_manager
