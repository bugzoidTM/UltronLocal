import json
import sys
import tempfile
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

sys.path.insert(0, r"F:\sistemas\UltronPro\backend")


def test_pending_active_investigation_executes_in_sandbox_and_injects_causal_edge():
    from ultronpro import active_investigation, causal_graph, sandbox_client

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)

        old_paths = (
            active_investigation.INVESTIGATION_LOG_PATH,
            active_investigation.INVESTIGATION_STATE_PATH,
            active_investigation.INVESTIGATION_EXECUTION_LOG_PATH,
            active_investigation.INVESTIGATION_EXECUTION_STATE_PATH,
            causal_graph.GRAPH_PATH,
            causal_graph.EDGE_LOG_PATH,
            sandbox_client.execute_python,
        )

        active_investigation.INVESTIGATION_LOG_PATH = root / "active_investigations.jsonl"
        active_investigation.INVESTIGATION_STATE_PATH = root / "active_investigation_state.json"
        active_investigation.INVESTIGATION_EXECUTION_LOG_PATH = root / "active_investigation_executions.jsonl"
        active_investigation.INVESTIGATION_EXECUTION_STATE_PATH = root / "active_investigation_execution_state.json"
        causal_graph.GRAPH_PATH = root / "causal_graph.json"
        causal_graph.EDGE_LOG_PATH = root / "causal_graph_edges.jsonl"

        def fake_execute_python(code: str, timeout_sec: int = 10):
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

        sandbox_client.execute_python = fake_execute_python
        try:
            report = {
                "ok": True,
                "resolved": True,
                "investigation_id": "inv_test123",
                "ts": 2_000_000_000,
                "status": "needs_experiment",
                "reason": "no_structured_coverage",
                "task_type": "operations",
                "query": "Qual o risco de fazer deploy sem rollback?",
                "coverage": {"score": 0.0},
                "missing_slots": ["aresta_causal_relevante"],
                "next_experiment": {
                    "kind": "causal_graph_enrichment",
                    "target_route": "unknown",
                    "query_terms": ["risco", "deploy", "rollback"],
                    "action": "registrar uma decisao ou observacao verificavel como aresta causal antes de responder com confianca",
                    "acceptance": "a proxima resposta deve citar evidencia interna recuperada ou declarar UNKNOWN com a lacuna exata",
                },
            }
            active_investigation.INVESTIGATION_STATE_PATH.write_text(
                json.dumps(report, ensure_ascii=False),
                encoding="utf-8",
            )

            result = active_investigation.execute_pending_experiment()

            assert result["ok"] is True
            assert result["executed"] is True
            assert result["injected"] is True
            assert result["sandbox"]["ok"] is True

            lookup = causal_graph.query_for_problem("Qual o risco de fazer deploy sem rollback?", limit=3)
            assert lookup["count"] >= 1
            assert "deploy" in lookup["items"][0]["cause"]
        finally:
            (
                active_investigation.INVESTIGATION_LOG_PATH,
                active_investigation.INVESTIGATION_STATE_PATH,
                active_investigation.INVESTIGATION_EXECUTION_LOG_PATH,
                active_investigation.INVESTIGATION_EXECUTION_STATE_PATH,
                causal_graph.GRAPH_PATH,
                causal_graph.EDGE_LOG_PATH,
                sandbox_client.execute_python,
            ) = old_paths
