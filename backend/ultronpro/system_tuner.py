"""Camada ajustadora do sistema agêntico.

Consome os achados da camada avaliadora (trajectory_evaluator) e os converte
em ajustes concretos, sempre limitados, reversíveis e auditáveis:

- subagent/tool  -> overrides do catálogo de ações do online_rl_loop
                    (delta de prioridade, multiplicador de cooldown, desativação
                    temporária), com expiração automática;
- prompt         -> proposta de cognitive patch (segue shadow eval + gates);
- aux_code       -> proposta de cognitive patch que, se promovida, escala para
                    proposta real de self_modification pela ponte existente;
- memory         -> insight gravado na memória via ports;
- reversão       -> remove override que não melhorou a recompensa.

Nada aqui aplica código diretamente: mudanças comportamentais passam pelos
gates existentes; overrides expiram sozinhos. Determinístico, sem LLM.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from ultronpro import cognitive_patches
from ultronpro.core.ports import RuntimePorts, default_ports

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
OVERRIDES_PATH = DATA_DIR / "online_rl_action_overrides.json"
LEDGER_PATH = DATA_DIR / "system_tuner_ledger.jsonl"
STATE_PATH = DATA_DIR / "system_tuner_state.json"
SCHEMA = "ultron.system_tuner.v1"

# Limites duros: o tuner nunca pode desligar o sistema nem distorcer a seleção
# além de margens pequenas; tudo expira sozinho.
PRIORITY_DELTA_CLAMP = 0.15
COOLDOWN_MULT_MIN = 0.5
COOLDOWN_MULT_MAX = 3.0
OVERRIDE_TTL_SEC = 6 * 3600
FINDING_REAPPLY_TTL_SEC = 24 * 3600


def _now() -> int:
    return int(time.time())


def _read_json(path: Path, default: Any = None) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        pass
    return default


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _state() -> dict[str, Any]:
    state = _read_json(STATE_PATH, {})
    if not isinstance(state, dict):
        state = {}
    state.setdefault("schema", SCHEMA)
    state.setdefault("applied_findings", {})
    return state


def active_overrides(*, now: int | None = None) -> dict[str, dict[str, Any]]:
    """Overrides vigentes do catálogo de ações; expira e poda automaticamente."""
    now = int(now or _now())
    raw = _read_json(OVERRIDES_PATH, {})
    if not isinstance(raw, dict):
        return {}
    overrides = raw.get("overrides") if isinstance(raw.get("overrides"), dict) else {}
    alive: dict[str, dict[str, Any]] = {}
    for kind, item in overrides.items():
        if isinstance(item, dict) and int(item.get("expires_at") or 0) > now:
            alive[str(kind)] = dict(item)
    if len(alive) != len(overrides):
        _write_json(OVERRIDES_PATH, {"schema": SCHEMA, "overrides": alive, "updated_at": now})
    return alive


def _set_override(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    overrides = active_overrides()
    overrides[kind] = payload
    _write_json(OVERRIDES_PATH, {"schema": SCHEMA, "overrides": overrides, "updated_at": _now()})
    return payload


def _remove_override(kind: str) -> bool:
    overrides = active_overrides()
    existed = kind in overrides
    overrides.pop(kind, None)
    _write_json(OVERRIDES_PATH, {"schema": SCHEMA, "overrides": overrides, "updated_at": _now()})
    return existed


def _ledger_row(finding: dict[str, Any], action_taken: str, params: dict[str, Any], ok: bool) -> dict[str, Any]:
    row = {
        "schema": SCHEMA,
        "ts": _now(),
        "finding_id": finding.get("finding_id"),
        "detector": finding.get("detector"),
        "lever": finding.get("lever"),
        "target": finding.get("target"),
        "action_taken": action_taken,
        "params": params,
        "ok": bool(ok),
    }
    _append_jsonl(LEDGER_PATH, row)
    return row


def _apply_adjust_action(finding: dict[str, Any]) -> dict[str, Any]:
    rec = finding.get("recommendation") or {}
    kind = str(rec.get("kind") or finding.get("target") or "")
    if not kind:
        return {"ok": False, "error": "missing_kind"}
    delta = max(-PRIORITY_DELTA_CLAMP, min(PRIORITY_DELTA_CLAMP, float(rec.get("priority_delta") or 0.0)))
    mult = max(COOLDOWN_MULT_MIN, min(COOLDOWN_MULT_MAX, float(rec.get("cooldown_mult") or 1.0)))
    payload = {
        "priority_delta": round(delta, 4),
        "cooldown_mult": round(mult, 4),
        "reward_baseline": rec.get("reward_baseline"),
        "finding_id": finding.get("finding_id"),
        "reason": str(finding.get("label") or "")[:240],
        "applied_at": _now(),
        "expires_at": _now() + OVERRIDE_TTL_SEC,
    }
    _set_override(kind, payload)
    return {"ok": True, "kind": kind, "override": payload}


def _apply_revert_override(finding: dict[str, Any]) -> dict[str, Any]:
    rec = finding.get("recommendation") or {}
    kind = str(rec.get("kind") or finding.get("target") or "")
    existed = _remove_override(kind) if kind else False
    return {"ok": bool(kind), "kind": kind, "removed": existed}


def _apply_patch_proposal(finding: dict[str, Any], *, patch_kind: str) -> dict[str, Any]:
    rec = finding.get("recommendation") or {}
    patch = cognitive_patches.create_patch({
        "kind": patch_kind,
        "source": "system_tuner",
        "problem_pattern": str(rec.get("problem_pattern") or finding.get("label") or "")[:300],
        "hypothesis": str(finding.get("label") or "")[:600],
        "proposed_change": {
            "change_type": "trajectory_evaluation_adjustment",
            "lever": finding.get("lever"),
            "target": finding.get("target"),
            "directive": rec.get("directive"),
            "evidence": finding.get("evidence"),
            "acceptance": "shadow_eval deve melhorar a metrica alvo sem regressao antes da promocao",
        },
        "expected_gain": f"Resolver achado {finding.get('detector')} em {finding.get('target')}",
        "risk_level": "medium",
        "status": "proposed",
        "evidence_refs": [f"trajectory_finding:{finding.get('finding_id')}"],
        "tags": ["system_tuner", str(finding.get("detector") or "")[:60]],
        "notes": "Gerado deterministicamente pela camada avaliadora de trajetorias; sem LLM.",
    })
    return {"ok": bool(patch.get("id")), "patch_id": patch.get("id"), "patch_kind": patch_kind}


def _apply_memory_insight(finding: dict[str, Any], *, ports: RuntimePorts) -> dict[str, Any]:
    rec = finding.get("recommendation") or {}
    try:
        insight_id = ports.memory.add_insight(
            kind="trajectory_lesson",
            title=str(rec.get("title") or finding.get("label") or "")[:180],
            text=str(rec.get("text") or finding.get("label") or "")[:2000],
            priority=2 if float(finding.get("severity") or 0.0) >= 0.6 else 3,
            source_id=f"system_tuner:{finding.get('finding_id')}",
            meta={"finding": finding},
        )
        return {"ok": bool(insight_id), "insight_id": insight_id}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200]}


def apply_findings(
    findings: list[dict[str, Any]],
    *,
    max_adjustments: int = 5,
    ports: RuntimePorts | None = None,
) -> dict[str, Any]:
    ports = ports or default_ports()
    state = _state()
    applied_map = state.get("applied_findings") or {}
    now = _now()

    applied: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for finding in findings:
        if len(applied) >= max(1, int(max_adjustments)):
            skipped.append({"finding_id": finding.get("finding_id"), "reason": "max_adjustments_reached"})
            continue
        fid = str(finding.get("finding_id") or "")
        last_applied = int(applied_map.get(fid) or 0)
        rec_type = str((finding.get("recommendation") or {}).get("type") or "")
        # Reversões podem repetir; ajustes idempotentes respeitam o TTL.
        if rec_type != "revert_override" and last_applied and (now - last_applied) < FINDING_REAPPLY_TTL_SEC:
            skipped.append({"finding_id": fid, "reason": "recently_applied"})
            continue

        if rec_type == "adjust_action":
            outcome = _apply_adjust_action(finding)
            action_taken = "adjust_action"
        elif rec_type == "revert_override":
            outcome = _apply_revert_override(finding)
            action_taken = "revert_override"
        elif rec_type == "propose_aux_code_patch":
            outcome = _apply_patch_proposal(finding, patch_kind="heuristic_patch")
            action_taken = "propose_aux_code_patch"
        elif rec_type == "adjust_prompt_policy":
            outcome = _apply_patch_proposal(finding, patch_kind="confidence_patch")
            action_taken = "adjust_prompt_policy"
        elif rec_type == "record_memory_insight":
            outcome = _apply_memory_insight(finding, ports=ports)
            action_taken = "record_memory_insight"
        else:
            skipped.append({"finding_id": fid, "reason": f"unknown_recommendation:{rec_type[:40]}"})
            continue

        row = _ledger_row(finding, action_taken, (finding.get("recommendation") or {}) | {"outcome": outcome}, bool(outcome.get("ok")))
        applied.append({"finding_id": fid, "action_taken": action_taken, "outcome": outcome, "ledger_ts": row["ts"]})
        if outcome.get("ok"):
            applied_map[fid] = now

    state["applied_findings"] = {k: v for k, v in applied_map.items() if (now - int(v)) < FINDING_REAPPLY_TTL_SEC * 7}
    state["last_run_at"] = now
    state["last_applied_count"] = len(applied)
    _write_json(STATE_PATH, state)

    summary = {
        "ok": True,
        "schema": SCHEMA,
        "ts": now,
        "non_llm": True,
        "findings_received": len(findings),
        "applied": applied,
        "applied_count": len(applied),
        "skipped": skipped,
        "active_overrides": active_overrides(),
    }
    try:
        if applied:
            ports.events.add_event(
                "system_tuner.adjustments_applied",
                f"system tuner aplicou {len(applied)} ajustes a partir de achados de trajetoria",
                meta={"applied": applied, "skipped": skipped},
            )
            ports.workspace.publish(
                "system_tuner",
                "system_tuner.adjustments_applied",
                {"applied": applied, "active_overrides": summary["active_overrides"]},
                salience=0.76,
                ttl_sec=3600,
            )
    except Exception:
        pass
    return summary


def status() -> dict[str, Any]:
    rows = []
    try:
        if LEDGER_PATH.exists():
            for line in LEDGER_PATH.read_text(encoding="utf-8", errors="ignore").splitlines()[-20:]:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        pass
    return {
        "ok": True,
        "schema": SCHEMA,
        "active_overrides": active_overrides(),
        "recent_ledger": rows,
        "state": _state(),
    }


def run_selftest() -> dict[str, Any]:
    import tempfile

    global OVERRIDES_PATH, LEDGER_PATH, STATE_PATH
    old = (OVERRIDES_PATH, LEDGER_PATH, STATE_PATH)
    with tempfile.TemporaryDirectory(prefix="system-tuner-") as td:
        base = Path(td)
        OVERRIDES_PATH = base / "overrides.json"
        LEDGER_PATH = base / "ledger.jsonl"
        STATE_PATH = base / "state.json"
        try:
            finding = {
                "finding_id": "tf_selftest",
                "detector": "low_reward_action",
                "lever": "subagent",
                "target": "selftest_kind",
                "label": "selftest",
                "severity": 0.7,
                "evidence": {},
                "recommendation": {
                    "type": "adjust_action",
                    "kind": "selftest_kind",
                    "priority_delta": -0.5,  # deve ser limitado a -0.15
                    "cooldown_mult": 9.0,    # deve ser limitado a 3.0
                    "reward_baseline": 0.2,
                },
            }
            from ultronpro.core.ports import recording_ports
            ports, _, _, _ = recording_ports()
            summary = apply_findings([finding], ports=ports)
            override = active_overrides().get("selftest_kind") or {}
            clamped = override.get("priority_delta") == -PRIORITY_DELTA_CLAMP and override.get("cooldown_mult") == COOLDOWN_MULT_MAX
            return {
                "ok": bool(summary.get("applied_count") == 1 and clamped),
                "non_llm": True,
                "override": override,
            }
        finally:
            OVERRIDES_PATH, LEDGER_PATH, STATE_PATH = old
