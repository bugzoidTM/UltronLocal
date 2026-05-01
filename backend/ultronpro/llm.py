import os
import logging
import subprocess
import uuid
import json
import hashlib
from collections import OrderedDict
from pathlib import Path
from typing import Dict, Optional, Any
import httpx
import time
from ultronpro.settings import get_api_key
from ultronpro import persona, llm_adapter, provider_policy

# --- API Models ---
from pydantic import BaseModel

class SettingsUpdate(BaseModel):
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    groq_api_key: Optional[str] = None
    deepseek_api_key: Optional[str] = None
    openrouter_api_key: Optional[str] = None
    gemini_api_key: Optional[str] = None
    huggingface_api_key: Optional[str] = None
    lightrag_api_key: Optional[str] = None

logger = logging.getLogger("uvicorn")


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)) or default)
    except Exception:
        return float(default)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)) or default)
    except Exception:
        return int(default)


def _provider_failure_cooldown_sec(provider: str, error_text: str) -> int:
    pv = str(provider or '').strip().lower()
    low = str(error_text or '').lower()
    rate_limited = any(t in low for t in ['429', 'rate limit', 'quota', 'too many requests'])
    transient = any(t in low for t in ['504', 'timeout', 'timed out', 'inference_busy_retry', 'busy'])

    if pv == 'gemini':
        if rate_limited:
            return max(60, _env_int('ULTRON_GEMINI_RATE_LIMIT_COOLDOWN_SEC', 300))
        return max(3, _env_int('ULTRON_GEMINI_FAILURE_COOLDOWN_SEC', 15))
    if pv == 'ultron_infer':
        return max(5, _env_int('ULTRON_INFER_FAILURE_COOLDOWN_SEC', 20))
    if pv in ('ollama_local', 'ollama'):
        return max(5, _env_int('ULTRON_OLLAMA_FAILURE_COOLDOWN_SEC', 20))
    if transient and not rate_limited:
        return max(30, _env_int('ULTRON_PROVIDER_TRANSIENT_COOLDOWN_SEC', 120))
    return max(60, _env_int('ULTRON_PROVIDER_FAILURE_COOLDOWN_SEC', 900))


# LLM Routing Strategy
PRIMARY_LOCAL_PROVIDER = os.getenv('ULTRON_PRIMARY_LOCAL_PROVIDER', 'ultron_infer').strip().lower() or 'ultron_infer'
PRIMARY_LOCAL_MODEL = os.getenv('ULTRON_PRIMARY_LOCAL_MODEL', os.getenv('ULTRON_INFER_MODEL_NAME', os.getenv('ULTRON_OLLAMA_LOCAL_MODEL', os.getenv('OLLAMA_CANARY_MODEL', 'qwen2.5:3b-instruct-q4_K_M'))))
CANARY_PROVIDER = os.getenv('ULTRON_CANARY_PROVIDER', PRIMARY_LOCAL_PROVIDER).strip().lower() or PRIMARY_LOCAL_PROVIDER
CANARY_MODEL = os.getenv('ULTRON_CANARY_MODEL_NAME', os.getenv('ULTRON_PRIMARY_LOCAL_MODEL', os.getenv('ULTRON_INFER_MODEL_NAME', os.getenv('ULTRON_OLLAMA_LOCAL_MODEL', os.getenv('OLLAMA_CANARY_MODEL', 'qwen2.5:3b-instruct-q4_K_M')))))
PREFER_ULTRON_INFER = os.getenv('ULTRON_PREFER_ULTRON_INFER', '1') == '1'

MODELS = {
    "default": {"provider": PRIMARY_LOCAL_PROVIDER, "model": PRIMARY_LOCAL_MODEL},
    "cheap": {"provider": "github_models", "model": os.getenv('GITHUB_MODELS_DEFAULT_MODEL', 'gpt-4o-mini')},
    "reasoning": {"provider": PRIMARY_LOCAL_PROVIDER, "model": PRIMARY_LOCAL_MODEL},
    "creative": {"provider": PRIMARY_LOCAL_PROVIDER, "model": PRIMARY_LOCAL_MODEL},
    "deep": {"provider": PRIMARY_LOCAL_PROVIDER, "model": PRIMARY_LOCAL_MODEL},
    "openai_default": {"provider": "openai", "model": os.getenv('OPENAI_DEFAULT_MODEL', 'gpt-4o-mini')},
    "anthropic_default": {"provider": "anthropic", "model": os.getenv('ANTHROPIC_DEFAULT_MODEL', 'claude-3-5-sonnet-20241022')},
    "deepseek_default": {"provider": "deepseek", "model": os.getenv('DEEPSEEK_DEFAULT_MODEL', 'deepseek-chat')},
    "openrouter_free": {"provider": "openrouter", "model": os.getenv('OPENROUTER_DEFAULT_MODEL', 'google/gemma-3-12b-it:free')},
    "gemini_default": {"provider": "gemini", "model": os.getenv('GEMINI_DEFAULT_MODEL', 'gemini-2.0-flash')},
    "hf_free": {"provider": "huggingface", "model": os.getenv('HUGGINGFACE_DEFAULT_MODEL', 'meta-llama/Llama-3.2-1B-Instruct')},
    "local": {"provider": PRIMARY_LOCAL_PROVIDER, "model": PRIMARY_LOCAL_MODEL},
    "canary_qwen": {"provider": CANARY_PROVIDER, "model": CANARY_MODEL},
    "nvidia": {"provider": "nvidia", "model": os.getenv('NVIDIA_DEFAULT_MODEL', 'meta/llama-3.1-8b-instruct')},
    "github_models": {"provider": "github_models", "model": os.getenv('GITHUB_MODELS_DEFAULT_MODEL', 'gpt-4o-mini')}
}

ALLOW_OLLAMA_FALLBACK = os.getenv('ULTRON_ALLOW_OLLAMA_FALLBACK', '0') == '1'
LLM_CACHE_ENABLED = os.getenv('ULTRON_LLM_CACHE_ENABLED', '1') == '1'
LLM_CACHE_MAX_ENTRIES = _env_int('ULTRON_LLM_CACHE_MAX_ENTRIES', 512)
LLM_CACHE_TTL_SEC = _env_float('ULTRON_LLM_CACHE_TTL_SEC', 900.0)
LLM_CACHE_MIN_PROMPT_CHARS = _env_int('ULTRON_LLM_CACHE_MIN_PROMPT_CHARS', 16)
LLM_CACHE_MAX_PROMPT_CHARS = _env_int('ULTRON_LLM_CACHE_MAX_PROMPT_CHARS', 12000)


class _TTLResponseCache:
    def __init__(self, max_entries: int = 512, ttl_sec: float = 900.0):
        self.max_entries = max(8, int(max_entries or 512))
        self.ttl_sec = max(5.0, float(ttl_sec or 900.0))
        self._store: OrderedDict[str, tuple[float, str]] = OrderedDict()
        self.hits = 0
        self.misses = 0
        self.stales = 0
        self.writes = 0

    def _prune(self) -> None:
        now = time.time()
        stale_keys = [k for k, (exp, _) in self._store.items() if exp <= now]
        for k in stale_keys:
            self._store.pop(k, None)
            self.stales += 1
        while len(self._store) > self.max_entries:
            self._store.popitem(last=False)

    def get(self, key: str) -> str | None:
        if not key:
            return None
        item = self._store.get(key)
        if not item:
            self.misses += 1
            return None
        exp, value = item
        if exp <= time.time():
            self._store.pop(key, None)
            self.misses += 1
            self.stales += 1
            return None
        self._store.move_to_end(key)
        self.hits += 1
        return value

    def set(self, key: str, value: str) -> None:
        if not key or not isinstance(value, str) or not value.strip():
            return
        self._store[key] = (time.time() + self.ttl_sec, value)
        self._store.move_to_end(key)
        self.writes += 1
        self._prune()

    def status(self) -> dict[str, Any]:
        self._prune()
        return {
            'enabled': True,
            'backend': 'memory',
            'entries': len(self._store),
            'max_entries': self.max_entries,
            'ttl_sec': self.ttl_sec,
            'hits': self.hits,
            'misses': self.misses,
            'stales': self.stales,
            'writes': self.writes,
        }


def _build_response_cache():
    return _TTLResponseCache(max_entries=LLM_CACHE_MAX_ENTRIES, ttl_sec=LLM_CACHE_TTL_SEC)


def _response_cache_status() -> dict[str, Any]:
    try:
        st = _RESPONSE_CACHE.status()
    except Exception as e:
        st = {'enabled': bool(LLM_CACHE_ENABLED), 'backend': 'memory', 'error': str(e)[:180]}
    st.setdefault('configured_backend', 'memory')
    st.setdefault('ttl_sec', LLM_CACHE_TTL_SEC)
    st.setdefault('min_prompt_chars', LLM_CACHE_MIN_PROMPT_CHARS)
    st.setdefault('max_prompt_chars', LLM_CACHE_MAX_PROMPT_CHARS)
    return st


_RESPONSE_CACHE = _build_response_cache()


def _normalize_cache_text(text: str | None) -> str:
    t = ' '.join(str(text or '').strip().split())
    return t[:LLM_CACHE_MAX_PROMPT_CHARS]


def _cache_key(prompt: str, strategy: str, system: str | None, json_mode: bool, max_tokens: int | None, cloud_fallback: bool, input_class: str | None, inject_persona: bool) -> str:
    norm_prompt = _normalize_cache_text(prompt)
    norm_system = _normalize_cache_text(system)
    if len(norm_prompt) < LLM_CACHE_MIN_PROMPT_CHARS:
        return ''
    payload = {
        'prompt': norm_prompt,
        'system': norm_system,
        'strategy': str(strategy or 'default'),
        'json_mode': bool(json_mode),
        'max_tokens': int(max_tokens or 0),
        'cloud_fallback': bool(cloud_fallback),
        'input_class': str(input_class or ''),
        'inject_persona': bool(inject_persona),
        'primary_local_provider': str(PRIMARY_LOCAL_PROVIDER or ''),
        'primary_local_model': str(PRIMARY_LOCAL_MODEL or ''),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def _cacheable_request(strategy: str, prompt: str, json_mode: bool, max_tokens: int | None) -> bool:
    if not LLM_CACHE_ENABLED:
        return False
    if json_mode:
        return False
    if not str(prompt or '').strip():
        return False
    if int(max_tokens or 0) > 512:
        return False
    return str(strategy or 'default') in {'default', 'reasoning', 'creative', 'deep', 'cheap', 'local'}


def _is_cacheable_response(text: str) -> bool:
    s = str(text or '').strip()
    if not s:
        return False
    low = s.lower()
    noisy_markers = (
        'temporariamente saturada',
        'falhou ou expirou',
        'não houve verbalização local disponível',
        'excedeu o orçamento global',
        'rate limit',
        'busy_retry')
    return not any(m in low for m in noisy_markers)


def _is_provider_disabled(provider: str) -> bool:
    p = str(provider or '').strip().lower()
    if os.getenv('ULTRON_DISABLE_CLOUD_PROVIDERS', '0') == '1' and p in ('huggingface', 'openrouter', 'groq', 'deepseek', 'openai', 'anthropic', 'gemini', 'nvidia', 'github_models'):
        return True
    env_map = {
        'huggingface': 'ULTRON_DISABLE_HUGGINGFACE',
        'openrouter': 'ULTRON_DISABLE_OPENROUTER',
        'groq': 'ULTRON_DISABLE_GROQ',
        'deepseek': 'ULTRON_DISABLE_DEEPSEEK',
        'openai': 'ULTRON_DISABLE_OPENAI',
        'anthropic': 'ULTRON_DISABLE_ANTHROPIC',
        'gemini': 'ULTRON_DISABLE_GEMINI',
        'nvidia': 'ULTRON_DISABLE_NVIDIA',
        'github_models': 'ULTRON_DISABLE_GITHUB_MODELS',
        'ollama_cloud': 'ULTRON_DISABLE_OLLAMA_CLOUD',
        'ollama_local': 'ULTRON_DISABLE_OLLAMA_LOCAL',
        'ultron_infer': 'ULTRON_DISABLE_ULTRON_INFER',
    }
    ek = env_map.get(p)
    return bool(ek and os.getenv(ek, '0') == '1')


def _provider_has_key(provider: str) -> bool:
    p = str(provider or '').strip().lower()
    if p in ( 'ultron_infer', 'openclaw_bridge'):
        return True
    try:
        return bool(str(get_api_key(p) or '').strip())
    except Exception:
        return False


def _model_for_provider_task(provider: str, task_type: str, strategy: str) -> str:
    p = str(provider or '').strip().lower()
    tt = str(task_type or 'general').strip().lower()
    st = str(strategy or 'default').strip().lower()

    if p == 'gemini':
        if tt in ('planning_long', 'reasoning_complex') or st in ('deep', 'reasoning'):
            return os.getenv('GEMINI_REASONING_MODEL', os.getenv('GEMINI_DEFAULT_MODEL', 'gemini-2.0-flash'))
        return os.getenv('GEMINI_FAST_MODEL', os.getenv('GEMINI_DEFAULT_MODEL', 'gemini-2.0-flash'))
    if p == 'openrouter':
        if tt in ('routine', 'general') or st == 'cheap':
            return os.getenv('OPENROUTER_CHEAP_MODEL', os.getenv('OPENROUTER_DEFAULT_MODEL', 'google/gemma-3-12b-it:free'))
        return os.getenv('OPENROUTER_REASONING_MODEL', os.getenv('OPENROUTER_DEFAULT_MODEL', 'google/gemma-3-12b-it:free'))
    if p == 'huggingface':
        if tt in ('routine', 'general') or st == 'cheap':
            return os.getenv('HUGGINGFACE_CHEAP_MODEL', os.getenv('HUGGINGFACE_DEFAULT_MODEL', 'meta-llama/Llama-3.2-1B-Instruct'))
        return os.getenv('HUGGINGFACE_REASONING_MODEL', os.getenv('HUGGINGFACE_DEFAULT_MODEL', 'meta-llama/Llama-3.2-1B-Instruct'))
    if p == 'deepseek':
        return os.getenv('DEEPSEEK_REASONING_MODEL', os.getenv('DEEPSEEK_DEFAULT_MODEL', 'deepseek-chat'))
    if p == 'groq':
        if tt in ('planning_long', 'reasoning_complex') or st in ('deep', 'reasoning'):
            return os.getenv('GROQ_REASONING_MODEL', os.getenv('GROQ_DEFAULT_MODEL', 'llama-3.3-70b-versatile'))
        return os.getenv('GROQ_FAST_MODEL', os.getenv('GROQ_DEFAULT_MODEL', 'llama-3.3-70b-versatile'))
    if p == 'nvidia':
        if tt in ('planning_long', 'reasoning_complex') or st in ('deep', 'reasoning'):
            return os.getenv('NVIDIA_REASONING_MODEL', os.getenv('NVIDIA_DEFAULT_MODEL', 'meta/llama-3.1-8b-instruct'))
        return os.getenv('NVIDIA_FAST_MODEL', os.getenv('NVIDIA_DEFAULT_MODEL', 'meta/llama-3.1-8b-instruct'))
    if p == 'github_models':
        if tt in ('routine', 'general') or st == 'cheap':
            return os.getenv('GITHUB_MODELS_FAST_MODEL', os.getenv('GITHUB_MODELS_DEFAULT_MODEL', 'gpt-4o-mini'))
        return os.getenv('GITHUB_MODELS_REASONING_MODEL', os.getenv('GITHUB_MODELS_DEFAULT_MODEL', 'gpt-4o-mini'))
    if p == 'ollama_cloud':
        return os.getenv('OLLAMA_CLOUD_DEFAULT_MODEL', 'minimax-m2.7')
    if p == 'openai':
        return os.getenv('OPENAI_DEFAULT_MODEL', 'gpt-4o-mini')
    if p == 'anthropic':
        return os.getenv('ANTHROPIC_DEFAULT_MODEL', 'claude-3-5-sonnet-20241022')
    return llm_adapter.provider_default_model(p)

class LLMRouter:
    def __init__(self):
        # Clients cache
        self.clients = {}
        self.fail_cooldown_until: Dict[str, int] = {}
        self.last_call_meta = {'provider': None, 'model': None, 'task_type': None, 'budget_mode': None}
        self.usage = {
            'started_at': int(time.time()),
            'providers': {
                'openai': {'calls': 0, 'ok': 0, 'errors': 0, 'tokens_in': 0, 'tokens_out': 0, 'tokens_total': 0, 'limit_tokens': int(os.getenv('OPENAI_DAILY_LIMIT_TOKENS', '0') or 0)},
                'gemini': {'calls': 0, 'ok': 0, 'errors': 0, 'tokens_in': 0, 'tokens_out': 0, 'tokens_total': 0, 'limit_tokens': int(os.getenv('GEMINI_DAILY_LIMIT_TOKENS', '0') or 0)},
                'anthropic': {'calls': 0, 'ok': 0, 'errors': 0, 'tokens_in': 0, 'tokens_out': 0, 'tokens_total': 0, 'limit_tokens': int(os.getenv('ANTHROPIC_DAILY_LIMIT_TOKENS', '0') or 0)},
                'groq': {'calls': 0, 'ok': 0, 'errors': 0, 'tokens_in': 0, 'tokens_out': 0, 'tokens_total': 0, 'limit_tokens': int(os.getenv('GROQ_TPD_LIMIT', '100000') or 100000)},
                'deepseek': {'calls': 0, 'ok': 0, 'errors': 0, 'tokens_in': 0, 'tokens_out': 0, 'tokens_total': 0, 'limit_tokens': int(os.getenv('DEEPSEEK_DAILY_LIMIT_TOKENS', '0') or 0)},
                'openrouter': {'calls': 0, 'ok': 0, 'errors': 0, 'tokens_in': 0, 'tokens_out': 0, 'tokens_total': 0, 'limit_tokens': int(os.getenv('OPENROUTER_DAILY_LIMIT_TOKENS', '0') or 0)},
                'huggingface': {'calls': 0, 'ok': 0, 'errors': 0, 'tokens_in': 0, 'tokens_out': 0, 'tokens_total': 0, 'limit_tokens': int(os.getenv('HUGGINGFACE_DAILY_LIMIT_TOKENS', '0') or 0)},
                'openclaw_bridge': {'calls': 0, 'ok': 0, 'errors': 0, 'tokens_in': 0, 'tokens_out': 0, 'tokens_total': 0, 'limit_tokens': 0},
                'ollama': {'calls': 0, 'ok': 0, 'errors': 0, 'tokens_in': 0, 'tokens_out': 0, 'tokens_total': 0, 'limit_tokens': 0},
                'ollama_local': {'calls': 0, 'ok': 0, 'errors': 0, 'tokens_in': 0, 'tokens_out': 0, 'tokens_total': 0, 'limit_tokens': 0},
            },
            'last_error': None,
        }

    def _touch(self, provider: str, ok: bool | None = None, err: str | None = None, tin: int = 0, tout: int = 0):
        p = self.usage['providers'].setdefault(provider, {'calls': 0, 'ok': 0, 'errors': 0, 'tokens_in': 0, 'tokens_out': 0, 'tokens_total': 0, 'limit_tokens': 0})
        p['calls'] = int(p.get('calls') or 0) + 1
        if ok is True:
            p['ok'] = int(p.get('ok') or 0) + 1
        elif ok is False:
            p['errors'] = int(p.get('errors') or 0) + int(1 if err else 0)
        p['tokens_in'] = int(p.get('tokens_in') or 0) + int(tin or 0)
        p['tokens_out'] = int(p.get('tokens_out') or 0) + int(tout or 0)
        p['tokens_total'] = int(p.get('tokens_total') or 0) + int(tin or 0) + int(tout or 0)
        if err:
            em = str(err)
            self.usage['last_error'] = {'ts': int(time.time()), 'provider': provider, 'error': em[:220]}
            low = em.lower()
            # global backoff for known external failure states
            if provider in ('huggingface', 'openrouter', 'groq', 'deepseek', 'openai', 'anthropic', 'gemini', 'ultron_infer', 'ollama_local', 'ollama', 'nvidia', 'github_models'):
                if any(t in low for t in ['402', '403', '404', '429', 'rate limit', 'insufficient credits', 'depleted your monthly included credits', 'model_not_supported', 'no endpoints found', 'payment required', 'inference_busy_retry', '504', 'timeout', 'timed out', 'forbidden', 'not found']):
                    cool_sec = _provider_failure_cooldown_sec(provider, em)
                    self.fail_cooldown_until[str(provider)] = int(time.time()) + cool_sec
                try:
                    if provider not in ('ultron_infer', 'ollama_local', 'ollama'):
                        llm_adapter.maybe_quarantine_provider(provider, em)
                except Exception:
                    pass

    def _provider_cooldown_active(self, provider: str) -> bool:
        ts = int(self.fail_cooldown_until.get(str(provider or ''), 0) or 0)
        return ts > int(time.time())

    def usage_status(self) -> dict:
        out = {'started_at': self.usage.get('started_at'), 'providers': {}, 'last_error': self.usage.get('last_error'), 'response_cache': _response_cache_status() if LLM_CACHE_ENABLED else {'enabled': False, 'configured_backend': 'memory'}}
        now = int(time.time())
        elapsed = max(1, now - int(self.usage.get('started_at') or now))
        for k, v in (self.usage.get('providers') or {}).items():
            lim = int(v.get('limit_tokens') or 0)
            used = int(v.get('tokens_total') or 0)
            rate_tps = float(used) / float(elapsed)
            eta_sec = None
            if lim > 0 and rate_tps > 0:
                eta_sec = int(max(0, (lim - used) / rate_tps))
            out['providers'][k] = {
                **v,
                'remaining_tokens': (lim - used) if lim > 0 else None,
                'limit_applicable': bool(lim > 0),
                'tokens_per_sec': round(rate_tps, 6),
                'eta_to_limit_sec': eta_sec,
            }
        return out

    def healthcheck(self, provider: str = 'auto') -> dict:
        p = str(provider or 'auto').lower().strip()
        if p == 'auto':
            # prefer explicit providers, fallback to ollama
            for cand in ('gemini', 'ultron_infer', 'ollama_local', 'huggingface', 'openrouter', 'openai', 'anthropic', 'groq', 'deepseek', 'ollama', 'openclaw_bridge', 'nvidia', 'github_models'):
                r = self.healthcheck(cand)
                if r.get('ok'):
                    return r
            return {'ok': False, 'provider': 'auto', 'error': 'no_provider_healthy'}

        c = self._get_client(p)
        if not c:
            return {'ok': False, 'provider': p, 'error': 'client_unavailable'}

        t0 = time.time()
        try:
            if p == 'openclaw_bridge':
                txt = self._call_openclaw_bridge(c, 'Reply with OK only.', 'Healthcheck probe.', json_mode=False, max_tokens=64)
                dt = int((time.time() - t0) * 1000)
                return {'ok': bool((txt or '').strip()), 'provider': p, 'latency_ms': dt, 'sample': (txt or '')[:40]}

            if p == 'ultron_infer':
                base = (c or {}).get('base_url') or os.getenv('ULTRON_LOCAL_INFER_URL', 'http://127.0.0.1:8025')
                headers = {'x-api-key': os.getenv('ULTRON_LOCAL_INFER_TOKEN','').strip()} if os.getenv('ULTRON_LOCAL_INFER_TOKEN','').strip() else {}
                with httpx.Client(timeout=10.0) as hc:
                    rr = hc.get(base.rstrip('/') + '/health', headers=headers)
                    rr.raise_for_status()
                dt = int((time.time() - t0) * 1000)
                return {'ok': True, 'provider': p, 'latency_ms': dt, 'check': 'health'}

            # tiny generation probe (low token)
            strategy_map = {
                'openrouter': 'openrouter_free',
                'huggingface': 'hf_free',
                'openai': 'openai_default',
                'gemini': 'gemini_default',
                'groq': 'cheap',
                'anthropic': 'anthropic_default',
                'deepseek': 'deepseek_default',
                'nvidia': 'nvidia',
                'github_models': 'github_models'
            }
            txt = self.complete(
                'Reply with OK only.',
                strategy=strategy_map.get(p, 'local'),
                system='Healthcheck probe.',
                json_mode=False)
            dt = int((time.time() - t0) * 1000)
            return {'ok': bool((txt or '').strip()), 'provider': p, 'latency_ms': dt, 'sample': (txt or '')[:40]}
        except Exception as e:
            self._touch(p, ok=False, err=str(e))
            return {'ok': False, 'provider': p, 'error': str(e)[:220]}

    def _get_client(self, provider: str) -> Any:
        if _is_provider_disabled(provider):
            return None
        if self._provider_cooldown_active(provider):
            return None
        try:
            if llm_adapter.is_provider_quarantined(provider):
                return None
        except Exception:
            pass
        if provider in self.clients:
            return self.clients[provider]
        
        client = None
        try:
            key = get_api_key(provider)
            compat_timeout = _env_float('ULTRON_LLM_COMPAT_TIMEOUT_SEC', 10.0)
            router_timeout = _env_float('ULTRON_LLM_ROUTER_TIMEOUT_SEC', max(compat_timeout, 12.0))
            anthropic_timeout = _env_float('ULTRON_LLM_ANTHROPIC_TIMEOUT_SEC', compat_timeout)
            
            if provider == "openai":
                from openai import OpenAI
                if key: client = OpenAI(api_key=key, timeout=compat_timeout, max_retries=0)
            elif provider == "anthropic":
                from anthropic import Anthropic
                if key: client = Anthropic(api_key=key, timeout=anthropic_timeout, max_retries=0)
            elif provider == "groq":
                from groq import Groq
                if key: client = Groq(api_key=key, timeout=compat_timeout, max_retries=0)
            elif provider == "deepseek":
                from openai import OpenAI
                if key: client = OpenAI(api_key=key, base_url="https://api.deepseek.com", timeout=compat_timeout, max_retries=0)
            elif provider == "gemini":
                if key:
                    client = {
                        'api_key': key,
                        'base_url': os.getenv('GEMINI_BASE_URL', 'https://generativelanguage.googleapis.com/v1beta'),
                        'timeout': _env_float('ULTRON_GEMINI_TIMEOUT_SEC', max(router_timeout, 12.0)),
                    }
            elif provider == "openrouter":
                from openai import OpenAI
                if key:
                    client = OpenAI(
                        api_key=key,
                        base_url="https://openrouter.ai/api/v1",
                        timeout=router_timeout,
                        max_retries=0,
                        default_headers={
                            'HTTP-Referer': os.getenv('OPENROUTER_HTTP_REFERER', 'https://ultronpro.nutef.com'),
                            'X-Title': os.getenv('OPENROUTER_APP_TITLE', 'UltronPro'),
                        })
            elif provider == "nvidia":
                from openai import OpenAI
                if key:
                    client = OpenAI(
                        api_key=key,
                        base_url=os.getenv('NVIDIA_BASE_URL', 'https://integrate.api.nvidia.com/v1'),
                        timeout=router_timeout,
                        max_retries=0)
            elif provider == "github_models":
                from openai import OpenAI
                if key:
                    client = OpenAI(
                        api_key=key,
                        base_url=os.getenv('GITHUB_MODELS_BASE_URL', 'https://models.inference.ai.azure.com'),
                        timeout=router_timeout,
                        max_retries=0)
            elif provider == "ollama_cloud":
                from openai import OpenAI
                if key:
                    client = OpenAI(
                        api_key=key,
                        base_url=os.getenv('OLLAMA_CLOUD_BASE_URL', 'https://ollama.com/api/openai'),
                        timeout=router_timeout,
                        max_retries=0)
            elif provider == "huggingface":
                from openai import OpenAI
                if key:
                    client = OpenAI(
                        api_key=key,
                        base_url=os.getenv('HUGGINGFACE_BASE_URL', 'https://router.huggingface.co/v1'),
                        timeout=router_timeout,
                        max_retries=0)
            elif provider == "ollama":
                # local HTTP endpoint; no API key required
                client = {"base_url": os.getenv('OLLAMA_BASE_URL', 'http://127.0.0.1:11434')}
            elif provider == "ollama_local":
                client = {"base_url": os.getenv('OLLAMA_BASE_URL_LOCAL', os.getenv('OLLAMA_BASE_URL', 'http://127.0.0.1:11434'))}
            elif provider == "ultron_infer":
                client = {
                    "base_url": os.getenv('ULTRON_LOCAL_INFER_URL', 'http://127.0.0.1:8025'),
                    "token": os.getenv('ULTRON_LOCAL_INFER_TOKEN', '').strip(),
                }
            elif provider == "openclaw_bridge":
                client = {
                    "agent": os.getenv('OPENCLAW_BRIDGE_AGENT', 'bridge'),
                    "timeout": int(os.getenv('OPENCLAW_BRIDGE_TIMEOUT_SEC', '120') or 120),
                    "session_prefix": os.getenv('OPENCLAW_BRIDGE_SESSION_PREFIX', 'ulbridge'),
                    "url": os.getenv('OPENCLAW_BRIDGE_URL', 'http://172.17.0.1:18991/generate'),
                }
        except Exception as e:
            logger.error(f"Failed to init {provider}: {e}")

        if client:
            self.clients[provider] = client
            
        return client

    def complete(self, prompt: str, strategy: str = "default", system: str = None, json_mode: bool = False, inject_persona: bool = True, max_tokens: int | None = None, cloud_fallback: bool = True, input_class: str | None = None) -> str:
        # runtime personality injection (dynamic system prompt + few-shot exemplars)
        if inject_persona:
            try:
                system = persona.build_system_prompt(system)
            except Exception:
                pass

        cache_key = ''
        if _cacheable_request(strategy, prompt, json_mode, max_tokens):
            try:
                cache_key = _cache_key(prompt, strategy, system, json_mode, max_tokens, cloud_fallback, input_class, inject_persona)
                cached = _RESPONSE_CACHE.get(cache_key)
                if cached is not None:
                    self.last_call_meta = {
                        'provider': 'cache',
                        'model': 'response_cache',
                        'task_type': llm_adapter.classify_task_type(input_class=input_class, strategy=strategy),
                        'budget_mode': os.getenv('ULTRON_LLM_BUDGET_MODE', 'economy').strip().lower(),
                    }
                    return cached
            except Exception:
                cache_key = ''

        config = MODELS.get(strategy, MODELS["default"])
        provider = config["provider"]
        model = config["model"]

        # Unified adapter-based routing (Phase 6)
        budget_mode = os.getenv('ULTRON_LLM_BUDGET_MODE', 'balanced').strip().lower()
        task_type = llm_adapter.classify_task_type(input_class=input_class, strategy=strategy)
        cloud_available = os.getenv('ULTRON_DISABLE_CLOUD_PROVIDERS', '0') != '1'
        def _has_provider(pv: str) -> bool:
            if not _provider_has_key(pv):
                return False
            return self._get_client(pv) is not None

        routed = llm_adapter.route_provider(task_type=task_type, budget_mode=budget_mode, cloud_available=cloud_available, has_provider=_has_provider)
        provider = str(routed.get('provider') or provider)
        model = str(routed.get('model') or _model_for_provider_task(provider, task_type, strategy))

        # local runtime providers rely on server-side active adapter marker

        client = None
        # 1. Prefer local ultron_infer for primary reasoning strategies (unless adapter selected explicit cloud)
        if strategy in ('default', 'reasoning', 'creative', 'deep') and provider in ('ultron_infer', 'ollama_local'):
            cloud_disabled = os.getenv('ULTRON_DISABLE_CLOUD_PROVIDERS', '0') == '1'
            prefer_hf = (os.getenv('ULTRON_PREFER_HF', '0') == '1') and (not cloud_disabled)
            if prefer_hf:
                hf_client = self._get_client('huggingface')
                if hf_client:
                    provider = 'huggingface'
                    model = os.getenv('HUGGINGFACE_REASONING_MODEL', MODELS['hf_free']['model'])
                    client = hf_client
                else:
                    ol = self._get_client('ollama_local')
                    if ol:
                        provider = 'ollama_local'
                        model = os.getenv('ULTRON_OLLAMA_LOCAL_MODEL', MODELS['local']['model'])
                        client = ol
                    else:
                        ui = self._get_client('ultron_infer')
                        if ui:
                            provider = 'ultron_infer'
                            model = MODELS['local']['model']
                            client = ui
                        else:
                            client = self._get_client(provider)
            else:
                # stable runtime path; optionally prefer remote infer over ollama-compatible endpoint
                first_provider = 'ultron_infer' if PREFER_ULTRON_INFER else 'ollama_local'
                second_provider = 'ollama_local' if first_provider == 'ultron_infer' else 'ultron_infer'
                if self._provider_cooldown_active(first_provider) and not self._provider_cooldown_active(second_provider):
                    first_provider, second_provider = second_provider, first_provider
                first = self._get_client(first_provider)
                if first:
                    provider = first_provider
                    model = MODELS['local']['model'] if first_provider == 'ultron_infer' else os.getenv('ULTRON_OLLAMA_LOCAL_MODEL', MODELS['local']['model'])
                    client = first
                else:
                    second = self._get_client(second_provider)
                    if second:
                        provider = second_provider
                        model = MODELS['local']['model'] if second_provider == 'ultron_infer' else os.getenv('ULTRON_OLLAMA_LOCAL_MODEL', MODELS['local']['model'])
                        client = second
                    else:
                        client = self._get_client(provider)
        elif strategy in ('cheap'):
            cloud_disabled = os.getenv('ULTRON_DISABLE_CLOUD_PROVIDERS', '0') == '1'
            if not cloud_disabled:
                # Prioridade para o que está funcionando hoje (NVIDIA e GitHub)
                gh_client = self._get_client('github_models')
                if gh_client:
                    provider = 'github_models'
                    model = os.getenv('GITHUB_MODELS_DEFAULT_MODEL', 'gpt-4o-mini')
                    client = gh_client
                else:
                    nv_client = self._get_client('nvidia')
                    if nv_client:
                        provider = 'nvidia'
                        model = os.getenv('NVIDIA_DEFAULT_MODEL', 'meta/llama-3.1-8b-instruct')
                        client = nv_client
                    else:
                        # Fallback para os outros
                        hf_client = self._get_client('huggingface')
                        if hf_client:
                            provider = 'huggingface'
                            model = MODELS['hf_free']['model']
                            client = hf_client
                        else:
                            or_client = self._get_client('openrouter')
                            if or_client:
                                provider = 'openrouter'
                                model = MODELS['openrouter_free']['model']
                                client = or_client
                            else:
                                client = None
            else:
                client = None
            if not client:
                ol = self._get_client('ollama_local')
                if ol:
                    provider = 'ollama_local'
                    model = os.getenv('ULTRON_OLLAMA_LOCAL_MODEL', MODELS['local']['model'])
                    client = ol
                else:
                    # economic hard-fallback: local ultron_infer before paid/rate-limited cloud
                    local_client = self._get_client('ultron_infer')
                    if local_client:
                        provider = 'ultron_infer'
                        model = MODELS['local']['model']
                        client = local_client
                    else:
                        client = self._get_client(provider)
        else:
            client = self._get_client(provider)
        
        # 2. Fallback chain across providers
        if not client and cloud_fallback and cloud_available:
            for cand in llm_adapter.provider_priority(task_type=task_type, budget_mode=budget_mode):
                if self._provider_cooldown_active(cand):
                    continue
                if cand == provider:
                    continue
                c = self._get_client(cand)
                if c:
                    provider = cand
                    model = _model_for_provider_task(cand, task_type, strategy)
                    client = c
                    logger.warning(f"Provider fallback: using {provider}/{model}")
                    break

        # 3. Optional local Ollama fallback (disabled by default to protect VPS)
        if not client and ALLOW_OLLAMA_FALLBACK:
            provider = 'ollama'
            model = MODELS['local']['model']
            client = self._get_client('ollama')

        if not client:
            logger.error("No LLM clients available in cloud chain (and local fallback disabled).")
            self._touch('none', ok=False, err='no_llm_clients_cloud_chain')
            return ""

        self.last_call_meta = {'provider': provider, 'model': model, 'task_type': task_type, 'budget_mode': budget_mode, 'role': 'serve'}
        try:
            if provider == "anthropic":
                out = self._call_anthropic(client, model, prompt, system, json_mode)
            elif provider == 'gemini':
                out = self._call_gemini(client, model, prompt, system, json_mode, max_tokens=max_tokens)
            elif provider == 'openclaw_bridge':
                out = self._call_openclaw_bridge(client, prompt, system, json_mode, max_tokens=max_tokens)
            elif provider in ('ollama_local', 'ollama'):
                out = self._call_ollama(client, model, prompt, system, json_mode, max_tokens=max_tokens, provider_label=provider)
            elif provider == 'ultron_infer':
                out = self._call_ultron_infer(client, model, prompt, system, json_mode, max_tokens=max_tokens)
            else:
                out = self._call_openai_compat(client, model, prompt, system, json_mode, provider=provider, max_tokens=max_tokens)
            provider_policy.record_event(
                role='serve',
                provider=provider,
                model=model,
                task_type=task_type,
                outcome='ok',
                artifact_count=1 if str(out or '').strip() else 0,
                trace_payload={
                    'problem': str(prompt or '')[:500],
                    'response_excerpt': str(out or '')[:500],
                    'strategy': f'llm::{provider}',
                    'steps': [
                        {'step': 1, 'kind': 'provider_select', 'detail': f'provider={provider} model={model} task_type={task_type} budget_mode={budget_mode}'},
                        {'step': 2, 'kind': 'provider_response', 'detail': str(out or '')[:240]}],
                    'artifacts': ['llm_response'],
                    'artifact_refs': [f'provider://{provider}/{model}'],
                    'expected_effect': {
                        'kind': 'provider_assist',
                        'goal': 'gerar resposta útil e passível de internalização posterior',
                    },
                    'observed_effect': {
                        'kind': 'provider_response',
                        'success': True,
                        'nonempty': bool(str(out or '').strip()),
                    },
                    'cloud_dependency_intent': 'worker_assist_not_permanent_dependency',
                    'work_context': {
                        'budget_mode': budget_mode,
                        'role': 'serve',
                        'cache_key_present': bool(cache_key),
                    },
                })
            if cache_key and _is_cacheable_response(out):
                try:
                    _RESPONSE_CACHE.set(cache_key, str(out))
                except Exception:
                    pass
            return out
        except Exception as e:
            provider_policy.record_event(
                role='serve',
                provider=provider,
                model=model,
                task_type=task_type,
                outcome='error',
                notes=str(e),
                trace_payload={
                    'problem': str(prompt or '')[:500],
                    'strategy': f'llm::{provider}',
                    'steps': [
                        {'step': 1, 'kind': 'provider_select', 'detail': f'provider={provider} model={model} task_type={task_type} budget_mode={budget_mode}'},
                        {'step': 2, 'kind': 'provider_error', 'detail': str(e)[:240]}],
                    'artifacts': [],
                    'expected_effect': {
                        'kind': 'provider_assist',
                        'goal': 'gerar resposta útil e passível de internalização posterior',
                    },
                    'observed_effect': {
                        'kind': 'provider_error',
                        'success': False,
                        'error': str(e)[:240],
                    },
                    'cloud_dependency_intent': 'worker_assist_not_permanent_dependency',
                    'work_context': {
                        'budget_mode': budget_mode,
                        'role': 'serve',
                    },
                })
            self._touch(provider, ok=False, err=str(e))
            logger.error(f"LLM Call Error ({provider}/{model}): {e}")

            # retry on alternative providers first, then use configured local fallback.
            if cloud_fallback and cloud_available:
                for cand in llm_adapter.provider_priority(task_type=task_type, budget_mode=budget_mode):
                    if cand == provider:
                        continue
                    if self._provider_cooldown_active(cand):
                        continue
                    try:
                        c = self._get_client(cand)
                        if not c:
                            continue
                        cand_model = _model_for_provider_task(cand, task_type, strategy)
                        if cand == 'gemini':
                            out = self._call_gemini(c, cand_model, prompt, system, json_mode, max_tokens=max_tokens)
                        elif cand == 'anthropic':
                            out = self._call_anthropic(c, cand_model, prompt, system, json_mode)
                        else:
                            out = self._call_openai_compat(c, cand_model, prompt, system, json_mode, provider=cand, max_tokens=max_tokens)
                        
                        provider_policy.record_event(
                            role='serve', provider=cand, model=cand_model, task_type=task_type, outcome='fallback_ok', notes=f'fallback_from={provider}',
                            artifact_count=1 if str(out or '').strip() else 0,
                            trace_payload={
                                'problem': str(prompt or '')[:500],
                                'response_excerpt': str(out or '')[:500],
                                'strategy': f'llm_fallback::{cand}',
                                'steps': [
                                    {'step': 1, 'kind': 'provider_error', 'detail': f'fallback_from={provider}'},
                                    {'step': 2, 'kind': 'provider_response', 'detail': str(out or '')[:240]}],
                                'artifacts': ['llm_response', 'fallback_success'],
                                'artifact_refs': [f'provider://{cand}/{cand_model}'],
                                'expected_effect': {'kind': 'fallback_provider_assist', 'goal': 'manter continuidade sem travar o ciclo'},
                                'observed_effect': {'kind': 'fallback_provider_response', 'success': True, 'fallback_from': provider},
                                'cloud_dependency_intent': 'fallback_bridge_to_keep_local_loop_alive',
                                'work_context': {'budget_mode': budget_mode, 'role': 'serve', 'fallback_from': provider},
                            })
                        return out
                    except Exception as e3:
                        self._touch(cand, ok=False, err=str(e3))
                        logger.warning("LLM fallback error (%s/%s): %s", cand, cand_model, str(e3)[:220])
                        continue

                local_retry_order = []
                primary_local = str(PRIMARY_LOCAL_PROVIDER or '').strip().lower()
                for cand in [primary_local, 'ultron_infer', 'ollama_local']:
                    if cand and cand not in local_retry_order and cand != provider:
                        local_retry_order.append(cand)
                for cand in local_retry_order:
                    try:
                        c = self._get_client(cand)
                        if not c:
                            continue
                        if cand == 'ultron_infer':
                            return self._call_ultron_infer(c, MODELS['local']['model'], prompt, system, json_mode, max_tokens=max_tokens)
                        if cand in ('ollama_local', 'ollama'):
                            return self._call_ollama(c, MODELS['local']['model'], prompt, system, json_mode, max_tokens=max_tokens, provider_label=cand)
                    except Exception as e2:
                        self._touch(cand, ok=False, err=str(e2))
                        continue

            if ALLOW_OLLAMA_FALLBACK:
                try:
                    ocli = self._get_client('ollama')
                    if ocli:
                        return self._call_ollama(ocli, MODELS['local']['model'], prompt, system, json_mode, max_tokens=max_tokens)
                except Exception as e2:
                    self._touch('ollama', ok=False, err=str(e2))

            return ""

    def _chat_messages(self, prompt: str, system: str | None) -> list[dict]:
        messages = []
        if system:
            messages.append({"role": "system", "content": str(system)})
        messages.append({"role": "user", "content": str(prompt or "")})
        return messages

    def _call_ollama(self, client, model, prompt, system, json_mode, max_tokens: int | None = None, provider_label: str = 'ollama_local'):
        base = str((client or {}).get('base_url') or os.getenv('OLLAMA_BASE_URL', 'http://127.0.0.1:11434')).rstrip('/')
        timeout_sec = float((client or {}).get('timeout') or _env_float('ULTRON_OLLAMA_TIMEOUT_SEC', 45.0))
        messages = self._chat_messages(prompt, system)
        if json_mode:
            messages[-1]["content"] = str(messages[-1]["content"]) + "\n\nReturn ONLY valid JSON."
        body = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": 0.2,
                "num_predict": int(max(32, min(4096, int(max_tokens or 256)))),
            },
        }
        if json_mode:
            body["format"] = "json"
        with httpx.Client(timeout=max(10.0, timeout_sec)) as hc:
            rr = hc.post(base + '/api/chat', json=body)
            rr.raise_for_status()
            data = rr.json() if rr.text else {}
        msg = data.get('message') if isinstance(data, dict) else {}
        text = str((msg or {}).get('content') or data.get('response') or '').strip()
        self._touch(provider_label, ok=bool(text))
        return text

    def _call_ultron_infer(self, client, model, prompt, system, json_mode, max_tokens: int | None = None):
        base = str((client or {}).get('base_url') or os.getenv('ULTRON_LOCAL_INFER_URL', 'http://127.0.0.1:8025')).rstrip('/')
        token = str((client or {}).get('token') or os.getenv('ULTRON_LOCAL_INFER_TOKEN', '')).strip()
        timeout_sec = float((client or {}).get('timeout') or _env_float('ULTRON_INFER_TIMEOUT_SEC', 45.0))
        headers = {'x-api-key': token} if token else {}
        last_err: Exception | None = None
        if os.getenv('ULTRON_INFER_BINARY_CLIENT_ENABLED', '1') == '1':
            try:
                from ultronpro import binary_protocol

                host, port = binary_protocol.binary_endpoint_from_base(
                    base,
                    default_port=int(os.getenv('ULTRON_LOCAL_INFER_BINARY_PORT', '8026') or 8026),
                )
                connect_timeout = _env_float('ULTRON_INFER_BINARY_CONNECT_TIMEOUT_SEC', 0.35)
                decoded = binary_protocol.infer_via_binary_tcp(
                    host=host,
                    port=port,
                    token=token,
                    model=model,
                    prompt=str(prompt or ''),
                    system=system,
                    max_tokens=int(max_tokens or 256),
                    temperature=0.2,
                    json_mode=bool(json_mode),
                    timeout_sec=timeout_sec,
                    connect_timeout_sec=connect_timeout,
                )
                text = str(decoded.get('text') or '').strip()
                if text:
                    self._touch('ultron_infer', ok=True)
                    return text
            except Exception as e:
                last_err = e
                logger.debug("ultron_infer binary transport unavailable; falling back to HTTP: %s", e)
        messages = self._chat_messages(prompt, system)
        if json_mode:
            messages[-1]["content"] = str(messages[-1]["content"]) + "\n\nReturn ONLY valid JSON."
        body = {
            "model": model,
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": int(max(32, min(4096, int(max_tokens or 256)))),
            "stream": False,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        with httpx.Client(timeout=max(10.0, timeout_sec)) as hc:
            for path in ('/v1/chat/completions', '/chat/completions'):
                try:
                    rr = hc.post(base + path, json=body, headers=headers)
                    rr.raise_for_status()
                    data = rr.json() if rr.text else {}
                    choices = data.get('choices') if isinstance(data, dict) else []
                    if choices:
                        msg = (choices[0] or {}).get('message') or {}
                        text = str(msg.get('content') or (choices[0] or {}).get('text') or '').strip()
                        if text:
                            self._touch('ultron_infer', ok=True)
                            return text
                except Exception as e:
                    last_err = e
            try:
                rr = hc.post(base + '/generate', json={'prompt': str(prompt or ''), 'model': model, 'max_tokens': int(max_tokens or 256)}, headers=headers)
                rr.raise_for_status()
                data = rr.json() if rr.text else {}
                text = str(data.get('text') or data.get('response') or data.get('content') or '').strip()
                if text:
                    self._touch('ultron_infer', ok=True)
                    return text
            except Exception as e:
                last_err = e
        raise RuntimeError(str(last_err or 'ultron_infer_empty_response'))

    def _call_gemini(self, client, model, prompt, system, json_mode, max_tokens: int | None = None):
        api_key = str((client or {}).get('api_key') or '').strip()
        base = str((client or {}).get('base_url') or 'https://generativelanguage.googleapis.com/v1beta').rstrip('/')
        timeout_sec = float((client or {}).get('timeout') or _env_float('ULTRON_GEMINI_TIMEOUT_SEC', 15.0))
        text_prompt = str(prompt or '')
        if json_mode:
            text_prompt += "\n\nReturn ONLY valid JSON."
        body = {
            'contents': [{'parts': [{'text': text_prompt}]}],
            'generationConfig': {
                'temperature': 0.2,
                'maxOutputTokens': int(max(32, min(512, int(max_tokens or int(os.getenv('ULTRON_CLOUD_MAX_TOKENS', '220') or 220))))),
            },
        }
        if system:
            body['systemInstruction'] = {'parts': [{'text': str(system)}]}
        if json_mode:
            body['generationConfig']['responseMimeType'] = 'application/json'
        url = f"{base}/models/{model}:generateContent?key={api_key}"
        with httpx.Client(timeout=max(8.0, timeout_sec)) as hc:
            rr = hc.post(url, json=body, headers={'Content-Type': 'application/json'})
            rr.raise_for_status()
            data = rr.json() if rr.text else {}
        text = ''
        for cand in data.get('candidates', []) or []:
            content = cand.get('content') or {}
            for part in content.get('parts', []) or []:
                if isinstance(part, dict) and part.get('text'):
                    text += str(part.get('text'))
        usage = data.get('usageMetadata') or {}
        tin = int(usage.get('promptTokenCount') or 0)
        tout = int(usage.get('candidatesTokenCount') or usage.get('outputTokenCount') or 0)
        self._touch('gemini', ok=True, tin=tin, tout=tout)
        return text

    def _call_openai_compat(self, client, model, prompt, system, json_mode, provider='openai', max_tokens: int | None = None):
        messages = []
        if system: messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        # Hard cap for cloud costs (prevents providers defaulting to huge max_tokens like 65536).
        # Exception: if the caller explicitly requests more tokens (e.g. chat synthesis passes 4096),
        # respect it up to 4096 so that chat responses are not truncated to 220 chars.
        cap_env = int(os.getenv('ULTRON_CLOUD_MAX_TOKENS', '220') or 220)
        explicit_large = isinstance(max_tokens, int) and max_tokens > cap_env
        req_max = int(max_tokens) if isinstance(max_tokens, int) and max_tokens > 0 else cap_env
        hard_cap = int(max(cap_env, min(4096, int(max_tokens or cap_env)))) if explicit_large else cap_env
        req_max = int(max(32, min(hard_cap, req_max)))

        kwargs = {"model": model, "messages": messages, "temperature": 0.3, "max_tokens": req_max}
        if json_mode and "groq" not in str(getattr(client, 'base_url', '')):
            kwargs["response_format"] = {"type": "json_object"}

        # model rotation on quota/support failures
        def _model_candidates(pv: str, primary: str) -> list[str]:
            out = [str(primary or '').strip()]
            if pv == 'huggingface':
                raw = os.getenv('HUGGINGFACE_FALLBACK_MODELS', 'zai-org/GLM-5,zai-org/GLM-4.5-Air,meta-llama/Llama-3.2-1B-Instruct')
                out.extend([x.strip() for x in raw.split(',') if x.strip()])
            elif pv == 'openrouter':
                raw = os.getenv('OPENROUTER_FALLBACK_MODELS', 'google/gemma-2-9b-it:free,meta-llama/llama-3.2-3b-instruct:free,microsoft/phi-3-mini-128k-instruct:free')
                out.extend([x.strip() for x in raw.split(',') if x.strip()])
            # keep order + dedup
            dedup = []
            seen = set()
            for m in out:
                if m and m not in seen:
                    dedup.append(m); seen.add(m)
            return dedup

        last_err = None
        for mdl in _model_candidates(provider, model):
            try:
                local_kwargs = dict(kwargs)
                local_kwargs['model'] = mdl
                res = client.chat.completions.create(**local_kwargs)
                usage = getattr(res, 'usage', None)
                tin = int(getattr(usage, 'prompt_tokens', 0) or 0) if usage is not None else 0
                tout = int(getattr(usage, 'completion_tokens', 0) or 0) if usage is not None else 0
                self._touch(provider, ok=True, tin=tin, tout=tout)
                return res.choices[0].message.content
            except Exception as e:
                last_err = e
                em = str(e).lower()
                retriable_model = any(t in em for t in [
                    'model_not_supported', 'not supported', 'insufficient credits', 'requires more credits',
                    'depleted your monthly included credits', '402', 'payment required'
                ])
                if retriable_model:
                    continue
                raise

        raise last_err if last_err else RuntimeError('openai_compat_failed')

    def _call_anthropic(self, client, model, prompt, system, json_mode):
        kwargs = {
            "model": model, 
            "max_tokens": 4096, 
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3
        }
        if system: kwargs["system"] = system
        if json_mode: kwargs["messages"][0]["content"] += "\nReturn ONLY valid JSON."
            
        res = client.messages.create(**kwargs)
        usage = getattr(res, 'usage', None)
        tin = int(getattr(usage, 'input_tokens', 0) or 0) if usage is not None else 0
        tout = int(getattr(usage, 'output_tokens', 0) or 0) if usage is not None else 0
        self._touch('anthropic', ok=True, tin=tin, tout=tout)
        return res.content[0].text

    def _call_openclaw_bridge(self, client, prompt, system, json_mode, max_tokens: int | None = None):
        msg = str(prompt or '').strip()
        if system:
            msg = f"System: {str(system).strip()}\n\nUser: {msg}"
        if json_mode:
            msg += "\n\nReturn ONLY valid JSON."

        timeout_sec = int((client or {}).get('timeout') or _env_int('OPENCLAW_BRIDGE_TIMEOUT_SEC', 120))

        # Preferred path: HTTP bridge service on host
        br_url = str((client or {}).get('url') or '').strip()
        if br_url:
            try:
                with httpx.Client(timeout=max(20.0, float(timeout_sec))) as hc:
                    rr = hc.post(br_url, json={'message': msg, 'max_tokens': int(max_tokens or 256)})
                    rr.raise_for_status()
                    j = rr.json() if rr.text else {}
                txt = str(j.get('text') or '').strip()
                if txt:
                    self._touch('openclaw_bridge', ok=True)
                    return txt
            except Exception as e:
                self._touch('openclaw_bridge', ok=False, err=str(e))

        # Fallback path: local CLI
        sess = f"{(client or {}).get('session_prefix','ulbridge')}-{uuid.uuid4().hex[:10]}"
        agent_id = str((client or {}).get('agent') or 'bridge')
        cmd = [
            'openclaw', 'agent', '--local', '--agent', agent_id,
            '--session-id', sess,
            '--message', msg,
            '--json', '--timeout', str(timeout_sec)
        ]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=max(30, timeout_sec + 20))
        if p.returncode != 0:
            raise RuntimeError((p.stderr or p.stdout or 'openclaw_bridge_failed')[:400])

        out = json.loads((p.stdout or '').strip() or '{}')
        payloads = out.get('payloads') or []
        text = ''
        if payloads and isinstance(payloads[0], dict):
            text = str(payloads[0].get('text') or '').strip()
        if not text:
            raise RuntimeError('openclaw_bridge_empty_reply')

        meta = (out.get('meta') or {}).get('agentMeta') or {}
        usage = meta.get('usage') or {}
        tin = int(usage.get('input') or 0)
        tout = int(usage.get('output') or 0)
        self._touch('openclaw_bridge', ok=True, tin=tin, tout=tout)
        return text


router = LLMRouter()
def complete(prompt: str, strategy: str = "default", system: str = None, json_mode: bool = False, inject_persona: bool = True, max_tokens: int | None = None, cloud_fallback: bool = True, input_class: str | None = None) -> str:
    return router.complete(prompt, strategy, system, json_mode, inject_persona=inject_persona, max_tokens=max_tokens, cloud_fallback=cloud_fallback, input_class=input_class)


def last_call_meta() -> dict:
    return dict(router.last_call_meta or {})

def usage_status() -> dict:
    return router.usage_status()


def response_cache_status() -> dict:
    return _response_cache_status()

def healthcheck(provider: str = 'auto') -> dict:
    return router.healthcheck(provider)


def router_status(task_type: str = 'general', budget_mode: str | None = None) -> dict:
    mode = str(budget_mode or os.getenv('ULTRON_LLM_BUDGET_MODE', 'balanced')).strip().lower()
    cloud_available = (os.getenv('ULTRON_DISABLE_CLOUD_PROVIDERS', '0') != '1')
    availability: dict[str, bool] = {}
    provider_details: dict[str, dict[str, Any]] = {}

    def _probe(p: str) -> bool:
        pv = str(p or '').strip().lower()
        disabled = _is_provider_disabled(pv)
        quarantined = False
        cooldown_active = False
        has_key = False
        client_ready = False
        reason = 'unavailable'

        if disabled:
            reason = 'disabled'
        else:
            try:
                quarantined = bool(llm_adapter.is_provider_quarantined(pv))
            except Exception:
                quarantined = False
            cooldown_active = bool(router._provider_cooldown_active(pv))
            has_key = bool(_provider_has_key(pv))
            if quarantined:
                reason = 'quarantined'
            elif cooldown_active:
                reason = 'cooldown'
            elif not has_key:
                reason = 'missing_key'
            else:
                client_ready = router._get_client(pv) is not None
                reason = 'ready' if client_ready else 'client_unavailable'

        available = bool((not disabled) and (not quarantined) and (not cooldown_active) and has_key and client_ready)
        availability[pv] = available
        provider_details[pv] = {
            'available': available,
            'reason': reason,
            'has_key': has_key,
            'disabled': disabled,
            'quarantined': quarantined,
            'cooldown_active': cooldown_active,
            'default_model': llm_adapter.provider_default_model(pv),
        }
        return available

    routed = llm_adapter.route_provider(
        task_type=task_type,
        budget_mode=mode,
        cloud_available=cloud_available,
        has_provider=_probe)
    priority = llm_adapter.provider_priority(task_type=task_type, budget_mode=mode)
    for p in priority:
        provider_details.setdefault(str(p or '').strip().lower(), {})
        if str(p or '').strip().lower() not in availability:
            _probe(p)

    selected_provider = str((routed or {}).get('provider') or '').strip().lower()
    selected_runtime_model = str((routed or {}).get('model') or llm_adapter.provider_default_model(selected_provider))
    if selected_provider:
        provider_details.setdefault(selected_provider, {})
        provider_details[selected_provider]['selected'] = True
        provider_details[selected_provider]['runtime_model'] = selected_runtime_model

    return {
        'budget_mode': mode,
        'task_type': task_type,
        'cloud_available': cloud_available,
        'selected': {
            **dict(routed or {}),
            'task_type': task_type,
            'budget_mode': mode,
        },
        'priority': priority,
        'availability': availability,
        'providers': provider_details,
        'policy': {
            'priority': priority,
            'history_min_n': int(os.getenv('ULTRON_PROVIDER_HISTORY_MIN_N', '6') or 6),
            'prefer_ultron_infer': os.getenv('ULTRON_PREFER_ULTRON_INFER', '1') == '1',
            'primary_local_provider': str(PRIMARY_LOCAL_PROVIDER or 'ultron_infer'),
            'primary_local_model': str(PRIMARY_LOCAL_MODEL or ''),
            'canary_provider': str(CANARY_PROVIDER or ''),
            'canary_model': str(CANARY_MODEL or ''),
            'allow_ollama_fallback': bool(ALLOW_OLLAMA_FALLBACK),
        },
        'history': llm_adapter.get_perf_snapshot().get('procedural', {}),
        'quarantine': llm_adapter.quarantine_status(),
        'last_call_meta': last_call_meta(),
    }
