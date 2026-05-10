import sys
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def test_cognitive_core_no_coverage_returns_calibrated_gap_signal(tmp_path, monkeypatch):
    from ultronpro import active_investigation, cognitive_response

    monkeypatch.setattr(active_investigation, "INVESTIGATION_LOG_PATH", tmp_path / "active_investigations.jsonl")
    monkeypatch.setattr(active_investigation, "INVESTIGATION_STATE_PATH", tmp_path / "active_investigation_state.json")
    monkeypatch.setattr(active_investigation, "_register_in_causal_graph", lambda report: {"ok": True, "edge": {}})
    monkeypatch.setattr(
        active_investigation,
        "_learned_route",
        lambda query: {"routed": False, "module": "memory", "method": "test_no_coverage"},
    )
    monkeypatch.setattr(active_investigation, "_probe_causal_graph", lambda query: {"ok": True, "count": 0, "items": []})
    monkeypatch.setattr(active_investigation, "_probe_episodic_memory", lambda query, task_type: {"ok": True, "count": 0, "summary": ""})
    monkeypatch.setattr(active_investigation, "_probe_store", lambda query: {"ok": True, "triples": [], "insights": [], "experiences": []})
    monkeypatch.setattr(active_investigation, "_probe_workspace", lambda: {"ok": True, "count": 0, "items": []})
    monkeypatch.setattr(active_investigation, "_probe_runtime_state", lambda: {"ok": True, "files": {}})
    monkeypatch.setattr(
        cognitive_response.CognitiveResponseEngine,
        "_transfer_prior",
        staticmethod(lambda query, *, reason, task_type, learned_route: None),
    )

    engine = cognitive_response.CognitiveResponseEngine()
    for answerer in (engine.operational, engine.dialogue, engine.episodic, engine.simulation, engine.symbolic):
        monkeypatch.setattr(answerer, "answer", lambda query, task_type: None)

    result = engine.answer("O protocolo azorq-91 causou o episodio limiar em nebula-x?", task_type="memory")

    assert result["resolved"] is True
    assert result["strategy"] == "non_llm_active_investigation"
    assert result["confidence"] <= 0.44
    assert "UNKNOWN" in result["answer"]
    assert "com certeza" not in result["answer"].lower()

    gap = result["gap_signal"]
    assert gap["schema"] == "ultron.cognitive_gap_signal.v1"
    assert gap["reason"] == "no_structured_coverage"
    assert "aresta_causal_relevante" in gap["missing_slots"]
    assert "episodio_relevante" in gap["missing_slots"]
    assert "causal_graph" in gap["open_dimensions"]
    assert "episodic_memory" in gap["open_dimensions"]
    assert gap["next_step"]["requires_sandbox"] is True
    assert gap["next_step"]["experiment"]["kind"] == "causal_graph_enrichment"


def test_active_gap_intervention_executes_sandbox_and_records_episode(tmp_path, monkeypatch):
    from ultronpro import active_investigation, causal_graph, episodic_memory, sandbox_client, store

    monkeypatch.setattr(active_investigation, "INVESTIGATION_LOG_PATH", tmp_path / "active_investigations.jsonl")
    monkeypatch.setattr(active_investigation, "INVESTIGATION_STATE_PATH", tmp_path / "active_investigation_state.json")
    monkeypatch.setattr(active_investigation, "INVESTIGATION_EXECUTION_LOG_PATH", tmp_path / "active_investigation_executions.jsonl")
    monkeypatch.setattr(active_investigation, "INVESTIGATION_EXECUTION_STATE_PATH", tmp_path / "active_investigation_execution_state.json")
    monkeypatch.setattr(causal_graph, "GRAPH_PATH", tmp_path / "causal_graph.json")
    monkeypatch.setattr(causal_graph, "EDGE_LOG_PATH", tmp_path / "causal_graph_edges.jsonl")
    monkeypatch.setattr(store, "publish_workspace", lambda *args, **kwargs: 1)

    recorded_episodes = []
    monkeypatch.setattr(episodic_memory, "append_episode", lambda **kwargs: recorded_episodes.append(kwargs) or {"ok": True})

    def fake_execute_python(code: str, timeout_sec: int = 10):
        namespace = {}
        captured = StringIO()
        with redirect_stdout(captured):
            exec(code, namespace, namespace)
        return {"ok": True, "returncode": 0, "stdout": captured.getvalue(), "stderr": ""}

    monkeypatch.setattr(sandbox_client, "execute_python", fake_execute_python)

    gap_signal = {
        "schema": "ultron.cognitive_gap_signal.v1",
        "source": "metacog_orchestrator",
        "reason": "metacognitive_no_coverage",
        "task_type": "planning",
        "query_terms": ["azorq", "nebula", "limiar"],
        "missing_slots": ["aresta_causal_relevante", "episodio_relevante"],
        "open_dimensions": ["causal_graph", "episodic_memory"],
        "module_gaps": [
            {"missing_slot": "aresta_causal_relevante", "dimension": "causal_graph"},
            {"missing_slot": "episodio_relevante", "dimension": "episodic_memory"},
        ],
        "coverage": {"causal_hint_count": 0, "episodic_similar_count": 0, "rag_doc_count": 0},
        "next_step": {
            "type": "minimal_intervention",
            "requires_sandbox": True,
            "experiment": {
                "kind": "causal_graph_enrichment",
                "target_route": "causal_graph",
                "query_terms": ["azorq", "nebula", "limiar"],
                "action": "executar intervencao minima sandboxada",
                "acceptance": "registrar aresta causal ou manter UNKNOWN",
            },
        },
    }

    result = active_investigation.run_minimal_intervention_for_gap_signal(
        "O protocolo azorq-91 causou o episodio limiar em nebula-x?",
        gap_signal=gap_signal,
        task_type="planning",
        source="test",
    )

    assert result["ok"] is True
    assert result["executed"] is True
    assert result["injected"] is True
    assert result["episodic_recorded"] is True
    assert recorded_episodes
    assert recorded_episodes[0]["kind"] == "active_gap_intervention"
    assert "episodio_relevante" in recorded_episodes[0]["meta"]["missing_slots"]

    lookup = causal_graph.query_for_problem("azorq nebula limiar", limit=3)
    assert lookup["count"] >= 1
    assert "active_investigation_gap" in lookup["items"][0]["cause"]


def test_metacog_no_coverage_helper_forces_unknown_learning_proposal():
    from ultronpro import main

    gap = main._build_metacog_gap_signal(
        "Planeje a politica para o dominio inedito azorq-91",
        task_type="planning",
        causal_hints={"count": 0, "items": []},
        episodic_similar=[],
        query_sig={"uncertainty": "high"},
        rag_docs=[],
    )
    answer = main._render_metacog_gap_answer(
        gap,
        {
            "executed": True,
            "injected": True,
            "episodic_recorded": True,
            "next_experiment": {"kind": "causal_graph_enrichment"},
        },
    )

    assert main._metacog_gap_requires_uncertainty(gap) is True
    assert "UNKNOWN" in answer
    assert "Lacunas especificas" in answer
    assert "Proposta de aprendizado" in answer
    assert "Intervencao minima executada no sandbox" in answer
