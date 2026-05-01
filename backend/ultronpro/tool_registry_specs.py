"""
UltronPro Tool Registry - Specs e Tipos

Define as especificações declarativas para todas as tools do sistema:
- Metadata: nome, descrição, categoria, tags
- Custo: tempo, tokens, dinheiro
- Risco: side effects, segurança
- Timeout: limites de execução
- Autorização: políticas de uso
"""

import os
import time
from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Callable, Union
from dataclasses import dataclass, field


class ToolCategory(str, Enum):
    """Categorias de ferramentas."""
    FILE = "file"
    BASH = "bash"
    SEARCH = "search"
    CODE = "code"
    LLM = "llm"
    WEB = "web"
    MEMORY = "memory"
    PLANNING = "planning"
    TASK = "task"
    TEAM = "team"
    SYSTEM = "system"


class RiskLevel(str, Enum):
    """Níveis de risco de uma ferramenta."""
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class SideEffect(str, Enum):
    """Tipos de side effects."""
    NONE = "none"
    READ = "read"
    WRITE = "write"
    DELETE = "delete"
    NETWORK = "network"
    FILESYSTEM = "filesystem"
    EXECUTION = "execution"
    STATE = "state"


class AuthorizationPolicy(str, Enum):
    """Políticas de autorização."""
    PUBLIC = "public"
    USER_CONFIRM = "user_confirm"
    ADMIN_ONLY = "admin_only"
    SYSTEM_ONLY = "system_only"
    BLOCKED = "blocked"


@dataclass
class ToolCost:
    """Custo de execução de uma ferramenta."""
    max_seconds: float = 30.0
    max_tokens: int = 1000
    max_memory_mb: int = 256
    estimated_cost: float = 0.0
    rate_limit_per_min: int = 60
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "max_seconds": self.max_seconds,
            "max_tokens": self.max_tokens,
            "max_memory_mb": self.max_memory_mb,
            "estimated_cost": self.estimated_cost,
            "rate_limit_per_min": self.rate_limit_per_min,
        }


@dataclass
class ToolRisk:
    """Perfil de risco de uma ferramenta."""
    level: RiskLevel = RiskLevel.LOW
    side_effects: List[SideEffect] = field(default_factory=list)
    can_revert: bool = True
    requires_confirmation: bool = False
    data_privacy: str = "internal"  # internal, sensitive, confidential
    rate_limit_reason: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "level": self.level.value,
            "side_effects": [s.value for s in self.side_effects],
            "can_revert": self.can_revert,
            "requires_confirmation": self.requires_confirmation,
            "data_privacy": self.data_privacy,
            "rate_limit_reason": self.rate_limit_reason,
        }


@dataclass
class ToolSpec:
    """
    Especificação declarativa de uma ferramenta.
    
    Define metadata, custos, riscos e políticas de uma tool.
    """
    name: str
    description: str
    category: ToolCategory
    function: Optional[Callable] = None
    
    version: str = "1.0.0"
    author: str = "system"
    
    cost: ToolCost = field(default_factory=ToolCost)
    risk: ToolRisk = field(default_factory=ToolRisk)
    authorization: AuthorizationPolicy = AuthorizationPolicy.PUBLIC
    
    tags: List[str] = field(default_factory=list)
    examples: List[str] = field(default_factory=list)
    
    input_schema: Dict[str, Any] = field(default_factory=dict)
    output_schema: Dict[str, Any] = field(default_factory=dict)
    
    requires_context: List[str] = field(default_factory=list)
    conflicts_with: List[str] = field(default_factory=list)
    
    deprecated: bool = False
    deprecation_message: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "category": self.category.value,
            "version": self.version,
            "author": self.author,
            "cost": self.cost.to_dict(),
            "risk": self.risk.to_dict(),
            "authorization": self.authorization.value,
            "tags": self.tags,
            "examples": self.examples,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "requires_context": self.requires_context,
            "conflicts_with": self.conflicts_with,
            "deprecated": self.deprecated,
            "deprecation_message": self.deprecation_message,
        }
    
    @property
    def has_side_effects(self) -> bool:
        return any(se != SideEffect.NONE for se in self.risk.side_effects)
    
    @property
    def is_safe(self) -> bool:
        return self.risk.level in (RiskLevel.NONE, RiskLevel.LOW) and not self.has_side_effects
    
    @property
    def requires_approval(self) -> bool:
        return (
            self.risk.requires_confirmation or
            self.risk.level in (RiskLevel.HIGH, RiskLevel.CRITICAL) or
            SideEffect.DELETE in self.risk.side_effects or
            SideEffect.EXECUTION in self.risk.side_effects
        )


@dataclass
class ToolExecution:
    """Registro de uma execução de ferramenta."""
    tool_name: str
    started_at: float = field(default_factory=time.time)
    ended_at: Optional[float] = None
    success: bool = False
    error: Optional[str] = None
    input_args: Dict[str, Any] = field(default_factory=dict)
    output: Any = None
    execution_time_ms: int = 0
    tokens_used: int = 0
    cost_used: float = 0.0
    approved_by: Optional[str] = None
    denied_by: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "success": self.success,
            "error": self.error,
            "input_args": self.input_args,
            "execution_time_ms": self.execution_time_ms,
            "tokens_used": self.tokens_used,
            "cost_used": round(self.cost_used, 6),
            "approved_by": self.approved_by,
            "denied_by": self.denied_by,
        }


@dataclass
class ToolStats:
    """Estatísticas de uso de uma ferramenta."""
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    total_time_ms: int = 0
    total_tokens: int = 0
    total_cost: float = 0.0
    last_used: Optional[float] = None
    last_error: Optional[str] = None
    
    @property
    def success_rate(self) -> float:
        if self.total_calls == 0:
            return 0.0
        return self.successful_calls / self.total_calls
    
    @property
    def avg_time_ms(self) -> float:
        if self.total_calls == 0:
            return 0.0
        return self.total_time_ms / self.total_calls
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_calls": self.total_calls,
            "successful_calls": self.successful_calls,
            "failed_calls": self.failed_calls,
            "success_rate": round(self.success_rate, 4),
            "total_time_ms": self.total_time_ms,
            "avg_time_ms": round(self.avg_time_ms, 2),
            "total_tokens": self.total_tokens,
            "total_cost": round(self.total_cost, 6),
            "last_used": self.last_used,
            "last_error": self.last_error,
        }
