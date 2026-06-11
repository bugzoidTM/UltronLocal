"""Camada avaliadora de trajetórias.

Varre os logs de execução dos loops agênticos (RL online, patch loop, aquisição
confiável, predições de ação) e o ledger do system_tuner, e produz achados
estruturados: cada achado nomeia um detector, uma severidade e a alavanca de
ajuste recomendada (prompt, tool, memory, subagent, aux_code). A camada
ajustadora (system_tuner) consome esses achados. Determinístico, sem LLM.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
RL_RUNS_PATH = DATA_DIR / "online_rl_runs.jsonl"
PATCH_RUNS_PATH = DATA_DIR / "cognitive_patch_loop_runs.jsonl"
ACQUISITION_RUNS_PATH = DATA_DIR / "trusted_acquisition_runs.jsonl"
PREDICTIONS_PATH = DATA_DIR / "action_predictions.jsonl"
TUNER_LEDGER_PATH = DATA_DIR / "system_tuner_ledger.jsonl"
STATE_PATH = DATA_DIR / "trajectory_evaluation_state.json"
EVAL_LOG_PATH = DATA_DIR / "trajectory_evaluations.jsonl"

FINDING_SCHEMA = "ultron.trajectory_finding.v1"
EVAL_SCHEMA = "ultron.trajectory_evaluation.v1"

DEFAULT_WINDOW = 80
LOW_REWARD_MIN_RUNS = 4
LOW_REWARD_THRESHOLD = 0.30
FAILURE_SIGNATURE_MIN = 3
PIPELINE_STALL_HOLDS = 5
SATURATION_MIN = 3
CHRONIC_SURPRISE_MIN = 3
INEFFECTIVE_MIN_RUNS_AFTER = 3


def _now() -> int:
    return int(time.time())


def _read_jsonl(path: Path, limit: int = DEFAULT_WINDOW) -> list[dict[str, Any]]:
    try:
        if not path.exists():
            return []
        rows: list[dict[str, Any]] = []
        lines = [ln for ln in path.read_text(encoding="utf-8", errors="ignore").splitlines() if ln.strip()]
        for line in lines[-max(1, int(limit)):]:
            try:
                item = json.loads(line)
            except Exception:
                continue
            if isinstance(item, dict):
                rows.append(item)
        return rows
    except Exception:
        return []


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _finding(
    *,
    detector: str,
    lever: str,
    target: str,
    label: str,
    severity: float,
    evidence: dict[str, Any],
    recommendation: dict[str, Any],
) -> dict[str, Any]:
    base = {
        "schema": FINDING_SCHEMA,
        "detector": detector,
        "lever": lever,
        "target": target,
        "label": label,
        "severity": round(max(0.0, min(1.0, float(severity))), 4),
        "evidence": evidence,
        "recommendation": recommendation,
    }
    raw = json.dumps({"detector": detector, "lever": lever, "target": target}, sort_keys=True)
    base["finding_id"] = f"tf_{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:12]}"
    return base


def _error_signature(error: Any) -> str:
    text = re.sub(r"\d+", "<n>", str(error or "")).strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text[:160]


def _rl_run_rows(window: int) -> list[dict[str, Any]]:
    rows = _read_jsonl(RL_RUNS_PATH, limit=window)
    out = []
    for row in rows:
        selection = row.get("selection") if isinstance(row.get("selection"), dict) else {}
        selected = selection.get("selected") if isinstance(selection.get("selected"), dict) else {}
        kind = str(selected.get("kind") or "")
        if not kind:
            continue
        reward = row.get("reward") if isinstance(row.get("reward"), dict) else {}
        result = row.get("action_result") if isinstance(row.get("action_result"), dict) else {}
        out.append({
            "ts": int(row.get("ts") or 0),
            "kind": kind,
            "reward": float(reward.get("reward") or 0.0),
            "error": result.get("error"),
            "ok": bool(result.get("ok")),
        })
    return out


def detect_low_reward_actions(rl_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_kind: dict[str, list[float]] = {}
    for row in rl_rows:
        by_kind.setdefault(row["kind"], []).append(row["reward"])
    findings = []
    for kind, rewards in sorted(by_kind.items()):
        if len(rewards) < LOW_REWARD_MIN_RUNS:
            continue
        mean = sum(rewards) / len(rewards)
        if mean >= LOW_REWARD_THRESHOLD:
            continue
        findings.append(_finding(
            detector="low_reward_action",
            lever="subagent",
            target=kind,
            label=f"acao {kind} com recompensa media baixa ({mean:.2f}) em {len(rewards)} execucoes",
            severity=min(1.0, (LOW_REWARD_THRESHOLD - mean) * 2.5 + 0.3),
            evidence={"kind": kind, "runs": len(rewards), "mean_reward": round(mean, 4)},
            recommendation={
                "type": "adjust_action",
                "kind": kind,
                "priority_delta": -0.10,
                "cooldown_mult": 2.0,
                "reward_baseline": round(mean, 4),
            },
        ))
    return findings


def detect_recurring_failures(rl_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    signatures: dict[str, dict[str, Any]] = {}
    for row in rl_rows:
        if not row.get("error"):
            continue
        sig = _error_signature(row["error"])
        if not sig:
            continue
        bucket = signatures.setdefault(sig, {"count": 0, "kinds": set(), "sample": str(row["error"])[:240]})
        bucket["count"] += 1
        bucket["kinds"].add(row["kind"])
    findings = []
    for sig, bucket in sorted(signatures.items()):
        if bucket["count"] < FAILURE_SIGNATURE_MIN:
            continue
        kinds = sorted(bucket["kinds"])
        findings.append(_finding(
            detector="recurring_failure_signature",
            lever="aux_code",
            target=sig[:80],
            label=f"falha recorrente ({bucket['count']}x) nas acoes {', '.join(kinds)}",
            severity=min(1.0, 0.4 + bucket["count"] * 0.1),
            evidence={"signature": sig, "count": bucket["count"], "kinds": kinds, "sample_error": bucket["sample"]},
            recommendation={
                "type": "propose_aux_code_patch",
                "problem_pattern": bucket["sample"],
                "kinds": kinds,
            },
        ))
    return findings


def detect_patch_pipeline_stall(window: int) -> list[dict[str, Any]]:
    rows = _read_jsonl(PATCH_RUNS_PATH, limit=window)
    holds = 0
    promotes = 0
    for row in rows:
        action = str(row.get("final_action") or "")
        if action == "hold":
            holds += 1
        elif action == "promote":
            promotes += 1
    if promotes > 0 or holds < PIPELINE_STALL_HOLDS:
        return []
    return [_finding(
        detector="patch_pipeline_stall",
        lever="subagent",
        target="cognitive_patch_loop",
        label=f"pipeline de patches estagnado: {holds} holds sem nenhuma promocao na janela",
        severity=min(1.0, 0.35 + holds * 0.05),
        evidence={"holds": holds, "promotes": promotes, "window": window},
        recommendation={
            "type": "adjust_action",
            "kind": "cognitive_patch_loop",
            "priority_delta": 0.10,
            "cooldown_mult": 0.5,
            "reward_baseline": None,
        },
    )]


def detect_acquisition_saturation(window: int) -> list[dict[str, Any]]:
    rows = _read_jsonl(ACQUISITION_RUNS_PATH, limit=window)
    saturated = 0
    gap_ids: set[str] = set()
    for row in rows:
        remaining = row.get("gaps_remaining") if isinstance(row.get("gaps_remaining"), list) else []
        if any("saturated" in str(item) for item in remaining):
            saturated += 1
            decision = row.get("decision") if isinstance(row.get("decision"), dict) else {}
            need = decision.get("need") if isinstance(decision.get("need"), dict) else {}
            if need.get("id"):
                gap_ids.add(str(need["id"]))
    if saturated < SATURATION_MIN:
        return []
    return [_finding(
        detector="acquisition_saturation",
        lever="memory",
        target="trusted_acquisition",
        label=f"aquisicao confiavel saturada {saturated}x na janela; fontes atuais esgotadas para {sorted(gap_ids)}",
        severity=min(1.0, 0.3 + saturated * 0.08),
        evidence={"saturated_runs": saturated, "gap_ids": sorted(gap_ids)},
        recommendation={
            "type": "record_memory_insight",
            "title": "Fontes confiaveis saturadas para lacunas recorrentes",
            "text": (
                f"As lacunas {sorted(gap_ids)} esgotaram as fontes confiaveis disponiveis "
                f"({saturated} execucoes saturadas). Diversificar dominios confiaveis via "
                "ULTRON_TRUSTED_SOURCE_DOMAINS ou ampliar o catalogo de seeds."
            ),
        },
    )]


def detect_chronic_surprise(window: int) -> list[dict[str, Any]]:
    rows = _read_jsonl(PREDICTIONS_PATH, limit=window)
    by_kind: dict[str, int] = {}
    for row in rows:
        if bool(row.get("high_surprise")):
            kind = str(row.get("kind") or "")
            if kind:
                by_kind[kind] = by_kind.get(kind, 0) + 1
    findings = []
    for kind, count in sorted(by_kind.items()):
        if count < CHRONIC_SURPRISE_MIN:
            continue
        findings.append(_finding(
            detector="chronic_surprise",
            lever="prompt",
            target=kind,
            label=f"consequencias de {kind} surpreendem o modelo repetidamente ({count}x)",
            severity=min(1.0, 0.35 + count * 0.08),
            evidence={"kind": kind, "high_surprise_count": count},
            recommendation={
                "type": "adjust_prompt_policy",
                "kind": kind,
                "directive": (
                    f"Antes de executar {kind}, declarar explicitamente a previsao e tratar o resultado "
                    "como hipotese: o modelo de consequencias desta acao esta mal calibrado."
                ),
            },
        ))
    return findings


def detect_ineffective_adjustments(rl_rows: list[dict[str, Any]], window: int) -> list[dict[str, Any]]:
    """Meta-avaliação: os ajustes do próprio system_tuner melhoraram algo?"""
    ledger = _read_jsonl(TUNER_LEDGER_PATH, limit=window)
    findings = []
    seen_kinds: set[str] = set()
    for entry in reversed(ledger):
        if str(entry.get("action_taken") or "") != "adjust_action":
            continue
        params = entry.get("params") if isinstance(entry.get("params"), dict) else {}
        kind = str(params.get("kind") or "")
        baseline = params.get("reward_baseline")
        ts = int(entry.get("ts") or 0)
        if not kind or baseline is None or kind in seen_kinds:
            continue
        seen_kinds.add(kind)
        rewards_after = [r["reward"] for r in rl_rows if r["kind"] == kind and r["ts"] > ts]
        if len(rewards_after) < INEFFECTIVE_MIN_RUNS_AFTER:
            continue
        mean_after = sum(rewards_after) / len(rewards_after)
        if mean_after > float(baseline) + 0.05:
            continue
        findings.append(_finding(
            detector="ineffective_adjustment",
            lever="subagent",
            target=kind,
            label=(
                f"ajuste em {kind} nao melhorou a recompensa "
                f"(baseline={float(baseline):.2f}, depois={mean_after:.2f} em {len(rewards_after)} execucoes)"
            ),
            severity=0.5,
            evidence={
                "kind": kind,
                "reward_baseline": float(baseline),
                "mean_reward_after": round(mean_after, 4),
                "runs_after": len(rewards_after),
                "adjustment_ts": ts,
            },
            recommendation={"type": "revert_override", "kind": kind},
        ))
    return findings


def evaluate(window: int = DEFAULT_WINDOW) -> dict[str, Any]:
    started = _now()
    rl_rows = _rl_run_rows(window)
    findings: list[dict[str, Any]] = []
    findings.extend(detect_low_reward_actions(rl_rows))
    findings.extend(detect_recurring_failures(rl_rows))
    findings.extend(detect_patch_pipeline_stall(window))
    findings.extend(detect_acquisition_saturation(window))
    findings.extend(detect_chronic_surprise(window))
    findings.extend(detect_ineffective_adjustments(rl_rows, window))
    findings.sort(key=lambda f: -float(f.get("severity") or 0.0))

    report = {
        "schema": EVAL_SCHEMA,
        "ok": True,
        "ts": started,
        "window": int(window),
        "non_llm": True,
        "rl_runs_scanned": len(rl_rows),
        "findings": findings,
        "findings_count": len(findings),
        "levers": sorted({str(f.get("lever")) for f in findings}),
    }
    _append_jsonl(EVAL_LOG_PATH, report)
    _write_json(STATE_PATH, {
        "schema": EVAL_SCHEMA,
        "last_ts": started,
        "last_findings_count": len(findings),
        "last_levers": report["levers"],
        "last_findings": findings[:10],
    })
    return report


def status() -> dict[str, Any]:
    state = {}
    try:
        if STATE_PATH.exists():
            state = json.loads(STATE_PATH.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        state = {}
    return {
        "ok": True,
        "schema": EVAL_SCHEMA,
        "state": state if isinstance(state, dict) else {},
        "recent_evaluations": _read_jsonl(EVAL_LOG_PATH, limit=10),
    }


def run_selftest() -> dict[str, Any]:
    rl_rows = [
        {"ts": 100 + i, "kind": "selftest_kind", "reward": 0.1, "error": "timeout after 30s", "ok": False}
        for i in range(5)
    ]
    low = detect_low_reward_actions(rl_rows)
    failures = detect_recurring_failures(rl_rows)
    return {
        "ok": bool(low and failures and low[0]["recommendation"]["type"] == "adjust_action"),
        "non_llm": True,
        "low_reward_findings": len(low),
        "failure_findings": len(failures),
    }
