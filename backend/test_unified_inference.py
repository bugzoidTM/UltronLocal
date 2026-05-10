import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def test_inference_frame_requires_premises_before_conclusion():
    from ultronpro.unified_inference import InferenceFrame

    frame = InferenceFrame("pergunta nova", task_type="unknown")
    conclusion = frame.decide(statement="resposta sem evidencia", threshold=0.5)
    data = frame.to_dict()

    assert conclusion["resolved"] is False
    assert data["formalism"] == "weighted_support_graph_v1"
    assert data["gaps"][0]["missing_slot"] == "premise"
    assert data["inference_steps"][0]["rule"] == "threshold_rejection"


def test_inference_frame_selects_supported_candidate():
    from ultronpro.unified_inference import InferenceFrame

    frame = InferenceFrame("deploy com rollback", task_type="operations")
    p1 = frame.add_premise(
        source="causal_graph",
        modality="causal_edge",
        statement="rollback guard reduces partial deploy risk",
        confidence=0.76,
    )
    frame.infer(
        rule="modus_support_by_causal_edge",
        rule_type="support",
        input_ids=[p1],
        conclusion="usar rollback antes de deploy",
    )
    conclusion = frame.decide(
        statement="usar rollback antes de deploy",
        selected_source="symbolic_causal",
        strategy="non_llm_symbolic_causal",
    )

    assert conclusion["resolved"] is True
    assert conclusion["confidence"] >= 0.76
    assert frame.to_dict()["conclusion"]["selected_source"] == "symbolic_causal"


def test_semantic_cache_hit_carries_inference_trace(tmp_path, monkeypatch):
    from ultronpro import semantic_cache

    monkeypatch.setattr(semantic_cache, "CACHE_PATH", tmp_path / "semantic_cache.json")
    assert semantic_cache.store("Como fortalecer memoria episodica?", "Use episodios estruturados.", "unit")

    hit = semantic_cache.lookup("Como fortalecer memoria episodica?")

    assert hit["cache_hit"] == "exact"
    assert hit["inference_trace"]["schema"] == "ultron.unified_inference.v1"
    assert hit["inference_trace"]["conclusion"]["selected_source"] == "semantic_cache"


def test_local_reasoning_result_carries_inference_trace():
    from ultronpro import local_reasoning_engine

    result = local_reasoning_engine.resolve("calcule 2 + 2")

    assert result["resolved"] is True
    assert result["method"] == "math"
    assert result["inference_trace"]["formalism"] == "weighted_support_graph_v1"
    assert result["inference_trace"]["conclusion"]["resolved"] is True


def test_cognitive_response_success_carries_inference_trace():
    from ultronpro import cognitive_response

    old_engine = cognitive_response._ENGINE
    cognitive_response._ENGINE = None
    try:
        result = cognitive_response.answer("Qual LLM vc usa?")
    finally:
        cognitive_response._ENGINE = old_engine

    assert result["resolved"] is True
    assert result["inference_trace"]["schema"] == "ultron.unified_inference.v1"
    assert result["inference_trace"]["conclusion"]["selected_source"] == result["module"]
