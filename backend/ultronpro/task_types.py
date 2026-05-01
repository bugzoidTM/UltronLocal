"""
UltronPro Task System - Tipos e Interfaces Unificadas

Define os tipos de tarefas para a arquitetura de times de agentes:
- local_bash: Execução de comandos shell local
- local_agent: Agente LLM rodando localmente
- remote_agent: Agente LLM em provedor cloud
- in_process_teammate: teammate executando no mesmo processo
- local_workflow: Workflow composto por múltiplas tarefas
- monitor_mcp: Monitoramento de ferramentas MCP
- dream: Tarefa de consolidação/consciência offline

Características:
- Budget (tempo, tokens, memória)
- Ownership (proprietário da tarefa)
- Isolation (sandbox para execução)
- Audit (rastro completo de execução)
"""

import os
import json
import time
import uuid
import hashlib
import asyncio
import logging
from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Callable, Union
from pathlib import Path

logger = logging.getLogger("uvicorn")

# ==================== ENUMS ====================

class TaskType(str, Enum):
    """Tipos de tarefa suportados pelo sistema."""
    LOCAL_BASH = "local_bash"
    LOCAL_AGENT = "local_agent"
    REMOTE_AGENT = "remote_agent"
    IN_PROCESS_TEAMMATE = "in_process_teammate"
    LOCAL_WORKFLOW = "local_workflow"
    MONITOR_MCP = "monitor_mcp"
    DREAM = "dream"


class TaskStatus(str, Enum):
    """Status terminais e intermediários de tarefas."""
    # Terminais
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    # Intermediários
    PREFLIGHT = "preflight"
    RETRYING = "retrying"
    BLOCKED = "blocked"
    PAUSED = "paused"
    # Terminais de erro
    BUDGET_EXCEEDED = "budget_exceeded"
    ISOLATION_BREACH = "isolation_breach"
    PERMISSION_DENIED = "permission_denied"


class TaskPriority(int, Enum):
    """Prioridade de tarefas."""
    CRITICAL = 10
    HIGH = 7
    NORMAL = 5
    LOW = 3
    BACKGROUND = 1


class IsolationLevel(str, Enum):
    """Nível de isolamento para execução."""
    NONE = "none"
    SOFT = "soft"
    HARD = "hard"
    SANDBOX = "sandbox"


# ==================== BUDGET ====================

@dataclass
class TaskBudget:
    """Orçamento de recursos para uma tarefa."""
    max_seconds: float = 60.0
    max_tokens: int = 4096
    max_memory_mb: int = 512
    max_cost: float = 0.10
    max_retries: int = 3
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "max_seconds": self.max_seconds,
            "max_tokens": self.max_tokens,
            "max_memory_mb": self.max_memory_mb,
            "max_cost": self.max_cost,
            "max_retries": self.max_retries,
        }
    
    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "TaskBudget":
        return cls(
            max_seconds=float(d.get("max_seconds", 60.0)),
            max_tokens=int(d.get("max_tokens", 4096)),
            max_memory_mb=int(d.get("max_memory_mb", 512)),
            max_cost=float(d.get("max_cost", 0.10)),
            max_retries=int(d.get("max_retries", 3)),
        )


# ==================== OWNERSHIP ====================

@dataclass
class TaskOwner:
    """Proprietário de uma tarefa (quem criou/reclamou)."""
    owner_id: str
    owner_type: str = "system"  # system, user, agent, workflow
    owner_name: str = ""
    team_id: Optional[str] = None
    parent_task_id: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "owner_id": self.owner_id,
            "owner_type": self.owner_type,
            "owner_name": self.owner_name,
            "team_id": self.team_id,
            "parent_task_id": self.parent_task_id,
            "created_at": self.created_at,
        }


# ==================== ISOLATION ====================

@dataclass
class TaskIsolation:
    """Configuração de isolamento para execução."""
    level: IsolationLevel = IsolationLevel.SOFT
    allowed_paths: List[str] = field(default_factory=list)
    denied_paths: List[str] = field(default_factory=list)
    allowed_tools: List[str] = field(default_factory=list)
    denied_tools: List[str] = field(default_factory=list)
    network_access: bool = True
    env_vars: Dict[str, str] = field(default_factory=dict)
    working_dir: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "level": self.level.value,
            "allowed_paths": self.allowed_paths,
            "denied_paths": self.denied_paths,
            "allowed_tools": self.allowed_tools,
            "denied_tools": self.denied_tools,
            "network_access": self.network_access,
            "env_vars": self.env_vars,
            "working_dir": self.working_dir,
        }


# ==================== AUDIT ====================

@dataclass
class TaskAudit:
    """Rastro de auditoria completo da tarefa."""
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    ended_at: Optional[float] = None
    preflight_at: Optional[float] = None
    preflight_result: Optional[Dict[str, Any]] = None
    hooks_executed: List[str] = field(default_factory=list)
    retries: int = 0
    last_error: Optional[str] = None
    warnings: List[str] = field(default_factory=list)
    artifacts: List[Dict[str, Any]] = field(default_factory=list)
    steps: List[Dict[str, Any]] = field(default_factory=list)
    
    @property
    def execution_time_ms(self) -> int:
        if self.started_at and self.ended_at:
            return int((self.ended_at - self.started_at) * 1000)
        return 0
    
    def add_step(self, step_type: str, data: Dict[str, Any]):
        """Adiciona um passo à execução."""
        self.steps.append({
            "ts": time.time(),
            "type": step_type,
            "data": data,
        })
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "created_at": self.created_at,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "preflight_at": self.preflight_at,
            "preflight_result": self.preflight_result,
            "hooks_executed": self.hooks_executed,
            "retries": self.retries,
            "last_error": self.last_error,
            "warnings": self.warnings,
            "artifacts": self.artifacts,
            "steps": self.steps,
            "execution_time_ms": self.execution_time_ms,
        }


# ==================== TASK ====================

@dataclass
class Task:
    """
    Tarefa unificada do UltronPro.
    
    Attributes:
        id: Identificador único (UUID)
        type: Tipo de execução
        description: Descrição legível da tarefa
        payload: Dados de entrada específicos do tipo
        status: Status atual
        priority: Prioridade (1-10)
        budget: Orçamento de recursos
        owner: Proprietário da tarefa
        isolation: Configuração de isolamento
        audit: Rastro de auditoria
        tags: Tags para categorização
        metadata: Dados adicionais
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    type: TaskType = TaskType.LOCAL_AGENT
    description: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)
    status: TaskStatus = TaskStatus.PENDING
    priority: TaskPriority = TaskPriority.NORMAL
    budget: TaskBudget = field(default_factory=TaskBudget)
    owner: TaskOwner = field(default_factory=lambda: TaskOwner(owner_id="system"))
    isolation: TaskIsolation = field(default_factory=TaskIsolation)
    audit: TaskAudit = field(default_factory=TaskAudit)
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    result: Optional[Any] = None
    
    # Hash único para deduplicação
    @property
    def fingerprint(self) -> str:
        fp_data = f"{self.type.value}:{self.description}:{json.dumps(self.payload, sort_keys=True)}"
        return hashlib.md5(fp_data.encode()).hexdigest()[:16]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type.value,
            "description": self.description,
            "payload": self.payload,
            "status": self.status.value,
            "priority": self.priority.value,
            "budget": self.budget.to_dict(),
            "owner": self.owner.to_dict(),
            "isolation": self.isolation.to_dict(),
            "audit": self.audit.to_dict(),
            "tags": self.tags,
            "metadata": self.metadata,
            "result": self.result,
            "fingerprint": self.fingerprint,
        }
    
    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Task":
        return cls(
            id=str(d.get("id", "")),
            type=TaskType(d.get("type", "local_agent")),
            description=str(d.get("description", "")),
            payload=d.get("payload", {}),
            status=TaskStatus(d.get("status", "pending")),
            priority=TaskPriority(d.get("priority", 5)),
            budget=TaskBudget.from_dict(d.get("budget", {})),
            owner=TaskOwner(**d.get("owner", {})) if isinstance(d.get("owner"), dict) else TaskOwner(owner_id="system"),
            isolation=TaskIsolation(**d.get("isolation", {})) if isinstance(d.get("isolation"), dict) else TaskIsolation(),
            audit=TaskAudit(**d.get("audit", {})) if isinstance(d.get("audit"), dict) else TaskAudit(),
            tags=d.get("tags", []),
            metadata=d.get("metadata", {}),
            result=d.get("result"),
        )


# ==================== TASK RESULT ====================

@dataclass
class TaskResult:
    """Resultado padronizado de execução de tarefa."""
    task_id: str
    success: bool
    status: TaskStatus
    output: Optional[Any] = None
    error: Optional[str] = None
    execution_time_ms: int = 0
    tokens_used: int = 0
    cost_used: float = 0.0
    audit: Optional[TaskAudit] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "success": self.success,
            "status": self.status.value,
            "output": self.output,
            "error": self.error,
            "execution_time_ms": self.execution_time_ms,
            "tokens_used": self.tokens_used,
            "cost_used": self.cost_used,
            "audit": self.audit.to_dict() if self.audit else None,
        }


# ==================== TASK HOOKS ====================

@dataclass
class TaskHooks:
    """Hooks para customização do ciclo de vida da tarefa."""
    on_create: Optional[Callable[["Task"], None]] = None
    on_start: Optional[Callable[["Task"], None]] = None
    on_progress: Optional[Callable[["Task", float], None]] = None
    on_success: Optional[Callable[["Task", Any], None]] = None
    on_failure: Optional[Callable[["Task", str], None]] = None
    on_timeout: Optional[Callable[["Task"], None]] = None
    on_cancel: Optional[Callable[["Task"], None]] = None
    on_cleanup: Optional[Callable[["Task"], None]] = None


# ==================== TASK TEMPLATES ====================

class TaskTemplates:
    """Templates pré-configurados para tipos comuns de tarefas."""
    
    @staticmethod
    def bash(command: str, cwd: Optional[str] = None, timeout: float = 30.0) -> Task:
        """Template para execução de comando bash."""
        return Task(
            type=TaskType.LOCAL_BASH,
            description=f"Executar: {command[:50]}",
            payload={
                "command": command,
                "working_dir": cwd or os.getcwd(),
            },
            budget=TaskBudget(max_seconds=timeout, max_retries=1),
            isolation=TaskIsolation(level=IsolationLevel.HARD),
        )
    
    @staticmethod
    def local_agent(prompt: str, model: str = "llama3.2:1b", budget: float = 60.0) -> Task:
        """Template para agente LLM local."""
        return Task(
            type=TaskType.LOCAL_AGENT,
            description=f"Agente local: {prompt[:50]}",
            payload={
                "prompt": prompt,
                "model": model,
            },
            budget=TaskBudget(max_seconds=budget),
            isolation=TaskIsolation(level=IsolationLevel.SOFT),
        )
    
    @staticmethod
    def remote_agent(prompt: str, provider: str = "groq", model: str = "llama-3.3-70b") -> Task:
        """Template para agente LLM cloud."""
        return Task(
            type=TaskType.REMOTE_AGENT,
            description=f"Agente cloud ({provider}): {prompt[:50]}",
            payload={
                "prompt": prompt,
                "provider": provider,
                "model": model,
            },
            budget=TaskBudget(max_seconds=45.0, max_cost=0.05),
            isolation=TaskIsolation(level=IsolationLevel.SOFT),
        )
    
    @staticmethod
    def teammate(task: str, teammate_id: str, team: str) -> Task:
        """Template para teammate in-process."""
        return Task(
            type=TaskType.IN_PROCESS_TEAMMATE,
            description=f"Teammate {teammate_id}: {task[:50]}",
            payload={
                "task": task,
                "teammate_id": teammate_id,
                "team": team,
            },
            owner=TaskOwner(owner_id=teammate_id, owner_type="agent", team_id=team),
            budget=TaskBudget(max_seconds=30.0),
        )
    
    @staticmethod
    def workflow(steps: List[Dict[str, Any]], name: str = "workflow") -> Task:
        """Template para workflow composto."""
        return Task(
            type=TaskType.LOCAL_WORKFLOW,
            description=f"Workflow: {name}",
            payload={"steps": steps, "name": name},
            budget=TaskBudget(max_seconds=300.0, max_retries=2),
        )
    
    @staticmethod
    def monitor_mcp(tool_name: str, interval: float = 60.0) -> Task:
        """Template para monitoramento MCP."""
        return Task(
            type=TaskType.MONITOR_MCP,
            description=f"Monitorar {tool_name}",
            payload={
                "tool_name": tool_name,
                "interval_seconds": interval,
            },
            budget=TaskBudget(max_seconds=3600.0, max_retries=1),
            tags=["monitoring", tool_name],
        )
    
    @staticmethod
    def dream(context: Dict[str, Any] = None) -> Task:
        """Template para tarefa de consolidação/dream."""
        return Task(
            type=TaskType.DREAM,
            description="Consolidação offline (sono)",
            payload={
                "context": context or {},
                "retention_days": 14,
                "max_active_rows": 3000,
            },
            budget=TaskBudget(max_seconds=120.0, max_retries=1),
            owner=TaskOwner(owner_id="system", owner_type="system", owner_name="SleepCycle"),
            isolation=TaskIsolation(level=IsolationLevel.NONE),
            tags=["consolidation", "sleep", "dream"],
        )
