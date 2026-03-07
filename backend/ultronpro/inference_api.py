from __future__ import annotations

import os
import json
import time
from pathlib import Path
from threading import Lock
from typing import Optional
import asyncio

import torch
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import PeftModel

# CPU stabilization knobs (safe defaults for VPS)
try:
    torch.set_num_threads(max(1, int(os.getenv('ULTRON_INFER_TORCH_THREADS', '2'))))
    torch.set_num_interop_threads(max(1, int(os.getenv('ULTRON_INFER_TORCH_INTEROP_THREADS', '1'))))
except Exception:
    pass

app = FastAPI(title='UltronPro Inference API', version='0.1.0')

API_TOKEN = str(os.getenv('ULTRON_LOCAL_INFER_TOKEN', '') or '').strip()
BASE_MODEL = str(os.getenv('ULTRON_FINETUNE_BASE_MODEL', 'TinyLlama/TinyLlama-1.1B-Chat-v1.0'))
RUNTIME_ACTIVE_ADAPTER = Path('/app/data/runtime_active_adapter.json')

_lock = Lock()
_infer_lock = asyncio.Lock()  # backpressure: single generation at a time
_state = {
    'loaded_base': None,
    'loaded_adapter': None,
    'tokenizer': None,
    'model': None,
    'last_loaded_at': 0,
}


class GenerateRequest(BaseModel):
    prompt: str
    system: Optional[str] = None
    max_new_tokens: int = 160
    temperature: float = 0.2
    mode: Optional[str] = 'balanced'  # fast | balanced | deep


def _auth_ok(x_api_key: str | None) -> bool:
    if not API_TOKEN:
        return True
    return bool(x_api_key and str(x_api_key).strip() == API_TOKEN)


def _active_adapter_path() -> str:
    try:
        if not RUNTIME_ACTIVE_ADAPTER.exists():
            return ''
        j = json.loads(RUNTIME_ACTIVE_ADAPTER.read_text(encoding='utf-8'))
        return str(j.get('adapter_path') or '').strip()
    except Exception:
        return ''


def _compose_prompt(system: str | None, prompt: str) -> str:
    s = str(system or '').strip()
    p = str(prompt or '').strip()
    if s:
        return f"<|system|>\n{s}\n<|user|>\n{p}\n<|assistant|>\n"
    return p


def _ensure_loaded():
    base = BASE_MODEL
    adapter = _active_adapter_path()

    with _lock:
        if _state['model'] is not None and _state['tokenizer'] is not None and _state['loaded_base'] == base and _state['loaded_adapter'] == adapter:
            return

        tok = AutoTokenizer.from_pretrained(base)
        mdl = AutoModelForCausalLM.from_pretrained(base)
        mdl.eval()

        if adapter and Path(adapter).exists():
            mdl = PeftModel.from_pretrained(mdl, adapter)

        _state['tokenizer'] = tok
        _state['model'] = mdl
        _state['loaded_base'] = base
        _state['loaded_adapter'] = adapter
        _state['last_loaded_at'] = int(time.time())


@app.get('/health')
async def health():
    return {
        'ok': True,
        'base_model': BASE_MODEL,
        'loaded_base': _state.get('loaded_base'),
        'loaded_adapter': _state.get('loaded_adapter'),
        'last_loaded_at': _state.get('last_loaded_at'),
    }


def _infer_sync(req: GenerateRequest) -> dict:
    _ensure_loaded()
    tok = _state['tokenizer']
    mdl = _state['model']
    if tok is None or mdl is None:
        raise RuntimeError('model_not_loaded')

    text = _compose_prompt(req.system, req.prompt)
    ins = tok(text, return_tensors='pt')

    mode = str(req.mode or 'balanced').strip().lower()
    if mode == 'fast':
        cap = int(os.getenv('ULTRON_INFER_MAX_NEW_TOKENS_FAST', '96'))
    elif mode == 'deep':
        cap = int(os.getenv('ULTRON_INFER_MAX_NEW_TOKENS_DEEP', '224'))
    else:
        cap = int(os.getenv('ULTRON_INFER_MAX_NEW_TOKENS_BALANCED', '144'))

    if mode == 'balanced' and len(text) > 900:
        cap = min(cap + 32, int(os.getenv('ULTRON_INFER_MAX_NEW_TOKENS_DEEP', '224')))

    with torch.no_grad():
        out = mdl.generate(
            **ins,
            max_new_tokens=max(24, min(cap, int(req.max_new_tokens or cap))),
            do_sample=bool(float(req.temperature or 0.0) > 0.0),
            temperature=float(req.temperature or 0.2),
            pad_token_id=tok.eos_token_id,
        )

    gen = tok.decode(out[0][ins['input_ids'].shape[1]:], skip_special_tokens=True).strip()
    return {
        'ok': True,
        'text': gen,
        'base_model': _state.get('loaded_base'),
        'adapter': _state.get('loaded_adapter') or '',
    }


@app.post('/generate')
async def generate(req: GenerateRequest, x_api_key: str | None = Header(default=None)):
    if not _auth_ok(x_api_key):
        raise HTTPException(401, 'unauthorized')

    # Backpressure: avoid request pile-up that starves /health and causes cascading timeouts.
    try:
        await asyncio.wait_for(_infer_lock.acquire(), timeout=0.8)
    except Exception:
        raise HTTPException(429, 'inference_busy_retry')

    try:
        return await asyncio.wait_for(asyncio.to_thread(_infer_sync, req), timeout=28.0)
    except asyncio.TimeoutError:
        raise HTTPException(504, 'inference_timeout')
    except RuntimeError as e:
        raise HTTPException(500, str(e))
    finally:
        if _infer_lock.locked():
            _infer_lock.release()
