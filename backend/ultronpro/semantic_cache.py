from __future__ import annotations

import hashlib
import json
import re
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from ultronpro import embeddings

CACHE_PATH = Path(__file__).resolve().parent.parent / 'data' / 'semantic_cache.json'
EXACT_TTL_SEC = 24 * 3600
SEMANTIC_TTL_SEC = 12 * 3600
SEMANTIC_THRESHOLD = 0.92
SEMANTIC_MAX_INDEX = 500

CONCEPTUAL_DEPENDENCIES: dict[str, set[str]] = {
    'provider': {'groq', 'gemini', 'anthropic', 'openai', 'deepseek', 'llm', 'model'},
    'config': {'interval', 'timeout', 'ttl', 'cache', 'threshold', 'budget'},
    'system': {'ultronpro', 'loop', 'autonomy', 'reflexion', 'judge', 'health'},
    'math': {'calcule', 'quanto', 'resultado', 'sqrt', 'pow', 'pi', 'e'},
    'memory': {'store', 'fact', 'experience', 'action', 'event', 'sqlite'},
}

CONCEPT_INVALIDATION_RULES: dict[str, list[str]] = {
    'provider': ['model_changed', 'provider_switched', 'api_key_updated', 'rate_limit_hit'],
    'config': ['parameter_modified', 'threshold_adjusted', 'interval_changed'],
    'system': ['loop_restarted', 'mode_changed', 'health_degraded'],
    'math': ['formula_updated', 'constant_redefined'],
    'memory': ['schema_changed', 'data_purged', 'index_rebuilt'],
}


def _now() -> int:
    return int(time.time())


def _norm_q(q: str) -> str:
    return ' '.join(str(q or '').strip().lower().split())


def _md5(s: str) -> str:
    return hashlib.md5(s.encode('utf-8', errors='ignore')).hexdigest()


def _load() -> dict[str, Any]:
    if CACHE_PATH.exists():
        try:
            d = json.loads(CACHE_PATH.read_text(encoding='utf-8'))
            if isinstance(d, dict):
                d.setdefault('exact', {})
                d.setdefault('semantic', [])
                return d
        except Exception:
            pass
    return {'exact': {}, 'semantic': []}


def _save(d: dict[str, Any]):
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding='utf-8')


def _extract_concepts(query: str) -> set[str]:
    """Extract conceptual keywords from query for dependency tracking."""
    qn = _norm_q(query)
    concepts = set()
    for concept, keywords in CONCEPTUAL_DEPENDENCIES.items():
        if any(kw in qn for kw in keywords):
            concepts.add(concept)
    return concepts


def _invalidate_by_concept(d: dict[str, Any], concept: str, rules: list[str] | None = None) -> dict[str, Any]:
    """Invalidate cache entries related to a concept when a triggering rule occurs."""
    now = _now()
    
    # Invalidate exact matches
    exact = d.get('exact') or {}
    if isinstance(exact, dict):
        dead = []
        for k, v in exact.items():
            if isinstance(v, dict):
                entry_concepts = _extract_concepts(v.get('q', ''))
                if concept in entry_concepts:
                    if rules is None or any(r in str(v.get('answer', '')) for r in (rules or [])):
                        dead.append(k)
        for k in dead:
            exact.pop(k, None)
    
    # Invalidate semantic matches
    sem = d.get('semantic') or []
    if isinstance(sem, list):
        sem = [
            x for x in sem
            if isinstance(x, dict)
            and concept not in _extract_concepts(x.get('q', ''))
        ]
    
    d['exact'] = exact
    d['semantic'] = sem
    return d


def _prune(d: dict[str, Any]) -> dict[str, Any]:
    now = _now()

    # exact TTL
    exact = d.get('exact') or {}
    if isinstance(exact, dict):
        dead = []
        for k, v in exact.items():
            ts = int((v or {}).get('ts') or 0)
            if (now - ts) > EXACT_TTL_SEC:
                dead.append(k)
        for k in dead:
            exact.pop(k, None)
    else:
        exact = {}

    # semantic TTL + cap by oldest
    sem = d.get('semantic') or []
    if not isinstance(sem, list):
        sem = []
    sem = [x for x in sem if isinstance(x, dict) and (now - int(x.get('ts') or 0) <= SEMANTIC_TTL_SEC)]
    sem.sort(key=lambda x: int(x.get('ts') or 0), reverse=True)
    sem = sem[:SEMANTIC_MAX_INDEX]

    d['exact'] = exact
    d['semantic'] = sem
    return d


def _attach_inference_trace(query: str, hit: dict[str, Any]) -> dict[str, Any]:
    try:
        from ultronpro import unified_inference

        out = dict(hit)
        out["inference_trace"] = unified_inference.trace_from_cache_hit(query, out)
        return out
    except Exception:
        return hit


def lookup(query: str) -> dict[str, Any] | None:
    qn = _norm_q(query)
    if not qn:
        return None

    d = _prune(_load())
    _save(d)

    # exact
    key = _md5(qn)
    ex = (d.get('exact') or {}).get(key)
    if isinstance(ex, dict):
        return _attach_inference_trace(query, {
            'cache_hit': 'exact',
            'score': 1.0,
            'answer': str(ex.get('answer') or ''),
            'strategy': str(ex.get('strategy') or 'cache'),
        })

    # semantic
    try:
        qv = embeddings.embed_text(qn)
    except Exception:
        return None

    best = None
    best_score = -1.0
    for e in (d.get('semantic') or []):
        ev = e.get('embedding')
        if not isinstance(ev, list) or not ev:
            continue
        try:
            sc = float(embeddings.cosine_similarity(qv, ev))
        except Exception:
            continue
        if sc > best_score:
            best_score = sc
            best = e

    if best is not None and best_score >= SEMANTIC_THRESHOLD:
        return _attach_inference_trace(query, {
            'cache_hit': 'semantic',
            'score': round(best_score, 4),
            'answer': str(best.get('answer') or ''),
            'strategy': str(best.get('strategy') or 'cache'),
        })
    return None


def store(query: str, answer: str, strategy: str) -> bool:
    qn = _norm_q(query)
    ans = str(answer or '').strip()
    if not qn or not ans:
        return False

    try:
        qv = embeddings.embed_text(qn)
    except Exception:
        qv = []

    d = _prune(_load())
    now = _now()
    key = _md5(qn)

    entry = {
        'q': qn,
        'answer': ans,
        'strategy': str(strategy or ''),
        'ts': now,
        'embedding': qv,
    }

    ex = d.get('exact') or {}
    ex[key] = entry
    d['exact'] = ex

    sem = d.get('semantic') or []
    sem = [x for x in sem if str(x.get('q') or '') != qn]
    sem.append(entry)
    sem.sort(key=lambda x: int(x.get('ts') or 0), reverse=True)
    d['semantic'] = sem[:SEMANTIC_MAX_INDEX]

    _save(d)
    return True


def invalidate_conceptual(concept: str, trigger_rule: str | None = None) -> int:
    """
    Invalidate cache entries based on conceptual dependencies.
    Returns count of invalidated entries.
    """
    d = _load()
    rules = CONCEPT_INVALIDATION_RULES.get(concept, []) if trigger_rule else None
    if trigger_rule and trigger_rule in rules:
        d = _invalidate_by_concept(d, concept, [trigger_rule])
    else:
        d = _invalidate_by_concept(d, concept)
    _save(d)
    return 0
