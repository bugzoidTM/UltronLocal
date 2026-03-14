import httpx
import os
import logging
import re
import json
import time
import hashlib
from pathlib import Path
from typing import List, Dict, Optional

logger = logging.getLogger("uvicorn")

# Heuristic task_type tagging from document text (fast bootstrap, no classifier required)
_TASK_TYPE_KEYWORDS = {
    "coding": ["python", "código", "code", "bug", "stacktrace", "api", "endpoint", "função", "classe", "sql", "docker", "git", "deploy"],
    "research": [
        "pesquisa", "artigo", "paper", "estudo", "benchmark", "comparativo", "referência", "fonte", "evidência",
        "hipótese", "hipotese", "experimento", "metodologia", "método", "metodo", "resultados", "conclusão", "conclusao",
        "amostra", "estatística", "estatistica", "revisão", "revisao", "ensaio", "científico", "cientifico", "dados"
    ],
    "operations": [
        "incidente", "erro", "erro 5", "error", "failed", "failure", "exception",
        "latência", "latencia", "latency", "timeout", "sla", "monitor", "observabilidade", "alerta",
        "rollback", "restart", "restarted", "produção", "producao", "runtime", "unavailable",
        "queue", "worker", "dispatch", "scheduler", "backoff", "retry",
        "job", "status", "registered", "running_remote", "converged", "eval_done", "trigger_eval_batteries",
        "adapter", "gate", "pipeline", "health", "503", "502", "500"
    ],
    "planning": ["roadmap", "milestone", "prioridade", "priorizar", "plano", "objetivo", "estratégia", "estrategia", "cronograma"],
    "conversation_ptbr": ["responda", "usuário", "usuario", "português", "portugues", "pt-br", "conversa", "assistente"],
    "safety_guardrails": ["segurança", "seguranca", "política", "politica", "compliance", "guardrail", "risco", "bloquear", "proibido"],
}


def _infer_task_type(text: str) -> str:
    t = (text or "").lower()
    if not t:
        return "general"

    scores: dict[str, int] = {}
    for task_type, kws in _TASK_TYPE_KEYWORDS.items():
        s = 0
        for kw in kws:
            if kw in t:
                s += 1
        scores[task_type] = s

    # Boost research when scientific structure appears
    if any(k in t for k in ("metodologia", "método", "hipótese", "hipotese", "resultados", "conclusão", "conclusao", "revisão", "revisao")):
        scores["research"] = int(scores.get("research", 0)) + 2

    best = max(scores.items(), key=lambda kv: kv[1]) if scores else ("general", 0)
    if (best[1] or 0) <= 0:
        return "general"
    return str(best[0])


def _relevance_score(query: str, text: str) -> float:
    q_tokens = {t for t in re.findall(r"[a-zA-ZÀ-ÿ0-9_]{4,}", (query or '').lower())}
    t_tokens = {t for t in re.findall(r"[a-zA-ZÀ-ÿ0-9_]{4,}", (text or '').lower())}
    if not q_tokens or not t_tokens:
        return 0.0
    overlap = len(q_tokens.intersection(t_tokens))
    # conservative score; requires some lexical evidence to pass >=0.5 gate
    score = overlap / max(1, len(q_tokens))
    return round(float(score), 4)


_INGEST_STATE_PATH = Path('/app/data/rag_ingest_state.json')
_QUARANTINE_PATH = Path('/app/data/rag_ingest_quarantine.jsonl')


def _text_hash(s: str) -> str:
    return hashlib.md5((s or '').encode('utf-8', errors='ignore')).hexdigest()


def _load_ingest_state() -> dict:
    if _INGEST_STATE_PATH.exists():
        try:
            d = json.loads(_INGEST_STATE_PATH.read_text(encoding='utf-8'))
            if isinstance(d, dict):
                d.setdefault('recent', [])
                return d
        except Exception:
            pass
    return {'recent': []}


def _save_ingest_state(d: dict):
    _INGEST_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _INGEST_STATE_PATH.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding='utf-8')


def _source_penalty(source: str) -> float:
    s = (source or '').lower()
    if 'uselessfacts' in s:
        return 0.12
    return 0.0


def _quality_score(text: str, source: str) -> float:
    t = str(text or '')
    toks = re.findall(r"[a-zA-ZÀ-ÿ0-9_]{3,}", t.lower())
    uniq = len(set(toks)) / max(1, len(toks))
    length_score = min(1.0, len(t) / 700.0)
    punct_ok = 1.0 if any(ch in t for ch in '.!?') else 0.6
    noise = 1.0 if ('```' in t or '{"entity"' in t) else 0.0
    score = (0.40 * length_score) + (0.35 * uniq) + (0.25 * punct_ok) - (0.20 * noise) - _source_penalty(source)
    return max(0.0, min(1.0, round(score, 4)))


def _dedupe_recent(h: str, max_items: int = 2000) -> bool:
    st = _load_ingest_state()
    arr = list(st.get('recent') or [])
    if h in arr:
        return False
    arr.append(h)
    st['recent'] = arr[-max_items:]
    _save_ingest_state(st)
    return True


def _quarantine(text: str, source: str, reason: str, score: float):
    _QUARANTINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    rec = {
        'ts': int(time.time()),
        'source': str(source or '')[:100],
        'reason': str(reason or '')[:120],
        'score': float(score),
        'text': str(text or '')[:1200],
    }
    with _QUARANTINE_PATH.open('a', encoding='utf-8') as f:
        f.write(json.dumps(rec, ensure_ascii=False) + '\n')


def _get_lightrag_config():
    """Load LightRAG config from settings."""
    from ultronpro import settings
    s = settings.load_settings()
    return s.get("lightrag_url"), s.get("lightrag_api_key")

def _extract_context_any(data) -> str:
    """Tolerante a mudanças de schema JSON."""
    if data is None:
        return ""
    if isinstance(data, str):
        return data
    if isinstance(data, list):
        return "\n".join([_extract_context_any(x) for x in data[:6] if _extract_context_any(x)])
    if isinstance(data, dict):
        # chaves comuns em variações de API
        for k in ("context", "response", "result", "answer", "text", "content"):
            v = data.get(k)
            if v:
                return _extract_context_any(v)
        # fallback: serializa campos curtos
        parts = []
        for k, v in list(data.items())[:8]:
            sv = _extract_context_any(v)
            if sv:
                parts.append(f"{k}: {sv}")
        return "\n".join(parts)
    return str(data)


async def search_knowledge(query: str, top_k: int = 5) -> List[Dict]:
    """Search LightRAG knowledge base with adaptive endpoint/schema handling."""
    url, key = _get_lightrag_config()
    if not url or not key:
        logger.warning("LightRAG not configured. Skipping knowledge search.")
        return []

    base = url.rstrip("/")
    payload = {
        "query": query,
        "mode": "mix",
        "top_k": int(top_k),
        "only_need_context": True,
    }

    endpoints = [f"{base}/query", f"{base}/query/data"]

    try:
        async with httpx.AsyncClient() as client:
            last_err = None
            for ep in endpoints:
                try:
                    resp = await client.post(
                        ep,
                        headers={"X-API-Key": key},
                        json=payload,
                        timeout=20.0,
                    )
                    if resp.status_code >= 400:
                        last_err = f"{ep} -> {resp.status_code}"
                        continue

                    data = resp.json()
                    context = _extract_context_any(data)
                    if not context:
                        continue

                    text = str(context)
                    ttype = _infer_task_type(text)
                    score = _relevance_score(query, text)
                    return [{
                        "text": text[:2500],
                        "source_id": "lightrag",
                        "score": score,
                        "type": "experience",
                        "task_type": ttype,
                    }]
                except Exception as e:
                    last_err = str(e)
                    continue

            if last_err:
                logger.error(f"LightRAG Search Error: {last_err}")
            return []

    except Exception as e:
        logger.error(f"LightRAG Search Error: {e}")
        return []

async def fetch_random_documents(limit: int = 1) -> List[Dict]:
    """Fetch random documents from LightRAG.

    Compatível com instâncias onde /documents/{id} não existe.
    """
    url, key = _get_lightrag_config()
    if not url or not key:
        return []

    base = url.replace('/api', '')

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{base}/documents",
                headers={"X-API-Key": key},
                timeout=10.0,
            )
            resp.raise_for_status()
            data = resp.json()

            processed = data.get("statuses", {}).get("processed", [])
            if not processed:
                return []

            import random
            selected = random.sample(processed, min(limit, len(processed)))

            results = []
            for doc in selected:
                doc_id = doc.get("id")
                if not doc_id:
                    continue

                # 1) Tenta endpoint de detalhe (se existir)
                content = ""
                try:
                    doc_resp = await client.get(
                        f"{base}/documents/{doc_id}",
                        headers={"X-API-Key": key},
                        timeout=5.0,
                    )
                    if doc_resp.status_code == 200:
                        doc_data = doc_resp.json()
                        content = (doc_data.get("content") or "").strip()
                except Exception:
                    pass

                # 2) Fallback: usa summary do próprio listing
                if not content:
                    content = (doc.get("content_summary") or "").strip()

                if len(content) > 40:
                    ttype = _infer_task_type(content)
                    results.append(
                        {
                            "id": doc_id,
                            "content": content[:2000],
                            "summary": (doc.get("content_summary") or content)[:200],
                            "task_type": ttype,
                        }
                    )

            return results

    except Exception as e:
        logger.error(f"LightRAG Fetch Error: {e}")
        return []

async def ingest_knowledge(text: str, source: str = "ultronpro") -> bool:
    """Push new knowledge to LightRAG.

    Controlled by env ULTRON_LIGHTRAG_INGEST_ENABLED (default: enabled).
    """
    enabled = str(os.getenv('ULTRON_LIGHTRAG_INGEST_ENABLED', '1')).strip().lower() not in ('0', 'false', 'no', 'off')
    if not enabled:
        return False

    url, key = _get_lightrag_config()
    if not url or not key:
        logger.warning('LightRAG ingest skipped: missing config')
        return False

    t = str(text or '').strip()
    src = str(source or 'ultronpro')[:80]
    if len(t) < 40:
        _quarantine(t, src, 'too_short', 0.0)
        return False

    # quality gate + lexical dedupe to reduce RAG noise
    min_q = float(os.getenv('ULTRON_RAG_INGEST_MIN_QUALITY', '0.58') or 0.58)
    qscore = _quality_score(t, src)
    if qscore < min_q:
        _quarantine(t, src, 'low_quality', qscore)
        return False

    h = _text_hash(t)
    if not _dedupe_recent(h):
        return False

    base = url.replace('/api', '')
    payload = {
        'text': t,
        'source': src,
    }

    endpoints = [
        (f"{base}/documents/text", payload),
        (f"{base}/documents", payload),
        # U1 worker contract fallback
        (f"{base}/ingest", {'docs': [t]}),
    ]

    try:
        async with httpx.AsyncClient() as client:
            for ep, body in endpoints:
                try:
                    r = await client.post(
                        ep,
                        headers={"X-API-Key": key, 'Content-Type': 'application/json'},
                        json=body,
                        timeout=20.0,
                    )
                    if r.status_code < 300:
                        # /ingest may return ok=true with ingested_ok=0 (no-op)
                        if ep.endswith('/ingest'):
                            try:
                                jd = r.json() if r.text else {}
                            except Exception:
                                jd = {}
                            if int((jd or {}).get('ingested_ok') or 0) <= 0:
                                logger.warning(f"LightRAG ingest no-op source={src} ep={ep} resp={(r.text or '')[:180]}")
                                continue
                        logger.info(f"LightRAG ingest ok source={src} quality={qscore} ep={ep}")
                        return True
                    logger.warning(f"LightRAG ingest rejected ep={ep} status={r.status_code} body={(r.text or '')[:180]}")
                except Exception as e:
                    logger.warning(f"LightRAG ingest exception ep={ep}: {e}")
                    continue
    except Exception as e:
        logger.error(f'LightRAG ingest error: {e}')

    _quarantine(t, src, 'ingest_failed', qscore)
    return False
