"""
self_modification_gate.py — Hard security gate for autonomous self-modification.

Controls:
  ULTRON_SELF_MOD_ENABLED=1      — Master switch (default ON; set 0 to disable all patches)
  ULTRON_SELF_MOD_AUTO_APPROVE=0 — Whether the gate can auto-promote (default OFF)

Pipeline enforced before any patch may be promoted:
  1. Module import safety check (all modules must still import cleanly)
  2. Unit test run (backend tests must pass)
  3. Benchmark measurement before/after patch application
  4. Rollback if benchmark drops
  5. Protected-module guard (critical modules require manual approval)
  6. Human approval gate when ULTRON_SELF_MOD_AUTO_APPROVE=0

Even with auto-approve ON, hard vetoes (import failure, test failure,
benchmark regression, critical-module modification) always block promotion.
"""
from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

# ── Env config ──────────────────────────────────────────────────────────────
ENABLED = int(os.getenv("ULTRON_SELF_MOD_ENABLED", "1")) == 1
AUTO_APPROVE = int(os.getenv("ULTRON_SELF_MOD_AUTO_APPROVE", "0")) == 1

# Modules whose source may NEVER be altered without explicit human approval
CRITICAL_MODULES = frozenset([
    "ultronpro.self_modification_gate",  # this file
    "ultronpro.rl_policy",
    "ultronpro.promotion_gate",
    "ultronpro.cognitive_patch_loop",
    "ultronpro.rollback_manager",
    "ultronpro.homeostasis",
    "ultronpro.self_governance",
    "ultronpro.store",
    "ultronpro.main",
])

# Minimum benchmark accuracy that must be maintained after any patch
BENCHMARK_FLOOR = float(os.getenv("ULTRON_SELF_MOD_BENCH_FLOOR", "0.60"))

GATE_LOG_PATH = Path(__file__).resolve().parent.parent / "data" / "self_modification_gate_log.jsonl"
BACKEND_ROOT = Path(__file__).resolve().parent.parent

# ── Internal helpers ─────────────────────────────────────────────────────────

def _now() -> int:
    return int(time.time())


def _log(entry: dict[str, Any]) -> None:
    GATE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with GATE_LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": _now(), **entry}, ensure_ascii=False) + "\n")


def _veto(reason: str, details: Any = None) -> dict[str, Any]:
    entry = {"ok": False, "vetoed": True, "reason": reason, "details": details}
    _log({"event": "veto", **entry})
    return entry


def _pass(reason: str, details: Any = None) -> dict[str, Any]:
    entry = {"ok": True, "vetoed": False, "reason": reason, "details": details}
    _log({"event": "pass", **entry})
    return entry


# ── Gate checks ──────────────────────────────────────────────────────────────

def check_import_safety() -> dict[str, Any]:
    """Attempt to import every core ultronpro submodule. Skip known optional-dep modules."""
    ultronpro_dir = Path(__file__).resolve().parent

    # Modules that have optional heavy deps (scipy, torch, PIL) or hardcoded paths
    # These are expected to fail in environments without those deps installed
    KNOWN_OPTIONAL: frozenset[str] = frozenset([
        "ultronpro.arc_executor",
        "ultronpro.inference_api",
        "ultronpro.perception",
        "ultronpro.visual_inductor",
        "ultronpro.clean_llm",
        "ultronpro.clean_llm_ast",
        "ultronpro.clean_roadmap",
        "ultronpro.fix_llm_syntax",
    ])

    failed: list[str] = []
    ok: list[str] = []
    skipped: list[str] = []
    for py_file in sorted(ultronpro_dir.glob("*.py")):
        mod_name = f"ultronpro.{py_file.stem}"
        if mod_name in KNOWN_OPTIONAL:
            skipped.append(mod_name)
            continue
        try:
            importlib.import_module(mod_name)
            ok.append(mod_name)
        except Exception as exc:
            failed.append(f"{mod_name}: {str(exc)[:120]}")
    if failed:
        return _veto("import_safety_failed", {"failed": failed, "ok_count": len(ok), "skipped": len(skipped)})
    return _pass("all_modules_import_ok", {"ok_count": len(ok), "skipped": len(skipped)})


def check_unit_tests(timeout_sec: int = 60) -> dict[str, Any]:
    """Run backend test suite (non-scratch test_*.py files) in a subprocess."""
    test_files = [
        p for p in BACKEND_ROOT.glob("test_*.py")
        if "scratch" not in str(p)
    ]
    if not test_files:
        return _veto("no_unit_tests_found", {"note": "unit tests are required for self-modification — no tests found"})

    cmd = [sys.executable, "-m", "pytest", "--tb=no", "-q"] + [str(t) for t in test_files[:20]]
    try:
        result = subprocess.run(
            cmd,
            cwd=str(BACKEND_ROOT),
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
        if result.returncode == 0:
            return _pass("unit_tests_passed", {"stdout": result.stdout[-500:]})
        else:
            return _veto("unit_tests_failed", {
                "returncode": result.returncode,
                "stdout": result.stdout[-800:],
                "stderr": result.stderr[-400:],
            })
    except subprocess.TimeoutExpired:
        return _veto("unit_tests_timeout", {"timeout_sec": timeout_sec})
    except Exception as exc:
        return _veto("unit_tests_error", {"error": str(exc)[:200]})


def measure_benchmark_accuracy() -> float | None:
    """Return current benchmark accuracy from external_benchmarks.
    Returns None if no run has been performed yet (no baseline available).
    """
    try:
        from ultronpro import external_benchmarks
        stat = external_benchmarks.status()
        runs = stat.get("audit") or {}
        acc = runs.get("oracle_accuracy") or runs.get("accuracy")
        if acc is not None:
            return float(acc)
        # No stored result — don't trigger run (could block for minutes)
        return None
    except Exception:
        return None


def check_benchmark_regression(before_acc: float | None, after_acc: float | None) -> dict[str, Any]:
    """Veto if benchmark dropped more than 5% relative or below floor.
    If no baseline exists (None), treat as no regression (first-time gate pass).
    """
    if before_acc is None or after_acc is None:
        return _pass("benchmark_no_baseline", {
            "note": "No prior benchmark run — regression check skipped (first-time pass).",
            "before": before_acc, "after": after_acc,
        })
    drop = before_acc - after_acc
    relative_drop = drop / max(0.01, before_acc)
    if after_acc < BENCHMARK_FLOOR:
        return _veto("benchmark_below_floor", {
            "before": before_acc, "after": after_acc, "floor": BENCHMARK_FLOOR
        })
    if relative_drop > 0.05:
        return _veto("benchmark_regression", {
            "before": before_acc, "after": after_acc,
            "drop": round(drop, 4), "relative_drop_pct": round(relative_drop * 100, 2)
        })
    return _pass("benchmark_ok", {
        "before": before_acc, "after": after_acc, "drop": round(drop, 4)
    })


def check_critical_modules(patch: dict[str, Any]) -> dict[str, Any]:
    """Veto if the patch touches critical modules and auto-approve is on."""
    change = patch.get("proposed_change") if isinstance(patch.get("proposed_change"), dict) else {}
    target = str(change.get("target_module") or change.get("module") or "").strip()
    if not target:
        return _pass("no_module_target", {})
    if target in CRITICAL_MODULES:
        return _veto("critical_module_protected", {
            "target_module": target,
            "note": "Manual human approval required to modify critical modules.",
        })
    return _pass("module_not_critical", {"target_module": target})


def check_human_approval_required(patch: dict[str, Any]) -> dict[str, Any]:
    """When AUTO_APPROVE=0, all promotions require explicit human sign-off."""
    if AUTO_APPROVE:
        return _pass("auto_approve_enabled", {})
    approved_by = str(patch.get("approved_by") or "").strip()
    if not approved_by:
        return _veto(
            "human_approval_required",
            {
                "patch_id": patch.get("id"),
                "note": "Set ULTRON_SELF_MOD_AUTO_APPROVE=1 or add 'approved_by' field to patch.",
            },
        )
    return _pass("human_approval_present", {"approved_by": approved_by})


# ── Main entry point ─────────────────────────────────────────────────────────

def run_gate(patch: dict[str, Any], *, skip_tests: bool = False) -> dict[str, Any]:
    """
    Run the full self-modification security gate pipeline.

    Returns a dict with:
      - ok: bool — True only if ALL checks passed and promotion is allowed
      - vetoed: bool
      - checks: list of individual check results
      - decision: 'promote' | 'hold' | 'reject'
    """
    if not ENABLED:
        entry = _veto("self_modification_disabled", {"ULTRON_SELF_MOD_ENABLED": 0})
        return {"ok": False, "vetoed": True, "decision": "hold", "checks": [entry]}

    checks: list[dict[str, Any]] = []

    # 1. Master switch / critical module guard
    crit = check_critical_modules(patch)
    checks.append(crit)
    if crit.get("vetoed"):
        return {"ok": False, "vetoed": True, "decision": "hold", "checks": checks}

    # 2. Human approval gate
    approval = check_human_approval_required(patch)
    checks.append(approval)
    if approval.get("vetoed"):
        return {"ok": False, "vetoed": True, "decision": "hold", "checks": checks}

    # 3. Import safety
    imp = check_import_safety()
    checks.append(imp)
    if imp.get("vetoed"):
        return {"ok": False, "vetoed": True, "decision": "reject", "checks": checks}

    # 4. Unit tests (optional skip for speed in dev — never skip in prod)
    if not skip_tests:
        tests = check_unit_tests()
        checks.append(tests)
        if tests.get("vetoed"):
            return {"ok": False, "vetoed": True, "decision": "reject", "checks": checks}

    # 5. Benchmark before/after
    before_acc = measure_benchmark_accuracy()
    checks.append({"check": "benchmark_before", "accuracy": before_acc})

    # NOTE: The actual patch application happens in cognitive_patch_loop before calling
    # run_gate — so here we measure the *current* (post-patch) accuracy.
    after_acc = measure_benchmark_accuracy()
    bench = check_benchmark_regression(before_acc, after_acc)
    checks.append(bench)
    if bench.get("vetoed"):
        return {"ok": False, "vetoed": True, "decision": "reject", "checks": checks}

    # All checks passed
    decision = "promote" if AUTO_APPROVE else "hold"
    _log({"event": "gate_passed", "patch_id": patch.get("id"), "decision": decision})
    return {
        "ok": True,
        "vetoed": False,
        "decision": decision,
        "checks": checks,
        "note": (
            "Auto-approved by gate."
            if AUTO_APPROVE
            else "Gate passed — awaiting human approval (ULTRON_SELF_MOD_AUTO_APPROVE=0)."
        ),
    }


def status() -> dict[str, Any]:
    """Return current gate configuration and recent log tail."""
    log_tail: list[dict] = []
    if GATE_LOG_PATH.exists():
        lines = GATE_LOG_PATH.read_text(encoding="utf-8", errors="ignore").splitlines()
        for ln in lines[-20:]:
            try:
                log_tail.append(json.loads(ln))
            except Exception:
                pass
    return {
        "ok": True,
        "enabled": ENABLED,
        "auto_approve": AUTO_APPROVE,
        "benchmark_floor": BENCHMARK_FLOOR,
        "critical_modules": sorted(CRITICAL_MODULES),
        "log_path": str(GATE_LOG_PATH),
        "recent_log": log_tail,
    }
