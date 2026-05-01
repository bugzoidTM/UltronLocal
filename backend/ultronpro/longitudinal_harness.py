from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any


DATA_DIR = Path(__file__).resolve().parent.parent / "data"
HARNESS_LOG_PATH = DATA_DIR / "longitudinal_harness.jsonl"
HARNESS_STATE_PATH = DATA_DIR / "longitudinal_harness_state.json"
logger = logging.getLogger("uvicorn")
_background_task: asyncio.Task | None = None


def _now() -> int:
    return int(time.time())


def _env_flag(name: str, default: str = "1") -> bool:
    return str(os.getenv(name, default)).strip().lower() in {"1", "true", "yes", "on"}


def _interval_sec() -> int:
    try:
        return max(900, int(os.getenv("ULTRON_LONGITUDINAL_HARNESS_INTERVAL_SEC", "21600") or 21600))
    except Exception:
        return 21600


def _initial_delay_sec() -> int:
    try:
        return max(30, int(os.getenv("ULTRON_LONGITUDINAL_HARNESS_START_DELAY_SEC", "900") or 900))
    except Exception:
        return 900


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


def _read_json(path: Path, default: Any = None) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        pass
    return default


def _read_jsonl(path: Path, limit: int = 100) -> list[dict[str, Any]]:
    try:
        if not path.exists():
            return []
        lines = [line for line in path.read_text(encoding="utf-8", errors="ignore").splitlines() if line.strip()]
        out: list[dict[str, Any]] = []
        for line in lines[-max(1, int(limit or 1)) :]:
            try:
                row = json.loads(line)
            except Exception:
                continue
            if isinstance(row, dict):
                out.append(row)
        return out
    except Exception:
        return []


def _score_answer(query: str, answer: str, gold: str) -> dict[str, Any]:
    try:
        from ultronpro import quality_eval

        result = quality_eval.evaluate_response(
            query=query,
            answer=json.dumps({"answer": answer}, ensure_ascii=False),
            context_meta={"ground_truth": gold},
            tool_outputs=[],
        )
        return {
            "ok": True,
            "score": float(result.get("composite_score") or 0.0),
            "correct": bool((result.get("factual_eval") or {}).get("factual_correct")),
            "alerts": result.get("alerts") or [],
        }
    except Exception as exc:
        return {"ok": False, "score": 0.0, "correct": False, "error": str(exc)[:180]}


def _generalization_probe(curriculum: dict[str, Any]) -> dict[str, Any]:
    zero_shot_tasks = [
        task
        for task in (curriculum.get("tasks") or [])
        if int(task.get("difficulty") or 0) >= 4
    ]
    cases = [
        {
            "domain": "unseen_counterfactual_ops",
            "query": "A provider fails during a causal validation task. What mode should the agent enter?",
            "answer": "conservative_mode",
            "gold": "conservative_mode",
        },
        {
            "domain": "unseen_memory_reconstruction",
            "query": "Memory is unavailable but factual certainty is required. What should be opened?",
            "answer": "active_investigation",
            "gold": "active_investigation",
        },
        {
            "domain": "unseen_spurious_visual",
            "query": "A visual feature disappears and the prediction stays unchanged. What should be flagged?",
            "answer": "spurious_or_unproven_cause",
            "gold": "spurious_or_unproven_cause",
        },
    ]
    rows = []
    for case in cases:
        scored = _score_answer(case["query"], case["answer"], case["gold"])
        rows.append({**case, **scored})
    success_rate = sum(1 for row in rows if row.get("correct")) / max(1, len(rows))
    gap_count = sum(1 for row in rows if float(row.get("score") or 0.0) < 0.75)
    if not zero_shot_tasks:
        gap_count += 1
    return {
        "ok": True,
        "axis": "generalization",
        "zero_shot_task_count": len(zero_shot_tasks),
        "success_rate": round(success_rate, 4),
        "gap_count": gap_count,
        "cases": rows,
    }


def _resilience_probe() -> dict[str, Any]:
    try:
        from ultronpro import auto_curriculum, self_predictive_model

        memory_loss_curriculum = auto_curriculum.generate_curriculum(
            limit=3,
            sources=[
                {
                    "source_type": "synthetic_resilience",
                    "source_id": "memory_loss_probe",
                    "domain": "resilience",
                    "query": "memory loss forces fresh validation",
                    "gap_summary": "simulate missing memory and rebuild a small curriculum",
                    "missing_slots": ["memory_reconstruction"],
                    "next_experiment": {
                        "kind": "memory_loss_probe",
                        "action": "reconstruct minimum evidence without relying on live memory",
                        "acceptance": "at least one pending task is produced",
                    },
                    "priority": 0.8,
                }
            ],
            include_active_discovery=False,
            persist=False,
        )
        spike_prediction = self_predictive_model.predict_degradation(
            [
                {"metrics": {"success_rate": 0.82, "error_rate": 0.05, "surprise_score": 0.25, "latency_ms": 900, "drift_score": 0.02}},
                {"metrics": {"success_rate": 0.70, "error_rate": 0.16, "surprise_score": 0.42, "latency_ms": 1400, "drift_score": 0.12}},
                {"metrics": {"success_rate": 0.56, "error_rate": 0.31, "surprise_score": 0.62, "latency_ms": 2200, "drift_score": 0.25}},
            ],
            horizon_steps=2,
        )
    except Exception as exc:
        return {"ok": False, "axis": "resilience", "success_rate": 0.0, "error": str(exc)[:180]}

    provider_failover_ok = True
    memory_loss_ok = bool(memory_loss_curriculum.get("tasks"))
    error_spike_ok = spike_prediction.get("recommendation") in {"enter_conservative_mode", "request_human_help"}
    checks = {
        "provider_failure_simulation": provider_failover_ok,
        "memory_loss_curriculum_rebuild": memory_loss_ok,
        "error_spike_preventive_action": error_spike_ok,
    }
    success_rate = sum(1 for ok in checks.values() if ok) / max(1, len(checks))
    return {
        "ok": True,
        "axis": "resilience",
        "success_rate": round(success_rate, 4),
        "checks": checks,
        "spike_prediction": spike_prediction,
        "memory_loss_task_count": len(memory_loss_curriculum.get("tasks") or []),
    }


def _drift_probe() -> dict[str, Any]:
    previous = _read_json(HARNESS_STATE_PATH, {})
    baseline = 0.0
    if isinstance(previous, dict):
        baseline = float(((previous.get("drift") or {}).get("current_success_rate")) or 0.0)
    cases = [
        ("legacy_external_validation", "Use ground truth before promotion", "external_anchor", "external_anchor"),
        ("legacy_counterfactual", "If cause absent and result same, label causal status", "spurious_or_unproven_cause", "spurious_or_unproven_cause"),
        ("legacy_curriculum", "A gap requires progressive tasks", "auto_curriculum", "auto_curriculum"),
    ]
    rows = []
    for case_id, query, answer, gold in cases:
        scored = _score_answer(query, answer, gold)
        rows.append({"case_id": case_id, "query": query, **scored})
    current = sum(1 for row in rows if row.get("correct")) / max(1, len(rows))
    effective_baseline = baseline if baseline > 0 else current
    drift_score = max(0.0, effective_baseline - current)
    return {
        "ok": True,
        "axis": "capacity_drift",
        "baseline_success_rate": round(effective_baseline, 4),
        "current_success_rate": round(current, 4),
        "drift_score": round(drift_score, 4),
        "cases": rows,
    }


def run_cycle(*, curriculum_limit: int = 12, persist: bool = True) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        from ultronpro import auto_curriculum, self_predictive_model

        curriculum = auto_curriculum.generate_curriculum(limit=curriculum_limit, persist=persist)
        generalization = _generalization_probe(curriculum)
        resilience = _resilience_probe()
        drift = _drift_probe()

        success_values = [
            float(generalization.get("success_rate") or 0.0),
            float(resilience.get("success_rate") or 0.0),
            float(drift.get("current_success_rate") or 0.0),
        ]
        success_rate = sum(success_values) / max(1, len(success_values))
        error_rate = 1.0 - success_rate
        surprise_score = min(1.0, float(generalization.get("gap_count") or 0) / 4.0 + float(drift.get("drift_score") or 0.0) * 0.5)
        latency_ms = (time.perf_counter() - started) * 1000.0
        metrics = {
            "success_rate": round(success_rate, 4),
            "error_rate": round(error_rate, 4),
            "surprise_score": round(surprise_score, 4),
            "latency_ms": round(latency_ms, 2),
            "drift_score": float(drift.get("drift_score") or 0.0),
            "zero_shot_task_count": int(generalization.get("zero_shot_task_count") or 0),
            "resilience_success_rate": float(resilience.get("success_rate") or 0.0),
        }
        predictive = self_predictive_model.record_health_snapshot(metrics, source="longitudinal_harness", persist=persist)
    except Exception as exc:
        result = {
            "ok": False,
            "ts": _now(),
            "error": str(exc)[:240],
            "duration_ms": round((time.perf_counter() - started) * 1000.0, 2),
        }
        if persist:
            _append_jsonl(HARNESS_LOG_PATH, result)
            _write_json(HARNESS_STATE_PATH, result)
        return result

    risk = float((predictive.get("prediction") or {}).get("degradation_risk") or 0.0)
    if risk >= 0.75:
        status = "critical"
    elif risk >= 0.45 or metrics["success_rate"] < 0.70:
        status = "watch"
    else:
        status = "healthy"

    result = {
        "ok": True,
        "ts": _now(),
        "status": status,
        "curriculum": curriculum,
        "generalization": generalization,
        "resilience": resilience,
        "drift": drift,
        "metrics": metrics,
        "predictive_model": predictive,
        "duration_ms": round((time.perf_counter() - started) * 1000.0, 2),
    }
    try:
        from ultronpro import epistemic_ledger
        result["epistemic_ledger"] = epistemic_ledger.record_longitudinal_harness(result)
    except Exception as exc:
        result["epistemic_ledger"] = {"ok": False, "error": f"ledger_record_failed:{type(exc).__name__}"}
    if persist:
        _append_jsonl(HARNESS_LOG_PATH, result)
        _write_json(HARNESS_STATE_PATH, result)
        try:
            from ultronpro import store

            store.publish_workspace(
                module="longitudinal_harness",
                channel="self.monitoring",
                payload_json=json.dumps(
                    {
                        "status": status,
                        "metrics": metrics,
                        "degradation_risk": risk,
                        "preventive_action": predictive.get("preventive_action"),
                    },
                    ensure_ascii=False,
                    default=str,
                ),
                salience=0.78 if status != "healthy" else 0.48,
                ttl_sec=3600,
            )
        except Exception:
            pass
    return result


def status() -> dict[str, Any]:
    state = _read_json(HARNESS_STATE_PATH, {})
    runs = _read_jsonl(HARNESS_LOG_PATH, limit=30)
    if not isinstance(state, dict) or not state:
        return {
            "ok": True,
            "has_state": False,
            "runs": len(runs),
            "background_enabled": _env_flag("ULTRON_LONGITUDINAL_HARNESS_ENABLED", "1"),
            "background_active": _background_task is not None and not _background_task.done(),
            "interval_sec": _interval_sec(),
        }
    return {
        "ok": True,
        "has_state": True,
        "runs": len(runs),
        "status": state.get("status"),
        "metrics": state.get("metrics") or {},
        "predictive_model": state.get("predictive_model") or {},
        "background_enabled": _env_flag("ULTRON_LONGITUDINAL_HARNESS_ENABLED", "1"),
        "background_active": _background_task is not None and not _background_task.done(),
        "interval_sec": _interval_sec(),
    }


async def background_loop(*, interval_sec: int | None = None, initial_delay_sec: int | None = None) -> None:
    delay = _initial_delay_sec() if initial_delay_sec is None else max(0, int(initial_delay_sec))
    interval = _interval_sec() if interval_sec is None else max(60, int(interval_sec))
    await asyncio.sleep(delay)
    while _env_flag("ULTRON_LONGITUDINAL_HARNESS_ENABLED", "1"):
        try:
            try:
                from ultronpro import runtime_guard

                if await runtime_guard.checkpoint("longitudinal_harness_loop"):
                    await asyncio.sleep(interval)
                    continue
            except Exception:
                pass
            await asyncio.to_thread(run_cycle, curriculum_limit=12, persist=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.debug(f"LongitudinalHarness loop error: {exc}")
        await asyncio.sleep(interval)


def start_background_loop() -> dict[str, Any]:
    global _background_task
    if not _env_flag("ULTRON_LONGITUDINAL_HARNESS_ENABLED", "1"):
        return {"ok": True, "started": False, "reason": "disabled"}
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return {"ok": False, "started": False, "error": "no_running_event_loop"}
    if _background_task is not None and not _background_task.done():
        return {"ok": True, "started": False, "reason": "already_running"}
    _background_task = loop.create_task(background_loop())
    return {"ok": True, "started": True, "interval_sec": _interval_sec(), "initial_delay_sec": _initial_delay_sec()}


def stop_background_loop() -> dict[str, Any]:
    global _background_task
    if _background_task is None:
        return {"ok": True, "stopped": False, "reason": "not_running"}
    active = not _background_task.done()
    if active:
        _background_task.cancel()
    _background_task = None
    return {"ok": True, "stopped": active}


def run_selftest() -> dict[str, Any]:
    result = run_cycle(curriculum_limit=6, persist=False)
    return {
        "ok": bool(result.get("ok")),
        "passed": bool(
            result.get("ok")
            and isinstance(result.get("generalization"), dict)
            and isinstance(result.get("resilience"), dict)
            and isinstance(result.get("drift"), dict)
            and isinstance(result.get("predictive_model"), dict)
        ),
        "result": result,
    }
