from __future__ import annotations

import os
import time
from threading import Lock
from typing import Optional
import asyncio

import torch
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel
from transformers import AutoModelForCausalLM, AutoTokenizer

# CPU stabilization knobs (safe defaults for VPS)
try:
    torch.set_num_threads(max(1, int(os.getenv('ULTRON_INFER_TORCH_THREADS', '2'))))
    torch.set_num_interop_threads(max(1, int(os.getenv('ULTRON_INFER_TORCH_INTEROP_THREADS', '1'))))
except Exception:
    pass

app = FastAPI(title='UltronPro Inference API', version='0.2.0')

API_TOKEN = str(os.getenv('ULTRON_LOCAL_INFER_TOKEN', '') or '').strip()
BASE_MODEL = str(os.getenv('ULTRON_BASE_MODEL', 'Qwen/Qwen2.5-3B-Instruct'))

_lock = Lock()
_infer_lock = asyncio.Lock()
_state = {
    'loaded_base': None,
    'tokenizer': None,
    'model': None,
    'last_loaded_at': 0,
}


class GenerateRequest(BaseModel):
    prompt: str
    system: Optional[str] = None
    max_new_tokens: int = 160
    temperature: float = 0.2
    mode: Optional[str] = 'balanced'


def _auth_ok(x_api_key: str | None) -> bool:
    if not API_TOKEN:
        return True
    return bool(x_api_key and str(x_api_key).strip() == API_TOKEN)


def _compose_prompt(system: str | None, prompt: str) -> str:
    s = str(system or '').strip()
    p = str(prompt or '').strip()
    if s:
        return f"<|system|>\n{s}\n<|user|>\n{p}\n<|assistant|>\n"
    return p


def _reset_loaded_state():
    with _lock:
        _state['tokenizer'] = None
        _state['model'] = None
        _state['loaded_base'] = None
        _state['last_loaded_at'] = 0


def _ensure_loaded():
    base = BASE_MODEL
    with _lock:
        if _state['model'] is not None and _state['tokenizer'] is not None and _state['loaded_base'] == base:
            return

        tok = AutoTokenizer.from_pretrained(base)
        mdl = AutoModelForCausalLM.from_pretrained(base)
        mdl.eval()

        _state['tokenizer'] = tok
        _state['model'] = mdl
        _state['loaded_base'] = base
        _state['last_loaded_at'] = int(time.time())


@app.get('/health')
async def health():
    return {
        'ok': True,
        'mode': 'base_model_only',
        'base_model': BASE_MODEL,
        'loaded_base': _state.get('loaded_base'),
        'adapter_runtime': {
            'enabled': False,
            'reason': 'training_disabled_by_architecture',
        },
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
        'adapter': '',
    }


@app.post('/runtime/apply-release')
async def runtime_apply_release(x_api_key: str | None = Header(default=None)):
    if not _auth_ok(x_api_key):
        raise HTTPException(401, 'unauthorized')
    return {
        'ok': True,
        'applied': False,
        'disabled': True,
        'reason': 'training_disabled_by_architecture',
    }


@app.post('/runtime/reload')
async def runtime_reload(x_api_key: str | None = Header(default=None)):
    if not _auth_ok(x_api_key):
        raise HTTPException(401, 'unauthorized')
    _reset_loaded_state()
    try:
        _ensure_loaded()
    except Exception as e:
        raise HTTPException(500, str(e))
    return {'ok': True, 'loaded_base': _state.get('loaded_base'), 'loaded_adapter': ''}


@app.post('/generate')
async def generate(req: GenerateRequest, x_api_key: str | None = Header(default=None)):
    if not _auth_ok(x_api_key):
        raise HTTPException(401, 'unauthorized')

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
