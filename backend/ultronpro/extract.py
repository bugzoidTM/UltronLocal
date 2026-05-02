from __future__ import annotations
import re
import json
import logging
import time
from ultronpro import llm

# Regex fallback (just in case)
_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"([A-ZÀ-ÿ][^\n\r]{1,50}?)\s+é\s+([^\n\r]{1,100}?)[\.,;]", re.IGNORECASE), "é"),
]

def _parse_json_robustly(text: str) -> dict | list | None:
    text = text.strip()
    
    # 1: Direct parsing
    try:
        return json.loads(text)
    except Exception:
        pass
        
    # 2: Extracting from markdown code blocks
    if "```" in text:
        parts = text.split("```")
        for p in parts:
            p = p.strip()
            if p.lower().startswith("json"):
                p = p[4:].strip()
            if not p: continue
            try:
                return json.loads(p)
            except Exception:
                pass

    # 3: Finding start/end of array/object
    start_idx = -1
    for i, c in enumerate(text):
        if c in ('[', '{'):
            start_idx = i
            break
            
    if start_idx != -1:
        end_char = ']' if text[start_idx] == '[' else '}'
        end_idx = text.rfind(end_char)
        if end_idx != -1 and end_idx >= start_idx:
            try:
                return json.loads(text[start_idx:end_idx+1])
            except Exception:
                pass
                
    return None


def _unwrap_sequence_payload(data):
    """Return the most likely list-like payload without assuming one provider schema."""
    seen = 0
    while isinstance(data, dict) and seen < 4:
        if _looks_like_triple_dict(data):
            return [data]
        next_data = None
        for key in ("triples", "facts", "relations", "items", "data", "result", "results", "output"):
            if key in data:
                next_data = data.get(key)
                break
        if next_data is None:
            return []
        if isinstance(next_data, str):
            parsed = _parse_json_robustly(next_data)
            data = parsed if parsed is not None else next_data
        else:
            data = next_data
        seen += 1
    if isinstance(data, list):
        return data
    if isinstance(data, str):
        parsed = _parse_json_robustly(data)
        if parsed is not None and parsed is not data:
            return _unwrap_sequence_payload(parsed)
    return []


def _looks_like_triple_dict(item: dict) -> bool:
    keys = {str(k).lower() for k in item.keys()}
    has_s = bool(keys & {"s", "subject", "sujeito", "source"})
    has_p = bool(keys & {"p", "predicate", "predicado", "relation", "relacao"})
    has_o = bool(keys & {"o", "object", "objeto", "target"})
    return has_s and has_p and has_o


def _coerce_triple_item(item) -> tuple[str, str, str, float] | None:
    if isinstance(item, dict):
        s = item.get('s') or item.get('subject') or item.get('Subject') or item.get('sujeito') or item.get('source')
        p = item.get('p') or item.get('predicate') or item.get('Predicate') or item.get('predicado') or item.get('relation') or item.get('relacao')
        o = item.get('o') or item.get('object') or item.get('Object') or item.get('objeto') or item.get('target')
        conf = item.get('confidence') or item.get('score') or 0.85
    elif isinstance(item, (list, tuple)) and len(item) >= 3:
        s, p, o = item[0], item[1], item[2]
        conf = item[3] if len(item) > 3 else 0.82
    else:
        return None
    if not (s and p and o):
        return None
    try:
        confidence = float(conf)
    except Exception:
        confidence = 0.85
    return (str(s), str(p), str(o), max(0.0, min(1.0, confidence)))

def extract_norms(text: str, max_retries: int = 3) -> list[tuple[str, str, str, float]]:
    """Extract norms using LLM."""
    if not text: return []
    prompt = f"""Extract normative rules/laws from the text.
Return JSON array of objects with keys: "rule" (text of the rule).
Text: {text[:4000]}"""
    
    out = []
    logger = logging.getLogger("uvicorn")
    
    for attempt in range(max_retries):
        try:
            res = llm.complete(prompt, json_mode=True)
            data = _parse_json_robustly(res)
            
            if isinstance(data, dict):
                if 'rules' in data: data = data['rules']
                elif 'norms' in data: data = data['norms']
            
            if isinstance(data, list):
                for i in data:
                    txt = i if isinstance(i, str) else i.get('rule') or i.get('text')
                    if txt:
                        out.append(('AGI', 'deve', txt, 0.8))
                
                if out:
                    return out
            
            logger.warning(f"extract_norms: attempt {attempt+1} failed parser.")
        except Exception as e:
            logger.error(f"extract_norms: Error on attempt {attempt+1}: {e}")
            
    return out

def _regex_fallback(text: str) -> list[tuple[str, str, str, float]]:
    out: list[tuple[str, str, str, float]] = []
    seen = set()

    patterns = [
        (re.compile(r"([A-ZÀ-ÿ][^\.\n]{2,80}?)\s+é\s+([^\.\n]{2,120})[\.;]", re.IGNORECASE), "é"),
        (re.compile(r"([A-ZÀ-ÿ][^\.\n]{2,80}?)\s+tem\s+([^\.\n]{2,120})[\.;]", re.IGNORECASE), "tem"),
        (re.compile(r"([A-ZÀ-ÿ][^\.\n]{2,80}?)\s+causa\s+([^\.\n]{2,120})[\.;]", re.IGNORECASE), "causa"),
    ]

    for pat, pred in patterns:
        for m in pat.finditer(text):
            s = re.sub(r"\s+", " ", (m.group(1) or "").strip())
            o = re.sub(r"\s+", " ", (m.group(2) or "").strip())
            key = (s.lower(), pred.lower(), o.lower())
            if len(s) < 2 or len(o) < 2 or key in seen:
                continue
            seen.add(key)
            out.append((s, pred, o, 0.55))
            if len(out) >= 12:
                return out

    return out


def extract_triples(text: str, max_retries: int = 3) -> list[tuple[str, str, str, float]]:
    """Extract triples using LLM; fallback para regex quando não houver LLM, com auto-retry e parse robusto."""
    logger = logging.getLogger("uvicorn")
    
    if not text or len(text) < 10:
        logger.debug(f"extract_triples: text too short ({len(text) if text else 0} chars)")
        return []

    prompt = f"""Extract key facts from the text as triples (Subject, Predicate, Object).
Focus on relationships, definitions, and causality.
Return ONLY a JSON array of objects with keys "s", "p", "o".
Output in Portuguese.
Text: {text[:3000]}"""

    out = []
    
    for attempt in range(max_retries):
        logger.info(f"extract_triples (Attempt {attempt+1}/{max_retries}): calling LLM for {len(text)} chars...")
        try:
            res = llm.complete(prompt, json_mode=True, strategy="cheap")
            logger.info(f"extract_triples: LLM returned {len(res)} chars.")
            if not str(res or "").strip():
                logger.warning("extract_triples: LLM empty/unavailable; using local fallback without retry.")
                break
            
            data = _parse_json_robustly(res)
            logger.debug(f"extract_triples: parsed JSON type={type(data)}")
            
            if data is not None:
                items = _unwrap_sequence_payload(data)
                if items:
                    logger.info(f"extract_triples: processing {len(items)} items from LLM on attempt {attempt+1}")
                    for i in items:
                        triple = _coerce_triple_item(i)
                        if triple:
                            out.append(triple)
                    if out:
                        logger.info(f"extract_triples: returning {len(out)} triples")
                        return out
                else:
                    logger.warning(f"extract_triples: no triple items after unwrap (parsed={type(data)})")
                    break
            
            if attempt + 1 < max_retries:
                logger.warning(f"extract_triples: attempt {attempt+1} failed to yield valid triples. Retrying...")
            else:
                logger.warning(f"extract_triples: attempt {attempt+1} failed to yield valid triples.")
            
        except Exception as e:
            logger.error(f"extract_triples: Exception on attempt {attempt+1}: {e}")
            if any(t in str(e).lower() for t in ["429", "rate limit", "quota", "no_llm_clients_cloud_chain"]):
                break
    
    # Se depois de todos os retries não houver out
    if not out:
        fb = _regex_fallback(text)
        if fb:
            logger.info(f"extract_triples: regex fallback generated {len(fb)} triples")
            return fb

    logger.info(f"extract_triples: returning {len(out)} triples (empty/failed after retries)")
    return out
