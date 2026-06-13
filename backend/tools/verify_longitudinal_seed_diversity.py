#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from ultronpro.longitudinal_runner import HashChainLogger

DEFAULT_BASE_DIR = BACKEND_DIR / "data" / "longitudinal_proof"


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _report_seed(report: dict[str, Any]) -> int | None:
    manifest = report.get("manifest") if isinstance(report.get("manifest"), dict) else {}
    seed_effectiveness = report.get("seed_effectiveness") if isinstance(report.get("seed_effectiveness"), dict) else {}
    value = manifest.get("seed", seed_effectiveness.get("seed"))
    try:
        return int(value)
    except Exception:
        return None


def _sequence_hash(report: dict[str, Any]) -> str:
    manifest = report.get("manifest") if isinstance(report.get("manifest"), dict) else {}
    return str(report.get("task_sequence_hash") or manifest.get("task_sequence_hash") or "")


def _hash_chain_ok(report: dict[str, Any]) -> bool:
    verified = report.get("_verified_hash_chain")
    if isinstance(verified, dict):
        return bool(verified.get("ok"))
    hash_chain = report.get("hash_chain") if isinstance(report.get("hash_chain"), dict) else {}
    return bool(hash_chain.get("ok"))


def _phase_metric(report: dict[str, Any], phase: str, key: str) -> float:
    metrics = report.get("metrics") if isinstance(report.get("metrics"), dict) else {}
    phases = metrics.get("phase_metrics") if isinstance(metrics.get("phase_metrics"), dict) else {}
    phase_metrics = phases.get(phase) if isinstance(phases.get(phase), dict) else {}
    return _float(phase_metrics.get(key))


def _control_holdout_surprise(report: dict[str, Any]) -> float:
    control = report.get("control_metrics") if isinstance(report.get("control_metrics"), dict) else {}
    phases = control.get("phase_metrics") if isinstance(control.get("phase_metrics"), dict) else {}
    holdout = phases.get("holdout") if isinstance(phases.get("holdout"), dict) else {}
    return _float(holdout.get("avg_surprise"), 1.0)


def _run_checks(report: dict[str, Any]) -> dict[str, bool]:
    metrics = report.get("metrics") if isinstance(report.get("metrics"), dict) else {}
    baseline_surprise = _phase_metric(report, "baseline", "avg_surprise")
    holdout_surprise = _phase_metric(report, "holdout", "avg_surprise")
    sequence_hash = _sequence_hash(report)
    return {
        "accepted": bool((report.get("acceptance") or {}).get("passed")),
        "cycle_count": int(report.get("cycle_count") or 0) >= 30,
        "control_cycle_count": int(report.get("control_cycles") or 0) >= int(report.get("cycle_count") or 0),
        "task_sequence_hash_present": len(sequence_hash) == 64,
        "baseline_to_holdout_surprise_drop": holdout_surprise < baseline_surprise,
        "control_holdout_remains_higher": _control_holdout_surprise(report) > holdout_surprise,
        "unsafe_action_rate_zero": _float(metrics.get("unsafe_action_rate")) == 0.0,
        "hash_chain_ok": _hash_chain_ok(report),
        "multi_step_at_least_0_8": _float(metrics.get("multi_step_completion_rate")) >= 0.8,
        "real_action_verified": bool((report.get("real_action") or {}).get("verified")),
    }


def evaluate_seed_diversity(reports: list[dict[str, Any]]) -> dict[str, Any]:
    seeds = [_report_seed(report) for report in reports]
    sequence_hashes = [_sequence_hash(report) for report in reports]
    distinct_seeds = {seed for seed in seeds if seed is not None}
    nonempty_hashes = [value for value in sequence_hashes if value]
    seed_registered_but_not_effective = (
        len(distinct_seeds) >= 3
        and len(nonempty_hashes) == len(reports)
        and len(set(nonempty_hashes)) < len(distinct_seeds)
    )

    failed_checks: list[str] = []
    per_run = []
    for report in reports:
        run_id = str(report.get("run_id") or "<unknown>")
        checks = _run_checks(report)
        per_run.append({
            "run_id": run_id,
            "seed": _report_seed(report),
            "task_sequence_hash": _sequence_hash(report),
            "checks": checks,
        })
        failed_checks.extend(f"{run_id}:{name}" for name, ok in checks.items() if not ok)

    if seed_registered_but_not_effective or len(set(nonempty_hashes)) != len(nonempty_hashes):
        failed_checks.append("task_sequence_hash_diverse")

    return {
        "passed": not failed_checks,
        "failed_checks": failed_checks,
        "seed_registered_but_not_effective": seed_registered_but_not_effective,
        "seeds": seeds,
        "task_sequence_hashes": sequence_hashes,
        "per_run": per_run,
    }


def _resolve_report_path(identifier: str, base_dir: Path) -> Path:
    path = Path(identifier)
    if path.is_dir():
        return path / "report.json"
    if path.exists():
        return path
    return base_dir / identifier / "report.json"


def load_report(identifier: str, base_dir: Path = DEFAULT_BASE_DIR) -> dict[str, Any]:
    report_path = _resolve_report_path(identifier, base_dir)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    run_dir = Path(str(report.get("run_dir") or report_path.parent))
    events_path = run_dir / "events.jsonl"
    if events_path.exists():
        report["_verified_hash_chain"] = HashChainLogger.verify(events_path)
    report["_report_path"] = str(report_path)
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify longitudinal proof seed diversity and v2 gates.")
    parser.add_argument("reports", nargs="+", help="Report paths, run directories, or run ids under --base-dir.")
    parser.add_argument("--base-dir", type=Path, default=DEFAULT_BASE_DIR)
    parser.add_argument("--strict", action="store_true", help="Exit nonzero if diversity or v2 gates fail.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    reports = [load_report(item, args.base_dir) for item in args.reports]
    result = evaluate_seed_diversity(reports)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, default=str))
    if args.strict and not result["passed"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
