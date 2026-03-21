from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

PERF_PATH = Path('/app/data/llm_provider_perf.json')
QUARANTINE_PATH = Path('/app/data/llm_provider_quarantine.json')


class BaseProvider:
    name = 'base'

    def __init__(self, model: str):
        self.model = model

    def complete(self, prompt: str, max_tokens: int = 220) -> str:
        raise NotImplementedError


class OllamaProvider(BaseProvider):
    name = 'ollama_local'


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
    if pv in ('', 'ollama_local', 'ollama', 'ultron_infer', 'gemini'):
        return {'ok': False, 'reason': 'provider_not_quarantinable'}
    if not any(k in em for k in ['402', '429', 'rate limit', 'insufficient', 'payment required', 'credits', 'quota']):
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


def provider_priority(*, task_type: str, budget_mode: str) -> list[str]:
    mode = str(budget_mode or 'economy').strip().lower()
    tt = str(task_type or 'general').strip().lower()

    # Explicit policy: local -> cheaper cloud -> more capable cloud
    cheap_cloud = ['openrouter', 'huggingface', 'deepseek']
    capable_cloud = ['gemini', 'anthropic', 'openai']

    prefer_remote_infer = os.getenv('ULTRON_PREFER_ULTRON_INFER', '0') == '1'
    primary = str(os.getenv('ULTRON_PRIMARY_LOCAL_PROVIDER', 'ollama_local') or 'ollama_local').strip().lower()
    local_chain = ['ultron_infer', 'ollama_local'] if prefer_remote_infer else ['ollama_local', 'ultron_infer']
    ordered = []
    for pv in [primary] + local_chain + cheap_cloud + capable_cloud:
        if pv and pv not in ordered:
            ordered.append(pv)

    if mode == 'economy':
        return ordered

    if mode == 'balanced':
        return ordered

    # performance
    perf = []
    for pv in [primary] + capable_cloud + cheap_cloud + local_chain:
        if pv and pv not in perf:
            perf.append(pv)
    return perf


def provider_default_model(provider: str) -> str:
    pv = str(provider or '').strip().lower()
    model_map = {
        'ollama_local': os.getenv('ULTRON_OLLAMA_LOCAL_MODEL', os.getenv('ULTRON_PRIMARY_LOCAL_MODEL', os.getenv('OLLAMA_CANARY_MODEL', 'llama3.2'))),
        'ultron_infer': os.getenv('ULTRON_INFER_MODEL_NAME', os.getenv('ULTRON_PRIMARY_LOCAL_MODEL', os.getenv('OLLAMA_CANARY_MODEL', 'local-infer'))),
        'openai': os.getenv('OPENAI_DEFAULT_MODEL', 'gpt-4o-mini'),
        'anthropic': os.getenv('ANTHROPIC_DEFAULT_MODEL', 'claude-3-5-sonnet-20241022'),
        'openrouter': os.getenv('OPENROUTER_DEFAULT_MODEL', 'google/gemma-2-9b-it:free'),
        'gemini': os.getenv('GEMINI_DEFAULT_MODEL', 'gemini-3-flash-preview'),
        'huggingface': os.getenv('HUGGINGFACE_DEFAULT_MODEL', 'meta-llama/Llama-3.2-1B-Instruct'),
        'deepseek': os.getenv('DEEPSEEK_DEFAULT_MODEL', 'deepseek-chat'),
        'openclaw_bridge': os.getenv('OPENCLAW_BRIDGE_AGENT', 'bridge'),
    }
    return model_map.get(pv, model_map['ollama_local'])


def route_provider(*, task_type: str, budget_mode: str, cloud_available: bool, has_provider: callable) -> dict[str, str]:
    mode = str(budget_mode or os.getenv('ULTRON_LLM_BUDGET_MODE', 'economy')).strip().lower()
    tt = str(task_type or 'general').strip().lower()

    # history override for non-economy (requires confidence via n>=10)
    if mode != 'economy':
        history_pick = pick_best_provider_from_history(tt, minimum_n=10)
        if history_pick and has_provider(history_pick):
            return {'provider': history_pick, 'model': provider_default_model(history_pick)}

    priority = provider_priority(task_type=tt, budget_mode=mode)
    for pv in priority:
        if pv not in ('ollama_local', 'ultron_infer') and not cloud_available:
            continue
        if has_provider(pv):
            return {'provider': pv, 'model': provider_default_model(pv)}

    primary = str(os.getenv('ULTRON_PRIMARY_LOCAL_PROVIDER', 'ollama_local') or 'ollama_local').strip().lower()
    if has_provider(primary):
        return {'provider': primary, 'model': provider_default_model(primary)}
    if has_provider('gemini'):
        return {'provider': 'gemini', 'model': provider_default_model('gemini')}
    return {'provider': 'ollama_local', 'model': provider_default_model('ollama_local')}
