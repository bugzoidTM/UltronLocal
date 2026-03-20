import os
import logging
import subprocess
import uuid
import json
from pathlib import Path
from typing import Dict, Optional, Any
import httpx
import time
from ultronpro.settings import get_api_key
from ultronpro import persona, llm_adapter

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


# LLM Routing Strategy
PRIMARY_LOCAL_PROVIDER = os.getenv('ULTRON_PRIMARY_LOCAL_PROVIDER', 'ollama_local').strip().lower() or 'ollama_local'
PRIMARY_LOCAL_MODEL = os.getenv('ULTRON_PRIMARY_LOCAL_MODEL', os.getenv('OLLAMA_CANARY_MODEL', 'qwen2.5:3b-instruct-q4_K_M'))
CANARY_PROVIDER = os.getenv('ULTRON_CANARY_PROVIDER', PRIMARY_LOCAL_PROVIDER).strip().lower() or PRIMARY_LOCAL_PROVIDER
CANARY_MODEL = os.getenv('ULTRON_CANARY_MODEL_NAME', os.getenv('OLLAMA_CANARY_MODEL', 'qwen2.5:7b-instruct-q4_K_M'))
PREFER_ULTRON_INFER = os.getenv('ULTRON_PREFER_ULTRON_INFER', '0') == '1'

MODELS = {
    "default": {"provider": PRIMARY_LOCAL_PROVIDER, "model": PRIMARY_LOCAL_MODEL},
    "cheap": {"provider": "groq", "model": os.getenv('GROQ_DEFAULT_MODEL', 'llama-3.3-70b-versatile')},
    "reasoning": {"provider": PRIMARY_LOCAL_PROVIDER, "model": PRIMARY_LOCAL_MODEL},
    "creative": {"provider": PRIMARY_LOCAL_PROVIDER, "model": PRIMARY_LOCAL_MODEL},
    "deep": {"provider": PRIMARY_LOCAL_PROVIDER, "model": PRIMARY_LOCAL_MODEL},
    "openai_default": {"provider": "openai", "model": os.getenv('OPENAI_DEFAULT_MODEL', 'gpt-4o-mini')},
    "anthropic_default": {"provider": "anthropic", "model": os.getenv('ANTHROPIC_DEFAULT_MODEL', 'claude-3-5-sonnet-20241022')},
    "deepseek_default": {"provider": "deepseek", "model": os.getenv('DEEPSEEK_DEFAULT_MODEL', 'deepseek-chat')},
    "openrouter_free": {"provider": "openrouter", "model": os.getenv('OPENROUTER_DEFAULT_MODEL', 'google/gemma-2-9b-it:free')},
    "gemini_default": {"provider": "gemini", "model": os.getenv('GEMINI_DEFAULT_MODEL', 'gemini-3-flash-preview')},
    "hf_free": {"provider": "huggingface", "model": os.getenv('HUGGINGFACE_DEFAULT_MODEL', 'meta-llama/Llama-3.2-1B-Instruct')},
    "local": {"provider": PRIMARY_LOCAL_PROVIDER, "model": PRIMARY_LOCAL_MODEL},
    "canary_qwen": {"provider": CANARY_PROVIDER, "model": CANARY_MODEL}
}

ALLOW_OLLAMA_FALLBACK = os.getenv('ULTRON_ALLOW_OLLAMA_FALLBACK', '0') == '1'


def _is_provider_disabled(provider: str) -> bool:
    p = str(provider or '').strip().lower()
    # global kill-switch for external cloud providers
    if os.getenv('ULTRON_DISABLE_CLOUD_PROVIDERS', '0') == '1' and p in ('huggingface', 'openrouter', 'groq', 'deepseek', 'openai', 'anthropic', 'gemini'):
        return True
    env_map = {
        'huggingface': 'ULTRON_DISABLE_HUGGINGFACE',
        'openrouter': 'ULTRON_DISABLE_OPENROUTER',
        'groq': 'ULTRON_DISABLE_GROQ',
        'deepseek': 'ULTRON_DISABLE_DEEPSEEK',
        'openai': 'ULTRON_DISABLE_OPENAI',
        'anthropic': 'ULTRON_DISABLE_ANTHROPIC',
        'gemini': 'ULTRON_DISABLE_GEMINI',
        'ollama_local': 'ULTRON_DISABLE_OLLAMA_LOCAL',
        'ultron_infer': 'ULTRON_DISABLE_ULTRON_INFER',
    }
    ek = env_map.get(p)
    return bool(ek and os.getenv(ek, '0') == '1')

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
            p['errors'] = int(p.get('errors') or 0) + 1
        p['tokens_in'] = int(p.get('tokens_in') or 0) + int(tin or 0)
        p['tokens_out'] = int(p.get('tokens_out') or 0) + int(tout or 0)
        p['tokens_total'] = int(p.get('tokens_total') or 0) + int(tin or 0) + int(tout or 0)
        if err:
            em = str(err)
            self.usage['last_error'] = {'ts': int(time.time()), 'provider': provider, 'error': em[:220]}
            low = em.lower()
            # global backoff for known external failure states
            if provider in ('huggingface', 'openrouter', 'groq', 'deepseek', 'openai', 'anthropic', 'gemini'):
                if any(t in low for t in ['402', '429', 'rate limit', 'insufficient credits', 'depleted your monthly included credits', 'model_not_supported', 'no endpoints found', 'payment required']):
                    if provider == 'gemini':
                        cool_sec = int(os.getenv('ULTRON_GEMINI_FAILURE_COOLDOWN_SEC', '15') or 15)
                        self.fail_cooldown_until[str(provider)] = int(time.time()) + max(3, cool_sec)
                    else:
                        cool_sec = int(os.getenv('ULTRON_PROVIDER_FAILURE_COOLDOWN_SEC', '900') or 900)
                        self.fail_cooldown_until[str(provider)] = int(time.time()) + max(60, cool_sec)
                try:
                    if not (provider == 'gemini' and any(t in low for t in ['429', 'rate limit'])):
                        llm_adapter.maybe_quarantine_provider(provider, em)
                except Exception:
                    pass

    def _provider_cooldown_active(self, provider: str) -> bool:
        ts = int(self.fail_cooldown_until.get(str(provider or ''), 0) or 0)
        return ts > int(time.time())

    def usage_status(self) -> dict:
        out = {'started_at': self.usage.get('started_at'), 'providers': {}, 'last_error': self.usage.get('last_error')}
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
            for cand in ('gemini', 'ultron_infer', 'ollama_local', 'huggingface', 'openrouter', 'openai', 'anthropic', 'groq', 'deepseek', 'ollama', 'openclaw_bridge'):
                r = self.healthcheck(cand)
                if r.get('ok'):
                    return r
            return {'ok': False, 'provider': 'auto', 'error': 'no_provider_healthy'}

        c = self._get_client(p)
        if not c:
            return {'ok': False, 'provider': p, 'error': 'client_unavailable'}

        t0 = time.time()
        try:
            if p in ('ollama', 'ollama_local'):
                base = (c or {}).get('base_url') or os.getenv('OLLAMA_BASE_URL', 'http://127.0.0.1:11434')
                with httpx.Client(timeout=10.0) as hc:
                    rr = hc.get(base.rstrip('/') + '/api/tags')
                    rr.raise_for_status()
                dt = int((time.time() - t0) * 1000)
                return {'ok': True, 'provider': p, 'latency_ms': dt, 'check': 'tags'}

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
            }
            txt = self.complete(
                'Reply with OK only.',
                strategy=strategy_map.get(p, 'local'),
                system='Healthcheck probe.',
                json_mode=False,
            )
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
                        },
                    )
            elif provider == "huggingface":
                from openai import OpenAI
                if key:
                    client = OpenAI(
                        api_key=key,
                        base_url=os.getenv('HUGGINGFACE_BASE_URL', 'https://router.huggingface.co/v1'),
                        timeout=router_timeout,
                        max_retries=0,
                    )
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

        config = MODELS.get(strategy, MODELS["default"])
        provider = config["provider"]
        model = config["model"]

        # Unified adapter-based routing (Phase 6)
        budget_mode = os.getenv('ULTRON_LLM_BUDGET_MODE', 'economy').strip().lower()
        task_type = llm_adapter.classify_task_type(input_class=input_class, strategy=strategy)
        cloud_available = os.getenv('ULTRON_DISABLE_CLOUD_PROVIDERS', '0') != '1'

        def _has_provider(pv: str) -> bool:
            return self._get_client(pv) is not None

        routed = llm_adapter.route_provider(task_type=task_type, budget_mode=budget_mode, cloud_available=cloud_available, has_provider=_has_provider)
        provider = str(routed.get('provider') or provider)
        model = str(routed.get('model') or model)

        # local runtime providers rely on server-side active adapter marker

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
                        model = os.getenv('OLLAMA_CANARY_MODEL', MODELS['canary_qwen']['model'])
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
                first = self._get_client(first_provider)
                if first:
                    provider = first_provider
                    model = MODELS['local']['model'] if first_provider == 'ultron_infer' else os.getenv('OLLAMA_CANARY_MODEL', MODELS['canary_qwen']['model'])
                    client = first
                else:
                    second = self._get_client(second_provider)
                    if second:
                        provider = second_provider
                        model = MODELS['local']['model'] if second_provider == 'ultron_infer' else os.getenv('OLLAMA_CANARY_MODEL', MODELS['canary_qwen']['model'])
                        client = second
                    else:
                        client = self._get_client(provider)
        elif strategy in ('cheap',):
            cloud_disabled = os.getenv('ULTRON_DISABLE_CLOUD_PROVIDERS', '0') == '1'
            if not cloud_disabled:
                # Prefer HF free router when configured, then OpenRouter free
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
                    model = os.getenv('OLLAMA_CANARY_MODEL', MODELS['canary_qwen']['model'])
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
        if not client and cloud_fallback:
            for cand in llm_adapter.provider_priority(task_type=task_type, budget_mode=budget_mode):
                if cand in ('ollama_local', 'ultron_infer', provider):
                    continue
                c = self._get_client(cand)
                if c:
                    provider = cand
                    if cand == 'groq':
                        model = MODELS['cheap']['model']
                    elif cand == 'deepseek':
                        model = MODELS['deep']['model']
                    elif cand == 'openrouter':
                        model = MODELS['openrouter_free']['model']
                    elif cand == 'gemini':
                        model = MODELS['gemini_default']['model']
                    elif cand == 'huggingface':
                        model = MODELS['hf_free']['model']
                    elif cand == 'openai':
                        model = 'gpt-4o-mini'
                    else:
                        model = 'claude-3-5-sonnet-20241022'
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

        self.last_call_meta = {'provider': provider, 'model': model, 'task_type': task_type, 'budget_mode': budget_mode}
        try:
            if provider == "anthropic":
                return self._call_anthropic(client, model, prompt, system, json_mode)
            if provider == 'gemini':
                return self._call_gemini(client, model, prompt, system, json_mode, max_tokens=max_tokens)
            if provider == 'openclaw_bridge':
                return self._call_openclaw_bridge(client, prompt, system, json_mode, max_tokens=max_tokens)
            if provider in ('ollama', 'ollama_local'):
                return self._call_ollama(client, model, prompt, system, json_mode, max_tokens=max_tokens, provider_label=provider)
            if provider == 'ultron_infer':
                return self._call_ultron_infer(client, model, prompt, system, json_mode, max_tokens=max_tokens)
            return self._call_openai_compat(client, model, prompt, system, json_mode, provider=provider, max_tokens=max_tokens)
        except Exception as e:
            self._touch(provider, ok=False, err=str(e))
            logger.error(f"LLM Call Error ({provider}/{model}): {e}")

            # retry on alternative providers before touching local
            if cloud_fallback:
                for cand in llm_adapter.provider_priority(task_type=task_type, budget_mode=budget_mode):
                    if cand in ('ollama_local', 'ultron_infer') or cand == provider:
                        continue
                    try:
                        c = self._get_client(cand)
                        if not c:
                            continue
                        if cand == 'huggingface':
                            return self._call_openai_compat(c, MODELS['hf_free']['model'], prompt, system, json_mode, provider='huggingface', max_tokens=max_tokens)
                        if cand == 'gemini':
                            return self._call_gemini(c, MODELS['gemini_default']['model'], prompt, system, json_mode, max_tokens=max_tokens)
                        if cand == 'anthropic':
                            return self._call_anthropic(c, 'claude-3-5-sonnet-20241022', prompt, system, json_mode)
                        if cand == 'deepseek':
                            return self._call_openai_compat(c, MODELS['deep']['model'], prompt, system, json_mode, provider='deepseek', max_tokens=max_tokens)
                        if cand == 'openrouter':
                            return self._call_openai_compat(c, MODELS['openrouter_free']['model'], prompt, system, json_mode, provider='openrouter', max_tokens=max_tokens)
                        if cand == 'groq':
                            return self._call_openai_compat(c, MODELS['cheap']['model'], prompt, system, json_mode, provider='groq', max_tokens=max_tokens)
                        return self._call_openai_compat(c, 'gpt-4o-mini', prompt, system, json_mode, provider='openai', max_tokens=max_tokens)
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

        # Hard cap for cloud costs (prevents providers defaulting to huge max_tokens like 65536)
        cap_env = int(os.getenv('ULTRON_CLOUD_MAX_TOKENS', '220') or 220)
        req_max = int(max_tokens) if isinstance(max_tokens, int) and max_tokens > 0 else cap_env
        req_max = int(max(32, min(cap_env, req_max)))

        kwargs = {"model": model, "messages": messages, "temperature": 0.3, "max_tokens": req_max}
        if json_mode and "groq" not in str(client.base_url):
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

        # Fallback path: local CLI (works only if openclaw binary exists in this runtime)
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

    def _call_ollama(self, client, model, prompt, system, json_mode, max_tokens: int | None = None, provider_label: str = 'ollama'):
        base = (client or {}).get('base_url') or os.getenv('OLLAMA_BASE_URL', 'http://127.0.0.1:11434')
        body_prompt = prompt
        if system:
            body_prompt = f"[SYSTEM]\n{system}\n\n[USER]\n{prompt}"
        if json_mode:
            body_prompt += "\n\nReturn ONLY valid JSON."
        options = {'temperature': 0.2}
        if max_tokens is not None:
            options['num_predict'] = int(max(16, min(512, max_tokens)))
        payload = {
            'model': model,
            'prompt': body_prompt,
            'stream': False,
            'options': options
        }
        timeout_sec = _env_float('ULTRON_OLLAMA_TIMEOUT_SEC', 60.0)
        with httpx.Client(timeout=max(5.0, timeout_sec)) as hc:
            r = hc.post(base.rstrip('/') + '/api/generate', json=payload)
            r.raise_for_status()
            data = r.json()
            tin = int(data.get('prompt_eval_count') or 0)
            tout = int(data.get('eval_count') or 0)
            self._touch(provider_label or 'ollama', ok=True, tin=tin, tout=tout)
            return str(data.get('response') or '')

    def _call_ultron_infer(self, client, model, prompt, system, json_mode, max_tokens: int | None = None):
        base = (client or {}).get('base_url') or os.getenv('ULTRON_LOCAL_INFER_URL', 'http://127.0.0.1:8025')
        token = (client or {}).get('token') or os.getenv('ULTRON_LOCAL_INFER_TOKEN', '').strip()
        body_prompt = prompt + ('\n\nReturn ONLY valid JSON.' if json_mode else '')
        req_max = int(max(32, min(256, max_tokens or 160)))
        mode = 'deep' if req_max >= 180 else 'balanced'
        payload = {
            'prompt': body_prompt,
            'system': system,
            'max_new_tokens': req_max,
            'temperature': 0.2,
            'mode': mode,
        }
        headers = {'x-api-key': token} if token else {}
        last_err = None
        base_timeout = _env_float('ULTRON_LOCAL_INFER_TIMEOUT_SEC', 18.0)
        retry_timeout = _env_float('ULTRON_LOCAL_INFER_RETRY_TIMEOUT_SEC', max(base_timeout + 10.0, 28.0))
        for to in (base_timeout, retry_timeout):
            try:
                with httpx.Client(timeout=to) as hc:
                    r = hc.post(base.rstrip('/') + '/generate', json=payload, headers=headers)
                    r.raise_for_status()
                    data = r.json()
                    txt = str(data.get('text') or '')
                    self._touch('ultron_infer', ok=True, tin=max(0, len(body_prompt)//4), tout=max(0, len(txt)//4))
                    return txt
            except Exception as e:
                last_err = e
        raise last_err if last_err else RuntimeError('ultron_infer_failed')

router = LLMRouter()
def complete(prompt: str, strategy: str = "default", system: str = None, json_mode: bool = False, inject_persona: bool = True, max_tokens: int | None = None, cloud_fallback: bool = True, input_class: str | None = None) -> str:
    return router.complete(prompt, strategy, system, json_mode, inject_persona=inject_persona, max_tokens=max_tokens, cloud_fallback=cloud_fallback, input_class=input_class)


def last_call_meta() -> dict:
    return dict(router.last_call_meta or {})

def usage_status() -> dict:
    return router.usage_status()

def healthcheck(provider: str = 'auto') -> dict:
    return router.healthcheck(provider)


def router_status(task_type: str = 'general', budget_mode: str | None = None) -> dict:
    mode = str(budget_mode or os.getenv('ULTRON_LLM_BUDGET_MODE', 'economy')).strip().lower()
    def _has(p: str) -> bool:
        return router._get_client(p) is not None
    routed = llm_adapter.route_provider(task_type=task_type, budget_mode=mode, cloud_available=(os.getenv('ULTRON_DISABLE_CLOUD_PROVIDERS', '0') != '1'), has_provider=_has)
    return {
        'budget_mode': mode,
        'task_type': task_type,
        'selected': routed,
        'priority': llm_adapter.provider_priority(task_type=task_type, budget_mode=mode),
        'history': llm_adapter.get_perf_snapshot().get('procedural', {}),
        'quarantine': llm_adapter.quarantine_status(),
        'last_call_meta': last_call_meta(),
    }
