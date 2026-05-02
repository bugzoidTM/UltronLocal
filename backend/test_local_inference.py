import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def test_local_inference_embeddings_and_vector_search():
    from ultronpro import local_inference

    vec = local_inference.embed_text("memoria episodica causal", prefer_rust=False)
    assert len(vec) == 128
    assert abs(sum(v * v for v in vec) - 1.0) < 0.01

    results = local_inference.vector_search(
        "memoria episodica causal",
        [
            {"id": "a", "text": "receita de bolo simples"},
            {"id": "b", "text": "memoria episodica estruturada com causalidade"},
        ],
        top_k=2,
    )
    assert results[0]["id"] == "b"
    assert results[0]["_local_inference_backend"] in {"python", "rust"}


def test_local_inference_symbolic_intent_and_event_parser():
    from ultronpro import local_inference

    intent = local_inference.classify_intent("Qual LLM voce usa?", prefer_rust=False)
    assert intent["label"] == "autobiographical"
    assert intent["confidence"] >= 0.8

    event = local_inference.parse_event("unit", "HTTP API timeout failed", prefer_rust=False)
    assert event["event_type"] == "network"
    assert event["severity"] == "error"


def test_embeddings_module_can_force_local_backend(monkeypatch):
    monkeypatch.setenv("ULTRON_EMBEDDINGS_BACKEND", "local")

    from ultronpro import embeddings

    a = embeddings.embed_text("busca vetorial leve")
    b = embeddings.embed_text("busca vetorial leve")
    c = embeddings.embed_text("assunto muito diferente")

    assert len(a) == 128
    assert embeddings.cosine_similarity(a, b) > embeddings.cosine_similarity(a, c)


def test_semantic_cache_uses_local_embeddings(tmp_path, monkeypatch):
    monkeypatch.setenv("ULTRON_EMBEDDINGS_BACKEND", "local")

    from ultronpro import semantic_cache

    monkeypatch.setattr(semantic_cache, "CACHE_PATH", tmp_path / "semantic_cache.json")
    assert semantic_cache.store("Como fortalecer memoria episodica?", "Use episodios estruturados.", "unit")
    hit = semantic_cache.lookup("Como fortalecer memoria episodica?")
    assert hit is not None
    assert hit["cache_hit"] == "exact"


def test_plasticity_rerank_prefers_local_relevance(monkeypatch):
    monkeypatch.setenv("ULTRON_LOCAL_RERANK_ENABLED", "1")

    from ultronpro import plasticity_runtime

    ranked = plasticity_runtime.rerank_with_hard_negatives(
        "memoria episodica causal",
        [
            {"id": "x", "text": "frontend visual"},
            {"id": "y", "text": "memoria episodica com consequencia causal"},
        ],
        top_k=2,
    )
    assert ranked[0]["id"] == "y"


def test_sensory_bus_enriches_events_with_local_parser(monkeypatch):
    monkeypatch.setenv("ULTRON_LOCAL_EVENT_PARSE_ENABLED", "1")

    from ultronpro import sensory_bus

    event = sensory_bus.normalize_event(
        source_type="logs",
        source="unit",
        payload={"text": "HTTP API timeout failed"},
        consent_scope="diagnostic_log",
    )
    parsed = event.metadata.get("local_event_parse") or {}
    assert parsed.get("event_type") == "network"
    assert parsed.get("severity") == "error"
    assert event.salience >= 0.78
