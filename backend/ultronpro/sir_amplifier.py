from __future__ import annotations

import json
import re
import time
import unicodedata
from typing import Any, Callable


SIR_SCHEMA_VERSION = "sir.v1"
SIR_SYSTEM_PROMPT = (
    "Gere resposta em PT-BR seguindo ESTRITAMENTE este contexto estruturado. "
    "Não adicione fatos externos. Mantenha tom direto."
)

REQUIRED_SIR_FIELDS = (
    "facts",
    "rules_applied",
    "constraints",
    "causal_graph_excerpt",
    "verification_status",
)

SIR_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "answer",
        "used_fact_ids",
        "used_rule_ids",
        "satisfied_constraints",
        "verification_notes",
    ],
    "properties": {
        "answer": {"type": "string"},
        "used_fact_ids": {"type": "array", "items": {"type": "string"}},
        "used_rule_ids": {"type": "array", "items": {"type": "string"}},
        "satisfied_constraints": {"type": "array", "items": {"type": "string"}},
        "verification_notes": {"type": "string"},
    },
}

_STOPWORDS = {
    "a",
    "ao",
    "aos",
    "as",
    "de",
    "da",
    "das",
    "do",
    "dos",
    "e",
    "em",
    "o",
    "os",
    "ou",
    "para",
    "por",
    "que",
    "se",
    "sem",
    "um",
    "uma",
    "com",
    "como",
    "qual",
    "quais",
    "quem",
    "the",
    "and",
    "for",
    "from",
    "with",
}

_PROHIBITED_EXTERNAL_HINTS = {
    "chatgpt",
    "openai",
    "marvel",
    "stark",
    "banner",
    "sokovia",
    "homem",
    "ferro",
    "tony",
}


class SIRValidationError(ValueError):
    pass


def _ascii_fold(text: Any) -> str:
    value = unicodedata.normalize("NFKD", str(text or "").lower())
    return "".join(ch for ch in value if not unicodedata.combining(ch))


def _compact_text(text: Any, limit: int = 420) -> str:
    value = re.sub(r"\s+", " ", str(text or "").strip())
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 3)].rstrip() + "..."


def _tokens(text: Any) -> set[str]:
    folded = _ascii_fold(text)
    return {
        token
        for token in re.findall(r"[a-z0-9_]{3,}", folded)
        if token not in _STOPWORDS
    }


def _numbers(text: Any) -> set[str]:
    return set(re.findall(r"\b\d+(?:[.,]\d+)?%?\b", str(text or "")))


def _letters(index: int) -> str:
    index = max(0, int(index))
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    out = ""
    while True:
        out = alphabet[index % 26] + out
        index = index // 26 - 1
        if index < 0:
            return out


def _fact_id(index: int) -> str:
    return f"FACT_{index + 1}"


def _rule_id(index: int) -> str:
    return f"RULE_{index + 1}"


def _constraint_id(index: int) -> str:
    return f"CONSTRAINT_{_letters(index)}"


def _causal_id(index: int) -> str:
    return f"CAUSE_{index + 1}"


def _fact(
    index: int,
    text: Any,
    *,
    source: str,
    critical: bool = False,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    value = _compact_text(text)
    tokens = sorted(_tokens(value))[:14]
    return {
        "id": _fact_id(index),
        "anchor": f"[{_fact_id(index)}]",
        "text": value,
        "source": str(source or "unknown")[:80],
        "critical": bool(critical),
        "required_terms": tokens[:8],
        "numbers": sorted(_numbers(value)),
        "metadata": metadata or {},
    }


def _rule(
    index: int,
    rule: Any,
    *,
    input_refs: list[str] | None = None,
    output: Any = "",
    confidence: float = 1.0,
) -> dict[str, Any]:
    return {
        "id": _rule_id(index),
        "anchor": f"[{_rule_id(index)}]",
        "rule": _compact_text(rule, 240),
        "input_refs": input_refs or [],
        "output": _compact_text(output, 240),
        "confidence": max(0.0, min(1.0, float(confidence))),
    }


def _constraint(
    index: int,
    text: Any,
    *,
    kind: str,
    critical: bool = True,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": _constraint_id(index),
        "anchor": f"[{_constraint_id(index)}]",
        "type": str(kind or "general"),
        "text": _compact_text(text, 220),
        "critical": bool(critical),
        "metadata": metadata or {},
    }


def _cause(
    index: int,
    *,
    source: Any,
    relation: Any,
    target: Any,
    evidence_refs: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": _causal_id(index),
        "anchor": f"[{_causal_id(index)}]",
        "source": _compact_text(source, 120),
        "relation": _compact_text(relation, 80),
        "target": _compact_text(target, 180),
        "evidence_refs": evidence_refs or [],
    }


def _base_constraints(query: str, *, extra: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    constraints = [
        _constraint(0, "Usar somente fatos presentes no SIR.", kind="no_external_facts"),
        _constraint(1, "Responder em PT-BR.", kind="language"),
        _constraint(2, "Manter tom direto, sem preambulo e sem expor raciocinio interno.", kind="style"),
    ]
    line_count = _extract_requested_line_count(query)
    if line_count:
        constraints.append(
            _constraint(
                len(constraints),
                f"Responder em exatamente {line_count} linha(s).",
                kind="line_count",
                metadata={"expected_lines": line_count},
            )
        )
    for item in extra or []:
        if isinstance(item, dict):
            constraints.append(
                _constraint(
                    len(constraints),
                    item.get("text") or item.get("constraint") or item,
                    kind=item.get("type") or item.get("kind") or "general",
                    critical=bool(item.get("critical", True)),
                    metadata=item.get("metadata") if isinstance(item.get("metadata"), dict) else {},
                )
            )
    return constraints


def _extract_requested_line_count(query: str) -> int | None:
    text = _ascii_fold(query)
    words = {"uma": 1, "um": 1, "duas": 2, "dois": 2, "tres": 3, "three": 3, "two": 2, "one": 1}
    match = re.search(r"\b(\d{1,2}|uma|um|duas|dois|tres|one|two|three)\s+(?:linha|linhas|line|lines)\b", text)
    if not match:
        return None
    raw = match.group(1)
    count = int(raw) if raw.isdigit() else words.get(raw)
    return max(1, min(12, int(count))) if count else None


def _context_segments(raw_context: str, *, limit: int = 8) -> list[str]:
    text = str(raw_context or "").replace("\r\n", "\n")
    lines: list[str] = []
    for part in re.split(r"\n{1,}|\s{2,}", text):
        item = part.strip(" \t-*•")
        if not item:
            continue
        folded = _ascii_fold(item)
        if "conhecimento encontrado" in folded or folded.startswith("fontes:"):
            continue
        if len(item) < 3:
            continue
        lines.append(_compact_text(item, 420))
    if not lines and text.strip():
        lines = [_compact_text(text, 420)]
    dedup: list[str] = []
    seen: set[str] = set()
    for line in lines:
        key = _ascii_fold(line)
        if key in seen:
            continue
        seen.add(key)
        dedup.append(line)
        if len(dedup) >= limit:
            break
    return dedup


def validate_sir(sir: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(sir, dict):
        raise SIRValidationError("SIR must be a JSON object")
    missing = [field for field in REQUIRED_SIR_FIELDS if field not in sir]
    if missing:
        raise SIRValidationError(f"SIR missing required field(s): {', '.join(missing)}")
    for field in ("facts", "rules_applied", "constraints", "causal_graph_excerpt"):
        if not isinstance(sir.get(field), list):
            raise SIRValidationError(f"SIR field '{field}' must be a list")
    if not isinstance(sir.get("verification_status"), dict):
        raise SIRValidationError("SIR field 'verification_status' must be an object")
    for idx, fact in enumerate(sir.get("facts") or []):
        if not isinstance(fact, dict) or not fact.get("id") or not isinstance(fact.get("text"), str):
            raise SIRValidationError(f"SIR fact at index {idx} is invalid")
    for idx, rule in enumerate(sir.get("rules_applied") or []):
        if not isinstance(rule, dict) or not rule.get("id") or not isinstance(rule.get("rule"), str):
            raise SIRValidationError(f"SIR rule at index {idx} is invalid")
    for idx, constraint in enumerate(sir.get("constraints") or []):
        if not isinstance(constraint, dict) or not constraint.get("id") or not isinstance(constraint.get("text"), str):
            raise SIRValidationError(f"SIR constraint at index {idx} is invalid")
    sir.setdefault("schema_version", SIR_SCHEMA_VERSION)
    return sir


def build_sir_from_raw_context(
    query: str,
    raw_context: str,
    *,
    source: str = "own_reasoning",
    extra_constraints: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    facts: list[dict[str, Any]] = []
    for idx, segment in enumerate(_context_segments(raw_context)):
        facts.append(_fact(idx, segment, source=source, critical=idx < 2))

    if not facts:
        facts.append(
            _fact(
                0,
                "Nao ha fato estruturado suficiente recuperado para responder sem inventar.",
                source=source,
                critical=True,
                metadata={"unresolved": True},
            )
        )

    rules = [
        _rule(
            0,
            "O motor local recupera contexto e o LLM apenas verbaliza esse contexto.",
            input_refs=[f["id"] for f in facts],
            output="Resposta deve se limitar aos fatos ancorados.",
            confidence=0.92,
        )
    ]
    causes = [
        _cause(
            0,
            source=source,
            relation="supports_answer",
            target=facts[0]["id"],
            evidence_refs=[facts[0]["id"]],
        )
    ]
    sir = {
        "schema_version": SIR_SCHEMA_VERSION,
        "created_at": int(time.time()),
        "query": _compact_text(query, 280),
        "facts": facts,
        "rules_applied": rules,
        "constraints": _base_constraints(query, extra=extra_constraints),
        "causal_graph_excerpt": causes,
        "verification_status": {
            "status": "pending_llm_synthesis",
            "schema_valid": True,
            "critical_fact_ids": [f["id"] for f in facts if f.get("critical")],
            "checks": ["schema_validated", "anchors_assigned", "context_compressed"],
            "confidence": 0.72 if facts and not facts[0].get("metadata", {}).get("unresolved") else 0.35,
        },
    }
    return validate_sir(sir)


def build_sir_from_local_result(query: str, local_result: dict[str, Any]) -> dict[str, Any]:
    method = str((local_result or {}).get("method") or "local")
    result = str((local_result or {}).get("result") or "").strip()
    if not result:
        result = "O motor local nao resolveu a consulta."
    facts = [_fact(0, f"Resultado local via {method}: {result}", source=f"local_reasoning_engine.{method}", critical=True)]
    rules = [
        _rule(
            0,
            f"Resolver localmente por {method} antes de qualquer LLM.",
            input_refs=["FACT_1"],
            output=result,
            confidence=1.0 if (local_result or {}).get("resolved") else 0.4,
        )
    ]
    sir = {
        "schema_version": SIR_SCHEMA_VERSION,
        "created_at": int(time.time()),
        "query": _compact_text(query, 280),
        "facts": facts,
        "rules_applied": rules,
        "constraints": _base_constraints(query),
        "causal_graph_excerpt": [
            _cause(0, source=f"local_reasoning_engine.{method}", relation="produced", target="FACT_1", evidence_refs=["FACT_1"])
        ],
        "verification_status": {
            "status": "local_resolved",
            "schema_valid": True,
            "critical_fact_ids": ["FACT_1"],
            "checks": ["schema_validated", "local_resolution"],
            "confidence": 1.0 if (local_result or {}).get("resolved") else 0.4,
        },
    }
    return validate_sir(sir)


def build_sir_from_autobiographical_route(query: str, route: dict[str, Any]) -> dict[str, Any]:
    ctx = route.get("context") if isinstance(route, dict) and isinstance(route.get("context"), dict) else {}
    identity = ctx.get("identity_block") if isinstance(ctx.get("identity_block"), dict) else {}
    confidence = route.get("confidence") if isinstance(route.get("confidence"), dict) else {}
    facts: list[dict[str, Any]] = []

    facts.append(
        _fact(
            len(facts),
            f"Identidade registrada: nome={identity.get('name') or 'UltronPro'}; papel={identity.get('role') or 'nao especificado'}; missao={identity.get('mission') or 'nao especificada'}.",
            source="autobiographical_router.identity_block",
            critical=True,
        )
    )
    if identity.get("origin") or identity.get("creator") or identity.get("creator_name"):
        facts.append(
            _fact(
                len(facts),
                f"Origem/autoria registrada: origem={identity.get('origin') or 'nao especificada'}; criador={identity.get('creator_name') or identity.get('creator') or 'nao especificado'}.",
                source="autobiographical_router.identity_block",
                critical=True,
            )
        )
    if identity.get("foundational_context"):
        facts.append(
            _fact(
                len(facts),
                f"Contexto fundacional: {identity.get('foundational_context')}",
                source="autobiographical_router.identity_block",
                critical=False,
            )
        )

    for record in (ctx.get("origin_records") or [])[:3]:
        if not isinstance(record, dict):
            continue
        facts.append(
            _fact(
                len(facts),
                f"Registro de origem: ts={record.get('ts')}; tipo={record.get('kind')}; texto={record.get('text')}.",
                source="autobiographical_router.origin_records",
                critical=route.get("category") == "creation",
            )
        )

    bio = ctx.get("biographic_digest") if isinstance(ctx.get("biographic_digest"), dict) else {}
    for key in ("identity_thesis", "narrative", "trajectory_digest", "daily_digest"):
        value = bio.get(key) if key in bio else ctx.get(key)
        if value:
            facts.append(_fact(len(facts), f"{key}: {value}", source="autobiographical_router.digest", critical=False))

    for memory in (ctx.get("recent_memories") or [])[:4]:
        if isinstance(memory, dict) and memory.get("text"):
            facts.append(
                _fact(
                    len(facts),
                    f"Memoria autobiografica: {memory.get('text')}",
                    source="autobiographical_router.recent_memories",
                    critical=False,
                )
            )

    if not facts:
        facts.append(
            _fact(
                0,
                "Nao ha memoria autobiografica estruturada suficiente para esta pergunta.",
                source="autobiographical_router",
                critical=True,
            )
        )

    extra_constraints = [
        {
            "type": "autobiographical_scope",
            "text": "Responder somente a partir dos registros autobiograficos estruturados.",
        },
        {
            "type": "first_person",
            "text": "Pode usar primeira pessoa, mas sem inventar episodios ou origem externa.",
        },
    ]
    rules = [
        _rule(
            0,
            "Perguntas autobiograficas usam self_model, memorias e digest antes do LLM.",
            input_refs=[f["id"] for f in facts[:6]],
            output="Resposta autobiografica ancorada.",
            confidence=float(confidence.get("confidence_score") or 0.55),
        )
    ]
    if confidence.get("uncertainty_statement"):
        rules.append(
            _rule(
                1,
                "Quando a cobertura for baixa, declarar incerteza autobiografica em vez de alucinar.",
                input_refs=[f["id"] for f in facts],
                output=confidence.get("uncertainty_statement"),
                confidence=float(confidence.get("confidence_score") or 0.55),
            )
        )

    kept_facts = facts[:10]
    sir = {
        "schema_version": SIR_SCHEMA_VERSION,
        "created_at": int(time.time()),
        "query": _compact_text(query, 280),
        "facts": kept_facts,
        "rules_applied": rules,
        "constraints": _base_constraints(query, extra=extra_constraints),
        "causal_graph_excerpt": [
            _cause(0, source="self_model", relation="grounds", target="autobiographical_answer", evidence_refs=[facts[0]["id"]])
        ],
        "verification_status": {
            "status": "pending_llm_synthesis",
            "schema_valid": True,
            "critical_fact_ids": [f["id"] for f in kept_facts if f.get("critical")],
            "checks": ["schema_validated", "autobiographical_context_anchored"],
            "confidence": float(confidence.get("confidence_score") or 0.55),
            "coverage": confidence.get("coverage", ctx.get("coverage")),
        },
    }
    return validate_sir(sir)


def build_sir_from_transfer_prior(query: str, prior: dict[str, Any]) -> dict[str, Any]:
    facts = [
        _fact(
            0,
            f"Prior autoisomorfico: tipo={prior.get('type')}; score={prior.get('score')}; origem={prior.get('origin')}.",
            source="autoisomorphic_mapper",
            critical=True,
        )
    ]
    if prior.get("causal_claim"):
        facts.append(_fact(1, f"Claim causal transferido: {prior.get('causal_claim')}", source="autoisomorphic_mapper", critical=True))
    policy_text = prior.get("policy") or prior.get("policy_summary") or prior.get("transferred_policy") or prior.get("policy_hypothesis")
    if policy_text:
        facts.append(_fact(len(facts), f"Politica transferida: {policy_text}", source="autoisomorphic_mapper", critical=False))
    rules = [
        _rule(
            0,
            "Prior autoisomorfico degradado e sempre hipotetico ate validacao ativa.",
            input_refs=[f["id"] for f in facts],
            output="Apresentar como hipotese operacional, nao como fato final.",
            confidence=float(prior.get("score") or 0.5),
        )
    ]
    sir = {
        "schema_version": SIR_SCHEMA_VERSION,
        "created_at": int(time.time()),
        "query": _compact_text(query, 280),
        "facts": facts,
        "rules_applied": rules,
        "constraints": _base_constraints(
            query,
            extra=[{"type": "hypothesis_only", "text": "Nao promover prior autoisomorfico a conclusao sem validacao."}],
        ),
        "causal_graph_excerpt": [
            _cause(
                0,
                source=prior.get("source_domain") or prior.get("domain_source") or "source_domain",
                relation="possible_isomorphism_to",
                target=prior.get("target_domain") or "target_domain",
                evidence_refs=[f["id"] for f in facts],
            )
        ],
        "verification_status": {
            "status": "transfer_prior_requires_validation",
            "schema_valid": True,
            "critical_fact_ids": [f["id"] for f in facts if f.get("critical")],
            "checks": ["schema_validated", "hypothesis_anchored"],
            "confidence": float(prior.get("score") or 0.5),
        },
    }
    return validate_sir(sir)


def compression_payload(sir: dict[str, Any]) -> dict[str, Any]:
    validate_sir(sir)
    keep = {
        "schema_version": sir.get("schema_version") or SIR_SCHEMA_VERSION,
        "query": _compact_text(sir.get("query"), 280),
        "facts": [],
        "rules_applied": [],
        "constraints": [],
        "causal_graph_excerpt": [],
        "verification_status": sir.get("verification_status") or {},
    }
    for fact in sir.get("facts") or []:
        keep["facts"].append(
            {
                "id": fact.get("id"),
                "anchor": fact.get("anchor"),
                "text": _compact_text(fact.get("text"), 360),
                "source": fact.get("source"),
                "critical": bool(fact.get("critical")),
                "required_terms": list(fact.get("required_terms") or [])[:8],
                "numbers": list(fact.get("numbers") or [])[:8],
            }
        )
    for rule in sir.get("rules_applied") or []:
        keep["rules_applied"].append(
            {
                "id": rule.get("id"),
                "anchor": rule.get("anchor"),
                "rule": _compact_text(rule.get("rule"), 220),
                "input_refs": list(rule.get("input_refs") or [])[:8],
                "output": _compact_text(rule.get("output"), 220),
                "confidence": rule.get("confidence"),
            }
        )
    for constraint in sir.get("constraints") or []:
        keep["constraints"].append(
            {
                "id": constraint.get("id"),
                "anchor": constraint.get("anchor"),
                "type": constraint.get("type"),
                "text": _compact_text(constraint.get("text"), 180),
                "critical": bool(constraint.get("critical")),
                "metadata": constraint.get("metadata") or {},
            }
        )
    for cause in sir.get("causal_graph_excerpt") or []:
        if isinstance(cause, dict):
            keep["causal_graph_excerpt"].append(
                {
                    "id": cause.get("id"),
                    "anchor": cause.get("anchor"),
                    "source": _compact_text(cause.get("source"), 90),
                    "relation": _compact_text(cause.get("relation"), 80),
                    "target": _compact_text(cause.get("target"), 140),
                    "evidence_refs": list(cause.get("evidence_refs") or [])[:8],
                }
            )
    return keep


def constrained_decoder_metadata() -> dict[str, Any]:
    backend = "json_mode_schema"
    available = []
    try:
        import outlines  # noqa: F401

        backend = "outlines"
        available.append("outlines")
    except Exception:
        pass
    try:
        import guidance  # noqa: F401

        if backend == "json_mode_schema":
            backend = "guidance"
        available.append("guidance")
    except Exception:
        pass
    return {
        "backend": backend,
        "available_backends": available,
        "fallback": "provider_json_mode_with_schema_validation",
        "schema_name": "sir_response_v1",
        "schema": SIR_RESPONSE_SCHEMA,
    }


def build_llm_payload(sir: dict[str, Any], *, feedback: dict[str, Any] | None = None) -> str:
    payload = {
        "context": compression_payload(sir),
        "decoder": constrained_decoder_metadata(),
        "response_schema": SIR_RESPONSE_SCHEMA,
    }
    if feedback:
        payload["verification_feedback"] = feedback
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _parse_json_object(raw: Any) -> dict[str, Any] | None:
    text = str(raw or "").strip()
    if not text:
        return None
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"\s*```$", "", text).strip()
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except Exception:
        pass
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        try:
            obj, _ = decoder.raw_decode(text[match.start() :])
            if isinstance(obj, dict):
                return obj
        except Exception:
            continue
    return None


def validate_model_response(obj: dict[str, Any] | None) -> dict[str, Any]:
    issues: list[str] = []
    if not isinstance(obj, dict):
        return {"ok": False, "issues": ["invalid_json_or_not_object"]}
    if not isinstance(obj.get("answer"), str) or not obj.get("answer", "").strip():
        issues.append("missing_answer")
    for field in ("used_fact_ids", "used_rule_ids", "satisfied_constraints"):
        if not isinstance(obj.get(field), list) or not all(isinstance(x, str) for x in obj.get(field) or []):
            issues.append(f"invalid_{field}")
    if not isinstance(obj.get("verification_notes"), str):
        issues.append("invalid_verification_notes")
    return {"ok": not issues, "issues": issues}


def _fact_covered(answer: str, fact: dict[str, Any]) -> bool:
    answer_folded = _ascii_fold(answer)
    fact_text = str(fact.get("text") or "")
    nums = list(fact.get("numbers") or _numbers(fact_text))
    if nums and not all(str(n).replace(",", ".").rstrip("%") in answer_folded.replace(",", ".") for n in nums[:3]):
        return False
    terms = [t for t in (fact.get("required_terms") or sorted(_tokens(fact_text))) if len(str(t)) >= 3]
    if not terms:
        return bool(nums)
    overlap = sum(1 for t in terms if str(t).lower() in answer_folded)
    if len(terms) <= 2:
        return overlap >= 1
    return overlap >= 2 or (overlap / max(1, len(terms))) >= 0.34


def _contradiction_for_fact(answer: str, fact_text: str) -> str | None:
    a = _ascii_fold(answer)
    f = _ascii_fold(fact_text)
    if "ativo" in f and re.search(r"\bnao\b.{0,32}\bativo\b", a):
        return "answer_negates_active_fact"
    if "operacional" in f and re.search(r"\bnao\b.{0,32}\boperacional\b", a):
        return "answer_negates_operational_fact"
    if "nao ha" in f and re.search(r"\b(ha|existe|tenho)\b.{0,36}\b(fato|evidencia|registro)\b", a):
        return "answer_claims_evidence_absent_from_sir"
    return None


def _allowed_claim_tokens(sir: dict[str, Any]) -> set[str]:
    allowed = set(_tokens(sir.get("query") or ""))
    for fact in sir.get("facts") or []:
        allowed |= _tokens(fact.get("text") or "")
    for cause in sir.get("causal_graph_excerpt") or []:
        if isinstance(cause, dict):
            allowed |= _tokens(json.dumps(cause, ensure_ascii=False, default=str))
    return allowed


def _constraint_violations(answer: str, sir: dict[str, Any]) -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    answer_tokens = _tokens(answer)
    allowed_tokens = _allowed_claim_tokens(sir)
    answer_numbers = _numbers(answer)
    allowed_numbers = _numbers(json.dumps(sir, ensure_ascii=False, default=str))

    for constraint in sir.get("constraints") or []:
        kind = str(constraint.get("type") or "")
        cid = str(constraint.get("id") or "")
        if kind == "no_external_facts":
            prohibited = sorted((answer_tokens & _PROHIBITED_EXTERNAL_HINTS) - allowed_tokens)
            new_numbers = sorted(answer_numbers - allowed_numbers)
            if prohibited or new_numbers:
                violations.append({"constraint_id": cid, "reason": "external_fact_like_claim", "tokens": prohibited, "numbers": new_numbers})
        elif kind == "line_count":
            expected = (constraint.get("metadata") or {}).get("expected_lines")
            if expected:
                lines = [line for line in str(answer or "").splitlines() if line.strip()]
                if len(lines) != int(expected):
                    violations.append({"constraint_id": cid, "reason": "line_count_mismatch", "expected": int(expected), "actual": len(lines)})
        elif kind == "style":
            if re.search(r"\b(como modelo|sou um modelo de linguagem|as an ai)\b", _ascii_fold(answer)):
                violations.append({"constraint_id": cid, "reason": "exposes_model_persona"})
        elif kind == "hypothesis_only":
            if "hipot" not in _ascii_fold(answer) and "valid" not in _ascii_fold(answer):
                violations.append({"constraint_id": cid, "reason": "missing_hypothesis_qualification"})
    return violations


def verify_answer_against_sir(
    answer: str,
    sir: dict[str, Any],
    *,
    model_response: dict[str, Any] | None = None,
) -> dict[str, Any]:
    validate_sir(sir)
    text = str(answer or "").strip()
    issues: list[dict[str, Any]] = []
    if not text:
        issues.append({"type": "empty_answer", "reason": "answer_is_empty"})

    fact_ids = {str(f.get("id")) for f in sir.get("facts") or [] if isinstance(f, dict)}
    rule_ids = {str(r.get("id")) for r in sir.get("rules_applied") or [] if isinstance(r, dict)}
    constraint_ids = {str(c.get("id")) for c in sir.get("constraints") or [] if isinstance(c, dict)}

    if model_response:
        for used in model_response.get("used_fact_ids") or []:
            if used not in fact_ids:
                issues.append({"type": "invented_anchor", "field": "used_fact_ids", "id": used})
        for used in model_response.get("used_rule_ids") or []:
            if used not in rule_ids:
                issues.append({"type": "invented_anchor", "field": "used_rule_ids", "id": used})
        for used in model_response.get("satisfied_constraints") or []:
            if used not in constraint_ids:
                issues.append({"type": "invented_anchor", "field": "satisfied_constraints", "id": used})

    omitted: list[str] = []
    contradictions: list[dict[str, Any]] = []
    for fact in sir.get("facts") or []:
        if not isinstance(fact, dict):
            continue
        if fact.get("critical") and not _fact_covered(text, fact):
            omitted.append(str(fact.get("id")))
        contradiction = _contradiction_for_fact(text, str(fact.get("text") or ""))
        if contradiction:
            contradictions.append({"fact_id": fact.get("id"), "reason": contradiction})

    if omitted:
        issues.append({"type": "critical_fact_omission", "fact_ids": omitted})
    if contradictions:
        issues.append({"type": "contradiction", "items": contradictions})

    violations = _constraint_violations(text, sir)
    if violations:
        issues.append({"type": "constraint_violation", "items": violations})

    return {
        "ok": not issues,
        "issues": issues,
        "omitted_fact_ids": omitted,
        "contradictions": contradictions,
        "constraint_violations": violations,
    }


def deterministic_answer_from_sir(sir: dict[str, Any], *, fallback_text: str | None = None) -> str:
    validate_sir(sir)
    facts = [f for f in sir.get("facts") or [] if isinstance(f, dict)]
    critical = [f for f in facts if f.get("critical")] or facts[:2]
    if critical:
        parts = [str(f.get("text") or "").strip() for f in critical if str(f.get("text") or "").strip()]
        answer = " ".join(parts[:3]).strip()
    else:
        answer = ""
    if not answer and fallback_text:
        answer = _compact_text(fallback_text, 600)
    if not answer:
        answer = "Nao ha evidencia estruturada suficiente para responder sem inventar."
    if facts and (facts[0].get("metadata") or {}).get("unresolved") and "inventar" not in _ascii_fold(answer):
        answer += " Nao vou adicionar fatos externos."
    expected_lines = None
    for c in sir.get("constraints") or []:
        if c.get("type") == "line_count":
            expected_lines = (c.get("metadata") or {}).get("expected_lines")
            break
    if expected_lines:
        answer = _fit_line_count(answer, int(expected_lines))
    return answer.strip()


def _fit_line_count(text: str, count: int) -> str:
    count = max(1, min(12, int(count or 1)))
    compact = re.sub(r"\s+", " ", str(text or "").strip())
    if count == 1:
        return compact
    words = compact.split()
    if not words:
        return "\n".join([""] * count)
    step = max(1, len(words) // count)
    lines: list[str] = []
    start = 0
    for idx in range(count):
        if idx == count - 1:
            lines.append(" ".join(words[start:]).strip())
            break
        lines.append(" ".join(words[start : start + step]).strip())
        start += step
    return "\n".join(line for line in lines if line)


def synthesize_answer_with_sir(
    *,
    query: str,
    sir: dict[str, Any],
    complete_fn: Callable[..., str],
    fallback_text: str | None = None,
    max_attempts: int = 2,
    max_tokens: int = 700,
) -> dict[str, Any]:
    validate_sir(sir)
    feedback: dict[str, Any] | None = None
    attempts: list[dict[str, Any]] = []
    last_verification: dict[str, Any] | None = None

    for attempt in range(max(1, int(max_attempts or 1))):
        prompt = build_llm_payload(sir, feedback=feedback)
        raw = complete_fn(
            prompt,
            system=SIR_SYSTEM_PROMPT,
            json_mode=True,
            inject_persona=False,
            max_tokens=max_tokens,
        )
        parsed = _parse_json_object(raw)
        model_validation = validate_model_response(parsed)
        answer = str((parsed or {}).get("answer") or "").strip()
        verification = verify_answer_against_sir(answer, sir, model_response=parsed or {})
        last_verification = verification
        attempts.append(
            {
                "attempt": attempt + 1,
                "model_validation": model_validation,
                "verification": verification,
                "raw_excerpt": str(raw or "")[:500],
            }
        )
        if model_validation.get("ok") and verification.get("ok"):
            return {
                "ok": True,
                "answer": answer,
                "strategy": "sir_constrained_synthesis",
                "sir": compression_payload(sir),
                "verification": verification,
                "attempts": attempts,
            }
        feedback = {
            "previous_attempt": attempt + 1,
            "model_validation_issues": model_validation.get("issues") or [],
            "verification_issues": verification.get("issues") or [],
            "repair": {
                "must_cover_fact_ids": verification.get("omitted_fact_ids") or [],
                "must_satisfy_constraint_ids": [item.get("constraint_id") for item in verification.get("constraint_violations") or [] if item.get("constraint_id")],
                "do_not_add_external_facts": True,
            },
        }

    return {
        "ok": True,
        "answer": deterministic_answer_from_sir(sir, fallback_text=fallback_text),
        "strategy": "sir_deterministic_fallback",
        "sir": compression_payload(sir),
        "verification": last_verification or {"ok": False, "issues": [{"type": "no_llm_attempt"}]},
        "attempts": attempts,
    }
