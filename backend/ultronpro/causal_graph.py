from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

GRAPH_PATH = Path('/app/data/causal_graph.json')
EDGE_LOG_PATH = Path('/app/data/causal_graph_edges.jsonl')

CAUSAL_PREDICATES = {
    'causa', 'resulta_em', 'implica', 'leva_a', 'provoca', 'depende_de',
    'requer', 'bloqueia', 'melhora', 'degrada', 'ativa', 'inibe'
}


def _now() -> int:
    return int(time.time())


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-zA-ZÀ-ÿ0-9_]{4,}", (text or '').lower()))


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or '').strip().lower())


def _norm_predicate(p: str) -> str:
    x = _norm(p).replace(' ', '_')
    x = x.replace('ç', 'c').replace('ã', 'a').replace('á', 'a').replace('â', 'a').replace('é', 'e').replace('ê', 'e').replace('í', 'i').replace('ó', 'o').replace('ô', 'o').replace('õ', 'o').replace('ú', 'u')
    return x


def _is_causal_predicate(p: str) -> bool:
    np = _norm_predicate(p)
    if np in CAUSAL_PREDICATES:
        return True
    return any(k in np for k in ['caus', 'implic', 'result', 'leva', 'provoc', 'depend', 'requer', 'bloque', 'melhor', 'degrad', 'ativ', 'inib'])


def _default_graph() -> dict[str, Any]:
    return {'nodes': {}, 'edges': {}, 'updated_at': 0}


def load_graph() -> dict[str, Any]:
    if not GRAPH_PATH.exists():
        return _default_graph()
    try:
        d = json.loads(GRAPH_PATH.read_text(encoding='utf-8'))
        if isinstance(d, dict):
            d.setdefault('nodes', {})
            d.setdefault('edges', {})
            return d
    except Exception:
        pass
    return _default_graph()


def save_graph(g: dict[str, Any]) -> dict[str, Any]:
    out = dict(g or {})
    out.setdefault('nodes', {})
    out.setdefault('edges', {})
    out['updated_at'] = _now()
    GRAPH_PATH.parent.mkdir(parents=True, exist_ok=True)
    GRAPH_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    return out


def _edge_key(a: str, b: str, cond: str) -> str:
    return f"{_norm(a)}|{_norm(b)}|{_norm(cond)}"


def _infer_severity(effect: str) -> int:
    e = _norm(effect)
    high = ['timeout', 'falha', 'crash', 'perda', 'indisponivel', 'indisponível', 'corrup', 'erro fatal', 'trap', 'risco', 'danger', 'perigo']
    med = ['lentidao', 'lentidão', 'degrad', 'instavel', 'instável', 'atraso', 'warning']
    if any(k in e for k in high):
        return 3
    if any(k in e for k in med):
        return 2
    return 1


def upsert_edge(*, cause: str, effect: str, condition: str = '', evidence: dict[str, Any] | None = None, confidence: float = 0.6, source: str = 'unknown'):
    a = _norm(cause)
    b = _norm(effect)
    c = _norm(condition)
    if not a or not b:
        return {'ok': False, 'reason': 'missing_nodes'}

    g = load_graph()
    g['nodes'][a] = {'label': a}
    g['nodes'][b] = {'label': b}

    k = _edge_key(a, b, c)
    cur = g['edges'].get(k) if isinstance(g.get('edges'), dict) else None
    if not isinstance(cur, dict):
        cur = {
            'cause': a,
            'effect': b,
            'condition': c,
            'support': 0,
            'confidence': 0.5,
            'severity': _infer_severity(b),
            'sources': [],
            'last_evidence': None,
            'updated_at': 0,
        }
    cur['support'] = int(cur.get('support') or 0) + 1
    cur['confidence'] = round(min(0.99, max(float(cur.get('confidence') or 0.5), float(confidence or 0.5)) + 0.02), 4)
    cur['severity'] = max(int(cur.get('severity') or 1), _infer_severity(b))
    srcs = set(cur.get('sources') or [])
    srcs.add(str(source or 'unknown'))
    cur['sources'] = sorted(list(srcs))[:8]
    cur['last_evidence'] = evidence or {}
    cur['updated_at'] = _now()

    g['edges'][k] = cur
    save_graph(g)

    EDGE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with EDGE_LOG_PATH.open('a', encoding='utf-8') as f:
        f.write(json.dumps({'ts': _now(), 'edge': cur, 'source': source}, ensure_ascii=False) + '\n')
    return {'ok': True, 'edge': cur}


def apply_delta_update(*, cause: str, effect: str, condition: str = '', category: str, evidence: dict[str, Any] | None = None, source: str = 'delta_update') -> dict[str, Any]:
    """
    Deterministic confidence update rules:
      - confirmed: +0.05 (max 0.99)
      - refuted:  -0.10 (min 0.10)
      - unexpected: create edge at 0.60 when absent (or keep as-is if present)
    """
    a = _norm(cause)
    b = _norm(effect)
    c = _norm(condition)
    if not a or not b:
        return {'ok': False, 'reason': 'missing_nodes'}

    g = load_graph()
    g['nodes'][a] = {'label': a}
    g['nodes'][b] = {'label': b}

    k = _edge_key(a, b, c)
    cur = g.get('edges', {}).get(k) if isinstance(g.get('edges'), dict) else None
    before = float((cur or {}).get('confidence') or 0.6)

    if not isinstance(cur, dict):
        cur = {
            'cause': a,
            'effect': b,
            'condition': c,
            'support': 0,
            'confidence': 0.6,
            'severity': _infer_severity(b),
            'sources': [],
            'last_evidence': None,
            'updated_at': 0,
        }
        before = 0.6

    cat = str(category or '').strip().lower()
    after = before
    if cat == 'confirmed':
        after = min(0.99, before + 0.05)
    elif cat == 'refuted':
        after = max(0.10, before - 0.10)
    elif cat == 'unexpected':
        # keep existing confidence if edge already exists; new edge starts at 0.60
        after = before
    else:
        return {'ok': False, 'reason': 'invalid_category'}

    cur['confidence'] = round(float(after), 4)
    cur['support'] = int(cur.get('support') or 0) + 1
    cur['severity'] = max(int(cur.get('severity') or 1), _infer_severity(b))
    srcs = set(cur.get('sources') or [])
    srcs.add(str(source or 'delta_update'))
    cur['sources'] = sorted(list(srcs))[:8]
    cur['last_evidence'] = evidence or {}
    cur['updated_at'] = _now()

    g['edges'][k] = cur
    save_graph(g)

    EDGE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with EDGE_LOG_PATH.open('a', encoding='utf-8') as f:
        f.write(json.dumps({'ts': _now(), 'edge': cur, 'source': source, 'delta_category': cat, 'confidence_before': round(before, 4), 'confidence_after': round(float(after), 4)}, ensure_ascii=False) + '\n')

    return {
        'ok': True,
        'edge': cur,
        'delta_category': cat,
        'confidence_before': round(before, 4),
        'confidence_after': round(float(after), 4),
    }


def extract_triples_from_text(text: str) -> list[dict[str, str]]:
    t = str(text or '').strip()
    if not t:
        return []
    out: list[dict[str, str]] = []

    # Pattern: A causa B se C
    m = re.search(r"(.{3,120}?)\s+causa\s+(.{3,120}?)(?:\s+se\s+(.{2,120}))?$", t, flags=re.IGNORECASE)
    if m:
        out.append({'cause': m.group(1).strip(' .,:;-'), 'effect': m.group(2).strip(' .,:;-'), 'condition': (m.group(3) or '').strip(' .,:;-')})

    # Pattern: A -> B (cond: C)
    for mm in re.finditer(r"\(?\s*([^\)\-]{3,80})\s*\)?\s*[-=]+>\s*\(?\s*([^\)\-]{3,80})\s*\)?(?:\s*\(?\s*(?:se|condi[cç][aã]o|cond)\s*[:\-]\s*([^\)\n]{2,80})\s*\)?)?", t, flags=re.IGNORECASE):
        out.append({'cause': mm.group(1).strip(' .,:;-'), 'effect': mm.group(2).strip(' .,:;-'), 'condition': (mm.group(3) or '').strip(' .,:;-')})

    # Dedup
    seen = set()
    ded = []
    for x in out:
        k = (_norm(x.get('cause')), _norm(x.get('effect')), _norm(x.get('condition')))
        if k in seen or not k[0] or not k[1]:
            continue
        seen.add(k)
        ded.append(x)
    return ded[:8]


def ingest_confirmed_hypothesis(hypothesis: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    triples = extract_triples_from_text(hypothesis)
    n = 0
    for t in triples:
        r = upsert_edge(
            cause=t.get('cause') or '',
            effect=t.get('effect') or '',
            condition=t.get('condition') or '',
            evidence=details or {},
            confidence=0.68,
            source='reflexion_confirmed',
        )
        if r.get('ok'):
            n += 1
    return {'ok': True, 'ingested': n, 'triples': triples}


def query_for_problem(problem: str, limit: int = 5) -> dict[str, Any]:
    g = load_graph()
    q = _tokens(problem)
    scored: list[tuple[float, dict[str, Any]]] = []
    for e in (g.get('edges') or {}).values():
        if not isinstance(e, dict):
            continue
        txt = f"{e.get('cause','')} {e.get('effect','')} {e.get('condition','')}"
        t = _tokens(txt)
        if not q or not t:
            continue
        inter = len(q & t)
        if inter <= 0:
            continue
        sim = inter / max(1, len(q | t))
        conf = float(e.get('confidence') or 0.5)
        sup = min(0.15, float(e.get('support') or 0) * 0.02)
        scored.append((sim + conf * 0.25 + sup, e))

    scored.sort(key=lambda x: x[0], reverse=True)
    items = []
    for sc, e in scored[:max(1, int(limit or 5))]:
        items.append({
            'score': round(float(sc), 4),
            'cause': e.get('cause'),
            'effect': e.get('effect'),
            'condition': e.get('condition'),
            'confidence': e.get('confidence'),
            'severity': int(e.get('severity') or 1),
            'support': e.get('support'),
        })
    return {'ok': True, 'count': len(items), 'items': items}


def bootstrap_from_triples(triples: list[dict[str, Any]], source: str = 'bootstrap_filtered') -> dict[str, Any]:
    scanned = 0
    causal = 0
    ingested = 0
    for t in triples or []:
        scanned += 1
        p = str((t or {}).get('predicate') or '')
        if not _is_causal_predicate(p):
            continue
        causal += 1
        r = upsert_edge(
            cause=str((t or {}).get('subject') or ''),
            effect=str((t or {}).get('object') or ''),
            condition='',
            confidence=float((t or {}).get('confidence') or 0.6),
            source=source,
            evidence={'predicate': p, 'triple_id': (t or {}).get('id')},
        )
        if r.get('ok'):
            ingested += 1
    return {'ok': True, 'scanned': scanned, 'causal_candidates': causal, 'ingested': ingested}


def evaluate_step_risk(query: str, step: dict[str, Any] | None) -> dict[str, Any]:
    st = step if isinstance(step, dict) else {}
    r = score_plan_risk(query=query, steps=[st])
    activated = r.get('activated_edges') if isinstance(r, dict) and isinstance(r.get('activated_edges'), list) else []
    vetoes = []
    warnings = []
    for e in activated:
        sev = int((e or {}).get('severity') or 1)
        conf = float((e or {}).get('confidence') or 0.0)
        cause = str((e or {}).get('cause') or '')
        effect = str((e or {}).get('effect') or '')
        if sev >= 3 and conf > 0.7:
            vetoes.append({'cause': cause, 'effect': effect, 'severity': sev, 'confidence': conf})
        elif sev == 2:
            warnings.append({'cause': cause, 'effect': effect, 'severity': sev, 'confidence': conf})
    return {
        'ok': True,
        'risk_score': float(r.get('risk_score') or 0.0),
        'activated_edges': activated,
        'vetoes': vetoes,
        'warnings': warnings,
    }


def score_plan_risk(query: str, steps: list[dict[str, Any]] | None) -> dict[str, Any]:
    g = load_graph()
    edges = [e for e in (g.get('edges') or {}).values() if isinstance(e, dict)]
    q_base = _tokens(query)
    risk_score = 0.0
    activated = []

    for idx, st in enumerate(steps or [], start=1):
        if not isinstance(st, dict):
            continue
        tool = str(st.get('tool') or '')
        args = st.get('args') if isinstance(st.get('args'), dict) else {}
        txt = f"{query} {tool} {json.dumps(args, ensure_ascii=False)}"
        tq = _tokens(txt)
        if not tq:
            continue
        for e in edges:
            et = _tokens(f"{e.get('cause','')} {e.get('effect','')} {e.get('condition','')}")
            if not et:
                continue
            inter = len(tq & et)
            if inter <= 0:
                continue
            match = inter / max(1, len(tq | et))
            conf = float(e.get('confidence') or 0.5)
            sev = int(e.get('severity') or _infer_severity(str(e.get('effect') or '')))
            contrib = conf * sev * match
            if contrib <= 0:
                continue
            risk_score += contrib
            activated.append({
                'step': idx,
                'tool': tool,
                'cause': e.get('cause'),
                'effect': e.get('effect'),
                'condition': e.get('condition'),
                'confidence': conf,
                'severity': sev,
                'match': round(match, 4),
                'contribution': round(contrib, 4),
            })

    activated.sort(key=lambda x: float(x.get('contribution') or 0.0), reverse=True)
    return {
        'ok': True,
        'risk_score': round(risk_score, 4),
        'activated_edges': activated[:20],
        'edges_considered': len(edges),
        'query_tokens': len(q_base),
    }


def assess_rule_against_graph(rule_text: str) -> dict[str, Any]:
    triples = extract_triples_from_text(rule_text)
    if not triples:
        return {'ok': True, 'has_causal_rule': False, 'confirmations': 0, 'contradictions': 0, 'triples': []}
    g = load_graph()
    edges = [e for e in (g.get('edges') or {}).values() if isinstance(e, dict)]
    conf = 0
    contra = 0
    details = []
    for t in triples:
        c = _norm(t.get('cause') or '')
        efx = _norm(t.get('effect') or '')
        cond = _norm(t.get('condition') or '')
        matched_same = False
        matched_conflict = False
        for e in edges:
            ec = _norm(e.get('cause') or '')
            ee = _norm(e.get('effect') or '')
            ed = _norm(e.get('condition') or '')
            if ec == c and ee == efx and (not cond or cond == ed):
                matched_same = True
            if ec == c and ee != efx and (not cond or cond == ed):
                matched_conflict = True
        if matched_same:
            conf += 1
        if matched_conflict:
            contra += 1
        details.append({'triple': t, 'confirmed': matched_same, 'contradicted': matched_conflict})
    return {'ok': True, 'has_causal_rule': True, 'confirmations': conf, 'contradictions': contra, 'triples': details}


def status() -> dict[str, Any]:
    g = load_graph()
    return {
        'ok': True,
        'nodes': len(g.get('nodes') or {}),
        'edges': len(g.get('edges') or {}),
        'updated_at': g.get('updated_at') or 0,
        'path': str(GRAPH_PATH),
    }
