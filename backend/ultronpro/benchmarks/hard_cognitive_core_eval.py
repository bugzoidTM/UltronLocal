from __future__ import annotations

import asyncio
import itertools
import json
import os
import time
from pathlib import Path
from typing import Any


os.environ.setdefault("BENCHMARK_MODE", "1")
os.environ.setdefault("ULTRON_DISABLE_CLOUD_PROVIDERS", "1")

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPORT_PATH = BACKEND_DIR / "data" / "hard_cognitive_eval_runs.jsonl"


def _score(ok: bool, points: float) -> float:
    return float(points) if ok else 0.0


def _append_report(report: dict[str, Any]) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with REPORT_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(report, ensure_ascii=False) + "\n")


def evaluate_biographic_digest() -> dict[str, Any]:
    from ultronpro import biographic_digest

    digest = biographic_digest.generate_biographic_digest(window_days=30, persist=True)
    evidence_counts = digest.get("evidence_counts") if isinstance(digest.get("evidence_counts"), dict) else {}
    ok = bool(digest.get("identity")) and len(str(digest.get("narrative") or "")) >= 300 and bool(digest.get("became"))
    return {
        "ok": ok,
        "score": _score(ok, 2.0),
        "day": digest.get("day"),
        "narrative_len": len(str(digest.get("narrative") or "")),
        "became_count": len(digest.get("became") or []),
        "evidence_counts": evidence_counts,
        "checksum": digest.get("checksum"),
    }


def evaluate_abstraction_compiler() -> dict[str, Any]:
    from ultronpro import episodic_compiler

    stamp = str(int(time.time()))
    domain = f"hard_eval_abstraction_{stamp}"
    episode = {
        "goal": "hard cognitive evaluation",
        "steps": ["observe_state", "apply_coverage_gate", "validate_result"],
        "preconditions": {"coverage_gate": True, "rollback": True},
        "guards": {"no_external_llm": True},
        "outcome": "success",
        "evidence": {"regression": False, "latency_ms": 80},
    }
    abstraction = episodic_compiler.compile_causal_invariant(domain, "guarded_validation", episode, 0.05)
    test_results = []
    if abstraction:
        for _ in range(5):
            test_results.append(episodic_compiler.test_abstraction(abstraction["id"], episode, True, 0.05))
    retrieved = episodic_compiler.retrieve_applicable_abstractions(domain, "coverage rollback no external llm")
    final = test_results[-1] if test_results else {}
    ok = bool(abstraction) and final.get("status") == "compiled_skill" and bool(retrieved)
    return {
        "ok": ok,
        "score": _score(ok, 2.0),
        "abstraction_id": (abstraction or {}).get("id"),
        "name": (abstraction or {}).get("name"),
        "final_status": final.get("status"),
        "test_count": final.get("test_count"),
        "confirmation_rate": final.get("confirmation_rate"),
        "retrieved_count": len(retrieved),
    }


def _train_transfer_model(name: str, features: list[str], *, target: bool):
    from ultronpro.local_world_models import LocalWorldModel

    weights = [0.46, 0.27, 0.16, 0.08]

    def prob(combo: tuple[int, ...]) -> float:
        return min(0.95, max(0.05, 0.03 + sum(w * x for w, x in zip(weights, combo))))

    def outcomes(combo: tuple[int, ...], reps: int) -> list[str]:
        n_success = round(prob(combo) * reps)
        return ["success"] * n_success + ["blocked"] * (reps - n_success)

    model = LocalWorldModel(name)
    model.structural_features = list(features)
    combos = list(itertools.product([0, 1], repeat=4))
    sequence: list[tuple[tuple[int, ...], str]] = []
    if target:
        lows = [c for c in combos if prob(c) < 0.5]
        highs = [c for c in combos if prob(c) >= 0.5]
        for c in lows * 8:
            sequence.extend((c, o) for o in outcomes(c, 1))
        for c in highs:
            sequence.extend((c, o) for o in outcomes(c, 6))
    else:
        for c in combos:
            sequence.extend((c, o) for o in outcomes(c, 12))

    for combo, outcome in sequence:
        state = {feat: int(value) for feat, value in zip(features, combo)}
        model.train_step(state, "guarded_transfer", {"done": True}, outcome, {"surprise_delta": 0.02})
    return model


def evaluate_isomorphism_mapper() -> dict[str, Any]:
    from ultronpro.autoisomorphic_mapper import AutoIsomorphicMapper
    from ultronpro.local_world_models import get_manager

    stamp = str(int(time.time()))
    source_domain = f"hard_eval_fs_guard_{stamp}"
    target_domain = f"hard_eval_api_guard_{stamp}"
    source = _train_transfer_model(source_domain, ["guarded", "validated", "reversible", "resource_ok"], target=False)
    target = _train_transfer_model(target_domain, ["auth_ok", "schema_ok", "rollback_ready", "quota_ok"], target=True)

    manager = get_manager()
    manager.models[source_domain] = source
    manager.models[target_domain] = target
    mapper = AutoIsomorphicMapper()
    mapper.manager = manager
    found = mapper.scan_global_isomorphism()
    relevant = [
        row for row in found
        if {row.get("domain_source"), row.get("domain_target")} == {source_domain, target_domain}
    ]
    best = relevant[0] if relevant else {}
    ok = bool(best) and float(best.get("transfer_improvement") or 0.0) >= 0.05 and float(best.get("p_value") or 1.0) <= 0.05
    return {
        "ok": ok,
        "score": _score(ok, 2.0),
        "source_domain": source_domain,
        "target_domain": target_domain,
        "raw_score": best.get("raw_score"),
        "p_value": best.get("p_value"),
        "transfer_improvement": best.get("transfer_improvement"),
        "mapping": best.get("mapping"),
    }


async def evaluate_non_llm_chat() -> dict[str, Any]:
    from ultronpro.main import ChatRequest, chat_fast

    questions = [
        "quem é você?",
        "de onde você veio?",
        "qual meu nome?",
        "eu perguntei sobre mim",
        "você lembra de mim?",
        "qual o risco de executar um comando com pouca memoria?",
        "quanto é 2+2?",
        "qual o nome do sistema?",
    ]
    rows = []
    for question in questions:
        response = await chat_fast(ChatRequest(message=question))
        if hasattr(response, "body"):
            data = json.loads(response.body.decode("utf-8"))
        else:
            data = response
        strategy = str(data.get("strategy") or data.get("method") or "")
        answer = str(data.get("answer") or data.get("response") or "")
        non_llm = bool(data.get("cognitive_core")) or strategy.startswith(("non_llm", "local_", "symbolic", "intent_"))
        rows.append({
            "question": question,
            "strategy": strategy,
            "module": data.get("module"),
            "non_llm": non_llm,
            "answer_len": len(answer.strip()),
            "ok": non_llm and len(answer.strip()) > 0 and "[RAG]" not in answer,
        })
    passed = sum(1 for row in rows if row["ok"])
    ratio = passed / max(1, len(rows))
    ok = ratio >= 0.60
    return {
        "ok": ok,
        "score": round(2.0 * ratio, 3),
        "passed": passed,
        "total": len(rows),
        "ratio": round(ratio, 4),
        "items": rows,
    }


def evaluate_external_benchmark() -> dict[str, Any]:
    from ultronpro import external_benchmarks

    audit = external_benchmarks.suite_audit()
    oracle = external_benchmarks.run_selftest()
    no_cloud_probe = external_benchmarks.run_suite(
        limit_per_benchmark=1,
        predictor="llm",
        strategy="local",
        tag="hard_cognitive_eval_no_cloud_probe",
    )
    audit_ok = bool(audit.get("ok")) and bool(oracle.get("ok"))
    no_cloud_accuracy = float(no_cloud_probe.get("overall_accuracy") or 0.0)
    score = (1.0 if audit_ok else 0.0) + min(1.0, no_cloud_accuracy)
    return {
        "ok": audit_ok,
        "score": round(score, 3),
        "suite_count": audit.get("count"),
        "oracle_selftest_ok": oracle.get("ok"),
        "oracle_accuracy": (oracle.get("report") or {}).get("overall_accuracy"),
        "no_cloud_probe_accuracy": no_cloud_probe.get("overall_accuracy"),
        "no_cloud_probe_total": no_cloud_probe.get("total"),
        "no_cloud_probe_correct": no_cloud_probe.get("correct"),
        "no_cloud_probe_run_id": no_cloud_probe.get("run_id"),
    }


async def run_hard_evaluation() -> dict[str, Any]:
    started = time.time()
    sections = {
        "biographic_digest": evaluate_biographic_digest(),
        "abstraction_compiler": evaluate_abstraction_compiler(),
        "isomorphism_mapper": evaluate_isomorphism_mapper(),
        "non_llm_chat": await evaluate_non_llm_chat(),
        "external_benchmark": evaluate_external_benchmark(),
    }
    total_score = round(sum(float(item.get("score") or 0.0) for item in sections.values()), 3)
    passed = total_score > 5.0
    report = {
        "ok": passed,
        "score_0_10": total_score,
        "threshold": ">5.0",
        "ts": int(time.time()),
        "duration_sec": round(time.time() - started, 3),
        "sections": sections,
    }
    _append_report(report)
    return report


if __name__ == "__main__":
    print(json.dumps(asyncio.run(run_hard_evaluation()), ensure_ascii=False, indent=2))
