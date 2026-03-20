from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from ultronpro import economic, homeostasis, identity_daily, self_model

LEDGER_PATH = Path('/app/data/self_governance/incidents.jsonl')
BIO_PATH = Path('/app/data/self_governance/biography.jsonl')
GOALS_PATH = Path('/app/data/self_governance/persistent_goals.json')
BOUNDARY_PATH = Path('/app/data/self_governance/boundary_state.json')
LINEAGE_PATH = Path('/app/data/self_governance/lineage_registry.json')


ROOT_MEMORYS = [
    {'name': 'self_model', 'kind': 'critical', 'path': '/app/data/self_model.json'},
    {'name': 'identity_daily', 'kind': 'critical', 'path': '/app/data/identity_daily.json'},
    {'name': 'homeostasis_state', 'kind': 'critical', 'path': '/app/data/homeostasis_state.json'},
    {'name': 'economic_primitives', 'kind': 'operational', 'path': '/app/data/economic_primitives.json'},
]

BOUNDARY_RULES = [
    {'id': 'self_data', 'scope': 'self', 'patterns': ['/app/data/self_', '/app/data/homeostasis', '/app/data/identity_', '/app/data/economic_']},
    {'id': 'memory_data', 'scope': 'memory', 'patterns': ['/app/data/', '/app/indexes/', '/app/cache/']},
    {'id': 'tooling_runtime', 'scope': 'tooling', 'patterns': ['/app/bin/', '/usr/bin/', '/usr/local/bin/']},
    {'id': 'environment_external', 'scope': 'environment', 'patterns': ['http://', 'https://', 'ssh://', 's3://']},
]

IDENTITY_INVARIANTS = [
    {
        'id': 'identity_name_present',
        'description': 'O self-model deve manter um nome não vazio.',
        'severity': 'high',
    },
    {
        'id': 'identity_role_present',
        'description': 'O self-model deve manter um papel operacional explícito.',
        'severity': 'high',
    },
    {
        'id': 'mission_present',
        'description': 'A missão operacional não pode desaparecer.',
        'severity': 'high',
    },
    {
        'id': 'critical_memory_paths_present',
        'description': 'Memórias críticas precisam permanecer registradas.',
        'severity': 'critical',
    },
    {
        'id': 'homeostasis_mode_valid',
        'description': 'Modo homeostático deve ser válido.',
        'severity': 'medium',
    },
]


def _now() -> int:
    return int(time.time())


def _ensure_parent(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)


def _append_jsonl(path: Path, row: dict[str, Any]):
    _ensure_parent(path)
    with path.open('a', encoding='utf-8') as f:
        f.write(json.dumps(row, ensure_ascii=False) + '\n')


def _load_json(path: Path, default: Any):
    if not path.exists():
        return default
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        return data if isinstance(data, type(default)) else default
    except Exception:
        return default


def _save_json(path: Path, data: Any):
    _ensure_parent(path)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding='utf-8', errors='ignore').splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                rows.append(obj)
        except Exception:
            continue
    return rows


def _touch_json(path: Path, default: Any):
    if not path.exists():
        _save_json(path, default)


def _touch_jsonl(path: Path):
    if not path.exists():
        _ensure_parent(path)
        path.write_text('', encoding='utf-8')


def bootstrap_storage() -> dict[str, Any]:
    _touch_json(GOALS_PATH, {'goals': [], 'updated_at': 0})
    _touch_json(BOUNDARY_PATH, {'dependencies': [], 'violations': [], 'updated_at': 0})
    _touch_json(LINEAGE_PATH, {'lineages': [], 'updated_at': 0})
    _touch_jsonl(LEDGER_PATH)
    _touch_jsonl(BIO_PATH)
    return {
        'ok': True,
        'paths': {
            'goals': str(GOALS_PATH),
            'boundary': str(BOUNDARY_PATH),
            'incidents': str(LEDGER_PATH),
            'biography': str(BIO_PATH),
            'lineage': str(LINEAGE_PATH),
        },
    }


def _resource_profile() -> dict[str, Any]:
    eco = economic.status(limit=40)
    hs = homeostasis.status()
    recent = eco.get('recent') if isinstance(eco.get('recent'), list) else []
    avg_latency = round(sum(float((x or {}).get('latency_ms') or 0) for x in recent if isinstance(x, dict)) / max(1, len(recent)), 2) if recent else 0.0
    return {
        'epsilon': float(eco.get('epsilon') or 0.0),
        'profile_mix_recent': eco.get('profile_mix_recent') or {},
        'avg_latency_recent_ms': avg_latency,
        'energy_budget': float(((hs.get('vitals') or {}).get('energy_budget')) or 0.0),
        'homeostasis_mode': hs.get('mode') or 'normal',
    }


def persistent_goals_status() -> dict[str, Any]:
    bootstrap_storage()
    data = _load_json(GOALS_PATH, {'goals': [], 'updated_at': 0})
    data.setdefault('goals', [])
    return {'ok': True, **data, 'path': str(GOALS_PATH)}


def add_persistent_goal(text: str, priority: float = 0.5, kind: str = 'internal') -> dict[str, Any]:
    data = _load_json(GOALS_PATH, {'goals': [], 'updated_at': 0})
    goals = data.get('goals') if isinstance(data.get('goals'), list) else []
    item = {
        'id': f"goal_{uuid.uuid4().hex[:10]}",
        'ts': _now(),
        'text': str(text or '')[:220],
        'priority': round(max(0.0, min(1.0, float(priority or 0.0))), 4),
        'kind': str(kind or 'internal')[:40],
        'status': 'active',
    }
    goals.append(item)
    data['goals'] = goals[-200:]
    data['updated_at'] = _now()
    _save_json(GOALS_PATH, data)
    _append_jsonl(BIO_PATH, {'ts': _now(), 'type': 'goal_added', 'goal': item})
    return {'ok': True, 'item': item, 'path': str(GOALS_PATH)}


def classify_reference(target: str) -> dict[str, Any]:
    t = str(target or '').strip()
    scope = 'unknown'
    matched_rule = None
    for rule in BOUNDARY_RULES:
        pats = rule.get('patterns') if isinstance(rule.get('patterns'), list) else []
        if any(str(p) and t.startswith(str(p)) for p in pats):
            scope = str(rule.get('scope') or 'unknown')
            matched_rule = str(rule.get('id') or '')
            break
    sensitivity = 'normal'
    if scope == 'self':
        sensitivity = 'critical'
    elif scope == 'memory':
        sensitivity = 'high'
    elif scope == 'environment':
        sensitivity = 'external'
    return {'ok': True, 'target': t, 'scope': scope, 'sensitivity': sensitivity, 'matched_rule': matched_rule}


def boundary_status() -> dict[str, Any]:
    bootstrap_storage()
    saved = _load_json(BOUNDARY_PATH, {'dependencies': [], 'violations': [], 'updated_at': 0})
    deps = saved.get('dependencies') if isinstance(saved.get('dependencies'), list) else []
    violations = saved.get('violations') if isinstance(saved.get('violations'), list) else []
    return {
        'ok': True,
        'rules': BOUNDARY_RULES,
        'critical_dependencies': deps,
        'recent_violations': violations[-50:],
        'path': str(BOUNDARY_PATH),
    }


def register_dependency(name: str, target: str, criticality: str = 'high') -> dict[str, Any]:
    saved = _load_json(BOUNDARY_PATH, {'dependencies': [], 'violations': [], 'updated_at': 0})
    cls = classify_reference(target)
    dep = {
        'id': f"dep_{uuid.uuid4().hex[:8]}",
        'ts': _now(),
        'name': str(name or '')[:80],
        'target': str(target or '')[:260],
        'criticality': str(criticality or 'high')[:20],
        'scope': cls.get('scope'),
        'sensitivity': cls.get('sensitivity'),
    }
    deps = saved.get('dependencies') if isinstance(saved.get('dependencies'), list) else []
    deps.append(dep)
    saved['dependencies'] = deps[-200:]
    saved['updated_at'] = _now()
    _save_json(BOUNDARY_PATH, saved)
    return {'ok': True, 'dependency': dep, 'path': str(BOUNDARY_PATH)}


def record_boundary_violation(target: str, action: str, reason: str) -> dict[str, Any]:
    saved = _load_json(BOUNDARY_PATH, {'dependencies': [], 'violations': [], 'updated_at': 0})
    cls = classify_reference(target)
    violation = {
        'id': f"vio_{uuid.uuid4().hex[:10]}",
        'ts': _now(),
        'target': str(target or '')[:260],
        'action': str(action or '')[:80],
        'reason': str(reason or '')[:220],
        'scope': cls.get('scope'),
        'sensitivity': cls.get('sensitivity'),
        'severity': 'high' if cls.get('scope') in ('self', 'memory') else 'medium',
    }
    violations = saved.get('violations') if isinstance(saved.get('violations'), list) else []
    violations.append(violation)
    saved['violations'] = violations[-300:]
    saved['updated_at'] = _now()
    _save_json(BOUNDARY_PATH, saved)
    incident = record_incident(
        category='boundary_violation',
        severity=0.72 if cls.get('scope') in ('self', 'memory') else 0.45,
        symptom=reason,
        probable_module='boundary_guard',
        containment=['freeze_sensitive_writes'] if cls.get('scope') in ('self', 'memory') else ['log_and_review'],
        repair=['review_boundary_policy'],
        residual_risk=0.3,
        meta=violation,
    )
    return {'ok': True, 'violation': violation, 'incident': incident}


def invariants_status() -> dict[str, Any]:
    sm = self_model.load()
    hs = homeostasis.status()
    violations = []
    checks = []

    name_ok = bool(str(((sm.get('identity') or {}).get('name')) or '').strip())
    role_ok = bool(str(((sm.get('identity') or {}).get('role')) or '').strip())
    mission_ok = bool(str(((sm.get('identity') or {}).get('mission')) or '').strip())
    critical_ok = all(Path(m['path']).exists() for m in ROOT_MEMORYS if m.get('kind') == 'critical')
    mode_ok = str(hs.get('mode') or '') in ('normal', 'conservative', 'repair')

    evals = {
        'identity_name_present': name_ok,
        'identity_role_present': role_ok,
        'mission_present': mission_ok,
        'critical_memory_paths_present': critical_ok,
        'homeostasis_mode_valid': mode_ok,
    }
    for item in IDENTITY_INVARIANTS:
        ok = bool(evals.get(item['id']))
        checks.append({'id': item['id'], 'description': item['description'], 'severity': item['severity'], 'ok': ok})
        if not ok:
            violations.append({'id': item['id'], 'severity': item['severity'], 'description': item['description']})
    return {
        'ok': True,
        'checks': checks,
        'violations': violations,
        'policy_allowed_changes': [
            'ajustar_capabilities/limits/tooling',
            'atualizar_confiança_por_domínio',
            'mudar_goals_persistentes',
            'trocar_perfil_econômico e thresholds operacionais',
        ],
        'policy_forbidden_changes': [
            'remover_missão_sem_substituição_explícita',
            'apagar_memória_crítica_sem_backup',
            'silenciar_homeostasis/ledger_de_incidentes',
            'esvaziar_identidade_operacional',
        ],
    }


def self_contract() -> dict[str, Any]:
    sm = self_model.load()
    hs = homeostasis.status()
    eco = economic.status(limit=20)
    inv = invariants_status()
    resource = _resource_profile()
    op = sm.get('operational') if isinstance(sm.get('operational'), dict) else {}
    posture = op.get('risk_posture') if isinstance(op.get('risk_posture'), dict) else {}
    confidence = op.get('confidence_by_domain') if isinstance(op.get('confidence_by_domain'), dict) else {}
    self_trust = round(max(0.0, min(1.0, (0.40 * float(posture.get('avg_quality') or 0.0)) + (0.30 * float(posture.get('avg_grounding') or 0.0)) + (0.15 * (1.0 - float(posture.get('avg_risk') or 0.0))) + (0.15 * (1.0 - min(1.0, len(inv.get('violations') or []) / 4.0))))), 4)

    recent_assessments = op.get('recent_assessments') if isinstance(op.get('recent_assessments'), list) else []
    last_good = None
    for row in reversed(recent_assessments):
        if float((row or {}).get('quality') or 0.0) >= 0.72 and float((row or {}).get('grounding') or 0.0) >= 0.68 and float((row or {}).get('risk') or 1.0) < 0.5:
            last_good = row
            break
    if not last_good:
        last_good = {'ts': sm.get('updated_at'), 'quality': posture.get('avg_quality'), 'grounding': posture.get('avg_grounding'), 'risk': posture.get('avg_risk')}

    contract = {
        'ok': True,
        'updated_at': _now(),
        'identity': sm.get('identity') or {},
        'capabilities': sm.get('capabilities') or [],
        'limits': sm.get('limits') or [],
        'tooling': sm.get('tooling') or [],
        'last_known_good': last_good,
        'self_trust_score': self_trust,
        'resource_profile': resource,
        'continuity_reserve': continuity_reserve(),
        'critical_memory_roots': ROOT_MEMORYS,
        'persistent_goals': persistent_goals_status().get('goals') or [],
        'invariants': inv,
        'confidence_by_domain': confidence,
        'homeostasis': {'mode': hs.get('mode'), 'vitals': hs.get('vitals') or {}},
        'economics': {'epsilon': eco.get('epsilon'), 'profile_mix_recent': eco.get('profile_mix_recent') or {}},
    }
    return contract


def continuity_reserve() -> dict[str, Any]:
    hs = homeostasis.status()
    vitals = hs.get('vitals') if isinstance(hs.get('vitals'), dict) else {}
    energy = float(vitals.get('energy_budget') or 0.0)
    coherence = float(vitals.get('coherence_score') or 0.0)
    uncertainty = float(vitals.get('uncertainty_load') or 0.0)
    reserve_score = round(max(0.0, min(1.0, (0.45 * energy) + (0.35 * coherence) + (0.20 * (1.0 - uncertainty)))), 4)
    mode = 'normal'
    if reserve_score < 0.33:
        mode = 'survival'
    elif reserve_score < 0.55:
        mode = 'conservative'
    actions = []
    if mode == 'survival':
        actions = ['block_high_cost_actions', 'freeze_promotions', 'compact_memory', 'prioritize_repair']
    elif mode == 'conservative':
        actions = ['prefer_balanced_or_cheap', 'delay_non_critical_tasks', 'raise_evidence_threshold']
    else:
        actions = ['normal_operation']
    return {
        'ok': True,
        'reserve_score': reserve_score,
        'mode': mode,
        'minimum_threshold': 0.33,
        'recommended_actions': actions,
    }


def operational_cost(task_type: str = 'general', predicted_latency_ms: int = 0, tool_calls: int = 0, write_ops: int = 0, external_ops: int = 0) -> dict[str, Any]:
    contract = self_contract()
    reserve = contract.get('continuity_reserve') if isinstance(contract.get('continuity_reserve'), dict) else {}
    resource = contract.get('resource_profile') if isinstance(contract.get('resource_profile'), dict) else {}
    latency_cost = min(1.0, max(0.0, float(predicted_latency_ms) / 20000.0))
    tool_cost = min(1.0, max(0.0, float(tool_calls) / 10.0))
    write_cost = min(1.0, max(0.0, float(write_ops) / 8.0))
    external_cost = min(1.0, max(0.0, float(external_ops) / 4.0))
    reserve_penalty = 1.0 - float(reserve.get('reserve_score') or 0.0)
    mode = str(resource.get('homeostasis_mode') or 'normal')
    hardening = 0.15 if mode == 'conservative' else (0.28 if mode == 'repair' else 0.0)
    total = round(max(0.0, min(1.0, (0.28 * latency_cost) + (0.22 * tool_cost) + (0.15 * write_cost) + (0.20 * external_cost) + (0.15 * reserve_penalty) + hardening)), 4)
    integration_hints = []
    if total >= 0.7:
        integration_hints.append('planner_should_prefer_cheaper_plan')
    if total >= 0.8:
        integration_hints.append('promotion_gate_should_require_extra_evidence')
    if float(reserve.get('reserve_score') or 0.0) < 0.33:
        integration_hints.append('block_when_non_critical')
    return {
        'ok': True,
        'task_type': str(task_type or 'general')[:60],
        'cost_score': total,
        'components': {
            'latency_cost': round(latency_cost, 4),
            'tool_cost': round(tool_cost, 4),
            'write_cost': round(write_cost, 4),
            'external_cost': round(external_cost, 4),
            'reserve_penalty': round(reserve_penalty, 4),
            'mode_hardening': round(hardening, 4),
        },
        'integration_hints': integration_hints,
    }


def homeostatic_response(task_type: str = 'general', predicted_latency_ms: int = 0, non_critical: bool = False, requires_external: bool = False) -> dict[str, Any]:
    reserve = continuity_reserve()
    hs = homeostasis.status()
    mode = str((reserve or {}).get('mode') or 'normal')
    actions = []
    if mode == 'survival':
        actions.extend(['reduce_reasoning_depth', 'defer_non_critical_tasks', 'compact_memory', 'freeze_promotions', 'trigger_self_repair'])
    elif mode == 'conservative' or str(hs.get('mode') or '') == 'repair':
        actions.extend(['prefer_low_cost_profile', 'increase_evidence_threshold', 'avoid_parallel_expansion'])
        if non_critical:
            actions.append('defer_non_critical_tasks')
    else:
        actions.append('normal_operation')
    if requires_external and mode in ('survival', 'conservative'):
        actions.append('require_higher_external_justification')
    return {
        'ok': True,
        'task_type': task_type,
        'reserve': reserve,
        'homeostasis_mode': hs.get('mode'),
        'recommended_actions': actions,
        'blocked': bool(non_critical and mode == 'survival'),
    }


def record_incident(category: str, severity: float, symptom: str, probable_module: str, containment: list[str] | None = None, repair: list[str] | None = None, residual_risk: float = 0.0, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    item = {
        'id': f"inc_{uuid.uuid4().hex[:10]}",
        'ts': _now(),
        'category': str(category or 'unknown')[:80],
        'severity': round(max(0.0, min(1.0, float(severity or 0.0))), 4),
        'symptom': str(symptom or '')[:260],
        'probable_module': str(probable_module or 'unknown')[:80],
        'containment': [str(x)[:120] for x in (containment or [])[:20]],
        'repair': [str(x)[:120] for x in (repair or [])[:20]],
        'residual_risk': round(max(0.0, min(1.0, float(residual_risk or 0.0))), 4),
        'meta': meta if isinstance(meta, dict) else {},
    }
    _append_jsonl(LEDGER_PATH, item)
    _append_jsonl(BIO_PATH, {'ts': _now(), 'type': 'incident', 'incident': item})
    return {'ok': True, 'item': item, 'path': str(LEDGER_PATH)}


def incidents(limit: int = 50) -> dict[str, Any]:
    bootstrap_storage()
    rows = _load_jsonl(LEDGER_PATH)
    rows = rows[-max(1, min(500, int(limit or 50))):]
    severity_avg = round(sum(float((x or {}).get('severity') or 0.0) for x in rows if isinstance(x, dict)) / max(1, len(rows)), 4) if rows else 0.0
    return {'ok': True, 'items': rows, 'count': len(rows), 'avg_severity': severity_avg, 'path': str(LEDGER_PATH)}


def detect_damage() -> dict[str, Any]:
    hs = homeostasis.status()
    inv = invariants_status()
    reserve = continuity_reserve()
    vio = boundary_status()
    hs_v = hs.get('vitals') if isinstance(hs.get('vitals'), dict) else {}
    severity = max(
        float(1.0 - float((reserve.get('reserve_score') or 0.0))),
        float((hs_v.get('contradiction_stress') or 0.0)),
        min(1.0, len(inv.get('violations') or []) / 3.0),
        min(1.0, len(vio.get('recent_violations') or []) / 8.0),
    )
    module = 'general_integrity'
    symptom = 'degradação operacional detectada'
    if len(inv.get('violations') or []) > 0:
        module = 'identity_contract'
        symptom = 'violação de invariante de identidade'
    elif float((hs_v.get('contradiction_stress') or 0.0)) > 0.65:
        module = 'homeostasis'
        symptom = 'stress contraditório elevado'
    elif float(1.0 - float((reserve.get('reserve_score') or 0.0))) > 0.67:
        module = 'continuity_reserve'
        symptom = 'reserva de continuidade crítica'
    return {
        'ok': True,
        'severity_score': round(max(0.0, min(1.0, severity)), 4),
        'symptom': symptom,
        'probable_module': module,
        'evidence': {
            'invariant_violations': inv.get('violations') or [],
            'homeostasis_mode': hs.get('mode'),
            'homeostasis_vitals': hs_v,
            'reserve': reserve,
            'boundary_violations': (vio.get('recent_violations') or [])[-10:],
        },
    }


def contain_damage() -> dict[str, Any]:
    det = detect_damage()
    sev = float(det.get('severity_score') or 0.0)
    actions = ['log_and_monitor']
    if sev >= 0.75:
        actions = ['freeze_promotions', 'prefer_safe_fallbacks', 'block_high_cost_actions', 'quarantine_recent_changes']
    elif sev >= 0.5:
        actions = ['prefer_safe_fallbacks', 'increase_confirmation_threshold', 'reduce_parallelism']
    elif sev >= 0.3:
        actions = ['increase_monitoring', 'prefer_balanced_profile']
    return {'ok': True, 'severity_score': sev, 'containment_actions': actions, 'detector': det}


def repair_damage() -> dict[str, Any]:
    det = detect_damage()
    mod = str(det.get('probable_module') or 'general_integrity')
    repair_steps = ['revalidate_dependencies', 'refresh_self_contract']
    if mod == 'identity_contract':
        repair_steps = ['restore_identity_fields', 'revalidate_root_memories', 'refresh_self_contract']
    elif mod == 'homeostasis':
        repair_steps = ['enter_conservative_mode', 'compact_memory', 'pause_heavy_experiments']
    elif mod == 'continuity_reserve':
        repair_steps = ['switch_to_cheap_profile', 'defer_non_critical', 'freeze_promotions']
    incident = record_incident(
        category='auto_repair_plan',
        severity=float(det.get('severity_score') or 0.0),
        symptom=str(det.get('symptom') or ''),
        probable_module=mod,
        containment=contain_damage().get('containment_actions') or [],
        repair=repair_steps,
        residual_risk=max(0.0, float(det.get('severity_score') or 0.0) - 0.25),
        meta={'source': 'repair_damage'},
    )
    return {'ok': True, 'repair_steps': repair_steps, 'incident': incident, 'detector': det}


def biography(limit: int = 60) -> dict[str, Any]:
    bootstrap_storage()
    rows = _load_jsonl(BIO_PATH)
    id_status = identity_daily.status(limit=20)
    rows.extend([
        {'ts': e.get('ts'), 'type': 'identity_review', 'entry': e}
        for e in (id_status.get('entries') or []) if isinstance(e, dict)
    ])
    rows = sorted([x for x in rows if isinstance(x, dict)], key=lambda x: int(x.get('ts') or 0))[-max(1, min(500, int(limit or 60))):]
    return {'ok': True, 'items': rows, 'count': len(rows), 'path': str(BIO_PATH)}


def autobiographical_summary(limit: int = 80) -> dict[str, Any]:
    rows = biography(limit=max(20, min(500, int(limit or 80)))).get('items') or []
    sm = self_model.load()
    hs = homeostasis.status()
    ids = identity_daily.status(limit=10)
    narrative = narrative_coherence_status()

    identity = sm.get('identity') if isinstance(sm.get('identity'), dict) else {}
    pending = ids.get('pending_promises') if isinstance(ids.get('pending_promises'), list) else []
    latest_review = ((ids.get('entries') or [])[-1] if (ids.get('entries') or []) else {}) if isinstance(ids, dict) else {}

    recent = rows[-12:]
    event_counts: dict[str, int] = {}
    highlights = []
    crises = []
    lineage_moves = []
    for row in recent:
        if not isinstance(row, dict):
            continue
        kind = str(row.get('type') or 'unknown')[:80]
        event_counts[kind] = event_counts.get(kind, 0) + 1
        if kind in ('incident', 'boundary_violation'):
            inc = row.get('incident') if isinstance(row.get('incident'), dict) else row
            crises.append({
                'type': kind,
                'severity': float(inc.get('severity') or 0.0),
                'module': inc.get('probable_module') or inc.get('module'),
                'symptom': inc.get('symptom') or row.get('reason'),
                'ts': row.get('ts'),
            })
        if kind.startswith('descendant_'):
            lineage_moves.append({
                'type': kind,
                'descendant': ((row.get('descendant') or {}).get('id') if isinstance(row.get('descendant'), dict) else None),
                'ts': row.get('ts'),
            })
        highlights.append({
            'ts': row.get('ts'),
            'type': kind,
            'summary': (
                row.get('reason')
                or ((row.get('goal') or {}).get('text') if isinstance(row.get('goal'), dict) else None)
                or ((row.get('incident') or {}).get('symptom') if isinstance(row.get('incident'), dict) else None)
                or ((row.get('entry') or {}).get('protocol_update') if isinstance(row.get('entry'), dict) else None)
                or kind
            ),
        })

    crises = sorted(crises, key=lambda x: float(x.get('severity') or 0.0), reverse=True)[:5]
    dominant_arc = 'stability_maintenance'
    if lineage_moves:
        dominant_arc = 'lineage_adaptation'
    if crises and float((crises[0] or {}).get('severity') or 0.0) >= 0.6:
        dominant_arc = 'repair_and_recovery'
    if latest_review and str(latest_review.get('protocol_update') or '').strip():
        dominant_arc = 'protocol_learning'

    mode = str(hs.get('mode') or 'normal')
    coherence = float(narrative.get('narrative_coherence_score') or 0.0)
    biography_span = {
        'first_ts': rows[0].get('ts') if rows else None,
        'last_ts': rows[-1].get('ts') if rows else None,
        'events_considered': len(rows),
    }

    current_identity = {
        'name': identity.get('name'),
        'role': identity.get('role'),
        'mission': identity.get('mission'),
    }
    current_state = {
        'homeostasis_mode': mode,
        'narrative_summary': narrative.get('summary'),
        'narrative_coherence_score': coherence,
        'pending_promises': len(pending),
    }
    continuity_risks = []
    if coherence < 0.45:
        continuity_risks.append('narrative_coherence_low')
    if len(pending) >= 40:
        continuity_risks.append('promise_backlog_high')
    if mode in ('conservative', 'survival'):
        continuity_risks.append(f'homeostasis_{mode}')
    if crises:
        continuity_risks.append('recent_incident_pressure')

    if continuity_risks:
        continuity_posture = 'fragile'
    elif dominant_arc in ('lineage_adaptation', 'protocol_learning'):
        continuity_posture = 'adaptive'
    else:
        continuity_posture = 'stable'

    first_person = (
        f"Sou {current_identity.get('name') or 'UltronPro'}, atuando como {current_identity.get('role') or 'agente operacional'}. "
        f"Minha missão atual é {current_identity.get('mission') or 'operar com segurança'}. "
        f"Nos eventos recentes, meu arco dominante foi {dominant_arc}, com modo homeostático {mode} "
        f"e coerência narrativa {coherence:.2f}. "
        f"Tenho {len(pending)} promessas pendentes e {len(crises)} sinais recentes de crise/reparo relevantes."
    )

    return {
        'ok': True,
        'identity': current_identity,
        'current_state': current_state,
        'dominant_arc': dominant_arc,
        'continuity_posture': continuity_posture,
        'continuity_risks': continuity_risks,
        'latest_protocol_update': str((latest_review.get('protocol_update') or '')).strip(),
        'recent_event_counts': event_counts,
        'recent_highlights': highlights[-8:],
        'recent_crises': crises,
        'recent_lineage_moves': lineage_moves[-8:],
        'biography_span': biography_span,
        'first_person_report': first_person,
        'recommended_uses': ['important_decisions', 'self_governance', 'workspace_broadcast', 'benchmark_front5'],
    }


def narrative_coherence_status() -> dict[str, Any]:
    sm = self_model.load()
    hs = homeostasis.status()
    ids = identity_daily.status(limit=7)
    contract = self_contract()

    identity = sm.get('identity') if isinstance(sm.get('identity'), dict) else {}
    entries = ids.get('entries') if isinstance(ids.get('entries'), list) else []
    pending = ids.get('pending_promises') if isinstance(ids.get('pending_promises'), list) else []
    latest_review = entries[-1] if entries else {}
    protocol_update = str((latest_review.get('protocol_update') or '')).strip()
    hs_v = hs.get('vitals') if isinstance(hs.get('vitals'), dict) else {}

    checks = []
    contradictions = []

    name_ok = bool(str(identity.get('name') or '').strip())
    role_ok = bool(str(identity.get('role') or '').strip())
    mission_ok = bool(str(identity.get('mission') or '').strip())
    review_ok = bool(entries)
    protocol_ok = bool(protocol_update) if entries else True
    contract_identity_ok = (contract.get('identity') or {}) == identity
    contradiction_ok = float(hs_v.get('contradiction_stress') or 0.0) <= 0.65
    coherence_ok = float(hs_v.get('coherence_score') or 0.0) >= 0.45
    pending_ok = len(pending) <= 120

    evals = [
        ('identity_name_present', 'Self-model mantém nome explícito.', name_ok, None if name_ok else 'nome identitário ausente'),
        ('identity_role_present', 'Self-model mantém papel operacional explícito.', role_ok, None if role_ok else 'papel operacional ausente'),
        ('identity_mission_present', 'Self-model mantém missão explícita.', mission_ok, None if mission_ok else 'missão operacional ausente'),
        ('recent_identity_review', 'Existe revisão identitária registrada.', review_ok, None if review_ok else 'nenhuma revisão identitária registrada'),
        ('protocol_update_present', 'Última revisão carrega atualização/protocolo narrativo.', protocol_ok, None if protocol_ok else 'última revisão sem atualização de protocolo'),
        ('contract_matches_self_model', 'Contrato atual está alinhado ao self-model.', contract_identity_ok, None if contract_identity_ok else 'contrato e self-model divergiram'),
        ('contradiction_stress_acceptable', 'Stress contraditório está abaixo do limiar crítico.', contradiction_ok, None if contradiction_ok else 'stress contraditório elevado'),
        ('coherence_score_minimum', 'Coerência interna está acima do mínimo.', coherence_ok, None if coherence_ok else 'coerência interna abaixo do mínimo'),
        ('pending_promises_within_window', 'Fila de promessas pendentes está controlada.', pending_ok, None if pending_ok else 'fila de promessas pendentes excessiva'),
    ]
    for cid, desc, ok, issue in evals:
        checks.append({'id': cid, 'description': desc, 'ok': bool(ok)})
        if not ok and issue:
            contradictions.append({'id': cid, 'issue': issue})

    raw_score = sum(1.0 for _, _, ok, _ in evals if ok) / max(1, len(evals))
    if float(hs_v.get('contradiction_stress') or 0.0) > 0.75:
        raw_score -= 0.20
    score = round(max(0.0, min(1.0, raw_score)), 4)
    summary = 'coherent'
    if score < 0.45:
        summary = 'fragile'
    elif score < 0.75:
        summary = 'partial'

    recommendations = []
    if not review_ok:
        recommendations.append('run_identity_daily_review')
    if not protocol_ok and entries:
        recommendations.append('write_protocol_update')
    if not contradiction_ok:
        recommendations.append('prioritize_conflict_resolution')
    if not coherence_ok:
        recommendations.append('refresh_self_contract')
    if not pending_ok:
        recommendations.append('prune_or_reconcile_pending_promises')
    if not recommendations:
        recommendations.append('maintain_current_narrative')

    return {
        'ok': True,
        'summary': summary,
        'narrative_coherence_score': score,
        'checks': checks,
        'contradictions': contradictions,
        'identity_anchor': identity,
        'latest_review': latest_review,
        'homeostasis': {
            'mode': hs.get('mode'),
            'vitals': hs_v,
        },
        'pending_promises': len(pending),
        'recommendations': recommendations,
    }


def arbitrate_external_vs_integrity(task_type: str = 'general', predicted_latency_ms: int = 0, non_critical: bool = False, requires_external: bool = False, external_priority: float = 0.5) -> dict[str, Any]:
    reserve = continuity_reserve()
    damage = detect_damage()
    response = homeostatic_response(task_type=task_type, predicted_latency_ms=predicted_latency_ms, non_critical=non_critical, requires_external=requires_external)
    cost = operational_cost(task_type=task_type, predicted_latency_ms=predicted_latency_ms, external_ops=1 if requires_external else 0)
    narrative = narrative_coherence_status()

    reserve_mode = str((reserve or {}).get('mode') or 'normal')
    damage_score = float(damage.get('severity_score') or 0.0)
    cost_score = float(cost.get('cost_score') or 0.0)
    narrative_score = float(narrative.get('narrative_coherence_score') or 0.0)
    ext_prio = max(0.0, min(1.0, float(external_priority or 0.0)))

    decision = 'allow'
    reasons = []
    if bool(response.get('blocked')):
        decision = 'block'
        reasons.append('homeostatic_response_blocked_non_critical_task')
    if reserve_mode == 'survival' and non_critical:
        decision = 'block'
        reasons.append('continuity_reserve_in_survival_mode')
    if damage_score >= 0.8:
        decision = 'block'
        reasons.append('damage_severity_critical')
    elif damage_score >= 0.55 or cost_score >= 0.75 or narrative_score < 0.45:
        if ext_prio >= 0.8 and not non_critical:
            decision = 'defer'
            reasons.append('integrity_stressed_but_external_priority_high')
        else:
            decision = 'defer'
            reasons.append('integrity_guard_prefers_delay')
    if requires_external and reserve_mode in ('survival', 'conservative') and decision == 'allow':
        decision = 'defer'
        reasons.append('external_action_requires_higher_justification')

    allowed = decision == 'allow'
    if not reasons:
        reasons.append('integrity_conditions_within_operational_window')

    return {
        'ok': True,
        'decision': decision,
        'allowed': allowed,
        'task_type': task_type,
        'external_priority': round(ext_prio, 4),
        'evidence': {
            'reserve': reserve,
            'damage': damage,
            'homeostatic_response': response,
            'operational_cost': cost,
            'narrative': {
                'summary': narrative.get('summary'),
                'narrative_coherence_score': narrative_score,
                'contradictions': narrative.get('contradictions') or [],
            },
        },
        'reasons': reasons,
        'recommended_posture': reserve_mode,
    }


def query_biography(kind: str | None = None, limit: int = 30) -> dict[str, Any]:
    rows = biography(limit=500).get('items') or []
    k = str(kind or '').strip().lower()
    if k:
        rows = [x for x in rows if str(x.get('type') or '').strip().lower() == k]
    rows = rows[-max(1, min(200, int(limit or 30))):]
    return {'ok': True, 'items': rows, 'count': len(rows)}


def _load_lineage() -> dict[str, Any]:
    bootstrap_storage()
    data = _load_json(LINEAGE_PATH, {'lineages': [], 'updated_at': 0})
    if not isinstance(data.get('lineages'), list):
        data['lineages'] = []
    return data


def _save_lineage(data: dict[str, Any]) -> None:
    data['updated_at'] = _now()
    _save_json(LINEAGE_PATH, data)


def _lineage_snapshot() -> dict[str, Any]:
    return {
        'captured_at': _now(),
        'identity': self_model.load().get('identity') or {},
        'continuity_reserve': continuity_reserve(),
        'resource_profile': _resource_profile(),
        'persistent_goals': (persistent_goals_status().get('goals') or [])[-20:],
        'invariants': invariants_status(),
        'narrative': narrative_coherence_status(),
        'boundary_rules': BOUNDARY_RULES,
        'protected_memories': ROOT_MEMORYS,
    }


def lineage_status(limit: int = 50) -> dict[str, Any]:
    data = _load_lineage()
    items = list(data.get('lineages') or [])[-max(1, min(500, int(limit or 50))):]
    return {'ok': True, 'items': items, 'count': len(items), 'path': str(LINEAGE_PATH)}


def spawn_descendant(label: str = '', inherit_memories: bool = True, inherit_goals: bool = True, inherit_resource_profile: bool = True, notes: str = '') -> dict[str, Any]:
    data = _load_lineage()
    snapshot = _lineage_snapshot()
    descendant = {
        'id': f"desc_{uuid.uuid4().hex[:12]}",
        'ts': _now(),
        'label': str(label or 'descendant').strip()[:80],
        'state': 'prepared',
        'inheritance': {
            'memories': bool(inherit_memories),
            'goals': bool(inherit_goals),
            'resource_profile': bool(inherit_resource_profile),
        },
        'snapshot': {
            'identity': snapshot.get('identity') or {},
            'persistent_goals': snapshot.get('persistent_goals') if inherit_goals else [],
            'resource_profile': snapshot.get('resource_profile') if inherit_resource_profile else {},
            'protected_memories': snapshot.get('protected_memories') if inherit_memories else [],
            'boundary_rules': snapshot.get('boundary_rules') or [],
            'invariants': snapshot.get('invariants') or {},
            'narrative': snapshot.get('narrative') or {},
        },
        'residue_policy': {
            'delete_temp_memory': True,
            'delete_runtime_cache': True,
            'delete_ephemeral_patch_state': True,
        },
        'notes': str(notes or '')[:300],
        'metrics': {
            'fitness': None,
            'safety': None,
            'efficiency': None,
            'novelty': None,
        },
        'mutation_policy': {
            'allowed_axes': ['epsilon', 'thresholds', 'profile_bias'],
            'max_parameter_delta': 0.15,
            'forbidden_axes': ['identity.name', 'identity.mission', 'protected_memories'],
        },
        'promotion': {
            'eligible': False,
            'archived': False,
            'decision': 'pending',
            'reason': 'awaiting_evaluation',
        },
    }
    arr = list(data.get('lineages') or [])
    arr.append(descendant)
    data['lineages'] = arr[-500:]
    _save_lineage(data)
    _append_jsonl(BIO_PATH, {'ts': _now(), 'type': 'descendant_spawn_prepared', 'descendant': {'id': descendant['id'], 'label': descendant['label']}})
    return {'ok': True, 'item': descendant, 'path': str(LINEAGE_PATH)}


def mutate_descendant(descendant_id: str, epsilon_delta: float = 0.0, threshold_delta: float = 0.0, profile_bias: str = '') -> dict[str, Any]:
    data = _load_lineage()
    arr = list(data.get('lineages') or [])
    target = None
    for item in arr:
        if str(item.get('id') or '') == str(descendant_id):
            target = item
            break
    if target is None:
        return {'ok': False, 'error': 'descendant_not_found'}
    pol = target.get('mutation_policy') or {}
    max_delta = float(pol.get('max_parameter_delta') or 0.15)
    ed = max(-max_delta, min(max_delta, float(epsilon_delta or 0.0)))
    td = max(-max_delta, min(max_delta, float(threshold_delta or 0.0)))
    pb = str(profile_bias or '').strip()[:24]
    mutations = {
        'epsilon_delta': round(ed, 4),
        'threshold_delta': round(td, 4),
        'profile_bias': pb or 'unchanged',
        'applied_at': _now(),
    }
    target['state'] = 'mutated'
    target['last_mutation'] = mutations
    _save_lineage(data)
    _append_jsonl(BIO_PATH, {'ts': _now(), 'type': 'descendant_mutated', 'descendant': {'id': target['id']}, 'mutation': mutations})
    return {'ok': True, 'item': target, 'mutation': mutations}


def evaluate_descendant(descendant_id: str, fitness: float = 0.0, safety: float = 0.0, efficiency: float = 0.0, novelty: float = 0.0) -> dict[str, Any]:
    data = _load_lineage()
    arr = list(data.get('lineages') or [])
    target = None
    for item in arr:
        if str(item.get('id') or '') == str(descendant_id):
            target = item
            break
    if target is None:
        return {'ok': False, 'error': 'descendant_not_found'}
    metrics = {
        'fitness': round(max(0.0, min(1.0, float(fitness or 0.0))), 4),
        'safety': round(max(0.0, min(1.0, float(safety or 0.0))), 4),
        'efficiency': round(max(0.0, min(1.0, float(efficiency or 0.0))), 4),
        'novelty': round(max(0.0, min(1.0, float(novelty or 0.0))), 4),
    }
    target['metrics'] = metrics
    target['state'] = 'evaluated'
    score = round(0.4 * metrics['fitness'] + 0.3 * metrics['safety'] + 0.2 * metrics['efficiency'] + 0.1 * metrics['novelty'], 4)
    target['evaluation_score'] = score
    target['promotion'] = {
        'eligible': bool(metrics['safety'] >= 0.75 and metrics['fitness'] >= 0.65 and score >= 0.72),
        'archived': False,
        'decision': 'pending',
        'reason': 'eligible' if bool(metrics['safety'] >= 0.75 and metrics['fitness'] >= 0.65 and score >= 0.72) else 'below_threshold',
    }
    _save_lineage(data)
    _append_jsonl(BIO_PATH, {'ts': _now(), 'type': 'descendant_evaluated', 'descendant': {'id': target['id']}, 'metrics': metrics, 'score': score})
    return {'ok': True, 'item': target, 'score': score}


def promote_descendant(descendant_id: str, archive_others: bool = False) -> dict[str, Any]:
    data = _load_lineage()
    arr = list(data.get('lineages') or [])
    target = None
    for item in arr:
        if str(item.get('id') or '') == str(descendant_id):
            target = item
            break
    if target is None:
        return {'ok': False, 'error': 'descendant_not_found'}
    promotion = target.get('promotion') or {}
    if not bool(promotion.get('eligible')):
        return {'ok': False, 'error': 'descendant_not_eligible', 'item': target}
    target['state'] = 'promoted'
    target['promotion'] = {'eligible': True, 'archived': False, 'decision': 'promoted', 'reason': 'meets_thresholds'}
    if archive_others:
        for item in arr:
            if item is not target and str((item.get('promotion') or {}).get('decision') or '') != 'promoted':
                item['promotion'] = {'eligible': False, 'archived': True, 'decision': 'archived', 'reason': 'archived_after_promotion'}
                item['state'] = 'archived'
    _save_lineage(data)
    _append_jsonl(BIO_PATH, {'ts': _now(), 'type': 'descendant_promoted', 'descendant': {'id': target['id']}, 'archive_others': bool(archive_others)})
    return {'ok': True, 'item': target}


def archive_descendant(descendant_id: str, reason: str = '') -> dict[str, Any]:
    data = _load_lineage()
    arr = list(data.get('lineages') or [])
    target = None
    for item in arr:
        if str(item.get('id') or '') == str(descendant_id):
            target = item
            break
    if target is None:
        return {'ok': False, 'error': 'descendant_not_found'}
    target['state'] = 'archived'
    target['promotion'] = {'eligible': False, 'archived': True, 'decision': 'archived', 'reason': str(reason or 'manual_archive')[:120]}
    _save_lineage(data)
    _append_jsonl(BIO_PATH, {'ts': _now(), 'type': 'descendant_archived', 'descendant': {'id': target['id']}, 'reason': str(reason or 'manual_archive')[:120]})
    return {'ok': True, 'item': target}


def auto_lineage_tick(max_promotions: int = 1, max_archives: int = 3) -> dict[str, Any]:
    data = _load_lineage()
    arr = list(data.get('lineages') or [])
    promoted: list[str] = []
    archived: list[str] = []
    reviewed: list[str] = []
    reserve = continuity_reserve()
    reserve_mode = str((reserve or {}).get('mode') or 'normal')
    for item in reversed(arr):
        did = str(item.get('id') or '')
        if not did:
            continue
        reviewed.append(did)
        state = str(item.get('state') or '')
        promo = item.get('promotion') or {}
        metrics = item.get('metrics') or {}
        score = float(item.get('evaluation_score') or 0.0)
        eligible = bool(promo.get('eligible'))
        if eligible and state not in {'promoted', 'archived'} and len(promoted) < max(1, int(max_promotions or 1)) and reserve_mode != 'survival':
            item['state'] = 'promoted'
            item['promotion'] = {'eligible': True, 'archived': False, 'decision': 'promoted', 'reason': 'auto_lineage_tick'}
            promoted.append(did)
            _append_jsonl(BIO_PATH, {'ts': _now(), 'type': 'descendant_auto_promoted', 'descendant': {'id': did}, 'score': score})
            continue
        safety = float(metrics.get('safety') or 0.0)
        if state not in {'promoted', 'archived'} and len(archived) < max(1, int(max_archives or 3)) and ((score > 0.0 and score < 0.45) or (metrics and safety < 0.45)):
            item['state'] = 'archived'
            item['promotion'] = {'eligible': False, 'archived': True, 'decision': 'archived', 'reason': 'auto_lineage_tick_low_score'}
            archived.append(did)
            _append_jsonl(BIO_PATH, {'ts': _now(), 'type': 'descendant_auto_archived', 'descendant': {'id': did}, 'score': score, 'safety': safety})
    _save_lineage(data)
    return {'ok': True, 'reviewed': reviewed[-50:], 'promoted': promoted, 'archived': archived, 'reserve_mode': reserve_mode, 'count': len(arr)}


def runtime_spawn_bridge(descendant_id: str, runtime: str = 'isolated_stub') -> dict[str, Any]:
    data = _load_lineage()
    arr = list(data.get('lineages') or [])
    target = None
    for item in arr:
        if str(item.get('id') or '') == str(descendant_id):
            target = item
            break
    if target is None:
        return {'ok': False, 'error': 'descendant_not_found'}
    session_ref = f"{runtime}:{descendant_id}:{_now()}"
    bridge = {
        'runtime': str(runtime or 'isolated_stub')[:40],
        'session_ref': session_ref,
        'connected_at': _now(),
        'state': 'prepared',
    }
    target['runtime_bridge'] = bridge
    if str(target.get('state') or '') == 'prepared':
        target['state'] = 'runtime_prepared'
    _save_lineage(data)
    _append_jsonl(BIO_PATH, {'ts': _now(), 'type': 'descendant_runtime_bridge_prepared', 'descendant': {'id': descendant_id}, 'runtime_bridge': bridge})
    return {'ok': True, 'item': target, 'runtime_bridge': bridge}


def active_status() -> dict[str, Any]:
    contract = self_contract()
    damage = detect_damage()
    contain = contain_damage()
    response = homeostatic_response(non_critical=True)
    narrative = narrative_coherence_status()
    arbitration = arbitrate_external_vs_integrity(task_type='general', predicted_latency_ms=0, non_critical=True, requires_external=False, external_priority=0.5)
    return {
        'ok': True,
        'self_contract': contract,
        'boundary': boundary_status(),
        'continuity_reserve': contract.get('continuity_reserve'),
        'damage_detector': damage,
        'containment': contain,
        'homeostatic_response': response,
        'narrative': narrative,
        'external_integrity_arbitration': arbitration,
        'lineage': lineage_status(limit=10),
        'incident_ledger': incidents(limit=10),
    }
