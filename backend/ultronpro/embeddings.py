"""Embeddings module using sentence-transformers (all-MiniLM-L6-v2).

Provides semantic search over experiences and triples.
Model is loaded lazily on first use to avoid startup delay.
"""
from __future__ import annotations

import json
import os
import math
from typing import Any

try:
    import numpy as np
except Exception:
    np = None

_model = None
_model_name = os.getenv('ULTRON_EMBED_MODEL', 'all-MiniLM-L6-v2')


def _backend() -> str:
    return str(os.getenv("ULTRON_EMBEDDINGS_BACKEND", "local") or "local").strip().lower()


def _local_embedding_enabled() -> bool:
    return _backend() in {"auto", "local", "rust", "lightweight"}


def _transformer_enabled() -> bool:
    return _backend() in {"auto", "transformer", "sentence-transformers", "sentence_transformers"}


def _embed_local(text: str) -> list[float]:
    from ultronpro import local_inference

    return local_inference.embed_text(text)


def _embed_local_batch(texts: list[str]) -> list[list[float]]:
    from ultronpro import local_inference

    return local_inference.embed_texts(texts)


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(_model_name)
    return _model


def embed_text(text: str) -> list[float]:
    """Return embedding vector for a single text."""
    if _backend() in {"local", "rust", "lightweight"}:
        return _embed_local(text)
    if _transformer_enabled():
        try:
            model = _get_model()
            vec = model.encode(text, convert_to_numpy=True)
            return vec.tolist()
        except Exception:
            if not _local_embedding_enabled():
                raise
    return _embed_local(text)


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Batch embed multiple texts."""
    if not texts:
        return []
    if _backend() in {"local", "rust", "lightweight"}:
        return _embed_local_batch(texts)
    if _transformer_enabled():
        try:
            model = _get_model()
            vecs = model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
            return [v.tolist() for v in vecs]
        except Exception:
            if not _local_embedding_enabled():
                raise
    return _embed_local_batch(texts)


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    if not a or not b:
        return 0.0
    if np is None:
        n = min(len(a), len(b))
        if n <= 0:
            return 0.0
        dot = sum(float(a[i]) * float(b[i]) for i in range(n))
        norm_a = math.sqrt(sum(float(x) * float(x) for x in a[:n]))
        norm_b = math.sqrt(sum(float(x) * float(x) for x in b[:n]))
        denom = norm_a * norm_b
        return 0.0 if denom == 0 else float(dot / denom)
    a_np = np.array(a)
    b_np = np.array(b)
    denom = (np.linalg.norm(a_np) * np.linalg.norm(b_np))
    if denom == 0:
        return 0.0
    return float(np.dot(a_np, b_np) / denom)


def search_similar(
    query_vec: list[float],
    candidates: list[dict[str, Any]],
    vec_key: str = "embedding",
    top_k: int = 10,
    min_score: float = 0.0,
) -> list[tuple[dict[str, Any], float]]:
    """Search candidates by cosine similarity to query vector.
    
    Returns list of (candidate, score) tuples sorted by score descending.
    """
    results = []
    for c in candidates:
        vec = c.get(vec_key)
        if not vec:
            continue
        score = cosine_similarity(query_vec, vec)
        if score >= min_score:
            results.append((c, score))
    results.sort(key=lambda x: x[1], reverse=True)
    return results[:top_k]


def embedding_to_json(vec: list[float]) -> str:
    """Serialize embedding to JSON for storage."""
    return json.dumps(vec)


def embedding_from_json(s: str | None) -> list[float] | None:
    """Deserialize embedding from JSON."""
    if not s:
        return None
    try:
        return json.loads(s)
    except Exception:
        return None
