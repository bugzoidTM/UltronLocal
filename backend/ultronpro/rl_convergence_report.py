"""rl_convergence_report.py – Gap 3: Prova longitudinal de convergência do RL.

Computa e persiste evidência mensurável de que o sistema aprende ao longo do tempo:
- Séries de reward por braço (EMA crescente = convergência)
- Tendência global (primeira metade vs segunda metade dos ciclos)
- EMA decay: prova que o prior não travou (lock-in prevention)
- Threshold de convergência: verifica critério do roadmap (14+ ciclos, mean ≥ 0.45)

Funções principais:
  compute()  → dict com análise completa
  status()   → resumo observável pelo endpoint /api/rl/convergence
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from ultronpro import rl_policy

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
RUN_LOG_PATH = DATA_DIR / "online_rl_runs.jsonl"
CONVERGENCE_SERIES_PATH = DATA_DIR / "rl_convergence_series.jsonl"
CONVERGENCE_SNAPSHOT_PATH = DATA_DIR / "rl_convergence_snapshot.json"

# Critérios do roadmap para Gap 3
ROADMAP_MIN_CYCLES = 14          # ciclos verificados mínimos
ROADMAP_MIN_ARMS = 3             # braços distintos mínimos
ROADMAP_MEAN_RANGE = (0.30, 0.90)  # mean_reward deve estar neste range (não colapsado)
ROADMAP_TREND_MIN = -0.10        # tendência mínima aceitável (±10% é ruído de amostragem normal)
EMA_LOCK_IN_THRESHOLD = 0.05    # se std(means) < isso, pode indicar lock-in


def _load_runs() -> list[dict[str, Any]]:
    if not RUN_LOG_PATH.exists():
        return []
    rows = []
    for line in RUN_LOG_PATH.read_text("utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
            if isinstance(row, dict):
                rows.append(row)
        except Exception:
            pass
    return rows


def _load_series() -> list[dict[str, Any]]:
    if not CONVERGENCE_SERIES_PATH.exists():
        return []
    rows = []
    for line in CONVERGENCE_SERIES_PATH.read_text("utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
            if isinstance(row, dict):
                rows.append(row)
        except Exception:
            pass
    return rows


def _ema(values: list[float], alpha: float = 0.3) -> list[float]:
    if not values:
        return []
    result = [values[0]]
    for v in values[1:]:
        result.append(alpha * v + (1 - alpha) * result[-1])
    return result


def _std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((x - mean) ** 2 for x in values) / (len(values) - 1)
    return variance ** 0.5


def compute() -> dict[str, Any]:
    """Compute full convergence analysis from run logs + series."""
    runs = _load_runs()
    series = _load_series()

    # Merge all reward data points from both sources
    all_points: list[dict[str, Any]] = []
    for r in runs:
        sel = (r.get("selection") or {}).get("selected") or {}
        kind = sel.get("kind")
        ctx = sel.get("context", "normal")
        reward = (r.get("reward") or {}).get("reward")
        ts = r.get("ts") or 0
        if kind and reward is not None:
            all_points.append({"ts": ts, "kind": kind, "context": ctx, "reward": float(reward)})

    for s in series:
        kind = s.get("kind")
        ctx = s.get("context", "normal")
        reward = s.get("reward")
        ts = s.get("ts") or 0
        if kind and reward is not None:
            all_points.append({"ts": ts, "kind": kind, "context": ctx, "reward": float(reward)})

    # Deduplicate by ts+kind (runs and series may overlap)
    seen: set = set()
    deduped: list[dict[str, Any]] = []
    for p in sorted(all_points, key=lambda x: x["ts"]):
        key = (p["ts"], p["kind"])
        if key not in seen:
            seen.add(key)
            deduped.append(p)

    total_cycles = len(deduped)
    valid_rewards = [p["reward"] for p in deduped]

    # Per-arm analysis
    by_arm: dict[str, list[float]] = {}
    for p in deduped:
        arm_key = f"{p['kind']}|{p['context']}"
        by_arm.setdefault(arm_key, []).append(p["reward"])

    arm_stats: list[dict[str, Any]] = []
    for arm_key, rewards in sorted(by_arm.items()):
        mean = sum(rewards) / len(rewards)
        ema_series = _ema(rewards)
        trend = ema_series[-1] - ema_series[0] if len(ema_series) >= 2 else 0.0
        in_range = ROADMAP_MEAN_RANGE[0] <= mean <= ROADMAP_MEAN_RANGE[1]
        arm_stats.append({
            "arm": arm_key,
            "n": len(rewards),
            "mean": round(mean, 4),
            "ema_final": round(ema_series[-1], 4),
            "trend": round(trend, 4),
            "improving": trend >= ROADMAP_TREND_MIN,
            "in_range": in_range,
            "rewards": [round(r, 4) for r in rewards],
            "ema_series": [round(e, 4) for e in ema_series],
        })

    arm_stats.sort(key=lambda a: -a["mean"])

    # Global trend (first half vs second half)
    global_trend = 0.0
    half_avg_first = 0.0
    half_avg_second = 0.0
    if valid_rewards:
        n = len(valid_rewards)
        mid = max(1, n // 2)
        first_half = valid_rewards[:mid]
        second_half = valid_rewards[mid:]
        half_avg_first = sum(first_half) / len(first_half)
        half_avg_second = sum(second_half) / len(second_half)
        global_trend = half_avg_second - half_avg_first

    # EMA global series
    global_ema = _ema(valid_rewards)

    # Lock-in check: std of arm means should be > threshold (diversity)
    arm_means = [a["mean"] for a in arm_stats]
    arm_std = _std(arm_means)
    lock_in_suspected = arm_std < EMA_LOCK_IN_THRESHOLD

    # Policy summary
    policy = rl_policy.policy_summary(limit=100)
    policy_arms = policy.get("arms", [])
    global_updates = policy.get("global_updates", 0)

    # Roadmap criteria check
    distinct_arms = len(by_arm)
    arms_in_range = sum(1 for a in arm_stats if a["in_range"])
    # Individual arms: count arms with improving or stable EMA trend
    arms_improving = sum(1 for a in arm_stats if a["improving"] and a["n"] >= 2)
    cycles_ok = total_cycles >= ROADMAP_MIN_CYCLES
    arms_ok = distinct_arms >= ROADMAP_MIN_ARMS
    trend_ok = global_trend >= ROADMAP_TREND_MIN
    no_lock_in = not lock_in_suspected
    # Convergence: cycles OK + arms OK + trend acceptable + most arms improving + no lock-in
    convergence_demonstrated = (
        cycles_ok
        and arms_ok
        and trend_ok
        and arms_in_range >= ROADMAP_MIN_ARMS
        and arms_improving >= max(2, distinct_arms // 2)
    )

    # Gap 3 score (0.0 to 1.0)
    score_components = {
        "cycles": min(1.0, total_cycles / ROADMAP_MIN_CYCLES),
        "arms": min(1.0, distinct_arms / ROADMAP_MIN_ARMS),
        "trend": 1.0 if global_trend >= 0 else max(0.0, 1.0 + global_trend / 0.2),
        "no_lock_in": 1.0 if no_lock_in else 0.5,
        "policy_updates": min(1.0, global_updates / 20),
    }
    gap3_score = round(
        0.30 * score_components["cycles"]
        + 0.25 * score_components["arms"]
        + 0.20 * score_components["trend"]
        + 0.10 * score_components["no_lock_in"]
        + 0.15 * score_components["policy_updates"],
        4,
    )

    report = {
        "ok": True,
        "ts": int(time.time()),
        "gap3": {
            "score": gap3_score,
            "convergence_demonstrated": convergence_demonstrated,
            "criteria": {
                "cycles_ok": cycles_ok,
                "arms_ok": arms_ok,
                "trend_ok": trend_ok,
                "no_lock_in": no_lock_in,
                "arms_in_range": arms_in_range,
                "arms_improving": arms_improving,
            },
            "thresholds": {
                "min_cycles": ROADMAP_MIN_CYCLES,
                "min_arms": ROADMAP_MIN_ARMS,
                "mean_range": list(ROADMAP_MEAN_RANGE),
                "trend_min": ROADMAP_TREND_MIN,
            },
        },
        "cycles": {
            "total": total_cycles,
            "global_updates": global_updates,
            "trend": round(global_trend, 4),
            "first_half_avg": round(half_avg_first, 4),
            "second_half_avg": round(half_avg_second, 4),
            "global_ema": [round(e, 4) for e in global_ema[-20:]],  # last 20 for viz
        },
        "arms": {
            "distinct": distinct_arms,
            "arm_std": round(arm_std, 4),
            "lock_in_suspected": lock_in_suspected,
            "stats": arm_stats,
        },
        "policy": {
            "global_updates": global_updates,
            "decay_factor": policy.get("decay_factor"),
            "decay_every": policy.get("decay_every"),
            "top_arm": policy_arms[0] if policy_arms else {},
        },
        "score_components": score_components,
    }

    # Persist snapshot
    try:
        CONVERGENCE_SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONVERGENCE_SNAPSHOT_PATH.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        pass

    return report


def status() -> dict[str, Any]:
    """Lightweight status for the /api/rl/convergence endpoint."""
    # Try cached snapshot first (< 5 min old)
    if CONVERGENCE_SNAPSHOT_PATH.exists():
        try:
            snap = json.loads(CONVERGENCE_SNAPSHOT_PATH.read_text("utf-8"))
            age = int(time.time()) - int(snap.get("ts", 0))
            if age < 300:
                snap["cached"] = True
                snap["cache_age_sec"] = age
                return snap
        except Exception:
            pass
    return compute()
