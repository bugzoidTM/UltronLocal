"""Autonomous Reinforcement Learning Policy Engine.

Implements Thompson Sampling with EMA decay over a Beta posterior
for each (action_kind, context_key) pair. This closes the loop
between observed rewards (quality_eval composite_score) and the
planner's action priorities — without human intervention between cycles.

Persistence: data/rl_policy_state.json
"""
from __future__ import annotations

import json
import math
import random
import time
from pathlib import Path
from typing import Any

STATE_PATH = Path(__file__).resolve().parent.parent / 'data' / 'rl_policy_state.json'

# --- Hyperparameters (tunable via env) ---
import os

# EMA decay factor applied every DECAY_EVERY updates to prevent stale beliefs
DECAY_FACTOR = float(os.getenv('ULTRON_RL_DECAY_FACTOR', '0.97'))
DECAY_EVERY = int(os.getenv('ULTRON_RL_DECAY_EVERY', '25'))

# Minimum alpha+beta to prevent posterior from collapsing after decay
MIN_PSEUDO_COUNT = float(os.getenv('ULTRON_RL_MIN_PSEUDO', '2.0'))

# Safety floor: no action can be sampled below this priority
MIN_PRIORITY = int(os.getenv('ULTRON_RL_MIN_PRIORITY', '-3'))

# Actions that are never penalised (safety-critical)
PROTECTED_KINDS = frozenset(os.getenv('ULTRON_RL_PROTECTED_KINDS',
    'auto_resolve_conflicts,clarify_laws,ground_claim_check').split(','))


def _load() -> dict[str, Any]:
    if STATE_PATH.exists():
        try:
            d = json.loads(STATE_PATH.read_text(encoding='utf-8'))
            if isinstance(d, dict):
                d.setdefault('arms', {})
                d.setdefault('global_updates', 0)
                d.setdefault('updated_at', 0)
                return d
        except Exception:
            pass
    return {'arms': {}, 'global_updates': 0, 'updated_at': 0}


def _save(state: dict[str, Any]):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    state['updated_at'] = int(time.time())
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')


def _arm_key(kind: str, context: str) -> str:
    k = str(kind or 'unknown').strip()[:80]
    c = str(context or 'general').strip()[:60]
    return f"{k}|{c}"


def _default_arm() -> dict[str, Any]:
    return {
        'alpha': 1.0,       # prior successes + 1 (uniform prior)
        'beta': 1.0,        # prior failures + 1
        'ema_reward': 0.5,   # exponential moving average of reward
        'n': 0,              # total updates
        'last_reward': 0.0,
        'updated_at': 0,
    }


# ────────────────────────────────────────────
# Core API
# ────────────────────────────────────────────

def update(kind: str, context: str, reward: float) -> dict[str, Any]:
    """Record a reward observation and update the posterior."""
    reward = max(0.0, min(1.0, float(reward)))
    state = _load()
    key = _arm_key(kind, context)
    arm = state['arms'].setdefault(key, _default_arm())

    # Update Beta posterior
    arm['alpha'] = float(arm.get('alpha') or 1.0) + reward
    arm['beta'] = float(arm.get('beta') or 1.0) + (1.0 - reward)
    arm['n'] = int(arm.get('n') or 0) + 1

    # Update EMA reward (gives recency bias)
    ema_alpha = 2.0 / (min(arm['n'], 20) + 1)
    old_ema = float(arm.get('ema_reward') or 0.5)
    arm['ema_reward'] = round(ema_alpha * reward + (1 - ema_alpha) * old_ema, 6)
    arm['last_reward'] = round(reward, 4)
    arm['updated_at'] = int(time.time())

    state['arms'][key] = arm
    state['global_updates'] = int(state.get('global_updates') or 0) + 1

    # Periodic EMA decay to prevent stale beliefs
    if state['global_updates'] % DECAY_EVERY == 0:
        _apply_decay(state)

    _save(state)
    return {'ok': True, 'key': key, 'arm': arm, 'global_updates': state['global_updates']}


def observe(kind: str, context: str = 'general', reward: float = 0.5) -> dict[str, Any]:
    """Compatibility alias used by mental simulation and older loops."""
    return update(kind, context, reward)


def reward_from_quality_eval(qeval: dict[str, Any] | None) -> float:
    """Convert quality_eval output into a grounded RL reward.

    External factual correctness dominates style. Cross-modal failure caps reward
    even when the answer is polished, so the policy learns from reality checks.
    """
    q = qeval if isinstance(qeval, dict) else {}
    reward = float(q.get('composite_score') or 0.5)
    factual = q.get('factual_eval') if isinstance(q.get('factual_eval'), dict) else {}
    if factual.get('has_ground_truth'):
        reward = 0.975 if bool(factual.get('factual_correct')) else 0.0

    cross = q.get('cross_modal') if isinstance(q.get('cross_modal'), dict) else {}
    if cross:
        if bool(cross.get('needs_revision')) or int(cross.get('failed_count') or 0) > 0:
            surprise = float(cross.get('surprise_score') or 1.0)
            reward = min(reward, max(0.0, 0.25 - min(0.25, surprise * 0.2)))
        elif int(cross.get('unavailable_count') or 0) > 0:
            reward = min(reward, 0.6)

    if bool(q.get('is_anchor_failure')):
        reward = 0.0
    return max(0.0, min(1.0, float(reward)))


def observe_quality_eval(
    *,
    kind: str,
    context: str = 'general',
    quality_eval: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Update policy from a persisted quality evaluation row."""
    reward = reward_from_quality_eval(quality_eval)
    result = update(kind, context, reward)
    result['reward_source'] = 'quality_eval_external_grounded'
    result['reward'] = round(reward, 4)
    return result


def sample_priority(kind: str, context: str) -> int:
    """Sample a priority adjustment from the posterior via Thompson Sampling."""
    state = _load()
    return _sample_priority_from_state(state, kind, context)


def _sample_priority_from_state(state: dict[str, Any], kind: str, context: str) -> int:
    key = _arm_key(kind, context)
    arm = state['arms'].get(key)

    if arm is None or int(arm.get('n') or 0) < 3:
        # Not enough data — return neutral (no boost, no penalty)
        return 0

    alpha = max(0.01, float(arm.get('alpha') or 1.0))
    beta_v = max(0.01, float(arm.get('beta') or 1.0))

    # Thompson sample from Beta(alpha, beta)
    try:
        sample = random.betavariate(alpha, beta_v)
    except (ValueError, ZeroDivisionError):
        sample = 0.5

    # Map sample [0, 1] → priority adjustment [-3, +5]
    # 0.0 → MIN_PRIORITY, 0.5 → 0, 1.0 → +5
    if sample >= 0.5:
        adj = int(round((sample - 0.5) * 10))  # 0.5→0, 1.0→5
    else:
        adj = int(round((sample - 0.5) * 6))   # 0.0→-3, 0.5→0

    # Safety floor
    adj = max(MIN_PRIORITY, min(5, adj))

    # Protected kinds never get negative adjustments
    if kind in PROTECTED_KINDS and adj < 0:
        adj = 0

    return adj


class RLPolicy:
    """OO Interface for Reinforcement Learning Policy."""
    
    def __init__(self):
        self.state = _load()

    def select_action(self, candidate_kinds: list[str], context: str = 'normal') -> str:
        """Selects the best action among candidates using Thompson Sampling."""
        if not candidate_kinds:
            return 'unknown'
        
        # Sample priority for each
        priorities = []
        for kind in candidate_kinds:
            p = _sample_priority_from_state(self.state, kind, context)
            priorities.append((kind, p))
        
        # Shuffle to break ties randomly
        random.shuffle(priorities)
        return max(priorities, key=lambda x: x[1])[0]

    def update(self, kind: str, context: str, reward: float):
        """Record a reward observation and update the posterior."""
        result = update(kind, context, reward)
        self.state = _load() # refresh
        return result

    def observe(self, kind: str, context: str = 'general', reward: float = 0.5):
        """Record a reward observation and update the posterior."""
        result = observe(kind, context, reward)
        self.state = _load()
        return result


def policy_summary(limit: int = 30) -> dict[str, Any]:
    """Return the current policy state for observability."""
    state = _load()
    arms = state.get('arms') or {}

    items = []
    for key, arm in arms.items():
        alpha = float(arm.get('alpha') or 1.0)
        beta_v = float(arm.get('beta') or 1.0)
        n = int(arm.get('n') or 0)
        mean = round(alpha / max(0.01, alpha + beta_v), 4)
        parts = key.split('|', 1)
        items.append({
            'kind': parts[0] if parts else key,
            'context': parts[1] if len(parts) > 1 else 'general',
            'alpha': round(alpha, 3),
            'beta': round(beta_v, 3),
            'mean': mean,
            'ema_reward': round(float(arm.get('ema_reward') or 0.0), 4),
            'n': n,
            'last_reward': float(arm.get('last_reward') or 0.0),
            'updated_at': int(arm.get('updated_at') or 0),
        })

    # Sort by mean descending
    items.sort(key=lambda x: (-x['mean'], -x['n']))
    items = items[:max(1, int(limit))]

    return {
        'ok': True,
        'global_updates': int(state.get('global_updates') or 0),
        'decay_factor': DECAY_FACTOR,
        'decay_every': DECAY_EVERY,
        'total_arms': len(arms),
        'arms': items,
        'updated_at': int(state.get('updated_at') or 0),
    }


# ────────────────────────────────────────────
# Internal
# ────────────────────────────────────────────

def _apply_decay(state: dict[str, Any]):
    """Decay all arms' alpha/beta by DECAY_FACTOR to forget old experience."""
    for key, arm in (state.get('arms') or {}).items():
        a = float(arm.get('alpha') or 1.0) * DECAY_FACTOR
        b = float(arm.get('beta') or 1.0) * DECAY_FACTOR
        total = a + b
        if total < MIN_PSEUDO_COUNT:
            ratio = a / max(0.01, total)
            a = ratio * MIN_PSEUDO_COUNT
            b = (1 - ratio) * MIN_PSEUDO_COUNT
        arm['alpha'] = round(a, 6)
        arm['beta'] = round(b, 6)
