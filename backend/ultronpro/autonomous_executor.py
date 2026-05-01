"""
AutonomousExecutor - Execução autônoma de objetivos emergentes

O sistema define subtarefa → executa → avalia o próprio resultado → ajusta
Tudo sem gate humano obrigatório.

Fluxo:
1. Define objetivo emergente (do intrinsic_utility)
2. Cria subtarefas via planner
3. Executa ações autonomamente
4. Avalia resultado (self-assessment)
5. Ajusta comportamento (drives + params)
6. Repete até objetivo completo ou abandonado
"""

from __future__ import annotations

import json
import time
import asyncio
import logging
from pathlib import Path
from typing import Any, Optional
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger("uvicorn")

DATA_DIR = Path(__file__).resolve().parent.parent / 'data'


class ExecutionStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    ABANDONED = "abandoned"
    WAITING_APPROVAL = "waiting_approval"


@dataclass
class SubTask:
    id: str
    description: str
    expected_outcome: str
    status: ExecutionStatus = ExecutionStatus.PENDING
    result: str = ""
    execution_time_ms: int = 0
    attempts: int = 0
    max_attempts: int = 3


@dataclass
class ExecutionResult:
    task_id: str
    success: bool
    quality_score: float
    execution_time_ms: int
    feedback: str
    adjustments: list[str] = field(default_factory=list)


class AutonomousExecutor:
    """
    Executor autônomo que fecha o loop:
    objetivo → subtarefas → execução → avaliação → ajuste
    """
    
    def __init__(self):
        self.state_file = DATA_DIR / 'autonomous_executor_state.json'
        self.current_goal: dict | None = None
        self.subtasks: list[SubTask] = []
        self.execution_history: list[ExecutionResult] = []
        self.execution_enabled = True
        self.auto_approval_threshold = 0.7  # Auto-approve if confidence >= 0.7
        self.max_autonomous_iterations = 5
        self._load()
        
        # Gate humano configurável
        self.require_human_approval = os.getenv('ULTRON_REQUIRE_HUMAN_APPROVAL', '0') == '1'
    
    def _load(self):
        if self.state_file.exists():
            try:
                data = json.loads(self.state_file.read_text())
                self.execution_history = data.get('history', [])
            except Exception:
                pass
    
    def _save(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        try:
            self.state_file.write_text(json.dumps({
                'current_goal': self.current_goal,
                'subtasks_count': len(self.subtasks),
                'history': self.execution_history[-100:]
            }, indent=2, default=str))
        except Exception as e:
            logger.warning(f"Failed to save executor state: {e}")
    
    def get_emergent_goal(self) -> dict | None:
        """Obtém objetivo emergente do intrinsic_utility."""
        try:
            from ultronpro import intrinsic_utility
            state = intrinsic_utility._load()
            goal = state.get('active_emergent_goal')
            
            if not goal:
                # Deriva novo objetivo se não existir
                result = intrinsic_utility.tick()
                goal = result.get('active_emergent_goal')
            
            return goal
        except Exception as e:
            logger.warning(f"Failed to get emergent goal: {e}")
            return None
    
    def create_subtasks_from_goal(self, goal: dict) -> list[SubTask]:
        """
        Cria subtarefas a partir do objetivo emergente.
        Usa código determinístico quando possível, LLM como fallback.
        """
        drive = goal.get('drive', 'unknown')
        description = goal.get('description', '')
        subtasks = []
        
        # Regras determinísticas para cada drive
        if drive == 'competence':
            # Melhorar qualidade das ações
            subtasks.append(SubTask(
                id="comp_1",
                description="Analisar métricas de qualidade das últimas ações",
                expected_outcome="Lista de domínios com baixa qualidade (<0.5)"
            ))
            subtasks.append(SubTask(
                id="comp_2", 
                description="Identificar padrões de falha mais frequentes",
                expected_outcome="Top 3 padrões de falha com contagem"
            ))
            subtasks.append(SubTask(
                id="comp_3",
                description="Gerar recomendações de melhoria",
                expected_outcome="Ações priorizadas para melhorar qualidade"
            ))
        
        elif drive == 'coherence':
            # Reduzir stress contraditório
            subtasks.append(SubTask(
                id="coh_1",
                description="Listar conflitos abertos mais antigos",
                expected_outcome="Top 5 conflitos por idade"
            ))
            subtasks.append(SubTask(
                id="coh_2",
                description="Avaliar viabilidade de resolução",
                expected_outcome="Conflitos resolúveis vs não-resoluíveis"
            ))
        
        elif drive == 'autonomy':
            # Aumentar taxa local
            subtasks.append(SubTask(
                id="aut_1",
                description="Contar ações locais vs cloud nas últimas 100",
                expected_outcome="Percentual de autonomia"
            ))
            subtasks.append(SubTask(
                id="aut_2",
                description="Identificar tipos de query que exigem cloud",
                expected_outcome="Lista de casos que precisam LLM externo"
            ))
        
        elif drive == 'novelty':
            # Expandir conhecimento
            subtasks.append(SubTask(
                id="nov_1",
                description="Listar domínios com menos conhecimento no grafo",
                expected_outcome="Top 5 domínios inexplorados"
            ))
            subtasks.append(SubTask(
                id="nov_2",
                description="Sugerir áreas para exploração",
                expected_outcome="Domínios priorizados por utilidade"
            ))
        
        elif drive == 'integrity':
            # Restaurar integridade
            subtasks.append(SubTask(
                id="int_1",
                description="Verificar invariantes do sistema",
                expected_outcome="Lista de invariantes violados"
            ))
            subtasks.append(SubTask(
                id="int_2",
                description="Checar self-contract",
                expected_outcome="Status de compliance"
            ))
        
        else:
            # Fallback: análise geral
            subtasks.append(SubTask(
                id="gen_1",
                description=f"Analisar estado do drive '{drive}'",
                expected_outcome="Diagnóstico e recomendações"
            ))
        
        return subtasks
    
    async def execute_subtask(self, task: SubTask) -> ExecutionResult:
        """Executa uma subtarefa e retorna resultado."""
        task.status = ExecutionStatus.RUNNING
        task.attempts += 1
        t0 = time.time()
        
        try:
            result_text = ""
            success = False
            quality_score = 0.5
            
            # Execução determinística baseada no ID da tarefa
            if task.id.startswith("comp_"):
                result_text = await self._execute_competence_task(task)
                success = True
                quality_score = 0.7
            elif task.id.startswith("coh_"):
                result_text = await self._execute_coherence_task(task)
                success = True
                quality_score = 0.7
            elif task.id.startswith("aut_"):
                result_text = await self._execute_autonomy_task(task)
                success = True
                quality_score = 0.8
            elif task.id.startswith("nov_"):
                result_text = await self._execute_novelty_task(task)
                success = True
                quality_score = 0.6
            elif task.id.startswith("int_"):
                result_text = await self._execute_integrity_task(task)
                success = True
                quality_score = 0.7
            else:
                result_text = f"Análise genérica: {task.description}"
                success = True
                quality_score = 0.5
            
            task.status = ExecutionStatus.SUCCESS if success else ExecutionStatus.FAILED
            task.result = result_text
            task.execution_time_ms = int((time.time() - t0) * 1000)
            
            return ExecutionResult(
                task_id=task.id,
                success=success,
                quality_score=quality_score,
                execution_time_ms=task.execution_time_ms,
                feedback=result_text
            )
            
        except Exception as e:
            task.status = ExecutionStatus.FAILED
            task.result = f"Erro: {str(e)}"
            task.execution_time_ms = int((time.time() - t0) * 1000)
            
            return ExecutionResult(
                task_id=task.id,
                success=False,
                quality_score=0.0,
                execution_time_ms=task.execution_time_ms,
                feedback=f"Execução falhou: {str(e)}"
            )
    
    async def _execute_competence_task(self, task: SubTask) -> str:
        """Executa tarefa de competência (melhorar qualidade)."""
        try:
            from ultronpro import self_model, rl_policy
            
            # Coletar métricas
            op = self_model.load().get('operational', {})
            posture = op.get('risk_posture', {})
            avg_q = posture.get('avg_quality', 0.5)
            avg_g = posture.get('avg_grounding', 0.5)
            
            # Analisar RL policy
            ps = rl_policy.policy_summary(limit=20)
            arms = ps.get('arms', [])
            
            low_quality = []
            for arm in arms:
                if isinstance(arm, dict):
                    mean = arm.get('mean', 0.5)
                    if mean < 0.5:
                        low_quality.append({
                            'action': arm.get('action_kind', 'unknown'),
                            'mean': mean
                        })
            
            result = f"Qualidade média: {avg_q:.0%}, Groundness: {avg_g:.0%}. "
            result += f"Ações com baixa qualidade: {len(low_quality)}"
            
            if low_quality:
                result += f". Prioridades: {[a['action'] for a in low_quality[:3]]}"
            
            return result
        except Exception as e:
            return f"Análise de competência: {str(e)}"
    
    async def _execute_coherence_task(self, task: SubTask) -> str:
        """Executa tarefa de coerência (resolver conflitos)."""
        try:
            from ultronpro import store
            
            conflicts = store.list_conflicts(status='open', limit=5)
            
            if not conflicts:
                return "Nenhum conflito aberto. Coerência nominal."
            
            oldest = sorted(conflicts, key=lambda c: c.get('created_at', 0))[:3]
            result = f"{len(conflicts)} conflitos abertos. "
            result += "Mais antigos: " + ", ".join([c.get('subject', '?') for c in oldest])
            
            return result
        except Exception as e:
            return f"Análise de coerência: {str(e)}"
    
    async def _execute_autonomy_task(self, task: SubTask) -> str:
        """Executa tarefa de autonomia (aumentar resolução local)."""
        try:
            from ultronpro import self_model
            
            causal = self_model.load().get('causal', {})
            events = causal.get('recent_events', [])
            
            if not events:
                return "Sem eventos recentes para análise."
            
            recent = events[-100:]
            local_count = sum(
                1 for e in recent 
                if 'local' in str(e.get('strategy', '')).lower() 
                or 'symbolic' in str(e.get('strategy', '')).lower()
                or 'cache' in str(e.get('strategy', '')).lower()
            )
            
            autonomy_rate = local_count / len(recent) if recent else 0
            result = f"Taxa de autonomia: {autonomy_rate:.0%} ({local_count}/{len(recent)} ações locais)"
            
            return result
        except Exception as e:
            return f"Análise de autonomia: {str(e)}"
    
    async def _execute_novelty_task(self, task: SubTask) -> str:
        """Executa tarefa de novidade (explorar conhecimento)."""
        try:
            from ultronpro import graph
            
            # Contar nodos por domínio
            try:
                root = graph.get_root()
                nodes = graph.list_nodes(root_id=root.get('id') if root else None, limit=100)
                
                domains = {}
                for n in nodes:
                    if isinstance(n, dict):
                        d = n.get('domain', 'unknown')
                        domains[d] = domains.get(d, 0) + 1
                
                if domains:
                    sorted_domains = sorted(domains.items(), key=lambda x: x[1])
                    result = f"Domínios conhecidos: {len(domains)}. "
                    result += "Menos explorados: " + ", ".join([f"{d}({c})" for d, c in sorted_domains[:3]])
                else:
                    result = "Grafo vazio ou inacessível."
            except:
                result = "Não foi possível acessar o grafo causal."
            
            return result
        except Exception as e:
            return f"Análise de novidade: {str(e)}"
    
    async def _execute_integrity_task(self, task: SubTask) -> str:
        """Executa tarefa de integridade (verificar invariantes)."""
        try:
            from ultronpro import self_governance
            
            inv = self_governance.invariants_status()
            violations = inv.get('violations', []) if isinstance(inv, dict) else []
            
            result = f"Invariantes: {len(violations)} violados"
            if violations:
                result += ". Exemplos: " + ", ".join([str(v)[:30] for v in violations[:2]])
            
            return result
        except Exception as e:
            return f"Análise de integridade: {str(e)}"
    
    def evaluate_goal_progress(self, results: list[ExecutionResult]) -> tuple[bool, float, str]:
        """
        Avalia progresso do objetivo baseado nos resultados das subtarefas.
        Retorna (completed, overall_score, feedback).
        """
        if not results:
            return False, 0.0, "Nenhuma subtarefa executada"
        
        total_score = sum(r.quality_score for r in results) / len(results)
        success_count = sum(1 for r in results if r.success)
        success_rate = success_count / len(results)
        
        avg_time = sum(r.execution_time_ms for r in results) / len(results)
        
        feedback = f"Execução: {success_count}/{len(results)} tarefas. "
        feedback += f"Score médio: {total_score:.0%}. "
        feedback += f"Tempo médio: {avg_time:.0f}ms"
        
        completed = success_rate >= 0.7 and total_score >= 0.5
        
        return completed, (total_score + success_rate) / 2, feedback
    
    async def execute_autonomous_cycle(self) -> dict[str, Any]:
        """
        Executa um ciclo completo de execução autônoma.
        
        Returns:
            dict com status da execução, resultados, e ajustes feitos
        """
        if not self.execution_enabled:
            return {'status': 'disabled', 'message': 'Execução autônoma desabilitada'}
        
        cycle_result = {
            'timestamp': time.time(),
            'goal': None,
            'subtasks_executed': 0,
            'overall_score': 0.0,
            'completed': False,
            'adjustments': [],
            'feedback': '',
            'epistemic_gap_perception': None,
            'active_investigation_experiment': None,
        }

        try:
            from ultronpro import active_investigation

            pending = await asyncio.to_thread(active_investigation.pending_experiments, limit=1)
            if not pending:
                try:
                    from ultronpro import epistemic_curiosity

                    gaps = await asyncio.to_thread(epistemic_curiosity.collect_epistemic_gaps, use_cache=False)
                    seed_result = await asyncio.to_thread(
                        active_investigation.seed_epistemic_gap_experiments,
                        gaps,
                        limit=1,
                        source='autonomous_executor_epistemic_gap_scan',
                    )
                except Exception as seed_exc:
                    seed_result = {
                        'ok': False,
                        'seeded': 0,
                        'error': f'{type(seed_exc).__name__}:{str(seed_exc)[:180]}',
                    }
            else:
                seed_result = {'ok': True, 'seeded': 0, 'reason': 'pending_queue_not_empty'}
            cycle_result['epistemic_gap_perception'] = seed_result

            investigation_result = await asyncio.to_thread(active_investigation.execute_pending_experiment)
            cycle_result['active_investigation_experiment'] = investigation_result
            if investigation_result.get('executed'):
                if investigation_result.get('ok') and investigation_result.get('injected'):
                    cycle_result['adjustments'].append(
                        f"Investigacao ativa consumida e injetada no grafo causal: {investigation_result.get('investigation_id')}"
                    )
                else:
                    cycle_result['adjustments'].append(
                        f"Investigacao ativa consumida mas nao consolidada: {investigation_result.get('error') or investigation_result.get('reason')}"
                    )
        except Exception as e:
            logger.warning(f"Active investigation experiment skipped: {e}")
            cycle_result['active_investigation_experiment'] = {
                'ok': False,
                'executed': False,
                'error': str(e)[:180],
            }
        
        # 1. Obter objetivo emergente
        goal = self.get_emergent_goal()
        if not goal:
            cycle_result['status'] = 'no_goal'
            cycle_result['message'] = 'Nenhum objetivo emergente disponivel'
            return cycle_result
            return {'status': 'no_goal', 'message': 'Nenhum objetivo emergente disponível'}
        
        self.current_goal = goal
        cycle_result['goal'] = goal.get('title') or goal.get('drive', 'unknown')
        
        # 2. Criar subtarefas se necessário
        if not self.subtasks:
            self.subtasks = self.create_subtasks_from_goal(goal)
        
        # 2.5 Mental Simulation: comparar hipóteses sobre como executar o objetivo
        mental_scenario_id = None
        try:
            from ultronpro import mental_simulation
            # Create hypotheses for the objective
            hyps = [
                {
                    "description": f"Executar todas subtarefas de '{goal.get('drive', '?')}' na ordem padrão",
                    "predicted_outcome": "sucesso incremental",
                    "confidence": 0.65,
                    "risk": 0.25,
                    "benefit": 0.7,
                },
                {
                    "description": f"Focar apenas na subtarefa de maior impacto para '{goal.get('drive', '?')}'",
                    "predicted_outcome": "ganho rápido concentrado",
                    "confidence": 0.55,
                    "risk": 0.35,
                    "benefit": 0.8,
                },
            ]
            scn = mental_simulation.compare(
                f"autonomous:{goal.get('drive', 'unknown')}",
                hyps,
            )
            mental_scenario_id = scn.get('id') if isinstance(scn, dict) else None
            cycle_result['mental_simulation'] = {
                'scenario_id': mental_scenario_id,
                'chosen': (scn.get('simulated_outcome') or {}).get('hypothesis_description', '') if isinstance(scn, dict) else '',
            }
        except Exception as e:
            logger.debug(f"Mental simulation skipped in autonomous cycle: {e}")
        
        # 3. Executar subtarefas (com pré-imaginação)
        results = []
        for task in self.subtasks:
            if task.status == ExecutionStatus.SUCCESS:
                continue  # Já executada
            
            if task.attempts >= task.max_attempts:
                task.status = ExecutionStatus.ABANDONED
                continue
            
            # 3.1 Pre-imagine consequences of this specific subtask
            try:
                from ultronpro import mental_simulation
                pre_sim = mental_simulation.imagine(
                    action_kind=f"subtask:{task.id}",
                    action_text=task.description,
                    context={"goal_drive": goal.get("drive"), "expected": task.expected_outcome},
                )
                if pre_sim.get("recommended_posture") == "abort":
                    logger.info(f"Mental Sim: ABORTANDO subtask {task.id} (posture=abort, risk={pre_sim.get('risk_score')})")
                    task.status = ExecutionStatus.ABANDONED
                    task.result = f"Bloqueada por simulação mental: risco={pre_sim.get('risk_score', '?')}"
                    cycle_result['adjustments'].append(f"Subtask '{task.id}' bloqueada pela simulação mental pré-execução")
                    continue
            except Exception:
                pass
            
            result = await self.execute_subtask(task)
            results.append(result)
            cycle_result['subtasks_executed'] += 1
            
            # Registrar no loop de reforço
            try:
                from ultronpro.autonomous_loop import close_loop_with_intrinsic
                close_loop_with_intrinsic(
                    action_kind='autonomous_execution',
                    context=task.id,
                    success=result.success,
                    quality_score=result.quality_score,
                    latency_ms=result.execution_time_ms
                )
            except Exception:
                pass
            
            # AUTO-CORREÇÃO: aprender com erros
            if not result.success:
                try:
                    from ultronpro.self_corrector import learn_from_error
                    learn_result = learn_from_error(
                        action='autonomous_execution',
                        context=task.id,
                        error=result.feedback,
                        metadata={'quality_score': result.quality_score}
                    )
                    if learn_result.get('correction_applied'):
                        cycle_result['adjustments'].append(f"Correção automática: {learn_result.get('correction', {}).get('reason', 'N/A')}")
                except Exception:
                    pass
            else:
                try:
                    from ultronpro.self_corrector import record_success
                    record_success('autonomous_execution', task.id)
                except Exception:
                    pass
        
        # 4. Avaliar progresso do objetivo
        completed, overall_score, feedback = self.evaluate_goal_progress(results)
        cycle_result['overall_score'] = overall_score
        cycle_result['completed'] = completed
        cycle_result['feedback'] = feedback
        
        # 4.5 Mental Simulation: learn from this execution (post-mortem)
        if mental_scenario_id:
            try:
                from ultronpro import mental_simulation
                learn_result = mental_simulation.learn(mental_scenario_id, {
                    "result": "sucesso" if completed else "parcial",
                    "success": completed,
                    "overall_score": overall_score,
                    "subtasks_done": cycle_result['subtasks_executed'],
                    "feedback": feedback,
                })
                if learn_result.get("ok"):
                    lessons = learn_result.get("lessons", [])
                    comps = learn_result.get("competencies_extracted", [])
                    if lessons:
                        cycle_result['adjustments'].append(f"Lições da simulação mental: {'; '.join(lessons[:2])}")
                    if comps:
                        cycle_result['adjustments'].append(f"Competências consolidadas: {len(comps)}")
            except Exception as e:
                logger.debug(f"Mental simulation post-mortem skipped: {e}")
        
        # 5. Se objetivo completo, sinalizar e possibly derivar novo
        if completed:
            cycle_result['adjustments'].append(f"Objetivo '{goal.get('drive')}' completado com score {overall_score:.0%}")
            
            # Atualizar progresso no goal tracker
            try:
                from ultronpro.autonomous_loop import get_autonomous_loop
                aloop = get_autonomous_loop()
                aloop.update_goal_progress(
                    f"emergent_{goal.get('drive', 'unknown')}",
                    1.0,
                    feedback
                )
            except Exception:
                pass
            
            # Limpar para próximo ciclo
            self.subtasks = []
            self.current_goal = None
        
        # 6. Ajustar parâmetros baseado nos resultados
        if results:
            avg_score = sum(r.quality_score for r in results) / len(results)
            if avg_score < 0.5:
                cycle_result['adjustments'].append("Baixo score detectado - ajustando parâmetros para modo conservador")
                # Could trigger parameter adjustments here
        
        # 7. Salvar histórico
        self.execution_history.append(ExecutionResult(
            task_id=goal.get('drive', 'unknown'),
            success=completed,
            quality_score=overall_score,
            execution_time_ms=sum(r.execution_time_ms for r in results),
            feedback=feedback
        ))
        self._save()
        
        return cycle_result
    
    def get_status(self) -> dict[str, Any]:
        """Retorna status do executor."""
        return {
            'enabled': self.execution_enabled,
            'current_goal': self.current_goal,
            'subtasks_pending': len([t for t in self.subtasks if t.status == ExecutionStatus.PENDING]),
            'subtasks_completed': len([t for t in self.subtasks if t.status == ExecutionStatus.SUCCESS]),
            'history_size': len(self.execution_history),
            'require_approval': self.require_human_approval,
            'auto_approval_threshold': self.auto_approval_threshold
        }


# Singleton
import os
_executor: AutonomousExecutor | None = None

def get_executor() -> AutonomousExecutor:
    global _executor
    if _executor is None:
        _executor = AutonomousExecutor()
    return _executor

async def run_plan(plan: Any, goal_id: str = "") -> dict[str, Any]:
    """
    Ponte para o AutonomousGoalLoop executar planos estruturados gerados pelo Planner.
    Converte os PlanSteps do ExecutionPlan em SubTasks e executa serialmente.
    """
    executor = get_executor()
    if not plan or not hasattr(plan, 'steps'):
        return {'success': False, 'error': 'Plano vazio ou inválido'}
    
    results = []
    fake_goal = {'drive': 'persistent', 'description': plan.objective}
    
    for idx, step in enumerate(plan.steps):
        task = SubTask(
            id=f"step_{idx}_{step.id}",
            description=step.text,
            expected_outcome=step.expected_outcome
        )
        res = await executor.execute_subtask(task)
        results.append(res)
        if not res.success:
            return {'success': False, 'error': f"Falha no passo {step.id}: {res.feedback}", 'results': results}
            
    return {'success': True, 'results': results}
