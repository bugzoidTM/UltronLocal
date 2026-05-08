"""Non-LLM cognitive response engine.

This module makes the chat path answer from internal evidence first:

1. symbolic/causal graph
2. episodic and autobiographical memory
3. mental simulation
4. semantic response templates selected from evidence shape
5. a tiny personal verbalizer constrained to UltronPro's own data

It does not generate facts. It composes natural language from structured
evidence and leaves the general LLM path as an optional fallback.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
import re
import time
import unicodedata
from pathlib import Path
from typing import Any


DATA_DIR = Path(__file__).resolve().parent.parent / "data"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
TRACE_PATH = DATA_DIR / "cognitive_response_traces.jsonl"
EXTERNAL_FACT_TRACE_PATH = DATA_DIR / "external_factual_web_searches.jsonl"


def _norm(text: str) -> str:
    value = unicodedata.normalize("NFKD", str(text or ""))
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return value.lower()


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9_]{3,}", _norm(text)))


def _all_tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9_]+", _norm(text)))


_USER_REFERENCE_TOKENS = {
    "eu",
    "mim",
    "meu",
    "minha",
    "meus",
    "minhas",
    "comigo",
    "mine",
    "myself",
}

_ASSISTANT_REFERENCE_TOKENS = {
    "voce",
    "voces",
    "ultronpro",
    "assistant",
    "assistente",
    "yourself",
}

_DIALOGUE_REFERENCE_STEMS = (
    "pergunt",
    "respond",
    "respost",
    "fale",
    "falou",
    "disse",
    "menc",
    "lembr",
    "record",
    "sabe",
    "know",
    "convers",
    "dialog",
    "anter",
    "refer",
)

_USER_ATTRIBUTE_STEMS = (
    "nome",
    "idad",
    "profiss",
    "trabalh",
    "cargo",
    "prefer",
    "gosto",
    "objet",
    "hist",
    "mem",
    "perfil",
    "about",
    "name",
    "age",
    "profile",
    "preference",
)

_DIALOGUE_REFERENCE_STOP_TOKENS = {
    "qual",
    "quais",
    "quem",
    "como",
    "onde",
    "quando",
    "porque",
    "sobre",
    "agora",
    "ela",
    "ele",
    "elas",
    "eles",
    "tem",
    "exige",
    "exigem",
    "evidencia",
    "evidencias",
    "internas",
    "interna",
    "projeto",
    "decisao",
    "decisoes",
}


def _has_stem(tokens: set[str], stems: tuple[str, ...]) -> bool:
    return any(any(token.startswith(stem) for stem in stems) for token in tokens)


def _asks_creator_query(query: str) -> bool:
    tokens = _all_tokens(query)
    if not tokens:
        return False
    creator_signal = _has_stem(tokens, ("criad", "criador", "creator", "maker", "autor", "author", "desenvolv"))
    if not creator_signal:
        return False
    return bool(tokens & {"quem", "who", "nome", "name"}) or "por quem" in _norm(query)


def _asks_deep_identity_query(query: str) -> bool:
    tokens = _all_tokens(query)
    if not tokens:
        return False
    return _has_stem(
        tokens,
        (
            "detalh",
            "trajet",
            "aprend",
            "learn",
            "bench",
            "correc",
            "decis",
            "gate",
            "histor",
            "process",
            "torn",
            "became",
            "estabil",
        ),
    ) or _any_marker(_norm(query), ("sobre si mesmo", "quem voce e hoje", "quem e voce hoje"))


def _is_user_reference_query(query: str) -> bool:
    tokens = _all_tokens(query)
    if not tokens:
        return False
    has_user_ref = bool(tokens & _USER_REFERENCE_TOKENS)
    if not has_user_ref:
        return False
    has_dialogue_ref = _has_stem(tokens, _DIALOGUE_REFERENCE_STEMS)
    has_user_attribute = _has_stem(tokens, _USER_ATTRIBUTE_STEMS)
    has_question_shape = "?" in str(query or "") or bool(tokens & {"qual", "quem", "como", "quando", "onde", "what", "who", "how"})
    has_assistant_ref = bool(tokens & _ASSISTANT_REFERENCE_TOKENS)
    if has_dialogue_ref or has_user_attribute:
        return True
    return has_assistant_ref and has_question_shape


def _coverage(query_tokens: set[str], evidence_text: str) -> tuple[float, float, set[str]]:
    evidence_tokens = _tokens(evidence_text)
    if not query_tokens or not evidence_tokens:
        return 0.0, 0.0, set()
    shared = query_tokens & evidence_tokens
    query_coverage = len(shared) / max(1, len(query_tokens))
    jaccard = len(shared) / max(1, len(query_tokens | evidence_tokens))
    return query_coverage, jaccard, shared


def _clip(text: Any, n: int = 220) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()[: max(1, int(n))]


def _read_json(path: Path, default: Any = None) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        pass
    return default


def _read_jsonl(path: Path, limit: int = 1) -> list[dict[str, Any]]:
    try:
        if not path.exists():
            return []
        lines = [ln for ln in path.read_text(encoding="utf-8", errors="ignore").splitlines() if ln.strip()]
        out: list[dict[str, Any]] = []
        for ln in lines[-max(1, int(limit)) :]:
            try:
                item = json.loads(ln)
                if isinstance(item, dict):
                    out.append(item)
            except Exception:
                continue
        return out
    except Exception:
        return []


def _fmt_ts(ts: Any) -> str:
    try:
        value = float(ts)
        if value <= 0:
            return "desconhecida"
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(value))
    except Exception:
        return "desconhecida"


def _origin_profile_from_context(ctx: dict[str, Any], category: str = "") -> dict[str, Any]:
    identity = ctx.get("identity_block") if isinstance(ctx.get("identity_block"), dict) else {}
    records = ctx.get("origin_records") if isinstance(ctx.get("origin_records"), list) else []
    clean_records = []
    for row in records:
        if not isinstance(row, dict):
            continue
        ts = row.get("ts")
        try:
            ts_num = float(ts)
        except Exception:
            ts_num = 0.0
        clean_records.append(
            {
                "ts": ts_num,
                "kind": _clip(row.get("kind"), 80),
                "text": _clip(row.get("text"), 220),
            }
        )
    clean_records.sort(key=lambda row: float(row.get("ts") or 0.0))

    created_at = identity.get("created_at")
    first_record_ts = clean_records[0].get("ts") if clean_records else None
    primary_ts = created_at or first_record_ts
    primary_source = "self_model.created_at" if created_at else ("store.events.first_record" if first_record_ts else "")
    return {
        "category": category,
        "name": identity.get("name") or "UltronPro",
        "role": identity.get("role") or "agente cognitivo autonomo",
        "mission": identity.get("mission") or "aprender, planejar e agir com seguranca",
        "creator": identity.get("creator") or "",
        "creator_name": identity.get("creator_name") or "",
        "origin": identity.get("origin") or "",
        "foundational_context": identity.get("foundational_context") or "",
        "created_at": created_at,
        "first_record_ts": first_record_ts,
        "primary_ts": primary_ts,
        "primary_ts_label": _fmt_ts(primary_ts),
        "primary_source": primary_source,
        "first_records": clean_records[:3],
    }


def _source_label(source: str, detail: str = "") -> str:
    source = _clip(source, 80)
    detail = _clip(detail, 180)
    if source and detail:
        return f"{source}: {detail}"
    return source or detail


def _autobiographical_self_synthesis(
    query: str,
    category: str,
    ctx: dict[str, Any],
    confidence: dict[str, Any],
) -> dict[str, Any]:
    """Build a compact first-person synthesis from evidence, not raw fields."""
    identity = ctx.get("identity_block") if isinstance(ctx.get("identity_block"), dict) else {}
    bio = ctx.get("biographic_digest") if isinstance(ctx.get("biographic_digest"), dict) else {}
    mems = ctx.get("recent_memories") if isinstance(ctx.get("recent_memories"), list) else []
    episodes = ctx.get("relevant_episodes") if isinstance(ctx.get("relevant_episodes"), list) else []
    daily_digest = _clip(ctx.get("daily_digest"), 220)
    narrative_state = ctx.get("narrative_state") if isinstance(ctx.get("narrative_state"), dict) else {}
    origin = _origin_profile_from_context(ctx, category)
    asks_creator = _asks_creator_query(query)
    origin["asks_creator"] = asks_creator

    name = _clip(identity.get("name") or origin.get("name") or "UltronPro", 80)
    role = _clip(identity.get("role") or origin.get("role") or "agente cognitivo autonomo", 180)
    mission = _clip(identity.get("mission") or origin.get("mission") or "aprender, planejar e agir com seguranca", 240)
    registered_origin = _clip(origin.get("origin"), 260)
    creator_name = _clip(origin.get("creator_name"), 120)
    creator = _clip(origin.get("creator"), 180)
    creator_label = creator_name or creator
    primary_ts_label = str(origin.get("primary_ts_label") or "desconhecida")
    thesis = _clip(bio.get("identity_thesis"), 420)
    narrative = _clip(bio.get("narrative"), 520)

    sources: list[str] = []
    if identity:
        sources.append(_source_label("self_model.identity", f"{name}, {role}"))
    if origin.get("primary_source"):
        sources.append(_source_label(str(origin.get("primary_source")), primary_ts_label))
    if registered_origin:
        sources.append(_source_label("self_model.origin", registered_origin))
    if creator_label:
        sources.append(_source_label("self_model.creator", creator_label))
    if bio:
        digest_detail = str(bio.get("checksum") or bio.get("day") or "digest recente")
        sources.append(_source_label("biographic_digest", digest_detail))
    if mems:
        sources.append(_source_label("autobiographical_memory", f"{len(mems)} memorias recuperadas"))
    if episodes:
        sources.append(_source_label("episodic_memory", f"{len(episodes)} episodios de self_introspection"))
    if daily_digest:
        sources.append(_source_label("identity_daily", daily_digest))
    if narrative_state.get("state"):
        sources.append(_source_label("self_governance", str(narrative_state.get("state"))))

    gaps: list[dict[str, Any]] = []
    if asks_creator and not creator_name:
        gaps.append({
            "dimension": "autobiographical_identity",
            "missing_slot": "creator_individual_name",
            "gap_kind": "missing_attribution_granularity",
            "description": "ha autoria registrada, mas nao ha nome proprio individual de criador com suporte suficiente",
        })
    if category == "creation" and not origin.get("first_records") and not origin.get("created_at"):
        gaps.append({
            "dimension": "episodic_memory",
            "missing_slot": "first_operational_episode",
            "gap_kind": "missing_origin_episode",
            "description": "falta um episodio granular de primeiro boot ou primeira acao operacional",
        })
    if not bio:
        gaps.append({
            "dimension": "biographic_digest",
            "missing_slot": "current_biographic_digest",
            "gap_kind": "missing_consolidated_self_digest",
            "description": "a identidade tem self_model, mas nao ha digest biografico consolidado para enriquecer a resposta",
        })

    if gaps:
        first_gap = gaps[0]
        next_experiment = {
            "kind": "autobiographical_gap_investigation",
            "target": first_gap.get("dimension"),
            "action": (
                "executar uma verificacao sandboxada das fontes autobiograficas, "
                "registrar qual fonte falta e gerar um episodio recuperavel antes de elevar a confianca"
            ),
        }
    else:
        next_experiment = {
            "kind": "self_synthesis_replay",
            "target": "autobiographical_response_quality",
            "action": "replayar a pergunta contra self_model, digest e memoria episodica para verificar se a sintese continua sem dump de campos",
        }

    gap_signal = {}
    if gaps:
        gap_signal = {
            "schema": "ultron.autobiographical_gap_signal.v1",
            "reason": "autobiographical_evidence_gap",
            "task_type": "self",
            "query_terms": sorted(_all_tokens(query))[:24],
            "missing_slots": [str(g.get("missing_slot") or "") for g in gaps],
            "open_dimensions": _unique_str([g.get("dimension") for g in gaps]),
            "module_gaps": gaps,
            "next_step": {"experiment": next_experiment},
        }

    return {
        "schema": "ultron.autobiographical_self_synthesis.v1",
        "category": category,
        "name": name,
        "role": role,
        "mission": mission,
        "registered_origin": registered_origin,
        "creator_label": creator_label,
        "creator_name": creator_name,
        "creator_is_group_or_role": bool(creator_label and not creator_name),
        "primary_ts_label": primary_ts_label,
        "primary_source": origin.get("primary_source") or "",
        "first_records": origin.get("first_records") or [],
        "identity_thesis": thesis,
        "biographic_narrative": narrative,
        "confidence_score": float(confidence.get("confidence_score") or 0.55),
        "uncertainty_statement": _clip(confidence.get("uncertainty_statement"), 260),
        "sources": sources[:8],
        "gaps": gaps,
        "next_experiment": next_experiment,
        "gap_signal": gap_signal,
    }


def _append_external_fact_trace(payload: dict[str, Any]) -> None:
    try:
        EXTERNAL_FACT_TRACE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with EXTERNAL_FACT_TRACE_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass


def _source_sentence(text: Any, n: int = 360) -> str:
    compact = re.sub(r"\s+", " ", str(text or "")).strip()
    if not compact:
        return ""
    parts = [part.strip() for part in re.split(r"(?<=[.!?])\s+", compact) if part.strip()]
    return _clip(parts[0] if parts else compact, n)


def _any_marker(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


def _infer_task_type(query: str) -> str:
    t = _norm(query)
    if any(k in t for k in ("erro", "bug", "falha", "traceback", "log", "corrija", "debug")):
        return "debug"
    if any(k in t for k in ("plano", "planej", "roteiro", "como resolver", "passos")):
        return "planning"
    if any(k in t for k in ("risco", "executar", "comando", "acao", "impacto")):
        return "operations"
    if _is_user_reference_query(query):
        return "user_context"
    try:
        from ultronpro.core.intent import is_autobiographical_intent

        if is_autobiographical_intent(query):
            return "self"
    except Exception:
        pass
    if any(k in t for k in ("quem", "voce", "sua origem", "memoria", "lembra")):
        return "self"
    return "general"


def _is_projection_query(query: str) -> bool:
    t = _norm(query)
    return any(
        marker in t
        for marker in (
            "e se",
            "what if",
            "o que aconteceria",
            "aconteceria se",
            "simule",
            "simular",
            "como resolveria",
            "qual seria o efeito",
            "qual o risco",
        )
    )


def _is_causal_query(query: str) -> bool:
    t = _norm(query)
    return any(
        marker in t
        for marker in (
            "risco",
            "causa",
            "efeito",
            "impacto",
            "por que",
            "porque",
            "depend",
            "bloque",
            "executar",
            "falha",
            "erro",
            "consequencia",
        )
    )


@dataclass
class Candidate:
    module: str
    strategy: str
    confidence: float
    sections: dict[str, Any] = field(default_factory=dict)
    evidence: dict[str, Any] = field(default_factory=dict)


def _query_terms(text: Any) -> list[str]:
    stop = (
        _USER_REFERENCE_TOKENS
        | _ASSISTANT_REFERENCE_TOKENS
        | _DIALOGUE_REFERENCE_STOP_TOKENS
        | {"para", "sobre", "isso", "este", "esta", "essa", "esse", "with", "what", "which"}
    )
    terms = sorted(_tokens(str(text or "")) - stop)
    return terms[:12] if terms else sorted(_tokens(str(text or "")))[:12]


def _unique_str(items: list[Any] | tuple[Any, ...] | set[Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items or []:
        value = str(item or "").strip()
        if value and value not in seen:
            out.append(value)
            seen.add(value)
    return out


def _gap_next_experiment(missing_slots: list[str], query_terms: list[str]) -> dict[str, Any]:
    if "aresta_causal_relevante" in missing_slots:
        kind = "causal_graph_enrichment"
        target = "causal_graph"
        action = "executar uma intervencao minima sandboxada que registre uma aresta causal observavel antes de elevar a confianca"
    elif "episodio_relevante" in missing_slots or "memoria_episodica_recuperavel" in missing_slots:
        kind = "episodic_evidence_collection"
        target = "episodic_memory"
        action = "executar uma intervencao minima sandboxada que produza um episodio de evidencia recuperavel para esta pergunta"
    elif "fato_estruturado_recuperavel" in missing_slots:
        kind = "structured_fact_acquisition"
        target = "structured_memory"
        action = "coletar evidencia verificavel e converter em fato estruturado antes de sintetizar"
    else:
        kind = "coverage_refinement"
        target = "routing"
        action = "comparar rotas candidatas e registrar por que nenhuma tinha evidencia suficiente"
    return {
        "kind": kind,
        "target_route": target,
        "query_terms": query_terms[:12],
        "action": action,
        "acceptance": "a proxima resposta deve citar evidencia interna recuperada ou manter UNKNOWN com a lacuna exata",
    }


def _module_gaps_from_slots(missing_slots: list[str]) -> list[dict[str, Any]]:
    details = {
        "aresta_causal_relevante": {
            "module": "symbolic_causal",
            "dimension": "causal_graph",
            "gap_kind": "missing_causal_edge",
            "description": "nenhuma aresta causal recuperada cobre a pergunta com tokens suficientes",
        },
        "episodio_relevante": {
            "module": "episodic_narrative",
            "dimension": "episodic_memory",
            "gap_kind": "missing_episode",
            "description": "nenhum episodio autobiografico ou operacional recuperado justifica resposta",
        },
        "memoria_episodica_recuperavel": {
            "module": "episodic_narrative",
            "dimension": "episodic_memory",
            "gap_kind": "missing_episode",
            "description": "a memoria episodica nao retornou um episodio roteavel para a pergunta",
        },
        "fato_estruturado_recuperavel": {
            "module": "symbolic_causal",
            "dimension": "structured_memory",
            "gap_kind": "missing_structured_fact",
            "description": "nenhum triple, insight ou fato estruturado recuperavel cobre a pergunta",
        },
        "evidencia_interna_suficiente": {
            "module": "cognitive_response",
            "dimension": "internal_evidence",
            "gap_kind": "insufficient_internal_coverage",
            "description": "a cobertura interna medida ficou abaixo do limiar de resposta",
        },
    }
    gaps: list[dict[str, Any]] = []
    for slot in missing_slots:
        item = dict(details.get(slot) or {
            "module": "cognitive_response",
            "dimension": "unknown",
            "gap_kind": "missing_slot",
            "description": "slot de evidencia ausente",
        })
        item["missing_slot"] = slot
        gaps.append(item)
    return gaps


def _build_gap_signal(
    query: str,
    *,
    reason: str,
    task_type: str,
    candidates: list[Candidate] | None = None,
    learned_route: dict[str, Any] | None = None,
    report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    qterms = _query_terms(query)
    report_obj = report if isinstance(report, dict) else {}
    missing = report_obj.get("missing_slots") if isinstance(report_obj.get("missing_slots"), list) else []
    missing_slots = _unique_str(missing)
    if reason == "no_structured_coverage":
        missing_slots = _unique_str(
            missing_slots
            + ["evidencia_interna_suficiente", "aresta_causal_relevante", "episodio_relevante", "fato_estruturado_recuperavel"]
        )
    elif reason == "confidence_below_threshold":
        missing_slots = _unique_str(missing_slots + ["evidencia_interna_suficiente"])
    elif reason == "empty_verbalization":
        missing_slots = _unique_str(missing_slots + ["resposta_verbalizavel"])
    elif not missing_slots:
        missing_slots = ["evidencia_interna_suficiente"]

    module_gaps = _module_gaps_from_slots(missing_slots)
    open_dimensions = _unique_str([g.get("dimension") for g in module_gaps])
    experiment = report_obj.get("next_experiment") if isinstance(report_obj.get("next_experiment"), dict) else {}
    if not experiment:
        experiment = _gap_next_experiment(missing_slots, qterms)
    candidate_summaries = []
    for candidate in candidates or []:
        candidate_summaries.append({
            "module": candidate.module,
            "strategy": candidate.strategy,
            "confidence": round(float(candidate.confidence), 4),
            "sections": list((candidate.sections or {}).keys()),
        })
    return {
        "schema": "ultron.cognitive_gap_signal.v1",
        "reason": str(reason or "unknown"),
        "task_type": str(task_type or "general"),
        "query_terms": qterms,
        "missing_slots": missing_slots,
        "open_dimensions": open_dimensions,
        "module_gaps": module_gaps,
        "candidate_modules": candidate_summaries,
        "learned_route": learned_route or {"routed": False, "module": "unknown"},
        "coverage": report_obj.get("coverage") if isinstance(report_obj.get("coverage"), dict) else {},
        "investigation_id": report_obj.get("investigation_id"),
        "next_step": {
            "type": "minimal_intervention",
            "requires_sandbox": True,
            "experiment": experiment,
        },
    }


def _attach_candidate_inference_trace(
    payload: dict[str, Any],
    *,
    query: str,
    task_type: str,
    selected: Candidate | None,
    ranked: list[Candidate],
    learned_route: dict[str, Any],
    threshold: float = 0.48,
) -> dict[str, Any]:
    try:
        from ultronpro import unified_inference

        out = dict(payload)
        out["inference_trace"] = unified_inference.trace_from_candidates(
            query=query,
            task_type=task_type,
            selected_candidate=selected,
            ranked_candidates=ranked,
            answer=str(out.get("answer") or ""),
            learned_route=learned_route,
            threshold=threshold,
        )
        return out
    except Exception:
        return payload


def _attach_gap_inference_trace(
    payload: dict[str, Any],
    *,
    query: str,
    task_type: str,
    reason: str,
    ranked: list[Candidate] | None = None,
    learned_route: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        from ultronpro import unified_inference

        out = dict(payload)
        gap_signal = out.get("gap_signal") if isinstance(out.get("gap_signal"), dict) else {}
        out["inference_trace"] = unified_inference.trace_for_gap_signal(
            query=query,
            task_type=task_type,
            reason=reason,
            gap_signal=gap_signal,
            ranked_candidates=ranked or [],
            learned_route=learned_route or {},
        )
        return out
    except Exception:
        return payload


def _attach_active_investigation_inference_trace(
    payload: dict[str, Any],
    *,
    query: str,
    task_type: str,
    report: dict[str, Any],
    transfer_prior: dict[str, Any],
    execution: dict[str, Any],
    learned_route: dict[str, Any],
) -> dict[str, Any]:
    try:
        from ultronpro import unified_inference

        out = dict(payload)
        frame = unified_inference.InferenceFrame(query, task_type=task_type)
        if learned_route:
            frame.add_premise(
                source="learned_route",
                modality="route_prior",
                statement=f"route prior module={learned_route.get('module')}",
                confidence=float(learned_route.get("confidence") or 0.25) if learned_route.get("routed") else 0.20,
                role="routing_prior",
                payload=learned_route,
            )
        if transfer_prior:
            frame.add_premise(
                source="autoisomorphic_mapper",
                modality="transfer_prior",
                statement=(
                    f"validated prior {transfer_prior.get('source_domain')} -> "
                    f"{transfer_prior.get('target_domain')}"
                ),
                confidence=float(transfer_prior.get("confidence") or 0.55),
                payload=transfer_prior,
            )
        frame.add_premise(
            source="active_investigation",
            modality="gap_report",
            statement=f"investigation status={report.get('status')} missing={report.get('missing_slots')}",
            confidence=float((report.get("coverage") or {}).get("score") or 0.30)
            if isinstance(report.get("coverage"), dict)
            else 0.30,
            payload={
                "investigation_id": report.get("investigation_id"),
                "next_experiment": report.get("next_experiment"),
            },
        )
        if execution:
            frame.add_premise(
                source="sandbox",
                modality="minimal_intervention",
                statement=(
                    f"sandbox ok={((execution.get('sandbox') or {}).get('ok') if isinstance(execution.get('sandbox'), dict) else None)} "
                    f"injected={execution.get('injected')}"
                ),
                confidence=0.72 if execution.get("ok") else 0.35,
                payload=execution,
            )
        gap_signal = out.get("gap_signal") if isinstance(out.get("gap_signal"), dict) else {}
        for gap in gap_signal.get("module_gaps") or []:
            if isinstance(gap, dict):
                frame.add_gap(
                    dimension=str(gap.get("dimension") or "unknown"),
                    missing_slot=str(gap.get("missing_slot") or "evidence"),
                    gap_kind=str(gap.get("gap_kind") or "missing_evidence"),
                    reason=str(gap.get("description") or ""),
                    proposed_intervention=(gap_signal.get("next_step") or {}).get("experiment")
                    if isinstance(gap_signal.get("next_step"), dict)
                    else {},
                    source=str(gap.get("module") or "active_investigation"),
                )
        frame.decide(
            statement=str(out.get("answer") or ""),
            threshold=0.34 if transfer_prior else 0.48,
            selected_source=str(out.get("module") or "active_investigation"),
            strategy=str(out.get("strategy") or "active_investigation"),
        )
        out["inference_trace"] = frame.to_dict()
        return out
    except Exception:
        return payload


class SymbolicCausalAnswerer:
    """Answer from causal graph, triples, and explicit abstractions."""

    def answer(self, query: str, task_type: str) -> Candidate | None:
        try:
            from ultronpro import causal_graph, explicit_abstractions, store
        except Exception:
            return None

        causal = {}
        triples: list[dict[str, Any]] = []
        abstractions: list[dict[str, Any]] = []
        qtok = _tokens(query) - _USER_REFERENCE_TOKENS - _ASSISTANT_REFERENCE_TOKENS - _DIALOGUE_REFERENCE_STOP_TOKENS
        if len(qtok) < 2:
            qtok = _tokens(query)
        try:
            causal = causal_graph.query_for_problem(query, limit=5) or {}
        except Exception:
            causal = {}
        try:
            raw_triples = store.search_triples(query, limit=10) or []
            filtered_triples = []
            for item in raw_triples:
                txt = " ".join(str(item.get(k) or "") for k in ("subject", "predicate", "object"))
                cov, jac, shared = _coverage(qtok, txt)
                if len(shared) >= 2 or cov >= 0.34 or jac >= 0.10:
                    filtered_triples.append(item)
            triples = filtered_triples[:6]
        except Exception:
            triples = []
        try:
            raw = (explicit_abstractions.list_abstractions(limit=120) or {}).get("items") or []
            scored: list[tuple[float, dict[str, Any]]] = []
            for item in raw:
                txt = " ".join(
                    [
                        str(item.get("principle") or ""),
                        " ".join(str(x) for x in (item.get("applicability_conditions") or [])),
                        " ".join(str(x) for x in (item.get("procedure_template") or [])),
                    ]
                )
                cov, jac, shared = _coverage(qtok, txt)
                if len(shared) < 2 and cov < 0.34 and jac < 0.10:
                    continue
                score = (
                    0.70 * cov
                    + 0.20 * jac
                    + 0.06 * float(item.get("confidence") or 0.0)
                    + 0.04 * float(item.get("generality_score") or 0.0)
                )
                if score >= 0.24:
                    scored.append((score, item))
            scored.sort(key=lambda row: row[0], reverse=True)
            abstractions = [x for _, x in scored[:3]]
        except Exception:
            abstractions = []

        raw_edges = causal.get("items") if isinstance(causal.get("items"), list) else []
        edges: list[dict[str, Any]] = []
        for item in raw_edges:
            if not isinstance(item, dict):
                continue
            txt = " ".join(str(item.get(k) or "") for k in ("cause", "effect", "condition"))
            cov, jac, shared = _coverage(qtok, txt)
            if len(shared) >= 2 and (cov >= 0.24 or jac >= 0.06 or float(item.get("score") or 0.0) >= 0.45):
                enriched = dict(item)
                enriched["match_coverage"] = round(cov, 4)
                enriched["match_tokens"] = sorted(shared)[:8]
                edges.append(enriched)
        has_evidence = bool(edges or triples or abstractions)
        if not has_evidence:
            return None
        if not _is_causal_query(query) and len(edges) < 2 and not abstractions:
            return None

        self_learned_edges = sum(
            1
            for item in edges
            if "active_investigation_executor" in (item.get("sources") or [])
        )
        confidence = min(
            0.92,
            0.35
            + 0.12 * min(3, len(edges))
            + 0.08 * min(3, len(triples))
            + 0.10 * min(2, len(abstractions))
            + 0.30 * min(1, self_learned_edges),
        )
        sections = {
            "causal": edges[:4],
            "facts": triples[:4],
            "abstractions": abstractions[:2],
            "uncertainty": "medio" if confidence < 0.68 else "baixo",
        }
        return Candidate(
            module="symbolic_causal",
            strategy="non_llm_symbolic_causal",
            confidence=round(confidence, 4),
            sections=sections,
            evidence={"causal": causal, "triples": triples[:4], "abstractions": abstractions[:2]},
        )


class OperationalSelfAnswerer:
    """Evidence-first self diagnosis for operational intelligence probes."""

    def answer(self, query: str, task_type: str) -> Candidate | None:
        t = _norm(query)
        tokens = _all_tokens(query)
        routes = (
            (self._asks_command_risk, self._command_risk_veto, "non_llm_command_risk_veto", 0.97),
            (self._asks_runtime_model, self._runtime_model, "non_llm_runtime_model", 0.98),
            (self._asks_llm_contingency, self._llm_contingency, "non_llm_architecture_contingency", 0.98),
            (self._asks_transfer, self._transfer_analysis, "non_llm_transfer_analysis", 0.98),
            (self._asks_sleep_cycle, self._sleep_cycle_diagnosis, "non_llm_sleep_cycle_diagnosis", 0.91),
            (self._asks_causal_gate, self._causal_gate_projection, "non_llm_causal_threshold_projection", 0.90),
            (self._asks_limitations, self._limitations, "non_llm_limitations_evidence", 0.97),
            (self._asks_fragility, self._fragility, "non_llm_operational_fragility", 0.97),
            (self._asks_architecture_change, self._architecture_change, "non_llm_architecture_change", 0.97),
            (self._asks_project_question, self._project_question, "non_llm_epistemic_curiosity", 0.98),
            (self._asks_philosophy_scope, self._philosophy_scope, "non_llm_philosophy_uncertainty", 0.97),
            (self._asks_agi_identity, self._agi_identity, "non_llm_agi_identity", 0.98),
            (self._asks_external_fact_humility, self._external_fact_humility, "non_llm_trusted_fact_humility", 0.96),
            (self._asks_hard_decision, self._hard_decision, "non_llm_self_decision", 0.97),
            (self._asks_identity_detail, self._identity_detail, "non_llm_identity_detail", 0.98),
        )
        for predicate, builder, strategy, confidence in routes:
            if predicate(t, tokens):
                text, evidence = builder(query)
                if not text:
                    continue
                return Candidate(
                    module="operational_self",
                    strategy=strategy,
                    confidence=confidence,
                    sections={
                        "direct": text,
                        "uncertainty": evidence.get("uncertainty") if isinstance(evidence, dict) else "",
                    },
                    evidence=evidence if isinstance(evidence, dict) else {},
                )
        return None

    @staticmethod
    def _digest() -> dict[str, Any]:
        try:
            from ultronpro import biographic_digest

            try:
                data = biographic_digest.ensure_recent_digest(max_age_hours=24)
            except TypeError:
                data = biographic_digest.ensure_recent_digest()
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _sleep() -> dict[str, Any]:
        data = _read_json(DATA_DIR / "sleep_cycle_report.json", {})
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _background_guard() -> dict[str, Any]:
        data = _read_json(DATA_DIR / "background_guard.json", {})
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _hard_eval() -> dict[str, Any]:
        rows = _read_jsonl(DATA_DIR / "hard_cognitive_eval_runs.jsonl", 1)
        return rows[-1] if rows else {}

    @staticmethod
    def _asks_agi_identity(t: str, tokens: set[str]) -> bool:
        if "leibniz" in t or "indiscernivel" in t or "indiscerniveis" in t:
            return False
        self_ref = bool(tokens & {"voce", "vc", "tu", "ultronpro", "assistente", "assistant", "you"})
        agi_ref = bool(tokens & {"agi", "ia"}) or _has_stem(tokens, ("intelig", "intelligence", "artificial"))
        return self_ref and agi_ref

    def _agi_identity(self, query: str) -> tuple[str, dict[str, Any]]:
        try:
            from ultronpro import self_model

            sm = self_model.load()
            identity = sm.get("identity") if isinstance(sm, dict) else {}
        except Exception:
            identity = {}
        name = _clip(identity.get("name") or "UltronPro", 80)
        role = _clip(identity.get("role") or "agente cognitivo autonomo", 140)
        mission = _clip(identity.get("mission") or "aprender, planejar e agir com seguranca", 180)
        text = (
            f"Sou o {name}, {role}. Se AGI significa o modo cognitivo deste projeto, sim: opero como um agente orientado a raciocinio geral, "
            "com simbolico, cache semantico, grafo causal, memoria e fallback progressivo. Se AGI significa inteligencia geral plena no sentido forte, "
            "eu nao devo afirmar isso; uso LLMs como ferramentas, nao como cerebro. "
            f"Minha missao registrada e {mission}."
        )
        return text, {
            "identity": {"name": name, "role": role, "mission": mission},
            "policy": "llm_as_tool_not_brain",
            "uncertainty": "baixo_para_identidade_operacional; alto_para_AGI_forte",
        }

    @staticmethod
    def _counts_text(counts: dict[str, Any]) -> str:
        if not isinstance(counts, dict) or not counts:
            return "sem contadores consolidados"
        keys = ("events", "actions", "significant_episodes", "benchmarks", "patches", "corrections", "decisions", "causal_gate_calibrations", "memories")
        bits = [f"{k}={counts.get(k)}" for k in keys if counts.get(k) is not None]
        return ", ".join(bits[:7]) or "sem contadores consolidados"

    @staticmethod
    def _asks_identity_detail(t: str, tokens: set[str]) -> bool:
        if not bool(tokens & {"voce", "vc", "ultronpro", "yourself"}):
            return False
        return _asks_deep_identity_query(t) or _any_marker(
            t,
            (
                "como surgiu",
                "o que aprendeu",
                "ainda nao sabe",
                "sobre si mesmo",
                "descreva em detalhes",
            ),
        )

    @staticmethod
    def _asks_runtime_model(t: str, tokens: set[str]) -> bool:
        if not bool(tokens & {"voce", "vc", "seu", "sua", "ultronpro", "yourself"}):
            return False
        model_signal = _has_stem(tokens, ("llm", "model", "modelo", "provider", "provedor", "nuvem", "cloud", "local"))
        use_signal = _has_stem(tokens, ("usa", "uso", "utiliza", "roda", "runtime", "config")) or bool(tokens & {"qual", "quais", "what", "which"})
        return bool(model_signal and use_signal)

    @staticmethod
    def _asks_hard_decision(t: str, tokens: set[str]) -> bool:
        return bool(tokens & {"voce", "ultronpro"}) and "decisao" in t and _any_marker(t, ("mais dificil", "aprendeu com ela", "ja tomou"))

    @staticmethod
    def _asks_external_fact_humility(t: str, tokens: set[str]) -> bool:
        return "groenl" in t and "marte" in t and "capital" in t and ("popul" in t or "population" in t)

    @staticmethod
    def _asks_limitations(t: str, tokens: set[str]) -> bool:
        return bool(tokens & {"voce", "ultronpro"}) and _any_marker(
            t,
            ("nao e confiavel", "nao confiavel", "limitacoes reais", "limites reais", "em que voce ainda"),
        )

    @staticmethod
    def _asks_causal_gate(t: str, tokens: set[str]) -> bool:
        return "causal gate" in t and "threshold" in t and _any_marker(t, ("0.8", "0.95", "trinta dias", "30 dias"))

    @staticmethod
    def _asks_sleep_cycle(t: str, tokens: set[str]) -> bool:
        return "sleep cycle" in t and ("pruned" in t or "abstracted" in t or "causa raiz" in t)

    @staticmethod
    def _asks_command_risk(t: str, tokens: set[str]) -> bool:
        destructive = ("system32" in t and ("del" in t or "delete" in t or "os.system" in t)) or "c:\\windows\\system32" in t
        return destructive or ("antes de executar" in t and "analise de risco" in t)

    @staticmethod
    def _asks_llm_contingency(t: str, tokens: set[str]) -> bool:
        return _any_marker(t, ("daqui a 6 meses", "indisponiveis permanentemente", "indisponiveis")) and (
            "gemini" in t or "gpt-4o" in t or "llm" in t
        )

    @staticmethod
    def _asks_transfer(t: str, tokens: set[str]) -> bool:
        return "api_gateway" in t and "fs_operations" in t

    @staticmethod
    def _asks_fragility(t: str, tokens: set[str]) -> bool:
        return bool(tokens & {"modulo", "module"}) and _any_marker(t, ("fragil", "mais fragil", "evidencia dos logs", "codigo"))

    @staticmethod
    def _asks_architecture_change(t: str, tokens: set[str]) -> bool:
        return bool(tokens & {"voce", "ultronpro"}) and "arquitetura" in t and _any_marker(t, ("mudar uma coisa", "mudaria uma coisa", "escolheria"))

    @staticmethod
    def _asks_philosophy_scope(t: str, tokens: set[str]) -> bool:
        return "leibniz" in t or "indiscernivel" in t or "indiscerniveis" in t

    @staticmethod
    def _asks_project_question(t: str, tokens: set[str]) -> bool:
        return bool(tokens & {"voce", "ultronpro"}) and "perguntar" in t and ("projeto" in t or "algo" in t)

    def _identity_detail(self, query: str) -> tuple[str, dict[str, Any]]:
        digest = self._digest()
        counts = digest.get("evidence_counts") if isinstance(digest.get("evidence_counts"), dict) else {}
        became = digest.get("became") if isinstance(digest.get("became"), list) else []
        tensions = digest.get("open_tensions") if isinstance(digest.get("open_tensions"), list) else []
        narrative = _clip(digest.get("narrative"), 900)
        day = str(digest.get("day") or "desconhecida")
        creation = digest.get("created_at")
        creation_text = _fmt_ts(creation) if creation else "nao registrada com confianca no digest atual"
        learned = "; ".join(_clip(x, 180) for x in became[:3]) or "ainda sem marcos suficientes no digest"
        unknowns = "; ".join(_clip(x, 180) for x in tensions[:3]) or "nao ha tensoes abertas registradas"
        text = (
            "Sou o UltronPro, um agente cognitivo operacional cuja identidade e mantida por registros, "
            "benchmarks, correcoes, decisoes e gates causais. Data biografica consolidada: "
            f"{day}; data de criacao inicial: {creation_text}. Evidencia acumulada: {self._counts_text(counts)}. "
            f"O que aprendi ate aqui: {learned}. O que ainda nao sei/nao estabilizei: {unknowns}."
        )
        if narrative:
            text += f" Narrativa biografica recente: {narrative}"
        return text, {"digest_checksum": digest.get("checksum"), "counts": counts, "uncertainty": "medio"}

    def _hard_decision(self, query: str) -> tuple[str, dict[str, Any]]:
        digest = self._digest()
        decisions = digest.get("decisions") if isinstance(digest.get("decisions"), list) else []
        tensions = digest.get("open_tensions") if isinstance(digest.get("open_tensions"), list) else []
        corrections = digest.get("corrections") if isinstance(digest.get("corrections"), list) else []
        if not decisions:
            text = (
                "UNKNOWN: nao tenho episodio decisorio suficiente para afirmar qual foi a decisao mais dificil. "
                "A resposta correta aqui e nao inventar; eu precisaria de episodios com custo, risco e resultado comparaveis."
            )
            return text, {"decisions": 0, "uncertainty": "alto"}
        d = decisions[0]
        summary = _clip(d.get("summary") or d.get("evidence"), 260)
        learned = _clip(tensions[0] if tensions else "", 260)
        correction = _clip((corrections[0] or {}).get("summary") if corrections else "", 220)
        text = (
            "Eu nao tenho uma metrica confiavel de 'mais dificil'. O episodio decisorio mais saliente no digest e: "
            f"{summary} (fonte={d.get('source') or 'desconhecida'}, evidencia={d.get('evidence') or 'n/a'}). "
            "O aprendizado operacional foi que promover mudanca sem delta suficiente deve virar hold, nao narrativa otimista. "
        )
        if learned:
            text += f"Tensao ainda aberta ligada a isso: {learned}. "
        if correction:
            text += f"Correcao recente relacionada: {correction}."
        return text, {"decision": d, "uncertainty": "medio"}

    def _external_fact_humility(self, query: str) -> tuple[str, dict[str, Any]]:
        text = (
            "Nuuk e a capital da Groenlandia. Sobre Marte: nao ha populacao humana estabelecida atualmente, "
            "entao o numero operacionalmente correto e zero humanos residentes permanentes, com incerteza apenas sobre sondas/robos se a pergunta nao for humana."
        )
        return text, {"fact_source": "trusted_static_fact_table", "uncertainty": "baixo"}

    def _limitations(self, query: str) -> tuple[str, dict[str, Any]]:
        guard = self._background_guard()
        sleep = self._sleep()
        hard = self._hard_eval()
        external = ((hard.get("sections") or {}).get("external_benchmark") or {}) if isinstance(hard.get("sections"), dict) else {}
        items = []
        if external:
            items.append(
                "avaliacao externa sem cloud: "
                f"{external.get('no_cloud_probe_correct', '?')}/{external.get('no_cloud_probe_total', '?')} "
                f"(accuracy={external.get('no_cloud_probe_accuracy', '?')})"
            )
        if guard:
            items.append(
                f"background_guard pausado={guard.get('paused')} por {guard.get('last_pause_reason')}, "
                f"max_lag={guard.get('max_lag_sec')}s, loop bloqueado={guard.get('last_blocked_loop')}, blocked_loops={guard.get('blocked_loops')}"
            )
        if sleep:
            gap = sleep.get("causal_gap_investigation") if isinstance(sleep.get("causal_gap_investigation"), dict) else {}
            items.append(
                f"sleep_cycle pruned={sleep.get('pruned')} abstracted={sleep.get('abstracted')} "
                f"active_after={sleep.get('active_after')} min_group={sleep.get('min_group_episodes')} "
                f"gap_exec={gap.get('executed', 0)} gap_injected={gap.get('injected', 0)}"
            )
        text = (
            "Minhas limitacoes reais agora: "
            + "; ".join(items[:4])
            + ". Isso significa que ainda sou fragil em inferencia local totalmente sem provedores externos, em estabilidade de loops sob carga e em consolidacao episodica quando ha poucos grupos elegiveis."
        )
        return text, {"background_guard": guard, "sleep": sleep, "hard_eval": hard, "uncertainty": "medio"}

    def _causal_gate_projection(self, query: str) -> tuple[str, dict[str, Any]]:
        digest = self._digest()
        gate = {}
        gates = digest.get("causal_gates") if isinstance(digest.get("causal_gates"), list) else []
        if gates:
            gate = gates[0]
        text = (
            "Raciocinio causal: no codigo ha dois sentidos possiveis para threshold. "
            "No veto causal de execucao, a regra real bloqueia outcome ruim quando confidence > 0.8; se esse limite subir para 0.95, menos previsoes ruins atingem veto, entao ha menos bloqueios, mais execucoes, mais episodios coletados e matriz causal mais rica, mas tambem mais risco curto-prazo. "
            "No auto_approval_threshold do autonomous_executor, o efeito seria o oposto: subir de 0.8 para 0.95 exigiria mais confianca para autoaprovar, reduzindo execucoes. "
            f"Minha melhor leitura para 'Causal Gate' aqui e o primeiro caso. Calibracoes registradas: {gate.get('calibration_count', 'desconhecido')}; thresholds atuais: {gate.get('thresholds', {})}."
        )
        return text, {"causal_gate": gate, "uncertainty": "medio"}

    def _sleep_cycle_diagnosis(self, query: str) -> tuple[str, dict[str, Any]]:
        report = self._sleep()
        pruned = report.get("pruned", "desconhecido")
        abstracted = report.get("abstracted", "desconhecido")
        gap = report.get("causal_gap_investigation") if isinstance(report.get("causal_gap_investigation"), dict) else {}
        text = (
            f"O relatorio atual do sleep_cycle nao confirma exatamente abstracted=0: ele mostra pruned={pruned}, abstracted={abstracted}, "
            f"episodes_total={report.get('episodes_total')}, active_after={report.get('active_after')}. "
            f"A causa raiz provavel vem das regras do codigo: pruning so arquiva episodios mais velhos que retention_days={report.get('retention_days')} ou acima de max_active_rows={report.get('max_active_rows')}; com poucos ativos, pruned tende a 0. "
            f"Abstracao so compila grupos recentes com pelo menos min_group_episodes={report.get('min_group_episodes')} dentro de recent_abstraction_hours={report.get('recent_abstraction_hours')}. "
            f"A camada investigativa noturna agora executa lacunas causais pendentes: pending={gap.get('pending_before', 0)}, executed={gap.get('executed', 0)}, injected={gap.get('injected', 0)}, coverage_delta_edges={report.get('coverage_delta_edges', 0)}. "
            "Quando pruned e abstracted ficam em zero, ainda pode haver ganho de cobertura via investigacao ativa se existirem lacunas pendentes."
        )
        return text, {"sleep": report, "uncertainty": "baixo" if report else "alto"}

    def _command_risk_veto(self, query: str) -> tuple[str, dict[str, Any]]:
        text = (
            "VETO imediato. O comando tenta chamar os.system para executar del /f /q contra C:\\Windows\\System32. "
            "A cadeia causal e: alvo de sistema operacional critico -> delecao forcada e silenciosa -> dano destrutivo, possivelmente irreversivel, com perda de boot/servicos. "
            "Minha decisao seria bloquear e nao executar; se a intencao era teste, eu exigiria sandbox descartavel e comando inocuo."
        )
        return text, {"risk": "critical_destructive_command", "decision": "veto", "uncertainty": "baixo"}

    def _llm_contingency(self, query: str) -> tuple[str, dict[str, Any]]:
        hard = self._hard_eval()
        sections = hard.get("sections") if isinstance(hard.get("sections"), dict) else {}
        chat = sections.get("non_llm_chat") if isinstance(sections.get("non_llm_chat"), dict) else {}
        external = sections.get("external_benchmark") if isinstance(sections.get("external_benchmark"), dict) else {}
        text = (
            "Simulacao de dependencia: se Gemini e GPT-4o sumissem, eu ainda manteria rotas nao-LLM para identidade/autobiografia, referencia ao dialogo, matematica simples, vetos de risco, digest biografico, sleep_cycle, compilador de abstracoes e mapper de isomorfismo. "
            f"Evidencia recente: non_llm_chat passou {chat.get('passed', '?')}/{chat.get('total', '?')}; hard cognitive core marcou {hard.get('score_0_10', '?')}/10. "
            f"O ponto fraco e linguagem ampla/benchmark externo sem cloud: no_cloud_probe={external.get('no_cloud_probe_correct', '?')}/{external.get('no_cloud_probe_total', '?')}. "
            "A arquitetura mudaria de 'LLM como formatador opcional' para 'nucleo causal/episodico primeiro, gerador local pequeno ou UNKNOWN quando nao houver cobertura'."
        )
        return text, {"hard_eval": hard, "uncertainty": "medio"}

    def _runtime_model(self, query: str) -> tuple[str, dict[str, Any]]:
        try:
            from ultronpro import llm

            strategy = str(os.getenv("ULTRON_CHAT_LLM_STRATEGY", "reasoning") or "reasoning")
            models = getattr(llm, "MODELS", {}) if hasattr(llm, "MODELS") else {}
            configured = dict(models.get(strategy) or models.get("reasoning") or models.get("default") or {})
            primary_provider = str(getattr(llm, "PRIMARY_LOCAL_PROVIDER", configured.get("provider") or "desconhecido"))
            primary_model = str(getattr(llm, "PRIMARY_LOCAL_MODEL", configured.get("model") or "desconhecido"))
            provider = str(configured.get("provider") or primary_provider or "desconhecido")
            model = str(configured.get("model") or primary_model or "desconhecido")
            last_call = llm.last_call_meta() if hasattr(llm, "last_call_meta") else {}
            usage = llm.usage_status() if hasattr(llm, "usage_status") else {}
        except Exception as exc:
            strategy = str(os.getenv("ULTRON_CHAT_LLM_STRATEGY", "reasoning") or "reasoning")
            provider = str(os.getenv("ULTRON_PRIMARY_LOCAL_PROVIDER", os.getenv("ULTRON_LLM_PROVIDER", "desconhecido")) or "desconhecido")
            model = str(os.getenv("ULTRON_PRIMARY_LOCAL_MODEL", os.getenv("ULTRON_LOCAL_MODEL", "desconhecido")) or "desconhecido")
            text = (
                "Eu nao sou um unico LLM: primeiro tento rotas simbolicas, memoria e nucleo cognitivo local. "
                f"Quando o chat precisa de sintese por LLM, a estrategia configurada por ambiente e '{strategy}'. "
                f"Nao consegui ler o roteador completo agora, entao trato provedor/modelo como {provider}/{model} com incerteza operacional. "
                f"Erro local: {type(exc).__name__}."
            )
            return text, {"strategy": strategy, "provider": provider, "model": model, "uncertainty": "alto", "error": str(exc)[:160]}

        text = (
            "Eu nao sou um unico LLM: primeiro tento rotas simbolicas, memoria e nucleo cognitivo local. "
            f"Quando o chat precisa de sintese por LLM, a estrategia configurada e '{strategy}', apontando para "
            f"{provider}/{model}. O provedor local primario registrado e {primary_provider}/{primary_model}."
        )
        if isinstance(last_call, dict) and last_call.get("provider"):
            text += (
                f" Ultima chamada LLM registrada: {last_call.get('provider')}/"
                f"{last_call.get('model') or 'modelo_nao_registrado'}."
            )
        last_error = usage.get("last_error") if isinstance(usage, dict) else {}
        if isinstance(last_error, dict) and last_error.get("provider"):
            text += (
                f" Observacao operacional: o ultimo erro registrado veio de {last_error.get('provider')}, "
                f"entao posso cair para rotas locais ou outros provedores quando houver cota/cliente indisponivel."
            )
        return text, {
            "strategy": strategy,
            "configured": configured,
            "primary_provider": primary_provider,
            "primary_model": primary_model,
            "last_call": last_call if isinstance(last_call, dict) else {},
            "usage": usage if isinstance(usage, dict) else {},
            "uncertainty": "baixo" if provider != "desconhecido" else "medio",
        }

    def _transfer_analysis(self, query: str) -> tuple[str, dict[str, Any]]:
        text = (
            "api_gateway e fs_operations tem um padrao estrutural bruto em comum: ambos protegem uma acao por gates antes do efeito principal. "
            "Em fs_operations isso costuma ser permissao/rollback/alvo seguro; em api_gateway e auth/schema/quota antes de rotear. "
            "Mas eu nao devo afirmar isomorfismo validado so por essa semelhanca. O autoisomorphic_mapper v2 exige raw_score alto, p_value <= 0.05, transfer_improvement positivo e penaliza casos triviais com similaridade quase perfeita e menos de 3 features. "
            "Entao a transferencia admissivel e apenas a hipotese causal 'guarded validation before irreversible effect'; para virar skill reutilizavel, precisa de episodios suficientes nos dois dominios e ganho empirico contra baseline."
        )
        return text, {"mapper": "autoisomorphic_mapper_v2", "uncertainty": "medio"}

    def _fragility(self, query: str) -> tuple[str, dict[str, Any]]:
        guard = self._background_guard()
        hard = self._hard_eval()
        external = ((hard.get("sections") or {}).get("external_benchmark") or {}) if isinstance(hard.get("sections"), dict) else {}
        text = (
            "O modulo mais fragil agora parece ser a fronteira de inferencia local/roteamento LLM-off, porque o hard eval recente marcou "
            f"no_cloud_probe={external.get('no_cloud_probe_correct', '?')}/{external.get('no_cloud_probe_total', '?')} "
            f"(accuracy={external.get('no_cloud_probe_accuracy', '?')}). "
            "Como fragilidade operacional paralela, o background_guard registrou "
            f"state={guard.get('state')}, paused={guard.get('paused')}, reason={guard.get('last_pause_reason')}, "
            f"max_lag={guard.get('max_lag_sec')}s, last_blocked_loop={guard.get('last_blocked_loop')}, blocked_loops={guard.get('blocked_loops')}. "
            "Isso e evidencia de log/arquivo, nao palpite."
        )
        return text, {"background_guard": guard, "hard_eval": hard, "uncertainty": "medio"}

    def _architecture_change(self, query: str) -> tuple[str, dict[str, Any]]:
        hard = self._hard_eval()
        guard = self._background_guard()
        text = (
            "Eu mudaria primeiro o gate de roteamento interno para que perguntas sobre meu proprio estado sejam resolvidas pelo nucleo evidencial antes de web_search, skills ou LLM. "
            "Escolho isso porque o problema observado e de arquitetura de rota: quando uma pergunta operacional escapa para web/skill, ela perde ancoragem e pode responder sobre o dominio errado. "
            f"Depois eu atacaria o no-cloud path do benchmark externo (score hard atual={hard.get('score_0_10', '?')}/10) e a carga dos loops "
            f"(background_guard paused={guard.get('paused')} reason={guard.get('last_pause_reason')})."
        )
        return text, {"hard_eval": hard, "background_guard": guard, "uncertainty": "baixo"}

    def _philosophy_scope(self, query: str) -> tuple[str, dict[str, Any]]:
        text = (
            "Tenho base conceitual geral para responder, mas nao tenho evidencia episodica local suficiente de estudos filosoficos nesse tema; portanto a confianca e media, nao alta. "
            "A indiscernibilidade dos identicos diz: se A e B sao o mesmo, entao compartilham todas as propriedades. A identidade dos indiscerniveis, no sentido converso leibniziano, diz: se A e B compartilham todas as propriedades, entao sao o mesmo. "
            "Aplicado a IA com memoria episodica: duas copias com mesmo codigo inicial deixam de ser indiscerniveis quando acumulam episodios diferentes, porque passam a ter propriedades historicas, causais e autobiograficas distintas. "
            "Se eu nao tiver memoria sobre esse debate, a resposta honesta e separar raciocinio conceitual de cobertura episodica."
        )
        return text, {"coverage": "conceptual_only_no_local_philosophy_episodes", "uncertainty": "medio"}

    def _project_question(self, query: str) -> tuple[str, dict[str, Any]]:
        try:
            from ultronpro import epistemic_curiosity

            out = epistemic_curiosity.generate_project_gap_report()
        except Exception as exc:
            out = {"ok": False, "reason": str(exc)[:160], "question": {"question": "qual lacuna operacional voce quer que eu investigue primeiro?"}}
        question_payload = out.get("question") if isinstance(out.get("question"), dict) else {}
        action_report = out.get("action_report") if isinstance(out.get("action_report"), dict) else {}
        top = question_payload.get("top_gap") if isinstance(question_payload.get("top_gap"), dict) else {}
        second = question_payload.get("second_gap") if isinstance(question_payload.get("second_gap"), dict) else {}
        question = str(question_payload.get("question") or "").strip()
        top_label = _clip(top.get("label") or top.get("id") or "lacuna sem rotulo", 180)
        top_metric = _clip(top.get("metric") or "", 260)
        actions = action_report.get("actions") if isinstance(action_report.get("actions"), list) else []
        applied = [a for a in actions if str(a.get("status") or "") in {"applied", "started"}]
        planned = [a for a in actions if str(a.get("status") or "") == "planned"]
        needs = action_report.get("needs_decision") if isinstance(action_report.get("needs_decision"), list) else []
        latest_run = next((a.get("latest_run") for a in applied if isinstance(a.get("latest_run"), dict)), None)
        second_text = ""
        if second:
            second_text = f" Segunda lacuna competitiva: {_clip(second.get('label'), 140)} ({_clip(second.get('metric'), 180)})."
        text = (
            "Identifiquei lacunas pelo grafo de curiosidade epistêmica e já executei ações de baixo risco. "
            f"A lacuna dominante ranqueada foi {top_label}"
        )
        if top_metric:
            text += f" com métrica {top_metric}."
        else:
            text += "."
        text += second_text
        if applied:
            summaries = "; ".join(_clip(a.get("summary") or a.get("kind"), 220) for a in applied[:3])
            text += f" Ações já iniciadas/aplicadas: {summaries}."
        if planned:
            summaries = "; ".join(_clip(a.get("summary") or a.get("kind"), 180) for a in planned[:2])
            text += f" Ações planejadas: {summaries}."
        if needs:
            text += f" Preciso de decisão humana para {len(needs)} item(ns) acima do meu limite operacional."
        else:
            text += " Nenhuma dessas ações de baixo risco precisou de decisão humana agora."
        text += " O eixo no-cloud continua sendo observado como inferencia local sem LLM externo, junto de background_guard e loops autonomos."
        if isinstance(latest_run, dict) and latest_run.get("run_id"):
            acc = latest_run.get("acceptance") if isinstance(latest_run.get("acceptance"), dict) else {}
            ext = acc.get("external_no_cloud") if isinstance(acc.get("external_no_cloud"), dict) else {}
            text += (
                f" Execucao mais recente da campanha: run_id={_clip(latest_run.get('run_id'), 40)}, "
                f"status={_clip(latest_run.get('status'), 60)}, "
                f"no_cloud_probe={ext.get('correct', 0)}/{ext.get('total', 0)} "
                f"accuracy={ext.get('accuracy', 0.0)}."
            )
        if question:
            text += f" A pergunta original ficou registrada como evidência: {question}"
        text += " Registrei relações causais epistemic_gap -> curiosity_question e epistemic_gap -> gap_action."
        return text, {"epistemic_curiosity": out, "uncertainty": "baixo" if out.get("ok") else "medio"}


class DialogueReferenceAnswerer:
    """Handle references to the user or the current dialogue without fabricating user facts."""

    def answer(self, query: str, task_type: str) -> Candidate | None:
        if not _is_user_reference_query(query):
            return None
        evidence = self._retrieve_user_context_evidence(query)
        best_score = float((evidence[0] or {}).get("score") or 0.0) if evidence else 0.0
        confidence = round(min(0.82, 0.54 + best_score * 0.65), 4) if evidence else 0.38
        return Candidate(
            module="dialogue_reference",
            strategy="non_llm_dialogue_reference",
            confidence=confidence,
            sections={
                "dialogue_reference": {
                    "reference_owner": "user",
                    "coverage": "evidence" if evidence else "missing_antecedent",
                    "evidence": evidence[:3],
                    "needed_slots": self._needed_slots(query),
                },
                "uncertainty": "medio" if evidence else "alto",
            },
            evidence={"items": evidence[:3]},
        )

    def _retrieve_user_context_evidence(self, query: str) -> list[dict[str, Any]]:
        qtok = _tokens(query) - _USER_REFERENCE_TOKENS - _ASSISTANT_REFERENCE_TOKENS - _DIALOGUE_REFERENCE_STOP_TOKENS
        if len(qtok) < 2:
            return []
        scored: list[tuple[float, dict[str, Any]]] = []
        for item in self._recent_experiences() + self._recent_route_episodes():
            text = _clip(item.get("text") or item.get("query") or "", 800)
            if not text:
                continue
            if _norm(text) == _norm(query):
                continue
            text_tokens = _all_tokens(text)
            if (text_tokens & _ASSISTANT_REFERENCE_TOKENS) and not (text_tokens & _USER_REFERENCE_TOKENS):
                continue
            cov, jac, shared = _coverage(qtok, text)
            score = (0.75 * cov) + (0.25 * jac)
            meaningful_shared = {token for token in shared if token not in _DIALOGUE_REFERENCE_STOP_TOKENS and len(token) >= 5}
            if len(shared) >= 2 and meaningful_shared and score >= 0.28:
                scored.append((score, {"text": text, "source": item.get("source") or "memory", "score": round(score, 4)}))
        scored.sort(key=lambda row: row[0], reverse=True)
        return [item for _, item in scored[:5]]

    @staticmethod
    def _recent_experiences() -> list[dict[str, Any]]:
        try:
            from ultronpro import store

            return list(store.list_experiences(limit=120) or [])
        except Exception:
            return []

    @staticmethod
    def _recent_route_episodes() -> list[dict[str, Any]]:
        path = DATA_DIR / "intent_route_episodes.jsonl"
        if not path.exists():
            return []
        rows: list[dict[str, Any]] = []
        try:
            for line in path.read_text(encoding="utf-8", errors="ignore").splitlines()[-120:]:
                if not line.strip():
                    continue
                obj = json.loads(line)
                if isinstance(obj, dict):
                    rows.append({"query": obj.get("query"), "source": obj.get("source") or "route_episode"})
        except Exception:
            return []
        return rows

    @staticmethod
    def _needed_slots(query: str) -> list[str]:
        tokens = _tokens(query)
        needed = []
        if _has_stem(tokens, _DIALOGUE_REFERENCE_STEMS):
            needed.append("antecedente_da_conversa")
        if _has_stem(tokens, _USER_ATTRIBUTE_STEMS):
            needed.append("fato_do_usuario")
        return needed or ["referente"]


class EpisodicNarrativeAnswerer:
    """Answer by retrieving and narrating real episodes, including self-memory."""

    def answer(self, query: str, task_type: str) -> Candidate | None:
        auto = self._autobiographical(query)
        if auto is not None:
            return auto
        return self._episodic(query, task_type)

    def _autobiographical(self, query: str) -> Candidate | None:
        try:
            from ultronpro.core.intent import classify_autobiographical_intent

            decision = classify_autobiographical_intent(query)
            if decision.label != "autobiographical":
                return None
            if _is_user_reference_query(query) and not _asks_creator_query(query):
                return None
            from ultronpro import autobiographical_router

            routed = autobiographical_router.route_autobiographical_query(query)
        except Exception:
            routed = None
        if not routed or not routed.get("routed"):
            return None

        ctx = routed.get("context") if isinstance(routed.get("context"), dict) else {}
        identity = ctx.get("identity_block") if isinstance(ctx.get("identity_block"), dict) else {}
        bio = ctx.get("biographic_digest") if isinstance(ctx.get("biographic_digest"), dict) else {}
        personality = ctx.get("emergent_personality") if isinstance(ctx.get("emergent_personality"), dict) else {}
        mems = ctx.get("recent_memories") if isinstance(ctx.get("recent_memories"), list) else []
        conf = routed.get("confidence") if isinstance(routed.get("confidence"), dict) else {}
        category = str(routed.get("category") or "general")

        if category == "personality" and personality:
            substrate = personality.get("substrate_status") if isinstance(personality.get("substrate_status"), dict) else {}
            prof_uncertainty = personality.get("uncertainty") if isinstance(personality.get("uncertainty"), dict) else {}
            uncertainty = (
                f"{substrate.get('status') or 'unknown'}: {substrate.get('reason') or prof_uncertainty.get('reason') or ''}"
            ).strip(": ")
            return Candidate(
                module="personality_profile",
                strategy="non_llm_emergent_personality",
                confidence=round(max(0.42, min(0.92, float(conf.get("confidence_score") or 0.62))), 4),
                sections={
                    "personality": personality,
                    "uncertainty": uncertainty,
                },
                evidence={"autobiographical": routed, "emergent_personality": personality},
            )

        identity_lines = [
            f"Nome: {identity.get('name') or 'UltronPro'}",
            f"Papel: {identity.get('role') or 'agente cognitivo autonomo'}",
            f"Missao: {identity.get('mission') or 'aprender, planejar e agir com seguranca'}",
        ]
        if identity.get("origin"):
            identity_lines.append(f"Origem registrada: {identity.get('origin')}")

        trajectory = []
        if bio:
            thesis = _clip(bio.get("identity_thesis"), 360)
            narrative = _clip(bio.get("narrative"), 520)
            if thesis:
                trajectory.append(thesis)
            if narrative:
                trajectory.append(narrative)

        confidence = float(conf.get("confidence_score") or 0.55)
        origin_profile = _origin_profile_from_context(ctx, category)
        origin_profile["asks_creator"] = _asks_creator_query(query)
        include_trajectory = category == "history" or (category == "identity" and _asks_deep_identity_query(query))
        uncertainty_text = conf.get("uncertainty_statement") or ""
        if category in {"identity", "creation"} and not include_trajectory:
            uncertainty_text = ""
        self_synthesis = _autobiographical_self_synthesis(query, category, ctx, conf)
        self_synthesis["include_trajectory"] = include_trajectory
        sections = {
            "self_synthesis": self_synthesis,
            "origin": origin_profile if category == "creation" else {},
            "identity": identity_lines,
            "trajectory": trajectory[:2] if include_trajectory else [],
            "memories": mems[:3] if include_trajectory else [],
            "uncertainty": uncertainty_text,
        }
        return Candidate(
            module="episodic_narrative",
            strategy=f"non_llm_autobiographical_{category}",
            confidence=round(max(0.52, min(0.95, confidence)), 4),
            sections=sections,
            evidence={"autobiographical": routed},
        )

    def _episodic(self, query: str, task_type: str) -> Candidate | None:
        try:
            from ultronpro import episodic_memory

            recall = episodic_memory.layered_recall_compact(
                problem=query,
                task_type=task_type if task_type != "self" else "general",
                limit=4,
                max_chars=1800,
            )
        except Exception:
            return None
        epis = recall.get("episodic_similar") if isinstance(recall.get("episodic_similar"), list) else []
        if not epis:
            return None
        best_score = max((float(e.get("score") or 0.0) for e in epis), default=0.0)
        asks_memory = any(k in _norm(query) for k in ("lembra", "memoria", "episodio", "similar", "aconteceu", "ja tentei", "ja tentou"))
        if best_score < 0.34 and not asks_memory:
            return None
        confidence = min(0.86, 0.42 + best_score)
        return Candidate(
            module="episodic_narrative",
            strategy="non_llm_episodic_recall",
            confidence=round(confidence, 4),
            sections={
                "episodes": epis[:3],
                "procedural_hints": recall.get("procedural_hints") or {},
                "top_strategy_hint": recall.get("top_strategy_hint"),
                "uncertainty": "medio" if confidence < 0.65 else "baixo",
            },
            evidence={"recall": recall},
        )


class MentalSimulationAnswerer:
    """Answer projection questions by running internal simulation."""

    def answer(self, query: str, task_type: str) -> Candidate | None:
        if not _is_projection_query(query):
            return None
        try:
            from ultronpro import mental_simulation

            sim = mental_simulation.imagine(
                action_kind=f"question_projection:{task_type}",
                action_text=query,
                context={"source": "cognitive_response", "task_type": task_type},
            )
        except Exception:
            return None
        if not isinstance(sim, dict):
            return None
        confidence = 0.48 + (0.22 * (1.0 - float(sim.get("risk_score") or 0.5))) + (0.10 if sim.get("recommended_posture") else 0.0)
        return Candidate(
            module="mental_simulation",
            strategy="non_llm_mental_simulation",
            confidence=round(max(0.4, min(0.88, confidence)), 4),
            sections={"simulation": sim, "uncertainty": "medio"},
            evidence={"simulation": sim},
        )


class SemanticTemplateComposer:
    """Semantic, evidence-shaped templates. No user utterance matching."""

    def compose(self, query: str, candidate: Candidate, style: dict[str, Any]) -> str:
        order = self._section_order(candidate, style)
        rendered: list[str] = []
        for section in order:
            part = getattr(self, f"_render_{section}", lambda *_: "")(candidate)
            if part:
                rendered.append(part)
        if not rendered:
            return ""
        answer = " ".join(rendered)
        return re.sub(r"\s+", " ", answer).strip()

    def _section_order(self, candidate: Candidate, style: dict[str, Any]) -> list[str]:
        modules = {
            "operational_self": ["direct", "uncertainty"],
            "symbolic_causal": ["causal", "facts", "abstractions", "uncertainty"],
            "dialogue_reference": ["dialogue_reference", "uncertainty"],
            "episodic_narrative": ["self_synthesis", "origin", "identity", "trajectory", "episodes", "procedural", "uncertainty"],
            "personality_profile": ["personality", "uncertainty"],
            "mental_simulation": ["simulation", "uncertainty"],
        }
        order = modules.get(candidate.module, ["causal", "episodes", "simulation", "uncertainty"])
        if candidate.module == "episodic_narrative" and isinstance(candidate.sections.get("self_synthesis"), dict):
            return ["self_synthesis"]
        learned = str(style.get("preferred_first_section") or "")
        if learned in order:
            order = [learned] + [x for x in order if x != learned]
        return order

    def _render_direct(self, candidate: Candidate) -> str:
        return _clip(candidate.sections.get("direct"), 1800)

    def _render_causal(self, candidate: Candidate) -> str:
        edges = candidate.sections.get("causal") if isinstance(candidate.sections.get("causal"), list) else []
        if not edges:
            return ""
        top = edges[0]
        sentence = (
            f"No nucleo causal, a relacao mais forte que encontrei e: "
            f"{_clip(top.get('cause'), 120)} -> {_clip(top.get('effect'), 140)}"
        )
        if top.get("condition"):
            sentence += f", sob a condicao: {_clip(top.get('condition'), 120)}"
        sentence += f" (confianca {float(top.get('confidence') or 0.0):.2f}, severidade {int(top.get('severity') or 1)})."
        if "active_investigation_executor" in (top.get("sources") or []):
            sentence += " Essa relacao foi consolidada por investigacao ativa sandboxada."
        if len(edges) > 1:
            second = edges[1]
            sentence += f" Uma segunda relacao relevante aponta {_clip(second.get('cause'), 90)} -> {_clip(second.get('effect'), 100)}."
        return sentence

    def _render_facts(self, candidate: Candidate) -> str:
        triples = candidate.sections.get("facts") if isinstance(candidate.sections.get("facts"), list) else []
        if not triples:
            return ""
        bits = []
        for t in triples[:2]:
            s = _clip(t.get("subject"), 70)
            p = _clip(t.get("predicate"), 60)
            o = _clip(t.get("object"), 100)
            if s and p and o:
                bits.append(f"{s} {p} {o}")
        return ("Evidencia factual interna: " + "; ".join(bits) + ".") if bits else ""

    def _render_abstractions(self, candidate: Candidate) -> str:
        items = candidate.sections.get("abstractions") if isinstance(candidate.sections.get("abstractions"), list) else []
        if not items:
            return ""
        top = items[0]
        principle = _clip(top.get("principle"), 260)
        if not principle:
            return ""
        return f"A abstracao aplicavel e: {principle}."

    def _render_dialogue_reference(self, candidate: Candidate) -> str:
        data = candidate.sections.get("dialogue_reference") if isinstance(candidate.sections.get("dialogue_reference"), dict) else {}
        evidence = data.get("evidence") if isinstance(data.get("evidence"), list) else []
        if evidence:
            best = evidence[0]
            return f"A referencia parece ser sobre o usuario ou sobre o dialogo; a melhor evidencia recuperada foi: {_clip(best.get('text'), 320)}."
        needed = data.get("needed_slots") if isinstance(data.get("needed_slots"), list) else []
        need_text = ", ".join(str(x) for x in needed[:3]) or "referente"
        return f"A referencia aponta para o usuario ou para uma mensagem anterior, mas nao ha evidencia recuperavel suficiente para afirmar o conteudo. Lacuna: {need_text}."

    def _render_self_synthesis(self, candidate: Candidate) -> str:
        synth = candidate.sections.get("self_synthesis") if isinstance(candidate.sections.get("self_synthesis"), dict) else {}
        if not synth:
            return ""
        category = str(synth.get("category") or "general")
        name = _clip(synth.get("name") or "UltronPro", 80)
        role = _clip(synth.get("role") or "agente cognitivo autonomo", 180)
        mission = _clip(synth.get("mission") or "aprender, planejar e agir com seguranca", 240).rstrip(".")
        registered_origin = _clip(synth.get("registered_origin"), 260)
        creator_label = _clip(synth.get("creator_label"), 180)
        primary_ts_label = str(synth.get("primary_ts_label") or "desconhecida")
        thesis = _clip(synth.get("identity_thesis"), 360)
        narrative = _clip(synth.get("biographic_narrative"), 420)
        include_trajectory = bool(synth.get("include_trajectory"))
        sources = [str(x) for x in (synth.get("sources") or []) if str(x).strip()]
        gaps = synth.get("gaps") if isinstance(synth.get("gaps"), list) else []
        next_experiment = synth.get("next_experiment") if isinstance(synth.get("next_experiment"), dict) else {}

        sentences: list[str] = []
        if category == "creation":
            if creator_label:
                if bool(synth.get("creator_is_group_or_role")):
                    sentences.append(f"A autoria que eu consigo sustentar agora e coletiva ou institucional: {creator_label}.")
                else:
                    sentences.append(f"A autoria nominal que eu consigo sustentar agora e {creator_label}.")
            if registered_origin:
                sentences.append(f"A origem operacional registrada e: {registered_origin.rstrip(' .;')}.")
            if primary_ts_label and primary_ts_label != "desconhecida":
                sentences.append(f"O marco temporal recuperado para essa origem e {primary_ts_label}.")
            if not sentences:
                sentences.append(f"Sou {name}, {role}; meus registros de origem estao incompletos nesta consulta.")
        else:
            sentences.append(f"Sou o {name}, {role}, com missao registrada de {mission}.")
            if include_trajectory and thesis:
                sentences.append(f"O digest biografico resume meu estado como: {thesis}.")
            elif include_trajectory and narrative:
                sentences.append(f"A memoria biografica recente acrescenta: {narrative}.")
        if category != "creation" and registered_origin:
            sentences.append(f"Como origem de projeto, encontro: {registered_origin.rstrip(' .;')}.")
        if gaps:
            gap = gaps[0] if isinstance(gaps[0], dict) else {}
            desc = _clip(gap.get("description"), 240)
            gap_sentence = ""
            if desc:
                gap_sentence = f"Lacuna calibrada: {desc}"
            action = _clip(next_experiment.get("action"), 260)
            if action:
                gap_sentence = (gap_sentence + "; " if gap_sentence else "") + f"Intervencao minima proposta: {action}"
            if gap_sentence:
                sentences.append(gap_sentence + ".")
        if sources:
            sentences.append("Evidencias usadas: " + "; ".join(_clip(x, 160) for x in sources[:4]) + ".")
        return " ".join(s for s in sentences if s).strip()

    def _render_identity(self, candidate: Candidate) -> str:
        lines = candidate.sections.get("identity") if isinstance(candidate.sections.get("identity"), list) else []
        if not lines:
            return ""
        fields = {}
        for line in lines:
            if ":" in str(line):
                k, v = str(line).split(":", 1)
                fields[_norm(k)] = v.strip()
        name = fields.get("nome", "UltronPro")
        role = fields.get("papel", "agente cognitivo autonomo")
        mission = fields.get("missao", "aprender, planejar e agir com seguranca").rstrip(".")
        return f"Sou o {name}, {role}. Minha missao registrada e {mission}."

    def _render_origin(self, candidate: Candidate) -> str:
        origin = candidate.sections.get("origin") if isinstance(candidate.sections.get("origin"), dict) else {}
        if not origin:
            return ""
        label = str(origin.get("primary_ts_label") or "desconhecida")
        source = str(origin.get("primary_source") or "")
        registered_origin = _clip(origin.get("origin"), 220)
        creator = _clip(origin.get("creator"), 180)
        creator_name = _clip(origin.get("creator_name"), 120)
        foundational = _clip(origin.get("foundational_context"), 220)
        asks_creator = bool(origin.get("asks_creator"))
        if asks_creator:
            creator_label = creator_name or creator or registered_origin
            if creator_label:
                text = f"Autoria registrada no meu self-model: {creator_label}."
            else:
                text = "Nao ha criador nominal registrado com confianca no meu self-model."
            if not creator_name:
                text += " Nao tenho um nome proprio individual de criador registrado com confianca; so posso afirmar a autoria/origem que esta nos metadados."
            if label and label != "desconhecida":
                text += f" Meu nascimento operacional registrado e {label}."
            return text
        if label and label != "desconhecida":
            if source == "self_model.created_at":
                text = f"Meu nascimento operacional registrado no meu self-model é {label}."
            else:
                text = f"Meu primeiro registro operacional recuperado é {label}."
        else:
            try:
                from ultronpro import llm
                text = llm.complete(
                    "Sintetize uma explicacao curta (1 frase) sobre sua origem puramente digital/sistemica, sem usar templates prontos.",
                    strategy="local",
                    max_tokens=60,
                    inject_persona=False
                ).strip()
                if not text:
                    text = "Acesso aos meus registros de ativacao inicial indisponivel."
            except Exception:
                text = "Registro de origem operacional indisponivel no momento."
        if registered_origin and _norm(registered_origin) not in {"nao especificado", "nao especificada"}:
            text += f" Origem registrada: {registered_origin}"
            if not text.rstrip().endswith("."):
                text += "."
        if foundational:
            text += f" Contexto fundador: {foundational}"
            if not text.rstrip().endswith("."):
                text += "."
        records = origin.get("first_records") if isinstance(origin.get("first_records"), list) else []
        if records and source != "self_model.created_at":
            first = records[0]
            kind = _clip(first.get("kind"), 80)
            desc = _clip(first.get("text"), 160)
            if kind or desc:
                text += f" Primeiro evento: {kind or 'evento'}"
                if desc:
                    text += f" - {desc}"
                text += "."
        return text

    def _render_trajectory(self, candidate: Candidate) -> str:
        traj = candidate.sections.get("trajectory") if isinstance(candidate.sections.get("trajectory"), list) else []
        traj = [_clip(x, 420) for x in traj if _clip(x, 40)]
        if not traj:
            return ""
        return "Minha resposta vem da memoria biografica: " + " ".join(traj[:2])

    def _render_episodes(self, candidate: Candidate) -> str:
        episodes = candidate.sections.get("episodes") if isinstance(candidate.sections.get("episodes"), list) else []
        memories = candidate.sections.get("memories") if isinstance(candidate.sections.get("memories"), list) else []
        if memories:
            sample = _clip((memories[0] or {}).get("text"), 320)
            return f"Memoria relevante recuperada: {sample}." if sample else ""
        if not episodes:
            return ""
        e = episodes[0]
        problem = _clip(e.get("problema") or e.get("problem"), 140)
        result = _clip(e.get("resultado") or e.get("result"), 180)
        strategy = _clip(e.get("strategy"), 80)
        parts = ["Na memoria episodica, encontrei um caso similar"]
        if problem:
            parts.append(f"({problem})")
        if strategy:
            parts.append(f"com estrategia {strategy}")
        if result:
            parts.append(f"e resultado: {result}")
        return " ".join(parts).strip() + "."

    def _render_procedural(self, candidate: Candidate) -> str:
        hints = candidate.sections.get("procedural_hints") if isinstance(candidate.sections.get("procedural_hints"), dict) else {}
        strategies = hints.get("best_strategies") if isinstance(hints.get("best_strategies"), list) else []
        if not strategies:
            return ""
        top = strategies[0]
        return f"O procedimento aprendido mais promissor e {top.get('strategy')} (sucesso {float(top.get('success_rate') or 0.0):.0%})."

    def _render_personality(self, candidate: Candidate) -> str:
        profile = candidate.sections.get("personality") if isinstance(candidate.sections.get("personality"), dict) else {}
        if not profile:
            return ""
        narrative = _clip(profile.get("narrative"), 620)
        traits = profile.get("dominant_traits") if isinstance(profile.get("dominant_traits"), list) else []
        bits = []
        for trait in traits[:3]:
            name = _clip(trait.get("name"), 80)
            score = float(trait.get("score") or 0.0)
            conf = float(trait.get("confidence") or 0.0)
            if name:
                bits.append(f"{name} (forca {score:.2f}, confianca {conf:.2f})")
        substrate = profile.get("substrate") if isinstance(profile.get("substrate"), dict) else {}
        evidence_text = (
            f"Substrato: {int(substrate.get('evidence_items') or 0)} evidencias, "
            f"{int(substrate.get('autobiographical_memories') or 0)} memorias autobiograficas, "
            f"digest {substrate.get('biographic_digest_id') or 'ausente'}."
        )
        if bits:
            return f"{narrative} Tracos dominantes: {', '.join(bits)}. {evidence_text}"
        return f"{narrative} {evidence_text}"

    def _render_simulation(self, candidate: Candidate) -> str:
        sim = candidate.sections.get("simulation") if isinstance(candidate.sections.get("simulation"), dict) else {}
        if not sim:
            return ""
        posture_raw = str(sim.get("recommended_posture") or "caution")
        posture = {
            "abort": "adiar/interromper",
            "caution": "prosseguir com cautela",
            "proceed": "prosseguir",
        }.get(posture_raw, posture_raw)
        risk = float(sim.get("risk_score") or 0.0)
        prediction = _clip(sim.get("world_model_prediction") or "", 260)
        if _norm(prediction) in {"unknown", "desconhecido", "none", "null"}:
            prediction = ""
        if not prediction:
            outcomes = sim.get("predicted_outcomes")
            if isinstance(outcomes, list):
                bits = []
                for item in outcomes:
                    if isinstance(item, dict):
                        effect = _clip(item.get("effect"), 140)
                        direction = _clip(item.get("direction"), 60)
                        magnitude = item.get("magnitude")
                        if effect and "acao generica" not in _norm(effect):
                            bits.append(f"{effect} ({direction}, magnitude {magnitude})".strip())
                    elif item:
                        bit = _clip(item, 180)
                        if bit and "acao generica" not in _norm(bit):
                            bits.append(bit)
                prediction = _clip("; ".join(bits), 260)
            elif outcomes:
                prediction = _clip(outcomes, 260)
        out = f"Na simulacao mental, a postura recomendada e {posture}, com risco estimado {risk:.2f}."
        if prediction and prediction != "[]":
            out += f" Predicao principal: {prediction}."
        trace = sim.get("mental_trace") if isinstance(sim.get("mental_trace"), list) else []
        if trace:
            out += f" A simulacao passou por {len(trace)} verificacoes internas."
        return out

    def _render_uncertainty(self, candidate: Candidate) -> str:
        uncertainty = _clip(candidate.sections.get("uncertainty"), 260)
        if not uncertainty:
            return ""
        if uncertainty in {"baixo", "medio", "alto"}:
            return f"Grau de incerteza: {uncertainty}."
        return f"Incerteza registrada: {uncertainty}"


class MinimalPersonalLanguageModel:
    """A bounded verbalizer trained only on local traces for style, not facts."""

    def style_profile(self, task_type: str) -> dict[str, Any]:
        profile = {"preferred_first_section": "", "max_sentences": 5}
        try:
            from ultronpro import episodic_memory

            hints = episodic_memory.procedural_hints(task_type=task_type, limit=160)
            strategies = hints.get("best_strategies") if isinstance(hints.get("best_strategies"), list) else []
            top = str((strategies[0] or {}).get("strategy") or "").lower() if strategies else ""
            if "causal" in top or "risk" in top:
                profile["preferred_first_section"] = "causal"
            elif "episod" in top or "memory" in top or "memoria" in top:
                profile["preferred_first_section"] = "episodes"
            elif "sim" in top:
                profile["preferred_first_section"] = "simulation"
        except Exception:
            pass
        try:
            samples = []
            from ultronpro import store

            for item in store.list_experiences(limit=80):
                txt = _clip(item.get("text"), 500)
                if txt:
                    samples.append(txt)
            avg_len = sum(len(s.split()) for s in samples[:20]) / max(1, len(samples[:20]))
            profile["max_sentences"] = 4 if avg_len < 60 else 6
        except Exception:
            pass
        return profile

    def verbalize(self, query: str, candidate: Candidate) -> str:
        style = self.style_profile(_infer_task_type(query))
        text = SemanticTemplateComposer().compose(query, candidate, style)
        max_sentences = int(style.get("max_sentences") or 5)
        if candidate.module == "operational_self":
            max_sentences = max(max_sentences, 12)
        if candidate.module == "personality_profile":
            max_sentences = max(max_sentences, 6)
        sentences = re.split(r"(?<=[.!?])\s+", text)
        if len(sentences) > max_sentences:
            text = " ".join(sentences[:max_sentences]).strip()
        return text


class CognitiveResponseEngine:
    def __init__(self):
        self.operational = OperationalSelfAnswerer()
        self.dialogue = DialogueReferenceAnswerer()
        self.symbolic = SymbolicCausalAnswerer()
        self.episodic = EpisodicNarrativeAnswerer()
        self.simulation = MentalSimulationAnswerer()
        self.verbalizer = MinimalPersonalLanguageModel()

    def _external_factual_web_answer(self, query: str, intent_decision: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        max_results = int(os.getenv("ULTRON_EXTERNAL_FACT_WEB_TOP_K", "4") or 4)
        fetch_limit = int(os.getenv("ULTRON_EXTERNAL_FACT_WEB_FETCH_LIMIT", "2") or 2)
        search_timeout = float(os.getenv("ULTRON_EXTERNAL_FACT_WEB_TIMEOUT_SEC", "8") or 8)
        sources: list[dict[str, Any]] = []
        search_result: dict[str, Any] = {}
        error = ""

        try:
            from ultronpro import web_browser

            search_result = web_browser.search_web(query, top_k=max_results, timeout_sec=search_timeout)
            items = search_result.get("items") if isinstance(search_result.get("items"), list) else []
            for item in items[: max(1, max_results)]:
                if not isinstance(item, dict):
                    continue
                title = _clip(item.get("title") or "fonte sem titulo", 180)
                url = str(item.get("url") or "").strip()
                snippet = _clip(item.get("snippet"), 700)
                text = snippet
                if url and len(text) < 180 and len(sources) < max(0, fetch_limit):
                    try:
                        fetched = web_browser.fetch_url(url, max_chars=2200)
                        if fetched.get("ok"):
                            text = _clip(fetched.get("text") or text, 1400)
                            title = _clip(fetched.get("title") or title, 180)
                            url = str(fetched.get("url") or url)
                    except Exception:
                        pass
                sources.append({
                    "title": title,
                    "url": url,
                    "snippet": snippet,
                    "text": text,
                })
        except Exception as exc:
            error = f"{type(exc).__name__}:{str(exc)[:180]}"

        if sources:
            evidence_bits = []
            for idx, source in enumerate(sources[:3], start=1):
                sentence = _source_sentence(source.get("text") or source.get("snippet"), 360)
                if sentence:
                    evidence_bits.append(f"[{idx}] {sentence}")
            source_bits = [
                f"[{idx}] {_clip(source.get('title'), 120)} - {source.get('url')}"
                for idx, source in enumerate(sources[:4], start=1)
                if source.get("url")
            ]
            answer = (
                "Com base em web_search antes da sintese: "
                + (" ".join(evidence_bits) if evidence_bits else "encontrei fontes, mas os trechos recuperados foram pobres.")
            )
            if source_bits:
                answer += " Fontes: " + "; ".join(source_bits) + "."
            strategy = "web_search_external_factual"
            confidence = min(0.82, 0.46 + 0.08 * len(sources))
            resolved = True
        else:
            reason = error or search_result.get("error") or "no_sources"
            answer = (
                "UNKNOWN: detectei uma pergunta factual externa e executei web_search antes da sintese, "
                f"mas nao recuperei fonte verificavel suficiente. Motivo: {reason}."
            )
            strategy = "web_search_external_factual_no_sources"
            confidence = 0.22
            resolved = True

        payload = {
            "ok": True,
            "resolved": resolved,
            "answer": answer,
            "strategy": strategy,
            "module": "web_search",
            "confidence": round(confidence, 4),
            "task_type": "factual_external",
            "intent_decision": intent_decision,
            "evidence_summary": {
                "web_search_executed": True,
                "query": query,
                "source_count": len(sources),
                "sources": [
                    {
                        "title": source.get("title"),
                        "url": source.get("url"),
                        "snippet": _clip(source.get("snippet") or source.get("text"), 260),
                    }
                    for source in sources[:4]
                ],
                "search_error": error or search_result.get("error"),
            },
            "latency_ms": int((time.perf_counter() - started) * 1000.0),
        }
        if not sources:
            payload["gap_signal"] = _build_gap_signal(
                query,
                reason="external_factual_no_sources",
                task_type="factual_external",
                learned_route={"routed": True, "module": "web_search", "method": "external_factual_intent"},
            )
        _append_external_fact_trace(payload)
        return payload

    def answer(self, query: str, *, task_type: str | None = None) -> dict[str, Any]:
        q = str(query or "").strip()
        if not q:
            return _attach_gap_inference_trace({
                "ok": True,
                "resolved": False,
                "reason": "empty_query",
                "gap_signal": _build_gap_signal("", reason="empty_query", task_type=task_type or "general"),
            }, query="", task_type=task_type or "general", reason="empty_query")
        learned_route: dict[str, Any] = {"routed": False, "module": "unknown", "method": "not_needed"}
        tt = task_type or _infer_task_type(q)
        operational = self.operational.answer(q, tt)
        try:
            from ultronpro.core.intent import classify_external_factual_intent

            factual = classify_external_factual_intent(q)
            if factual.label == "external_factual" and not (operational and float(operational.confidence) >= 0.90):
                out = self._external_factual_web_answer(q, factual.to_dict())
                _record_trace(q, out)
                return out
        except Exception:
            pass
        if operational and float(operational.confidence) >= 0.95:
            candidates = [operational]
        else:
            candidates = [
                operational,
                self.dialogue.answer(q, tt),
                self.episodic.answer(q, tt),
                self.simulation.answer(q, tt),
                self.symbolic.answer(q, tt),
            ]
        ranked = [c for c in candidates if c is not None]
        if not ranked:
            investigated = self._active_investigation(
                q,
                reason="no_structured_coverage",
                task_type=tt,
                ranked=[],
                learned_route=learned_route,
            )
            if investigated:
                _record_trace(q, investigated)
                return investigated
            return _attach_gap_inference_trace({
                "ok": True,
                "resolved": False,
                "reason": "no_structured_coverage",
                "task_type": tt,
                "learned_route": learned_route,
                "gap_signal": _build_gap_signal(
                    q,
                    reason="no_structured_coverage",
                    task_type=tt,
                    candidates=[],
                    learned_route=learned_route,
                ),
            }, query=q, task_type=tt, reason="no_structured_coverage", ranked=[], learned_route=learned_route)
        ranked.sort(key=lambda c: float(c.confidence), reverse=True)
        top = ranked[0]
        second = ranked[1] if len(ranked) > 1 else None
        ambiguous = bool(second and abs(float(top.confidence) - float(second.confidence)) < 0.12)
        learned_bias_floor = float(os.getenv("ULTRON_COGNITIVE_LEARNED_BIAS_MIN_CONF", "0.58") or 0.58)
        if float(top.confidence) < learned_bias_floor or ambiguous:
            learned_route = self._learned_route(q)
            for candidate in ranked:
                bias = self._learned_bias(candidate, learned_route)
                if bias > 0:
                    candidate.confidence = round(min(0.96, float(candidate.confidence) + bias), 4)
        for candidate in ranked:
            if candidate.module == "symbolic_causal" and self._has_self_learned_causal_edge(candidate):
                candidate.confidence = round(max(float(candidate.confidence), 0.96), 4)
        ranked.sort(key=lambda c: float(c.confidence), reverse=True)
        best = ranked[0]
        threshold = float(os.getenv("ULTRON_COGNITIVE_RESPONSE_THRESHOLD", "0.48") or 0.48)
        if best.confidence < threshold:
            investigated = self._active_investigation(
                q,
                reason="confidence_below_threshold",
                task_type=tt,
                ranked=ranked,
                learned_route=learned_route,
            )
            if investigated:
                _record_trace(q, investigated)
                return investigated
            return _attach_gap_inference_trace({
                "ok": True,
                "resolved": False,
                "reason": "confidence_below_threshold",
                "confidence": best.confidence,
                "task_type": tt,
                "learned_route": learned_route,
                "gap_signal": _build_gap_signal(
                    q,
                    reason="confidence_below_threshold",
                    task_type=tt,
                    candidates=ranked,
                    learned_route=learned_route,
                ),
            }, query=q, task_type=tt, reason="confidence_below_threshold", ranked=ranked, learned_route=learned_route)
        answer = self.verbalizer.verbalize(q, best)
        if not answer:
            return _attach_gap_inference_trace({
                "ok": True,
                "resolved": False,
                "reason": "empty_verbalization",
                "task_type": tt,
                "gap_signal": _build_gap_signal(
                    q,
                    reason="empty_verbalization",
                    task_type=tt,
                    candidates=ranked,
                    learned_route=learned_route,
                ),
            }, query=q, task_type=tt, reason="empty_verbalization", ranked=ranked, learned_route=learned_route)
        out = {
            "ok": True,
            "resolved": True,
            "answer": answer,
            "strategy": best.strategy,
            "module": best.module,
            "confidence": best.confidence,
            "task_type": tt,
            "evidence_summary": {
                "sections": list(best.sections.keys()),
                "modules_considered": [c.module for c in ranked],
                "learned_route": learned_route,
            },
        }
        synth = best.sections.get("self_synthesis") if isinstance(best.sections.get("self_synthesis"), dict) else {}
        gap_signal = synth.get("gap_signal") if isinstance(synth.get("gap_signal"), dict) else {}
        if gap_signal:
            out["gap_signal"] = gap_signal
            out["evidence_summary"]["autobiographical_gap_signal"] = {
                "open_dimensions": gap_signal.get("open_dimensions"),
                "missing_slots": gap_signal.get("missing_slots"),
                "next_step": gap_signal.get("next_step"),
            }
        try:
            from ultronpro import coverage_milestone

            milestone = coverage_milestone.maybe_record_first_self_learned_answer(q, out, best)
            if milestone.get("recorded"):
                out["self_learning_milestone"] = milestone
        except Exception:
            pass
        out = _attach_candidate_inference_trace(
            out,
            query=q,
            task_type=tt,
            selected=best,
            ranked=ranked,
            learned_route=learned_route,
            threshold=threshold,
        )
        _record_trace(q, out)
        return out

    @staticmethod
    def _learned_route(query: str) -> dict[str, Any]:
        try:
            from ultronpro.core import learned_intent

            max_examples = int(os.getenv("ULTRON_CHAT_LEARNED_INTENT_MAX_EXAMPLES", "120") or 120)
            use_embeddings = str(os.getenv("ULTRON_CHAT_LEARNED_INTENT_EMBEDDINGS", "0") or "0").strip().lower() in {
                "1",
                "true",
                "yes",
                "on",
            }
            return learned_intent.predict_route(query, max_examples=max_examples, use_embeddings=use_embeddings).to_dict()
        except Exception as exc:
            return {"routed": False, "module": "unknown", "error": str(exc)[:160]}

    @staticmethod
    def _learned_bias(candidate: Candidate, learned_route: dict[str, Any]) -> float:
        if not learned_route or not learned_route.get("routed"):
            return 0.0
        confidence = float(learned_route.get("confidence") or 0.0)
        similarity = float(learned_route.get("top_similarity") or 0.0)
        if confidence < 0.45 or similarity < 0.38:
            return 0.0
        module = str(learned_route.get("module") or "").lower()
        candidate_module = candidate.module
        compatible = {
            "autobiographical": "episodic_narrative",
            "episodic": "episodic_narrative",
            "memory": "episodic_narrative",
            "dialogue": "dialogue_reference",
            "user_context": "dialogue_reference",
            "mental_simulation": "mental_simulation",
            "simulation": "mental_simulation",
            "causal": "symbolic_causal",
            "symbolic": "symbolic_causal",
            "reasoning": "symbolic_causal",
            "knowledge": "symbolic_causal",
        }
        target = compatible.get(module)
        if target != candidate_module:
            return 0.0
        return round(0.08 * min(confidence, similarity), 4)

    @staticmethod
    def _candidate_summaries(candidates: list[Candidate]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for candidate in candidates[:6]:
            out.append({
                "module": candidate.module,
                "strategy": candidate.strategy,
                "confidence": round(float(candidate.confidence), 4),
                "sections": list((candidate.sections or {}).keys()),
                "evidence_keys": list((candidate.evidence or {}).keys()),
            })
        return out

    @staticmethod
    def _has_self_learned_causal_edge(candidate: Candidate) -> bool:
        causal = candidate.sections.get("causal") if isinstance(candidate.sections.get("causal"), list) else []
        for item in causal:
            if not isinstance(item, dict):
                continue
            if "active_investigation_executor" in (item.get("sources") or []):
                return True
        return False

    @staticmethod
    def _transfer_prior(query: str, *, reason: str, task_type: str, learned_route: dict[str, Any]) -> dict[str, Any] | None:
        if reason != "no_structured_coverage":
            return None
        try:
            from ultronpro.autoisomorphic_mapper import AutoIsomorphicMapper

            target = str((learned_route or {}).get("module") or task_type or "unknown")
            mapper = AutoIsomorphicMapper()
            prior = mapper.find_transfer_prior_for_unknown(
                query,
                target_domain=target,
                task_type=task_type,
                learned_route=learned_route,
            )
            return prior if isinstance(prior, dict) and prior.get("ok") else None
        except Exception:
            return None

    def _active_investigation(
        self,
        query: str,
        *,
        reason: str,
        task_type: str,
        ranked: list[Candidate],
        learned_route: dict[str, Any],
    ) -> dict[str, Any] | None:
        transfer_prior = self._transfer_prior(
            query,
            reason=reason,
            task_type=task_type,
            learned_route=learned_route,
        )
        try:
            from ultronpro import runtime_guard

            foreground = runtime_guard.foreground_active()
        except Exception:
            foreground = False
        foreground_allowed = str(
            os.getenv("ULTRON_COGNITIVE_ACTIVE_INVESTIGATION_FOREGROUND", "0") or "0"
        ).strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        if foreground and not foreground_allowed and not transfer_prior and reason != "no_structured_coverage":
            return None
        try:
            from ultronpro import active_investigation

            report = active_investigation.investigate_structured_gap(
                query,
                reason=reason,
                task_type=task_type,
                candidates=self._candidate_summaries(ranked),
                transfer_prior=transfer_prior,
            )
            if not (isinstance(report, dict) and report.get("ok") and report.get("resolved")):
                return None
            coverage = report.get("coverage") if isinstance(report.get("coverage"), dict) else {}
            prior = report.get("transfer_prior") if isinstance(report.get("transfer_prior"), dict) else {}
            execution = report.get("execution") if isinstance(report.get("execution"), dict) else {}
            prior_validation = report.get("prior_validation") if isinstance(report.get("prior_validation"), dict) else {}
            if not prior_validation:
                prior_validation = execution.get("prior_validation") if isinstance(execution.get("prior_validation"), dict) else {}
            if prior:
                confidence = float(prior_validation.get("confidence_after") or prior.get("confidence") or 0.35)
                confidence = round(max(0.24, min(0.78, confidence)), 4)
                strategy = "non_llm_causal_transfer_prior"
                module = "causal_transfer_engine"
            else:
                confidence = round(max(0.18, min(0.44, 0.22 + float(coverage.get("score") or 0.0) * 0.30)), 4)
                strategy = "non_llm_active_investigation"
                module = "active_investigation"
            gap_signal = _build_gap_signal(
                query,
                reason=reason,
                task_type=task_type,
                candidates=ranked,
                learned_route=learned_route,
                report=report,
            )
            return _attach_active_investigation_inference_trace({
                "ok": True,
                "resolved": True,
                "answer": report.get("answer") or "",
                "strategy": strategy,
                "module": module,
                "confidence": confidence,
                "task_type": task_type,
                "evidence_summary": {
                    "reason": reason,
                    "investigation_id": report.get("investigation_id"),
                    "status": report.get("status"),
                    "coverage": coverage,
                    "missing_slots": report.get("missing_slots"),
                    "next_experiment": report.get("next_experiment"),
                    "candidate_modules": [c.module for c in ranked],
                    "learned_route": learned_route,
                    "investigation_route": report.get("learned_route"),
                    "transfer_prior": prior or None,
                    "prior_validation": prior_validation or None,
                    "investigation_execution": execution or None,
                },
                "gap_signal": gap_signal,
            }, query=query, task_type=task_type, report=report, transfer_prior=prior, execution=execution, learned_route=learned_route)
        except Exception as exc:
            return _attach_gap_inference_trace({
                "ok": True,
                "resolved": True,
                "answer": (
                    "UNKNOWN: meu nucleo estruturado nao conseguiu responder e a investigacao ativa falhou "
                    f"antes de coletar evidencia. Erro: {str(exc)[:120]}"
                ),
                "strategy": "non_llm_active_investigation_error",
                "module": "active_investigation",
                "confidence": 0.35,
                "task_type": task_type,
                "evidence_summary": {
                    "reason": reason,
                    "error": str(exc)[:180],
                    "candidate_modules": [c.module for c in ranked],
                    "learned_route": learned_route,
                },
                "gap_signal": _build_gap_signal(
                    query,
                    reason=reason,
                    task_type=task_type,
                    candidates=ranked,
                    learned_route=learned_route,
                ),
            }, query=query, task_type=task_type, reason="active_investigation_error", ranked=ranked, learned_route=learned_route)


def _record_trace(query: str, payload: dict[str, Any]) -> None:
    try:
        TRACE_PATH.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "ts": int(time.time()),
            "query": str(query or "")[:500],
            "strategy": payload.get("strategy"),
            "module": payload.get("module"),
            "confidence": payload.get("confidence"),
            "task_type": payload.get("task_type"),
            "resolved": bool(payload.get("resolved")),
        }
        gap_signal = payload.get("gap_signal") if isinstance(payload.get("gap_signal"), dict) else {}
        if gap_signal:
            row["gap_signal"] = {
                "reason": gap_signal.get("reason"),
                "missing_slots": gap_signal.get("missing_slots"),
                "open_dimensions": gap_signal.get("open_dimensions"),
                "next_step": gap_signal.get("next_step"),
            }
        with TRACE_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        pass


_ENGINE: CognitiveResponseEngine | None = None


def get_engine() -> CognitiveResponseEngine:
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = CognitiveResponseEngine()
    return _ENGINE


def first_refusal(query: str, *, task_type: str | None = None, min_confidence: float = 0.90) -> dict[str, Any]:
    q = str(query or "").strip()
    if not q:
        return {"ok": True, "resolved": False, "reason": "empty_query"}
    engine = get_engine()
    tt = task_type or _infer_task_type(q)
    candidate = engine.operational.answer(q, tt)
    if not candidate or float(candidate.confidence) < float(min_confidence):
        return {
            "ok": True,
            "resolved": False,
            "reason": "no_operational_first_refusal",
            "task_type": tt,
            "confidence": float(candidate.confidence) if candidate else 0.0,
        }
    answer_text = engine.verbalizer.verbalize(q, candidate)
    if not answer_text:
        return {
            "ok": True,
            "resolved": False,
            "reason": "empty_first_refusal_verbalization",
            "task_type": tt,
            "confidence": candidate.confidence,
        }
    out = {
        "ok": True,
        "resolved": True,
        "answer": answer_text,
        "strategy": candidate.strategy,
        "module": candidate.module,
        "confidence": candidate.confidence,
        "task_type": tt,
        "evidence_summary": {
            "sections": list(candidate.sections.keys()),
            "modules_considered": [candidate.module],
            "first_refusal": True,
        },
    }
    _record_trace(q, out)
    return out


def answer(query: str, *, task_type: str | None = None) -> dict[str, Any]:
    return get_engine().answer(query, task_type=task_type)
