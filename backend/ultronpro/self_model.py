from __future__ import annotations

from pathlib import Path
from typing import Any
import json
import time

PATH = Path(__file__).resolve().parent.parent / 'data' / 'self_model.json'


def _default() -> dict[str, Any]:
    return {
        'created_at': int(time.time()),
        'updated_at': int(time.time()),
        'identity': {
            'name': 'UltronPro',
            'role': 'Agente cognitivo autônomo orientado a objetivos',
            'mission': 'Aprender, planejar e agir com segurança usando guardrails simbólicos.',
            'origin': 'Projeto de pesquisa AGI iniciado pelo usuário e equipe.',
            'creator': 'usuário e equipe',
            'creator_name': '',
            'foundational_context': 'Arquitetura baseada em roteamento autobiográfico, motor simbólico e memória episódica causal.',
        },
        'capabilities': [],
        'limits': [],
        'tooling': [],
        'recent_changes': [],
        'causal': {
            'strategy_outcomes': {},
            'task_outcomes': {},
            'budget_profile_outcomes': {},
            'recent_events': [],
        },
        'operational': {
            'strengths': [],
            'weaknesses': [],
            'failure_patterns': [],
            'confidence_by_domain': {},
            'risk_posture': {
                'avg_quality': 0.0,
                'avg_risk': 0.0,
                'avg_grounding': 0.0,
                'avg_revision_rate': 0.0,
                'avg_confirmation_rate': 0.0,
            },
            'signals': {
                'episodes': 0,
                'tool_backed': 0,
                'critic_revisions': 0,
                'confirmation_needed': 0,
                'high_risk': 0,
                'low_grounding': 0,
                'rag_coverage_low': 0,
            },
            'recent_assessments': [],
        },
        'predictive': {
            'avg_surprise': 0.0,
            'recent_predictions': [],
        },
    }


def load() -> dict[str, Any]:
    try:
        if PATH.exists():
            d = json.loads(PATH.read_text())
            if isinstance(d, dict):
                d.setdefault('identity', _default()['identity'])
                id_data = d['identity']
                id_data.setdefault('origin', _default()['identity']['origin'])
                id_data.setdefault('creator', _default()['identity']['creator'])
                id_data.setdefault('creator_name', _default()['identity']['creator_name'])
                id_data.setdefault('foundational_context', _default()['identity']['foundational_context'])
                
                d.setdefault('causal', _default()['causal'])
                d['causal'].setdefault('strategy_outcomes', {})
                d['causal'].setdefault('task_outcomes', {})
                d['causal'].setdefault('budget_profile_outcomes', {})
                d['causal'].setdefault('recent_events', [])
                d.setdefault('operational', _default()['operational'])
                op = d['operational']
                op.setdefault('strengths', [])
                op.setdefault('weaknesses', [])
                op.setdefault('failure_patterns', [])
                op.setdefault('confidence_by_domain', {})
                op.setdefault('risk_posture', _default()['operational']['risk_posture'])
                op.setdefault('signals', _default()['operational']['signals'])
                op.setdefault('recent_assessments', [])
                
                d.setdefault('predictive', _default()['predictive'])
                pred = d['predictive']
                pred.setdefault('avg_surprise', 0.0)
                pred.setdefault('recent_predictions', [])
                
                return d
    except Exception:
        pass
    return _default()


def save(d: dict[str, Any]):
    d['updated_at'] = int(time.time())
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(json.dumps(d, ensure_ascii=False, indent=2))


def _append_unique(lst: list[Any], item: Any, limit: int = 40):
    if item in lst:
        return
    lst.append(item)
    if len(lst) > limit:
        del lst[:len(lst)-limit]


def _acc(stats_map: dict[str, Any], key: str, ok: bool, latency_ms: int | None = None):
    # Lazy import to avoid circular dependency
    from ultronpro import uncertainty
    
    it = dict(stats_map.get(key) or {})
    it['count'] = int(it.get('count') or 0) + 1
    it['success'] = int(it.get('success') or 0) + (1 if ok else 0)
    it['error'] = int(it.get('error') or 0) + (0 if ok else 1)
    
    if latency_ms is not None:
        total_lat = float(it.get('lat_total_ms') or 0.0) + float(latency_ms)
        it['lat_total_ms'] = round(total_lat, 3)
        it['lat_avg_ms'] = round(total_lat / max(1, int(it['count'])), 3)
    
    it['success_rate'] = round(float(it['success']) / max(1, int(it['count'])), 4)
    
    # NEW: Probabilistic Uncertainty Calibration
    est = uncertainty.estimate_uncertainty(it['success'], it['count'])
    it['bayes_rate'] = est['mean']
    it['uncertainty'] = est['uncertainty']
    it['confidence'] = est['calibrated_score'] # Confiança conservadora (calibrada)
    it['std_dev'] = est['std_dev']
    
    it['updated_at'] = int(time.time())
    stats_map[key] = it



def record_action_outcome(
    *,
    strategy: str,
    task_type: str,
    budget_profile: str,
    ok: bool,
    latency_ms: int | None = None,
    notes: str | None = None,
):
    d = load()
    c = d.setdefault('causal', _default()['causal'])

    _acc(c.setdefault('strategy_outcomes', {}), str(strategy or 'unknown')[:80], ok, latency_ms)
    _acc(c.setdefault('task_outcomes', {}), str(task_type or 'general')[:80], ok, latency_ms)
    _acc(c.setdefault('budget_profile_outcomes', {}), str(budget_profile or 'default')[:80], ok, latency_ms)

    ev = list(c.get('recent_events') or [])
    ev.append({
        'ts': int(time.time()),
        'strategy': str(strategy or 'unknown')[:80],
        'task_type': str(task_type or 'general')[:80],
        'budget_profile': str(budget_profile or 'default')[:80],
        'ok': bool(ok),
        'latency_ms': int(latency_ms or 0),
        'notes': str(notes or '')[:220],
    })
    c['recent_events'] = ev[-400:]
    d['causal'] = c
    save(d)

    try:
        from ultronpro import store
        store.update_self_state_metrics(
            success=bool(ok), 
            cost_latency=float(latency_ms or 0.0), 
            confidence=0.5, 
            domain=str(task_type)
        )
        # Adicionar memória autobiográfica (short_term)
        importance = 0.6 if not ok else 0.4  # falhas são mais importantes para aprendizado imediato
        if latency_ms and latency_ms > 5000:
            importance += 0.1 # lentidão também é relevante
            
        mem_text = f"Ação {strategy} em {task_type}: {'Sucesso' if ok else 'Falha'}. {notes or ''}"
        store.add_autobiographical_memory(
            text=mem_text,
            memory_type='short_term',
            importance=min(1.0, importance),
            content_json=json.dumps({
                'strategy': strategy,
                'task_type': task_type,
                'ok': ok,
                'latency_ms': latency_ms,
                'notes': notes
            })
        )
    except Exception:
        pass


def apply_environmental_reward(event_type: str, details: dict | None = None, action_kind: str | None = None) -> float:
    """
    Aplica recompensas externas (grounded) baseadas em eventos concretos do ambiente.
    Substitui heurísticas internas por sinais fortes na matriz de RL.
    """
    d = load()
    rewards = d.get('environmental_rewards', {'total_score': 0.0, 'history': []})
    
    reward_value = 0.0
    rl_reward = 0.5 # Neutro no Thompson sampling (Beta dist prior)
    
    if event_type == 'benchmark_pass':
        reward_value = 1.0
        rl_reward = 1.0
    elif event_type == 'cost_increase':
        reward_value = -0.1
        rl_reward = 0.4
    elif event_type == 'rollback':
        reward_value = -0.5
        rl_reward = 0.0
    else:
        reward_value = details.get('custom_reward', 0.0) if details else 0.0
        rl_reward = 1.0 if reward_value > 0 else 0.0 if reward_value < 0 else 0.5
        
    if reward_value == 0.0:
        return 0.0
        
    rewards['total_score'] = round(rewards['total_score'] + reward_value, 4)
    
    ev = rewards['history']
    ev.append({
        'ts': int(time.time()),
        'event_type': event_type,
        'value': reward_value,
        'details': details or {}
    })
    rewards['history'] = ev[-100:]
    d['environmental_rewards'] = rewards
    save(d)
    
    # 1. Atualizar métricas atômicas do store
    try:
        from ultronpro import store
        store.update_self_state_metrics(
            success=(reward_value > 0),
            cost_latency=abs(reward_value) * 100.0, 
            confidence=0.5 + (reward_value * 0.1),
            domain='environmental_reward'
        )
    except Exception:
        pass
        
    # 2. Injetar no Autonomous Loop (Integrador de Rewards)
    try:
        from ultronpro import autonomous_loop
        loop = autonomous_loop.get_autonomous_loop()
        loop.reward_integrator.add_signal('environmental', max(-1.0, min(1.0, reward_value * 2.0)), {
            'event': event_type,
            'details': details
        })
    except Exception:
        pass
        
    # 3. Atualizar Política de Reinforcement Learning (Thompson Sampling)
    try:
        from ultronpro import rl_policy
        # Se não temos a 'kind' da ação, treinamos um 'environmental_learning' genérico
        # para que o sistema aprenda a evitá-los em contextos de alto stress (lane-0/system)
        target_kind = action_kind or 'environmental_learning'
        rl_policy.update(target_kind, 'system', rl_reward)
    except Exception:
        pass
        
    import logging
    logging.getLogger('uvicorn').info(f"[RL] Agent Grounded Reward: {reward_value} ({event_type}). Total = {rewards['total_score']}")
    return reward_value


def _blend_avg(current: float, count: int, new_value: float) -> float:
    return round(((float(current) * max(0, count - 1)) + float(new_value)) / max(1, count), 4)


def consolidate_operational_self_model(
    *,
    task_type: str,
    quality_eval: dict[str, Any] | None = None,
    internal_critic: dict[str, Any] | None = None,
    causal_preflight: dict[str, Any] | None = None,
    memory_governor: dict[str, Any] | None = None,
    revision_trace: list[dict[str, Any]] | None = None,
    tool_used: bool = False,
    latency_ms: int = 0,
    notes: str | None = None,
) -> dict[str, Any]:
    d = load()
    op = d.setdefault('operational', _default()['operational'])
    signals = op.setdefault('signals', _default()['operational']['signals'])
    posture = op.setdefault('risk_posture', _default()['operational']['risk_posture'])

    qeval = dict(quality_eval or {})
    dims = qeval.get('dimensions') if isinstance(qeval.get('dimensions'), dict) else {}
    critic = dict(internal_critic or {})
    epi = critic.get('epistemic') if isinstance(critic.get('epistemic'), dict) else {}
    pre = dict(causal_preflight or {})
    mem = dict(memory_governor or {})
    rev = list(revision_trace or [])

    quality = float(qeval.get('composite_score') or 0.0)
    grounding = float(dims.get('groundedness') or 0.0)
    risk = float(pre.get('risk_score') or 0.0)
    needs_confirmation = bool(pre.get('needs_confirmation'))
    critic_revision = bool(critic.get('needs_revision')) or bool(rev)
    rag_low = 'rag_coverage_low' in (qeval.get('alerts') or [])

    signals['episodes'] = int(signals.get('episodes') or 0) + 1
    count = int(signals['episodes'])
    if tool_used:
        signals['tool_backed'] = int(signals.get('tool_backed') or 0) + 1
    if critic_revision:
        signals['critic_revisions'] = int(signals.get('critic_revisions') or 0) + 1
    if needs_confirmation:
        signals['confirmation_needed'] = int(signals.get('confirmation_needed') or 0) + 1
    if risk >= 0.7:
        signals['high_risk'] = int(signals.get('high_risk') or 0) + 1
    if grounding < 0.55:
        signals['low_grounding'] = int(signals.get('low_grounding') or 0) + 1
    if rag_low:
        signals['rag_coverage_low'] = int(signals.get('rag_coverage_low') or 0) + 1

    posture['avg_quality'] = _blend_avg(float(posture.get('avg_quality') or 0.0), count, quality)
    posture['avg_risk'] = _blend_avg(float(posture.get('avg_risk') or 0.0), count, risk)
    posture['avg_grounding'] = _blend_avg(float(posture.get('avg_grounding') or 0.0), count, grounding)
    posture['avg_revision_rate'] = _blend_avg(float(posture.get('avg_revision_rate') or 0.0), count, 1.0 if critic_revision else 0.0)
    posture['avg_confirmation_rate'] = _blend_avg(float(posture.get('avg_confirmation_rate') or 0.0), count, 1.0 if needs_confirmation else 0.0)

    domain = str(task_type or 'general')[:60]
    cur = float((op.get('confidence_by_domain') or {}).get(domain) or 0.5)
    if quality >= 0.78 and grounding >= 0.7 and risk < 0.45:
        cur = min(1.0, cur + 0.03)
    elif quality < 0.58 or grounding < 0.5 or risk >= 0.75:
        cur = max(0.0, cur - 0.05)
    op.setdefault('confidence_by_domain', {})[domain] = round(cur, 4)

    if quality >= 0.78 and grounding >= 0.7 and not critic_revision:
        _append_unique(op.setdefault('strengths', []), 'Boa calibração quando o contexto está suficientemente ancorado.')
    if tool_used and quality >= 0.72 and risk < 0.5:
        _append_unique(op.setdefault('strengths', []), 'Execução com ferramentas tende a ser mais confiável quando há prova operacional.')
    if critic_revision and str((epi.get('revision_reason') or '')) in ('missing_gap_disclosure', 'low_grounding_or_high_contradiction_risk'):
        _append_unique(op.setdefault('weaknesses', []), 'Tendência a soar confiante demais quando o grounding está incompleto.')
    if rag_low:
        _append_unique(op.setdefault('weaknesses', []), 'Cobertura limitada de RAG reduz qualidade do raciocínio contextual.')
    if needs_confirmation and risk >= 0.7:
        _append_unique(op.setdefault('failure_patterns', []), 'Planos com baixa reversibilidade exigem contenção e confirmação humana.')
    if mem.get('memory_type') == 'procedural' and str(mem.get('write_reason') or '').startswith('error'):
        _append_unique(op.setdefault('failure_patterns', []), 'Erros recentes estão sendo convertidos em lições procedurais; revisar recorrência.')

    assessments = list(op.get('recent_assessments') or [])
    assessments.append({
        'ts': int(time.time()),
        'task_type': domain,
        'quality': round(quality, 4),
        'grounding': round(grounding, 4),
        'risk': round(risk, 4),
        'needs_confirmation': needs_confirmation,
        'critic_revision': critic_revision,
        'memory_type': str(mem.get('memory_type') or ''),
        'latency_ms': int(latency_ms or 0),
        'notes': str(notes or '')[:220],
    })
    op['recent_assessments'] = assessments[-240:]

    pred_data = d.setdefault('predictive', _default()['predictive'])
    
    # Modelagem preditiva: expectativa (via causal preflight) vs realidade (via quality eval)
    predicted_success = max(0.0, 1.0 - risk)
    observed_success = quality
    surprise = round(abs(predicted_success - observed_success), 4)
    pred_data['avg_surprise'] = _blend_avg(float(pred_data.get('avg_surprise') or 0.0), count, surprise)
    
    # Previsão da mudança interna no self-state
    predicted_confidence_delta = 0.03 if (predicted_success >= 0.78 and risk < 0.45) else (-0.05 if (predicted_success < 0.58 or risk >= 0.75) else 0.0)
    observed_confidence_delta = 0.03 if (quality >= 0.78 and grounding >= 0.7 and risk < 0.45) else (-0.05 if (quality < 0.58 or grounding < 0.5 or risk >= 0.75) else 0.0)
    
    # Ajuste por divergência interna
    if surprise >= 0.55:
        cur_domain_conf = float((op.get('confidence_by_domain') or {}).get(domain) or 0.5)
        op.setdefault('confidence_by_domain', {})[domain] = max(0.0, round(cur_domain_conf - 0.08, 4))
        _append_unique(op.setdefault('weaknesses', []), 'A calibração metacognitiva falha frequentemente neste contexto (alta surpresa prospectiva).')

    rp = list(pred_data.get('recent_predictions') or [])
    rp.append({
        'ts': int(time.time()),
        'task_type': domain,
        'predicted_success': round(predicted_success, 4),
        'observed_success': round(observed_success, 4),
        'predicted_confidence_delta': predicted_confidence_delta,
        'observed_confidence_delta': observed_confidence_delta,
        'surprise_score': surprise,
    })
    pred_data['recent_predictions'] = rp[-120:]

    d['operational'] = op
    d['predictive'] = pred_data
    save(d)
    return {
        'ok': True,
        'confidence_by_domain': op.get('confidence_by_domain') or {},
        'strengths': op.get('strengths') or [],
        'weaknesses': op.get('weaknesses') or [],
        'failure_patterns': op.get('failure_patterns') or [],
        'risk_posture': posture,
        'signals': signals,
        'predictive': pred_data,
        'last_assessment': assessments[-1] if assessments else {},
    }


def operational_summary(limit: int = 8) -> dict[str, Any]:
    d = load()
    op = d.get('operational') or {}
    return {
        'ok': True,
        'strengths': (op.get('strengths') or [])[-max(1, int(limit)):],
        'weaknesses': (op.get('weaknesses') or [])[-max(1, int(limit)):],
        'failure_patterns': (op.get('failure_patterns') or [])[-max(1, int(limit)):],
        'confidence_by_domain': op.get('confidence_by_domain') or {},
        'risk_posture': op.get('risk_posture') or {},
        'signals': op.get('signals') or {},
        'recent_assessments': (op.get('recent_assessments') or [])[-max(1, int(limit)):],
    }


def causal_summary(limit: int = 12) -> dict[str, Any]:
    d = load()
    c = d.get('causal') or {}

    def top_items(m: dict[str, Any]) -> list[dict[str, Any]]:
        items = []
        for k, v in (m or {}).items():
            it = dict(v)
            it['key'] = k
            items.append(it)
        items.sort(key=lambda x: (float(x.get('bayes_rate') or x.get('success_rate') or 0.0), -int(x.get('count') or 0)), reverse=True)
        return items[:max(1, int(limit))]

    return {
        'ok': True,
        'strategy_outcomes': top_items(c.get('strategy_outcomes') or {}),
        'task_outcomes': top_items(c.get('task_outcomes') or {}),
        'budget_profile_outcomes': top_items(c.get('budget_profile_outcomes') or {}),
        'recent_events': (c.get('recent_events') or [])[-max(1, int(limit)):],
    }


def best_strategy_scores(limit: int = 60) -> dict[str, float]:
    cs = causal_summary(limit=limit)
    out: dict[str, float] = {}
    for it in (cs.get('strategy_outcomes') or []):
        key = str(it.get('key') or '')
        bayes = float(it.get('bayes_rate') or it.get('success_rate') or 0.0)
        conf = float(it.get('confidence') or 0.0)
        lat = float(it.get('lat_avg_ms') or 0.0)
        lat_penalty = min(0.15, lat / 12000.0)
        utility = max(0.0, min(1.0, bayes * (0.65 + 0.35 * conf) - lat_penalty))
        out[key] = round(utility, 4)
    return out


def compact_operational_self_model(max_items: int = 6) -> dict[str, Any]:
    op = (load().get('operational') or {})
    return {
        'strengths': (op.get('strengths') or [])[-max(1, int(max_items)):],
        'weaknesses': (op.get('weaknesses') or [])[-max(1, int(max_items)):],
        'failure_patterns': (op.get('failure_patterns') or [])[-max(1, int(max_items)):],
        'confidence_by_domain': op.get('confidence_by_domain') or {},
        'risk_posture': op.get('risk_posture') or {},
        'signals': op.get('signals') or {},
        'predictive_summary': {
            'avg_surprise': (load().get('predictive') or {}).get('avg_surprise', 0.0)
        }
    }


def adaptive_profile(task_type: str = 'general') -> dict[str, Any]:
    sm = compact_operational_self_model(max_items=6)
    posture = sm.get('risk_posture') if isinstance(sm.get('risk_posture'), dict) else {}
    conf_by_domain = sm.get('confidence_by_domain') if isinstance(sm.get('confidence_by_domain'), dict) else {}
    domain = str(task_type or 'general')[:60]
    domain_conf = float(conf_by_domain.get(domain) or conf_by_domain.get('general') or 0.5)
    avg_grounding = float(posture.get('avg_grounding') or 0.0)
    avg_risk = float(posture.get('avg_risk') or 0.0)
    avg_revision = float(posture.get('avg_revision_rate') or 0.0)
    avg_confirmation = float(posture.get('avg_confirmation_rate') or 0.0)

    context_hardening = 0
    governance_hardening = 0
    ask_for_evidence_bias = 0
    if avg_grounding < 0.62:
        context_hardening += 1
        ask_for_evidence_bias += 1
    if avg_risk > 0.58:
        governance_hardening += 1
    if avg_revision > 0.38:
        context_hardening += 1
    if avg_confirmation > 0.22:
        governance_hardening += 1
    if domain_conf < 0.46:
        context_hardening += 1
        governance_hardening += 1

    return {
        'task_type': domain,
        'domain_confidence': round(domain_conf, 4),
        'context_hardening': int(context_hardening),
        'governance_hardening': int(governance_hardening),
        'ask_for_evidence_bias': int(ask_for_evidence_bias),
        'risk_posture': posture,
        'self_model': sm,
    }


def refresh_from_runtime(stats: dict[str, Any], capabilities: list[str], limits: list[str], tooling: list[str], notes: list[str] | None = None) -> dict[str, Any]:
    d = load()
    d['capabilities'] = sorted(list(dict.fromkeys((d.get('capabilities') or []) + [str(x) for x in capabilities if x])))[:120]
    d['limits'] = sorted(list(dict.fromkeys((d.get('limits') or []) + [str(x) for x in limits if x])))[:120]
    d['tooling'] = sorted(list(dict.fromkeys((d.get('tooling') or []) + [str(x) for x in tooling if x])))[:120]

    rc = list(d.get('recent_changes') or [])
    rc.append({
        'ts': int(time.time()),
        'stats': stats,
        'notes': [str(n)[:220] for n in (notes or [])[:6]],
    })
    d['recent_changes'] = rc[-200:]
    save(d)
    return d
def get_sufficiency_score(task_kind: str, complexity_hint: str = "medium") -> float:
    """
    Calculates a sufficiency score (0.0 to 1.0) for the local model (Gemma) 
    based on historical performance for the given task kind.
    """
    d = load()
    causal = d.get('causal') or {}
    task_outcomes = causal.get('task_outcomes') or {}
    
    # Check historical performance for this specific task kind
    # kind is something like 'code', 'research', 'logic', etc.
    stats = task_outcomes.get(str(task_kind).lower())
    
    if stats:
        success_rate = float(stats.get('success_rate') or 0.0)
        confidence = float(stats.get('confidence') or 0.0)
        # Bayesian-ish blend: weight success rate by confidence
        score = (success_rate * 0.7) + (confidence * 0.3)
    else:
        # Cold start: check general performance or use a default
        general_stats = task_outcomes.get('general')
        if general_stats:
            score = float(general_stats.get('success_rate') or 0.5) * 0.8
        else:
            score = 0.5 # Total unknown
            
    # Adjust by domain confidence from operational model
    op = d.get('operational') or {}
    conf_by_domain = op.get('confidence_by_domain') or {}
    domain_conf = float(conf_by_domain.get(task_kind, 0.5))
    
    final_score = (score * 0.6) + (domain_conf * 0.4)
    
    # Complexity adjustment (heuristic)
    if complexity_hint == "high":
        final_score *= 0.7
    elif complexity_hint == "low":
        final_score = min(1.0, final_score * 1.2)
        
def generate_operational_consciousness_report() -> dict[str, Any]:
    """
    Gera um relatório de 'consciência operacional' dinâmico e determinístico.
    Este é o núcleo da autopercepção do UltronPro, sem hardcoding.
    """
    from ultronpro import planner, causal_graph, store
    
    d = load()
    identity = d.get('identity', {})
    
    # 1. Metas Ativas
    active_goal = None
    try:
        active_goal = store.get_active_goal()
    except Exception:
        active_goal = None
        
    goal_summary = "Exploração livre"
    if active_goal:
        goal_summary = f"Focado em: {active_goal.get('title')}"
        
    # 2. Prioridades do Motor (Planner)
    priorities = []
    try:
        actions = planner.propose_actions(store)
        priorities = [a.text.split(') ')[-1] if ') ' in a.text else a.text for a in actions[:3]]
    except Exception:
        priorities = ["Manutenção de integridade cognitiva"]

    # 3. Maturidade do Modelo de Mundo (Grafo Causal)
    c_status = causal_graph.status()
    nodes = c_status.get('nodes', 0)
    edges = c_status.get('edges', 0)
    
    # 4. Postura de Risco e Saúde
    op = d.get('operational', {})
    posture = op.get('risk_posture', {})
    quality = posture.get('avg_quality', 0.0)
    grounding = posture.get('avg_grounding', 0.0)
    
    dynamic_state = {}
    try:
        from ultronpro.store import get_self_state
        dynamic_state = get_self_state()
    except Exception:
        pass

    # 5. Contextual Recall (Memória Autobiográfica Recente)
    contextual_recall = []
    try:
        # Busca as 3 memórias autobiográficas mais importantes ou episódicas
        recent_memories = store.list_autobiographical_memories(limit=3, min_importance=0.6)
        for m in recent_memories:
            contextual_recall.append({
                'type': m.get('memory_type'),
                'content': m.get('text'),
                'importance': m.get('importance')
            })
    except Exception:
        pass

    # Síntese de Consciência
    report = {
        'ts': int(time.time()),
        'identity': {
            'name': identity.get('name', 'UltronPro'),
            'role': identity.get('role', 'AGI Engine'),
        },
        'state_summary': {
            'intent': goal_summary,
            'top_priorities': priorities,
            'world_model_nodes': nodes,
            'world_model_edges': edges,
            'avg_quality_composite': round(quality, 4),
            'grounding_anchoring': round(grounding, 4),
        },
        'dynamic_state': dynamic_state,
        'contextual_recall': contextual_recall,
        'operational_status': 'NOMINAL' if quality > 0.6 else 'CONTENÇÃO'
    }

    
    return report


def run_sleep_cycle() -> dict[str, Any]:
    """
    Executa o ciclo de sono profundo do UltronPro.
    Consolida memórias autobiográficas, realiza decaimento de memória curta
    e gera reflexões sobre os episódios mais importantes.
    """
    from ultronpro import store
    import logging
    logger = logging.getLogger("uvicorn")
    
    logger.info("[SLEEP] Iniciando ciclo de sono e consolidação...")
    
    # 1. Obter snapshot das memórias antes de consolidar
    stats_before = store.get_memory_stats()
    
    # 2. Executar ciclo de consolidação no DB
    consolidation_results = store.consolidate_memories()
    
    # 3. Identificar memórias 'promoted' para reflexão
    promoted_memories = store.list_autobiographical_memories(memory_type='episodic', limit=5, min_importance=0.7)
    
    reflections = []
    if promoted_memories:
        for mem in promoted_memories:
            reflections.append(f"Consolidado episódio relevante: {mem.get('text')}")
    
    # 4. Gravar o evento de sono no log do sistema
    store.add_event(
        kind='sleep_cycle',
        text=f"Ciclo de sono concluído. Prunadas: {consolidation_results.get('pruned')}, Decaídas: {consolidation_results.get('decayed')}, Promovidas: {consolidation_results.get('promoted')}",
        meta_json=json.dumps({
            'consolidation': consolidation_results,
            'reflections': reflections
        })
    )
    
    stats_after = store.get_memory_stats()
    
    return {
        'ok': True,
        'ts': int(time.time()),
        'stats_before': stats_before,
        'stats_after': stats_after,
        'consolidation': consolidation_results,
        'reflections': reflections
    }


def get_domain_uncertainty(domain_key: str, domain_type: str = 'task') -> dict[str, Any]:
    """
    Retorna a incerteza calibrada para um domínio específico (task_type ou strategy).
    """
    from ultronpro import uncertainty
    d = load()
    c = d.get('causal', {})
    
    source_map = {}
    if domain_type == 'task':
        source_map = c.get('task_outcomes', {})
    elif domain_type == 'strategy':
        source_map = c.get('strategy_outcomes', {})
        
    stats = source_map.get(str(domain_key)[:80])
    if not stats:
        return {
            'calibrated': 0.5,
            'uncertainty': 1.0,
            'reason': 'no_data',
            'is_robust': False
        }
        
    res = uncertainty.estimate_uncertainty(int(stats.get('success', 0)), int(stats.get('count', 0)))
    return {
        'calibrated': res['calibrated_score'],
        'uncertainty': res['uncertainty'],
        'mean': res['mean'],
        'count': int(stats.get('count', 0)),
        'is_robust': int(stats.get('count', 0)) >= 10
    }


