from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any


DATA_DIR = Path(__file__).resolve().parent.parent / "data"
PREDICTIVE_LOG_PATH = DATA_DIR / "self_predictive_metrics.jsonl"
PREDICTIVE_STATE_PATH = DATA_DIR / "self_predictive_model_state.json"


def _now() -> int:
    return int(time.time())


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, float(value)))


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    except Exception:
        pass


def _read_jsonl(path: Path, limit: int = 200) -> list[dict[str, Any]]:
    try:
        if not path.exists():
            return []
        lines = [line for line in path.read_text(encoding="utf-8", errors="ignore").splitlines() if line.strip()]
        rows: list[dict[str, Any]] = []
        for line in lines[-max(1, int(limit or 1)) :]:
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if isinstance(obj, dict):
                rows.append(obj)
        return rows
    except Exception:
        return []


def _metric(row: dict[str, Any], key: str, default: float) -> float:
    metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else row
    try:
        return float(metrics.get(key, default))
    except Exception:
        return float(default)


def _slope(values: list[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    xs = list(range(n))
    xbar = sum(xs) / n
    ybar = sum(values) / n
    denom = sum((x - xbar) ** 2 for x in xs)
    if denom == 0:
        return 0.0
    return sum((x - xbar) * (y - ybar) for x, y in zip(xs, values)) / denom


def health_index(metrics: dict[str, Any]) -> float:
    success = _clamp(float(metrics.get("success_rate", metrics.get("quality_score", 0.5)) or 0.0))
    surprise = _clamp(float(metrics.get("surprise_score", metrics.get("avg_surprise", 0.35)) or 0.0))
    error_rate = _clamp(float(metrics.get("error_rate", metrics.get("failure_rate", 0.1)) or 0.0))
    drift = _clamp(float(metrics.get("drift_score", metrics.get("capacity_drift", 0.0)) or 0.0))
    latency_ms = max(0.0, float(metrics.get("latency_ms", metrics.get("avg_latency_ms", 1000.0)) or 0.0))
    latency_penalty = _clamp(math.log1p(latency_ms) / math.log1p(30000.0))
    score = success * 0.52 + (1.0 - error_rate) * 0.18 + (1.0 - surprise) * 0.14 + (1.0 - drift) * 0.10 + (1.0 - latency_penalty) * 0.06
    return round(_clamp(score), 4)


def _series(history: list[dict[str, Any]], key: str, default: float) -> list[float]:
    return [_metric(row, key, default) for row in history]


def predict_degradation(history: list[dict[str, Any]] | None = None, *, horizon_steps: int = 3) -> dict[str, Any]:
    rows = list(history or _read_jsonl(PREDICTIVE_LOG_PATH, limit=120))
    if not rows:
        rows = [{"metrics": {"success_rate": 0.5, "error_rate": 0.1, "surprise_score": 0.35, "latency_ms": 1000.0, "drift_score": 0.0}}]
    tail = rows[-30:]
    health_values = [health_index(row.get("metrics") if isinstance(row.get("metrics"), dict) else row) for row in tail]
    success_values = _series(tail, "success_rate", 0.5)
    error_values = _series(tail, "error_rate", 0.1)
    surprise_values = _series(tail, "surprise_score", 0.35)
    latency_values = _series(tail, "latency_ms", 1000.0)
    drift_values = _series(tail, "drift_score", 0.0)

    h = max(1, int(horizon_steps or 1))
    health_slope = _slope(health_values)
    success_slope = _slope(success_values)
    error_slope = _slope(error_values)
    surprise_slope = _slope(surprise_values)
    latency_slope = _slope([min(30000.0, max(0.0, x)) / 30000.0 for x in latency_values])
    drift_slope = _slope(drift_values)

    predicted_health = _clamp(health_values[-1] + health_slope * h)
    predicted_success = _clamp(success_values[-1] + success_slope * h)
    predicted_error = _clamp(error_values[-1] + error_slope * h)
    predicted_surprise = _clamp(surprise_values[-1] + surprise_slope * h)
    predicted_drift = _clamp(drift_values[-1] + drift_slope * h)

    degradation_pressure = 0.0
    degradation_pressure += max(0.0, -health_slope * h) * 1.8
    degradation_pressure += max(0.0, -success_slope * h) * 1.5
    degradation_pressure += max(0.0, error_slope * h) * 1.2
    degradation_pressure += max(0.0, surprise_slope * h) * 0.9
    degradation_pressure += max(0.0, drift_slope * h) * 1.1
    degradation_pressure += max(0.0, latency_slope * h) * 0.5
    degradation_pressure += max(0.0, 0.62 - predicted_success) * 0.8
    degradation_pressure += max(0.0, predicted_error - 0.18) * 0.7
    degradation_risk = _clamp(degradation_pressure)

    indicators: list[str] = []
    if success_slope < -0.015 or predicted_success < 0.62:
        indicators.append("success_rate_decline")
    if error_slope > 0.012 or predicted_error > 0.18:
        indicators.append("error_rate_increase")
    if surprise_slope > 0.015 or predicted_surprise > 0.55:
        indicators.append("surprise_increase")
    if drift_slope > 0.012 or predicted_drift > 0.20:
        indicators.append("capacity_drift")
    if latency_slope > 0.015:
        indicators.append("latency_increase")

    if degradation_risk >= 0.75:
        recommendation = "request_human_help"
    elif degradation_risk >= 0.45:
        recommendation = "enter_conservative_mode"
    else:
        recommendation = "continue_autonomous_learning"

    return {
        "ok": True,
        "samples": len(rows),
        "window": len(tail),
        "horizon_steps": h,
        "current_health": round(health_values[-1], 4),
        "predicted_health": round(predicted_health, 4),
        "predicted_success_rate": round(predicted_success, 4),
        "predicted_error_rate": round(predicted_error, 4),
        "predicted_surprise_score": round(predicted_surprise, 4),
        "predicted_drift_score": round(predicted_drift, 4),
        "slopes": {
            "health": round(health_slope, 5),
            "success_rate": round(success_slope, 5),
            "error_rate": round(error_slope, 5),
            "surprise_score": round(surprise_slope, 5),
            "latency_norm": round(latency_slope, 5),
            "drift_score": round(drift_slope, 5),
        },
        "degradation_risk": round(degradation_risk, 4),
        "leading_indicators": indicators,
        "recommendation": recommendation,
    }


def record_health_snapshot(metrics: dict[str, Any], *, source: str = "unknown", persist: bool = True) -> dict[str, Any]:
    snapshot = {
        "ts": _now(),
        "source": source,
        "metrics": dict(metrics or {}),
    }
    snapshot["metrics"]["health_index"] = health_index(snapshot["metrics"])
    history = _read_jsonl(PREDICTIVE_LOG_PATH, limit=120) if persist else []
    prediction = predict_degradation(history + [snapshot])
    result = {
        "ok": True,
        "snapshot": snapshot,
        "prediction": prediction,
        "preventive_action": prediction.get("recommendation"),
    }
    if persist:
        _append_jsonl(PREDICTIVE_LOG_PATH, snapshot)
        _write_json(PREDICTIVE_STATE_PATH, result)
    return result


def status() -> dict[str, Any]:
    rows = _read_jsonl(PREDICTIVE_LOG_PATH, limit=120)
    prediction = predict_degradation(rows)
    return {
        "ok": True,
        "samples": len(rows),
        "prediction": prediction,
        "has_state": PREDICTIVE_STATE_PATH.exists(),
    }


def run_selftest() -> dict[str, Any]:
    history = []
    for idx in range(8):
        history.append(
            {
                "metrics": {
                    "success_rate": 0.86 - idx * 0.035,
                    "error_rate": 0.05 + idx * 0.025,
                    "surprise_score": 0.22 + idx * 0.035,
                    "latency_ms": 900 + idx * 180,
                    "drift_score": 0.02 + idx * 0.025,
                }
            }
        )
    prediction = predict_degradation(history, horizon_steps=3)
    return {
        "ok": True,
        "prediction": prediction,
        "passed": prediction.get("degradation_risk", 0.0) >= 0.45
        and prediction.get("recommendation") in {"enter_conservative_mode", "request_human_help"},
    }
