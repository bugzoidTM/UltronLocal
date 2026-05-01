"""
UltronPro Tool Registry - Registry Central

Registry declarativo de ferramentas com:
- Metadados: custo, risco, timeout, side effects
- Autorização: políticas de uso
- Execução: wrapped com logging e budget
- Busca: por nome, categoria, tags
"""

import os
import json
import time
import asyncio
import logging
from typing import Dict, List, Optional, Any, Callable, Union
from pathlib import Path
from dataclasses import dataclass, field, asdict
from datetime import datetime

from ultronpro.tool_registry_specs import (
    ToolSpec, ToolCategory, RiskLevel, SideEffect, 
    AuthorizationPolicy, ToolCost, ToolRisk, ToolExecution, ToolStats
)

logger = logging.getLogger("uvicorn")

AUDIT_PATH = Path(__file__).resolve().parent.parent.parent / 'data' / 'tool_audit.jsonl'


@dataclass
class ToolAuthorization:
    """Resultado de autorização para uma tool."""
    allowed: bool
    reason: str
    requires_confirmation: bool = False
    confirmation_token: Optional[str] = None


class ToolRegistry:
    """
    Registry central de ferramentas do UltronPro.
    
    Funcionalidades:
    1. Registro de ferramentas com specs declarativas
    2. Busca por nome, categoria, tags
    3. Autorização com políticas
    4. Execução com logging e métricas
    5. Rate limiting
    """
    
    def __init__(self):
        self._tools: Dict[str, ToolSpec] = {}
        self._stats: Dict[str, ToolStats] = {}
        self._rate_limits: Dict[str, List[float]] = {}
        self._pending_authorizations: Dict[str, Dict[str, Any]] = {}
        self._hooks: Dict[str, Callable] = {}
        
        self._audit_enabled = True
        self._audit_path = AUDIT_PATH
        self._audit_path.parent.mkdir(parents=True, exist_ok=True)
        
        self._register_default_tools()
    
    def _register_default_tools(self):
        """Registra as tools padrão do sistema."""
        from ultronpro import env_tools, web_browser, knowledge_bridge, store
        from ultronpro import task_manager, skill_loader, skill_executor
        from ultronpro import sleep_cycle, causal_graph, semantic_cache
        
        tools = [
            self._create_file_tools(),
            self._create_search_tools(),
            self._create_web_tools(),
            self._create_memory_tools(),
            self._create_task_tools(),
            self._create_system_tools(),
        ]
        
        for tool_list in tools:
            for tool in tool_list:
                self.register(tool)
    
    def _create_file_tools(self) -> List[ToolSpec]:
        """Cria specs para tools de arquivo."""
        return [
            ToolSpec(
                name="file.read",
                description="Lê conteúdo de um arquivo",
                category=ToolCategory.FILE,
                tags=["file", "read", "io"],
                cost=ToolCost(max_seconds=5.0, max_tokens=100),
                risk=ToolRisk(
                    level=RiskLevel.LOW,
                    side_effects=[SideEffect.READ],
                    can_revert=True,
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Caminho do arquivo"}
                    },
                    "required": ["path"]
                },
            ),
            ToolSpec(
                name="file.write",
                description="Escreve conteúdo em um arquivo",
                category=ToolCategory.FILE,
                tags=["file", "write", "io"],
                cost=ToolCost(max_seconds=10.0, max_tokens=200),
                risk=ToolRisk(
                    level=RiskLevel.MEDIUM,
                    side_effects=[SideEffect.WRITE, SideEffect.FILESYSTEM],
                    can_revert=True,
                    requires_confirmation=True,
                ),
                authorization=AuthorizationPolicy.USER_CONFIRM,
                input_schema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"}
                    },
                    "required": ["path", "content"]
                },
            ),
            ToolSpec(
                name="file.glob",
                description="Busca arquivos por padrão glob",
                category=ToolCategory.FILE,
                tags=["file", "glob", "search", "pattern"],
                cost=ToolCost(max_seconds=15.0, max_tokens=100),
                risk=ToolRisk(level=RiskLevel.LOW, side_effects=[SideEffect.READ]),
            ),
            ToolSpec(
                name="file.grep",
                description="Busca padrão em arquivos",
                category=ToolCategory.FILE,
                tags=["file", "grep", "search", "regex"],
                cost=ToolCost(max_seconds=20.0, max_tokens=100),
                risk=ToolRisk(level=RiskLevel.LOW, side_effects=[SideEffect.READ]),
            ),
            ToolSpec(
                name="bash.run",
                description="Executa comando bash/shell",
                category=ToolCategory.BASH,
                tags=["bash", "shell", "exec", "command"],
                cost=ToolCost(max_seconds=60.0, max_tokens=50),
                risk=ToolRisk(
                    level=RiskLevel.HIGH,
                    side_effects=[SideEffect.EXECUTION, SideEffect.FILESYSTEM],
                    can_revert=False,
                    requires_confirmation=True,
                ),
                authorization=AuthorizationPolicy.USER_CONFIRM,
            ),
            ToolSpec(
                name="bash.sandbox",
                description="Executa código Python em sandbox isolado",
                category=ToolCategory.BASH,
                tags=["sandbox", "python", "exec", "isolated"],
                cost=ToolCost(max_seconds=30.0, max_tokens=100),
                risk=ToolRisk(
                    level=RiskLevel.MEDIUM,
                    side_effects=[SideEffect.EXECUTION],
                    can_revert=True,
                ),
            ),
        ]
    
    def _create_search_tools(self) -> List[ToolSpec]:
        """Cria specs para tools de busca."""
        return [
            ToolSpec(
                name="search.lsp",
                description="Busca símbolos em código usando LSP",
                category=ToolCategory.CODE,
                tags=["lsp", "code", "symbols", "search"],
                cost=ToolCost(max_seconds=10.0, max_tokens=200),
                risk=ToolRisk(level=RiskLevel.LOW, side_effects=[SideEffect.READ]),
            ),
            ToolSpec(
                name="search.grep",
                description="Busca padrão regex em arquivos",
                category=ToolCategory.SEARCH,
                tags=["grep", "regex", "search", "code"],
                cost=ToolCost(max_seconds=15.0, max_tokens=100),
                risk=ToolRisk(level=RiskLevel.LOW, side_effects=[SideEffect.READ]),
            ),
            ToolSpec(
                name="search.ripgrep",
                description="Busca avançada com ripgrep",
                category=ToolCategory.SEARCH,
                tags=["ripgrep", "rg", "search", "fast"],
                cost=ToolCost(max_seconds=10.0, max_tokens=100),
                risk=ToolRisk(level=RiskLevel.LOW, side_effects=[SideEffect.READ]),
            ),
        ]
    
    def _create_web_tools(self) -> List[ToolSpec]:
        """Cria specs para tools web."""
        return [
            ToolSpec(
                name="web.search",
                description="Pesquisa na web (DuckDuckGo)",
                category=ToolCategory.WEB,
                tags=["web", "search", "internet", "duckduckgo"],
                cost=ToolCost(max_seconds=15.0, estimated_cost=0.001),
                risk=ToolRisk(
                    level=RiskLevel.LOW,
                    side_effects=[SideEffect.NETWORK],
                ),
            ),
            ToolSpec(
                name="web.fetch",
                description="Busca conteúdo de uma URL",
                category=ToolCategory.WEB,
                tags=["web", "fetch", "http", "url"],
                cost=ToolCost(max_seconds=20.0, estimated_cost=0.002),
                risk=ToolRisk(
                    level=RiskLevel.LOW,
                    side_effects=[SideEffect.NETWORK],
                ),
            ),
            ToolSpec(
                name="web.mcp",
                description="Monitora ferramenta MCP",
                category=ToolCategory.WEB,
                tags=["mcp", "monitor", "tool"],
                cost=ToolCost(max_seconds=5.0),
                risk=ToolRisk(level=RiskLevel.LOW, side_effects=[SideEffect.READ]),
            ),
        ]
    
    def _create_memory_tools(self) -> List[ToolSpec]:
        """Cria specs para tools de memória."""
        return [
            ToolSpec(
                name="memory.rag",
                description="Busca em base de conhecimento RAG",
                category=ToolCategory.MEMORY,
                tags=["rag", "knowledge", "vector", "search"],
                cost=ToolCost(max_seconds=10.0, max_tokens=500),
                risk=ToolRisk(level=RiskLevel.LOW, side_effects=[SideEffect.READ]),
            ),
            ToolSpec(
                name="memory.graph",
                description="Consulta grafo de conhecimento",
                category=ToolCategory.MEMORY,
                tags=["graph", "knowledge", "triples", "causal"],
                cost=ToolCost(max_seconds=5.0, max_tokens=200),
                risk=ToolRisk(level=RiskLevel.LOW, side_effects=[SideEffect.READ]),
            ),
            ToolSpec(
                name="memory.episodic",
                description="Busca em memória episódica",
                category=ToolCategory.MEMORY,
                tags=["episodic", "memory", "experiences"],
                cost=ToolCost(max_seconds=5.0, max_tokens=100),
                risk=ToolRisk(level=RiskLevel.LOW, side_effects=[SideEffect.READ]),
            ),
            ToolSpec(
                name="memory.cache",
                description="Busca em cache semântico",
                category=ToolCategory.MEMORY,
                tags=["cache", "semantic", "learned"],
                cost=ToolCost(max_seconds=3.0, max_tokens=50),
                risk=ToolRisk(level=RiskLevel.NONE, side_effects=[SideEffect.NONE]),
            ),
        ]
    
    def _create_task_tools(self) -> List[ToolSpec]:
        """Cria specs para tools de tarefa."""
        return [
            ToolSpec(
                name="task.submit",
                description="Submete uma tarefa ao TaskManager",
                category=ToolCategory.TASK,
                tags=["task", "submit", "queue", "job"],
                cost=ToolCost(max_seconds=5.0, max_tokens=100),
                risk=ToolRisk(level=RiskLevel.LOW, side_effects=[SideEffect.STATE]),
            ),
            ToolSpec(
                name="task.execute",
                description="Executa uma tarefa específica",
                category=ToolCategory.TASK,
                tags=["task", "execute", "run", "job"],
                cost=ToolCost(max_seconds=120.0, max_tokens=500),
                risk=ToolRisk(level=RiskLevel.MEDIUM, side_effects=[SideEffect.EXECUTION]),
            ),
            ToolSpec(
                name="task.status",
                description="Verifica status de uma tarefa",
                category=ToolCategory.TASK,
                tags=["task", "status", "check"],
                cost=ToolCost(max_seconds=2.0, max_tokens=50),
                risk=ToolRisk(level=RiskLevel.NONE, side_effects=[SideEffect.NONE]),
            ),
            ToolSpec(
                name="task.dream",
                description="Executa consolidação offline (sono)",
                category=ToolCategory.TASK,
                tags=["dream", "sleep", "consolidation", "offline"],
                cost=ToolCost(max_seconds=120.0, max_tokens=200),
                risk=ToolRisk(level=RiskLevel.LOW, side_effects=[SideEffect.STATE]),
            ),
        ]
    
    def _create_system_tools(self) -> List[ToolSpec]:
        """Cria specs para tools de sistema."""
        return [
            ToolSpec(
                name="system.planning",
                description="Modo de planejamento de tarefas",
                category=ToolCategory.PLANNING,
                tags=["planning", "plan", "strategy"],
                cost=ToolCost(max_seconds=30.0, max_tokens=1000),
                risk=ToolRisk(level=RiskLevel.LOW, side_effects=[SideEffect.STATE]),
            ),
            ToolSpec(
                name="system.cron",
                description="Agenda tarefa recorrente",
                category=ToolCategory.SYSTEM,
                tags=["cron", "schedule", "recurring"],
                cost=ToolCost(max_seconds=5.0, max_tokens=100),
                risk=ToolRisk(level=RiskLevel.LOW, side_effects=[SideEffect.STATE]),
            ),
            ToolSpec(
                name="system.team",
                description="Coordena time de agentes",
                category=ToolCategory.TEAM,
                tags=["team", "agents", "coordination"],
                cost=ToolCost(max_seconds=30.0, max_tokens=500),
                risk=ToolRisk(level=RiskLevel.MEDIUM, side_effects=[SideEffect.STATE]),
            ),
            ToolSpec(
                name="system.todo",
                description="Gerencia lista de TODOs",
                category=ToolCategory.SYSTEM,
                tags=["todo", "task", "checklist"],
                cost=ToolCost(max_seconds=3.0, max_tokens=50),
                risk=ToolRisk(level=RiskLevel.LOW, side_effects=[SideEffect.STATE]),
            ),
            ToolSpec(
                name="system.worktree",
                description="Gerencia worktree git",
                category=ToolCategory.SYSTEM,
                tags=["git", "worktree", "branch"],
                cost=ToolCost(max_seconds=10.0, max_tokens=100),
                risk=ToolRisk(
                    level=RiskLevel.MEDIUM,
                    side_effects=[SideEffect.EXECUTION],
                    can_revert=True,
                ),
            ),
        ]
    
    # ==================== REGISTRATION ====================
    
    def register(self, spec: ToolSpec) -> None:
        """Registra uma ferramenta no registry."""
        self._tools[spec.name] = spec
        if spec.name not in self._stats:
            self._stats[spec.name] = ToolStats()
        logger.info(f"Registered tool: {spec.name} ({spec.category.value})")
    
    def register_function(
        self,
        name: str,
        func: Callable,
        description: str,
        category: ToolCategory = ToolCategory.SYSTEM,
        cost: Optional[ToolCost] = None,
        risk: Optional[ToolRisk] = None,
        **kwargs
    ) -> None:
        """Registra uma função como ferramenta."""
        spec = ToolSpec(
            name=name,
            description=description,
            category=category,
            function=func,
            cost=cost or ToolCost(),
            risk=risk or ToolRisk(),
            **kwargs
        )
        self.register(spec)
    
    # ==================== LOOKUP ====================
    
    def get(self, name: str) -> Optional[ToolSpec]:
        """Retorna spec de uma ferramenta."""
        return self._tools.get(name)
    
    def find(
        self,
        query: Optional[str] = None,
        category: Optional[ToolCategory] = None,
        tags: Optional[List[str]] = None,
        risk_level: Optional[RiskLevel] = None,
        safe_only: bool = False,
    ) -> List[ToolSpec]:
        """Busca ferramentas por múltiplos critérios."""
        results = list(self._tools.values())
        
        if query:
            query_lower = query.lower()
            results = [
                t for t in results
                if query_lower in t.name.lower() or
                   query_lower in t.description.lower() or
                   any(query_lower in tag.lower() for tag in t.tags)
            ]
        
        if category:
            results = [t for t in results if t.category == category]
        
        if tags:
            results = [
                t for t in results
                if any(tag in t.tags for tag in tags)
            ]
        
        if risk_level:
            results = [t for t in results if t.risk.level == risk_level]
        
        if safe_only:
            results = [t for t in results if t.is_safe]
        
        return sorted(results, key=lambda t: t.name)
    
    def suggest(
        self,
        task: str,
        safe_only: bool = False,
    ) -> List[ToolSpec]:
        """Sugere ferramentas para uma tarefa."""
        results = self.find(safe_only=safe_only)
        
        scored = []
        task_lower = task.lower()
        for t in results:
            score = 0
            
            if t.name.lower() in task_lower:
                score += 20
            if any(tag in task_lower for tag in t.tags):
                score += 10
            if task_lower in t.description.lower():
                score += 5
            
            if safe_only and not t.is_safe:
                continue
            
            if score > 0:
                scored.append((score, t))
        
        scored.sort(key=lambda x: x[0], reverse=True)
        return [t for _, t in scored[:5]]
    
    # ==================== AUTHORIZATION ====================
    
    def check_authorization(
        self,
        tool_name: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> ToolAuthorization:
        """Verifica se uma ferramenta pode ser executada."""
        spec = self.get(tool_name)
        if not spec:
            return ToolAuthorization(
                allowed=False,
                reason=f"Tool '{tool_name}' not found"
            )
        
        if spec.deprecated:
            return ToolAuthorization(
                allowed=False,
                reason=f"Tool '{tool_name}' is deprecated: {spec.deprecation_message}"
            )
        
        if not self._check_rate_limit(tool_name):
            return ToolAuthorization(
                allowed=False,
                reason=f"Rate limit exceeded for '{tool_name}'"
            )
        
        policy = spec.authorization
        
        if policy == AuthorizationPolicy.BLOCKED:
            return ToolAuthorization(
                allowed=False,
                reason=f"Tool '{tool_name}' is blocked by policy"
            )
        
        if policy == AuthorizationPolicy.ADMIN_ONLY:
            if not context or not context.get("is_admin", False):
                return ToolAuthorization(
                    allowed=False,
                    reason=f"Tool '{tool_name}' requires admin privileges"
                )
        
        if spec.requires_approval:
            token = f"token_{int(time.time())}_{tool_name}"
            self._pending_authorizations[token] = {
                "tool_name": tool_name,
                "context": context,
                "created_at": time.time(),
            }
            return ToolAuthorization(
                allowed=False,
                reason=f"Tool '{tool_name}' requires user confirmation",
                requires_confirmation=True,
                confirmation_token=token,
            )
        
        return ToolAuthorization(
            allowed=True,
            reason="Tool authorized"
        )
    
    def confirm_authorization(self, token: str, approved_by: str) -> bool:
        """Confirma uma autorização pendente."""
        if token not in self._pending_authorizations:
            return False
        
        auth = self._pending_authorizations[token]
        auth["approved_by"] = approved_by
        auth["approved_at"] = time.time()
        del self._pending_authorizations[token]
        return True
    
    def _check_rate_limit(self, tool_name: str) -> bool:
        """Verifica rate limit de uma ferramenta."""
        spec = self.get(tool_name)
        if not spec:
            return True
        
        limit = spec.cost.rate_limit_per_min
        if limit <= 0:
            return True
        
        now = time.time()
        window = 60.0
        
        if tool_name not in self._rate_limits:
            self._rate_limits[tool_name] = []
        
        calls = self._rate_limits[tool_name]
        calls = [t for t in calls if now - t < window]
        self._rate_limits[tool_name] = calls
        
        if len(calls) >= limit:
            return False
        
        calls.append(now)
        return True
    
    # ==================== EXECUTION ====================
    
    async def execute(
        self,
        tool_name: str,
        args: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Executa uma ferramenta com logging e métricas."""
        spec = self.get(tool_name)
        if not spec:
            return {"ok": False, "error": f"Tool '{tool_name}' not found"}
        
        auth = self.check_authorization(tool_name, context)
        if not auth.allowed:
            return {
                "ok": False,
                "error": auth.reason,
                "requires_confirmation": auth.requires_confirmation,
                "confirmation_token": auth.confirmation_token,
            }
        
        execution = ToolExecution(
            tool_name=tool_name,
            input_args=args or {},
            approved_by=context.get("user_id") if context else None,
        )
        
        start_time = time.time()
        
        try:
            if spec.function:
                if asyncio.iscoroutinefunction(spec.function):
                    result = await asyncio.wait_for(
                        spec.function(**(args or {})),
                        timeout=spec.cost.max_seconds
                    )
                else:
                    result = await asyncio.to_thread(
                        spec.function, **(args or {})
                    )
            else:
                result = await self._execute_builtin(tool_name, args or {}, spec)
            
            execution.success = True
            execution.output = result
            execution.ended_at = time.time()
            execution.execution_time_ms = int((execution.ended_at - execution.started_at) * 1000)
            
            self._update_stats(spec.name, execution)
            self._write_audit(execution)
            
            return {"ok": True, "result": result, "execution": execution.to_dict()}
            
        except asyncio.TimeoutError:
            execution.success = False
            execution.error = "Timeout"
            execution.ended_at = time.time()
            execution.execution_time_ms = int((execution.ended_at - execution.started_at) * 1000)
            
            self._update_stats(spec.name, execution)
            self._write_audit(execution)
            
            return {
                "ok": False,
                "error": f"Timeout after {spec.cost.max_seconds}s",
                "execution": execution.to_dict(),
            }
            
        except Exception as e:
            execution.success = False
            execution.error = str(e)
            execution.ended_at = time.time()
            execution.execution_time_ms = int((execution.ended_at - execution.started_at) * 1000)
            
            self._update_stats(spec.name, execution)
            self._write_audit(execution)
            
            return {
                "ok": False,
                "error": str(e),
                "execution": execution.to_dict(),
            }
    
    def execute_sync(
        self,
        tool_name: str,
        args: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Versão síncrona de execute."""
        return asyncio.run(self.execute(tool_name, args, context))
    
    async def _execute_builtin(
        self,
        tool_name: str,
        args: Dict[str, Any],
        spec: ToolSpec,
    ) -> Any:
        """Executa uma tool builtin integrada."""
        from ultronpro import env_tools, web_browser, knowledge_bridge, store
        
        if tool_name == "web.search":
            return web_browser.search_web(
                args.get("query", ""),
                top_k=args.get("top_k", 5),
            )
        
        if tool_name == "web.fetch":
            return web_browser.fetch_url(args.get("url", ""))
        
        if tool_name == "memory.rag":
            from ultronpro import knowledge_bridge
            return await knowledge_bridge.search_knowledge(
                args.get("query", ""),
                top_k=args.get("top_k", 5),
            )
        
        if tool_name == "memory.graph":
            triples = store.search_triples(
                args.get("query", ""),
                limit=args.get("limit", 10),
            )
            return {"triples": triples}
        
        if tool_name == "memory.cache":
            from ultronpro import semantic_cache
            return semantic_cache.lookup(
                args.get("query", ""),
                threshold=args.get("threshold", 0.8),
            )
        
        if tool_name == "file.read":
            path = args.get("path", "")
            p = Path(path)
            if p.exists():
                return {"ok": True, "content": p.read_text(encoding="utf-8")}
            return {"ok": False, "error": "File not found"}
        
        if tool_name == "file.write":
            path = args.get("path", "")
            content = args.get("content", "")
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            return {"ok": True, "path": str(p)}
        
        if tool_name == "task.dream":
            from ultronpro import sleep_cycle
            return sleep_cycle.run_cycle(
                retention_days=args.get("retention_days", 14),
                max_active_rows=args.get("max_active_rows", 3000),
            )
        
        return {"ok": True, "message": f"Tool '{tool_name}' executed"}
    
    # ==================== STATS ====================
    
    def _update_stats(self, tool_name: str, execution: ToolExecution):
        """Atualiza estatísticas de uso."""
        if tool_name not in self._stats:
            self._stats[tool_name] = ToolStats()
        
        stats = self._stats[tool_name]
        stats.total_calls += 1
        stats.total_time_ms += execution.execution_time_ms
        
        if execution.success:
            stats.successful_calls += 1
        else:
            stats.failed_calls += 1
            stats.last_error = execution.error
        
        stats.last_used = execution.ended_at
    
    def get_stats(self, tool_name: Optional[str] = None) -> Dict[str, Any]:
        """Retorna estatísticas de uso."""
        if tool_name:
            spec = self.get(tool_name)
            if not spec:
                return {}
            return {
                "tool": tool_name,
                "spec": spec.to_dict(),
                "stats": self._stats.get(tool_name, ToolStats()).to_dict(),
            }
        
        return {
            name: self._stats.get(name, ToolStats()).to_dict()
            for name in self._tools
        }
    
    # ==================== AUDIT ====================
    
    def _write_audit(self, execution: ToolExecution):
        """Escreve entrada no audit log."""
        if not self._audit_enabled:
            return
        
        try:
            entry = {
                "ts": int(time.time()),
                **execution.to_dict(),
            }
            with self._audit_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning(f"Failed to write tool audit: {e}")
    
    def get_audit_log(self, tool_name: Optional[str] = None, limit: int = 100) -> List[Dict]:
        """Retorna entradas do audit log."""
        if not self._audit_path.exists():
            return []
        
        entries = []
        try:
            with self._audit_path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        if tool_name and entry.get("tool_name") != tool_name:
                            continue
                        entries.append(entry)
                    except:
                        continue
        except Exception:
            pass
        
        return entries[-limit:]
    
    # ==================== STATUS ====================
    
    def list_all(self) -> List[Dict[str, Any]]:
        """Lista todas as ferramentas registradas."""
        return [
            {
                "spec": spec.to_dict(),
                "stats": self._stats.get(name, ToolStats()).to_dict(),
            }
            for name, spec in self._tools.items()
        ]
    
    def get_categories(self) -> List[str]:
        """Retorna lista de categorias disponíveis."""
        return [cat.value for cat in ToolCategory]
    
    def get_by_category(self, category: ToolCategory) -> List[ToolSpec]:
        """Retorna todas as tools de uma categoria."""
        return self.find(category=category)


# ==================== GLOBAL INSTANCE ====================

_registry: Optional[ToolRegistry] = None

def get_tool_registry() -> ToolRegistry:
    """Retorna instância global do registry."""
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
    return _registry


def tool(
    name: str,
    description: str,
    category: ToolCategory = ToolCategory.SYSTEM,
    cost: Optional[ToolCost] = None,
    risk: Optional[ToolRisk] = None,
    **kwargs
):
    """Decorador para registrar uma função como tool."""
    def decorator(func: Callable) -> Callable:
        registry = get_tool_registry()
        registry.register_function(
            name=name,
            func=func,
            description=description,
            category=category,
            cost=cost,
            risk=risk,
            **kwargs
        )
        return func
    return decorator
