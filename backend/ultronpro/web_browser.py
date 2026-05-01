from __future__ import annotations

import sys

import asyncio
import json
import os
import html
import re
import random
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import httpx
try:
    from bs4 import BeautifulSoup
except Exception:
    BeautifulSoup = None

from ultronpro import source_probe

_UA_LIST = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
    'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:123.0) Gecko/20100101 Firefox/123.0'
]

_DDG_HEADERS = {
    'User-Agent': random.choice(_UA_LIST),
}


def _clean(s: str) -> str:
    t = str(s or '')
    t = re.sub(r'<[^>]+>', ' ', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t


def extract_json_ld(html_content: str) -> list[dict[str, Any]]:
    """Extrai blocos <script type="application/ld+json"> do HTML."""
    if not html_content:
        return []
    if BeautifulSoup is None:
        return []
    
    results = []
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        scripts = soup.find_all('script', type='application/ld+json')
        for script in scripts:
            try:
                data = json.loads(script.string or '')
                if isinstance(data, list):
                    results.extend([x for x in data if isinstance(x, dict)])
                elif isinstance(data, dict):
                    results.append(data)
            except (json.JSONDecodeError, TypeError):
                continue
    except Exception:
        pass
    return results



def _resolve_ddg_redirect(url: str) -> str:
    raw = html.unescape(str(url or '').strip())
    if not raw:
        return ''
    try:
        p = urlparse(raw)
        if 'duckduckgo.com' in (p.netloc or '') and (p.path or '').startswith('/l/'):
            qs = parse_qs(p.query or '', keep_blank_values=False)
            uddg = (qs.get('uddg') or [''])[0]
            real = unquote(str(uddg or '').strip())
            if real.startswith('http://') or real.startswith('https://'):
                return real
    except Exception:
        pass
    return raw


def search_web(query: str, top_k: int = 5, timeout_sec: float = 10.0) -> dict[str, Any]:
    q = str(query or '').strip()
    if not q:
        return {'ok': False, 'error': 'empty_query', 'items': []}

    k = max(1, min(10, int(top_k or 5)))
    url = f"https://duckduckgo.com/html/?q={quote_plus(q)}"
    try:
        with httpx.Client(timeout=timeout_sec, follow_redirects=True, headers=_DDG_HEADERS) as hc:
            r = hc.get(url)
            body = r.text or ''
    except Exception as e:
        return {'ok': False, 'error': f'search_error:{type(e).__name__}', 'items': [], 'query': q}

    items: list[dict[str, Any]] = []
    for m in re.finditer(r'(?is)<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', body):
        href = _resolve_ddg_redirect(str(m.group(1) or '').strip())
        title = _clean(m.group(2) or '')[:280]
        if not href:
            continue
        snip = ''
        # snippet próximo ao bloco
        tail = body[m.end(): m.end() + 1200]
        mm = re.search(r'(?is)<a[^>]+class="result__snippet"[^>]*>(.*?)</a>|<div[^>]+class="result__snippet"[^>]*>(.*?)</div>', tail)
        if mm:
            snip = _clean((mm.group(1) or mm.group(2) or ''))[:500]
        if href.startswith('//'):
            href = 'https:' + href
        items.append({'title': title, 'url': href, 'snippet': snip})
        if len(items) >= k:
            break

    return {'ok': True, 'query': q, 'count': len(items), 'items': items}


def fetch_url(url: str, max_chars: int = 12000) -> dict[str, Any]:
    final_url = _resolve_ddg_redirect(url)
    info = source_probe.fetch_clean_text(final_url, max_chars=max_chars)
    if not bool(info.get('ok')):
        return {'ok': False, 'error': info.get('error') or 'fetch_failed', 'url': str(final_url or url or '')}
    return {
        'ok': True,
        'url': info.get('url') or str(final_url or url or ''),
        'title': info.get('title') or '',
        'status_code': info.get('status_code') or 0,
        'content_type': info.get('content_type') or '',
        'text': str(info.get('text') or ''),
        'text_chars': int(info.get('text_chars') or 0),
    }


def extract_structured(url: str, schema: dict[str, Any] | list[str] | str) -> dict[str, Any]:
    fetched = fetch_url(url)
    if not fetched.get('ok'):
        return {'ok': False, 'error': fetched.get('error') or 'fetch_failed', 'url': str(url or ''), 'data': {}}

    text = str(fetched.get('text') or '')
    lines = re.split(r'(?<=[\.!?])\s+', text)
    lines = [ln.strip() for ln in lines if ln.strip()]

    if isinstance(schema, str):
        try:
            schema_obj = json.loads(schema)
        except Exception:
            schema_obj = {'fields': [schema]}
    else:
        schema_obj = schema

    if isinstance(schema_obj, list):
        fields = [str(x).strip() for x in schema_obj if str(x).strip()]
    elif isinstance(schema_obj, dict):
        ff = schema_obj.get('fields') if isinstance(schema_obj.get('fields'), list) else list(schema_obj.keys())
        fields = [str(x).strip() for x in ff if str(x).strip()]
    else:
        fields = ['summary']

    data: dict[str, Any] = {}
    low_lines = [ln.lower() for ln in lines]
    for f in fields[:20]:
        key = str(f)
        lk = key.lower()
        hit = ''
        for i, ln in enumerate(low_lines[:800]):
            if lk in ln:
                hit = lines[i][:500]
                break
        if not hit:
            hit = (lines[0] if lines else '')[:500]
        data[key] = hit

    # always include compact summary
    summary = ' '.join(lines[:4])[:800]
    data.setdefault('summary', summary)

    return {
        'ok': True,
        'url': fetched.get('url') or str(url or ''),
        'title': fetched.get('title') or '',
        'data': data,
        'schema_fields': fields[:20],
    }


async def browse_url_puppeteer(url: str, wait_until: str = 'networkidle2', timeout_ms: int = 30000) -> dict[str, Any]:
    """Navega em uma URL usando o Puppeteer Bridge (Node.js) e extrai o conteúdo renderizado.
    
    Evita as falhas do asyncio.SelectorEventLoop do Windows pois o Node.js 
    roda isolado em um microserviço acessível via HTTP nativo.
    """
    results = {
        'ok': False,
        'url': url,
        'html': '',
        'text': '',
        'json_ld': [],
        'error': None
    }

    port = int(os.environ.get('PUPPETEER_BRIDGE_PORT', '9010'))
    bridge_url = f"http://127.0.0.1:{port}/browse"

    try:
        async with httpx.AsyncClient(timeout=timeout_ms / 1000 + 5.0) as client:
            resp = await client.post(bridge_url, json={
                "url": url,
                "wait_until": wait_until,
                "timeout_ms": timeout_ms,
                "max_chars": 20000
            })
            resp.raise_for_status()
            data = resp.json()

            if not data.get('ok'):
                results['error'] = data.get('error', 'bridge_error')
                return results

            results['status'] = data.get('status', 0)
            results['html'] = data.get('html', '')
            results['title'] = data.get('title', '')
            results['text'] = data.get('text', '')
            results['json_ld'] = extract_json_ld(results['html'])
            results['ok'] = True
            
    except httpx.ConnectError:
        results['error'] = 'puppeteer_bridge_not_running'
    except Exception as e:
        results['error'] = f"puppeteer_bridge_error: {type(e).__name__} {e}"
        
    return results
