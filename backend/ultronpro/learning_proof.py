from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path
from typing import Any


def _restore_cache(module: Any) -> None:
    try:
        module._cached_examples.cache_clear()
    except Exception:
        pass


def run_before_after_route_learning_proof() -> dict[str, Any]:
    """Prove that route traces can change future learned routing.

    This is intentionally not a new competence. It runs in a temporary data
    directory and checks whether a labeled failure becomes reusable routing
    evidence for a nearby query, without storing a benchmark answer.
    """
    from ultronpro import episodic_memory, trace_learning
    from ultronpro.core import learned_intent

    old_trace = trace_learning.TRACE_LEARNING_PATH
    old_state = trace_learning.TRACE_LEARNING_STATE_PATH
    old_route = learned_intent.ROUTE_EPISODES_PATH
    old_decision = learned_intent.DECISION_TRACE_DIR
    old_learned_episodic = learned_intent.EPISODIC_PATH
    old_ep = episodic_memory.EPISODIC_PATH
    old_proc = episodic_memory.PROCEDURAL_PATH
    old_prop = episodic_memory.LEARNING_PROPOSALS_PATH

    started = time.time()
    with tempfile.TemporaryDirectory(prefix="ultron-learning-proof-") as td:
        base = Path(td)
        trace_learning.TRACE_LEARNING_PATH = base / "trace_learning.jsonl"
        trace_learning.TRACE_LEARNING_STATE_PATH = base / "trace_learning_state.json"
        learned_intent.ROUTE_EPISODES_PATH = base / "intent_route_episodes.jsonl"
        learned_intent.DECISION_TRACE_DIR = base / "decision_traces"
        learned_intent.EPISODIC_PATH = base / "episodic_memory.jsonl"
        episodic_memory.EPISODIC_PATH = base / "episodic_memory.jsonl"
        episodic_memory.PROCEDURAL_PATH = base / "procedural_memory.jsonl"
        episodic_memory.LEARNING_PROPOSALS_PATH = base / "learning_proposals.jsonl"
        _restore_cache(learned_intent)

        try:
            probe = "como falo obrigado em frances"
            before = learned_intent.predict_route(probe, use_embeddings=False).to_dict()
            report = {
                "run_id": "learning_proof_temp",
                "items": [
                    {
                        "case_id": "proof_translation_wrong_causal",
                        "prompt": "como digo obrigado em frances",
                        "expected_intent": "translation",
                        "actual_intent": "causal_reasoning",
                        "expected_route": "translation",
                        "actual_route": "causal",
                        "actual_strategy": "causal_transfer_engine",
                        "route_ok": False,
                        "answer_ok": False,
                        "strategy_ok": False,
                        "ok": False,
                        "route_decision": {
                            "intent": "open_chat",
                            "route": "none",
                            "confidence": 0.35,
                            "should_use_causal": True,
                        },
                        "trace_rag": None,
                    }
                ],
            }
            learning = trace_learning.learn_from_route_eval_report(report, dry_run=False)
            _restore_cache(learned_intent)
            after = learned_intent.predict_route(probe, use_embeddings=False).to_dict()
            status = trace_learning.status()
            module_scores = after.get("module_scores") if isinstance(after.get("module_scores"), dict) else {}
            proposals = learning.get("learning_proposals") if isinstance(learning.get("learning_proposals"), list) else []
            criteria = {
                "cold_start_has_no_route": before.get("routed") is False,
                "trace_converted_to_add_fast_path": (learning.get("actions") or {}).get("add_fast_path") == 1,
                "positive_and_negative_route_evidence_recorded": learning.get("route_records") == 2,
                "future_similar_query_routes_to_expected_competence": after.get("routed") is True and after.get("module") == "translation",
                "causal_evidence_is_penalized": float(module_scores.get("causal") or 0.0) < 0.0,
                "translation_evidence_is_positive": float(module_scores.get("translation") or 0.0) > 0.0,
                "self_modification_requires_gate": bool(
                    proposals
                    and isinstance(proposals[0].get("proposal"), dict)
                    and ((proposals[0]["proposal"].get("details") or {}).get("requires_self_modification_gate") is True)
                ),
                "no_answer_fixture_used": bool(
                    proposals
                    and isinstance(proposals[0].get("proposal"), dict)
                    and ((proposals[0]["proposal"].get("details") or {}).get("do_not_hardcode_answer") is True)
                ),
            }
            return {
                "ok": all(criteria.values()),
                "duration_ms": int((time.time() - started) * 1000),
                "proof_type": "before_after_route_learning",
                "probe": probe,
                "criteria": criteria,
                "before": before,
                "learning": learning,
                "after": after,
                "trace_actions": status.get("actions"),
                "temp_paths": {
                    "base": str(base),
                    "trace_learning": str(trace_learning.TRACE_LEARNING_PATH),
                    "route_episodes": str(learned_intent.ROUTE_EPISODES_PATH),
                },
            }
        finally:
            trace_learning.TRACE_LEARNING_PATH = old_trace
            trace_learning.TRACE_LEARNING_STATE_PATH = old_state
            learned_intent.ROUTE_EPISODES_PATH = old_route
            learned_intent.DECISION_TRACE_DIR = old_decision
            learned_intent.EPISODIC_PATH = old_learned_episodic
            episodic_memory.EPISODIC_PATH = old_ep
            episodic_memory.PROCEDURAL_PATH = old_proc
            episodic_memory.LEARNING_PROPOSALS_PATH = old_prop
            _restore_cache(learned_intent)


def run_learning_proof() -> dict[str, Any]:
    from ultronpro import competence_ledger, trace_learning

    trace_selftest = trace_learning.run_selftest()
    competence_selftest = competence_ledger.run_selftest()
    before_after = run_before_after_route_learning_proof()
    return {
        "ok": bool(trace_selftest.get("ok")) and bool(competence_selftest.get("ok")) and bool(before_after.get("ok")),
        "ts": int(time.time()),
        "claim": "O sistema transforma traces de rota em evidencia reutilizavel e atualiza o ledger de competencias sem hardcodar respostas.",
        "evidence": {
            "trace_learning_selftest": trace_selftest,
            "competence_ledger_selftest": competence_selftest,
            "before_after_route_learning": before_after,
        },
    }


def main() -> int:
    out = run_learning_proof()
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
