from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

LOG_PATH = Path('/app/data/memory_governor.jsonl')


STABLE_PREFERENCE_TERMS = [
    'prefere', 'preferência', 'preferencia', 'gosta', 'não gosta', 'nao gosta',
    'sempre', 'nunca', 'costuma', 'tom de voz', 'chamar de',
]
DECISION_TERMS = [
    'decisão', 'decisao', 'vamos', 'a partir de agora', 'diretriz', 'foco', 'parar', 'remover',
]
ERROR_TERMS = [
    'erro', 'falha', 'bug', 'quebrou', 'incidente', 'regressão', 'regressao',
]


def _clip01(v: float) -> float:
    return max(0.0, min(1.0, float(v)))


def _contains_any(text: str, terms: list[str]) -> bool:
    t = str(text or '').lower()
    return any(x in t for x in terms)


def classify_writeback(*, query: str, answer: str, task_type: str = 'general', quality_eval: dict[str, Any] | None = None, internal_critic: dict[str, Any] | None = None, planner_context: dict[str, Any] | None = None, steps_executed: list[dict[str, Any]] | None = None, causal_preflight: dict[str, Any] | None = None) -> dict[str, Any]:
    q = str(query or '').strip()
    a = str(answer or '').strip()
    ql = q.lower()
    al = a.lower()
    qeval = dict(quality_eval or {})
    critic = dict(internal_critic or {})
    planner = dict(planner_context or {})
    steps = list(steps_executed or [])
    preflight = dict(causal_preflight or {})

    fallback = planner.get('context_fallback') if isinstance(planner.get('context_fallback'), dict) else {}
    rag_div = ((planner.get('rag_route') or {}).get('diversity') if isinstance(planner.get('rag_route'), dict) else {}) or {}
    composite = float(qeval.get('composite_score') or 0.0)
    critique_needs_revision = bool(critic.get('needs_revision'))
    tool_used = bool(steps)
    preflight_risk = float(preflight.get('risk_score') or 0.0)
    needs_confirmation = bool(preflight.get('needs_confirmation'))

    write = False
    memory_type = 'episodic'
    scope = 'task_local'
    ttl_hint = 'short'
    write_reason = 'routine_episode'
    confidence = 0.58

    if _contains_any(f'{q} {a}', DECISION_TERMS):
        write = True
        memory_type = 'semantic'
        scope = 'project'
        ttl_hint = 'long'
        write_reason = 'decision_or_direction_change'
        confidence = 0.86
    elif _contains_any(f'{q} {a}', STABLE_PREFERENCE_TERMS):
        write = True
        memory_type = 'preference'
        scope = 'global'
        ttl_hint = 'long'
        write_reason = 'stable_preference'
        confidence = 0.84
    elif _contains_any(f'{q} {a}', ERROR_TERMS) or critique_needs_revision or preflight_risk >= 0.7:
        write = True
        memory_type = 'procedural'
        scope = 'project'
        ttl_hint = 'medium'
        write_reason = 'error_revision_or_high_risk_lesson'
        confidence = 0.74
    elif tool_used:
        write = True
        memory_type = 'episodic'
        scope = 'project'
        ttl_hint = 'medium'
        write_reason = 'tool_backed_episode'
        confidence = 0.72
    elif composite >= 0.72:
        write = True
        memory_type = 'episodic'
        scope = 'task_local'
        ttl_hint = 'short'
        write_reason = 'high_quality_episode'
        confidence = 0.68

    if needs_confirmation and memory_type == 'episodic':
        memory_type = 'procedural'
        scope = 'project'
        ttl_hint = 'medium'
        write_reason = 'confirmation_gate_lesson'
        confidence = max(confidence, 0.71)

    if bool(fallback.get('needed')) and composite < 0.60:
        write = False
        write_reason = 'insufficient_grounding_do_not_promote'
        confidence = min(confidence, 0.34)

    if float(rag_div.get('coverage_score') or 0.0) < 0.35 and memory_type in ('semantic', 'procedural'):
        confidence = min(confidence, 0.52)

    fact = ''
    hypothesis = ''
    plan = ''
    interpretation = ''

    if memory_type == 'semantic':
        fact = a[:400] or q[:400]
        interpretation = 'Diretriz/decisão relevante para o projeto.'
    elif memory_type == 'preference':
        fact = a[:300] or q[:300]
        interpretation = 'Preferência estável detectada.'
    elif memory_type == 'procedural':
        fact = f'task_type={task_type}; quality={round(composite,4)}; critic_revision={critique_needs_revision}'
        hypothesis = 'Existe lição operacional reutilizável para evitar repetição do erro.'
        interpretation = 'Aprendizado procedural derivado de revisão, erro ou risco.'
    else:
        fact = q[:240]
        plan = a[:320]
        interpretation = 'Episódio útil para continuidade local do trabalho.'

    return {
        'should_write': write,
        'memory_type': memory_type,
        'scope': scope,
        'ttl_hint': ttl_hint,
        'write_reason': write_reason,
        'confidence': round(_clip01(confidence), 4),
        'fact': fact,
        'hypothesis': hypothesis,
        'plan': plan,
        'interpretation': interpretation,
        'signals': {
            'tool_used': tool_used,
            'composite_score': round(_clip01(composite), 4),
            'critic_needs_revision': critique_needs_revision,
            'fallback_needed': bool(fallback.get('needed')),
            'rag_coverage_score': round(_clip01(float(rag_div.get('coverage_score') or 0.0)), 4),
            'preflight_risk': round(_clip01(preflight_risk), 4),
            'needs_confirmation': needs_confirmation,
        },
    }


def persist_decision(row: dict[str, Any]) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(row or {})
    payload['ts'] = int(time.time())
    with LOG_PATH.open('a', encoding='utf-8') as f:
        f.write(json.dumps(payload, ensure_ascii=False) + '\n')
