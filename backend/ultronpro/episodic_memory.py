import json
import time
import os
from pathlib import Path
from typing import Any

EPISODIC_PATH = Path('/app/data/episodic_memory.jsonl')
EPISODIC_STRUCTURED_PATH = Path('/app/data/episodic_memory_structured.jsonl')
PROCEDURAL_PATH = Path('/app/data/procedural_memory.jsonl')
WORKING_STATE_PATH = Path('/app/data/working_memory_state.json')
AUDIT_PATH = Path('/app/data/episodic_audit.jsonl')
LEARNING_PROPOSALS_PATH = Path('/app/data/learning_proposals.jsonl')


def _tokens(text: str) -> set[str]:
    import re
    return {t for t in re.findall(r"[a-zA-ZÀ-ÿ0-9_]{4,}", (text or '').lower())}


def _infer_error_class(error_text: str) -> str:
    e = str(error_text or '').lower()
    if not e:
        return 'none'
    if '403' in e or 'forbidden' in e or 'permission' in e or 'acl' in e:
        return '403'
    if '429' in e or 'rate limit' in e or 'too many requests' in e:
        return '429'
    if any(x in e for x in ['500', '501', '502', '503', '504', '5xx', 'bad gateway', 'gateway timeout']):
        return '5xx'
    if 'timeout' in e or 'timed out' in e or 'connection aborted' in e:
        return 'timeout'
    if 'json' in e or 'parse' in e or 'decode' in e or 'invalid regular expression' in e:
        return 'parse'
    if 'sql' in e or 'db' in e or 'database' in e or 'postgres' in e or 'sqlite' in e:
        return 'db'
    return 'other'


def _audit_enabled() -> bool:
    return str(os.getenv('ULTRON_EPISODIC_AUDIT', '1')).strip().lower() not in ('0', 'false', 'no', 'off')


def _append_audit(row: dict[str, Any]):
    if not _audit_enabled():
        return
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with AUDIT_PATH.open('a', encoding='utf-8') as f:
        f.write(json.dumps(row, ensure_ascii=False) + '\n')


def append_episode(*, action_id: int, kind: str, text: str, task_type: str, strategy: str, ok: bool, latency_ms: int, error: str = '', meta: dict[str, Any] | None = None):
    EPISODIC_PATH.parent.mkdir(parents=True, exist_ok=True)
    _meta = dict(meta or {})
    now = int(time.time())
    err_text = str(error or '')[:240]
    error_class = str(_meta.get('error_class') or _infer_error_class(err_text))
    outcome = str(_meta.get('outcome') or ('success' if bool(ok) else 'failure'))
    tool = str(_meta.get('tool') or strategy or kind or task_type or 'unknown')
    txt = str(text or '')[:420]

    # Data-quality gate (no forced reasoning, only input hygiene)
    missing = []
    if not str(task_type or '').strip():
        missing.append('task_type')
    if int(latency_ms or 0) <= 0:
        missing.append('latency_ms')
    if not str(tool or '').strip():
        missing.append('tool')
    if not str(outcome or '').strip():
        missing.append('outcome')
    if not str(error_class or '').strip():
        missing.append('error_class')
    quality = 'strong' if not missing else 'weak'

    # Dedup TTL for repetitive/noisy events
    dedup_ttl_sec = int(os.getenv('ULTRON_EPISODIC_DEDUP_TTL_SEC', '1800') or 1800)
    qkey = f"{str(task_type or '').strip().lower()}|{str(tool).lower()}|{str(error_class).lower()}|{' '.join(sorted(list(_tokens(txt)))[:10])}"
    duplicate_recent = False
    for e in recent(limit=200):
        try:
            ets = int(e.get('ts') or 0)
            if now - ets > dedup_ttl_sec:
                continue
            eq = f"{str(e.get('task_type') or '').strip().lower()}|{str(e.get('tool') or e.get('strategy') or '').lower()}|{str(e.get('error_class') or '').lower()}|{' '.join(sorted(list(_tokens(str(e.get('text') or ''))))[:10])}"
            if eq == qkey:
                duplicate_recent = True
                break
        except Exception:
            continue

    row = {
        'ts': now,
        'action_id': int(action_id),
        'kind': str(kind or ''),
        'task_type': str(task_type or ''),
        'strategy': str(strategy or kind or ''),
        'text': txt,
        'ok': bool(ok),
        'latency_ms': int(latency_ms or 0),
        'error': err_text,
        'error_class': error_class,
        'tool': tool,
        'outcome': outcome,
        'quality': quality,
        'meta': _meta,
    }

    # Audit every decision path
    _append_audit({
        'ts': now,
        'event': 'append_episode_decision',
        'action_id': int(action_id),
        'accepted': (not duplicate_recent),
        'duplicate_recent': duplicate_recent,
        'quality': quality,
        'missing_fields': missing,
        'task_type': str(task_type or ''),
        'tool': tool,
        'error_class': error_class,
        'latency_ms': int(latency_ms or 0),
        'outcome': outcome,
    })

    if duplicate_recent:
        return

    with EPISODIC_PATH.open('a', encoding='utf-8') as f:
        f.write(json.dumps(row, ensure_ascii=False) + '\n')


def recent(limit: int = 1200) -> list[dict[str, Any]]:
    if not EPISODIC_PATH.exists():
        return []
    rows = []
    for ln in EPISODIC_PATH.read_text(encoding='utf-8', errors='ignore').splitlines()[-max(10, int(limit or 1200)):]:
        if not ln.strip():
            continue
        try:
            rows.append(json.loads(ln))
        except Exception:
            continue
    return rows


def find_similar(*, kind: str, text: str, task_type: str = '', limit: int = 5) -> list[dict[str, Any]]:
    q = _tokens(f"{kind} {task_type} {text}")
    out: list[tuple[float, dict[str, Any]]] = []
    for e in recent(limit=1600):
        et = _tokens(f"{e.get('kind','')} {e.get('task_type','')} {e.get('text','')}")
        if not et or not q:
            continue
        inter = len(q & et)
        if inter <= 0:
            continue
        sim = inter / max(1, len(q | et))
        quality = 0.15 if bool(e.get('ok')) else -0.12
        speed = 0.1 if int(e.get('latency_ms') or 0) < 1200 else -0.06
        score = sim + quality + speed
        out.append((score, e))
    out.sort(key=lambda x: x[0], reverse=True)
    return [e for _, e in out[:max(1, int(limit or 5))]]


def strategy_hints(kind: str, text: str, task_type: str = '') -> dict[str, Any]:
    sims = find_similar(kind=kind, text=text, task_type=task_type, limit=8)
    if not sims:
        return {'ok': True, 'hints': [], 'similar': []}
    good = [s for s in sims if bool(s.get('ok'))]
    bad = [s for s in sims if not bool(s.get('ok'))]
    hints = []
    if good:
        hints.append('Preferir estratégia semelhante aos episódios de sucesso com baixa latência.')
    if bad:
        hints.append('Evitar abordagem que falhou em episódios análogos recentes.')
    return {'ok': True, 'hints': hints[:3], 'similar': sims[:5]}


def recent_structured(limit: int = 120) -> list[dict[str, Any]]:
    if not EPISODIC_STRUCTURED_PATH.exists():
        return []
    rows = []
    for ln in EPISODIC_STRUCTURED_PATH.read_text(encoding='utf-8', errors='ignore').splitlines()[-max(10, int(limit or 120)):]:
        if not ln.strip():
            continue
        try:
            rows.append(json.loads(ln))
        except Exception:
            continue
    return rows


def find_similar_structured(problem: str, task_type: str = 'planning', limit: int = 5) -> list[dict[str, Any]]:
    q = _tokens(f"{task_type} {problem}")
    now = int(time.time())
    out: list[tuple[float, dict[str, Any]]] = []
    for e in recent_structured(limit=1200):
        epi = e.get('episodic_memory') if isinstance(e.get('episodic_memory'), dict) else {}
        txt = f"{e.get('task_type','')} {epi.get('problema','')} {epi.get('resultado','')} {epi.get('hipotese_pos_hoc','')}"
        et = _tokens(txt)
        if not et or not q:
            continue
        inter = len(q & et)
        if inter <= 0:
            continue
        sim = inter / max(1, len(q | et))
        ok_bonus = 0.15 if bool(e.get('ok')) else -0.08
        prm = epi.get('prm_score_final')
        prm_bonus = 0.0
        if isinstance(prm, (int, float)):
            prm_bonus = max(-0.1, min(0.2, float(prm) - 0.5))

        # recency bonus (0..0.08): prioriza episódios recentes sem sobrepor similaridade
        ets = int(e.get('ts') or 0)
        age_days = max(0.0, float(now - ets) / 86400.0) if ets > 0 else 9999.0
        recency_bonus = max(0.0, 0.08 - min(0.08, age_days * 0.01))

        score = sim + ok_bonus + prm_bonus + recency_bonus
        out.append((score, e))
    out.sort(key=lambda x: x[0], reverse=True)

    shaped: list[dict[str, Any]] = []
    for score, e in out[:max(1, int(limit or 5))]:
        epi = e.get('episodic_memory') if isinstance(e.get('episodic_memory'), dict) else {}
        shaped.append({
            'score': round(float(score), 4),
            'episode_id': str(e.get('episode_id') or ''),
            'ts': int(e.get('ts') or 0),
            'task_type': str(e.get('task_type') or ''),
            'strategy': str(e.get('strategy') or ''),
            'ok': bool(e.get('ok')),
            'problema': str(epi.get('problema') or '')[:240],
            'resultado': str(epi.get('resultado') or '')[:260],
            'hipotese_pos_hoc': str(epi.get('hipotese_pos_hoc') or '')[:220],
            'prm_score_final': epi.get('prm_score_final'),
        })
    return shaped


def _infer_domain(text: str, task_type: str = '') -> str:
    t = f"{str(task_type or '')} {str(text or '')}".lower()
    buckets = {
        'software': ['api', 'endpoint', 'debug', 'bug', 'deploy', 'build', 'docker', 'latency', 'timeout', 'retry', 'service'],
        'planning': ['planejar', 'plano', 'cronograma', 'roteiro', 'checklist', 'organizar'],
        'finance': ['orçamento', 'custo', 'budget', 'gasto', 'economia', 'barato', 'preço'],
        'operations': ['vps', 'cpu', 'memoria', 'memória', 'infra', 'monitoramento', 'uptime', 'swarm'],
        'events': ['festa', 'evento', 'convidados', 'decoração', 'comida'],
        'content': ['resumo', 'sumarizar', 'texto', 'artigo', 'post', 'headline'],
    }
    best = ('general', 0)
    for name, kws in buckets.items():
        score = sum(1 for k in kws if k in t)
        if score > best[1]:
            best = (name, score)
    return best[0]


def _constraint_tags(text: str) -> list[str]:
    t = str(text or '').lower()
    tags: list[str] = []
    if any(k in t for k in ['orçamento', 'budget', 'custo', 'barato', 'limite de gasto']):
        tags.append('budget')
    if any(k in t for k in ['prazo', 'deadline', 'urgente', 'até ', 'em ', 'tempo']):
        tags.append('time')
    if any(k in t for k in ['depend', 'bloqueio', 'porta', 'acesso', 'credencial', 'chave']):
        tags.append('dependencies')
    if any(k in t for k in ['cpu', 'memoria', 'memória', 'latência', 'latency', 'throughput', 'recursos']):
        tags.append('resources')
    return tags


def _uncertainty_level(text: str, ok: bool | None = None) -> str:
    t = str(text or '').lower()
    markers = ['talvez', 'incerto', 'não sei', 'nao sei', 'hipótese', 'hipotese', 'falha', 'erro', 'unknown']
    if any(m in t for m in markers):
        return 'high'
    if ok is False:
        return 'high'
    return 'low'


def structural_signature(*, problem: str, task_type: str = 'general', ok: bool | None = None, extra_text: str = '') -> dict[str, Any]:
    txt = f"{problem} {extra_text}".strip()
    tt = str(task_type or 'general').strip().lower() or 'general'
    if tt in ('planning', 'debug', 'summarization', 'execution', 'research', 'assistant'):
        problem_type = tt
    elif any(k in txt.lower() for k in ['debug', 'erro', 'falha', 'timeout', 'bug']):
        problem_type = 'debug'
    elif any(k in txt.lower() for k in ['planejar', 'plano', 'roteiro']):
        problem_type = 'planning'
    elif any(k in txt.lower() for k in ['executar', 'rodar', 'deploy', 'aplicar']):
        problem_type = 'execution'
    else:
        problem_type = 'general'

    return {
        'problem_type': problem_type,
        'constraints': _constraint_tags(txt),
        'uncertainty': _uncertainty_level(txt, ok=ok),
        'domain': _infer_domain(txt, task_type=tt),
        'task_type': tt,
    }


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return float(len(a & b)) / float(max(1, len(a | b)))


def find_structural_analogy(problem: str, task_type: str = 'planning', limit: int = 5, require_cross_domain: bool = False) -> dict[str, Any]:
    query_sig = structural_signature(problem=problem, task_type=task_type)
    now = int(time.time())
    ranked: list[tuple[float, dict[str, Any], dict[str, Any]]] = []

    for e in recent_structured(limit=1800):
        epi = e.get('episodic_memory') if isinstance(e.get('episodic_memory'), dict) else {}
        ep_problem = str(epi.get('problema') or '')
        ep_hyp = str(epi.get('hipotese_pos_hoc') or '')
        ep_result = str(epi.get('resultado') or '')
        ep_task = str(e.get('task_type') or 'general')
        ep_sig = structural_signature(
            problem=ep_problem,
            task_type=ep_task,
            ok=bool(e.get('ok')),
            extra_text=f"{ep_hyp} {ep_result}",
        )

        if require_cross_domain and ep_sig.get('domain') == query_sig.get('domain'):
            continue

        type_score = 1.0 if ep_sig.get('problem_type') == query_sig.get('problem_type') else 0.0
        constraints_score = _jaccard(set(ep_sig.get('constraints') or []), set(query_sig.get('constraints') or []))
        uncertainty_score = 1.0 if ep_sig.get('uncertainty') == query_sig.get('uncertainty') else 0.0
        domain_score = 1.0 if ep_sig.get('domain') == query_sig.get('domain') else 0.0

        ok_bonus = 0.12 if bool(e.get('ok')) else -0.1
        prm = epi.get('prm_score_final')
        prm_bonus = max(-0.06, min(0.16, (float(prm) - 0.5))) if isinstance(prm, (int, float)) else 0.0
        analogy_feedback_bonus = 0.0
        if bool(e.get('analogia_usada')):
            if e.get('analogia_foi_util') is True:
                analogy_feedback_bonus = 0.18
            elif e.get('analogia_foi_util') is False:
                analogy_feedback_bonus = -0.08
        ets = int(e.get('ts') or 0)
        age_days = max(0.0, float(now - ets) / 86400.0) if ets > 0 else 9999.0
        recency_bonus = max(0.0, 0.05 - min(0.05, age_days * 0.01))

        # estrutura > lexical; domínio não domina o score
        score = (
            0.38 * type_score
            + 0.36 * constraints_score
            + 0.16 * uncertainty_score
            + 0.10 * domain_score
            + ok_bonus
            + prm_bonus
            + analogy_feedback_bonus
            + recency_bonus
        )

        ranked.append((score, e, ep_sig))

    ranked.sort(key=lambda x: x[0], reverse=True)
    shaped: list[dict[str, Any]] = []
    for score, e, ep_sig in ranked[:max(1, int(limit or 5))]:
        epi = e.get('episodic_memory') if isinstance(e.get('episodic_memory'), dict) else {}
        shaped.append({
            'score': round(float(score), 4),
            'episode_id': str(e.get('episode_id') or ''),
            'task_type': str(e.get('task_type') or ''),
            'strategy': str(e.get('strategy') or ''),
            'ok': bool(e.get('ok')),
            'signature': ep_sig,
            'problem': str(epi.get('problema') or '')[:240],
            'result': str(epi.get('resultado') or '')[:260],
            'hypothesis': str(epi.get('hipotese_pos_hoc') or '')[:220],
            'cross_domain': ep_sig.get('domain') != query_sig.get('domain'),
            'analogia_usada': bool(e.get('analogia_usada')),
            'analogia_foi_util': e.get('analogia_foi_util'),
        })

    first_cross = next((x for x in shaped if bool(x.get('cross_domain'))), None)
    analogy = None
    if first_cross:
        analogy = {
            'source_episode_id': first_cross.get('episode_id'),
            'source_domain': first_cross.get('signature', {}).get('domain'),
            'target_domain': query_sig.get('domain'),
            'transfer_rule': f"Reaplicar padrão de {first_cross.get('signature', {}).get('problem_type')} com restrições {first_cross.get('signature', {}).get('constraints') or []} no novo domínio.",
            'why_it_worked': str(first_cross.get('hypothesis') or '')[:220],
        }

    return {
        'ok': True,
        'query_signature': query_sig,
        'matches': shaped,
        'first_cross_domain_analogy': analogy,
        'count': len(shaped),
    }


def _append_procedural(*, task_type: str, strategy: str, ok: bool, prm_score_final: float | None, latency_ms: int, source_episode_id: str):
    PROCEDURAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    row = {
        'ts': int(time.time()),
        'task_type': str(task_type or ''),
        'strategy': str(strategy or ''),
        'ok': bool(ok),
        'prm_score_final': (float(prm_score_final) if prm_score_final is not None else None),
        'latency_ms': int(latency_ms or 0),
        'source_episode_id': str(source_episode_id or ''),
    }
    with PROCEDURAL_PATH.open('a', encoding='utf-8') as f:
        f.write(json.dumps(row, ensure_ascii=False) + '\n')


def procedural_hints(task_type: str, limit: int = 120) -> dict[str, Any]:
    if not PROCEDURAL_PATH.exists():
        return {'ok': True, 'task_type': str(task_type or ''), 'best_strategies': []}
    rows = []
    for ln in PROCEDURAL_PATH.read_text(encoding='utf-8', errors='ignore').splitlines()[-max(10, int(limit or 120)):]:
        if not ln.strip():
            continue
        try:
            o = json.loads(ln)
        except Exception:
            continue
        if str(o.get('task_type') or '') == str(task_type or ''):
            rows.append(o)

    agg: dict[str, dict[str, Any]] = {}
    for r in rows:
        k = str(r.get('strategy') or 'unknown')
        a = agg.setdefault(k, {'strategy': k, 'n': 0, 'ok_n': 0, 'avg_prm': 0.0, 'avg_latency_ms': 0.0})
        a['n'] += 1
        if bool(r.get('ok')):
            a['ok_n'] += 1
        p = r.get('prm_score_final')
        if isinstance(p, (int, float)):
            a['avg_prm'] += float(p)
        a['avg_latency_ms'] += int(r.get('latency_ms') or 0)

    out = []
    for _, a in agg.items():
        n = max(1, int(a['n']))
        out.append({
            'strategy': a['strategy'],
            'n': a['n'],
            'success_rate': round(float(a['ok_n']) / n, 4),
            'avg_prm': round(float(a['avg_prm']) / n, 4),
            'avg_latency_ms': int(float(a['avg_latency_ms']) / n),
        })
    out.sort(key=lambda x: (x.get('success_rate') or 0.0, x.get('avg_prm') or 0.0), reverse=True)
    return {'ok': True, 'task_type': str(task_type or ''), 'best_strategies': out[:5]}


def append_procedural_learning(*, task_type: str, heuristic: str, bottleneck_step: str = '', outcome: str = 'observed', source_episode_id: str = '', confidence: float | None = None, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    PROCEDURAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    row = {
        'ts': int(time.time()),
        'kind': 'heuristic_rule',
        'task_type': str(task_type or ''),
        'heuristic': str(heuristic or '')[:500],
        'bottleneck_step': str(bottleneck_step or '')[:300],
        'outcome': str(outcome or 'observed')[:60],
        'source_episode_id': str(source_episode_id or ''),
        'confidence': (float(confidence) if isinstance(confidence, (int, float)) else None),
        'meta': dict(meta or {}),
    }
    with PROCEDURAL_PATH.open('a', encoding='utf-8') as f:
        f.write(json.dumps(row, ensure_ascii=False) + '\n')
    return {'ok': True, 'row': row}


def procedural_rule_frequency(heuristic: str, task_type: str = '', limit: int = 800) -> dict[str, Any]:
    if not PROCEDURAL_PATH.exists():
        return {'ok': True, 'count': 0}
    h = str(heuristic or '').strip().lower()
    t = str(task_type or '').strip().lower()
    c = 0
    for ln in PROCEDURAL_PATH.read_text(encoding='utf-8', errors='ignore').splitlines()[-max(50, int(limit or 800)):]:
        if not ln.strip():
            continue
        try:
            o = json.loads(ln)
        except Exception:
            continue
        if str(o.get('kind') or '') != 'heuristic_rule':
            continue
        if t and str(o.get('task_type') or '').strip().lower() != t:
            continue
        if str(o.get('heuristic') or '').strip().lower() == h:
            c += 1
    return {'ok': True, 'count': c}


def append_learning_proposal(kind: str, title: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    LEARNING_PROPOSALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    row = {
        'id': f"lp_{int(time.time())}_{abs(hash(str(title or '')))%100000}",
        'ts': int(time.time()),
        'kind': str(kind or 'proposal'),
        'title': str(title or '')[:220],
        'details': dict(details or {}),
    }
    with LEARNING_PROPOSALS_PATH.open('a', encoding='utf-8') as f:
        f.write(json.dumps(row, ensure_ascii=False) + '\n')
    return {'ok': True, 'proposal': row}


def working_memory_set(session_key: str, *, contexto_imediato: str, ultimos_tool_calls: list[dict[str, Any]] | None = None, estado_plano_execucao: dict[str, Any] | None = None):
    WORKING_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = json.loads(WORKING_STATE_PATH.read_text(encoding='utf-8')) if WORKING_STATE_PATH.exists() else {}
    except Exception:
        data = {}
    data[str(session_key or 'default')] = {
        'ts': int(time.time()),
        'contexto_imediato': str(contexto_imediato or '')[:1600],
        'ultimos_tool_calls': list(ultimos_tool_calls or [])[-5:],
        'estado_plano_execucao': dict(estado_plano_execucao or {}),
    }
    WORKING_STATE_PATH.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')


def working_memory_get(session_key: str = 'default') -> dict[str, Any]:
    if not WORKING_STATE_PATH.exists():
        return {}
    try:
        data = json.loads(WORKING_STATE_PATH.read_text(encoding='utf-8'))
        return data.get(str(session_key or 'default')) or {}
    except Exception:
        return {}


def get_task_memory_policy(task_type: str = 'planning') -> dict[str, Any]:
    t = str(task_type or 'planning').strip().lower()
    policies = {
        'planning': {'episodic_limit': 4, 'procedural_limit': 180, 'max_chars': 1500},
        'debug': {'episodic_limit': 5, 'procedural_limit': 220, 'max_chars': 1900},
        'summarization': {'episodic_limit': 2, 'procedural_limit': 100, 'max_chars': 1100},
        'code': {'episodic_limit': 4, 'procedural_limit': 200, 'max_chars': 1700},
        'general': {'episodic_limit': 3, 'procedural_limit': 160, 'max_chars': 1400},
    }
    return {'task_type': t, **policies.get(t, policies['general'])}


def layered_recall(problem: str, task_type: str = 'planning', limit: int = 3) -> dict[str, Any]:
    pol = get_task_memory_policy(task_type)
    eff_limit = max(1, min(int(pol.get('episodic_limit') or 3), int(limit or pol.get('episodic_limit') or 3)))
    epis = find_similar_structured(problem=problem, task_type=task_type, limit=eff_limit)
    proc = procedural_hints(task_type=task_type, limit=int(pol.get('procedural_limit') or 180))
    wm = working_memory_get('default')
    top_strategy = None
    bs = proc.get('best_strategies') if isinstance(proc, dict) else []
    if isinstance(bs, list) and bs:
        top_strategy = bs[0].get('strategy')
    return {
        'ok': True,
        'policy': pol,
        'working_memory': wm,
        'episodic_similar': epis,
        'episodic_similar_count': len(epis),
        'procedural_hints': proc,
        'top_strategy_hint': top_strategy,
    }


def layered_recall_compact(problem: str, task_type: str = 'planning', limit: int = 3, max_chars: int = 1800) -> dict[str, Any]:
    base = layered_recall(problem=problem, task_type=task_type, limit=limit)
    pol = base.get('policy') if isinstance(base.get('policy'), dict) else get_task_memory_policy(task_type)
    wm = base.get('working_memory') if isinstance(base.get('working_memory'), dict) else {}
    epis = base.get('episodic_similar') if isinstance(base.get('episodic_similar'), list) else []
    proc = base.get('procedural_hints') if isinstance(base.get('procedural_hints'), dict) else {'best_strategies': []}
    policy_budget = int(pol.get('max_chars') or 1500)
    budget_max = max(600, int(max_chars or policy_budget))

    compact = {
        'working_memory': {
            'contexto_imediato': str(wm.get('contexto_imediato') or '')[:300],
            'estado_plano_execucao': wm.get('estado_plano_execucao') if isinstance(wm.get('estado_plano_execucao'), dict) else {},
            'ultimos_tool_calls': (wm.get('ultimos_tool_calls') if isinstance(wm.get('ultimos_tool_calls'), list) else [])[-2:],
        },
        'episodic_similar': [
            {
                'score': e.get('score'),
                'strategy': e.get('strategy'),
                'ok': e.get('ok'),
                'problema': str(e.get('problema') or '')[:100],
                'resultado': str(e.get('resultado') or '')[:100],
                'prm_score_final': e.get('prm_score_final'),
            }
            for e in epis[:3]
        ],
        'procedural_hints': {
            'task_type': proc.get('task_type'),
            'best_strategies': [
                {
                    'strategy': s.get('strategy'),
                    'success_rate': s.get('success_rate'),
                    'avg_prm': s.get('avg_prm'),
                }
                for s in (proc.get('best_strategies') if isinstance(proc.get('best_strategies'), list) else [])[:3]
            ],
        },
        'top_strategy_hint': base.get('top_strategy_hint'),
    }

    def _size(obj: dict[str, Any]) -> int:
        return len(json.dumps(obj, ensure_ascii=False))

    # progressive shrinking to honor hard budget
    if _size(compact) > budget_max:
        compact['working_memory']['ultimos_tool_calls'] = []
    if _size(compact) > budget_max and len(compact['episodic_similar']) > 2:
        compact['episodic_similar'] = compact['episodic_similar'][:2]
    if _size(compact) > budget_max:
        for e in compact['episodic_similar']:
            e['resultado'] = str(e.get('resultado') or '')[:48]
            e['problema'] = str(e.get('problema') or '')[:72]
    if _size(compact) > budget_max and len(compact['episodic_similar']) > 1:
        compact['episodic_similar'] = compact['episodic_similar'][:1]
    if _size(compact) > budget_max:
        compact['working_memory']['contexto_imediato'] = str(compact['working_memory'].get('contexto_imediato') or '')[:120]
    if _size(compact) > budget_max:
        compact['procedural_hints']['best_strategies'] = (compact['procedural_hints'].get('best_strategies') or [])[:1]

    compact['budget'] = {
        'max_chars': budget_max,
        'actual_chars': 0,
        'truncated': False,
    }
    final_size = _size(compact)
    if final_size > budget_max:
        compact['working_memory']['contexto_imediato'] = str(compact['working_memory'].get('contexto_imediato') or '')[:80]
        final_size = _size(compact)
    compact['budget'] = {
        'max_chars': budget_max,
        'actual_chars': final_size,
        'truncated': final_size > budget_max,
    }
    return compact


def append_structured_episode(
    *,
    problem: str,
    plano_gerado: Any,
    passos_executados: list[dict[str, Any]] | None,
    resultado: str,
    prm_score_final: float | None,
    hipotese_pos_hoc: str,
    task_type: str = 'planning',
    strategy: str = 'orchestrator_qwen_tools',
    ok: bool = True,
    latency_ms: int = 0,
    work_context: dict[str, Any] | None = None,
    quality_eval: dict[str, Any] | None = None,
    memory_governor: dict[str, Any] | None = None,
    analogia_usada: bool = False,
    analogia_source_episode_id: str = '',
    analogia_foi_util: bool | None = None,
):
    EPISODIC_STRUCTURED_PATH.parent.mkdir(parents=True, exist_ok=True)
    now = int(time.time())
    steps = list(passos_executados or [])[:8]
    plan_obj = plano_gerado if isinstance(plano_gerado, (dict, list)) else {'raw': str(plano_gerado or '')[:1200]}

    episode_id = f"ep_{now}_{abs(hash(str(problem or '')[:80])) % 1000000}"
    row = {
        'episode_id': episode_id,
        'ts': now,
        'task_type': str(task_type or ''),
        'strategy': str(strategy or ''),
        'ok': bool(ok),
        'latency_ms': int(latency_ms or 0),
        'analogia_usada': bool(analogia_usada),
        'analogia_source_episode_id': str(analogia_source_episode_id or ''),
        'analogia_foi_util': (bool(analogia_foi_util) if isinstance(analogia_foi_util, bool) else None),
        # Camadas de memória explícitas
        'working_memory': {
            'contexto_imediato': str(problem or '')[:1200],
            'ultimos_tool_calls': steps[-3:],
            'estado_plano_execucao': {
                'num_passos': len(steps),
                'finalizou': bool(ok),
            },
            'runtime': dict(work_context or {}),
            'context_profile': str((work_context or {}).get('context_profile') or ''),
            'context_fallback': dict((work_context or {}).get('context_fallback') or {}),
            'context_metrics': dict((work_context or {}).get('context_metrics') or {}),
        },
        'episodic_memory': {
            'problema': str(problem or '')[:2000],
            'plano_gerado': plan_obj,
            'passos_executados': steps,
            'resultado': str(resultado or '')[:2400],
            'prm_score_final': (float(prm_score_final) if prm_score_final is not None else None),
            'hipotese_pos_hoc': str(hipotese_pos_hoc or '')[:1200],
        },
        'semantic_memory_ref': {
            'rag_enabled': True,
            'semantic_cache_enabled': True,
        },
        'quality_eval': dict(quality_eval or {}),
        'memory_governor': dict(memory_governor or {}),
        'memory_statement': {
            'fact': str((memory_governor or {}).get('fact') or '')[:600],
            'hypothesis': str((memory_governor or {}).get('hypothesis') or '')[:600],
            'plan': str((memory_governor or {}).get('plan') or '')[:600],
            'interpretation': str((memory_governor or {}).get('interpretation') or '')[:600],
        },
        'procedural_memory_ref': {
            'task_type': str(task_type or ''),
            'strategy': str(strategy or ''),
        },
    }

    with EPISODIC_STRUCTURED_PATH.open('a', encoding='utf-8') as f:
        f.write(json.dumps(row, ensure_ascii=False) + '\n')

    try:
        working_memory_set(
            'default',
            contexto_imediato=str(problem or ''),
            ultimos_tool_calls=steps[-3:],
            estado_plano_execucao={'num_passos': len(steps), 'finalizou': bool(ok), 'episode_id': episode_id},
        )
    except Exception:
        pass

    try:
        _append_procedural(
            task_type=str(task_type or ''),
            strategy=str(strategy or ''),
            ok=bool(ok),
            prm_score_final=(float(prm_score_final) if prm_score_final is not None else None),
            latency_ms=int(latency_ms or 0),
            source_episode_id=episode_id,
        )
    except Exception:
        pass

    return {'ok': True, 'episode_id': episode_id}
