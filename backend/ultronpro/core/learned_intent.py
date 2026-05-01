"""Episode-learned semantic routing.

The classifier here learns from actual route outcomes:

- explicit chat route episodes recorded by the runtime;
- decision traces produced by metacognition/voice routes;
- autobiographical/self-introspection episodes as lower-weight evidence.

It does not try to guess user wording. It asks: among past semantically similar
inputs, which module actually helped?
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from functools import lru_cache
import datetime as dt
import json
import math
import os
from pathlib import Path
import re
import time
from typing import Any


DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
ROUTE_EPISODES_PATH = DATA_DIR / "intent_route_episodes.jsonl"
DECISION_TRACE_DIR = DATA_DIR / "decision_traces"
EPISODIC_PATH = DATA_DIR / "episodic_memory.jsonl"


@dataclass(frozen=True)
class LearnedRoutePrediction:
    module: str
    confidence: float
    method: str
    evidence_count: int
    examples_seen: int
    top_similarity: float = 0.0
    margin: float = 0.0
    module_scores: dict[str, float] | None = None
    evidence: tuple[dict[str, Any], ...] = ()

    @property
    def routed(self) -> bool:
        return bool(self.module and self.module != "unknown" and self.evidence_count > 0)

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["routed"] = self.routed
        return out


def _enabled() -> bool:
    value = str(os.getenv("ULTRON_LEARNED_INTENT_ENABLED", "1") or "1").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _embedding_enabled() -> bool:
    value = str(os.getenv("ULTRON_INTENT_EMBEDDINGS_ENABLED", "1") or "1").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _safe_text(value: Any, limit: int = 1800) -> str:
    return " ".join(str(value or "").strip().split())[:limit]


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-zA-ZÀ-ÿ0-9_]{3,}", str(text or "").lower())}


def _token_similarity(left: str, right: str) -> float:
    a = _tokens(left)
    b = _tokens(right)
    if not a or not b:
        return 0.0
    return len(a & b) / max(1, len(a | b))


def _canonical_module(strategy: str = "", task_type: str = "", meta: dict[str, Any] | None = None) -> str:
    s = _safe_text(strategy, 120).lower()
    tt = _safe_text(task_type, 120).lower()
    joined = f"{s} {tt}"
    if tt == "self_introspection" or bool((meta or {}).get("autobiographical")):
        return "autobiographical"

    module = _safe_text((meta or {}).get("module"), 80).lower()
    if module:
        return module

    if s.startswith("autobiographical") or "identity" in joined or tt == "self_introspection":
        return "autobiographical"
    if s.startswith("skill_"):
        return "skills"
    if "symbolic" in joined:
        return "symbolic"
    if s.startswith("local_") or "local_logic" in joined:
        return "local_reasoning"
    if "semantic_cache" in joined or s == "cache":
        return "semantic_cache"
    if "rag" in joined:
        return "knowledge"
    if "orchestrator" in joined or "own_reasoning" in joined or "deep_" in joined:
        return "reasoning"
    if "clarify" in joined or "unavailable" in joined or "insufficient" in joined:
        return "insufficient"
    if s:
        return re.sub(r"[^a-z0-9_]+", "_", s)[:80] or "unknown"
    return "unknown"


def _outcome_ok(row: dict[str, Any]) -> bool:
    label = row.get("feedback_label")
    if isinstance(label, bool):
        return bool(label)
    if isinstance(label, str):
        low = label.strip().lower()
        if low in {"good", "accept", "accepted", "ok", "true", "1"}:
            return True
        if low in {"bad", "reject", "rejected", "fail", "false", "0"}:
            return False

    if "ok" in row:
        return bool(row.get("ok"))

    outcome = str(row.get("final_outcome") or row.get("outcome") or "").lower()
    if any(marker in outcome for marker in ("fail", "error", "unavailable", "fallback")):
        return False
    return outcome in {"success", "completed", "ok", "done"} or not outcome


def _read_jsonl(path: Path, limit: int) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return []
    for line in lines[-max(1, int(limit or 1)) :]:
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except Exception:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def _mtime(path: Path) -> int:
    try:
        return int(path.stat().st_mtime)
    except Exception:
        return 0


def _trace_signature() -> tuple[Any, ...]:
    if not DECISION_TRACE_DIR.exists():
        return ()
    files = sorted(DECISION_TRACE_DIR.glob("*.jsonl"))[-8:]
    return tuple((p.name, _mtime(p), p.stat().st_size if p.exists() else 0) for p in files)


def _cache_signature() -> tuple[Any, ...]:
    return (
        _mtime(ROUTE_EPISODES_PATH),
        ROUTE_EPISODES_PATH.stat().st_size if ROUTE_EPISODES_PATH.exists() else 0,
        _trace_signature(),
        _mtime(EPISODIC_PATH),
        EPISODIC_PATH.stat().st_size if EPISODIC_PATH.exists() else 0,
    )


def record_route_episode(
    query: str,
    *,
    module: str | None = None,
    strategy: str = "",
    ok: bool = True,
    latency_ms: int = 0,
    source: str = "chat",
    outcome: str = "success",
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    text = _safe_text(query, 2500)
    if not text:
        return {"ok": False, "reason": "empty_query"}

    meta_obj = dict(meta or {})
    chosen_module = _safe_text(module or "", 80).lower() or _canonical_module(strategy, source, meta_obj)
    row = {
        "ts": int(time.time()),
        "query": text,
        "module": chosen_module,
        "strategy": _safe_text(strategy, 120),
        "ok": bool(ok),
        "latency_ms": int(latency_ms or 0),
        "source": _safe_text(source, 80),
        "outcome": _safe_text(outcome, 80),
        "meta": meta_obj,
    }

    try:
        ROUTE_EPISODES_PATH.parent.mkdir(parents=True, exist_ok=True)
        with ROUTE_EPISODES_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        _cached_examples.cache_clear()
        return {"ok": True, "path": str(ROUTE_EPISODES_PATH), "module": chosen_module}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _explicit_examples(limit: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in _read_jsonl(ROUTE_EPISODES_PATH, limit=limit):
        query = _safe_text(row.get("query"), 2500)
        module = _safe_text(row.get("module"), 80).lower()
        if not query or not module:
            continue
        out.append(
            {
                "query": query,
                "module": module,
                "ok": bool(row.get("ok", True)),
                "strategy": _safe_text(row.get("strategy"), 120),
                "source": _safe_text(row.get("source") or "route_episode", 80),
                "ts": int(row.get("ts") or 0),
                "weight": 1.0,
            }
        )
    return out


def _decision_trace_examples(limit: int) -> list[dict[str, Any]]:
    if not DECISION_TRACE_DIR.exists():
        return []
    rows: list[dict[str, Any]] = []
    files = sorted(DECISION_TRACE_DIR.glob("*.jsonl"))[-8:]
    per_file = max(20, int(limit / max(1, len(files))))
    for path in files:
        rows.extend(_read_jsonl(path, limit=per_file))

    out: list[dict[str, Any]] = []
    for row in rows[-limit:]:
        query = _safe_text(row.get("input"), 2500)
        meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
        strategy = _safe_text(meta.get("strategy") or row.get("route"), 120)
        module = _canonical_module(strategy, str(row.get("task_type") or ""), meta)
        if not query or module == "unknown":
            continue
        out.append(
            {
                "query": query,
                "module": module,
                "ok": _outcome_ok(row),
                "strategy": strategy,
                "source": "decision_trace",
                "ts": int(row.get("ts") or 0),
                "weight": 0.9,
            }
        )
    return out


def _episodic_examples(limit: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in _read_jsonl(EPISODIC_PATH, limit=limit):
        meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
        query = _safe_text(
            meta.get("query")
            or meta.get("user_query")
            or meta.get("input")
            or meta.get("problem")
            or row.get("text"),
            2500,
        )
        strategy = _safe_text(row.get("strategy"), 120)
        module = _canonical_module(strategy, str(row.get("task_type") or ""), meta)
        if not query or module == "unknown":
            continue
        weight = 0.55
        if meta.get("query") or meta.get("user_query") or meta.get("input"):
            weight = 0.8
        out.append(
            {
                "query": query,
                "module": module,
                "ok": bool(row.get("ok", True)),
                "strategy": strategy,
                "source": "episodic_memory",
                "ts": int(row.get("ts") or 0),
                "weight": weight,
            }
        )
    return out


@lru_cache(maxsize=4)
def _cached_examples(signature: tuple[Any, ...], max_examples: int) -> tuple[dict[str, Any], ...]:
    explicit = _explicit_examples(limit=max_examples)
    traces = _decision_trace_examples(limit=max_examples)
    episodic = _episodic_examples(limit=max_examples)
    merged = explicit + traces + episodic
    merged.sort(key=lambda item: (int(item.get("ts") or 0), float(item.get("weight") or 0.0)), reverse=True)
    return tuple(merged[:max_examples])


def _examples(max_examples: int) -> tuple[dict[str, Any], ...]:
    return _cached_examples(_cache_signature(), int(max_examples or 500))


def _with_embeddings(
    query: str,
    examples: tuple[dict[str, Any], ...],
    *,
    enabled: bool | None = None,
) -> list[tuple[float, dict[str, Any]]]:
    if enabled is False:
        return []
    if enabled is None and not _embedding_enabled():
        return []
    try:
        from ultronpro import embeddings

        qv = embeddings.embed_text(query)
        texts = [str(ex.get("query") or "") for ex in examples]
        vectors = embeddings.embed_texts(texts)
        scored: list[tuple[float, dict[str, Any]]] = []
        for ex, vec in zip(examples, vectors):
            try:
                scored.append((float(embeddings.cosine_similarity(qv, vec)), ex))
            except Exception:
                continue
        return scored
    except Exception:
        return []


def _with_tokens(query: str, examples: tuple[dict[str, Any], ...]) -> list[tuple[float, dict[str, Any]]]:
    return [(_token_similarity(query, str(ex.get("query") or "")), ex) for ex in examples]


def predict_route(query: str, *, max_examples: int | None = None, use_embeddings: bool | None = None) -> LearnedRoutePrediction:
    if not _enabled():
        return LearnedRoutePrediction(
            module="unknown",
            confidence=0.0,
            method="disabled",
            evidence_count=0,
            examples_seen=0,
        )

    text = _safe_text(query, 2500)
    if not text:
        return LearnedRoutePrediction(
            module="unknown",
            confidence=0.0,
            method="empty_query",
            evidence_count=0,
            examples_seen=0,
        )

    max_examples = int(max_examples or os.getenv("ULTRON_LEARNED_INTENT_MAX_EXAMPLES", "500") or 500)
    examples = _examples(max_examples)
    if not examples:
        return LearnedRoutePrediction(
            module="unknown",
            confidence=0.0,
            method="no_episode_evidence",
            evidence_count=0,
            examples_seen=0,
        )

    scored = _with_embeddings(text, examples, enabled=use_embeddings)
    method = "episode_embeddings"
    if not scored:
        scored = _with_tokens(text, examples)
        method = "episode_token_similarity"

    sim_floor = float(os.getenv("ULTRON_LEARNED_INTENT_SIM_FLOOR", "0.38") or 0.38)
    half_life_days = float(os.getenv("ULTRON_LEARNED_INTENT_RECENCY_HALFLIFE_DAYS", "30") or 30)
    now = int(time.time())

    module_scores: dict[str, float] = {}
    evidence: list[dict[str, Any]] = []
    for sim, ex in sorted(scored, key=lambda item: item[0], reverse=True):
        if sim < sim_floor:
            continue
        module = _safe_text(ex.get("module"), 80).lower()
        if not module or module == "unknown":
            continue
        ts = int(ex.get("ts") or 0)
        age_days = max(0.0, (now - ts) / 86400.0) if ts else half_life_days
        recency = math.pow(0.5, age_days / max(1.0, half_life_days))
        signed = 1.0 if bool(ex.get("ok", True)) else -0.7
        weight = float(ex.get("weight") or 1.0) * (0.6 + 0.4 * recency)
        score = float(sim) * weight * signed
        module_scores[module] = module_scores.get(module, 0.0) + score
        evidence.append(
            {
                "module": module,
                "similarity": round(float(sim), 4),
                "strategy": ex.get("strategy"),
                "ok": bool(ex.get("ok", True)),
                "source": ex.get("source"),
            }
        )

    positive = {k: v for k, v in module_scores.items() if v > 0}
    if not positive:
        return LearnedRoutePrediction(
            module="unknown",
            confidence=0.0,
            method=method,
            evidence_count=0,
            examples_seen=len(examples),
            module_scores={k: round(v, 4) for k, v in module_scores.items()},
        )

    ranked = sorted(positive.items(), key=lambda item: item[1], reverse=True)
    top_module, top_score = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else 0.0
    denom = sum(abs(v) for v in module_scores.values()) or 1.0
    confidence = max(0.0, min(1.0, top_score / denom))
    top_similarity = max((float(e.get("similarity") or 0.0) for e in evidence if e.get("module") == top_module), default=0.0)
    return LearnedRoutePrediction(
        module=top_module,
        confidence=round(confidence, 4),
        method=method,
        evidence_count=sum(1 for e in evidence if e.get("module") == top_module),
        examples_seen=len(examples),
        top_similarity=round(top_similarity, 4),
        margin=round(float(top_score - second), 4),
        module_scores={k: round(v, 4) for k, v in module_scores.items()},
        evidence=tuple(evidence[:8]),
    )


def status() -> dict[str, Any]:
    examples = _examples(int(os.getenv("ULTRON_LEARNED_INTENT_MAX_EXAMPLES", "500") or 500))
    by_module: dict[str, int] = {}
    for ex in examples:
        module = str(ex.get("module") or "unknown")
        by_module[module] = by_module.get(module, 0) + 1
    return {
        "ok": True,
        "enabled": _enabled(),
        "embedding_enabled": _embedding_enabled(),
        "route_episode_path": str(ROUTE_EPISODES_PATH),
        "decision_trace_dir": str(DECISION_TRACE_DIR),
        "episodic_path": str(EPISODIC_PATH),
        "examples": len(examples),
        "by_module": by_module,
    }
