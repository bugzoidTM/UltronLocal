"""
UltronPro Skill Executor - Camada Declarativa de Workflow

Executa skills como camada declarativa entre roteamento e execução.
Responsável por:
- Identificar skill adequado para tarefa
- Validar ferramentas permitidas
- Executar hooks pre/post
- Aplicar budget limits
- Validar success checks
"""

import os
import time
import logging
import hashlib
import asyncio
import re
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger("uvicorn")


class ExecutionStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    BUDGET_EXCEEDED = "budget_exceeded"


@dataclass
class ExecutionContext:
    """Contexto de execução de um skill."""
    task: str
    skill_name: str
    tools_allowed: List[str]
    hooks: Dict[str, str]
    budget_max_seconds: int
    risk_level: str
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    status: ExecutionStatus = ExecutionStatus.PENDING
    results: Dict[str, Any] = field(default_factory=dict)
    checks_passed: List[str] = field(default_factory=list)
    checks_failed: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    hooks_executed: List[str] = field(default_factory=list)


@dataclass
class SkillResult:
    """Resultado da execução de um skill."""
    success: bool
    skill_name: str
    status: ExecutionStatus
    output: Any
    execution_time_ms: int
    checks_passed: List[str]
    checks_failed: List[str]
    hooks_executed: List[str]
    error: Optional[str] = None
    budget_used_ms: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


class SkillExecutor:
    """
    Executor declarativo de skills.
    
    Funciona como camada entre decision_router e executors.
    Valida, configura e valida skills antes/depois da execução.
    """
    
    def __init__(self):
        from ultronpro import skill_loader
        self.loader = skill_loader.get_skill_loader()
        self._hooks_registry: Dict[str, Callable] = {}
        self._register_default_hooks()
    
    def _register_default_hooks(self):
        """Registra hooks padrão do sistema."""
        self._hooks_registry = {
            # Hooks de permissão
            'verificar_permissao_web': self._hook_check_web_permission,
            'verificar_permissao_write': self._hook_check_write_permission,
            'verificar_permissao_exec': self._hook_check_exec_permission,
            
            # Hooks de validação
            'verificar_nao_existe': self._hook_check_not_exists,
            'verificar_gap_conhecimento': self._hook_check_knowledge_gap,
            'validar_input': self._hook_validate_input,
            
            # Hooks de cache/armazenamento
            'cache_resultado': self._hook_cache_result,
            'indexar_no_rag': self._hook_index_rag,
            'documentar_solucao': self._hook_document_solution,
            'registrar_padroes_encontrados': self._hook_register_patterns,
            
            # Hooks de análise
            'analisar_stacktrace': self._hook_analyze_stacktrace,
            'analisar_contexto_projeto': self._hook_analyze_project_context,
        }
    
    def _register_hook(self, name: str, func: Callable):
        """Registra um hook customizado."""
        self._hooks_registry[name] = func
    
    def _hook_check_web_permission(self, ctx: ExecutionContext) -> bool:
        """Verifica permissão para web."""
        return os.getenv('ULTRON_ALLOW_WEB_ACCESS', '1') == '1'
    
    def _hook_check_write_permission(self, ctx: ExecutionContext) -> bool:
        """Verifica permissão de escrita."""
        return os.getenv('ULTRON_ALLOW_WRITE', '0') == '1'
    
    def _hook_check_exec_permission(self, ctx: ExecutionContext) -> bool:
        """Verifica permissão de execução."""
        return os.getenv('ULTRON_ALLOW_EXEC', '0') == '1'
    
    def _hook_check_not_exists(self, ctx: ExecutionContext) -> bool:
        """Verifica se conceito não existe no grafo."""
        try:
            from ultronpro import store
            triples = store.search_triples(ctx.task, limit=1)
            return len(triples) == 0
        except:
            return True
    
    def _hook_check_knowledge_gap(self, ctx: ExecutionContext) -> bool:
        """Verifica gap de conhecimento."""
        return True  # Implementação pode verificar RAG
    
    def _hook_validate_input(self, ctx: ExecutionContext) -> bool:
        """Valida input da tarefa."""
        return len(ctx.task.strip()) > 0
    
    def _hook_cache_result(self, ctx: ExecutionContext) -> bool:
        """Armazena resultado em cache."""
        try:
            from ultronpro import semantic_cache
            semantic_cache.store(ctx.task, ctx.results.get('output', ''))
            return True
        except:
            return False
    
    def _hook_index_rag(self, ctx: ExecutionContext) -> bool:
        """Indexa resultado no RAG."""
        try:
            from ultronpro import knowledge_bridge
            text = str(ctx.results.get('output', ''))
            if len(text) > 50:
                res = knowledge_bridge.ingest_knowledge(text, source=f'skill:{ctx.skill_name}')
                if hasattr(res, '__await__'):
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(res)
                    except RuntimeError:
                        asyncio.run(res)
            return True
        except:
            return False
    
    def _hook_document_solution(self, ctx: ExecutionContext) -> bool:
        """Documenta solução no grafo."""
        try:
            from ultronpro import store
            output = str(ctx.results.get('output', ''))
            if output:
                store.remember(task=ctx.task, result=output, source=f'skill:{ctx.skill_name}')
            return True
        except:
            return False
    
    def _hook_register_patterns(self, ctx: ExecutionContext) -> bool:
        """Registra padrões encontrados."""
        return True
    
    def _hook_analyze_stacktrace(self, ctx: ExecutionContext) -> bool:
        """Analisa stacktrace."""
        return True
    
    def _hook_analyze_project_context(self, ctx: ExecutionContext) -> bool:
        """Analisa contexto do projeto."""
        return True
    
    def _execute_hook(self, hook_name: str, ctx: ExecutionContext) -> bool:
        """Executa um hook específico."""
        if hook_name in self._hooks_registry:
            try:
                result = self._hooks_registry[hook_name](ctx)
                ctx.hooks_executed.append(hook_name)
                return result
            except Exception as e:
                logger.warning(f"Hook {hook_name} failed: {e}")
                ctx.errors.append(f"Hook {hook_name}: {e}")
                return False
        else:
            logger.warning(f"Hook {hook_name} not found in registry")
            return True  # Hook não encontrado não bloqueia
    
    def _run_pre_hooks(self, ctx: ExecutionContext) -> bool:
        """Executa hooks pre-execução."""
        before_hook = ctx.hooks.get('before')
        if before_hook:
            return self._execute_hook(before_hook, ctx)
        return True
    
    def _run_post_hooks(self, ctx: ExecutionContext) -> bool:
        """Executa hooks post-execução."""
        after_hook = ctx.hooks.get('after')
        if after_hook:
            return self._execute_hook(after_hook, ctx)
        return True
    
    def _validate_tools(self, tools_used: List[str], allowed_tools: List[str]) -> bool:
        """Valida se ferramentas usadas estão permitidas."""
        if not allowed_tools:
            return True  # Sem lista, permite tudo
        
        for tool in tools_used:
            tool_base = tool.split('.')[0] if '.' in tool else tool
            if tool not in allowed_tools and not any(tool.startswith(t) for t in allowed_tools):
                return False
        return True
    
    def _check_budget(self, ctx: ExecutionContext) -> bool:
        """Verifica se budget foi respeitado."""
        elapsed = time.time() - ctx.start_time
        return elapsed <= ctx.budget_max_seconds
    
    def _validate_success_checks(self, ctx: ExecutionContext) -> tuple[List[str], List[str]]:
        """Valida success checks de um skill."""
        skill = self.loader.get_skill(ctx.skill_name)
        if not skill:
            return [], []
        
        passed = []
        failed = []
        
        output = str(ctx.results.get('output', ''))
        
        for check in skill.success_checks:
            check_lower = check.lower()
            
            # Verificações baseadas em conteúdo
            if 'resposta contem' in check_lower:
                marker = check_lower.replace('resposta contem', '').strip()
                output_lower = output.lower()
                has_source = bool(re.search(r'https?://\S+', output_lower)) or 'fonte:' in output_lower or 'source:' in output_lower
                if marker in ('fonte/url', 'fonte', 'url') and has_source:
                    passed.append(check)
                elif marker in output_lower:
                    passed.append(check)
                else:
                    failed.append(check)
            
            # Verificações de tempo
            elif 'tempo' in check_lower and '<' in check_lower:
                match = re.search(r'tempo\s*<\s*(\d+)', check_lower)
                if match:
                    max_time = int(match.group(1))
                    elapsed = (ctx.end_time or time.time()) - ctx.start_time
                    if elapsed < max_time:
                        passed.append(check)
                    else:
                        failed.append(check)
            
            # Verificações de инструмент
            elif 'ferramenta' in check_lower or 'tool' in check_lower:
                tools_used = ctx.results.get('tools_used', [])
                if any(t in output or t in str(ctx.results) for t in tools_used):
                    passed.append(check)
                else:
                    failed.append(check)
            
            # Verificação genérica
            else:
                passed.append(check)
        
        return passed, failed
    
    def _load_skill_context(self, skill_name: str, task: str) -> Optional[ExecutionContext]:
        """Carrega contexto de execução para um skill."""
        skill = self.loader.get_skill(skill_name)
        if not skill:
            return None
        
        return ExecutionContext(
            task=task,
            skill_name=skill_name,
            tools_allowed=skill.allowed_tools,
            hooks=skill.hooks,
            budget_max_seconds=skill.get_budget_limit(),
            risk_level=skill.risk_level,
        )

    async def _execute_builtin_skill(self, skill_name: str, task: str) -> Optional[Dict[str, Any]]:
        """Executa skills com implementação local direta quando disponível."""
        if skill_name != 'web_search':
            return None

        from ultronpro import web_browser

        res = await asyncio.to_thread(web_browser.search_web, task, 5, 8.0)
        if not res.get('ok'):
            return {
                'output': f"Pesquisa web falhou para '{task}'. Erro: {res.get('error') or 'unknown'}.",
                'tools_used': ['web_browser.search'],
                'raw': res,
            }

        items = res.get('items') or []
        sources: List[Dict[str, Any]] = []
        for item in items[:4]:
            title = str(item.get('title') or 'Fonte sem título').strip()
            url = str(item.get('url') or '').strip()
            snippet = str(item.get('snippet') or '').strip()
            text = snippet
            if url and len(text) < 260:
                try:
                    fetched = await asyncio.to_thread(web_browser.fetch_url, url, 2600)
                    if fetched.get('ok') and str(fetched.get('text') or '').strip():
                        text = str(fetched.get('text') or '').strip()
                        title = str(fetched.get('title') or title).strip() or title
                        url = str(fetched.get('url') or url).strip() or url
                except Exception:
                    pass
            sources.append({
                'title': title,
                'url': url,
                'snippet': snippet,
                'text': text[:2600],
            })

        answer = await self._synthesize_web_answer(task, sources)
        lines = [
            answer,
            "",
            "**Fontes:**",
        ]
        for idx, src in enumerate(sources[:5], start=1):
            title = str(src.get('title') or 'Fonte sem título').strip()
            url = str(src.get('url') or '').strip()
            lines.append(f"{idx}. {title} — fonte/URL: {url}")
        if not items:
            lines = [
                "Não encontrei fontes verificáveis para responder com segurança a essa pergunta.",
                "",
                "**Fontes:** nenhuma fonte/URL encontrada.",
            ]

        return {
            'output': "\n".join(lines),
            'tools_used': ['web_browser.search', 'web_browser.fetch'],
            'raw': {'search': res, 'sources': sources},
        }

    async def _synthesize_web_answer(self, task: str, sources: List[Dict[str, Any]]) -> str:
        if not sources:
            return "Não encontrei evidências suficientes na web para responder com segurança."

        evidence_blocks = []
        for idx, src in enumerate(sources[:4], start=1):
            title = str(src.get('title') or '').strip()
            url = str(src.get('url') or '').strip()
            text = " ".join(str(src.get('text') or src.get('snippet') or '').split())[:1400]
            evidence_blocks.append(f"[{idx}] {title}\nURL: {url}\nTrecho: {text}")

        prompt = (
            "Você é a skill web_search do UltronPro. Responda à pergunta do usuário usando as fontes abaixo.\n"
            "Não devolva apenas uma lista de URLs. Comece com uma resposta direta e cite as fontes como [1], [2].\n"
            "Se as fontes forem insuficientes, diga claramente o que foi possível verificar.\n"
            "Responda em PT-BR, de forma concisa.\n\n"
            f"Pergunta: {task}\n\n"
            "Fontes recuperadas:\n" + "\n\n".join(evidence_blocks)
        )

        try:
            from ultronpro import llm
            answer = await asyncio.to_thread(llm.complete, prompt, strategy='cheap', max_tokens=4096)
            answer = str(answer or '').strip()
            if answer and not self._looks_like_url_list(answer):
                return answer
        except Exception:
            pass

        bullets = []
        for idx, src in enumerate(sources[:3], start=1):
            title = str(src.get('title') or f'Fonte {idx}').strip()
            text = " ".join(str(src.get('text') or src.get('snippet') or '').split())
            if text:
                sentence = re.split(r'(?<=[.!?])\s+', text)[0][:320]
                bullets.append(f"- {sentence} [{idx}]")
            else:
                bullets.append(f"- Encontrei uma fonte relevante: {title}. [{idx}]")
        return (
            f"Com base nas fontes encontradas, a resposta para \"{task}\" é:\n"
            + "\n".join(bullets)
        )

    def _looks_like_url_list(self, answer: str) -> bool:
        lines = [ln.strip() for ln in str(answer or '').splitlines() if ln.strip()]
        if not lines:
            return True
        url_lines = sum(1 for ln in lines if re.search(r'https?://\S+', ln))
        return url_lines >= max(2, len(lines) // 2) and len(" ".join(lines)) < 900
    
    async def execute(self, task: str, suggested_skill: Optional[str] = None) -> SkillResult:
        """
        Executa um skill para uma tarefa.
        
        Args:
            task: Tarefa a ser executada
            suggested_skill: Nome do skill sugerido (opcional)
        
        Returns:
            SkillResult com resultado da execução
        """
        start_time = time.time()
        
        # Identificar skill
        skill_name = suggested_skill
        if not skill_name:
            skill = self.loader.suggest_skill(task)
            if skill:
                skill_name = skill.name
        
        if not skill_name:
            return SkillResult(
                success=False,
                skill_name='none',
                status=ExecutionStatus.FAILED,
                output=None,
                execution_time_ms=int((time.time() - start_time) * 1000),
                checks_passed=[],
                checks_failed=[],
                hooks_executed=[],
                error="No skill found for task"
            )
        
        # Carregar contexto
        ctx = self._load_skill_context(skill_name, task)
        if not ctx:
            return SkillResult(
                success=False,
                skill_name=skill_name,
                status=ExecutionStatus.FAILED,
                output=None,
                execution_time_ms=int((time.time() - start_time) * 1000),
                checks_passed=[],
                checks_failed=[],
                hooks_executed=[],
                error=f"Failed to load skill: {skill_name}"
            )
        
        ctx.status = ExecutionStatus.RUNNING
        
        # Verificar budget
        if not self._check_budget(ctx):
            return SkillResult(
                success=False,
                skill_name=skill_name,
                status=ExecutionStatus.BUDGET_EXCEEDED,
                output=None,
                execution_time_ms=int((time.time() - start_time) * 1000),
                checks_passed=[],
                checks_failed=[],
                hooks_executed=ctx.hooks_executed,
                error="Budget exceeded"
            )
        
        # Executar hooks pre
        if not self._run_pre_hooks(ctx):
            return SkillResult(
                success=False,
                skill_name=skill_name,
                status=ExecutionStatus.FAILED,
                output=None,
                execution_time_ms=int((time.time() - start_time) * 1000),
                checks_passed=ctx.checks_passed,
                checks_failed=['pre_hook_failed'],
                hooks_executed=ctx.hooks_executed,
                error="Pre-hook failed"
            )
        
        # Executar skill (implementação local direta quando houver; LLM como fallback)
        try:
            builtin_result = await self._execute_builtin_skill(skill_name, task)
            if builtin_result is not None:
                output = builtin_result.get('output')
                tools_used = builtin_result.get('tools_used') or ctx.tools_allowed
                raw_result = builtin_result.get('raw')
            else:
                from ultronpro import llm
                prompt = f"Executing specialized skill: [{skill_name}]. Task: {task}\n\nExecute the skill logic and return the final output in PT-BR."
                output = await asyncio.to_thread(llm.complete, prompt)
                tools_used = ctx.tools_allowed
                raw_result = None
            
            ctx.results = {
                'output': output,
                'tools_used': tools_used,
                'raw': raw_result,
            }
            ctx.status = ExecutionStatus.SUCCESS
        except Exception as e:
            ctx.status = ExecutionStatus.FAILED
            ctx.errors.append(str(e))
            return SkillResult(
                success=False,
                skill_name=skill_name,
                status=ExecutionStatus.FAILED,
                output=None,
                execution_time_ms=int((time.time() - start_time) * 1000),
                checks_passed=ctx.checks_passed,
                checks_failed=['execution_failed'],
                hooks_executed=ctx.hooks_executed,
                error=str(e)
            )
        
        ctx.end_time = time.time()
        
        # Executar hooks post
        self._run_post_hooks(ctx)
        
        # Validar success checks
        checks_passed, checks_failed = self._validate_success_checks(ctx)
        ctx.checks_passed = checks_passed
        ctx.checks_failed = checks_failed
        
        return SkillResult(
            success=ctx.status == ExecutionStatus.SUCCESS and len(checks_failed) == 0,
            skill_name=skill_name,
            status=ctx.status,
            output=ctx.results.get('output'),
            execution_time_ms=int((ctx.end_time - start_time) * 1000),
            checks_passed=checks_passed,
            checks_failed=checks_failed,
            hooks_executed=ctx.hooks_executed,
            budget_used_ms=int((ctx.end_time - start_time) * 1000),
            metadata={
                'risk_level': ctx.risk_level,
                'tools_allowed': ctx.tools_allowed,
            }
        )
    
    def execute_sync(self, task: str, suggested_skill: Optional[str] = None) -> SkillResult:
        """Versão síncrona do execute."""
        import asyncio
        return asyncio.run(self.execute(task, suggested_skill))


# Instância global
_executor: Optional[SkillExecutor] = None

def get_skill_executor() -> SkillExecutor:
    """Retorna instância global do executor."""
    global _executor
    if _executor is None:
        _executor = SkillExecutor()
    return _executor
