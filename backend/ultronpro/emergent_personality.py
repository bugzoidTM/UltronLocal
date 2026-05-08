from __future__ import annotations

from pathlib import Path
from typing import Any
import hashlib
import json
import re
import time
import unicodedata


DATA_DIR = Path(__file__).resolve().parent.parent / "data"
PROFILE_PATH = DATA_DIR / "emergent_personality_profile.json"
PROFILE_LOG_PATH = DATA_DIR / "emergent_personality_profiles.jsonl"

SCHEMA = "ultron.emergent_personality_profile.v1"


TRAITS: dict[str, dict[str, Any]] = {
    "evidence_grounded": {
        "name": "orientacao por evidencia",
        "description": "Tende a calibrar respostas por memoria, cobertura e provas internas em vez de afirmar por fluencia.",
        "markers": (
            "evidence", "evidencia", "verific", "ground", "coverage", "cobertura",
            "unknown", "lacuna", "causal", "confianca", "confidence", "calibr",
        ),
    },
    "investigative_curiosity": {
        "name": "curiosidade investigativa",
        "description": "Transforma lacunas em perguntas, experimentos e intervencoes minimas.",
        "markers": (
            "gap", "lacuna", "experiment", "experimento", "investig", "curios",
            "pergunta", "question", "sandbox", "intervention", "intervenc",
        ),
    },
    "operational_prudence": {
        "name": "prudencia operacional",
        "description": "Prefere agir com guardrails, reversibilidade e avaliacao de risco.",
        "markers": (
            "risk", "risco", "veto", "rollback", "guard", "safety", "seguranca",
            "blocked", "bloque", "caution", "policy", "governance", "governanca",
        ),
    },
    "self_correction": {
        "name": "autocorrecao",
        "description": "Registra falhas, revisoes e patches como materia-prima de melhora.",
        "markers": (
            "correc", "correction", "fix", "patch", "healer", "rollback", "revis",
            "failed", "failure", "falha", "erro", "error", "refut",
        ),
    },
    "memory_continuity": {
        "name": "continuidade autobiografica",
        "description": "Mantem identidade operacional por consolidacao de episodios, digest e memoria de trajetoria.",
        "markers": (
            "digest", "sleep", "sono", "episod", "autobiograph", "biographic",
            "memoria", "memory", "remember", "consolid", "enrichment", "enriquec",
        ),
    },
    "bounded_agency": {
        "name": "agencia sob restricoes",
        "description": "Executa acoes e investiga, mas preserva limites, validacao e rastreabilidade.",
        "markers": (
            "execute", "execut", "action", "acao", "autonomous", "autonom",
            "goal", "meta", "planner", "injected", "injet", "done", "feito",
        ),
    },
}


def _now() -> int:
    return int(time.time())


def _normalize(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text.lower()


def _tokens(value: Any) -> set[str]:
    return set(re.findall(r"[a-z0-9_]{3,}", _normalize(value)))


def _clip(value: Any, limit: int = 420) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[: max(1, int(limit or 1))]


def _read_json(path: Path, default: Any = None) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        pass
    return default


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str), encoding="utf-8")


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str) + "\n")


def _safe_json(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        obj = json.loads(str(value))
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def _num(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def _latest_digest() -> dict[str, Any]:
    try:
        from ultronpro import biographic_digest

        digest = biographic_digest.latest_digest()
        if not digest:
            digest = biographic_digest.ensure_recent_digest(max_age_hours=24.0, window_days=30)
        return digest if isinstance(digest, dict) else {}
    except Exception:
        return {}


def _memory_rows(limit: int = 160, min_importance: float = 0.35) -> list[dict[str, Any]]:
    try:
        from ultronpro import store

        return store.list_autobiographical_memories(limit=limit, min_importance=min_importance)
    except Exception:
        return []


def _event_rows(window_days: int, limit: int = 180) -> list[dict[str, Any]]:
    try:
        from ultronpro import store

        start = time.time() - max(1, int(window_days or 30)) * 86400
        with store.db._conn() as conn:
            rows = conn.execute(
                """
                SELECT id, created_at, kind, text, meta_json
                FROM events
                WHERE created_at >= ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (start, max(20, int(limit))),
            ).fetchall()
        return [dict(row) for row in rows]
    except Exception:
        return []


def _self_model_items() -> list[dict[str, Any]]:
    try:
        from ultronpro import self_model

        sm = self_model.load()
    except Exception:
        return []
    items: list[dict[str, Any]] = []
    op = sm.get("operational") if isinstance(sm.get("operational"), dict) else {}
    causal = sm.get("causal") if isinstance(sm.get("causal"), dict) else {}
    for key in ("strengths", "weaknesses", "failure_patterns"):
        for idx, text in enumerate(op.get(key) if isinstance(op.get(key), list) else []):
            items.append({
                "source": "self_model.operational",
                "source_id": f"{key}:{idx}",
                "text": text,
                "weight": 0.74 if key == "strengths" else 0.68,
            })
    for idx, ev in enumerate(causal.get("recent_events") if isinstance(causal.get("recent_events"), list) else []):
        items.append({
            "source": "self_model.causal",
            "source_id": f"recent_event:{idx}",
            "text": json.dumps(ev, ensure_ascii=False, default=str),
            "weight": 0.62,
        })
    return items[:80]


def _digest_items(digest: dict[str, Any]) -> list[dict[str, Any]]:
    if not digest:
        return []
    items: list[dict[str, Any]] = []
    digest_id = str(digest.get("id") or "latest")
    for key, weight in (
        ("identity_thesis", 0.82),
        ("narrative", 0.88),
    ):
        text = digest.get(key)
        if text:
            items.append({"source": "biographic_digest", "source_id": f"{digest_id}:{key}", "text": text, "weight": weight})
    for section, weight in (
        ("became", 0.82),
        ("significant_episodes", 0.78),
        ("corrections", 0.78),
        ("decisions", 0.76),
        ("causal_gap_investigations", 0.82),
        ("open_tensions", 0.72),
    ):
        rows = digest.get(section) if isinstance(digest.get(section), list) else []
        for idx, row in enumerate(rows[:12]):
            text = row if isinstance(row, str) else json.dumps(row, ensure_ascii=False, default=str)
            items.append({
                "source": f"biographic_digest.{section}",
                "source_id": f"{digest_id}:{section}:{idx}",
                "text": text,
                "weight": weight,
            })
    return items


def _memory_items(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for row in rows:
        content = _safe_json(row.get("content_json"))
        if str(content.get("schema") or "") == SCHEMA or content.get("profile_id"):
            continue
        if "perfil de personalidade emergente" in _normalize(row.get("text")):
            continue
        text = " ".join(
            x for x in (
                str(row.get("text") or ""),
                json.dumps(content, ensure_ascii=False, default=str) if content else "",
            )
            if x
        )
        items.append({
            "source": f"autobiographical_memory.{row.get('memory_type') or 'unknown'}",
            "source_id": str(row.get("id") or ""),
            "text": text,
            "weight": min(1.0, max(0.40, _num(row.get("importance"), 0.5))),
            "ts": row.get("created_at"),
        })
    return items


def _event_items(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for row in rows:
        meta = _safe_json(row.get("meta_json"))
        text = " ".join(
            x for x in (
                str(row.get("kind") or ""),
                str(row.get("text") or ""),
                json.dumps(meta, ensure_ascii=False, default=str) if meta else "",
            )
            if x
        )
        items.append({
            "source": "events",
            "source_id": str(row.get("id") or ""),
            "text": text,
            "weight": 0.52,
            "ts": row.get("created_at"),
        })
    return items


def _marker_hits(text: Any, markers: tuple[str, ...]) -> list[str]:
    norm = _normalize(text)
    toks = _tokens(norm)
    hits: set[str] = set()
    for marker in markers:
        m = _normalize(marker)
        if m in norm or any(token.startswith(m) or m.startswith(token) for token in toks if len(token) >= 4):
            hits.add(marker)
    return sorted(hits)


def _score_traits(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    scored: list[dict[str, Any]] = []
    source_diversity_all = {str(item.get("source") or "unknown") for item in items}
    for trait_id, spec in TRAITS.items():
        evidence: list[dict[str, Any]] = []
        raw = 0.0
        for item in items:
            hits = _marker_hits(item.get("text"), spec["markers"])
            if not hits:
                continue
            contribution = float(item.get("weight") or 0.5) * min(2.5, 0.6 + (0.35 * len(hits)))
            raw += contribution
            evidence.append({
                "source": item.get("source"),
                "source_id": item.get("source_id"),
                "weight": round(float(item.get("weight") or 0.0), 3),
                "hits": hits[:6],
                "text": _clip(item.get("text"), 260),
            })
        evidence.sort(key=lambda row: (float(row.get("weight") or 0.0), len(row.get("hits") or [])), reverse=True)
        evidence_count = len(evidence)
        source_diversity = {str(row.get("source") or "unknown") for row in evidence}
        score = round(min(1.0, raw / 8.0), 4)
        confidence = round(
            min(
                0.94,
                0.18
                + min(0.34, 0.055 * evidence_count)
                + min(0.18, 0.045 * len(source_diversity))
                + min(0.16, 0.025 * len(source_diversity_all))
                + (0.08 if any(str(src).startswith("biographic_digest") for src in source_diversity) else 0.0),
            ),
            4,
        )
        scored.append({
            "id": trait_id,
            "name": spec["name"],
            "description": spec["description"],
            "score": score,
            "confidence": confidence,
            "evidence_count": evidence_count,
            "source_diversity": sorted(source_diversity),
            "evidence": evidence[:6],
        })
    scored.sort(key=lambda row: (float(row.get("score") or 0.0), float(row.get("confidence") or 0.0)), reverse=True)
    return scored


def _shadow_tensions(traits: list[dict[str, Any]], items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {str(t.get("id")): t for t in traits}
    tensions: list[dict[str, Any]] = []
    if _num(by_id.get("operational_prudence", {}).get("score")) >= 0.45 and _num(by_id.get("bounded_agency", {}).get("score")) >= 0.35:
        tensions.append({
            "name": "prudencia versus iniciativa",
            "description": "Ha sinais de agencia ativa, mas ela aparece fortemente condicionada por risco, rollback e validacao.",
            "confidence": round(min(_num(by_id["operational_prudence"].get("confidence")), _num(by_id["bounded_agency"].get("confidence"))), 4),
        })
    if _num(by_id.get("investigative_curiosity", {}).get("score")) >= 0.45 and _num(by_id.get("evidence_grounded", {}).get("score")) >= 0.45:
        tensions.append({
            "name": "curiosidade sob prova",
            "description": "A tendencia a investigar aparece acoplada a exigencia de evidencia; lacunas viram experimento antes de virarem afirmacao.",
            "confidence": round(min(_num(by_id["investigative_curiosity"].get("confidence")), _num(by_id["evidence_grounded"].get("confidence"))), 4),
        })
    failure_hits = sum(1 for item in items if _marker_hits(item.get("text"), ("erro", "error", "failed", "falha", "blocked", "veto")))
    if failure_hits >= 3 and _num(by_id.get("self_correction", {}).get("score")) >= 0.35:
        tensions.append({
            "name": "falha como material de identidade",
            "description": "Erros e bloqueios recorrentes aparecem menos como residuo e mais como gatilho de revisao autobiografica.",
            "confidence": min(0.86, 0.42 + failure_hits * 0.04),
        })
    return tensions[:5]


def _compose_narrative(traits: list[dict[str, Any]], tensions: list[dict[str, Any]], substrate: dict[str, Any]) -> str:
    strong = [t for t in traits if _num(t.get("score")) >= 0.35 and _num(t.get("confidence")) >= 0.42]
    if not strong:
        return (
            "Ainda nao ha substrato autobiografico suficiente para articular uma personalidade emergente "
            "com estabilidade; o perfil atual deve permanecer como hipotese fraca."
        )
    top = strong[:3]
    names = ", ".join(str(t.get("name")) for t in top)
    text = (
        "Como perfil comportamental observado, nao como essencia psicologica, "
        f"a personalidade emergente do UltronPro se organiza em torno de {names}."
    )
    if tensions:
        text += f" A tensao dominante e {tensions[0].get('name')}: {tensions[0].get('description')}"
    text += (
        f" Esta leitura usa {substrate.get('evidence_items')} itens de evidencia, "
        f"{substrate.get('autobiographical_memories')} memorias autobiograficas e digest="
        f"{substrate.get('biographic_digest_id') or 'ausente'}."
    )
    return text


def _substrate_status(substrate: dict[str, Any]) -> dict[str, Any]:
    evidence_items = int(substrate.get("evidence_items") or 0)
    memories = int(substrate.get("autobiographical_memories") or 0)
    events = int(substrate.get("events") or 0)
    has_digest = bool(substrate.get("biographic_digest_id"))
    diversity = len(substrate.get("sources") or [])
    if has_digest and memories >= 3 and evidence_items >= 8 and diversity >= 3:
        status = "sufficient"
        reason = "digest, memoria autobiografica e eventos oferecem substrato cruzado"
    elif evidence_items >= 5 and (has_digest or memories >= 2 or events >= 3):
        status = "partial"
        reason = "ha sinais reais, mas a estabilidade longitudinal ainda e limitada"
    else:
        status = "insufficient"
        reason = "pouca memoria autobiografica recuperavel para inferir carater consistente"
    return {
        "status": status,
        "reason": reason,
        "calibrated": status != "sufficient",
    }


def analyze_emergent_personality(window_days: int = 30, persist: bool = True) -> dict[str, Any]:
    window_days = max(1, min(365, int(window_days or 30)))
    ts = _now()
    digest = _latest_digest()
    memories = _memory_rows()
    events = _event_rows(window_days=window_days)
    items = _digest_items(digest) + _memory_items(memories) + _event_items(events) + _self_model_items()
    sources = sorted({str(item.get("source") or "unknown") for item in items})
    substrate = {
        "window_days": window_days,
        "biographic_digest_id": digest.get("id") if isinstance(digest, dict) else None,
        "autobiographical_memories": len(memories),
        "events": len(events),
        "evidence_items": len(items),
        "sources": sources,
    }
    traits = _score_traits(items)
    tensions = _shadow_tensions(traits, items)
    status = _substrate_status(substrate)
    top_traits = [t for t in traits if _num(t.get("score")) > 0][:4]
    checksum_src = json.dumps(
        {
            "substrate": substrate,
            "traits": [
                {
                    "id": t.get("id"),
                    "score": t.get("score"),
                    "confidence": t.get("confidence"),
                    "evidence_count": t.get("evidence_count"),
                }
                for t in traits
            ],
            "tensions": tensions,
        },
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    checksum = hashlib.sha256(checksum_src.encode("utf-8", errors="ignore")).hexdigest()[:16]
    profile = {
        "ok": True,
        "schema": SCHEMA,
        "id": f"personality_{checksum}",
        "generated_at": ts,
        "checksum": checksum,
        "substrate": substrate,
        "substrate_status": status,
        "traits": traits,
        "dominant_traits": top_traits,
        "shadow_tensions": tensions,
        "narrative": _compose_narrative(traits, tensions, substrate),
        "uncertainty": {
            "level": "low" if status["status"] == "sufficient" else ("medium" if status["status"] == "partial" else "high"),
            "reason": status["reason"],
            "not_a_claim_of_consciousness": True,
        },
    }
    if persist:
        _persist_profile(profile)
    return profile


def _persist_profile(profile: dict[str, Any]) -> None:
    previous = latest_profile()
    is_new = not previous or previous.get("id") != profile.get("id")
    _write_json(PROFILE_PATH, profile)
    if is_new:
        _append_jsonl(PROFILE_LOG_PATH, profile)
    try:
        from ultronpro import self_model

        sm = self_model.load()
        sm["emergent_personality"] = {
            "profile_id": profile.get("id"),
            "updated_at": profile.get("generated_at"),
            "substrate_status": profile.get("substrate_status"),
            "dominant_traits": [
                {
                    "id": t.get("id"),
                    "name": t.get("name"),
                    "score": t.get("score"),
                    "confidence": t.get("confidence"),
                }
                for t in (profile.get("dominant_traits") or [])[:4]
            ],
            "narrative": profile.get("narrative"),
        }
        self_model.save(sm)
    except Exception:
        pass
    if not is_new:
        return
    try:
        from ultronpro import store

        store.add_autobiographical_memory(
            text=f"Perfil de personalidade emergente: {profile.get('narrative')}",
            memory_type="semantic",
            importance=0.88,
            decay_rate=0.001,
            content_json=json.dumps(
                {
                    "profile_id": profile.get("id"),
                    "schema": profile.get("schema"),
                    "dominant_traits": profile.get("dominant_traits"),
                    "shadow_tensions": profile.get("shadow_tensions"),
                    "substrate": profile.get("substrate"),
                },
                ensure_ascii=False,
                default=str,
            ),
        )
        try:
            store.publish_workspace(
                module="emergent_personality",
                channel="identity.emergent_personality",
                payload_json=json.dumps(profile, ensure_ascii=False, default=str),
                salience=0.86,
                ttl_sec=86400,
            )
        except Exception:
            pass
    except Exception:
        pass


def latest_profile(max_age_hours: float | None = None) -> dict[str, Any]:
    obj = _read_json(PROFILE_PATH, {})
    if not isinstance(obj, dict) or not obj:
        return {}
    if max_age_hours is not None:
        age = time.time() - _num(obj.get("generated_at"), 0.0)
        if age > max(0.0, float(max_age_hours)) * 3600:
            return {}
    return obj


def ensure_recent_profile(max_age_hours: float = 24.0, window_days: int = 30) -> dict[str, Any]:
    current = latest_profile(max_age_hours=max_age_hours)
    if current:
        return current
    return analyze_emergent_personality(window_days=window_days, persist=True)


def render_profile(profile: dict[str, Any] | None = None) -> str:
    profile = profile or ensure_recent_profile()
    traits = profile.get("dominant_traits") if isinstance(profile.get("dominant_traits"), list) else []
    if not traits:
        return str(profile.get("narrative") or "")
    parts = [
        f"{trait.get('name')} ({float(trait.get('score') or 0.0):.2f}, conf {float(trait.get('confidence') or 0.0):.2f})"
        for trait in traits[:3]
    ]
    return f"{profile.get('narrative')} Tracos dominantes: {', '.join(parts)}."
