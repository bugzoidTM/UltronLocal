from __future__ import annotations

from pathlib import Path
from typing import Any
import json
import time
import random
import re

from ultronpro import llm, economic

PATH = Path('/app/data/plasticity_runtime.json')
DISTILL_PATH = Path('/app/data/memory_distillations.json')


def _default() -> dict[str, Any]:
    return {
        'updated_at': int(time.time()),
        'feedback': [],
        'replays': [],
        'distillations': [],
        'policy_adjustments': [],
    }


def _load() -> dict[str, Any]:
    if PATH.exists():
        try:
            d = json.loads(PATH.read_text(encoding='utf-8'))
            if isinstance(d, dict):
                d.setdefault('feedback', [])
                d.setdefault('replays', [])
                d.setdefault('distillations', [])
                d.setdefault('policy_adjustments', [])
                return d
        except Exception:
            pass
    return _default()


def _save(d: dict[str, Any]) -> None:
    d['updated_at'] = int(time.time())
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding='utf-8')


def _save_distill(items: list[dict[str, Any]]) -> None:
    DISTILL_PATH.parent.mkdir(parents=True, exist_ok=True)
    DISTILL_PATH.write_text(json.dumps(items[-300:], ensure_ascii=False, indent=2), encoding='utf-8')


def _text_of_result(r: dict[str, Any]) -> str:
    parts = [
        str(r.get('subject') or ''),
        str(r.get('predicate') or ''),
        str(r.get('object') or ''),
        str(r.get('text') or ''),
        str(r.get('content') or ''),
        str(r.get('title') or ''),
    ]
    return ' '.join([p for p in parts if p]).strip().lower()


def rerank_with_hard_negatives(query: str, results: list[dict[str, Any]], top_k: int = 10) -> list[dict[str, Any]]:
    q = (query or '').lower().strip()
    toks = [t for t in re.split(r'\W+', q) if len(t) >= 3]
    neg_markers = {'nao', 'não', 'sem', 'evitar', 'exceto', 'except', 'without', 'avoid'}

    hard_negs = set()
    for i, t in enumerate(toks):
        if t in neg_markers and i + 1 < len(toks):
            hard_negs.add(toks[i + 1])

    scored = []
    for r in results or []:
        txt = _text_of_result(r)
        if not txt:
            continue
        pos = sum(1 for t in toks if t in txt)
        neg_hit = sum(1 for n in hard_negs if n in txt)
        score = float(pos) - (1.4 * float(neg_hit))
        rr = dict(r)
        rr['_plasticity_score'] = round(score, 4)
        rr['_hard_negative_hits'] = int(neg_hit)
        scored.append(rr)

    scored.sort(key=lambda x: (float(x.get('_plasticity_score') or 0.0), -int(x.get('_hard_negative_hits') or 0)), reverse=True)
    return scored[:max(1, int(top_k or 10))]


def record_feedback(task_type: str, profile: str, success: bool, latency_ms: int, hallucination: bool = False, note: str | None = None) -> dict[str, Any]:
    d = _load()
    reward = economic.reward(ok=bool(success), latency_ms=int(latency_ms), reliability=(0.0 if hallucination else 0.85))
    if hallucination:
        reward = max(0.0, float(reward) - 0.35)

    up = economic.update(task_type=task_type or 'general', profile=profile or 'balanced', reward_value=reward, ok=bool(success and not hallucination), latency_ms=int(latency_ms))

    fb = {
        'ts': int(time.time()),
        'task_type': str(task_type or 'general')[:48],
        'profile': str(profile or 'balanced')[:16],
        'success': bool(success),
        'hallucination': bool(hallucination),
        'latency_ms': int(latency_ms or 0),
        'reward': float(reward),
        'note': str(note or '')[:280],
    }
    arr = list(d.get('feedback') or [])
    arr.append(fb)
    d['feedback'] = arr[-1200:]

    # policy adjustment trace (runtime policy-gradient-ish)
    adj = list(d.get('policy_adjustments') or [])
    adj.append({'ts': int(time.time()), 'task_type': fb['task_type'], 'profile': fb['profile'], 'reward': reward, 'ok': bool(success and not hallucination), 'epsilon': (up or {}).get('epsilon')})
    d['policy_adjustments'] = adj[-1200:]

    _save(d)
    return {'ok': True, 'feedback': fb, 'economic': up}


def replay_tick(store_db, limit: int = 5) -> dict[str, Any]:
    d = _load()
    fb = list(d.get('feedback') or [])
    hard = [x for x in fb if (not x.get('success')) or bool(x.get('hallucination'))]
    sample = hard[-80:]
    random.shuffle(sample)
    chosen = sample[:max(1, min(12, int(limit or 5)))]

    actions = 0
    for it in chosen:
        note = str(it.get('note') or '').strip() or f"failure pattern in {it.get('task_type')}"
        q = f"[active-learning] Como evitar falha: {note[:220]}? Propor teste objetivo e critério de aceitação."
        try:
            store_db.add_questions([{'question': q, 'priority': 6, 'context': 'active_learning_replay'}])
            actions += 1
        except Exception:
            pass

    rep = {'ts': int(time.time()), 'picked': len(chosen), 'enqueued_questions': actions}
    arr = list(d.get('replays') or [])
    arr.append(rep)
    d['replays'] = arr[-600:]
    _save(d)
    return {'ok': True, **rep}


def distill_memory(store_db, max_items: int = 20) -> dict[str, Any]:
    events = store_db.list_events(since_id=0, limit=max(20, int(max_items or 20)))
    experiences = store_db.list_experiences(limit=max(20, int(max_items or 20)))

    lines = []
    for e in events[-max_items:]:
        lines.append(f"event[{e.get('kind')}]: {str(e.get('text') or '')[:160]}")
    for ex in experiences[-max_items:]:
        lines.append(f"exp[{ex.get('modality')}]: {str(ex.get('text') or '')[:160]}")

    text = '\n'.join(lines[-max_items:])
    if not text.strip():
        return {'ok': True, 'status': 'empty'}

    prompt = (
        'Summarize these operational traces into 3-7 practical lessons. '\
        'Return ONLY JSON with keys: lessons(array of short strings), risks(array), actions(array).\n' + text[:5000]
    )

    payload = {'lessons': [], 'risks': [], 'actions': []}
    try:
        raw = llm.complete(prompt, strategy='cheap', json_mode=True)
        if raw:
            j = json.loads(raw)
            if isinstance(j, dict):
                payload['lessons'] = [str(x)[:180] for x in (j.get('lessons') or [])][:8]
                payload['risks'] = [str(x)[:180] for x in (j.get('risks') or [])][:8]
                payload['actions'] = [str(x)[:180] for x in (j.get('actions') or [])][:8]
    except Exception:
        # heuristic fallback
        payload['lessons'] = [
            'Priorizar grounding antes de ações críticas.',
            'Quando erro intermitente ocorrer, aplicar retry + timeout adaptativo.',
            'Para conflitos recorrentes, executar replay de casos difíceis.'
        ]

    item = {'ts': int(time.time()), **payload}
    d = _load()
    arr = list(d.get('distillations') or [])
    arr.append(item)
    d['distillations'] = arr[-300:]
    _save(d)

    dist = []
    if DISTILL_PATH.exists():
        try:
            dist = json.loads(DISTILL_PATH.read_text(encoding='utf-8'))
            if not isinstance(dist, list):
                dist = []
        except Exception:
            dist = []
    dist.append(item)
    _save_distill(dist)

    return {'ok': True, 'item': item, 'path': str(DISTILL_PATH)}


def status(limit: int = 40) -> dict[str, Any]:
    d = _load()
    fb = (d.get('feedback') or [])[-max(1, int(limit or 40)):]
    dist = (d.get('distillations') or [])[-max(1, min(10, int(limit or 10))):]
    replay = (d.get('replays') or [])[-max(1, min(20, int(limit or 20))):]

    total = len(fb)
    fails = len([x for x in fb if not bool(x.get('success'))])
    halluc = len([x for x in fb if bool(x.get('hallucination'))])
    return {
        'ok': True,
        'path': str(PATH),
        'feedback_total': total,
        'failure_rate': round((fails / total), 4) if total else 0.0,
        'hallucination_rate': round((halluc / total), 4) if total else 0.0,
        'recent_feedback': fb,
        'recent_replays': replay,
        'recent_distillations': dist,
        'distill_path': str(DISTILL_PATH),
    }
