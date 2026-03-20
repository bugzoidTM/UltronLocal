from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from ultronpro import explicit_abstractions

DATA_PATH = Path('/app/data/structural_mappings.jsonl')

_DOMAIN_HINTS: dict[str, dict[str, list[str]]] = {
    'debugging': {
        'tokens': ['bug', 'erro', 'falha', 'stacktrace', 'regressão', 'exception'],
        'role_map': ['objetivo->corrigir_bug', 'risco->regressão', 'progresso->redução_da_causa_raiz'],
    },
    'infra': {
        'tokens': ['latência', 'latencia', 'deploy', 'serviço', 'timeout', 'fila', 'incidente'],
        'role_map': ['objetivo->restaurar_serviço', 'risco->indisponibilidade', 'progresso->redução_do_impacto'],
    },
    'pipeline': {
        'tokens': ['job', 'etl', 'pipeline', 'dag', 'falha', 'retry'],
        'role_map': ['objetivo->normalizar_fluxo', 'risco->quebra_do_pipeline', 'progresso->avanço_de_estágio'],
    },
    'planning': {
        'tokens': ['restrição', 'deadline', 'recurso', 'sequência', 'sequencia'],
        'role_map': ['objetivo->plano_viável', 'risco->violação_de_restrição', 'progresso->redução_de_pendências'],
    },
}


def _now() -> int:
    return int(time.time())


def _ensure_parent(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)


def _normalize(text: str) -> str:
    return str(text or '').strip().lower()


def _domain_signature(target_domain: str, target_text: str | None = None) -> dict[str, Any]:
    dom = _normalize(target_domain)
    txt = _normalize(target_text or '')
    hints = _DOMAIN_HINTS.get(dom, {})
    tokens = hints.get('tokens') or []
    matched = [t for t in tokens if t in txt]
    return {
        'target_domain': dom or 'general',
        'matched_tokens': matched,
        'hint_strength': round(min(1.0, len(matched) / max(1, len(tokens))), 4),
        'role_map': hints.get('role_map') or [],
    }


def _structural_similarity(abstraction: dict[str, Any], target_domain: str, target_text: str | None = None) -> float:
    sig = _domain_signature(target_domain, target_text)
    src = [_normalize(x) for x in (abstraction.get('source_domains') or []) if _normalize(x)]
    confidence = float(abstraction.get('confidence') or 0.0)
    generality = float(abstraction.get('generality_score') or 0.0)
    same_family = 0.0
    if sig['target_domain'] in src:
        same_family = 0.35
    elif any(x in ('risk_avoidance', 'resource_bounded_planning', 'grid_navigation') for x in src):
        same_family = 0.18
    return round(min(1.0, same_family + (0.25 * sig['hint_strength']) + (0.25 * confidence) + (0.15 * generality)), 4)


def _map_conditions(conditions: list[str], target_domain: str) -> list[str]:
    dom = _normalize(target_domain)
    out = []
    for cond in conditions:
        c = _normalize(cond)
        mapped = cond
        if dom == 'debugging':
            mapped = mapped.replace('objetivo', 'bug').replace('ação', 'intervenção').replace('risco', 'regressão')
        elif dom == 'infra':
            mapped = mapped.replace('objetivo', 'serviço').replace('ação', 'mitigação').replace('risco', 'incidente')
        elif dom == 'pipeline':
            mapped = mapped.replace('objetivo', 'job').replace('ação', 'etapa').replace('risco', 'quebra')
        out.append(str(mapped)[:220])
    return out[:30]


def _map_procedure(template: list[str], target_domain: str) -> list[str]:
    dom = _normalize(target_domain)
    mapped = []
    for step in template:
        s = _normalize(step)
        out = step
        if dom == 'debugging':
            out = out.replace('posição', 'estado do sistema').replace('objetivo', 'causa raiz').replace('ação', 'mudança de correção')
            out = out.replace('risco', 'regressão')
        elif dom == 'infra':
            out = out.replace('posição', 'estado do serviço').replace('objetivo', 'serviço saudável').replace('ação', 'ação operacional')
            out = out.replace('risco', 'incidente')
        elif dom == 'pipeline':
            out = out.replace('posição', 'estado do pipeline').replace('objetivo', 'execução correta').replace('ação', 'etapa/remediação')
            out = out.replace('risco', 'quebra')
        mapped.append(str(out)[:220])
    return mapped[:30]


def map_abstraction(abstraction_id: str, target_domain: str, target_text: str | None = None) -> dict[str, Any] | None:
    item = explicit_abstractions.get_abstraction(abstraction_id)
    if not item:
        return None
    sig = _domain_signature(target_domain, target_text)
    similarity = _structural_similarity(item, target_domain, target_text)
    conditions = _map_conditions(item.get('applicability_conditions') or [], target_domain)
    procedure = _map_procedure(item.get('procedure_template') or [], target_domain)
    mapping = {
        'ts': _now(),
        'abstraction_id': abstraction_id,
        'source_domains': item.get('source_domains') or [],
        'target_domain': sig['target_domain'],
        'structural_similarity': similarity,
        'principle': item.get('principle'),
        'mapped_applicability_conditions': conditions,
        'mapped_procedure_template': procedure,
        'role_alignment': sig['role_map'],
        'justification': {
            'matched_tokens': sig['matched_tokens'],
            'hint_strength': sig['hint_strength'],
            'confidence_used': item.get('confidence'),
            'generality_used': item.get('generality_score'),
        },
        'recommended': bool(similarity >= 0.45 and procedure),
    }
    _ensure_parent(DATA_PATH)
    with DATA_PATH.open('a', encoding='utf-8') as f:
        f.write(json.dumps(mapping, ensure_ascii=False) + '\n')
    return mapping


def apply_mapped_abstraction(abstraction_id: str, target_domain: str, target_text: str | None = None) -> dict[str, Any] | None:
    mapped = map_abstraction(abstraction_id, target_domain, target_text)
    if not mapped:
        return None
    plan = {
        'goal': f"aplicar abstração {abstraction_id} em {mapped.get('target_domain')}",
        'steps': mapped.get('mapped_procedure_template') or [],
        'guardrails': mapped.get('mapped_applicability_conditions') or [],
    }
    return {
        'ok': True,
        'mapping': mapped,
        'application_plan': plan,
    }


def recent_mappings(limit: int = 20) -> dict[str, Any]:
    rows = []
    if DATA_PATH.exists():
        for line in DATA_PATH.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    rows.append(obj)
            except Exception:
                continue
    rows = rows[-max(1, min(200, int(limit or 20))):]
    return {'ok': True, 'items': rows, 'count': len(rows), 'path': str(DATA_PATH)}
