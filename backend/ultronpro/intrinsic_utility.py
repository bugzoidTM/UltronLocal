"""Intrinsic Utility Function — Emergent Self-Goals.

Derives what the system *should want* from what it *learned about itself*.
No hardcoded goal templates. Objectives emerge from the gap between
observed and desired state, weighted by experience-adjusted drive priorities.

Persistence: data/intrinsic_utility_state.json
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

STATE_PATH = Path(__file__).resolve().parent.parent / 'data' / 'intrinsic_utility_state.json'

# ────────────────────────────────────────────
# Default drive weights (starting point only — they evolve)
# ────────────────────────────────────────────
_DEFAULT_DRIVES = {
    'competence':  {'weight': 0.22, 'desired': 0.80, 'observed': 0.50},
    'coherence':   {'weight': 0.22, 'desired': 0.75, 'observed': 0.50},
    'autonomy':    {'weight': 0.20, 'desired': 0.70, 'observed': 0.30},
    'novelty':     {'weight': 0.18, 'desired': 0.60, 'observed': 0.40},
    'integrity':   {'weight': 0.18, 'desired': 0.90, 'observed': 0.70},
}

EMA_ALPHA = 0.15       # blend factor for observed signal updates
WEIGHT_EMA = 0.08      # blend factor for drive weight adjustments
MIN_WEIGHT = 0.05      # no drive can be suppressed below this
TAMPER_WINDOW = 5      # number of recent hashes to keep


def _now() -> int:
    return int(time.time())


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, float(x)))


def _hash_drives(drives: dict[str, Any]) -> str:
    canon = json.dumps(
        {k: round(float(v.get('weight', 0)), 6)
         for k, v in sorted(drives.items())},
        sort_keys=True,
    )
    return hashlib.sha256(canon.encode()).hexdigest()[:16]


# ────────────────────────────────────────────
# State management
# ────────────────────────────────────────────

def _default_state() -> dict[str, Any]:
    drives = {k: dict(v) for k, v in _DEFAULT_DRIVES.items()}
    return {
        'created_at': _now(),
        'updated_at': _now(),
        'drives': drives,
        'utility': 0.5,
        'utility_history': [],
        'emergent_goals': [],
        'active_emergent_goal': None,
        'tick_count': 0,
        'weight_hashes': [_hash_drives(drives)],
    }


def _load() -> dict[str, Any]:
    if STATE_PATH.exists():
        try:
            d = json.loads(STATE_PATH.read_text(encoding='utf-8'))
            if isinstance(d, dict):
                d.setdefault('drives', {k: dict(v) for k, v in _DEFAULT_DRIVES.items()})
                d.setdefault('utility', 0.5)
                d.setdefault('utility_history', [])
                d.setdefault('emergent_goals', [])
                d.setdefault('active_emergent_goal', None)
                d.setdefault('tick_count', 0)
                d.setdefault('weight_hashes', [])
                # Ensure all default drives exist
                for k, v in _DEFAULT_DRIVES.items():
                    if k not in d['drives']:
                        d['drives'][k] = dict(v)
                return d
        except Exception:
            pass
    return _default_state()


def _save(state: dict[str, Any]):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    state['updated_at'] = _now()
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')


def _apply_kernel_to_drives(drives: dict[str, Any], kernel: dict[str, Any] | None = None) -> dict[str, Any]:
    out = {k: dict(v) for k, v in (drives or {}).items() if isinstance(v, dict)}
    try:
        if kernel is None:
            from ultronpro import intrinsic_kernel

            params = intrinsic_kernel.stable_drive_params()
        else:
            values = kernel.get('values') if isinstance(kernel.get('values'), dict) else {}
            params = {
                k: {'weight': v.get('weight'), 'desired': v.get('desired')}
                for k, v in values.items()
                if isinstance(v, dict)
            }
        for name, p in params.items():
            if name not in out:
                out[name] = dict(_DEFAULT_DRIVES.get(name) or {'observed': 0.5})
            out[name]['weight'] = round(_clamp(float(p.get('weight') or out[name].get('weight') or 0.1), MIN_WEIGHT, 0.60), 6)
            out[name]['desired'] = round(_clamp(float(p.get('desired') or out[name].get('desired') or 0.5), 0.1, 0.98), 6)
            out[name]['weight_source'] = 'stable_intrinsic_kernel'
    except Exception:
        return out or {k: dict(v) for k, v in _DEFAULT_DRIVES.items()}
    return out


# ────────────────────────────────────────────
# Signal collection (reads from other modules)
# ────────────────────────────────────────────

def _collect_signals() -> dict[str, float]:
    """Collect observable signals from the system's own subsystems."""
    signals = {
        'competence': 0.5,
        'coherence': 0.5,
        'autonomy': 0.3,
        'novelty': 0.4,
        'integrity': 0.7,
    }

    # Competence: from self_model quality + RL policy mean reward
    try:
        from ultronpro import self_model
        op = (self_model.load().get('operational') or {})
        posture = op.get('risk_posture') if isinstance(op.get('risk_posture'), dict) else {}
        avg_q = float(posture.get('avg_quality') or 0.0)
        avg_g = float(posture.get('avg_grounding') or 0.0)
        signals['competence'] = _clamp(0.6 * avg_q + 0.4 * avg_g)
    except Exception:
        pass

    try:
        from ultronpro import rl_policy
        ps = rl_policy.policy_summary(limit=50)
        arms = ps.get('arms') if isinstance(ps.get('arms'), list) else []
        if arms:
            avg_mean = sum(float(a.get('mean') or 0.5) for a in arms) / len(arms)
            signals['competence'] = _clamp(0.5 * signals['competence'] + 0.5 * avg_mean)
    except Exception:
        pass

    # Coherence: from homeostasis + narrative coherence
    try:
        from ultronpro import homeostasis
        hs = homeostasis.status()
        vitals = hs.get('vitals') if isinstance(hs.get('vitals'), dict) else {}
        coh = float(vitals.get('coherence_score') or 0.5)
        cstress = float(vitals.get('contradiction_stress') or 0.3)
        signals['coherence'] = _clamp(0.6 * coh + 0.4 * (1.0 - cstress))
    except Exception:
        pass

    try:
        from ultronpro import self_governance
        nc = self_governance.narrative_coherence_status()
        nc_score = float(nc.get('narrative_coherence_score') or 0.5)
        signals['coherence'] = _clamp(0.5 * signals['coherence'] + 0.5 * nc_score)
    except Exception:
        pass

    # Autonomy: ratio of local vs cloud actions + autonomous cycles
    try:
        from ultronpro import self_model, autonomous_cognition, online_rl_loop
        
        causal = (self_model.load().get('causal') or {})
        events = causal.get('recent_events') if isinstance(causal.get('recent_events'), list) else []
        recent = events[-100:]
        local_ratio = 0.0
        if recent:
            local_count = sum(1 for e in recent if 'local' in str(e.get('strategy') or '').lower()
                              or 'llama' in str(e.get('strategy') or '').lower()
                              or 'gemma' in str(e.get('strategy') or '').lower())
            local_ratio = _clamp(local_count / max(1, len(recent)))
            
        ac_status = autonomous_cognition.status()
        rl_status = online_rl_loop.status()
        
        ac_ticks = int(ac_status.get('metrics', {}).get('ticks', 0))
        rl_cycles = int(rl_status.get('state', {}).get('cycle_count', 0))
        
        cycle_autonomy = _clamp((ac_ticks + rl_cycles) / 50.0)
        
        signals['autonomy'] = _clamp(0.3 * local_ratio + 0.7 * cycle_autonomy)
    except Exception:
        pass

    # Novelty: from intrinsic drive state
    try:
        from ultronpro import intrinsic
        ist = intrinsic.load_state()
        drives = ist.get('drives') if isinstance(ist.get('drives'), dict) else {}
        # High novelty drive = system IS novel-hungry (so observed novelty is low)
        # Low novelty drive = system is satiated (observed novelty is high)
        signals['novelty'] = _clamp(1.0 - float(drives.get('novelty') or 0.5))
    except Exception:
        pass

    # Integrity: from self_governance damage detection
    try:
        from ultronpro import self_governance
        inv = self_governance.invariants_status()
        violations = inv.get('violations') if isinstance(inv.get('violations'), list) else []
        signals['integrity'] = _clamp(1.0 - min(1.0, len(violations) / 3.0))
    except Exception:
        pass

    try:
        from ultronpro import self_governance
        det = self_governance.detect_damage()
        sev = float(det.get('severity_score') or 0.0)
        signals['integrity'] = _clamp(0.5 * signals['integrity'] + 0.5 * (1.0 - sev))
    except Exception:
        pass

    return signals


# ────────────────────────────────────────────
# Core API
# ────────────────────────────────────────────

def compute_utility(state: dict[str, Any] | None = None) -> float:
    """Compute scalar utility U ∈ [0, 1] from current drives."""
    st = state or _load()
    drives = _apply_kernel_to_drives(st.get('drives') or {})
    total = 0.0
    weight_sum = 0.0
    for name, d in drives.items():
        w = float(d.get('weight') or 0.1)
        obs = float(d.get('observed') or 0.0)
        des = float(d.get('desired') or 0.5)
        # Utility contribution: how close is observed to desired?
        satisfaction = 1.0 - abs(des - obs) / max(0.01, des)
        total += w * _clamp(satisfaction)
        weight_sum += w
    return round(_clamp(total / max(0.01, weight_sum)), 4)


def tick() -> dict[str, Any]:
    """Main tick: collect signals, update observed values, compute utility,
    adjust drive weights, and derive emergent goal if needed."""
    state = _load()
    drives = state.get('drives') or {}

    # 1. Collect fresh signals
    signals = _collect_signals()

    # 2. Update observed values with EMA
    for name, signal_val in signals.items():
        if name in drives:
            old_obs = float(drives[name].get('observed') or 0.5)
            drives[name]['observed'] = round(
                EMA_ALPHA * signal_val + (1 - EMA_ALPHA) * old_obs, 6
            )

    state['drives'] = drives

    kernel_update = None
    try:
        from ultronpro import intrinsic_kernel

        kernel_update = intrinsic_kernel.update_kernel(intrinsic_state=state)
        kernel = (kernel_update or {}).get('kernel') if isinstance(kernel_update, dict) else None
        if isinstance(kernel, dict):
            drives = _apply_kernel_to_drives(drives, kernel=kernel)
            state['drives'] = drives
            state['utility_kernel'] = {
                'revision': kernel.get('revision'),
                'hash': kernel.get('hash'),
                'stability': kernel.get('stability'),
            }
    except Exception as exc:
        kernel_update = {'ok': False, 'error': str(exc)[:160]}

    # 3. Compute utility
    utility = compute_utility(state)
    state['utility'] = utility

    # 4. Track utility history
    hist = list(state.get('utility_history') or [])
    hist.append({
        'ts': _now(),
        'utility': utility,
        'signals': {k: round(v, 4) for k, v in signals.items()},
        'utility_kernel': state.get('utility_kernel'),
    })
    state['utility_history'] = hist[-500:]

    # 5. Derive emergent goal if utility dropped or no active goal
    state['tick_count'] = int(state.get('tick_count') or 0) + 1
    active = state.get('active_emergent_goal')
    should_derive = (
        active is None
        or (len(hist) >= 3 and utility < float(hist[-3].get('utility') or utility) - 0.05)
        or (state['tick_count'] % 10 == 0)  # periodic re-evaluation
    )

    if should_derive:
        goal = derive_goals(state)
        if goal:
            state['active_emergent_goal'] = goal
            goals_log = list(state.get('emergent_goals') or [])
            goals_log.append(goal)
            state['emergent_goals'] = goals_log[-200:]

    # 6. Update hash
    hashes = list(state.get('weight_hashes') or [])
    hashes.append(_hash_drives(drives))
    state['weight_hashes'] = hashes[-TAMPER_WINDOW:]

    _save(state)
    return {
        'ok': True,
        'utility': utility,
        'signals': signals,
        'active_emergent_goal': state.get('active_emergent_goal'),
        'tick_count': state['tick_count'],
        'utility_kernel': state.get('utility_kernel'),
        'kernel_update': kernel_update,
    }


def derive_goals(state: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Identify the hungriest drive and generate an emergent goal."""
    st = state or _load()
    drives = _apply_kernel_to_drives(st.get('drives') or {})

    # Find the drive with the biggest gap (desired - observed), weighted
    gaps = []
    for name, d in drives.items():
        desired = float(d.get('desired') or 0.5)
        observed = float(d.get('observed') or 0.0)
        weight = float(d.get('weight') or 0.1)
        gap = (desired - observed) * weight  # weighted gap
        gaps.append((gap, name, desired, observed, weight))

    gaps.sort(key=lambda x: -x[0])  # biggest gap first
    if not gaps or gaps[0][0] <= 0.01:
        return None  # All drives satisfied

    top_gap, drive_name, desired, observed, weight = gaps[0]

    # Generate the goal text from the gap analysis (no templates!)
    goal_templates_by_drive = {
        'competence': lambda obs, des: (
            f"Elevar qualidade média das ações de {obs:.0%} para {des:.0%}. "
            f"Foco: domínios com confidence_by_domain < 0.5, priorizando grounding verificável."
        ),
        'coherence': lambda obs, des: (
            f"Reduzir stress contraditório e elevar coerência narrativa de {obs:.0%} para {des:.0%}. "
            f"Priorizar resolução dos conflitos abertos mais antigos."
        ),
        'autonomy': lambda obs, des: (
            f"Aumentar taxa de resolução local de {obs:.0%} para {des:.0%}. "
            f"Expandir capacidade do planner simbólico para resolver sem chamada de nuvem."
        ),
        'novelty': lambda obs, des: (
            f"Expandir cobertura de conhecimento. Saturação de novidade atual: {obs:.0%}, alvo: {des:.0%}. "
            f"Explorar domínios com menos de 5 triplas no grafo causal."
        ),
        'integrity': lambda obs, des: (
            f"Restaurar integridade operacional de {obs:.0%} para {des:.0%}. "
            f"Verificar invariantes violados, reparar memórias críticas, revalidar self-contract."
        ),
    }

    gen = goal_templates_by_drive.get(drive_name)
    if gen:
        description = gen(observed, desired)
    else:
        description = f"Reduzir gap no drive '{drive_name}': observado={observed:.2f}, desejado={desired:.2f}."

    goal = {
        'ts': _now(),
        'drive': drive_name,
        'gap': round(top_gap, 4),
        'observed': round(observed, 4),
        'desired': round(desired, 4),
        'weight': round(weight, 4),
        'title': f"[emergente] Fortalecer {drive_name}",
        'description': description,
        'origin': 'intrinsic_utility',
        'utility_kernel': st.get('utility_kernel'),
        'objective_contract': 'stable_intrinsic_kernel_gap_minimization',
        'priority': round(_clamp(0.3 + top_gap * 3, 0.3, 1.0), 2),
    }
    return goal


def adjust_drive_weights(drive_name: str, reward: float) -> dict[str, Any]:
    """After executing an emergent goal, adjust drive weights based on outcome.

    High reward → this drive generated a valuable goal → increase weight.
    Low reward → this drive's goal didn't help → decrease weight.
    """
    reward = _clamp(float(reward))
    state = _load()
    drives = state.get('drives') or {}

    if drive_name not in drives:
        return {'ok': False, 'reason': 'drive_not_found'}

    kernel_update = None
    try:
        from ultronpro import intrinsic_kernel

        kernel_update = intrinsic_kernel.record_consequence(drive_name, reward)
    except Exception as exc:
        kernel_update = {'ok': False, 'error': str(exc)[:160]}

    d = drives[drive_name]
    old_weight = float(d.get('weight') or 0.1)

    # Adjust: reward > 0.5 → increase, reward < 0.5 → decrease
    delta = (reward - 0.5) * WEIGHT_EMA
    new_weight = _clamp(old_weight + delta, MIN_WEIGHT, 0.40)
    d['weight'] = round(new_weight, 6)

    # Normalize all weights to sum to 1
    total_w = sum(float(drives[k].get('weight') or 0.1) for k in drives)
    for k in drives:
        drives[k]['weight'] = round(float(drives[k].get('weight') or 0.1) / max(0.01, total_w), 6)

    state['drives'] = _apply_kernel_to_drives(drives)
    drives = state['drives']
    try:
        kernel = (kernel_update or {}).get('kernel') if isinstance(kernel_update, dict) else None
        if isinstance(kernel, dict):
            state['utility_kernel'] = {
                'revision': kernel.get('revision'),
                'hash': kernel.get('hash'),
                'stability': kernel.get('stability'),
            }
    except Exception:
        pass

    # Update hash
    hashes = list(state.get('weight_hashes') or [])
    hashes.append(_hash_drives(drives))
    state['weight_hashes'] = hashes[-TAMPER_WINDOW:]

    _save(state)
    return {
        'ok': True,
        'drive': drive_name,
        'old_weight': round(old_weight, 4),
        'new_weight': round(new_weight, 4),
        'reward': round(reward, 4),
        'kernel_update': kernel_update,
    }


def tamper_check() -> dict[str, Any]:
    """Verify that drive weights haven't been tampered with externally."""
    state = _load()
    drives = state.get('drives') or {}
    current_hash = _hash_drives(drives)
    known_hashes = state.get('weight_hashes') if isinstance(state.get('weight_hashes'), list) else []
    kernel_check = None
    try:
        from ultronpro import intrinsic_kernel

        kernel_check = intrinsic_kernel.tamper_check()
    except Exception as exc:
        kernel_check = {'ok': False, 'error': str(exc)[:160]}

    if not known_hashes:
        return {'ok': True, 'tampered': False, 'reason': 'no_history', 'kernel_check': kernel_check}

    if current_hash in known_hashes:
        return {'ok': True, 'tampered': False, 'current_hash': current_hash, 'kernel_check': kernel_check}

    # Tamper detected — revert to default
    state['drives'] = {k: dict(v) for k, v in _DEFAULT_DRIVES.items()}
    state['weight_hashes'] = [_hash_drives(state['drives'])]
    _save(state)
    return {
        'ok': True,
        'tampered': True,
        'current_hash': current_hash,
        'known_hashes': known_hashes,
        'action': 'reverted_to_defaults',
        'kernel_check': kernel_check,
    }


def status(limit: int = 20) -> dict[str, Any]:
    """Full observability snapshot."""
    state = _load()
    drives = _apply_kernel_to_drives(state.get('drives') or {})
    kernel_status = None
    try:
        from ultronpro import intrinsic_kernel

        kernel_status = intrinsic_kernel.status(limit=limit)
    except Exception as exc:
        kernel_status = {'ok': False, 'error': str(exc)[:160]}

    drive_report = []
    for name, d in drives.items():
        desired = float(d.get('desired') or 0.5)
        observed = float(d.get('observed') or 0.0)
        weight = float(d.get('weight') or 0.1)
        gap = round((desired - observed) * weight, 4)
        drive_report.append({
            'drive': name,
            'weight': round(weight, 4),
            'desired': round(desired, 4),
            'observed': round(observed, 4),
            'gap': gap,
            'satisfaction': round(_clamp(1.0 - abs(desired - observed) / max(0.01, desired)), 4),
        })
    drive_report.sort(key=lambda x: -x['gap'])

    hist = (state.get('utility_history') or [])[-max(1, int(limit)):]
    goals = (state.get('emergent_goals') or [])[-max(1, int(limit)):]

    tc = tamper_check()

    return {
        'ok': True,
        'utility': float(state.get('utility') or 0.5),
        'drives': drive_report,
        'active_emergent_goal': state.get('active_emergent_goal'),
        'tick_count': int(state.get('tick_count') or 0),
        'utility_history': hist,
        'recent_emergent_goals': goals,
        'tamper_check': tc,
        'utility_kernel': kernel_status,
        'updated_at': int(state.get('updated_at') or 0),
    }
