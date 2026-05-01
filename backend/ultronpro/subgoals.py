from __future__ import annotations

from pathlib import Path
from typing import Any
import json
import time

from ultronpro import llm

PATH = Path(__file__).resolve().parent.parent / 'data' / 'subgoal_dag.json'
SUBGOAL_TYPES = ('clarification', 'execution', 'validation', 'consolidation')


def _default() -> dict[str, Any]:
    return {'updated_at': int(time.time()), 'roots': []}


def load() -> dict[str, Any]:
    try:
        if PATH.exists():
            d = json.loads(PATH.read_text())
            if isinstance(d, dict):
                d.setdefault('roots', [])
                return d
    except Exception:
        pass
    return _default()


def save(d: dict[str, Any]):
    d['updated_at'] = int(time.time())
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(json.dumps(d, ensure_ascii=False, indent=2))


def _normalize_status(v: Any) -> str:
    s = str(v or 'open').strip().lower()
    return s if s in ('open', 'doing', 'blocked', 'done', 'skipped') else 'open'


def _normalize_type(v: Any) -> str:
    s = str(v or 'execution').strip().lower()
    return s if s in SUBGOAL_TYPES else 'execution'


def _normalize_list(v: Any) -> list[str]:
    if not isinstance(v, list):
        return []
    out = []
    for x in v:
        sx = str(x or '').strip()
        if sx:
            out.append(sx[:120])
    return out


def _normalize_node(it: dict[str, Any], idx: int, root_id: str, title: str) -> dict[str, Any] | None:
    if not isinstance(it, dict) or not it.get('title'):
        return None
    nid = str(it.get('id') or f'{root_id}_n{idx}')
    deps = _normalize_list(it.get('dependencies'))
    parent_id = str(it.get('parent_id')) if it.get('parent_id') else (deps[0] if deps else None)
    node = {
        'id': nid,
        'goal_id': root_id,
        'title': str(it.get('title'))[:180],
        'objective': str(it.get('objective') or it.get('title') or '')[:600],
        'parent_id': parent_id,
        'status': _normalize_status(it.get('status')),
        'type': _normalize_type(it.get('type')),
        'priority': int(max(1, min(7, int(it.get('priority') or 5)))),
        'success_criteria': str(it.get('success_criteria') or 'Resultado verificável não especificado')[:260],
        'dependencies': deps,
        'estimated_cost': str(it.get('estimated_cost') or 'medium')[:80],
        'horizon': str(it.get('horizon') or 'current_cycle')[:80],
        'retry_count': int(max(0, int(it.get('retry_count') or 0))),
        'origin': str(it.get('origin') or 'llm')[:40],
        'created_at': int(time.time()),
        'updated_at': int(time.time()),
    }
    if node['parent_id'] == node['id']:
        node['parent_id'] = None
    if node['id'] not in node['dependencies'] and node['parent_id']:
        node['dependencies'] = list(dict.fromkeys(node['dependencies'] + [node['parent_id']]))
    return node


def _fallback_nodes(root_id: str, title: str, objective: str) -> list[dict[str, Any]]:
    items = [
        {
            'id': f'{root_id}_clarify',
            'title': f'Clarificar escopo e métrica de sucesso: {title}',
            'objective': f'Definir o que conta como conclusão do goal "{title}" e quais restrições precisam ser respeitadas.',
            'type': 'clarification',
            'priority': 7,
            'success_criteria': 'Existe uma definição objetiva de sucesso com pelo menos 2 métricas verificáveis e restrições explícitas.',
            'dependencies': [],
            'estimated_cost': 'low',
            'horizon': 'current_cycle',
            'origin': 'fallback',
        },
        {
            'id': f'{root_id}_execute',
            'title': 'Executar menor experimento útil',
            'objective': f'Avançar o goal com a menor intervenção que produza evidência observável. Contexto: {objective[:220]}',
            'type': 'execution',
            'priority': 6,
            'success_criteria': 'Foi executado um experimento ou ação concreta e existe artefato observável do resultado.',
            'dependencies': [f'{root_id}_clarify'],
            'estimated_cost': 'medium',
            'horizon': 'current_cycle',
            'origin': 'fallback',
        },
        {
            'id': f'{root_id}_validate',
            'title': 'Validar resultado contra critério objetivo',
            'objective': 'Medir se a execução realmente satisfaz o goal ou se precisa de correção.',
            'type': 'validation',
            'priority': 6,
            'success_criteria': 'Existe verificação explícita comparando resultado observado versus critério objetivo definido.',
            'dependencies': [f'{root_id}_execute'],
            'estimated_cost': 'low',
            'horizon': 'current_cycle',
            'origin': 'fallback',
        },
        {
            'id': f'{root_id}_consolidate',
            'title': 'Consolidar aprendizado e próximo ciclo',
            'objective': 'Registrar o que funcionou, o que falhou e a próxima ação recomendada.',
            'type': 'consolidation',
            'priority': 5,
            'success_criteria': 'Aprendizado registrado com decisão explícita de continuar, corrigir ou encerrar o goal.',
            'dependencies': [f'{root_id}_validate'],
            'estimated_cost': 'low',
            'horizon': 'next_cycle',
            'origin': 'fallback',
        },
    ]
    return [_normalize_node(it, i, root_id, title) for i, it in enumerate(items, start=1) if _normalize_node(it, i, root_id, title)]


def _ensure_required_types(nodes: list[dict[str, Any]], root_id: str, title: str, objective: str) -> list[dict[str, Any]]:
    present = {str(n.get('type')) for n in nodes}
    if all(t in present for t in SUBGOAL_TYPES):
        return nodes
    fallback = _fallback_nodes(root_id, title, objective)
    by_type = {str(n.get('type')): n for n in nodes}
    for f in fallback:
        by_type.setdefault(str(f.get('type')), f)
    ordered = []
    seen = set()
    for t in SUBGOAL_TYPES:
        n = by_type.get(t)
        if n and n.get('id') not in seen:
            ordered.append(n)
            seen.add(n.get('id'))
    for n in nodes:
        if n.get('id') not in seen:
            ordered.append(n)
            seen.add(n.get('id'))
    return ordered


def synthesize_for_goal(title: str, objective: str, max_nodes: int = 7) -> dict[str, Any]:
    title = (title or 'Goal').strip()
    objective = (objective or '').strip()
    root_id = f'root_{int(time.time())}'
    nodes = None
    try:
        prompt = f"""Decompose the goal into a DAG of subgoals.
Return ONLY JSON array.
Each item MUST contain these fields:
id,title,objective,type,parent_id,dependencies,priority,success_criteria,estimated_cost,horizon,origin.

Rules:
- Allowed type values: clarification, execution, validation, consolidation.
- The DAG MUST contain at least one subgoal of each type.
- Dependencies must be explicit and coherent.
- success_criteria must be objectively verifiable, concrete, and measurable.
- Avoid vague criteria like 'improve the system' or 'make it better'.
- Good examples:
  - 'RAG com cobertura > 80% nos últimos 50 traces de planning'
  - 'p95 < 5s em 95% dos requests nas últimas 2 horas'
- Bad examples:
  - 'melhorar o RAG'
  - 'sistema mais rápido'
- Prefer a sequence where clarification precedes execution, execution precedes validation, and validation precedes consolidation.
- Keep total nodes <= {max_nodes}.

Goal: {title}
Objective: {objective}
"""
        raw = llm.complete(prompt, strategy='cheap', json_mode=True)
        arr = json.loads(raw) if raw else []
        if isinstance(arr, list) and arr:
            out = []
            for i, it in enumerate(arr[:max_nodes], start=1):
                n = _normalize_node(it, i, root_id, title)
                if n:
                    out.append(n)
            out = _ensure_required_types(out, root_id, title, objective)
            if out:
                nodes = out[:max_nodes]
    except Exception:
        nodes = None

    if not nodes:
        nodes = _fallback_nodes(root_id, title, objective)[:max_nodes]

    root = {
        'id': root_id,
        'title': title,
        'objective': objective[:1200],
        'status': 'active',
        'created_at': int(time.time()),
        'updated_at': int(time.time()),
        'schema_version': '8.1',
        'nodes': nodes,
    }

    d = load()
    d.setdefault('roots', []).append(root)
    d['roots'] = d['roots'][-60:]
    save(d)
    return root


def list_roots(limit: int = 20) -> list[dict[str, Any]]:
    d = load()
    return (d.get('roots') or [])[-max(1, int(limit)):]


def get_root(root_id: str) -> dict[str, Any] | None:
    d = load()
    for r in d.get('roots') or []:
        if r.get('id') == root_id:
            return r
    return None


def find_latest_root(title: str | None = None, objective: str | None = None) -> dict[str, Any] | None:
    d = load()
    roots = list(d.get('roots') or [])
    t = str(title or '').strip().lower()
    o = str(objective or '').strip().lower()
    for r in reversed(roots):
        rt = str(r.get('title') or '').strip().lower()
        ro = str(r.get('objective') or '').strip().lower()
        if t and rt == t:
            return r
        if o and ro == o:
            return r
    return roots[-1] if roots else None


def _cost_rank(v: Any) -> int:
    s = str(v or 'medium').strip().lower()
    order = {'low': 0, 'medium': 1, 'high': 2}
    return order.get(s, 1)


def _deps_done(root: dict[str, Any], node: dict[str, Any]) -> bool:
    deps = [str(x) for x in (node.get('dependencies') or []) if str(x).strip()]
    if not deps:
        return True
    idx = {str(n.get('id')): str(n.get('status') or 'open') for n in (root.get('nodes') or [])}
    return all(idx.get(dep) == 'done' for dep in deps)


def select_next_node(root: dict[str, Any]) -> dict[str, Any] | None:
    nodes = [n for n in (root.get('nodes') or []) if str(n.get('status') or 'open') == 'open' and _deps_done(root, n)]
    if not nodes:
        return None

    clar = [n for n in nodes if str(n.get('type') or '') == 'clarification']
    pool = clar if clar else nodes
    pool = sorted(pool, key=lambda n: (-int(n.get('priority') or 0), _cost_rank(n.get('estimated_cost')), str(n.get('title') or '')))
    return pool[0] if pool else None


def update_node(root_id: str, node_id: str, patch: dict[str, Any]) -> bool:
    d = load()
    for r in d.get('roots') or []:
        if r.get('id') != root_id:
            continue
        for n in r.get('nodes') or []:
            if n.get('id') == node_id:
                for k, v in (patch or {}).items():
                    if k == 'status':
                        n[k] = _normalize_status(v)
                    elif k in ('dependencies',):
                        n[k] = _normalize_list(v)
                    elif k == 'type':
                        n[k] = _normalize_type(v)
                    elif k == 'priority':
                        n[k] = int(max(1, min(7, int(v or 5))))
                    elif k == 'retry_count':
                        n[k] = int(max(0, int(v or 0)))
                    elif k in ('title', 'objective', 'success_criteria', 'estimated_cost', 'horizon', 'origin', 'parent_id', 'verification_note', 'last_result'):
                        n[k] = v
                n['updated_at'] = int(time.time())
                save(d)
                return True
    return False


def mark_node(root_id: str, node_id: str, status: str = 'done') -> bool:
    return update_node(root_id, node_id, {'status': status})
