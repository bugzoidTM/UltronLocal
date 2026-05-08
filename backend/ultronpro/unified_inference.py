from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math
import time
from typing import Any


SCHEMA = "ultron.unified_inference.v1"
FORMALISM = "weighted_support_graph_v1"


def _clip(value: Any, limit: int = 420) -> str:
    text = " ".join(str(value or "").split())
    return text[: max(1, int(limit or 1))]


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        number = float(value)
        if math.isnan(number) or math.isinf(number):
            return default
        return max(0.0, min(1.0, number))
    except Exception:
        return default


def _compact_payload(payload: Any, *, depth: int = 0) -> Any:
    if depth >= 3:
        return _clip(payload, 240)
    if isinstance(payload, dict):
        out: dict[str, Any] = {}
        for key, value in list(payload.items())[:16]:
            out[str(key)[:80]] = _compact_payload(value, depth=depth + 1)
        return out
    if isinstance(payload, list):
        return [_compact_payload(item, depth=depth + 1) for item in payload[:8]]
    if isinstance(payload, (str, int, float, bool)) or payload is None:
        return payload if not isinstance(payload, str) else _clip(payload, 500)
    return _clip(payload, 300)


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _noisy_or(confidences: list[float]) -> float:
    miss = 1.0
    for conf in confidences:
        miss *= 1.0 - _safe_float(conf)
    return round(max(0.0, min(1.0, 1.0 - miss)), 4)


@dataclass
class Premise:
    id: str
    source: str
    modality: str
    statement: str
    confidence: float = 0.5
    role: str = "evidence"
    payload: Any = None


@dataclass
class InferenceStep:
    id: str
    rule: str
    rule_type: str
    input_ids: list[str]
    conclusion: str
    confidence: float
    rationale: str = ""
    payload: Any = None


@dataclass
class InferenceGap:
    id: str
    dimension: str
    missing_slot: str
    gap_kind: str
    reason: str
    proposed_intervention: dict[str, Any] = field(default_factory=dict)
    source: str = "unified_inference"


class InferenceFrame:
    """Deterministic support graph for reasoning across cache/RAG/symbolic/LLM paths."""

    def __init__(self, query: str, *, task_type: str = "general"):
        self.query = str(query or "")
        self.task_type = str(task_type or "general")
        self.created_at = int(time.time())
        self.premises: list[Premise] = []
        self.steps: list[InferenceStep] = []
        self.gaps: list[InferenceGap] = []
        self.conclusion: dict[str, Any] = {
            "resolved": False,
            "statement": "",
            "confidence": 0.0,
            "selected_source": "",
        }

    def add_premise(
        self,
        *,
        source: str,
        modality: str,
        statement: str,
        confidence: float = 0.5,
        role: str = "evidence",
        payload: Any = None,
    ) -> str:
        pid = f"p{len(self.premises) + 1}"
        self.premises.append(
            Premise(
                id=pid,
                source=str(source or "unknown")[:80],
                modality=str(modality or "unknown")[:80],
                statement=_clip(statement, 700),
                confidence=_safe_float(confidence, 0.5),
                role=str(role or "evidence")[:80],
                payload=_compact_payload(payload),
            )
        )
        return pid

    def add_gap(
        self,
        *,
        dimension: str,
        missing_slot: str,
        gap_kind: str = "missing_evidence",
        reason: str = "",
        proposed_intervention: dict[str, Any] | None = None,
        source: str = "unified_inference",
    ) -> str:
        gid = f"g{len(self.gaps) + 1}"
        self.gaps.append(
            InferenceGap(
                id=gid,
                dimension=str(dimension or "unknown")[:100],
                missing_slot=str(missing_slot or "evidence")[:120],
                gap_kind=str(gap_kind or "missing_evidence")[:120],
                reason=_clip(reason, 520),
                proposed_intervention=_compact_payload(proposed_intervention or {}),
                source=str(source or "unified_inference")[:100],
            )
        )
        return gid

    def infer(
        self,
        *,
        rule: str,
        conclusion: str,
        input_ids: list[str] | None = None,
        confidence: float | None = None,
        rule_type: str = "support",
        rationale: str = "",
        payload: Any = None,
    ) -> str:
        ids = [str(x) for x in (input_ids or []) if str(x).strip()]
        if confidence is None:
            by_id = {p.id: p for p in self.premises}
            confidence = _noisy_or([by_id[x].confidence for x in ids if x in by_id])
        sid = f"s{len(self.steps) + 1}"
        self.steps.append(
            InferenceStep(
                id=sid,
                rule=str(rule or "unknown_rule")[:120],
                rule_type=str(rule_type or "support")[:80],
                input_ids=ids,
                conclusion=_clip(conclusion, 800),
                confidence=_safe_float(confidence, 0.0),
                rationale=_clip(rationale, 600),
                payload=_compact_payload(payload),
            )
        )
        return sid

    def support_confidence(self) -> float:
        evidence = [p.confidence for p in self.premises if p.role != "rejected"]
        if not evidence:
            return 0.0
        base = _noisy_or(evidence[:8])
        count_bonus = min(0.12, 0.025 * max(0, len(evidence) - 1))
        return round(max(0.0, min(1.0, base + count_bonus)), 4)

    def decide(
        self,
        *,
        statement: str = "",
        threshold: float = 0.48,
        selected_source: str = "",
        strategy: str = "",
    ) -> dict[str, Any]:
        conf = self.support_confidence()
        threshold = _safe_float(threshold, 0.48)
        resolved = bool(statement and self.premises and conf >= threshold)
        if not self.premises:
            self.add_gap(
                dimension="internal_evidence",
                missing_slot="premise",
                gap_kind="missing_premise",
                reason="no normalized premise was available to support inference",
                proposed_intervention={
                    "type": "minimal_intervention",
                    "target_route": "evidence_collection",
                    "action": "collect at least one recoverable premise before answering",
                },
            )
        elif not resolved:
            self.add_gap(
                dimension="internal_evidence",
                missing_slot="support_confidence",
                gap_kind="support_below_threshold",
                reason=f"support_confidence={conf:.4f} threshold={threshold:.4f}",
                proposed_intervention={
                    "type": "minimal_intervention",
                    "target_route": "evidence_collection",
                    "action": "add or validate the missing premise that would raise calibrated support",
                },
            )
        self.infer(
            rule="threshold_acceptance" if resolved else "threshold_rejection",
            rule_type="decision",
            input_ids=[p.id for p in self.premises],
            conclusion=statement if resolved else "insufficient support for conclusion",
            confidence=conf,
            rationale=f"weighted support compared against threshold={threshold:.4f}",
            payload={"threshold": threshold, "strategy": strategy, "selected_source": selected_source},
        )
        self.conclusion = {
            "resolved": resolved,
            "statement": _clip(statement, 900) if resolved else "",
            "confidence": conf,
            "selected_source": str(selected_source or ""),
            "strategy": str(strategy or ""),
        }
        return dict(self.conclusion)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "formalism": FORMALISM,
            "query": _clip(self.query, 900),
            "task_type": self.task_type,
            "created_at": self.created_at,
            "premises": [asdict(p) for p in self.premises],
            "inference_steps": [asdict(step) for step in self.steps],
            "gaps": [asdict(gap) for gap in self.gaps],
            "conclusion": dict(self.conclusion),
        }

    def compact(self) -> dict[str, Any]:
        data = self.to_dict()
        return {
            "schema": data["schema"],
            "formalism": data["formalism"],
            "premise_count": len(self.premises),
            "step_count": len(self.steps),
            "gap_count": len(self.gaps),
            "premise_sources": sorted({p.source for p in self.premises})[:12],
            "open_dimensions": sorted({g.dimension for g in self.gaps})[:12],
            "conclusion": data["conclusion"],
        }


def trace_from_candidates(
    *,
    query: str,
    task_type: str,
    selected_candidate: Any | None,
    ranked_candidates: list[Any] | None = None,
    answer: str = "",
    learned_route: dict[str, Any] | None = None,
    threshold: float = 0.48,
) -> dict[str, Any]:
    frame = InferenceFrame(query, task_type=task_type)
    if learned_route:
        frame.add_premise(
            source="learned_route",
            modality="route_prior",
            statement=f"learned route suggests module={learned_route.get('module')}",
            confidence=_safe_float(learned_route.get("confidence"), 0.35) if learned_route.get("routed") else 0.20,
            role="routing_prior",
            payload=learned_route,
        )
    candidates = list(ranked_candidates or [])
    for idx, candidate in enumerate(candidates[:8], start=1):
        module = str(_get(candidate, "module", "unknown"))
        strategy = str(_get(candidate, "strategy", "unknown"))
        confidence = _safe_float(_get(candidate, "confidence", 0.0))
        sections = _get(candidate, "sections", {}) if isinstance(_get(candidate, "sections", {}), dict) else {}
        evidence = _get(candidate, "evidence", {}) if isinstance(_get(candidate, "evidence", {}), dict) else {}
        frame.add_premise(
            source=module,
            modality="candidate_answer",
            statement=f"candidate {idx} via {strategy} exposes sections={list(sections.keys())}",
            confidence=confidence,
            role="selected_candidate" if candidate is selected_candidate else "candidate",
            payload={
                "strategy": strategy,
                "sections": sections,
                "evidence_keys": list(evidence.keys()),
            },
        )
    selected_source = str(_get(selected_candidate, "module", "none")) if selected_candidate is not None else ""
    selected_strategy = str(_get(selected_candidate, "strategy", "none")) if selected_candidate is not None else ""
    if selected_candidate is not None:
        frame.infer(
            rule="rank_candidates_by_calibrated_confidence",
            rule_type="selection",
            input_ids=[p.id for p in frame.premises],
            conclusion=f"selected {selected_source}/{selected_strategy}",
            confidence=_safe_float(_get(selected_candidate, "confidence", 0.0)),
            rationale="highest calibrated candidate after learned-route adjustment",
        )
    frame.decide(
        statement=answer,
        threshold=threshold,
        selected_source=selected_source,
        strategy=selected_strategy,
    )
    return frame.to_dict()


def trace_for_gap_signal(
    *,
    query: str,
    task_type: str,
    reason: str,
    gap_signal: dict[str, Any] | None = None,
    ranked_candidates: list[Any] | None = None,
    learned_route: dict[str, Any] | None = None,
) -> dict[str, Any]:
    frame = InferenceFrame(query, task_type=task_type)
    if learned_route:
        frame.add_premise(
            source="learned_route",
            modality="route_prior",
            statement=f"route prior module={learned_route.get('module')}",
            confidence=_safe_float(learned_route.get("confidence"), 0.25),
            role="routing_prior",
            payload=learned_route,
        )
    for candidate in list(ranked_candidates or [])[:8]:
        frame.add_premise(
            source=str(_get(candidate, "module", "candidate")),
            modality="candidate_answer",
            statement=f"candidate failed threshold via {_get(candidate, 'strategy', 'unknown')}",
            confidence=_safe_float(_get(candidate, "confidence", 0.0)),
            role="rejected",
            payload={"sections": list((_get(candidate, "sections", {}) or {}).keys())},
        )
    signal = gap_signal if isinstance(gap_signal, dict) else {}
    module_gaps = signal.get("module_gaps") if isinstance(signal.get("module_gaps"), list) else []
    for gap in module_gaps:
        if not isinstance(gap, dict):
            continue
        frame.add_gap(
            dimension=str(gap.get("dimension") or "unknown"),
            missing_slot=str(gap.get("missing_slot") or "evidence"),
            gap_kind=str(gap.get("gap_kind") or "missing_evidence"),
            reason=str(gap.get("description") or reason or "unresolved_gap"),
            proposed_intervention=(signal.get("next_step") or {}).get("experiment")
            if isinstance(signal.get("next_step"), dict)
            else {},
            source=str(gap.get("module") or "gap_signal"),
        )
    frame.decide(statement="", threshold=0.48, selected_source="", strategy=str(reason or "gap"))
    return frame.to_dict()


def trace_from_local_result(query: str, result: dict[str, Any]) -> dict[str, Any]:
    frame = InferenceFrame(query, task_type="local")
    method = str((result or {}).get("method") or "local")
    resolved = bool((result or {}).get("resolved"))
    if resolved:
        frame.add_premise(
            source="local_reasoning_engine",
            modality=method,
            statement=f"local resolver returned method={method}",
            confidence=0.86 if method in {"math", "rules", "facts"} else 0.70,
            payload=result,
        )
    frame.decide(
        statement=str((result or {}).get("result") or ""),
        threshold=0.48,
        selected_source="local_reasoning_engine",
        strategy=method,
    )
    return frame.to_dict()


def trace_from_cache_hit(query: str, hit: dict[str, Any]) -> dict[str, Any]:
    frame = InferenceFrame(query, task_type="cache")
    score = _safe_float((hit or {}).get("score"), 0.0)
    if hit:
        frame.add_premise(
            source="semantic_cache",
            modality=str((hit or {}).get("cache_hit") or "cache"),
            statement=f"cache returned answer with score={score:.4f}",
            confidence=score,
            payload={"strategy": (hit or {}).get("strategy"), "cache_hit": (hit or {}).get("cache_hit")},
        )
    frame.decide(
        statement=str((hit or {}).get("answer") or ""),
        threshold=0.92,
        selected_source="semantic_cache",
        strategy=str((hit or {}).get("strategy") or "cache"),
    )
    return frame.to_dict()


def trace_from_orchestrator_inputs(
    *,
    query: str,
    task_type: str,
    rag_docs: list[Any] | None = None,
    causal_hints: dict[str, Any] | None = None,
    episodic_similar: list[Any] | None = None,
    procedural_hints: dict[str, Any] | None = None,
    context_bundle: dict[str, Any] | None = None,
    metacog_gap_signal: dict[str, Any] | None = None,
) -> InferenceFrame:
    frame = InferenceFrame(query, task_type=task_type)
    for idx, doc in enumerate(list(rag_docs or [])[:5], start=1):
        if not isinstance(doc, dict):
            continue
        score = _safe_float(doc.get("score") or doc.get("_local_inference_score"), 0.52)
        text = doc.get("text") or doc.get("content") or doc.get("summary") or doc.get("title")
        frame.add_premise(
            source="rag",
            modality="retrieved_context",
            statement=f"rag_doc_{idx}: {_clip(text, 260)}",
            confidence=max(0.25, score),
            payload={"source_id": doc.get("source_id") or doc.get("id"), "score": score},
        )
    causal_items = []
    if isinstance(causal_hints, dict):
        causal_items = causal_hints.get("items") if isinstance(causal_hints.get("items"), list) else []
    for idx, edge in enumerate(causal_items[:5], start=1):
        if not isinstance(edge, dict):
            continue
        frame.add_premise(
            source="causal_graph",
            modality="causal_edge",
            statement=f"{edge.get('cause')} -> {edge.get('effect')} when {edge.get('condition')}",
            confidence=_safe_float(edge.get("confidence") or edge.get("score"), 0.58),
            payload=edge,
        )
    for idx, ep in enumerate(list(episodic_similar or [])[:5], start=1):
        if not isinstance(ep, dict):
            continue
        text = ep.get("text") or ep.get("summary") or ep.get("problem") or ep.get("resultado")
        frame.add_premise(
            source="episodic_memory",
            modality="episode",
            statement=f"episode_{idx}: {_clip(text, 260)}",
            confidence=_safe_float(ep.get("score") or ep.get("similarity"), 0.48),
            payload={"id": ep.get("id") or ep.get("episode_id"), "strategy": ep.get("strategy")},
        )
    if isinstance(procedural_hints, dict):
        strategies = procedural_hints.get("best_strategies") if isinstance(procedural_hints.get("best_strategies"), list) else []
        for idx, strategy in enumerate(strategies[:4], start=1):
            frame.add_premise(
                source="procedural_memory",
                modality="strategy_hint",
                statement=f"procedural_hint_{idx}: {_clip(strategy, 260)}",
                confidence=0.50,
                payload=strategy,
            )
    fallback = (context_bundle or {}).get("fallback") if isinstance(context_bundle, dict) else {}
    if isinstance(fallback, dict) and fallback.get("needed"):
        frame.add_gap(
            dimension="retrieval_context",
            missing_slot="required_context",
            gap_kind="context_policy_fallback",
            reason="context policy reported missing required sources",
            proposed_intervention={"action": "retrieve required context before synthesis", "missing": fallback.get("missing_required_sources")},
            source="context_policy",
        )
    if isinstance(metacog_gap_signal, dict) and metacog_gap_signal:
        for gap in metacog_gap_signal.get("module_gaps") or []:
            if not isinstance(gap, dict):
                continue
            frame.add_gap(
                dimension=str(gap.get("dimension") or "unknown"),
                missing_slot=str(gap.get("missing_slot") or "evidence"),
                gap_kind=str(gap.get("gap_kind") or "missing_evidence"),
                reason=str(gap.get("description") or ""),
                proposed_intervention=(metacog_gap_signal.get("next_step") or {}).get("experiment")
                if isinstance(metacog_gap_signal.get("next_step"), dict)
                else {},
                source=str(gap.get("module") or "metacog_gap_signal"),
            )
    return frame
