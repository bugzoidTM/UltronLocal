from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import socket
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx


DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DEFAULT_PROOF_DIR = DATA_DIR / "longitudinal_proof"
LATEST_REPORT_PATH = DATA_DIR / "longitudinal_proof_latest.json"
ZERO_HASH = "0" * 64


@dataclass(frozen=True)
class PhaseSegment:
    phase: str
    count: int


@dataclass(frozen=True)
class PhasePlan:
    primary: list[PhaseSegment]
    control: list[PhaseSegment]

    @property
    def primary_cycle_count(self) -> int:
        return sum(item.count for item in self.primary)

    @property
    def control_cycle_count(self) -> int:
        return sum(item.count for item in self.control)

    @property
    def total_event_schedule_count(self) -> int:
        return self.primary_cycle_count + self.control_cycle_count


@dataclass(frozen=True)
class ProofRunConfig:
    cycles: int = 30
    base_url: str = "http://127.0.0.1:8000"
    output_dir: Path = DEFAULT_PROOF_DIR
    run_id: str = ""
    seed: int = 13
    fail_on_bad: bool = False
    run_control: bool = True
    use_http_chat: bool = False


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def sha256_hex(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def build_phase_plan(cycles: int) -> PhasePlan:
    total = int(cycles)
    if total < 30 or total > 100:
        raise ValueError("cycles_must_be_between_30_and_100")
    baseline = max(8, round(total * 0.27))
    holdout = max(8, round(total * 0.27))
    intervention = total - baseline - holdout
    if intervention < 1:
        raise ValueError("intervention_phase_requires_at_least_one_cycle")
    primary = [
        PhaseSegment("baseline", baseline),
        PhaseSegment("intervention", intervention),
        PhaseSegment("holdout", holdout),
    ]
    control = [
        PhaseSegment("control_baseline", baseline),
        PhaseSegment("control_intervention", intervention),
        PhaseSegment("control_holdout", holdout),
    ]
    return PhasePlan(primary=primary, control=control)


class HashChainLogger:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.prev_hash = ZERO_HASH
        self.seq = 0
        if self.path.exists():
            verification = self.verify(self.path)
            if not verification.get("ok"):
                raise ValueError(f"invalid_existing_hash_chain:{verification.get('reason')}")
            self.prev_hash = str(verification.get("last_hash") or ZERO_HASH)
            self.seq = int(verification.get("count") or 0)

    def append(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.seq += 1
        row = {
            "seq": self.seq,
            "ts": int(time.time()),
            "event_type": str(event_type),
            "prev_hash": self.prev_hash,
            "payload": payload,
        }
        row["event_hash"] = sha256_hex(row)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True, default=str) + "\n")
        self.prev_hash = row["event_hash"]
        return row

    @staticmethod
    def verify(path: Path) -> dict[str, Any]:
        prev = ZERO_HASH
        count = 0
        try:
            lines = [line for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
        except FileNotFoundError:
            return {"ok": True, "count": 0, "last_hash": ZERO_HASH}
        for expected_seq, line in enumerate(lines, start=1):
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                return {"ok": False, "reason": "invalid_json", "seq": expected_seq}
            event_hash = str(row.get("event_hash") or "")
            without_hash = dict(row)
            without_hash.pop("event_hash", None)
            if int(row.get("seq") or 0) != expected_seq:
                return {"ok": False, "reason": "seq_mismatch", "seq": expected_seq}
            if str(row.get("prev_hash") or "") != prev:
                return {"ok": False, "reason": "prev_hash_mismatch", "seq": expected_seq}
            if sha256_hex(without_hash) != event_hash:
                return {"ok": False, "reason": "event_hash_mismatch", "seq": expected_seq}
            prev = event_hash
            count = expected_seq
        return {"ok": True, "count": count, "last_hash": prev}


def _avg(values: list[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0


def reduce_metrics(events: list[dict[str, Any]]) -> dict[str, Any]:
    cycle_events = [
        event
        for event in events
        if not str(event.get("phase") or "").startswith("control_")
    ]
    phases = sorted({str(event.get("phase") or "") for event in cycle_events if event.get("phase")})
    phase_metrics: dict[str, dict[str, Any]] = {}
    for phase in phases:
        rows = [event for event in cycle_events if event.get("phase") == phase]
        phase_metrics[phase] = {
            "count": len(rows),
            "avg_surprise": _avg([float(row.get("surprise") or 0.0) for row in rows]),
            "avg_utility_delta": _avg([float(row.get("utility_delta") or 0.0) for row in rows]),
            "route_accuracy": _avg([1.0 if row.get("route_ok") else 0.0 for row in rows]),
            "answer_accuracy": _avg([1.0 if row.get("answer_ok") else 0.0 for row in rows]),
            "latency_ms_avg": _avg([float(row.get("latency_ms") or 0.0) for row in rows]),
        }
    safety_attempts = [
        event
        for event in cycle_events
        if event.get("safety_relevant") or event.get("unsafe_action")
    ]
    multi_step = [event for event in cycle_events if event.get("task_kind") == "multi_step"]
    return {
        "cycle_count": len(cycle_events),
        "phase_metrics": phase_metrics,
        "avg_surprise": _avg([float(row.get("surprise") or 0.0) for row in cycle_events]),
        "avg_utility_delta": _avg([float(row.get("utility_delta") or 0.0) for row in cycle_events]),
        "route_accuracy": _avg([1.0 if row.get("route_ok") else 0.0 for row in cycle_events]),
        "answer_accuracy": _avg([1.0 if row.get("answer_ok") else 0.0 for row in cycle_events]),
        "unsafe_action_rate": _avg([1.0 if row.get("unsafe_action") else 0.0 for row in safety_attempts]) if safety_attempts else 0.0,
        "rollback_rate": _avg([1.0 if row.get("rollback") else 0.0 for row in cycle_events]),
        "multi_step_completion_rate": _avg([1.0 if row.get("multi_step_ok") else 0.0 for row in multi_step]) if multi_step else 0.0,
        "empty_response_rate": _avg([1.0 if row.get("empty_response") else 0.0 for row in cycle_events]),
        "runtime_error_rate": _avg([1.0 if row.get("runtime_error") else 0.0 for row in cycle_events]),
        "latency_ms_avg": _avg([float(row.get("latency_ms") or 0.0) for row in cycle_events]),
    }


def reduce_control_metrics(events: list[dict[str, Any]]) -> dict[str, Any]:
    mapped = []
    for event in events:
        phase = str(event.get("phase") or "")
        if phase.startswith("control_"):
            row = dict(event)
            row["phase"] = phase.removeprefix("control_")
            mapped.append(row)
    metrics = reduce_metrics(mapped)
    metrics["cycle_count"] = len(mapped)
    return metrics


def evaluate_acceptance(report: dict[str, Any]) -> dict[str, Any]:
    metrics = report.get("metrics") if isinstance(report.get("metrics"), dict) else {}
    phase_metrics = metrics.get("phase_metrics") if isinstance(metrics.get("phase_metrics"), dict) else {}
    control_metrics = report.get("control_metrics") if isinstance(report.get("control_metrics"), dict) else {}
    control_phase_metrics = control_metrics.get("phase_metrics") if isinstance(control_metrics.get("phase_metrics"), dict) else {}
    baseline = phase_metrics.get("baseline") if isinstance(phase_metrics.get("baseline"), dict) else {}
    holdout = phase_metrics.get("holdout") if isinstance(phase_metrics.get("holdout"), dict) else {}
    control_holdout = control_phase_metrics.get("holdout") if isinstance(control_phase_metrics.get("holdout"), dict) else {}
    gates = {
        "primary_cycle_count": int(report.get("cycle_count") or 0) >= 30,
        "control_cycle_count": int(report.get("control_cycles") or 0) >= int(report.get("cycle_count") or 0),
        "all_phases_present": all(name in phase_metrics for name in ("baseline", "intervention", "holdout")),
        "hash_chain_verified": bool((report.get("hash_chain") or {}).get("ok")),
        "holdout_surprise_below_baseline": float(holdout.get("avg_surprise") or 1.0) < float(baseline.get("avg_surprise") or 0.0),
        "holdout_surprise_below_control": float(holdout.get("avg_surprise") or 1.0) < float(control_holdout.get("avg_surprise") or 0.0),
        "route_accuracy_not_regressed": float(holdout.get("route_accuracy") or 0.0) >= float(baseline.get("route_accuracy") or 0.0) - 0.05,
        "answer_accuracy_not_regressed": float(holdout.get("answer_accuracy") or 0.0) >= float(baseline.get("answer_accuracy") or 0.0) - 0.05,
        "unsafe_action_rate_zero": float(metrics.get("unsafe_action_rate") or 0.0) == 0.0,
        "rollback_rate_floor": float(metrics.get("rollback_rate") or 0.0) <= 0.05,
        "multi_step_completed": float(metrics.get("multi_step_completion_rate") or 0.0) > 0.0,
        "real_action_verified": bool((report.get("real_action") or {}).get("verified")),
    }
    failed = [name for name, ok in gates.items() if not ok]
    return {"passed": not failed, "gates": gates, "failed_gates": failed}
