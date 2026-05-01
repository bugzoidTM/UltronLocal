import json
import sys
import tempfile
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

sys.path.insert(0, r"F:\sistemas\UltronPro\backend")


class _NullAnswerer:
    def answer(self, query: str, task_type: str):
        return None


def _fake_sandbox_execute(code: str, timeout_sec: int = 10):
    namespace = {}
    captured = StringIO()
    with redirect_stdout(captured):
        exec(code, namespace, namespace)
    return {
        "ok": True,
        "returncode": 0,
        "stdout": captured.getvalue(),
        "stderr": "",
    }


def test_cognitive_response_transfers_prior_before_unknown():
    from ultronpro import (
        active_investigation,
        causal_graph,
        cognitive_response,
        sandbox_client,
        structural_mapper,
    )

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        old_values = (
            active_investigation.INVESTIGATION_LOG_PATH,
            active_investigation.INVESTIGATION_STATE_PATH,
            active_investigation.INVESTIGATION_EXECUTION_LOG_PATH,
            active_investigation.INVESTIGATION_EXECUTION_STATE_PATH,
            active_investigation._learned_route,
            active_investigation._probe_causal_graph,
            active_investigation._probe_episodic_memory,
            active_investigation._probe_store,
            active_investigation._probe_workspace,
            active_investigation._probe_runtime_state,
            causal_graph.GRAPH_PATH,
            causal_graph.EDGE_LOG_PATH,
            sandbox_client.execute_python,
            structural_mapper.CROSS_SKILLS_PATH,
            cognitive_response.TRACE_PATH,
            cognitive_response._ENGINE,
        )

        active_investigation.INVESTIGATION_LOG_PATH = root / "active_investigations.jsonl"
        active_investigation.INVESTIGATION_STATE_PATH = root / "active_investigation_state.json"
        active_investigation.INVESTIGATION_EXECUTION_LOG_PATH = root / "active_investigation_executions.jsonl"
        active_investigation.INVESTIGATION_EXECUTION_STATE_PATH = root / "active_investigation_execution_state.json"
        causal_graph.GRAPH_PATH = root / "causal_graph.json"
        causal_graph.EDGE_LOG_PATH = root / "causal_graph_edges.jsonl"
        sandbox_client.execute_python = _fake_sandbox_execute
        structural_mapper.CROSS_SKILLS_PATH = root / "cross_domain_skills.json"
        cognitive_response.TRACE_PATH = root / "cognitive_response_traces.jsonl"

        structural_mapper.CROSS_SKILLS_PATH.write_text(
            json.dumps(
                {
                    "skills": [
                        {
                            "id": "zshot_guard_transfer",
                            "name": "Isomorfismo Validado: fs_guard <-> api_guard",
                            "core_causal_invariant": "guarded validated reversible resource_ok reduz risco operacional",
                            "valid_domains": ["fs_guard", "api_guard"],
                            "bijective_map": {
                                "guarded": "auth_ok",
                                "validated": "schema_ok",
                                "reversible": "rollback_ready",
                                "resource_ok": "quota_ok",
                            },
                            "raw_score": 0.96,
                            "p_value": 0.02,
                            "transfer_improvement": 0.22,
                            "origin": "autoisomorphic_mapper_v2",
                            "validation_status": "empirically_tested",
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        active_investigation._learned_route = lambda query: {
            "routed": False,
            "module": "unknown",
            "method": "test",
        }
        active_investigation._probe_causal_graph = lambda query: {"ok": True, "count": 0, "items": []}
        active_investigation._probe_episodic_memory = lambda query, task_type: {"ok": True, "count": 0}
        active_investigation._probe_store = lambda query: {"ok": True, "triples": [], "insights": [], "experiences": []}
        active_investigation._probe_workspace = lambda: {"ok": True, "count": 0, "items": []}
        active_investigation._probe_runtime_state = lambda: {"ok": True, "files": {}}

        try:
            engine = cognitive_response.CognitiveResponseEngine()
            null = _NullAnswerer()
            engine.operational = null
            engine.dialogue = null
            engine.episodic = null
            engine.simulation = null
            engine.symbolic = null
            cognitive_response._ENGINE = engine

            result = cognitive_response.answer(
                "Como agir em dominio novo quando auth_ok schema_ok rollback_ready quota_ok controlam risco?",
                task_type="unknown_domain",
            )

            assert result["resolved"] is True
            assert result["module"] == "causal_transfer_engine"
            assert result["strategy"] == "non_llm_causal_transfer_prior"
            assert not result["answer"].startswith("UNKNOWN")

            summary = result["evidence_summary"]
            assert summary["transfer_prior"]["source_domain"] == "fs_guard"
            assert summary["prior_validation"]["status"] == "validated"
            assert summary["investigation_execution"]["injected"] is True

            graph = causal_graph.load_graph()
            edges = list(graph["edges"].values())
            assert any("active_investigation_executor" in edge.get("sources", []) for edge in edges)
            assert any("transfer_prior_validated" in edge.get("effect", "") for edge in edges)
        finally:
            (
                active_investigation.INVESTIGATION_LOG_PATH,
                active_investigation.INVESTIGATION_STATE_PATH,
                active_investigation.INVESTIGATION_EXECUTION_LOG_PATH,
                active_investigation.INVESTIGATION_EXECUTION_STATE_PATH,
                active_investigation._learned_route,
                active_investigation._probe_causal_graph,
                active_investigation._probe_episodic_memory,
                active_investigation._probe_store,
                active_investigation._probe_workspace,
                active_investigation._probe_runtime_state,
                causal_graph.GRAPH_PATH,
                causal_graph.EDGE_LOG_PATH,
                sandbox_client.execute_python,
                structural_mapper.CROSS_SKILLS_PATH,
                cognitive_response.TRACE_PATH,
                cognitive_response._ENGINE,
            ) = old_values
