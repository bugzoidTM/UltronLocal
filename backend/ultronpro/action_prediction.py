"""Modelo preditivo de consequências de ações.

Fecha o ciclo sensorimotor do loop de RL online: antes de executar uma ação o
sistema prevê a recompensa esperada (predict); depois compara a previsão com a
consequência real (settle) e aprende com o erro — o arm fica calibrado, a
surpresa alimenta a curiosidade (exploration_bonus) e descalibração persistente
vira lacuna epistêmica (miscalibration_gap) que o ciclo de aquisição confiável
pode investigar. Determinístico, sem LLM.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
STATE_PATH = DATA_DIR / "action_prediction_state.json"
TRACE_PATH = DATA_DIR / "action_predictions.jsonl"
SCHEMA = "ultron.action_prediction.v1"

# EMA com memória curta: o modelo deve refletir o comportamento recente do mundo.
EMA_ALPHA = 0.30
PRIOR_REWARD = 0.5
PRIOR_CONFIDENCE = 0.2
SURPRISE_THRESHOLD = 0.35
RECENT_ERRORS_CAP = 60
MISCALIBRATION_MIN_SAMPLES = 4
MISCALIBRATION_MAE = 0.25


def _now() -> int:
    return int(time.time())


def _clip01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _read_json(path: Path, default: Any = None) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        pass
    return default


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _arm_key(kind: Any, context: Any) -> str:
    return f"{str(kind or 'unknown')}|{str(context or 'normal')}"


def _load_state() -> dict[str, Any]:
    state = _read_json(STATE_PATH, {})
    if not isinstance(state, dict):
        state = {}
    state.setdefault("schema", SCHEMA)
    state.setdefault("arms", {})
    state.setdefault("recent_abs_errors", [])
    return state


def predict(candidate: dict[str, Any], observation: dict[str, Any] | None = None) -> dict[str, Any]:
    """Prevê a recompensa da ação antes de executá-la, com base no histórico do arm."""
    kind = str(candidate.get("kind") or "unknown")
    context = str(candidate.get("context") or "normal")
    key = _arm_key(kind, context)
    arm = (_load_state().get("arms") or {}).get(key)
    if isinstance(arm, dict) and int(arm.get("n") or 0) > 0:
        n = int(arm.get("n") or 0)
        mae = float(arm.get("mae") or 0.5)
        predicted = _clip01(float(arm.get("mean_reward") or PRIOR_REWARD))
        confidence = round(min(0.95, (n / (n + 3.0)) * max(0.0, 1.0 - mae)), 4)
        basis = "arm_ema_mean_reward"
    else:
        n = 0
        predicted = PRIOR_REWARD
        confidence = PRIOR_CONFIDENCE
        basis = "uniform_prior"
    return {
        "schema": SCHEMA,
        "ts": _now(),
        "kind": kind,
        "context": context,
        "key": key,
        "predicted_reward": round(predicted, 4),
        "confidence": confidence,
        "basis": basis,
        "n_prior": n,
    }


def settle(prediction: dict[str, Any], actual_reward: float, *, detail: dict[str, Any] | None = None) -> dict[str, Any]:
    """Compara a previsão com a consequência real e atualiza o modelo do arm."""
    if not isinstance(prediction, dict) or "predicted_reward" not in prediction:
        return {"ok": False, "error": "invalid_prediction"}
    actual = _clip01(float(actual_reward))
    predicted = _clip01(float(prediction.get("predicted_reward") or PRIOR_REWARD))
    error = round(actual - predicted, 4)
    surprise = round(abs(error), 4)
    key = str(prediction.get("key") or _arm_key(prediction.get("kind"), prediction.get("context")))

    state = _load_state()
    arms = state["arms"]
    arm = arms.setdefault(key, {"n": 0, "mean_reward": PRIOR_REWARD, "mae": 0.5, "bias": 0.0})
    arm["n"] = int(arm.get("n") or 0) + 1
    arm["mean_reward"] = round((1 - EMA_ALPHA) * float(arm.get("mean_reward") or PRIOR_REWARD) + EMA_ALPHA * actual, 4)
    arm["mae"] = round((1 - EMA_ALPHA) * float(arm.get("mae") or 0.5) + EMA_ALPHA * surprise, 4)
    arm["bias"] = round((1 - EMA_ALPHA) * float(arm.get("bias") or 0.0) + EMA_ALPHA * error, 4)
    arm["calibration"] = round(max(0.0, 1.0 - float(arm["mae"])), 4)
    arm["last_surprise"] = surprise
    arm["updated_at"] = _now()

    recent = [float(x) for x in (state.get("recent_abs_errors") or [])][-(RECENT_ERRORS_CAP - 1):]
    recent.append(surprise)
    state["recent_abs_errors"] = recent
    state["updated_at"] = _now()
    _write_json(STATE_PATH, state)

    high_surprise = surprise >= SURPRISE_THRESHOLD
    _append_jsonl(TRACE_PATH, {
        **prediction,
        "actual_reward": actual,
        "error": error,
        "surprise": surprise,
        "high_surprise": high_surprise,
        "detail": detail or {},
    })
    return {
        "ok": True,
        "key": key,
        "predicted_reward": predicted,
        "actual_reward": actual,
        "error": error,
        "surprise": surprise,
        "high_surprise": high_surprise,
        "arm": dict(arm),
        "learning": learning_report(state),
    }


def learning_report(state: dict[str, Any] | None = None) -> dict[str, Any]:
    """A inteligência aqui é mensurável: o erro de predição está caindo?"""
    state = state if isinstance(state, dict) else _load_state()
    recent = [float(x) for x in (state.get("recent_abs_errors") or [])]
    if len(recent) < 4:
        return {"samples": len(recent), "trend": "insufficient_data", "improving": None}
    mid = len(recent) // 2
    first = sum(recent[:mid]) / mid
    second = sum(recent[mid:]) / (len(recent) - mid)
    delta = round(second - first, 4)
    if delta < -0.02:
        trend = "improving"
    elif delta > 0.02:
        trend = "worsening"
    else:
        trend = "stable"
    return {
        "samples": len(recent),
        "mae_first_half": round(first, 4),
        "mae_second_half": round(second, 4),
        "delta": delta,
        "improving": delta < 0.0,
        "trend": trend,
    }


def exploration_bonus(kind: str, context: str) -> float:
    """Ações cujas consequências o modelo ainda não entende merecem exploração."""
    arm = (_load_state().get("arms") or {}).get(_arm_key(kind, context))
    if not isinstance(arm, dict) or int(arm.get("n") or 0) <= 0:
        return 0.08
    return round(min(0.12, float(arm.get("mae") or 0.0) * 0.30), 4)


def miscalibration_gap() -> dict[str, Any] | None:
    """Descalibração persistente vira lacuna epistêmica para o ciclo de aquisição."""
    worst: tuple[str, float, dict[str, Any]] | None = None
    for key, arm in (_load_state().get("arms") or {}).items():
        if not isinstance(arm, dict) or int(arm.get("n") or 0) < MISCALIBRATION_MIN_SAMPLES:
            continue
        mae = float(arm.get("mae") or 0.0)
        if mae < MISCALIBRATION_MAE:
            continue
        if worst is None or mae > worst[1]:
            worst = (str(key), mae, dict(arm))
    if worst is None:
        return None
    key, mae, arm = worst
    kind = key.split("|", 1)[0]
    return {
        "gap_id": f"action_model_miscalibrated_{kind}",
        "label": f"modelo de consequencias mal calibrado para acao {kind}",
        "domain": "action_consequence_model",
        "metric": f"mae={mae} n={arm.get('n')} bias={arm.get('bias')}",
        "severity": min(1.0, mae * 1.6),
        "evidence": {"arm_key": key, "arm": arm},
        "next_experiment": (
            f"prever e medir consequencias de {kind} em contextos controlados "
            f"ate o erro medio cair abaixo de {MISCALIBRATION_MAE}"
        ),
    }


def status(limit: int = 20) -> dict[str, Any]:
    state = _load_state()
    arms = []
    for key, arm in (state.get("arms") or {}).items():
        if isinstance(arm, dict):
            arms.append({"key": key, **arm})
    arms.sort(key=lambda item: -int(item.get("n") or 0))
    return {
        "ok": True,
        "schema": SCHEMA,
        "arms": arms[: max(1, int(limit))],
        "learning": learning_report(state),
        "miscalibration_gap": miscalibration_gap(),
        "updated_at": state.get("updated_at"),
    }


def run_selftest() -> dict[str, Any]:
    import tempfile

    global STATE_PATH, TRACE_PATH
    old_state, old_trace = STATE_PATH, TRACE_PATH
    with tempfile.TemporaryDirectory(prefix="action-prediction-") as td:
        base = Path(td)
        STATE_PATH = base / "action_prediction_state.json"
        TRACE_PATH = base / "action_predictions.jsonl"
        try:
            candidate = {"kind": "selftest_action", "context": "selftest"}
            prediction = predict(candidate)
            settlement = settle(prediction, 0.9, detail={"selftest": True})
            converged = predict(candidate)
            return {
                "ok": bool(settlement.get("ok") and converged.get("basis") == "arm_ema_mean_reward"),
                "non_llm": True,
                "prediction": prediction,
                "settlement": {k: settlement.get(k) for k in ("key", "error", "surprise", "high_surprise")},
            }
        finally:
            STATE_PATH, TRACE_PATH = old_state, old_trace
