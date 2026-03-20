from __future__ import annotations

import html
import json
import re
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import httpx

from ultronpro import source_probe

_DDG_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122 Safari/537.36 UltronPro/0.1',
}


def _clean(s: str) -> str:
    t = str(s or '')
    t = re.sub(r'<[^>]+>', ' ', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t


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
