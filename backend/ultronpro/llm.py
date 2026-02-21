import os
import logging
from typing import Dict, Optional, Any
import httpx
import time
from ultronpro.settings import get_api_key
from ultronpro import persona

# --- API Models ---
from pydantic import BaseModel

class SettingsUpdate(BaseModel):
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    groq_api_key: Optional[str] = None
    deepseek_api_key: Optional[str] = None
    lightrag_api_key: Optional[str] = None

logger = logging.getLogger("uvicorn")

# LLM Routing Strategy
MODELS = {
    "default": {"provider": "deepseek", "model": "deepseek-chat"},
    "cheap": {"provider": "deepseek", "model": "deepseek-chat"},
    "reasoning": {"provider": "deepseek", "model": "deepseek-reasoner"},
    "creative": {"provider": "deepseek", "model": "deepseek-chat"},
    "deep": {"provider": "deepseek", "model": "deepseek-reasoner"},
    "local": {"provider": "ollama", "model": os.getenv('OLLAMA_MODEL', 'llama3.2:1b')}
}

ALLOW_OLLAMA_FALLBACK = os.getenv('ULTRON_ALLOW_OLLAMA_FALLBACK', '0') == '1'

class LLMRouter:
    def __init__(self):
        # Clients cache
        self.clients = {}
        self.usage = {
            'started_at': int(time.time()),
            'providers': {
                'openai': {'calls': 0, 'ok': 0, 'errors': 0, 'tokens_in': 0, 'tokens_out': 0, 'tokens_total': 0, 'limit_tokens': int(os.getenv('OPENAI_DAILY_LIMIT_TOKENS', '0') or 0)},
                'anthropic': {'calls': 0, 'ok': 0, 'errors': 0, 'tokens_in': 0, 'tokens_out': 0, 'tokens_total': 0, 'limit_tokens': int(os.getenv('ANTHROPIC_DAILY_LIMIT_TOKENS', '0') or 0)},
                'groq': {'calls': 0, 'ok': 0, 'errors': 0, 'tokens_in': 0, 'tokens_out': 0, 'tokens_total': 0, 'limit_tokens': int(os.getenv('GROQ_TPD_LIMIT', '100000') or 100000)},
                'deepseek': {'calls': 0, 'ok': 0, 'errors': 0, 'tokens_in': 0, 'tokens_out': 0, 'tokens_total': 0, 'limit_tokens': int(os.getenv('DEEPSEEK_DAILY_LIMIT_TOKENS', '0') or 0)},
                'ollama': {'calls': 0, 'ok': 0, 'errors': 0, 'tokens_in': 0, 'tokens_out': 0, 'tokens_total': 0, 'limit_tokens': 0},
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
            self.usage['last_error'] = {'ts': int(time.time()), 'provider': provider, 'error': str(err)[:220]}

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
            for cand in ('openai', 'anthropic', 'groq', 'deepseek', 'ollama'):
                r = self.healthcheck(cand)
                if r.get('ok'):
                    return r
            return {'ok': False, 'provider': 'auto', 'error': 'no_provider_healthy'}

        c = self._get_client(p)
        if not c:
            return {'ok': False, 'provider': p, 'error': 'client_unavailable'}

        t0 = time.time()
        try:
            if p == 'ollama':
                base = (c or {}).get('base_url') or os.getenv('OLLAMA_BASE_URL', 'http://127.0.0.1:11434')
                with httpx.Client(timeout=10.0) as hc:
                    rr = hc.get(base.rstrip('/') + '/api/tags')
                    rr.raise_for_status()
                dt = int((time.time() - t0) * 1000)
                return {'ok': True, 'provider': p, 'latency_ms': dt, 'check': 'tags'}

            # tiny generation probe (low token)
            txt = self.complete('Reply with OK only.', strategy='default' if p == 'openai' else ('cheap' if p == 'groq' else ('reasoning' if p == 'anthropic' else ('deep' if p == 'deepseek' else 'local'))), system='Healthcheck probe.', json_mode=False)
            dt = int((time.time() - t0) * 1000)
            return {'ok': bool((txt or '').strip()), 'provider': p, 'latency_ms': dt, 'sample': (txt or '')[:40]}
        except Exception as e:
            self._touch(p, ok=False, err=str(e))
            return {'ok': False, 'provider': p, 'error': str(e)[:220]}

    def _get_client(self, provider: str) -> Any:
        if provider in self.clients:
            return self.clients[provider]
        
        client = None
        try:
            key = get_api_key(provider)
            
            if provider == "openai":
                from openai import OpenAI
                if key: client = OpenAI(api_key=key, timeout=8.0, max_retries=0)
            elif provider == "anthropic":
                from anthropic import Anthropic
                if key: client = Anthropic(api_key=key, timeout=8.0, max_retries=0)
            elif provider == "groq":
                from groq import Groq
                if key: client = Groq(api_key=key, timeout=8.0, max_retries=0)
            elif provider == "deepseek":
                from openai import OpenAI
                if key: client = OpenAI(api_key=key, base_url="https://api.deepseek.com", timeout=8.0, max_retries=0)
            elif provider == "ollama":
                # local HTTP endpoint; no API key required
                client = {"base_url": os.getenv('OLLAMA_BASE_URL', 'http://127.0.0.1:11434')}
        except Exception as e:
            logger.error(f"Failed to init {provider}: {e}")

        if client:
            self.clients[provider] = client
            
        return client

    def complete(self, prompt: str, strategy: str = "default", system: str = None, json_mode: bool = False, inject_persona: bool = True, max_tokens: int | None = None) -> str:
        # runtime personality injection (dynamic system prompt + few-shot exemplars)
        if inject_persona:
            try:
                system = persona.build_system_prompt(system)
            except Exception:
                pass

        config = MODELS.get(strategy, MODELS["default"])
        provider = config["provider"]
        model = config["model"]
        
        # 1. Try preferred provider
        client = self._get_client(provider)
        
        # 2. Fallback chain across cloud providers first
        if not client:
            for cand in ('deepseek', 'openai', 'anthropic', 'groq'):
                c = self._get_client(cand)
                if c:
                    provider = cand
                    if cand == 'groq':
                        model = MODELS['cheap']['model']
                    elif cand == 'deepseek':
                        model = MODELS['deep']['model']
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

        try:
            if provider == "anthropic":
                return self._call_anthropic(client, model, prompt, system, json_mode)
            if provider == 'ollama':
                return self._call_ollama(client, model, prompt, system, json_mode, max_tokens=max_tokens)
            return self._call_openai_compat(client, model, prompt, system, json_mode, provider=provider)
        except Exception as e:
            self._touch(provider, ok=False, err=str(e))
            logger.error(f"LLM Call Error ({provider}/{model}): {e}")

            # retry on alternative cloud providers before touching local
            for cand in ('deepseek', 'openai', 'anthropic', 'groq'):
                if cand == provider:
                    continue
                try:
                    c = self._get_client(cand)
                    if not c:
                        continue
                    if cand == 'anthropic':
                        return self._call_anthropic(c, 'claude-3-5-sonnet-20241022', prompt, system, json_mode)
                    if cand == 'deepseek':
                        return self._call_openai_compat(c, MODELS['deep']['model'], prompt, system, json_mode, provider='deepseek')
                    if cand == 'groq':
                        return self._call_openai_compat(c, MODELS['cheap']['model'], prompt, system, json_mode, provider='groq')
                    return self._call_openai_compat(c, 'gpt-4o-mini', prompt, system, json_mode, provider='openai')
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

    def _call_openai_compat(self, client, model, prompt, system, json_mode, provider='openai'):
        messages = []
        if system: messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        
        kwargs = {"model": model, "messages": messages, "temperature": 0.3}
        if json_mode and "groq" not in str(client.base_url):
            kwargs["response_format"] = {"type": "json_object"}

        res = client.chat.completions.create(**kwargs)
        usage = getattr(res, 'usage', None)
        tin = int(getattr(usage, 'prompt_tokens', 0) or 0) if usage is not None else 0
        tout = int(getattr(usage, 'completion_tokens', 0) or 0) if usage is not None else 0
        self._touch(provider, ok=True, tin=tin, tout=tout)
        return res.choices[0].message.content

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

    def _call_ollama(self, client, model, prompt, system, json_mode, max_tokens: int | None = None):
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
        with httpx.Client(timeout=60.0) as hc:
            r = hc.post(base.rstrip('/') + '/api/generate', json=payload)
            r.raise_for_status()
            data = r.json()
            tin = int(data.get('prompt_eval_count') or 0)
            tout = int(data.get('eval_count') or 0)
            self._touch('ollama', ok=True, tin=tin, tout=tout)
            return str(data.get('response') or '')

router = LLMRouter()
def complete(prompt: str, strategy: str = "default", system: str = None, json_mode: bool = False, inject_persona: bool = True, max_tokens: int | None = None) -> str:
    return router.complete(prompt, strategy, system, json_mode, inject_persona=inject_persona, max_tokens=max_tokens)

def usage_status() -> dict:
    return router.usage_status()

def healthcheck(provider: str = 'auto') -> dict:
    return router.healthcheck(provider)
