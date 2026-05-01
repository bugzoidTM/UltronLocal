from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from ultronpro import provider_policy

PERF_PATH = Path('/app/data/llm_provider_perf.json')
QUARANTINE_PATH = Path('/app/data/llm_provider_quarantine.json')


class BaseProvider:
    name = 'base'

    def __init__(self, model: str):
        self.model = model

    def complete(self, prompt: str, max_tokens: int = 220) -> str:
        raise NotImplementedError





class AnthropicProvider(BaseProvider):
    name = 'anthropic'


class OpenAIProvider(BaseProvider):
    name = 'openai'


class OpenRouterProvider(BaseProvider):
    name = 'openrouter'


class HFProvider(BaseProvider):
    name = 'huggingface'


def _load_perf() -> dict[str, Any]:
    if PERF_PATH.exists():
        try:
            d = json.loads(PERF_PATH.read_text(encoding='utf-8'))
            if isinstance(d, dict):
                return d
        except Exception:
            pass
    return {'updated_at': 0, 'procedural': {}}


def _save_perf(d: dict[str, Any]):
    PERF_PATH.parent.mkdir(parents=True, exist_ok=True)
    d['updated_at'] = int(time.time())
    PERF_PATH.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding='utf-8')


def _load_quarantine() -> dict[str, Any]:
    if QUARANTINE_PATH.exists():
        try:
            d = json.loads(QUARANTINE_PATH.read_text(encoding='utf-8'))
            if isinstance(d, dict):
                return d
        except Exception:
            pass
    return {'updated_at': 0, 'providers': {}}


def _save_quarantine(d: dict[str, Any]):
    QUARANTINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    d['updated_at'] = int(time.time())
    QUARANTINE_PATH.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding='utf-8')


def maybe_quarantine_provider(provider: str, error_text: str, ttl_sec: int | None = None) -> dict[str, Any]:
    pv = str(provider or '').strip().lower()
    em = str(error_text or '').lower()
    if pv in ('', 'ollama_local', 'ollama', 'ultron_infer'):
        return {'ok': False, 'reason': 'provider_not_quarantinable'}
    if not any(k in em for k in ['402', '403', '404', '429', 'rate limit', 'insufficient', 'payment required', 'credits', 'quota', 'forbidden', 'not found']):
        return {'ok': False, 'reason': 'error_not_quarantinable'}
    ttl = int(ttl_sec or os.getenv('ULTRON_PROVIDER_QUARANTINE_SEC', '1800') or 1800)
    now = int(time.time())
    d = _load_quarantine()
    pp = d.setdefault('providers', {})
    pp[pv] = {
        'until': now + max(60, ttl),
        'reason': str(error_text or '')[:220],
        'updated_at': now,
    }
    _save_quarantine(d)
    return {'ok': True, 'provider': pv, 'until': pp[pv]['until']}


def is_provider_quarantined(provider: str) -> bool:
    pv = str(provider or '').strip().lower()
    d = _load_quarantine()
    ent = (d.get('providers') or {}).get(pv) if isinstance(d.get('providers'), dict) else None
    if not isinstance(ent, dict):
        return False
    return int(ent.get('until') or 0) > int(time.time())


def quarantine_status() -> dict[str, Any]:
    d = _load_quarantine()
    now = int(time.time())
    out = {}
    for pv, ent in (d.get('providers') or {}).items():
        until = int((ent or {}).get('until') or 0)
        out[pv] = {
            'active': until > now,
            'until': until,
            'remaining_sec': max(0, until - now),
            'reason': str((ent or {}).get('reason') or ''),
        }
    return {'updated_at': int(d.get('updated_at') or 0), 'providers': out}


def record_provider_performance(task_type: str, provider: str, prm_score: float):
    tt = str(task_type or 'general').strip().lower()
    pv = str(provider or 'unknown').strip().lower()
    score = max(0.0, min(1.0, float(prm_score or 0.0)))
    d = _load_perf()
    proc = d.setdefault('procedural', {})
    p = proc.setdefault(tt, {})
    cur = p.setdefault(pv, {'avg_prm': 0.0, 'n': 0})
    n = int(cur.get('n') or 0) + 1
    avg = float(cur.get('avg_prm') or 0.0)
    cur['avg_prm'] = round(((avg * (n - 1)) + score) / max(1, n), 4)
    cur['n'] = n
    _save_perf(d)


def get_perf_snapshot() -> dict[str, Any]:
    return _load_perf()


def pick_best_provider_from_history(task_type: str, minimum_n: int = 10) -> str | None:
    tt = str(task_type or 'general').strip().lower()
    d = _load_perf()
    proc = (d.get('procedural') or {}).get(tt)
    if not isinstance(proc, dict) or not proc:
        return None
    cand = []
    for pv, st in proc.items():
        n = int((st or {}).get('n') or 0)
        avg = float((st or {}).get('avg_prm') or 0.0)
        if n >= int(minimum_n):
            cand.append((avg, n, pv))
    if not cand:
        return None
    cand.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return cand[0][2]


def classify_task_type(input_class: str | None, strategy: str | None) -> str:
    ic = str(input_class or '').lower()
    st = str(strategy or '').lower()
    txt = f'{ic} {st}'
    if any(k in txt for k in ['math', 'symbolic', 'sql', 'duckdb']):
        return 'math_symbolic'
    if any(k in txt for k in ['plan', 'deep', 'long', 'roadmap']):
        return 'planning_long'
    if any(k in txt for k in ['complex', 'reasoning', 'analysis']):
        return 'reasoning_complex'
    if any(k in txt for k in ['cache', 'routine', 'rotineiro', 'cheap']):
        return 'routine'
    return 'general'


def _recent_provider_health(limit: int = 120) -> dict[str, float]:
    try:
        st = provider_policy.status(limit=limit)
        events = list(st.get('recent_events') or [])[-max(10, int(limit)):]
    except Exception:
        events = []
    stats: dict[str, dict[str, float]] = {}
    for e in events:
        provider = str(e.get('provider') or 'unknown').strip().lower()
        outcome = str(e.get('outcome') or 'unknown').strip().lower()
        notes = str(e.get('notes') or '').lower()
        bucket = stats.setdefault(provider, {'score': 0.0, 'n': 0.0})
        bucket['n'] += 1.0
        if outcome == 'ok':
            bucket['score'] += 1.0
        elif outcome == 'fallback_ok':
            bucket['score'] += 0.6
        elif outcome == 'error':
            penalty = -1.0
            if any(t in notes for t in ['429', 'rate limit', 'quota']):
                penalty = -2.5
            elif any(t in notes for t in ['504', 'timeout', 'timed out', 'busy']):
                penalty = -1.8
            bucket['score'] += penalty
    out: dict[str, float] = {}
    for provider, bucket in stats.items():
        n = max(1.0, float(bucket.get('n') or 1.0))
        out[provider] = float(bucket.get('score') or 0.0) / n
    return out


def _reorder_by_health(candidates: list[str]) -> list[str]:
    health = _recent_provider_health(limit=120)
    min_health = float(os.getenv('ULTRON_PROVIDER_MIN_HEALTH', '-1.5') or -1.5)
    indexed = [(idx, cand, float(health.get(cand, 0.0))) for idx, cand in enumerate(candidates)]
    keep = [row for row in indexed if row[2] >= min_health or row[1] not in health]
    drop = [row for row in indexed if row[2] < min_health and row[1] in health]
    keep.sort(key=lambda row: (-row[2], row[0]))
    drop.sort(key=lambda row: (-row[2], row[0]))
    return [cand for _, cand, _ in keep + drop]


def provider_priority(*, task_type: str, budget_mode: str) -> list[str]:
    mode = str(budget_mode or 'economy').strip().lower()
    tt = str(task_type or 'general').strip().lower()

    cheap_cloud = ['nvidia', 'github_models', 'openrouter', 'groq', 'huggingface', 'deepseek', 'ollama_cloud']
    capable_cloud = ['nvidia', 'anthropic', 'gemini', 'openai']

    prefer_remote_infer = os.getenv('ULTRON_PREFER_ULTRON_INFER', '1') == '1'
    primary = str(os.getenv('ULTRON_PRIMARY_LOCAL_PROVIDER', 'ultron_infer') or 'ultron_infer').strip().lower()
    local_chain = ['ultron_infer', 'ollama_local'] if prefer_remote_infer else ['ollama_local', 'ultron_infer']

    teacher_tasks = ['metacog', 'metacognition', 'reflexion', 'reflection', 'self_model_eval', 'reasoning_complex']
    scaffold_tasks = ['planning_long', 'research', 'coding', 'operations']
    routine_tasks = ['routine', 'general']
    symbolic_tasks = ['math_symbolic']

    if any(k in tt for k in symbolic_tasks):
        ordered = local_chain + ['nvidia', 'github_models'] + cheap_cloud + capable_cloud
    elif any(k in tt for k in teacher_tasks):
        ordered = ['nvidia', 'github_models', 'anthropic', 'gemini', 'openai', 'groq', 'openrouter', 'deepseek', 'ollama_cloud', 'huggingface'] + local_chain
    elif any(k in tt for k in scaffold_tasks):
        ordered = ['nvidia', 'github_models', primary] + local_chain + ['gemini', 'anthropic', 'openai', 'groq', 'openrouter', 'deepseek', 'ollama_cloud', 'huggingface']
    elif any(k in tt for k in routine_tasks):
        ordered = ['github_models', 'nvidia'] + local_chain + cheap_cloud + capable_cloud
    else:
        ordered = ['nvidia', 'github_models', 'gemini', 'anthropic', 'openai', 'groq', 'openrouter', 'deepseek', 'ollama_cloud', 'huggingface'] + local_chain

    dedup = []
    for pv in ordered:
        if pv and pv not in dedup:
            dedup.append(pv)

    if mode == 'economy':
        return _reorder_by_health(dedup)

    if mode == 'balanced':
        if tt in ('planning_long', 'reasoning_complex', 'metacognition', 'reflexion', 'reflection', 'self_model_eval'):
            preferred = ['nvidia', 'github_models', 'groq', 'openrouter', 'gemini', 'anthropic', 'openai', 'deepseek', 'ollama_cloud', 'huggingface', primary]
            boosted = []
            for pv in preferred + dedup:
                if pv and pv not in boosted:
                    boosted.append(pv)
            return _reorder_by_health(boosted)
        boosted = []
        for pv in ['nvidia', 'github_models', primary, 'groq', 'openrouter', 'gemini', 'anthropic', 'openai', 'deepseek', 'ollama_cloud', 'huggingface'] + dedup:
            if pv and pv not in boosted:
                boosted.append(pv)
        return _reorder_by_health(boosted)

    perf = []
    for pv in ['nvidia', 'github_models', 'groq', 'anthropic', 'openrouter', 'gemini', 'openai', 'deepseek', 'ollama_cloud', 'huggingface', primary] + local_chain:
        if pv and pv not in perf:
            perf.append(pv)
    return _reorder_by_health(perf)


def provider_default_model(provider: str) -> str:
    pv = str(provider or '').strip().lower()
    model_map = {
        'ollama_local': os.getenv('ULTRON_OLLAMA_LOCAL_MODEL', os.getenv('ULTRON_PRIMARY_LOCAL_MODEL', os.getenv('OLLAMA_CANARY_MODEL', 'qwen2.5:3b-instruct-q4_K_M'))),
        'ultron_infer': os.getenv('ULTRON_INFER_MODEL_NAME', os.getenv('ULTRON_PRIMARY_LOCAL_MODEL', os.getenv('OLLAMA_CANARY_MODEL', 'qwen2.5:3b-instruct-q4_K_M'))),
        'openai': os.getenv('OPENAI_DEFAULT_MODEL', 'gpt-4o-mini'),
        'anthropic': os.getenv('ANTHROPIC_DEFAULT_MODEL', 'claude-3-5-sonnet-20241022'),
        'groq': os.getenv('GROQ_DEFAULT_MODEL', 'llama-3.3-70b-versatile'),
        'openrouter': os.getenv('OPENROUTER_DEFAULT_MODEL', 'google/gemma-3-12b-it:free'),
        'gemini': os.getenv('GEMINI_DEFAULT_MODEL', 'gemini-2.0-flash'),
        'nvidia': os.getenv('NVIDIA_DEFAULT_MODEL', 'meta/llama-3.1-8b-instruct'),
        'github_models': os.getenv('GITHUB_MODELS_DEFAULT_MODEL', 'gpt-4o-mini'),
        'ollama_cloud': os.getenv('OLLAMA_CLOUD_DEFAULT_MODEL', 'minimax-m2.7'),
        'huggingface': os.getenv('HUGGINGFACE_DEFAULT_MODEL', 'meta-llama/Llama-3.2-1B-Instruct'),
        'deepseek': os.getenv('DEEPSEEK_DEFAULT_MODEL', 'deepseek-chat'),
        'openclaw_bridge': os.getenv('OPENCLAW_BRIDGE_AGENT', 'bridge'),
    }
    return model_map.get(pv, model_map['ollama_local'])


def route_provider(*, task_type: str, budget_mode: str, cloud_available: bool, has_provider: callable) -> dict[str, str]:
    mode = str(budget_mode or os.getenv('ULTRON_LLM_BUDGET_MODE', 'economy')).strip().lower()
    tt = str(task_type or 'general').strip().lower()

    history_threshold = int(os.getenv('ULTRON_PROVIDER_HISTORY_MIN_N', '6') or 6)
    allow_history_override = tt not in ('planning_long', 'reasoning_complex', 'metacognition', 'reflexion', 'reflection', 'self_model_eval')
    if mode != 'economy' and allow_history_override:
        history_pick = pick_best_provider_from_history(tt, minimum_n=history_threshold)
        if history_pick and history_pick not in ('ollama_local', 'ultron_infer') and not cloud_available:
            history_pick = ''
        if history_pick and has_provider(history_pick):
            return {'provider': history_pick, 'model': provider_default_model(history_pick)}

    priority = provider_priority(task_type=tt, budget_mode=mode)
    for pv in priority:
        if pv not in ('ollama_local', 'ultron_infer') and not cloud_available:
            continue
        if has_provider(pv):
            return {'provider': pv, 'model': provider_default_model(pv)}

    primary = str(os.getenv('ULTRON_PRIMARY_LOCAL_PROVIDER', 'ultron_infer') or 'ultron_infer').strip().lower()
    if has_provider(primary):
        return {'provider': primary, 'model': provider_default_model(primary)}
    for pv in provider_priority(task_type=tt, budget_mode=mode):
        if pv not in ('ollama_local', 'ultron_infer') and not cloud_available:
            continue
        if has_provider(pv):
            return {'provider': pv, 'model': provider_default_model(pv)}
    return {'provider': 'ollama_local', 'model': provider_default_model('ollama_local')}
