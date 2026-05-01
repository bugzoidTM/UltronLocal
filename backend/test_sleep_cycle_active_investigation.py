import json
import sys
import tempfile
import time
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

sys.path.insert(0, r"F:\sistemas\UltronPro\backend")


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


def _pending_report() -> dict:
    return {
        "ok": True,
        "resolved": True,
        "investigation_id": "inv_sleep_gap",
        "ts": int(time.time()),
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


def test_sleep_cycle_consumes_active_investigation_when_no_pruning_or_abstraction():
    from ultronpro import active_investigation, biographic_digest, causal_graph, cognitive_response, coverage_milestone, sandbox_client, sleep_cycle

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        old_paths = (
            sleep_cycle.EPISODIC_PATH,
            sleep_cycle.EPISODIC_ARCHIVE_PATH,
            sleep_cycle.ABSTRACTIONS_PATH,
            sleep_cycle.REPORT_PATH,
            sleep_cycle.AUDIT_PATH,
            active_investigation.INVESTIGATION_LOG_PATH,
            active_investigation.INVESTIGATION_STATE_PATH,
            active_investigation.INVESTIGATION_EXECUTION_LOG_PATH,
            active_investigation.INVESTIGATION_EXECUTION_STATE_PATH,
            causal_graph.GRAPH_PATH,
            causal_graph.EDGE_LOG_PATH,
            sandbox_client.execute_python,
            biographic_digest.DATA_DIR,
            biographic_digest.ACTIVE_INVESTIGATION_EXECUTION_LOG_PATH,
            coverage_milestone.FIRST_MILESTONE_PATH,
            coverage_milestone.MILESTONE_LOG_PATH,
            cognitive_response.TRACE_PATH,
        )

        sleep_cycle.EPISODIC_PATH = root / "episodic_memory.jsonl"
        sleep_cycle.EPISODIC_ARCHIVE_PATH = root / "episodic_memory_archive.jsonl"
        sleep_cycle.ABSTRACTIONS_PATH = root / "episodic_abstractions.json"
        sleep_cycle.REPORT_PATH = root / "sleep_cycle_report.json"
        sleep_cycle.AUDIT_PATH = root / "episodic_audit.jsonl"
        active_investigation.INVESTIGATION_LOG_PATH = root / "active_investigations.jsonl"
        active_investigation.INVESTIGATION_STATE_PATH = root / "active_investigation_state.json"
        active_investigation.INVESTIGATION_EXECUTION_LOG_PATH = root / "active_investigation_executions.jsonl"
        active_investigation.INVESTIGATION_EXECUTION_STATE_PATH = root / "active_investigation_execution_state.json"
        causal_graph.GRAPH_PATH = root / "causal_graph.json"
        causal_graph.EDGE_LOG_PATH = root / "causal_graph_edges.jsonl"
        sandbox_client.execute_python = _fake_sandbox_execute
        biographic_digest.DATA_DIR = root
        biographic_digest.ACTIVE_INVESTIGATION_EXECUTION_LOG_PATH = active_investigation.INVESTIGATION_EXECUTION_LOG_PATH
        coverage_milestone.FIRST_MILESTONE_PATH = root / "first_self_learned_answer_milestone.json"
        coverage_milestone.MILESTONE_LOG_PATH = root / "self_learning_milestones.jsonl"
        cognitive_response.TRACE_PATH = root / "cognitive_response_trace.jsonl"

        try:
            active_investigation.INVESTIGATION_STATE_PATH.write_text(
                json.dumps(_pending_report(), ensure_ascii=False),
                encoding="utf-8",
            )

            report = sleep_cycle.run_cycle(retention_days=14, max_active_rows=3000)

            assert report["ok"] is True
            assert report["pruned"] == 0
            assert report["abstracted"] == 0
            gap = report["causal_gap_investigation"]
            assert gap["pending_before"] == 1
            assert gap["executed"] == 1
            assert gap["injected"] == 1
            assert gap["coverage_gained"] is True
            assert report["coverage_gained"] is True

            lookup = causal_graph.query_for_problem("Qual o risco de fazer deploy sem rollback?", limit=3)
            assert lookup["count"] >= 1
            assert "deploy" in lookup["items"][0]["cause"]

            digest = biographic_digest.generate_biographic_digest(day="2099-01-01", window_days=1, persist=False)
            assert digest["evidence_counts"]["causal_gap_experiments"] >= 1
            assert digest["evidence_counts"]["causal_gap_injections"] >= 1
            assert digest["causal_gap_investigations"]
            assert "sono investigativo" in digest["narrative"].lower()

            answer = cognitive_response.answer("Qual o risco de fazer deploy sem rollback?")
            assert answer["resolved"] is True
            assert answer["module"] == "symbolic_causal"
            assert "investigacao ativa sandboxada" in answer["answer"]
            assert answer["self_learning_milestone"]["recorded"] is True

            milestone = json.loads(coverage_milestone.FIRST_MILESTONE_PATH.read_text(encoding="utf-8"))
            assert milestone["type"] == "first_self_learned_grounded_answer"
            assert milestone["verification"]["prior_unknown_status"] == "needs_experiment"
            assert milestone["verification"]["sandbox_ok"] is True
            assert milestone["verification"]["causal_injected"] is True
            assert milestone["verification"]["active_investigation_source_used"] is True
            assert milestone["audit_trail"]["initial_unknown"]["investigation_id"] == "inv_sleep_gap"
            assert milestone["audit_trail"]["grounded_answer"]["module"] == "symbolic_causal"
        finally:
            (
                sleep_cycle.EPISODIC_PATH,
                sleep_cycle.EPISODIC_ARCHIVE_PATH,
                sleep_cycle.ABSTRACTIONS_PATH,
                sleep_cycle.REPORT_PATH,
                sleep_cycle.AUDIT_PATH,
                active_investigation.INVESTIGATION_LOG_PATH,
                active_investigation.INVESTIGATION_STATE_PATH,
                active_investigation.INVESTIGATION_EXECUTION_LOG_PATH,
                active_investigation.INVESTIGATION_EXECUTION_STATE_PATH,
                causal_graph.GRAPH_PATH,
                causal_graph.EDGE_LOG_PATH,
                sandbox_client.execute_python,
                biographic_digest.DATA_DIR,
                biographic_digest.ACTIVE_INVESTIGATION_EXECUTION_LOG_PATH,
                coverage_milestone.FIRST_MILESTONE_PATH,
                coverage_milestone.MILESTONE_LOG_PATH,
                cognitive_response.TRACE_PATH,
            ) = old_paths


def test_sleep_cycle_seeds_epistemic_gap_and_executes_interventional_edge():
    from ultronpro import active_investigation, causal_graph, epistemic_curiosity, sandbox_client, sleep_cycle

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        old_paths = (
            sleep_cycle.EPISODIC_PATH,
            sleep_cycle.EPISODIC_ARCHIVE_PATH,
            sleep_cycle.ABSTRACTIONS_PATH,
            sleep_cycle.REPORT_PATH,
            sleep_cycle.AUDIT_PATH,
            sleep_cycle._load_recent_action_episodes,
            active_investigation.INVESTIGATION_LOG_PATH,
            active_investigation.INVESTIGATION_STATE_PATH,
            active_investigation.INVESTIGATION_EXECUTION_LOG_PATH,
            active_investigation.INVESTIGATION_EXECUTION_STATE_PATH,
            causal_graph.GRAPH_PATH,
            causal_graph.EDGE_LOG_PATH,
            sandbox_client.execute_python,
            epistemic_curiosity.collect_epistemic_gaps,
        )

        sleep_cycle.EPISODIC_PATH = root / "episodic_memory.jsonl"
        sleep_cycle.EPISODIC_ARCHIVE_PATH = root / "episodic_memory_archive.jsonl"
        sleep_cycle.ABSTRACTIONS_PATH = root / "episodic_abstractions.json"
        sleep_cycle.REPORT_PATH = root / "sleep_cycle_report.json"
        sleep_cycle.AUDIT_PATH = root / "episodic_audit.jsonl"
        sleep_cycle._load_recent_action_episodes = lambda hours=48: []
        active_investigation.INVESTIGATION_LOG_PATH = root / "active_investigations.jsonl"
        active_investigation.INVESTIGATION_STATE_PATH = root / "active_investigation_state.json"
        active_investigation.INVESTIGATION_EXECUTION_LOG_PATH = root / "active_investigation_executions.jsonl"
        active_investigation.INVESTIGATION_EXECUTION_STATE_PATH = root / "active_investigation_execution_state.json"
        causal_graph.GRAPH_PATH = root / "causal_graph.json"
        causal_graph.EDGE_LOG_PATH = root / "causal_graph_edges.jsonl"
        sandbox_client.execute_python = _fake_sandbox_execute

        def fake_collect_epistemic_gaps(*, use_cache: bool = True):
            return [
                epistemic_curiosity.EpistemicGap(
                    id="causal_graph_interventional_coverage",
                    label="cobertura interventional do grafo causal",
                    domain="causal_graph",
                    metric="edges=0 strong=0 weak=0",
                    priority=0.91,
                    evidence={"test": "sleep_seed"},
                    next_experiment="converter lacuna em experimento sandboxado e aresta causal interventiva",
                )
            ]

        epistemic_curiosity.collect_epistemic_gaps = fake_collect_epistemic_gaps

        try:
            report = sleep_cycle.run_cycle(retention_days=14, max_active_rows=3000)

            perception = report["epistemic_gap_perception"]
            assert perception["ok"] is True
            assert perception["seeded"] == 1

            gap = report["causal_gap_investigation"]
            assert gap["pending_before"] == 1
            assert gap["executed"] == 1
            assert gap["injected"] == 1

            graph = causal_graph.load_graph()
            edges = list(graph["edges"].values())
            injected = [edge for edge in edges if "active_investigation_executor" in edge.get("sources", [])]
            assert injected
            assert injected[0]["knowledge_type"] == "interventional_weak"
        finally:
            (
                sleep_cycle.EPISODIC_PATH,
                sleep_cycle.EPISODIC_ARCHIVE_PATH,
                sleep_cycle.ABSTRACTIONS_PATH,
                sleep_cycle.REPORT_PATH,
                sleep_cycle.AUDIT_PATH,
                sleep_cycle._load_recent_action_episodes,
                active_investigation.INVESTIGATION_LOG_PATH,
                active_investigation.INVESTIGATION_STATE_PATH,
                active_investigation.INVESTIGATION_EXECUTION_LOG_PATH,
                active_investigation.INVESTIGATION_EXECUTION_STATE_PATH,
                causal_graph.GRAPH_PATH,
                causal_graph.EDGE_LOG_PATH,
                sandbox_client.execute_python,
                epistemic_curiosity.collect_epistemic_gaps,
            ) = old_paths
