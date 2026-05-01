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
                if isinstance(data, dict):
                    if 'result' in data: data = data['result']
                    elif 'triples' in data: data = data['triples']
                    elif 'facts' in data: data = data['facts']
                    elif 'data' in data: data = data['data']
                    elif 'items' in data: data = data['items']
                
                if isinstance(data, list):
                    logger.info(f"extract_triples: processing {len(data)} items from LLM on attempt {attempt+1}")
                    for i in data:
                        if isinstance(i, dict):
                            s = i.get('s') or i.get('subject') or i.get('Subject') or i.get('sujeito')
                            p = i.get('p') or i.get('predicate') or i.get('Predicate') or i.get('predicado')
                            o = i.get('o') or i.get('object') or i.get('Object') or i.get('objeto')
                            if s and p and o:
                                out.append((str(s), str(p), str(o), 0.85))
                    
                    if out:
                        logger.info(f"extract_triples: returning {len(out)} triples")
                        return out
                else:
                    logger.warning(f"extract_triples: unexpected data type after unwrap: {type(data)}")
            
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
