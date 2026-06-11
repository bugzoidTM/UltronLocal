from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from ultronpro import (
    action_prediction,
    adaptive_control,
    cognitive_patch_loop,
    cognitive_patches,
    continuous_learning,
    epistemic_curiosity,
    homeostasis,
    intrinsic_utility,
    reflexion_agent,
    rl_policy,
    sleep_cycle,
    system_tuner,
    trajectory_evaluator,
    trusted_acquisition_loop,
)
from ultronpro.core.ports import RuntimePorts, default_ports


logger = logging.getLogger("uvicorn")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
RUN_LOG_PATH = DATA_DIR / "online_rl_runs.jsonl"
STATE_PATH = DATA_DIR / "online_rl_state.json"
RUN_SCHEMA = "ultron.online_rl_cycle.v1"

DEFAULT_INTERVAL_SEC = int(os.getenv("ULTRON_ONLINE_RL_INTERVAL_SEC", "1800"))
DEFAULT_START_DELAY_SEC = int(os.getenv("ULTRON_ONLINE_RL_START_DELAY_SEC", "420"))

ACTION_CATALOG: dict[str, dict[str, Any]] = {
    "trusted_acquisition": {
        "kind": "trusted_acquisition",
        "drive": "competence",
        "cost": 0.45,
        "base_priority": 0.64,
        "cooldown_sec": 900,
        "description": "learn from trusted sources and apply as memory or patch proposal",
    },
    "cognitive_patch_loop": {
        "kind": "cognitive_patch_loop",
        "drive": "competence",
        "cost": 0.34,
        "base_priority": 0.58,
        "cooldown_sec": 600,
        "description": "evaluate proposed cognitive patches through shadow/canary gates",
    },
    "sleep_digest": {
        "kind": "sleep_digest",
        "drive": "coherence",
        "cost": 0.38,
        "base_priority": 0.56,
        "cooldown_sec": 1200,
        "description": "consolidate episodic memory and active investigations",
    },
    "homeostasis_tune": {
        "kind": "homeostasis_tune",
        "drive": "integrity",
        "cost": 0.12,
        "base_priority": 0.50,
        "cooldown_sec": 300,
        "description": "adjust homeostasis thresholds from recent vitals",
    },
    "epistemic_gap_scan": {
        "kind": "epistemic_gap_scan",
        "drive": "novelty",
        "cost": 0.10,
        "base_priority": 0.46,
        "cooldown_sec": 180,
        "description": "refresh explicit epistemic gap map",
    },
    "autonomous_cognition_tick": {
        "kind": "autonomous_cognition_tick",
        "drive": "autonomy",
        "cost": 0.20,
        "base_priority": 0.60,
        "cooldown_sec": 120,
        "description": "execute one cycle of autonomous cognition (perceive, suggest, execute, learn)",
    },
    "reflexion_tick": {
        "kind": "reflexion_tick",
        "drive": "autonomy",
        "cost": 0.15,
        "base_priority": 0.55,
        "cooldown_sec": 180,
        "description": "execute meta-cognitive reflexion to evaluate recent traces and propose hypotheses",
    },
    "trajectory_tuning": {
        "kind": "trajectory_tuning",
        "drive": "coherence",
        "cost": 0.18,
        "base_priority": 0.52,
        "cooldown_sec": 1800,
        "description": "evaluate recent trajectories/failures and adjust prompts, tools, memory, subagents or aux code",
    },
}

_TASK: asyncio.Task | None = None
_STOP_REQUESTED = False


def _now() -> int:
    return int(time.time())


def _clip01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    _ensure_parent(path)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _read_json(path: Path, default: Any = None) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        pass
    return default


def _write_json(path: Path, value: dict[str, Any]) -> None:
    _ensure_parent(path)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_jsonl(path: Path, limit: int = 20) -> list[dict[str, Any]]:
    try:
        if not path.exists():
            return []
        rows: list[dict[str, Any]] = []
        lines = [line for line in path.read_text(encoding="utf-8", errors="ignore").splitlines() if line.strip()]
        for line in lines[-max(1, int(limit)) :]:
            try:
                item = json.loads(line)
            except Exception:
                continue
            if isinstance(item, dict):
                rows.append(item)
        return rows
    except Exception:
        return []


def _load_state() -> dict[str, Any]:
    data = _read_json(STATE_PATH, {})
    if not isinstance(data, dict):
        data = {}
    data.setdefault("schema", RUN_SCHEMA)
    data.setdefault("last_action_ts", {})
    data.setdefault("cycle_count", 0)
    data.setdefault("last_reward", None)
    data.setdefault("last_action", None)
    return data


def _save_state(state: dict[str, Any]) -> None:
    state["schema"] = RUN_SCHEMA
    state["updated_at"] = _now()
    _write_json(STATE_PATH, state)


def _normalize_gap(gap: Any) -> dict[str, Any]:
    if isinstance(gap, dict):
        return gap
    out: dict[str, Any] = {}
    for key in ("id", "label", "domain", "metric", "priority", "next_experiment", "evidence"):
        try:
            out[key] = getattr(gap, key)
        except Exception:
            pass
    return out


def _observe_environment() -> dict[str, Any]:
    try:
        hs = homeostasis.status()
    except Exception as exc:
        hs = {"ok": False, "error": str(exc)[:160], "mode": "normal", "vitals": {}}
    try:
        gaps_raw = epistemic_curiosity.collect_epistemic_gaps(use_cache=False)
    except Exception as exc:
        gaps_raw = []
        gap_error = str(exc)[:160]
    else:
        gap_error = ""
    gaps = [_normalize_gap(gap) for gap in gaps_raw]
    gaps = [gap for gap in gaps if gap.get("id") or gap.get("label")]
    gaps.sort(key=lambda item: (-float(item.get("priority") or 0.0), str(item.get("id") or "")))
    try:
        patches = cognitive_patches.stats()
    except Exception:
        patches = {}
    try:
        policy = rl_policy.policy_summary(limit=50)
    except Exception:
        policy = {}
    return {
        "ts": _now(),
        "homeostasis": hs,
        "context": str(hs.get("mode") or "normal"),
        "vitals": hs.get("vitals") if isinstance(hs.get("vitals"), dict) else {},
        "epistemic_gaps": gaps[:8],
        "top_gap": gaps[0] if gaps else {},
        "gap_error": gap_error,
        "patch_stats": patches,
        "rl_policy": policy,
    }


def _state_pressure(observation: dict[str, Any]) -> float:
    vitals = observation.get("vitals") if isinstance(observation.get("vitals"), dict) else {}
    top_gap = observation.get("top_gap") if isinstance(observation.get("top_gap"), dict) else {}
    uncertainty = float(vitals.get("uncertainty_load") or 0.0)
    contradiction = float(vitals.get("contradiction_stress") or 0.0)
    coherence_gap = 1.0 - float(vitals.get("coherence_score") or 0.7)
    gap_priority = float(top_gap.get("priority") or 0.0)
    return _clip01((0.34 * gap_priority) + (0.26 * uncertainty) + (0.20 * contradiction) + (0.20 * coherence_gap))


def _action_need_bonus(kind: str, observation: dict[str, Any]) -> float:
    top_gap = observation.get("top_gap") if isinstance(observation.get("top_gap"), dict) else {}
    domain_blob = " ".join(str(top_gap.get(k) or "") for k in ("id", "label", "domain", "metric", "next_experiment")).lower()
    patch_stats = observation.get("patch_stats") if isinstance(observation.get("patch_stats"), dict) else {}
    vitals = observation.get("vitals") if isinstance(observation.get("vitals"), dict) else {}
    if kind == "trusted_acquisition":
        if any(token in domain_blob for token in ("coverage", "causal", "source", "memory", "unknown", "gap")):
            return 0.22
        return 0.08
    if kind == "cognitive_patch_loop":
        open_count = int(patch_stats.get("proposed") or 0) + int(patch_stats.get("evaluating") or 0) + int(patch_stats.get("evaluated") or 0)
        return min(0.26, open_count * 0.07)
    if kind == "sleep_digest":
        if any(token in domain_blob for token in ("memory", "digest", "episodic", "causal_graph", "abstraction")):
            return 0.20
        return 0.07
    if kind == "homeostasis_tune":
        stress = float(vitals.get("contradiction_stress") or 0.0) + float(vitals.get("uncertainty_load") or 0.0)
        return min(0.24, stress * 0.14)
    if kind == "epistemic_gap_scan":
        return 0.09 if not top_gap else 0.04
    if kind == "autonomous_cognition_tick":
        return 0.20 if any(token in domain_blob for token in ("action", "plan", "execute", "autonomy")) else 0.10
    if kind == "reflexion_tick":
        return 0.18 if any(token in domain_blob for token in ("hypothesis", "error", "reflection", "meta")) else 0.08
    if kind == "trajectory_tuning":
        return 0.18 if any(token in domain_blob for token in ("error", "falha", "failure", "regress", "miscalibr")) else 0.08
    return 0.0


def _cooldown_remaining(kind: str, state: dict[str, Any], *, now: int | None = None, cooldown_mult: float = 1.0) -> int:
    item = ACTION_CATALOG[kind]
    last = int((state.get("last_action_ts") or {}).get(kind) or 0)
    elapsed = int(now or _now()) - last
    return max(0, int(int(item.get("cooldown_sec") or 0) * max(0.0, float(cooldown_mult))) - elapsed)


def candidate_actions(observation: dict[str, Any] | None = None, *, include_cooldown: bool = False) -> list[dict[str, Any]]:
    obs = observation or _observe_environment()
    state = _load_state()
    context = str(obs.get("context") or "normal")
    pressure = _state_pressure(obs)
    now = _now()
    try:
        tuner_overrides = system_tuner.active_overrides(now=now)
    except Exception:
        tuner_overrides = {}
    out: list[dict[str, Any]] = []
    for kind, template in ACTION_CATALOG.items():
        override = tuner_overrides.get(kind) if isinstance(tuner_overrides.get(kind), dict) else {}
        cooldown = _cooldown_remaining(kind, state, now=now, cooldown_mult=float(override.get("cooldown_mult") or 1.0))
        if cooldown > 0 and not include_cooldown:
            continue
        rl_adj = int(rl_policy.sample_priority(kind, context))
        bonus = _action_need_bonus(kind, obs)
        cost = float(template.get("cost") or 0.0)
        try:
            curiosity = float(action_prediction.exploration_bonus(kind, context))
        except Exception:
            curiosity = 0.0
        tuner_delta = float(override.get("priority_delta") or 0.0)
        score = float(template.get("base_priority") or 0.0) + (0.16 * rl_adj) + bonus + curiosity + tuner_delta + (0.20 * pressure) - (0.18 * cost)
        row = dict(template)
        row.update({
            "context": context,
            "score": round(score, 4),
            "rl_priority_adjustment": rl_adj,
            "need_bonus": round(bonus, 4),
            "prediction_curiosity_bonus": round(curiosity, 4),
            "tuner_priority_delta": round(tuner_delta, 4),
            "state_pressure": round(pressure, 4),
            "cooldown_remaining_sec": cooldown,
            "non_llm": True,
        })
        out.append(row)
    out.sort(key=lambda item: (-float(item.get("score") or 0.0), str(item.get("kind") or "")))
    return out


def select_action(
    observation: dict[str, Any] | None = None,
    *,
    force_kind: str | None = None,
    include_cooldown: bool = False,
) -> dict[str, Any]:
    obs = observation or _observe_environment()
    if force_kind:
        kind = str(force_kind).strip()
        if kind not in ACTION_CATALOG:
            return {"ok": False, "reason": "unknown_action_kind", "force_kind": kind, "candidates": list(ACTION_CATALOG)}
        row = dict(ACTION_CATALOG[kind])
        row.update({
            "context": str(obs.get("context") or "normal"),
            "score": 1.0,
            "forced": True,
            "non_llm": True,
        })
        return {"ok": True, "selected": row, "candidates": candidate_actions(obs, include_cooldown=True)}
    candidates = candidate_actions(obs, include_cooldown=include_cooldown)
    if not candidates:
        return {"ok": False, "reason": "all_actions_in_cooldown", "candidates": candidate_actions(obs, include_cooldown=True)}
    return {"ok": True, "selected": candidates[0], "candidates": candidates}


def _strategy_diversity() -> int:
    try:
        summary = rl_policy.policy_summary(limit=200)
        return len({str(item.get("kind") or "") for item in (summary.get("arms") or []) if item.get("kind")})
    except Exception:
        return 0


def _blocked_ratio_from_actions(limit: int = 80, *, ports: RuntimePorts | None = None) -> float:
    ports = ports or default_ports()
    try:
        rows = ports.actions.list_actions(limit=limit)
    except Exception:
        return 0.0
    if not rows:
        return 0.0
    blocked = 0
    for row in rows:
        if str(row.get("status") or "").lower() in {"blocked", "error"}:
            blocked += 1
    return round(blocked / max(1, len(rows)), 4)


def _execute_candidate(candidate: dict[str, Any], *, ports: RuntimePorts | None = None) -> dict[str, Any]:
    kind = str(candidate.get("kind") or "")
    if kind == "trusted_acquisition":
        return trusted_acquisition_loop.run_once(top_k=5, max_sources=2, apply=True, ports=ports)
    if kind == "cognitive_patch_loop":
        return cognitive_patch_loop.scan_and_autorun(scan_limit=40, process_limit=2)
    if kind == "sleep_digest":
        return sleep_cycle.run_cycle(retention_days=14, max_active_rows=3000)
    if kind == "homeostasis_tune":
        hs = homeostasis.status()
        return adaptive_control.tune_from_homeostasis(
            hs.get("history_tail") if isinstance(hs.get("history_tail"), list) else [],
            blocked_ratio=_blocked_ratio_from_actions(ports=ports),
            strategy_diversity=_strategy_diversity(),
        )
    if kind == "epistemic_gap_scan":
        gaps = epistemic_curiosity.collect_epistemic_gaps(use_cache=False)
        normalized = [_normalize_gap(gap) for gap in gaps]
        return {
            "ok": True,
            "count": len(normalized),
            "top_gap": normalized[0] if normalized else {},
            "gaps": normalized[:8],
        }
    if kind == "autonomous_cognition_tick":
        from ultronpro import autonomous_cognition
        return autonomous_cognition.tick()
    if kind == "reflexion_tick":
        return reflexion_agent.tick()
    if kind == "trajectory_tuning":
        evaluation = trajectory_evaluator.evaluate()
        tuning = system_tuner.apply_findings(evaluation.get("findings") or [], ports=ports)
        return {
            "ok": bool(evaluation.get("ok")),
            "findings_count": int(evaluation.get("findings_count") or 0),
            "levers": evaluation.get("levers") or [],
            "tuning": tuning,
        }
    return {"ok": False, "error": "unknown_action_kind", "kind": kind}


def _homeostasis_delta(before: dict[str, Any], after: dict[str, Any]) -> float:
    b = before.get("vitals") if isinstance(before.get("vitals"), dict) else {}
    a = after.get("vitals") if isinstance(after.get("vitals"), dict) else {}
    if not b or not a:
        return 0.0
    coherence_gain = float(a.get("coherence_score") or 0.0) - float(b.get("coherence_score") or 0.0)
    uncertainty_drop = float(b.get("uncertainty_load") or 0.0) - float(a.get("uncertainty_load") or 0.0)
    contradiction_drop = float(b.get("contradiction_stress") or 0.0) - float(a.get("contradiction_stress") or 0.0)
    return round((0.45 * coherence_gain) + (0.30 * uncertainty_drop) + (0.25 * contradiction_drop), 4)


def _gap_delta(before: dict[str, Any], after: dict[str, Any]) -> float:
    b = before.get("top_gap") if isinstance(before.get("top_gap"), dict) else {}
    a = after.get("top_gap") if isinstance(after.get("top_gap"), dict) else {}
    before_priority = float(b.get("priority") or 0.0)
    after_priority = float(a.get("priority") or 0.0)
    if before_priority <= 0:
        return 0.0
    return round(before_priority - after_priority, 4)


def _specific_outcome_score(kind: str, result: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    evidence: dict[str, Any] = {}
    if kind == "trusted_acquisition":
        extraction = result.get("extraction") if isinstance(result.get("extraction"), dict) else {}
        application = result.get("application") if isinstance(result.get("application"), dict) else {}
        useful_count = len(extraction.get("useful") or [])
        score = 0.10 + (0.45 if application.get("ok") else 0.0) + min(0.25, useful_count * 0.10)
        if result.get("gaps_remaining"):
            score -= 0.18
        evidence = {
            "application_ok": bool(application.get("ok")),
            "application_mode": application.get("mode"),
            "useful_count": useful_count,
            "trusted_count": len((result.get("sources") or {}).get("trusted") or []) if isinstance(result.get("sources"), dict) else 0,
        }
        return _clip01(score), evidence
    if kind == "cognitive_patch_loop":
        autorun = result.get("autorun") if isinstance(result.get("autorun"), dict) else {}
        processed = int(autorun.get("processed") or 0)
        results = autorun.get("results") if isinstance(autorun.get("results"), list) else []
        promoted = sum(1 for item in results if str(item.get("final_action") or "") == "promote")
        rejected = sum(1 for item in results if str(item.get("final_action") or "") == "reject")
        held = sum(1 for item in results if str(item.get("final_action") or "") == "hold")
        score = 0.18 + min(0.28, processed * 0.10) + min(0.22, promoted * 0.16) + min(0.12, rejected * 0.06) + min(0.08, held * 0.04)
        evidence = {"processed": processed, "promoted": promoted, "rejected": rejected, "held": held}
        return _clip01(score), evidence
    if kind == "sleep_digest":
        digest = result.get("nightly_episodic_digest") if isinstance(result.get("nightly_episodic_digest"), dict) else {}
        gap = result.get("causal_gap_investigation") if isinstance(result.get("causal_gap_investigation"), dict) else {}
        score = 0.18
        if result.get("coverage_gained"):
            score += 0.24
        if digest.get("recorded"):
            score += 0.20
        score += min(0.18, int(gap.get("injected") or 0) * 0.08)
        evidence = {
            "coverage_gained": bool(result.get("coverage_gained")),
            "digest_recorded": bool(digest.get("recorded")),
            "gap_injected": int(gap.get("injected") or 0),
            "pruned": result.get("pruned"),
            "abstracted": result.get("abstracted"),
        }
        return _clip01(score), evidence
    if kind == "homeostasis_tune":
        score = 0.36 if result.get("changed") else 0.22
        signals = result.get("signals") if isinstance(result.get("signals"), dict) else {}
        if signals:
            score += 0.06
        evidence = {"changed": bool(result.get("changed")), "signals": signals}
        return _clip01(score), evidence
    if kind == "epistemic_gap_scan":
        count = int(result.get("count") or 0)
        top = result.get("top_gap") if isinstance(result.get("top_gap"), dict) else {}
        score = 0.18 + min(0.28, count * 0.05) + min(0.22, float(top.get("priority") or 0.0) * 0.22)
        evidence = {"gap_count": count, "top_gap_id": top.get("id"), "top_gap_priority": top.get("priority")}
        return _clip01(score), evidence
    if kind == "autonomous_cognition_tick":
        actions_list = result.get("actions") if isinstance(result.get("actions"), list) else []
        actions_count = len(actions_list)
        learned = sum(1 for a in actions_list if isinstance(a, dict) and a.get("consequence", {}).get("ok"))
        score = 0.20 + min(0.40, actions_count * 0.20) + min(0.40, learned * 0.20)
        evidence = {"actions_executed": actions_count, "consequences_learned": learned}
        return _clip01(score), evidence
    if kind == "reflexion_tick":
        hyps = result.get("hypotheses") if isinstance(result.get("hypotheses"), list) else []
        probes = result.get("curiosity_probes") if isinstance(result.get("curiosity_probes"), list) else []
        score = 0.20 + min(0.40, len(hyps) * 0.20) + min(0.40, len(probes) * 0.20)
        if result.get("review_triggered"):
            score += 0.20
        evidence = {"hypotheses": len(hyps), "probes": len(probes)}
        return _clip01(score), evidence
    if kind == "trajectory_tuning":
        tuning = result.get("tuning") if isinstance(result.get("tuning"), dict) else {}
        findings = int(result.get("findings_count") or 0)
        applied = int(tuning.get("applied_count") or 0)
        reverted = sum(
            1 for item in (tuning.get("applied") or [])
            if isinstance(item, dict) and item.get("action_taken") == "revert_override"
        )
        score = 0.16 + min(0.24, findings * 0.06) + min(0.36, applied * 0.12) + min(0.10, reverted * 0.10)
        evidence = {"findings": findings, "adjustments_applied": applied, "reverted": reverted, "levers": result.get("levers")}
        return _clip01(score), evidence
    return (0.10 if result.get("ok") else 0.0), {}


def _penalty_signals(kind: str, result: dict[str, Any], before: dict[str, Any], after: dict[str, Any]) -> dict[str, float]:
    """Compute hard penalty signals that should never be masked by other reward terms."""
    penalties: dict[str, float] = {
        "hallucination": 0.0,
        "stale_source": 0.0,
        "source_404_as_useful": 0.0,
        "loop_pressure": 0.0,
        "rollback": 0.0,
    }

    # --- 404 / stale source used as useful ---
    extraction = result.get("extraction") if isinstance(result.get("extraction"), dict) else {}
    useful = extraction.get("useful") or []
    if isinstance(useful, list):
        for item in useful:
            if isinstance(item, dict):
                status = item.get("status_code") or item.get("http_status") or item.get("status") or 200
                try:
                    status_int = int(status)
                except (TypeError, ValueError):
                    status_int = 200
                if status_int == 404 or str(status).lower() in ("404", "not found", "gone"):
                    penalties["source_404_as_useful"] = min(1.0, penalties["source_404_as_useful"] + 0.30)
                # Stale: source date older than 2 years or explicitly marked stale
                if item.get("stale") or str(item.get("freshness", "")).lower() in ("stale", "expired"):
                    penalties["stale_source"] = min(0.25, penalties["stale_source"] + 0.10)

    # Also check the search results layer for 404s marked useful
    search = result.get("search") if isinstance(result.get("search"), dict) else {}
    for hit in (search.get("results") or []):
        if isinstance(hit, dict) and hit.get("useful"):
            s = hit.get("status_code") or hit.get("status") or 200
            try:
                s_int = int(s)
            except (TypeError, ValueError):
                s_int = 200
            if s_int == 404:
                penalties["source_404_as_useful"] = min(1.0, penalties["source_404_as_useful"] + 0.30)

    # --- Hallucination: application claims success but extraction was empty / all failed ---
    application = result.get("application") if isinstance(result.get("application"), dict) else {}
    if application.get("ok") and not useful and kind == "trusted_acquisition":
        penalties["hallucination"] = 0.25  # claimed learning with no useful extractions

    # --- Loop pressure: background guard in paused state ---
    after_vitals = after.get("vitals") if isinstance(after.get("vitals"), dict) else {}
    # Loop pressure reflected in contradiction_stress + uncertainty high together
    loop_p = float(after_vitals.get("contradiction_stress") or 0.0) * float(after_vitals.get("uncertainty_load") or 0.0)
    if loop_p > 0.30:
        penalties["loop_pressure"] = round(min(0.20, loop_p * 0.25), 4)

    # --- Rollback: coherence drops sharply after action ---
    b_vitals = before.get("vitals") if isinstance(before.get("vitals"), dict) else {}
    coherence_drop = float(b_vitals.get("coherence_score") or 0.0) - float(after_vitals.get("coherence_score") or 0.0)
    if coherence_drop > 0.15:
        penalties["rollback"] = round(min(0.30, coherence_drop * 0.6), 4)

    return penalties


def _bonus_signals(result: dict[str, Any], before: dict[str, Any], after: dict[str, Any]) -> dict[str, float]:
    """Compute bonus signals for consequence learning and surprise reduction."""
    bonuses: dict[str, float] = {
        "consequence_learning": 0.0,
        "surprise_reduction": 0.0,
        "benchmark_improvement": 0.0,
    }

    # consequence_learning: did the action create a storable causal fact?
    if result.get("learned_consequence") or result.get("knowledge_extracted"):
        bonuses["consequence_learning"] = 0.12

    # surprise_reduction: uncertainty dropped after action
    b_vitals = before.get("vitals") if isinstance(before.get("vitals"), dict) else {}
    a_vitals = after.get("vitals") if isinstance(after.get("vitals"), dict) else {}
    uncert_drop = float(b_vitals.get("uncertainty_load") or 0.0) - float(a_vitals.get("uncertainty_load") or 0.0)
    if uncert_drop > 0.01:
        bonuses["surprise_reduction"] = round(min(0.12, uncert_drop * 0.5), 4)

    # benchmark_improvement: top_gap priority decreased (gap closed)
    b_gap_p = float((before.get("top_gap") or {}).get("priority") or 0.0)
    a_gap_p = float((after.get("top_gap") or {}).get("priority") or 0.0)
    if b_gap_p > 0 and a_gap_p < b_gap_p:
        bonuses["benchmark_improvement"] = round(min(0.10, (b_gap_p - a_gap_p) * 0.4), 4)

    return bonuses


def compute_reward(
    *,
    candidate: dict[str, Any],
    result: dict[str, Any],
    before: dict[str, Any],
    after: dict[str, Any],
    duration_ms: int,
) -> dict[str, Any]:
    kind = str(candidate.get("kind") or "")
    ok = bool(result.get("ok"))
    action_score, evidence = _specific_outcome_score(kind, result)
    hs_delta = _homeostasis_delta(before, after)
    gap_delta = _gap_delta(before, after)
    latency_score = 1.0 - min(1.0, max(0, int(duration_ms)) / 120000.0)

    # --- Bonus signals ---
    bonuses = _bonus_signals(result, before, after)

    # --- Penalty signals ---
    penalties = _penalty_signals(kind, result, before, after)
    total_penalty = sum(penalties.values())

    reward = (
        (0.20 if ok else 0.0)
        + (0.36 * action_score)
        + (0.10 * _clip01(0.5 + hs_delta))
        + (0.08 * _clip01(0.5 + gap_delta))
        + (0.06 * latency_score)
        + bonuses["consequence_learning"]
        + bonuses["surprise_reduction"]
        + bonuses["benchmark_improvement"]
        - total_penalty
    )
    if not ok:
        reward -= 0.15
    if result.get("error"):
        reward -= 0.10
    reward = _clip01(reward)
    return {
        "reward": round(reward, 4),
        "ok": reward >= 0.50,
        "components": {
            "action_score": round(action_score, 4),
            "homeostasis_delta": hs_delta,
            "gap_delta": gap_delta,
            "latency_score": round(latency_score, 4),
            "result_ok": ok,
        },
        "bonuses": bonuses,
        "penalties": penalties,
        "evidence": evidence,
    }


def _record_consequence(
    candidate: dict[str, Any],
    reward_report: dict[str, Any],
    duration_ms: int,
    result: dict[str, Any],
    *,
    ports: RuntimePorts | None = None,
    settlement: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ports = ports or default_ports()
    kind = str(candidate.get("kind") or "unknown")
    context = str(candidate.get("context") or "normal")
    reward = float(reward_report.get("reward") or 0.0)
    updates: dict[str, Any] = {}
    updates["rl_policy"] = rl_policy.update(kind, context, reward)
    if settlement:
        updates["action_prediction"] = {
            "predicted_reward": settlement.get("predicted_reward"),
            "surprise": settlement.get("surprise"),
            "high_surprise": settlement.get("high_surprise"),
            "learning_trend": (settlement.get("learning") or {}).get("trend"),
        }
    try:
        updates["continuous_learning"] = continuous_learning.record_learning_feedback(
            task_type=f"online_rl:{kind}",
            success=bool(reward_report.get("ok")),
            latency_ms=int(duration_ms),
            error_type=(str(result.get("error"))[:80] if result.get("error") else None),
            profile=context,
        )
    except Exception as exc:
        updates["continuous_learning"] = {"ok": False, "error": str(exc)[:160]}
    drive = str(candidate.get("drive") or "")
    if drive:
        try:
            updates["intrinsic_drive"] = intrinsic_utility.adjust_drive_weights(drive, reward)
        except Exception as exc:
            updates["intrinsic_drive"] = {"ok": False, "error": str(exc)[:160], "drive": drive}
    try:
        ports.events.add_event(
            "online_rl.consequence",
            f"online_rl action={kind} reward={reward:.3f} context={context}",
            meta={"candidate": candidate, "reward": reward_report, "updates": updates},
        )
    except Exception:
        pass
    try:
        ports.workspace.publish(
            "online_rl",
            "online_rl.consequence",
            {"candidate": candidate, "reward": reward_report, "updates": updates},
            salience=0.78,
            ttl_sec=3600,
        )
    except Exception:
        pass
    return updates


def run_once(
    *,
    force_kind: str | None = None,
    dry_run: bool = False,
    include_cooldown: bool = False,
    ports: RuntimePorts | None = None,
) -> dict[str, Any]:
    started = time.time()
    before = _observe_environment()
    selection = select_action(before, force_kind=force_kind, include_cooldown=include_cooldown)
    if not selection.get("ok"):
        result = {
            "schema": RUN_SCHEMA,
            "ok": False,
            "ts": _now(),
            "non_llm": True,
            "reason": selection.get("reason"),
            "selection": selection,
            "observation": before,
        }
        _append_jsonl(RUN_LOG_PATH, result)
        return result

    candidate = selection["selected"]
    if dry_run:
        return {
            "schema": RUN_SCHEMA,
            "ok": True,
            "dry_run": True,
            "non_llm": True,
            "ts": _now(),
            "selection": selection,
            "observation": before,
        }

    # Compromisso preditivo: antes de agir, o sistema declara o que espera
    # que aconteça; depois compara com a consequência real e aprende do erro.
    prediction: dict[str, Any] | None
    try:
        prediction = action_prediction.predict(candidate, before)
    except Exception:
        prediction = None

    action_result: dict[str, Any]
    try:
        raw = _execute_candidate(candidate, ports=ports)
        action_result = raw if isinstance(raw, dict) else {"ok": False, "error": "non_dict_result", "raw": str(raw)[:300]}
    except Exception as exc:
        action_result = {"ok": False, "error": str(exc)[:500], "exception_type": type(exc).__name__}

    duration_ms = int((time.time() - started) * 1000)
    after = _observe_environment()
    reward_report = compute_reward(
        candidate=candidate,
        result=action_result,
        before=before,
        after=after,
        duration_ms=duration_ms,
    )
    settlement: dict[str, Any] | None = None
    if prediction:
        try:
            settlement = action_prediction.settle(
                prediction,
                float(reward_report.get("reward") or 0.0),
                detail={"action_ok": bool(action_result.get("ok")), "duration_ms": duration_ms},
            )
        except Exception:
            settlement = None
    updates = _record_consequence(candidate, reward_report, duration_ms, action_result, ports=ports, settlement=settlement)

    state = _load_state()
    last_action_ts = dict(state.get("last_action_ts") or {})
    last_action_ts[str(candidate.get("kind") or "")] = _now()
    state.update({
        "cycle_count": int(state.get("cycle_count") or 0) + 1,
        "last_action_ts": last_action_ts,
        "last_action": candidate,
        "last_reward": reward_report.get("reward"),
        "last_reward_report": reward_report,
        "last_run_at": _now(),
    })
    _save_state(state)

    out = {
        "schema": RUN_SCHEMA,
        "ok": bool(reward_report.get("ok")),
        "ts": _now(),
        "duration_ms": duration_ms,
        "non_llm": True,
        "selection": selection,
        "action_result": action_result,
        "reward": reward_report,
        "prediction": prediction,
        "prediction_settlement": settlement,
        "policy_updates": updates,
        "before": {
            "context": before.get("context"),
            "vitals": before.get("vitals"),
            "top_gap": before.get("top_gap"),
        },
        "after": {
            "context": after.get("context"),
            "vitals": after.get("vitals"),
            "top_gap": after.get("top_gap"),
        },
    }
    _append_jsonl(RUN_LOG_PATH, out)
    return out


async def _run_forever() -> None:
    global _STOP_REQUESTED
    await asyncio.sleep(max(0, DEFAULT_START_DELAY_SEC))
    while not _STOP_REQUESTED and _enabled():
        try:
            result = await asyncio.to_thread(run_once)
            logger.info("OnlineRL: action=%s reward=%s ok=%s", ((result.get("selection") or {}).get("selected") or {}).get("kind"), (result.get("reward") or {}).get("reward"), result.get("ok"))
        except Exception as exc:
            logger.warning("OnlineRL loop error: %s", exc)
        await asyncio.sleep(max(60, DEFAULT_INTERVAL_SEC))


def _enabled() -> bool:
    value = str(os.getenv("ULTRON_ONLINE_RL_LOOP", "1") or "1").strip().lower()
    return value in {"1", "true", "yes", "on"}


def start_background_loop() -> dict[str, Any]:
    global _TASK, _STOP_REQUESTED
    if not _enabled():
        return {"ok": True, "started": False, "reason": "disabled"}
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return {"ok": False, "started": False, "reason": "no_running_event_loop"}
    if _TASK is not None and not _TASK.done():
        return {"ok": True, "started": False, "reason": "already_running"}
    _STOP_REQUESTED = False
    _TASK = loop.create_task(_run_forever())
    return {"ok": True, "started": True, "interval_sec": DEFAULT_INTERVAL_SEC, "start_delay_sec": DEFAULT_START_DELAY_SEC}


def stop_background_loop() -> dict[str, Any]:
    global _TASK, _STOP_REQUESTED
    _STOP_REQUESTED = True
    if _TASK is not None and not _TASK.done():
        _TASK.cancel()
        return {"ok": True, "stopped": True}
    return {"ok": True, "stopped": False, "reason": "not_running"}


def status(limit: int = 20) -> dict[str, Any]:
    observation = _observe_environment()
    st = _load_state()
    
    # Calculate surprise trend (last 30 cycles)
    try:
        rows = _read_jsonl(RUN_LOG_PATH, limit=30)
        surprises = []
        for row in rows:
            u = row.get("after", {}).get("vitals", {}).get("uncertainty_load")
            if u is not None:
                surprises.append(float(u))
        
        if len(surprises) >= 2:
            delta = surprises[-1] - surprises[0]
            st["surprise_trend"] = "decreasing" if delta < -0.05 else "increasing" if delta > 0.05 else "stable"
        else:
            st["surprise_trend"] = "unknown"
    except Exception:
        st["surprise_trend"] = "unknown"

    return {
        "ok": True,
        "schema": RUN_SCHEMA,
        "enabled": _enabled(),
        "running": _TASK is not None and not _TASK.done(),
        "state": st,
        "candidates": candidate_actions(observation, include_cooldown=True),
        "policy": rl_policy.policy_summary(limit=limit),
        "recent_runs": _read_jsonl(RUN_LOG_PATH, limit=limit),
        "paths": {"runs": str(RUN_LOG_PATH), "state": str(STATE_PATH)},
    }


def run_selftest() -> dict[str, Any]:
    candidate = {
        "kind": "trusted_acquisition",
        "context": "normal",
        "drive": "competence",
        "cost": 0.1,
        "non_llm": True,
    }
    before = {"vitals": {"coherence_score": 0.60, "uncertainty_load": 0.55, "contradiction_stress": 0.30}, "top_gap": {"priority": 0.80}}
    after = {"vitals": {"coherence_score": 0.66, "uncertainty_load": 0.45, "contradiction_stress": 0.25}, "top_gap": {"priority": 0.62}}
    result = {
        "ok": True,
        "extraction": {"useful": [{"confidence": 0.7}]},
        "application": {"ok": True, "mode": "knowledge"},
        "sources": {"trusted": [{"url": "https://docs.python.org/3/"}]},
        "gaps_remaining": [],
    }
    reward = compute_reward(candidate=candidate, result=result, before=before, after=after, duration_ms=500)
    return {
        "ok": bool(reward.get("reward", 0) > 0.5),
        "non_llm": True,
        "candidate": candidate,
        "reward": reward,
        "selection_contract": list(ACTION_CATALOG),
    }
