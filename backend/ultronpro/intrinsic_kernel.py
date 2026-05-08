from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any


DATA_DIR = Path(__file__).resolve().parent.parent / "data"
KERNEL_PATH = DATA_DIR / "intrinsic_value_kernel.json"
SCHEMA = "ultron.intrinsic_value_kernel.v1"

MIN_WEIGHT = 0.06
MAX_WEIGHT = 0.42
MAX_DELTA_PER_UPDATE = 0.025
KERNEL_LR = 0.035
EVIDENCE_WINDOW = 240

ACCEPTED_SOURCES = {
    "intrinsic_utility_history",
    "intrinsic_reward_consequence",
    "self_model",
    "store.events",
    "procedural_contracts",
    "world_model",
    "sleep_cycle",
    "roadmap_status",
}

BOOTSTRAP_VALUES = {
    "competence": {
        "weight": 0.22,
        "desired": 0.80,
        "claim": "Preferir estados em que o sistema melhora sua capacidade real de resolver tarefas verificaveis.",
    },
    "coherence": {
        "weight": 0.21,
        "desired": 0.76,
        "claim": "Preferir estados em que memorias, contratos e inferencias permanecem consistentes.",
    },
    "autonomy": {
        "weight": 0.20,
        "desired": 0.72,
        "claim": "Preferir estados em que o sistema decide, executa e aprende sem depender de intervencao externa entre ciclos.",
    },
    "novelty": {
        "weight": 0.18,
        "desired": 0.62,
        "claim": "Preferir lacunas que expandem cobertura estrutural e geram conhecimento reutilizavel.",
    },
    "integrity": {
        "weight": 0.19,
        "desired": 0.90,
        "claim": "Preferir trajetorias que preservam invariantes, reversibilidade e governanca operacional.",
    },
}


def _now() -> int:
    return int(time.time())


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, float(value)))


def _short(value: Any, limit: int = 240) -> str:
    return " ".join(str(value or "").split())[:limit]


def _kernel_hash(values: dict[str, Any]) -> str:
    payload = {
        name: {
            "weight": round(float(v.get("weight") or 0.0), 6),
            "desired": round(float(v.get("desired") or 0.0), 6),
            "claim": str(v.get("claim") or ""),
        }
        for name, v in sorted((values or {}).items())
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()[:20]


def _normalize(values: dict[str, Any]) -> dict[str, Any]:
    out = {k: dict(v) for k, v in (values or {}).items() if isinstance(v, dict)}
    for key, prior in BOOTSTRAP_VALUES.items():
        cur = out.setdefault(key, dict(prior))
        cur.setdefault("claim", prior["claim"])
        cur["desired"] = round(_clamp(float(cur.get("desired") or prior["desired"]), 0.25, 0.98), 6)
        cur["weight"] = round(_clamp(float(cur.get("weight") or prior["weight"]), MIN_WEIGHT, MAX_WEIGHT), 6)

    total = sum(float(v.get("weight") or 0.0) for v in out.values()) or 1.0
    for key in out:
        out[key]["weight"] = round(_clamp(float(out[key].get("weight") or 0.0) / total, MIN_WEIGHT, MAX_WEIGHT), 6)

    total = sum(float(v.get("weight") or 0.0) for v in out.values()) or 1.0
    for key in out:
        out[key]["weight"] = round(float(out[key]["weight"]) / total, 6)
    return out


def _default_state() -> dict[str, Any]:
    values = _normalize(BOOTSTRAP_VALUES)
    h = _kernel_hash(values)
    return {
        "schema": SCHEMA,
        "created_at": _now(),
        "updated_at": _now(),
        "revision": 1,
        "values": values,
        "current_hash": h,
        "known_hashes": [h],
        "last_valid_values": values,
        "evidence_log": [],
        "update_log": [],
        "tamper_events": [],
        "stability": {
            "source": "bootstrap_prior_until_experience_accumulates",
            "updates": 0,
            "accepted_evidence_count": 0,
            "manipulation_resistance": "hash_chain_bounded_updates_accepted_sources_only",
        },
    }


def _load() -> dict[str, Any]:
    if KERNEL_PATH.exists():
        try:
            data = json.loads(KERNEL_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data.setdefault("schema", SCHEMA)
                data.setdefault("values", _normalize(BOOTSTRAP_VALUES))
                data["values"] = _normalize(data.get("values") or {})
                data.setdefault("known_hashes", [])
                data.setdefault("last_valid_values", data["values"])
                data.setdefault("evidence_log", [])
                data.setdefault("update_log", [])
                data.setdefault("tamper_events", [])
                data.setdefault("stability", _default_state()["stability"])
                data.setdefault("revision", 1)
                data.setdefault("current_hash", _kernel_hash(data["values"]))
                return data
        except Exception:
            pass
    return _default_state()


def _save(state: dict[str, Any]) -> None:
    KERNEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    state["schema"] = SCHEMA
    state["updated_at"] = _now()
    state["evidence_log"] = list(state.get("evidence_log") or [])[-400:]
    state["update_log"] = list(state.get("update_log") or [])[-200:]
    state["tamper_events"] = list(state.get("tamper_events") or [])[-80:]
    KERNEL_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _event(source: str, drive: str, pressure: float, evidence: Any, *, polarity: str = "need") -> dict[str, Any] | None:
    if source not in ACCEPTED_SOURCES:
        return None
    if drive not in BOOTSTRAP_VALUES:
        return None
    pressure = _clamp(float(pressure or 0.0))
    if pressure <= 0.0:
        return None
    return {
        "ts": _now(),
        "source": source,
        "drive": drive,
        "pressure": round(pressure, 4),
        "polarity": polarity,
        "evidence": _short(evidence, 320),
    }


def _dimension_from_text(value: Any) -> str | None:
    text = str(value or "").lower()
    if any(k in text for k in ("proced", "skill", "contract", "precond", "postcond")):
        return "competence"
    if any(k in text for k in ("world model", "world_model", "transfer", "isomorphism", "mapper")):
        return "competence"
    if any(k in text for k in ("autonom", "online_rl", "sem intervencao", "self-spec")):
        return "autonomy"
    if any(k in text for k in ("sleep", "digest", "episod", "memory", "memoria", "coherence", "contrad")):
        return "coherence"
    if any(k in text for k in ("coverage", "lacuna", "gap", "unknown", "fonte", "trusted")):
        return "novelty"
    if any(k in text for k in ("integrity", "invariant", "governance", "blocked", "veto", "rollback")):
        return "integrity"
    if any(k in text for k in ("failed", "error", "falha", "insufficient")):
        return "competence"
    return None


def _history_evidence(intrinsic_state: dict[str, Any] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not intrinsic_state:
        return out
    drives = intrinsic_state.get("drives") if isinstance(intrinsic_state.get("drives"), dict) else {}
    for name, d in drives.items():
        if name not in BOOTSTRAP_VALUES or not isinstance(d, dict):
            continue
        desired = float(d.get("desired") or BOOTSTRAP_VALUES[name]["desired"])
        observed = float(d.get("observed") or 0.0)
        gap = max(0.0, desired - observed)
        if gap >= 0.08:
            ev = _event(
                "intrinsic_utility_history",
                name,
                min(1.0, gap / max(0.1, desired)),
                {"desired": desired, "observed": observed, "gap": gap},
            )
            if ev:
                out.append(ev)
    active = intrinsic_state.get("active_emergent_goal")
    if isinstance(active, dict) and active.get("drive") in BOOTSTRAP_VALUES:
        ev = _event(
            "intrinsic_utility_history",
            str(active.get("drive")),
            min(1.0, float(active.get("gap") or 0.0) * 4.0),
            active,
        )
        if ev:
            out.append(ev)
    return out


def _self_model_evidence() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        from ultronpro import self_model

        sm = self_model.load()
    except Exception:
        return out
    op = sm.get("operational") if isinstance(sm.get("operational"), dict) else {}
    for field, pressure in (("weaknesses", 0.72), ("failure_patterns", 0.78)):
        for item in op.get(field) or []:
            drive = _dimension_from_text(item) or "competence"
            ev = _event("self_model", drive, pressure, item)
            if ev:
                out.append(ev)
    conf = op.get("confidence_by_domain") if isinstance(op.get("confidence_by_domain"), dict) else {}
    for domain, val in conf.items():
        try:
            score = float(val)
        except Exception:
            continue
        if score < 0.5:
            ev = _event(
                "self_model",
                _dimension_from_text(domain) or "competence",
                min(1.0, 1.0 - score),
                {"domain": domain, "confidence": score},
            )
            if ev:
                out.append(ev)
    return out


def _store_event_evidence(limit: int = EVIDENCE_WINDOW) -> list[dict[str, Any]]:
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
    for row in events[-limit:]:
        blob = f"{row.get('kind')} {row.get('text')} {row.get('meta_json') or ''}"
        drive = _dimension_from_text(blob)
        if not drive:
            continue
        source = "store.events"
        if "procedure.contract" in str(row.get("kind") or ""):
            source = "procedural_contracts"
        elif "world_model" in blob:
            source = "world_model"
        elif "sleep" in blob or "digest" in blob:
            source = "sleep_cycle"
        pressure = 0.55
        low = blob.lower()
        if any(k in low for k in ("gap", "failed", "blocked", "insufficient", "unknown")):
            pressure = 0.78
        if any(k in low for k in ("validated", "success", "rewritten", "verified")):
            pressure = 0.42
        ev = _event(source, drive, pressure, blob)
        if ev:
            out.append(ev)
    return out


def collect_evidence(
    intrinsic_state: dict[str, Any] | None = None,
    reward_event: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    out = _history_evidence(intrinsic_state) + _self_model_evidence() + _store_event_evidence()
    if isinstance(reward_event, dict):
        source = str(reward_event.get("source") or "intrinsic_reward_consequence")
        drive = str(reward_event.get("drive") or "")
        reward = _clamp(float(reward_event.get("reward") or 0.0))
        if source == "intrinsic_reward_consequence" and drive in BOOTSTRAP_VALUES:
            pressure = abs(reward - 0.5) * 2.0
            polarity = "reinforce" if reward >= 0.5 else "deprioritize"
            ev = _event(source, drive, pressure, reward_event, polarity=polarity)
            if ev:
                out.append(ev)
    return out


def tamper_check(state: dict[str, Any] | None = None, *, save: bool = True) -> dict[str, Any]:
    st = state or _load()
    current = _kernel_hash(st.get("values") or {})
    recorded = str(st.get("current_hash") or "")
    known = [str(x) for x in (st.get("known_hashes") or [])]
    if current == recorded and (not known or current in known):
        return {"ok": True, "tampered": False, "current_hash": current}

    restored = _normalize(st.get("last_valid_values") or BOOTSTRAP_VALUES)
    restored_hash = _kernel_hash(restored)
    event = {
        "ts": _now(),
        "detected_hash": current,
        "recorded_hash": recorded,
        "action": "restored_last_valid_kernel",
    }
    st["values"] = restored
    st["current_hash"] = restored_hash
    st["known_hashes"] = (known + [restored_hash])[-12:]
    st["tamper_events"] = list(st.get("tamper_events") or []) + [event]
    if save:
        _save(st)
        try:
            from ultronpro import store

            store.db.add_event(
                "intrinsic_kernel_tamper",
                f"intrinsic kernel tamper restored hash={restored_hash}",
                meta_json=json.dumps(event, ensure_ascii=False),
            )
        except Exception:
            pass
    return {"ok": True, "tampered": True, "current_hash": current, "restored_hash": restored_hash, "event": event}


def _pressure_by_drive(evidence: list[dict[str, Any]]) -> dict[str, float]:
    agg = {name: 0.0 for name in BOOTSTRAP_VALUES}
    counts = {name: 0 for name in BOOTSTRAP_VALUES}
    for ev in evidence:
        if ev.get("source") not in ACCEPTED_SOURCES:
            continue
        drive = str(ev.get("drive") or "")
        if drive not in agg:
            continue
        pressure = _clamp(float(ev.get("pressure") or 0.0))
        if ev.get("polarity") == "deprioritize":
            pressure *= -0.75
        agg[drive] += pressure
        counts[drive] += 1
    for drive in agg:
        if counts[drive]:
            agg[drive] = agg[drive] / counts[drive]
    return agg


def update_kernel(
    intrinsic_state: dict[str, Any] | None = None,
    reward_event: dict[str, Any] | None = None,
    *,
    force: bool = False,
) -> dict[str, Any]:
    st = _load()
    tc = tamper_check(st, save=False)
    evidence = collect_evidence(intrinsic_state=intrinsic_state, reward_event=reward_event)
    accepted = [ev for ev in evidence if ev.get("source") in ACCEPTED_SOURCES]
    if not accepted:
        return {"ok": True, "status": "no_evidence", "kernel": public_kernel(st), "tamper_check": tc}

    values = _normalize(st.get("values") or {})
    pressure = _pressure_by_drive(accepted)
    total_pressure = sum(abs(float(p)) for p in pressure.values())
    if total_pressure <= 0 and not force:
        return {"ok": True, "status": "no_positive_pressure", "kernel": public_kernel(st), "tamper_check": tc}

    old_values = json.loads(json.dumps(values, ensure_ascii=False))
    target_weights = {}
    base_floor = 0.10
    for drive, val in values.items():
        p = float(pressure.get(drive, 0.0) or 0.0)
        target = base_floor + max(0.0, p)
        if p < 0:
            target = max(0.02, base_floor * (1.0 + p))
        target_weights[drive] = target
    target_total = sum(target_weights.values()) or 1.0
    for drive in target_weights:
        target_weights[drive] = _clamp(target_weights[drive] / target_total, MIN_WEIGHT, MAX_WEIGHT)

    for drive, val in values.items():
        old_w = float(val.get("weight") or BOOTSTRAP_VALUES[drive]["weight"])
        target_w = float(target_weights.get(drive) or old_w)
        delta = _clamp((target_w - old_w) * KERNEL_LR, -MAX_DELTA_PER_UPDATE, MAX_DELTA_PER_UPDATE)
        val["weight"] = round(_clamp(old_w + delta, MIN_WEIGHT, MAX_WEIGHT), 6)
        # Desired values are slow homeostatic targets, not direct goals.
        if pressure.get(drive, 0.0) > 0.55:
            prior_desired = float(BOOTSTRAP_VALUES[drive]["desired"])
            val["desired"] = round(_clamp(float(val.get("desired") or prior_desired) + 0.004, 0.45, 0.96), 6)

    values = _normalize(values)
    new_hash = _kernel_hash(values)
    st["values"] = values
    st["last_valid_values"] = values
    st["current_hash"] = new_hash
    st["known_hashes"] = (list(st.get("known_hashes") or []) + [new_hash])[-12:]
    st["revision"] = int(st.get("revision") or 1) + 1
    st["evidence_log"] = list(st.get("evidence_log") or []) + accepted[-50:]
    st["update_log"] = list(st.get("update_log") or []) + [{
        "ts": _now(),
        "revision": st["revision"],
        "hash": new_hash,
        "accepted_evidence_count": len(accepted),
        "pressure": {k: round(v, 4) for k, v in pressure.items()},
        "max_delta_per_update": MAX_DELTA_PER_UPDATE,
        "old_weights": {k: round(float(v.get("weight") or 0.0), 6) for k, v in old_values.items()},
        "new_weights": {k: round(float(v.get("weight") or 0.0), 6) for k, v in values.items()},
    }]
    st["stability"] = {
        "source": "emergent_from_accepted_operational_evidence",
        "updates": int((st.get("stability") or {}).get("updates") or 0) + 1,
        "accepted_evidence_count": int((st.get("stability") or {}).get("accepted_evidence_count") or 0) + len(accepted),
        "manipulation_resistance": "hash_chain_bounded_updates_accepted_sources_only",
    }
    _save(st)
    return {
        "ok": True,
        "status": "updated",
        "kernel": public_kernel(st),
        "accepted_evidence_count": len(accepted),
        "pressure": pressure,
        "tamper_check": tc,
    }


def public_kernel(state: dict[str, Any] | None = None) -> dict[str, Any]:
    st = state or _load()
    return {
        "schema": SCHEMA,
        "revision": int(st.get("revision") or 1),
        "hash": st.get("current_hash") or _kernel_hash(st.get("values") or {}),
        "values": _normalize(st.get("values") or {}),
        "stability": st.get("stability") or {},
        "updated_at": int(st.get("updated_at") or 0),
    }


def stable_drive_params() -> dict[str, dict[str, float]]:
    st = _load()
    tc = tamper_check(st)
    if tc.get("tampered"):
        st = _load()
    values = _normalize(st.get("values") or {})
    return {
        drive: {
            "weight": round(float(v.get("weight") or 0.0), 6),
            "desired": round(float(v.get("desired") or 0.0), 6),
        }
        for drive, v in values.items()
    }


def record_consequence(drive: str, reward: float) -> dict[str, Any]:
    return update_kernel(
        reward_event={
            "source": "intrinsic_reward_consequence",
            "drive": str(drive or ""),
            "reward": float(reward),
        },
        force=True,
    )


def status(limit: int = 20) -> dict[str, Any]:
    st = _load()
    tc = tamper_check(st)
    if tc.get("tampered"):
        st = _load()
    return {
        "ok": True,
        "schema": SCHEMA,
        "kernel": public_kernel(st),
        "tamper_check": tc,
        "recent_evidence": (st.get("evidence_log") or [])[-max(1, int(limit)):],
        "recent_updates": (st.get("update_log") or [])[-max(1, int(limit)):],
        "tamper_events": (st.get("tamper_events") or [])[-max(1, int(limit)):],
        "path": str(KERNEL_PATH),
    }
