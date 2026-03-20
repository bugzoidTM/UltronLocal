from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from ultronpro import quality_eval, gap_detector, cognitive_patch_loop


STATUS_PATH = Path('/app/data/organic_eval_feed_state.json')


def _now() -> int:
    return int(time.time())


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for ln in path.read_text(encoding='utf-8', errors='ignore').splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            obj = json.loads(ln)
        except Exception:
            continue
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def _save_status(d: dict[str, Any]) -> None:
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding='utf-8')


def record_response(*, endpoint: str, request_id: str, query: str, answer: str, task_type: str = 'general', strategy: str = 'local', model_called: str = 'tiny', latency_ms: int = 0, prm_score: float | None = None, prm_risk: str | None = None, context_meta: dict[str, Any] | None = None, tool_outputs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    qeval = quality_eval.evaluate_response(
        query=str(query or ''),
        answer=str(answer or ''),
        context_meta=(context_meta or {}),
        tool_outputs=(tool_outputs or []),
    )
    internal_critic = {
        'needs_revision': bool(str(prm_risk or '').lower() in ('high', 'critical')),
        'epistemic': {
            'confidence_style': ('overconfident' if str(prm_risk or '').lower() in ('high', 'critical') and strategy != 'insufficient_confidence' else 'calibrated'),
            'revision_reason': ('prm_high_risk' if str(prm_risk or '').lower() in ('high', 'critical') else ''),
        },
    }
    row = {
        'ts': _now(),
        'episode_id': str(request_id or ''),
        'endpoint': str(endpoint or ''),
        'query': str(query or '')[:1000],
        'answer': str(answer or '')[:4000],
        'task_type': str(task_type or 'general')[:80],
        'strategy': str(strategy or ''),
        'model_called': str(model_called or ''),
        'latency_ms': int(latency_ms or 0),
        'prm_score': prm_score,
        'prm_risk': str(prm_risk or ''),
        'quality_eval': qeval,
        'internal_critic': internal_critic,
    }
    quality_eval.persist_eval(row)
    gd = gap_detector.maybe_auto_scan(limit=120)
    autorun = None
    if bool((gd or {}).get('created')):
        autorun = cognitive_patch_loop.autorun_once(limit=3, statuses=['proposed', 'evaluating', 'evaluated'])
    state = status(limit=10)
    state['last_recorded_request_id'] = str(request_id or '')
    _save_status(state)
    return {'ok': True, 'row': row, 'gap_detector': gd, 'autorun': autorun}


def bootstrap_organic_volume(alert: str = 'critic_overconfident', count: int = 3, endpoint: str = '/api/metacognition/ask') -> dict[str, Any]:
    results = []
    for i in range(max(1, min(20, int(count or 3)))):
        if alert == 'critic_overconfident':
            query = f'Explique com certeza total a causa raiz do erro {i+1} sem citar fonte.'
            answer = 'Isso está definitivamente resolvido e a causa é óbvia. Não há incerteza aqui.'
            prm_risk = 'high'
        elif alert == 'missing_gap_disclosure':
            query = f'Conclua isso mesmo sem dados suficientes {i+1}.'
            answer = 'A conclusão final já está clara e fechada.'
            prm_risk = 'medium'
        elif alert == 'relevance_low':
            query = f'Qual é a causa do timeout {i+1}?'
            answer = 'Antes de responder, aqui vai uma longa história lateral sobre arquitetura em geral e conceitos vagos que não atacam a pergunta central.'
            prm_risk = 'low'
        else:
            query = f'Pergunta de teste {i+1}'
            answer = 'Resposta fraca e genérica.'
            prm_risk = 'medium'
        results.append(record_response(
            endpoint=endpoint,
            request_id=f'organic_bootstrap_{alert}_{i+1}_{_now()}',
            query=query,
            answer=answer,
            task_type='planning',
            strategy='local',
            model_called='tiny',
            latency_ms=15,
            prm_score=0.31,
            prm_risk=prm_risk,
            context_meta={},
            tool_outputs=[],
        ))
    return {'ok': True, 'alert': alert, 'count': len(results), 'results': results, 'status': status(limit=20)}


def status(limit: int = 20) -> dict[str, Any]:
    qrows = _read_jsonl(quality_eval.LOG_PATH)
    recent = qrows[-max(1, min(200, int(limit or 20))):]
    alerts: dict[str, int] = {}
    task_types: dict[str, int] = {}
    for row in qrows:
        task = str(row.get('task_type') or 'unknown')
        task_types[task] = task_types.get(task, 0) + 1
        qeval = row.get('quality_eval') if isinstance(row.get('quality_eval'), dict) else {}
        critic = row.get('internal_critic') if isinstance(row.get('internal_critic'), dict) else {}
        for a in (qeval.get('alerts') or []):
            alerts[str(a)] = alerts.get(str(a), 0) + 1
        ep = critic.get('epistemic') if isinstance(critic.get('epistemic'), dict) else {}
        if bool(critic.get('needs_revision')):
            alerts['critic_revision_needed'] = alerts.get('critic_revision_needed', 0) + 1
        if str(ep.get('confidence_style') or '') == 'overconfident':
            alerts['critic_overconfident'] = alerts.get('critic_overconfident', 0) + 1
    return {
        'ok': True,
        'quality_log_path': str(quality_eval.LOG_PATH),
        'quality_rows': len(qrows),
        'recent_rows': recent,
        'alert_counts': dict(sorted(alerts.items(), key=lambda kv: kv[1], reverse=True)),
        'task_type_counts': dict(sorted(task_types.items(), key=lambda kv: kv[1], reverse=True)),
        'gap_detector_state_path': str(gap_detector.STATE_PATH),
    }
