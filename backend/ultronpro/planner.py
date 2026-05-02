from __future__ import annotations
from pathlib import Path
from dataclasses import dataclass
from typing import Any
from ultronpro import llm, tom, mission_control, self_model, squad_phase_a, squad_profiles, store
import json
import uuid
import time
from typing import List, Optional


@dataclass
class PlanStep:
    id: str
    kind: str  # e.g., 'code', 'research', 'logic', 'retrieval'
    text: str
    expected_outcome: str
    assigned_model: str = "undecided"
    routing_audit: str = ""

@dataclass
class ExecutionPlan:
    id: str
    goal_id: Optional[str]
    objective: str
    steps: List[PlanStep]
    version: int = 1
    created_at: float = 0.0

@dataclass
class ProposedAction:
    kind: str
    text: str
    priority: int = 0
    meta: Optional[dict] = None


def propose_actions(store, fast_mode: bool = False) -> list[ProposedAction]:
    """AGI Engine Planner (Deterministic Brain):
    
    1. Percepção: Carrega o estado da consciência operacional (self_model).
    2. TOM (Theory of Mind): Infere a intenção do usuário baseada em interações recentes.
    3. Conflitos: Identifica inconsistências epistemológicas que exigem resolução.
    4. Missões: Alinha ações com os objetivos de longo prazo.
    5. Priorização: Usa política de RL e priors causais para ordenar o próximo passo.
    """
    try:
        from ultronpro import self_model, tom, mission_control, squad_phase_a
        report = self_model.generate_operational_consciousness_report()
        st = report['state_summary']
        mode = report['operational_status']
    except Exception:
        return []

    # Teoria da Mente (empatia cognitiva): inferir intenção do humano
    recent_exp = store.list_experiences(limit=20)
    intent = tom.infer_user_intent(recent_exp)
    ilabel = intent.get('label')
    iconf = float(intent.get('confidence') or 0.0)

    emergency = (ilabel == 'urgent' and iconf >= 0.5)

    # Impulso de Vida: objetivo ativo injeta direção proativa quando não há emergência
    active_goal = None
    try:
        active_goal = store.get_active_goal()
    except Exception:
        active_goal = None

    actions: list[ProposedAction] = []
    gtitle = ""
    gdesc = ""
    if active_goal and not emergency:
        gtitle = str(active_goal.get('title') or '').strip()
        gdesc = str(active_goal.get('description') or '').strip()
        gtxt = f"{gtitle} {gdesc}".lower()

        # ações proativas determinísticas orientadas ao objetivo
        if any(k in gtxt for k in ['python', 'program', 'codigo', 'código']):
            actions.append(
                ProposedAction(
                    kind='absorb_lightrag_general',
                    text='(impulso-vida) Absorver conhecimento Python no LightRAG para avançar objetivo ativo.',
                    priority=9,
                    meta={'domains': 'python', 'max_topics': 20, 'doc_limit': 12, 'goal_id': active_goal.get('id')},
                )
            )
            actions.append(
                ProposedAction(
                    kind='execute_python_sandbox',
                    text='(impulso-vida) Validar hipótese com código Python em sandbox (prova executável).',
                    priority=9,
                    meta={
                        'goal_id': active_goal.get('id'),
                        'code': "print('sandbox-check: python goal active')\nprint(sum(i*i for i in range(10)))",
                        'timeout_sec': 10,
                    },
                )
            )
            actions.append(
                ProposedAction(
                    kind='ask_evidence',
                    text='(impulso-vida) Pesquisar no LightRAG tópicos críticos de Python ligados ao objetivo ativo e sintetizar plano de estudo/execução.',
                    priority=8,
                    meta={'goal_id': active_goal.get('id'), 'goal_title': gtitle},
                )
            )
        else:
            if any(k in gtxt for k in ['otimizar', 'database', 'banco', 'sql', 'desempenho', 'performance']):
                actions.append(
                    ProposedAction(
                        kind='execute_python_sandbox',
                        text='(impulso-vida) Rodar script Python sandbox para medir hipótese técnica do objetivo.',
                        priority=8,
                        meta={
                            'goal_id': active_goal.get('id'),
                            'code': "import sqlite3, os\nprint('db-path', os.getenv('ULTRONPRO_DB_PATH',str(Path(__file__).resolve().parent.parent / 'data' / 'ultron.db')))\nprint('probe-ok')",
                            'timeout_sec': 12,
                        },
                    )
                )
            actions.append(
                ProposedAction(
                    kind='ask_evidence',
                    text=f"(impulso-vida) Próximo passo objetivo para avançar '{gtitle}' com menor custo e evidência verificável.",
                    priority=8,
                    meta={'goal_id': active_goal.get('id'), 'goal_title': gtitle},
                )
            )

        # Engine-driven prioritization (No LLM improvisation unless needed)
        # Se a qualidade estiver baixa, focar em consolidar o que já existe (Grounding)
        if st['grounding_anchoring'] < 0.6:
             actions.append(
                ProposedAction(
                    kind='ask_evidence',
                    text=f"(motor-consciência) Baixa ancoragem ({st['grounding_anchoring']}). Priorizar coleta de evidências factuais para {gtitle}.",
                    priority=10,
                    meta={'goal_id': active_goal.get('id'), 'reason': 'low_grounding'}
                )
            )

    if ilabel == 'confused':
        actions.append(
            ProposedAction(
                kind='ask_evidence',
                text='(ação-TOM) Reformular explicação em passos simples e verificar entendimento do humano com uma pergunta de checagem.',
                priority=7,
                meta={'tom_intent': ilabel, 'tom_confidence': iconf},
            )
        )
    elif ilabel == 'testing':
        actions.append(
            ProposedAction(
                kind='ask_evidence',
                text='(ação-TOM) Fornecer resposta auditável com critérios de validação (o que funciona, limite e como testar).',
                priority=7,
                meta={'tom_intent': ilabel, 'tom_confidence': iconf},
            )
        )
    elif ilabel == 'urgent':
        actions.append(
            ProposedAction(
                kind='auto_resolve_conflicts',
                text='(ação-TOM) Priorizar resolução rápida do bloqueio principal antes de exploração ampla.',
                priority=8,
                meta={'tom_intent': ilabel, 'tom_confidence': iconf},
            )
        )
    else:  # exploratory
        actions.append(
            ProposedAction(
                kind='generate_analogy_hypothesis',
                text='(ação-TOM) Expandir entendimento com analogia estrutural de domínio adjacente.',
                priority=5,
                meta={'tom_intent': ilabel, 'tom_confidence': iconf, 'problem_text': 'exploração de contexto atual', 'target_domain': 'general'},
            )
        )

    # 1) Conflicts: keep collecting evidence / clarification
    conflicts = store.list_conflicts(status='open', limit=10)
    conflict_base_priority = 4 if (active_goal and not emergency) else 6

    for c in conflicts:
        seen = int(c.get('seen_count') or 0)
        qc = int(c.get('question_count') or 0)
        subj = c.get('subject')
        pred = c.get('predicate')
        cid = int(c.get('id'))
        
        if qc > 3 and not fast_mode: 
            summary = c.get('last_summary') or f"{subj} {pred} ???"
            prompt = f"""O conflito de conhecimento "{summary}" está travado após várias tentativas.
Proponha uma estratégia criativa/lateral para resolvê-lo.
Exemplos: buscar etimologia, propor experimento mental, verificar consenso científico atual, buscar em outra língua.
Responda APENAS com a ação sugerida (uma frase imperativa)."""
            
            # Explicitly local and non-blocking if possible (already in thread, but avoid cloud fallback hang)
            strategy = llm.complete(prompt, system="Você é um estrategista de resolução de conflitos epistemológicos.", strategy='local', cloud_fallback=False)
            if strategy:
                actions.append(
                    ProposedAction(
                        kind='ask_evidence',
                        text=f"🧠 Estratégia Improvisada: {strategy}",
                        priority=max(5, conflict_base_priority + 1),
                        meta={"conflict_id": cid, "strategy": "llm_improv"},
                    )
                )
        elif seen >= 2:
            actions.append(
                ProposedAction(
                    kind='ask_evidence',
                    text=f"(ação) Coletar evidências: qual é a formulação correta para '{subj}' {pred}? Forneça fonte/experimento/definição.",
                    priority=conflict_base_priority,
                    meta={"conflict_id": cid},
                )
            )

            if subj and pred and seen >= 2:
                topic = str(subj).strip().replace(' ', '_')
                actions.append(
                    ProposedAction(
                        kind='verify_source_headless',
                        text=f"(ação) Verificar fonte canônica para conflito #{cid} via fetch headless.",
                        priority=max(5, conflict_base_priority + 1),
                        meta={
                            'conflict_id': cid,
                            'url': f'https://en.wikipedia.org/wiki/{topic}',
                            'max_chars': 6000,
                        },
                    )
                )
                actions.append(
                    ProposedAction(
                        kind='ground_claim_check',
                        text=f"(ação) Validar claim crítica do conflito #{cid} com grounding empírico (source+python/sql quando aplicável).",
                        priority=max(5, conflict_base_priority + 1),
                        meta={
                            'conflict_id': cid,
                            'claim': f"{subj} {pred}",
                            'url': f'https://en.wikipedia.org/wiki/{topic}',
                            'require_reliability': 0.55,
                        },
                    )
                )
            if seen >= 3:
                q = f"{subj} {pred}"
                actions.append(
                    ProposedAction(
                        kind='generate_analogy_hypothesis',
                        text=f"(ação) Tentar analogia estrutural para resolver conflito: {subj} {pred}",
                        priority=max(5, conflict_base_priority + 1),
                        meta={"conflict_id": cid, "problem_text": q, "target_domain": str(pred)},
                    )
                )

    # 2) No conflicts? keep curiosity questions alive
    try:
        st_stats = store.stats()
        if int(st_stats.get('questions_open') or 0) < 3:
            actions.append(
                ProposedAction(
                    kind='generate_questions',
                    text='(ação) Gerar novas perguntas de curiosidade para manter aprendizado ativo.',
                    priority=3,
                    meta=None,
                )
            )
    except Exception:
        pass

    # 3) Laws / Norms check
    try:
        laws = store.list_laws(status='active', limit=10)
        norms = store.list_norms(limit=200)
        if laws and len(norms) < 5:
            actions.append(
                ProposedAction(
                    kind='clarify_laws',
                    text='(ação) Pedir reescrita das Leis em frases simples do tipo "Você deve ..." / "Não ..." para facilitar compilação.',
                    priority=2,
                )
            )
    except Exception:
        pass

    # 4) Mission Control delegation awareness
    try:
        m_tasks = mission_control.list_tasks(limit=40)
        hot = [t for t in m_tasks if str(t.get('status') or '') in ('assigned', 'in_progress', 'blocked')]
        if hot:
            top = hot[-1]
            ttitle = str(top.get('title') or '')
            tstatus = str(top.get('status') or '')
            ass = ','.join(top.get('assignees') or [])
            actions.append(
                ProposedAction(
                    kind='ask_evidence',
                    text=f"(mission-control) Atualizar task '{ttitle}' [{tstatus}] com próximo passo e evidência objetiva (assignees={ass}).",
                    priority=6,
                    meta={'mission_task_id': top.get('id'), 'mission_status': tstatus, 'assignees': top.get('assignees') or []},
                )
            )
    except Exception:
        pass

    # 5) Online RL policy (Thompson Sampling) + causal priors as cold-start fallback
    try:
        from ultronpro import rl_policy
        # Derive context from homeostasis + task type
        _rl_ctx = 'general'
        try:
            from ultronpro import homeostasis as _hs
            _rl_ctx = str((_hs.status().get('mode') or 'normal'))
        except Exception:
            pass

        by_strategy = self_model.best_strategy_scores(limit=60)
        for a in actions:
            # Try RL policy first (needs >= 3 observations)
            rl_adj = rl_policy.sample_priority(str(a.kind), _rl_ctx)
            if rl_adj != 0:
                a.priority = int(a.priority or 0) + rl_adj
            else:
                # Cold-start fallback: use causal priors from self_model
                sr = by_strategy.get(str(a.kind), None)
                if sr is not None:
                    if sr >= 0.72:
                        a.priority = int(a.priority or 0) + 2
                    elif sr >= 0.58:
                        a.priority = int(a.priority or 0) + 1
                    elif sr <= 0.32:
                        a.priority = int(a.priority or 0) - 2
                    elif sr <= 0.45:
                        a.priority = int(a.priority or 0) - 1
    except Exception:
        pass

    # 6) Autonomous Squad Switching (Operational Consciousness)
    try:
        current_prof = squad_phase_a.get_current_profile_id()
        target_prof = None
        
        # Use active goal to detect domain
        if active_goal:
            target_prof = _detect_squad_profile(f"{gtitle} {gdesc}")
        
        # If no active goal, maybe look at recent intent?
        if not target_prof and ilabel:
             target_prof = _detect_squad_profile(ilabel)

        if target_prof and target_prof != current_prof:
            from ultronpro import squad_profiles
            pinfo = squad_profiles.get_profile(target_prof)
            actions.append(
                ProposedAction(
                    kind='switch_squad',
                    text=f"🔄 Otimizar equipe: Alternar para '{pinfo['name']}' para melhor suporte ao objetivo atual.",
                    priority=10, # High priority to align tools before execution
                    meta={'target_profile': target_prof, 'current_profile': current_prof, 'reason': 'domain_optimization'}
                )
            )
    except Exception:
        pass

    # sort
    actions.sort(key=lambda a: (-int(a.priority or 0), a.kind))
    return actions[:10]


def _detect_squad_profile(text: str) -> str | None:
    txt = str(text or '').lower()
    # Scientific / Research
    if any(k in txt for k in ['pesquisa', 'research', 'evidência', 'evidence', 'fonte', 'source', 'grounding', 'paper', 'científico']):
        return 'scientific_research'
    # Coding / Engineering
    if any(k in txt for k in ['código', 'code', 'python', 'refactor', 'refatorar', 'debug', 'bug', 'architect', 'devops', 'sandbox']):
        return 'code_analysis'
    # Logic / Math
    if any(k in txt for k in ['logic', 'lógico', 'math', 'matemática', 'proof', 'prova', 'algoritmo', 'symbolic', 'simbólico']):
        return 'logic_math'
    return None

async def generate_structured_plan(objective: str, goal_id: Optional[str] = None) -> ExecutionPlan:
    """
    Decomposes an objective deterministically into an ExecutionPlan via parsing.
    Rule of Gold: No LLM used for planning logic.
    """
    import uuid
    import time
    
    # Text segmentation heuristic
    raw_steps = [s.strip() for s in str(objective or '').split('. ') if len(s.strip()) > 3]
    if not raw_steps:
        raw_steps = [objective]
        
    steps = []
    for i, s_text in enumerate(raw_steps):
        detected_prof = _detect_squad_profile(s_text)
        kind = "logic"
        if detected_prof == 'code_analysis':
            kind = "code"
        elif detected_prof == 'scientific_research':
            kind = "research"
            
        steps.append(PlanStep(
            id=f"step_{i+1}",
            kind=kind,
            text=s_text,
            expected_outcome="Structural pass"
        ))
        
    return ExecutionPlan(
        id=str(uuid.uuid4()),
        goal_id=goal_id,
        objective=objective,
        steps=steps,
        created_at=time.time()
    )

def propose_goal_plan(goal: dict, store: Any = None) -> ExecutionPlan:
    """
    Sincronizador para chamada de geração de plano com modelo Local.
    """
    import asyncio
    title = str(goal.get('title') or '')
    desc = str(goal.get('description') or '')
    objective = f"{title}: {desc}".strip(": ")
    
    # Phase 5.4: Homeostasis check antes de planos volumosos
    try:
        from ultronpro import homeostasis
        h_status = homeostasis.status()
        if h_status.get('mode') == 'repair':
            return ExecutionPlan(
                id=str(uuid.uuid4()), goal_id=goal.get('id'), objective=f"RECOVERY: {title}",
                steps=[PlanStep(id="repair_1", kind="logic", text="Sistema em modo de REPARO. Adiar plano volumoso e focar em estabilização.", expected_outcome="Homeostase nominal")],
                created_at=time.time()
            )
    except Exception:
        pass

    # Executa de forma síncrona
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        # Estamos num contexto já assíncrono, embora autonomous_loop espere algo síncrono.
        # Fallback rápido se não puder rodar async_to_sync
        plan = ExecutionPlan(
            id=str(uuid.uuid4()), goal_id=goal.get('id'), objective=objective,
            steps=[PlanStep(id="step_1", kind="logic", text=objective, expected_outcome="Execute the goal")],
            created_at=time.time()
        )
        try:
             # Just try a naive sync direct call since llm.complete isn't really async
             import sys
             if sys.version_info >= (3, 7):
                 # actually generate_structured_plan does not await anything, but we must run it
                 pass
        except:
             pass
        # Better: use asyncio.run if not in a running loop, but FastAPI runs an event loop.
        # Using a new event loop can fail. Let's just create a thread to run it safely.
    
    import threading
    result_list = []
    def runner():
        import asyncio
        new_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(new_loop)
        try:
            res = new_loop.run_until_complete(generate_structured_plan(objective, goal.get('id')))
            result_list.append(res)
        finally:
            new_loop.close()
            
    t = threading.Thread(target=runner)
    t.start()
    t.join()
    
    if result_list:
        return result_list[0]
        
    return ExecutionPlan(
        id=str(uuid.uuid4()), goal_id=goal.get('id'), objective=objective,
        steps=[PlanStep(id="step_1", kind="logic", text=objective, expected_outcome="Fallback achieved")],
        created_at=time.time()
    )
