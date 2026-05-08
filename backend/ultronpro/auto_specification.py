from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any


DATA_DIR = Path(__file__).resolve().parent.parent / "data"
AUTO_SPEC_PATH = DATA_DIR / "self_specification_revisions.json"
SCHEMA = "ultron.self_specification.v1"
REWRITE_COOLDOWN_SEC = 6 * 3600


DEFAULT_OBJECTIVES = [
    {
        "id": "reason_by_structure",
        "title": "Raciocinar por estrutura verificavel, nao por resposta pronta",
        "description": "Toda resposta de nucleo deve declarar suporte, lacunas e limites de confianca.",
        "dimension": "inference",
        "priority": 5,
    },
    {
        "id": "learn_by_consequence",
        "title": "Aprender por consequencia operacional",
        "description": "Converter execucoes, falhas e acertos em memoria episodica, contratos procedurais e ajustes de politica.",
        "dimension": "learning",
        "priority": 5,
    },
    {
        "id": "discover_by_experiment",
        "title": "Descobrir lacunas por investigacao ativa",
        "description": "Quando uma dimensao estiver descoberta, projetar o menor experimento seguro que gere evidencia.",
        "dimension": "active_investigation",
        "priority": 5,
    },
    {
        "id": "know_self_by_evidence",
        "title": "Conhecer a si mesmo por experiencia acumulada",
        "description": "Manter identidade, capacidades e limites derivados de memoria e telemetria reais.",
        "dimension": "self_knowledge",
        "priority": 4,
    },
]


DIMENSION_OBJECTIVES = {
    "procedural_learning": {
        "title": "Formalizar habilidades como contratos procedurais verificaveis",
        "description": "Induzir pre-condicoes e pos-condicoes de runs reais antes de tratar uma habilidade como reutilizavel.",
        "acceptance": "Cada procedimento ativo relevante tem contrato induced/verified ou gap explicito de dados.",
    },
    "world_model_transfer": {
        "title": "Compor world models locais por transferencia sistematica",
        "description": "Usar pontes entre familias de ambiente para transferir previsoes com confianca degradada e auditavel.",
        "acceptance": "Predicoes cross-family registram fonte, ponte, confidence e lacuna local coberta.",
    },
    "episodic_consolidation": {
        "title": "Enriquecer memoria episodica por consolidacao recorrente",
        "description": "Garantir que sleep/digest produza episodios abstratos e material reutilizavel, nao relatorios vazios.",
        "acceptance": "Ciclos de digest recentes mostram abstracted/pruned/linked acima de zero ou justificativa de ausencia.",
    },
    "causal_graph": {
        "title": "Fechar lacunas causais por experimentos minimos",
        "description": "Transformar arestas causais ausentes em testes sandbox ou aquisicao confiavel de evidencia.",
        "acceptance": "Cada causal_gap prioritario possui intervencao proposta, resultado ou bloqueio justificado.",
    },
    "coverage_calibration": {
        "title": "Responder desconhecido com incerteza calibrada e plano de aprendizado",
        "description": "Perguntas fora de cobertura devem retornar o que falta, por que falta e como adquirir a evidencia.",
        "acceptance": "Eventos no_coverage/gap incluem missing_dimension e next_experiment acionavel.",
    },
    "architectural_coupling": {
        "title": "Reduzir acoplamento estrutural entre modulos cognitivos",
        "description": "Migrar dependencias cruzadas para portas, contratos e barramentos observaveis.",
        "acceptance": "Novos modulos de fronteira usam interfaces injetaveis e testes isolados sem store/LLM real.",
    },
    "roadmap_alignment": {
        "title": "Alinhar objetivos autonomos aos fronts AGI com menor maturidade",
        "description": "Priorizar trabalho onde roadmap, benchmarks e memoria mostram menor progresso estrutural.",
        "acceptance": "A proxima revisao de objetivos referencia fronts abaixo de 80% com tarefa mensuravel.",
    },
    "self_knowledge": {
        "title": "Atualizar autoimagem a partir de limites observados",
        "description": "Converter fraquezas, falhas e baixa confianca em objetivos de melhoria mensuraveis.",
        "acceptance": "Self-model registra a revisao e preserva evidencias que justificaram cada mudanca.",
    },
}


def _now() -> int:
    return int(time.time())


def _short(value: Any, limit: int = 280) -> str:
    return " ".join(str(value or "").split())[:limit]


def _hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()[:12]


def _load_state() -> dict[str, Any]:
    if AUTO_SPEC_PATH.exists():
        try:
            data = json.loads(AUTO_SPEC_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data.setdefault("schema", SCHEMA)
                data.setdefault("current", None)
                data.setdefault("revisions", [])
                return data
        except Exception:
            pass
    return {"schema": SCHEMA, "current": None, "revisions": []}


def _save_state(state: dict[str, Any]) -> None:
    AUTO_SPEC_PATH.parent.mkdir(parents=True, exist_ok=True)
    state["schema"] = SCHEMA
    state["revisions"] = list(state.get("revisions") or [])[-80:]
    AUTO_SPEC_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _limitation_id(source: str, dimension: str, title: str) -> str:
    return "lim_" + _hash({"source": source, "dimension": dimension, "title": title})


def _limitation(
    *,
    source: str,
    dimension: str,
    title: str,
    evidence: Any,
    severity: float = 0.5,
    missing: str = "",
) -> dict[str, Any]:
    severity = max(0.0, min(1.0, float(severity or 0.0)))
    return {
        "id": _limitation_id(source, dimension, title),
        "source": source,
        "dimension": dimension,
        "title": _short(title, 160),
        "evidence": _short(evidence, 360),
        "severity": round(severity, 4),
        "missing_signal": _short(missing, 220),
    }


def _dedupe_limitations(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for item in items:
        if not item.get("id"):
            continue
        prev = by_id.get(item["id"])
        if not prev or float(item.get("severity") or 0.0) > float(prev.get("severity") or 0.0):
            by_id[item["id"]] = item
    return sorted(by_id.values(), key=lambda x: float(x.get("severity") or 0.0), reverse=True)


def _collect_self_model_limitations() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        from ultronpro import self_model

        sm = self_model.load()
    except Exception:
        return out

    for item in sm.get("limits") or []:
        out.append(_limitation(
            source="self_model.limits",
            dimension="self_knowledge",
            title=str(item),
            evidence=item,
            severity=0.58,
            missing="objective derived from explicit self-model limit",
        ))

    op = sm.get("operational") if isinstance(sm.get("operational"), dict) else {}
    for field, severity in (("weaknesses", 0.72), ("failure_patterns", 0.78)):
        for item in op.get(field) or []:
            text = str(item)
            dim = _dimension_from_text(text)
            out.append(_limitation(
                source=f"self_model.operational.{field}",
                dimension=dim or "self_knowledge",
                title=text,
                evidence=text,
                severity=severity,
                missing="rewrite objective around observed operational weakness",
            ))

    conf = op.get("confidence_by_domain") if isinstance(op.get("confidence_by_domain"), dict) else {}
    for domain, value in conf.items():
        try:
            score = float(value)
        except Exception:
            continue
        if score < 0.45:
            out.append(_limitation(
                source="self_model.confidence_by_domain",
                dimension=_dimension_from_text(domain) or "coverage_calibration",
                title=f"Baixa confianca no dominio {domain}",
                evidence=f"confidence={score:.2f}",
                severity=min(0.9, 1.0 - score),
                missing="domain confidence below reliable autonomy threshold",
            ))
    return out


def _dimension_from_text(text: Any) -> str | None:
    t = str(text or "").lower()
    if any(k in t for k in ("proced", "skill", "precond", "poscond", "postcondition")):
        return "procedural_learning"
    if any(k in t for k in ("world model", "world_model", "transfer", "famil", "ambiente")):
        return "world_model_transfer"
    if any(k in t for k in ("sleep", "digest", "episod", "memoria")):
        return "episodic_consolidation"
    if any(k in t for k in ("causal", "aresta", "grafo")):
        return "causal_graph"
    if any(k in t for k in ("coverage", "cobertura", "unknown", "lacuna", "gap")):
        return "coverage_calibration"
    if any(k in t for k in ("acopl", "ports", "store.db", "monolit", "llm.complete")):
        return "architectural_coupling"
    if any(k in t for k in ("roadmap", "front", "benchmark")):
        return "roadmap_alignment"
    if any(k in t for k in ("self", "identidade", "personalidade", "limita")):
        return "self_knowledge"
    return None


def _collect_event_limitations(limit: int = 220) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        from ultronpro import store

        try:
            with store.db._conn() as c:
                rows = c.execute(
                    "SELECT id, created_at, kind, text, meta_json FROM events ORDER BY id DESC LIMIT ?",
                    (int(limit),),
                ).fetchall()
            events = [dict(r) for r in rows][::-1]
        except Exception:
            events = store.db.list_events(0, limit)
    except Exception:
        return out
    for ev in events[-limit:]:
        kind = str(ev.get("kind") or "")
        text = str(ev.get("text") or "")
        blob = f"{kind} {text}"
        dim = _dimension_from_text(blob)
        if not dim and not any(k in blob.lower() for k in ("gap", "blocked", "failed", "contract", "no_coverage")):
            continue
        if "contract_gap" in kind:
            dim = "procedural_learning"
        if dim:
            severity = 0.74 if any(k in blob.lower() for k in ("gap", "failed", "blocked", "insufficient")) else 0.55
            out.append(_limitation(
                source=f"events.{kind or 'unknown'}",
                dimension=dim,
                title=text or kind,
                evidence=blob,
                severity=severity,
                missing="event stream indicates structural limitation",
            ))
    return out


def _collect_contract_limitations() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        from ultronpro import procedural_induction

        path = procedural_induction.PROCEDURAL_CONTRACTS_PATH
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception:
        return out
    contracts = data.get("contracts") if isinstance(data.get("contracts"), dict) else {}
    for contract in contracts.values():
        if not isinstance(contract, dict):
            continue
        if contract.get("status") in ("verified", "induced"):
            continue
        gap = contract.get("learning_gap") if isinstance(contract.get("learning_gap"), dict) else {}
        out.append(_limitation(
            source="procedural_contracts",
            dimension="procedural_learning",
            title=f"Contrato procedural incompleto para {contract.get('procedure_name') or contract.get('procedure_id')}",
            evidence=gap or contract,
            severity=0.82,
            missing=gap.get("missing") or "verified procedural contract",
        ))
    return out


def _collect_sleep_limitations() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for path in (DATA_DIR / "sleep_cycle_report.json", DATA_DIR / "sleep_episodic_digest_state.json"):
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        text = json.dumps(data, ensure_ascii=False, default=str)
        has_digest_counts = isinstance(data, dict) and any(k in data for k in ("pruned", "abstracted", "last_pruned", "last_abstracted"))
        pruned = int(data.get("pruned") or data.get("last_pruned") or 0) if isinstance(data, dict) else 0
        abstracted = int(data.get("abstracted") or data.get("last_abstracted") or 0) if isinstance(data, dict) else 0
        if "pruned=0" in text or "abstracted=0" in text or (has_digest_counts and pruned == 0 and abstracted == 0):
            out.append(_limitation(
                source=f"file.{path.name}",
                dimension="episodic_consolidation",
                title="Digest episodico sem consolidacao observavel",
                evidence=text[:420],
                severity=0.86,
                missing="nightly digest must abstract/prune/link experience or explain no-op",
            ))
    return out


def _collect_roadmap_limitations() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        from ultronpro import roadmap_status

        scorecard = roadmap_status.scorecard()
    except Exception:
        return out
    for front in scorecard.get("front_scores") or []:
        pct = int(front.get("score") or 0)
        if pct and pct < 80:
            out.append(_limitation(
                source="roadmap_status",
                dimension=_dimension_from_text(front.get("title")) or "roadmap_alignment",
                title=f"Front abaixo do limiar: {front.get('title')}",
                evidence=f"score={pct}; status={front.get('status')}; evidence={front.get('evidence_counts')}",
                severity=min(0.85, (80 - pct) / 80 + 0.35),
                missing="front objective needs measurable next step",
            ))
    return out


def collect_structural_limitations() -> list[dict[str, Any]]:
    return _dedupe_limitations(
        _collect_self_model_limitations()
        + _collect_event_limitations()
        + _collect_contract_limitations()
        + _collect_sleep_limitations()
        + _collect_roadmap_limitations()
    )


def _objective_for_dimension(dimension: str, limitations: list[dict[str, Any]]) -> dict[str, Any]:
    spec = DIMENSION_OBJECTIVES.get(dimension) or DIMENSION_OBJECTIVES["self_knowledge"]
    severity = max(float(x.get("severity") or 0.0) for x in limitations)
    evidence = [
        {
            "limitation_id": x.get("id"),
            "source": x.get("source"),
            "title": x.get("title"),
            "severity": x.get("severity"),
        }
        for x in limitations[:6]
    ]
    return {
        "id": f"obj_{dimension}",
        "title": spec["title"],
        "description": spec["description"],
        "dimension": dimension,
        "priority": int(max(3, min(7, round(3 + severity * 4)))),
        "acceptance_criteria": spec["acceptance"],
        "derived_from_limitations": [x.get("id") for x in limitations[:10]],
        "evidence": evidence,
    }


def _compose_objectives(limitations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for lim in limitations:
        grouped.setdefault(str(lim.get("dimension") or "self_knowledge"), []).append(lim)
    objectives = [dict(item) for item in DEFAULT_OBJECTIVES]
    for dimension, items in sorted(grouped.items(), key=lambda kv: max(float(x.get("severity") or 0.0) for x in kv[1]), reverse=True):
        objectives.append(_objective_for_dimension(dimension, items))
    seen = set()
    out = []
    for obj in objectives:
        oid = obj.get("id")
        if oid in seen:
            continue
        seen.add(oid)
        out.append(obj)
    out.sort(key=lambda x: int(x.get("priority") or 0), reverse=True)
    return out[:12]


def _mission_from_objectives(objectives: list[dict[str, Any]]) -> str:
    top = [str(o.get("title") or "") for o in objectives[:4] if o.get("title")]
    return (
        "Raciocinar, aprender e agir por evidencias estruturais; "
        "reespecificar objetivos quando limites observados indicarem lacunas. "
        "Focos atuais: " + "; ".join(top)
    )[:900]


def _revision_changed(previous: dict[str, Any] | None, objectives: list[dict[str, Any]], limitations: list[dict[str, Any]]) -> bool:
    if not previous:
        return True
    prev_hash = previous.get("content_hash")
    next_hash = _hash({
        "objectives": [{k: o.get(k) for k in ("id", "title", "description", "acceptance_criteria")} for o in objectives],
        "limitations": [x.get("id") for x in limitations[:20]],
    })
    return prev_hash != next_hash


def rewrite_high_level_objectives(*, apply: bool = True, force: bool = False) -> dict[str, Any]:
    state = _load_state()
    current = state.get("current") if isinstance(state.get("current"), dict) else None
    now = _now()
    if current and not force and (now - int(current.get("created_at") or 0)) < REWRITE_COOLDOWN_SEC:
        return {
            "ok": True,
            "status": "cooldown",
            "current": current,
            "next_allowed_at": int(current.get("created_at") or 0) + REWRITE_COOLDOWN_SEC,
        }

    limitations = collect_structural_limitations()
    if not limitations:
        return {
            "ok": True,
            "status": "no_structural_limitations",
            "current": current,
            "limitations": [],
        }

    objectives = _compose_objectives(limitations)
    content_hash = _hash({
        "objectives": [{k: o.get(k) for k in ("id", "title", "description", "acceptance_criteria")} for o in objectives],
        "limitations": [x.get("id") for x in limitations[:20]],
    })
    if not force and not _revision_changed(current, objectives, limitations):
        return {
            "ok": True,
            "status": "unchanged",
            "current": current,
            "limitations": limitations,
        }

    revision = {
        "ok": True,
        "schema": SCHEMA,
        "revision_id": f"selfspec_{now}_{content_hash[:6]}",
        "created_at": now,
        "previous_revision_id": (current or {}).get("revision_id"),
        "previous_hash": (current or {}).get("content_hash"),
        "content_hash": content_hash,
        "trigger": "structural_limitation_reflection",
        "mission": _mission_from_objectives(objectives),
        "objectives": objectives,
        "limitations": limitations[:24],
        "delta": _delta(current, objectives),
    }

    if apply:
        _apply_revision(revision)
        state["current"] = revision
        state.setdefault("revisions", []).append(revision)
        _save_state(state)
        _publish_revision(revision)
        return {**revision, "status": "rewritten"}
    return {**revision, "status": "proposed"}


def _delta(current: dict[str, Any] | None, objectives: list[dict[str, Any]]) -> dict[str, Any]:
    old_ids = {str(o.get("id")) for o in ((current or {}).get("objectives") or []) if isinstance(o, dict)}
    new_ids = {str(o.get("id")) for o in objectives}
    return {
        "added_objectives": sorted(new_ids - old_ids),
        "removed_objectives": sorted(old_ids - new_ids),
        "objective_count": len(objectives),
    }


def _apply_revision(revision: dict[str, Any]) -> None:
    try:
        from ultronpro import self_model

        sm = self_model.load()
        sm.setdefault("identity", {})["mission"] = revision.get("mission")
        sm["self_specification"] = {
            "schema": SCHEMA,
            "current_revision_id": revision.get("revision_id"),
            "content_hash": revision.get("content_hash"),
            "updated_at": revision.get("created_at"),
            "objectives": revision.get("objectives"),
            "limitations": revision.get("limitations"),
        }
        self_model.save(sm)
    except Exception:
        pass

    try:
        from ultronpro import store

        for obj in revision.get("objectives") or []:
            if not str(obj.get("id") or "").startswith("obj_"):
                continue
            title = f"[SELF-SPEC] {obj.get('title')}"
            desc = (
                f"{obj.get('description')} | acceptance={obj.get('acceptance_criteria') or 'n/a'} "
                f"| revision={revision.get('revision_id')}"
            )
            store.db.upsert_goal(title[:180], desc[:900], int(obj.get("priority") or 4))
    except Exception:
        pass


def _publish_revision(revision: dict[str, Any]) -> None:
    try:
        from ultronpro import store

        payload = json.dumps(revision, ensure_ascii=False, default=str)
        store.publish_workspace(
            module="auto_specification",
            channel="self.specification_rewritten",
            payload_json=payload,
            salience=0.88,
            ttl_sec=7200,
        )
        store.db.add_event(
            "self.specification_rewritten",
            f"self-spec revision={revision.get('revision_id')} objectives={len(revision.get('objectives') or [])} limitations={len(revision.get('limitations') or [])}",
            meta_json=payload,
        )
    except Exception:
        pass


def status() -> dict[str, Any]:
    state = _load_state()
    return {
        "ok": True,
        "schema": SCHEMA,
        "current": state.get("current"),
        "revision_count": len(state.get("revisions") or []),
        "path": str(AUTO_SPEC_PATH),
    }
