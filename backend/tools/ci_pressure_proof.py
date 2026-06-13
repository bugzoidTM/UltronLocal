#!/usr/bin/env python3
"""
ci_pressure_proof.py — run pressure_benchmark in a controlled environment and assert.
====================================================================================

What this honestly validates
----------------------------
`pressure_benchmark` is, at its core, a test of the *underlying model's* robustness
(MCQ accuracy + resistance to adversarial decoys). Its pressure axes are mostly
prompt-text framings. So against the deterministic, gold-blind mock LLM this runner
validates the parts that DON'T depend on model IQ:

  * the resilience harness executes end-to-end and reproducibly (all 5 axes scored);
  * routing/graceful-degradation works — under `provider_dropout` and
    `rate_limit_cascade` the system still reaches a provider and returns a scored
    answer instead of crashing/empty.

It deliberately does NOT assert the `maturity_index`/`MATURE` grade in mock mode —
that number is a property of the mock and is meaningless as a system claim.

Real-model grading
------------------
Set `ULTRON_PROOF_REAL_LLM=1` and point the providers at a real endpoint
(e.g. `OLLAMA_BASE_URL_LOCAL` / `ULTRON_LOCAL_INFER_URL`). Then this runner ALSO
asserts baseline_accuracy > 0 and maturity_index >= threshold — the genuine grade.

Exit code 0 = pass, 1 = fail.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

REAL_LLM = os.getenv("ULTRON_PROOF_REAL_LLM", "0") == "1"
ARTIFACT = BACKEND_DIR / "data" / "ci_pressure_proof_report.json"


def _fail(msg: str) -> None:
    print(f"[ci-pressure] FAIL: {msg}", flush=True)
    raise SystemExit(1)


def main() -> int:
    os.environ.setdefault("BENCHMARK_MODE", "1")

    if not REAL_LLM:
        # Controlled environment: route every local strategy (cheap, local_first, default…)
        # to the deterministic neutral mock so all 5 axes reach a provider.
        os.environ["ULTRON_DISABLE_CLOUD_PROVIDERS"] = "1"
        os.environ["ULTRON_PRIMARY_LOCAL_PROVIDER"] = "ollama_local"
        from tools.mock_llm_server import serve_in_thread
        port = int(os.getenv("MOCK_LLM_PORT", "11434"))
        _server, base = serve_in_thread("127.0.0.1", port)
        os.environ.setdefault("OLLAMA_BASE_URL_LOCAL", base)
        os.environ.setdefault("OLLAMA_BASE_URL", base)
        # belt-and-suspenders: if any path still picks ultron_infer, send it to the
        # mock's OpenAI-compat endpoint over HTTP (binary TCP transport off).
        os.environ.setdefault("ULTRON_LOCAL_INFER_URL", base)
        os.environ.setdefault("ULTRON_INFER_BINARY_CLIENT_ENABLED", "0")
        print(f"[ci-pressure] mode=MOCK (neutral/deterministic) provider={base}", flush=True)
    else:
        print("[ci-pressure] mode=REAL_LLM — will assert the maturity grade", flush=True)

    from ultronpro import pressure_benchmark as pb

    # Suite-level run (harness completeness + maturity index).
    suite = pb.run_pressure_suite(persist=False)
    # Per-case runs for the two routing/fallback axes (reachability proof).
    dropout = pb.run_axis("provider_dropout", persist=False)
    cascade = pb.run_axis("rate_limit_cascade", persist=False)

    axes = {a["axis"]: a for a in suite.get("axis_summary", [])}
    report = {
        "llm_mode": "real" if REAL_LLM else "mock_neutral",
        "ok": suite.get("ok"),
        "baseline_accuracy": suite.get("baseline_accuracy"),
        "maturity_index": suite.get("maturity_index"),
        "maturity_level": suite.get("maturity_level"),
        "mature": suite.get("mature"),
        "axes_run": suite.get("axes_run"),
        "axis_summary": suite.get("axis_summary"),
        "routing_axes_reachability": {},
    }

    # --- Harness completeness assertions (always) ---
    if not suite.get("ok"):
        _fail("pressure suite did not return ok")
    expected_axes = {"provider_dropout", "memory_blackout", "context_starvation",
                     "adversarial_framing", "rate_limit_cascade"}
    if set(suite.get("axes_run") or []) != expected_axes:
        _fail(f"not all axes ran: {suite.get('axes_run')}")
    for name, a in axes.items():
        if not a.get("ok"):
            _fail(f"axis {name} reported ok=False")
    mi = suite.get("maturity_index")
    if not isinstance(mi, (int, float)) or not (0.0 <= float(mi) <= 1.0):
        _fail(f"maturity_index not a finite value in [0,1]: {mi}")

    # --- Routing / graceful-degradation reachability (always) ---
    for axis_name, axis_res in (("provider_dropout", dropout), ("rate_limit_cascade", cascade)):
        cases = axis_res.get("cases") or []
        if not cases:
            _fail(f"{axis_name} produced no cases")
        non_empty = sum(1 for c in cases if str(c.get("predicted") or "").strip())
        errors = sum(1 for c in cases if c.get("error"))
        report["routing_axes_reachability"][axis_name] = {
            "cases": len(cases), "non_empty_predictions": non_empty, "errors": errors,
        }
        # Under simulated provider failure the system must still route to a working
        # provider (the mock/real local) and return an answer for every probe.
        if non_empty < len(cases):
            _fail(f"{axis_name}: {len(cases) - non_empty}/{len(cases)} probes returned an empty answer "
                  f"(routing/fallback did not recover)")

    # --- Real-model grade (only when a real endpoint is connected) ---
    # The honest `mature` flag already requires BOTH a meaningful absolute baseline
    # and retention >= threshold, so a consistently-weak model cannot pass on retention
    # math alone.
    if REAL_LLM:
        report["baseline_ok"] = suite.get("baseline_ok")
        if not suite.get("baseline_ok"):
            _fail(f"REAL_LLM mode: baseline_accuracy {suite.get('baseline_accuracy')} below floor "
                  f"{suite.get('min_baseline_for_maturity')} — retention is undefined (verdict: "
                  f"{suite.get('maturity_verdict')})")
        if not suite.get("mature"):
            _fail(f"REAL_LLM mode: NOT MATURE — {suite.get('maturity_verdict')}")

    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[ci-pressure] PASS — harness+routing validated "
          f"(mode={report['llm_mode']}, maturity_index={mi}, "
          f"baseline_acc={report['baseline_accuracy']})", flush=True)
    if not REAL_LLM:
        print("[ci-pressure] NOTE: maturity grade above is mock-derived and is NOT a system "
              "maturity claim. Run with ULTRON_PROOF_REAL_LLM=1 against a real endpoint to grade.",
              flush=True)
    print(f"[ci-pressure] artifact: {ARTIFACT}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
