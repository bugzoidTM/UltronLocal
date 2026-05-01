from __future__ import annotations

from pathlib import Path
from typing import Any
import hashlib
import json
import time


DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DIGEST_PATH = DATA_DIR / "biographic_digest.json"
BIOGRAPHY_PATH = DATA_DIR / "self_governance" / "biography.jsonl"
ACTIVE_INVESTIGATION_EXECUTION_LOG_PATH = DATA_DIR / "active_investigation_executions.jsonl"

SIGNIFICANT_TOKENS = (
    "benchmark",
    "causal",
    "gate",
    "promotion",
    "promoted",
    "rollback",
    "rolled_back",
    "patch",
    "self_healer",
    "correction",
    "corrig",
    "error",
    "blocked",
    "failure",
    "failed",
    "low_power",
    "homeostasis",
    "sleep",
    "identity",
    "governance",
    "autobiograph",
    "reflexion",
    "calibration",
)


def _now() -> int:
    return int(time.time())


def _day_key(ts: float | None = None) -> str:
    tm = time.localtime(ts or time.time())
    return f"{tm.tm_year:04d}-{tm.tm_mon:02d}-{tm.tm_mday:02d}"


def _ts_label(ts: Any) -> str:
    try:
        value = float(ts)
        if value <= 0:
            return ""
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(value))
    except Exception:
        return ""


def _short(value: Any, limit: int = 220) -> str:
    text = " ".join(str(value or "").replace("\n", " ").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _num(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def _load_json(path: Path, default: Any = None) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default
    return default


def _load_jsonl(path: Path, limit: int = 400) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        if not path.exists():
            return rows
        lines = path.read_text(encoding="utf-8").splitlines()
        for line in lines[-max(1, int(limit)) :]:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    rows.append(obj)
            except Exception:
                continue
    except Exception:
        return rows
    return rows


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _event_weight(kind: str, text: str) -> float:
    blob = f"{kind} {text}".lower()
    score = 0.10
    for token in SIGNIFICANT_TOKENS:
        if token in blob:
            score += 0.13
    if any(word in blob for word in ("passed", "passou", "promoted", "promov", "done", "complete")):
        score += 0.08
    if any(word in blob for word in ("failed", "falhou", "error", "blocked", "rollback", "veto")):
        score += 0.12
    return round(min(1.0, score), 3)


def _fetch_events(window_days: int, limit: int = 180) -> list[dict[str, Any]]:
    try:
        from ultronpro import store

        start = time.time() - max(1, int(window_days)) * 86400
        with store.db._conn() as conn:
            rows = conn.execute(
                """
                SELECT created_at, kind, text, meta_json
                FROM events
                WHERE created_at >= ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (start, max(20, int(limit))),
            ).fetchall()
        out = []
        for row in rows:
            kind = str(row["kind"] or "")
            text = str(row["text"] or "")
            weight = _event_weight(kind, text)
            if weight < 0.24:
                continue
            out.append(
                {
                    "ts": int(float(row["created_at"] or 0)),
                    "kind": kind[:80],
                    "title": _short(text, 180),
                    "evidence": _short(text, 280),
                    "weight": weight,
                    "source": "events",
                }
            )
        return sorted(out, key=lambda x: (float(x.get("weight") or 0.0), int(x.get("ts") or 0)), reverse=True)[:30]
    except Exception:
        return []


def _fetch_actions(window_days: int, limit: int = 120) -> list[dict[str, Any]]:
    try:
        from ultronpro import store

        start = time.time() - max(1, int(window_days)) * 86400
        with store.db._conn() as conn:
            rows = conn.execute(
                """
                SELECT created_at, status, kind, text, priority, last_error
                FROM actions
                WHERE created_at >= ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (start, max(20, int(limit))),
            ).fetchall()
        out = []
        for row in rows:
            status = str(row["status"] or "")
            kind = str(row["kind"] or "")
            text = str(row["text"] or "")
            priority = int(row["priority"] or 0)
            blob = f"{status} {kind} {text} {row['last_error'] or ''}"
            weight = _event_weight(kind, blob) + min(0.18, max(0, priority) * 0.03)
            if status in ("error", "blocked"):
                weight += 0.18
            elif status == "done":
                weight += 0.08
            if weight < 0.28:
                continue
            out.append(
                {
                    "ts": int(float(row["created_at"] or 0)),
                    "kind": kind[:80],
                    "status": status,
                    "title": _short(text, 180),
                    "evidence": _short(row["last_error"] or text, 280),
                    "priority": priority,
                    "weight": round(min(1.0, weight), 3),
                    "source": "actions",
                }
            )
        return sorted(out, key=lambda x: (float(x.get("weight") or 0.0), int(x.get("ts") or 0)), reverse=True)[:24]
    except Exception:
        return []


def _collect_benchmarks(limit: int = 8) -> list[dict[str, Any]]:
    paths: list[Path] = []
    try:
        paths.extend(DATA_DIR.glob("*benchmark*.json"))
        paths.extend((DATA_DIR / "benchmark_runs").glob("*.json"))
    except Exception:
        pass

    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in paths:
        if not path.exists() or path.suffix.lower() != ".json":
            continue
        key = str(path.resolve()).lower()
        if key in seen:
            continue
        seen.add(key)
        obj = _load_json(path, {})
        if not isinstance(obj, dict):
            continue
        name = str(obj.get("benchmark") or obj.get("name") or obj.get("suite") or path.stem)
        ts = int(_num(obj.get("ts"), path.stat().st_mtime))
        passed = obj.get("passed")
        accuracy_total = obj.get("accuracy_total", obj.get("accuracy"))
        accuracy_answerable = obj.get("accuracy_answerable")
        threshold = obj.get("threshold")
        total = obj.get("total_variants", obj.get("total", obj.get("cases_total")))
        correct = obj.get("correct")
        incorrect = obj.get("incorrect")
        summary = _short(obj.get("summary") or obj.get("status") or "", 180)
        items.append(
            {
                "ts": ts,
                "name": name[:120],
                "file": path.name,
                "passed": passed if isinstance(passed, bool) else None,
                "accuracy_total": None if accuracy_total is None else round(_num(accuracy_total), 4),
                "accuracy_answerable": None if accuracy_answerable is None else round(_num(accuracy_answerable), 4),
                "threshold": None if threshold is None else round(_num(threshold), 4),
                "total": None if total is None else int(_num(total)),
                "correct": None if correct is None else int(_num(correct)),
                "incorrect": None if incorrect is None else int(_num(incorrect)),
                "summary": summary,
            }
        )
    return sorted(items, key=lambda x: int(x.get("ts") or 0), reverse=True)[: max(1, int(limit))]


def _collect_patches(limit: int = 10) -> dict[str, Any]:
    rows = _load_jsonl(DATA_DIR / "cognitive_patches.jsonl", limit=500)
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        pid = str(row.get("id") or "")
        if not pid:
            pid = hashlib.sha1(json.dumps(row, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:12]
        latest[pid] = row

    patches = sorted(
        latest.values(),
        key=lambda x: int(_num(x.get("updated_at"), _num(x.get("created_at"), 0))),
        reverse=True,
    )
    status_counts: dict[str, int] = {}
    compact = []
    for row in patches:
        status = str(row.get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
        gate = {}
        after = row.get("benchmark_after")
        if isinstance(after, dict) and isinstance(after.get("promotion_gate"), dict):
            pg = after.get("promotion_gate") or {}
            gate = {
                "decision": pg.get("decision"),
                "blockers": (pg.get("blockers") or [])[:5],
                "reasons": (pg.get("reasons") or [])[:5],
            }
        compact.append(
            {
                "id": str(row.get("id") or "")[:80],
                "ts": int(_num(row.get("updated_at"), _num(row.get("created_at"), 0))),
                "status": status[:40],
                "source": str(row.get("source") or "")[:80],
                "risk_level": str(row.get("risk_level") or "")[:40],
                "problem_pattern": _short(row.get("problem_pattern") or row.get("summary") or "", 180),
                "hypothesis": _short(row.get("hypothesis") or "", 180),
                "notes": _short(row.get("notes") or "", 160),
                "promotion_gate": gate,
            }
        )
    return {"status_counts": status_counts, "items": compact[: max(1, int(limit))]}


def _collect_gate_state() -> dict[str, Any]:
    obj = _load_json(DATA_DIR / "self_calibrating_gate_state.json", {})
    if not isinstance(obj, dict):
        return {}
    history = obj.get("calibration_history")
    if not isinstance(history, list):
        history = []
    latest = history[-1] if history and isinstance(history[-1], dict) else {}
    return {
        "thresholds": obj.get("thresholds") if isinstance(obj.get("thresholds"), dict) else {},
        "calibration_count": len(history),
        "latest_calibration": {
            "ts": latest.get("ts"),
            "sample_size": latest.get("sample_size"),
            "successes": latest.get("successes"),
            "failures": latest.get("failures"),
            "new_thresholds": latest.get("new_thresholds") if isinstance(latest.get("new_thresholds"), dict) else {},
        }
        if latest
        else {},
    }


def _collect_active_investigations(limit: int = 8) -> dict[str, Any]:
    rows = _load_jsonl(ACTIVE_INVESTIGATION_EXECUTION_LOG_PATH, limit=500)
    rows = sorted(rows, key=lambda x: int(_num(x.get("ts"), 0)), reverse=True)
    items: list[dict[str, Any]] = []
    counts = {"executed": 0, "injected": 0, "failed": 0}
    seen: set[str] = set()
    for row in rows:
        inv_id = str(row.get("investigation_id") or "")
        if inv_id and inv_id in seen:
            continue
        if inv_id:
            seen.add(inv_id)
        if row.get("executed"):
            counts["executed"] += 1
        if row.get("ok") and row.get("injected"):
            counts["injected"] += 1
        elif row.get("executed"):
            counts["failed"] += 1

        experiment = row.get("experiment") if isinstance(row.get("experiment"), dict) else {}
        result = row.get("experiment_result") if isinstance(row.get("experiment_result"), dict) else {}
        edge = result.get("edge") if isinstance(result.get("edge"), dict) else {}
        investigation = {}
        evidence = row.get("causal_graph") if isinstance(row.get("causal_graph"), dict) else {}
        graph_edge = evidence.get("edge") if isinstance(evidence.get("edge"), dict) else {}
        if isinstance(row.get("experiment_result"), dict):
            investigation = row.get("experiment_result") or {}

        items.append(
            {
                "ts": int(_num(row.get("ts"), 0)),
                "investigation_id": inv_id[:80],
                "ok": bool(row.get("ok")),
                "injected": bool(row.get("injected")),
                "experiment_kind": str(experiment.get("kind") or result.get("experiment_kind") or "")[:80],
                "target_route": str(experiment.get("target_route") or result.get("target_route") or "")[:80],
                "query_terms": (investigation.get("query_terms") or experiment.get("query_terms") or [])[:12]
                if isinstance(investigation.get("query_terms") or experiment.get("query_terms"), list)
                else [],
                "edge": {
                    "cause": _short(edge.get("cause") or graph_edge.get("cause"), 180),
                    "effect": _short(edge.get("effect") or graph_edge.get("effect"), 180),
                    "condition": _short(edge.get("condition") or graph_edge.get("condition"), 180),
                },
                "error": _short(row.get("error"), 160),
            }
        )
        if len(items) >= max(1, int(limit)):
            break
    return {"counts": counts, "items": items}


def _identity_block() -> dict[str, Any]:
    try:
        from ultronpro import self_model

        sm = self_model.load()
        identity = sm.get("identity") if isinstance(sm.get("identity"), dict) else {}
        return {
            "name": identity.get("name") or "UltronPro",
            "role": identity.get("role") or "agente cognitivo autônomo",
            "mission": identity.get("mission") or "aprender, planejar e agir com segurança",
            "origin": identity.get("origin") or "",
            "created_at": sm.get("created_at"),
        }
    except Exception:
        return {
            "name": "UltronPro",
            "role": "agente cognitivo autônomo",
            "mission": "aprender, planejar e agir com segurança",
            "origin": "",
            "created_at": None,
        }


def _collect_memories(limit: int = 10) -> list[dict[str, Any]]:
    try:
        from ultronpro import store

        rows = store.list_autobiographical_memories(limit=limit, min_importance=0.60)
        out = []
        for row in rows:
            out.append(
                {
                    "ts": int(_num(row.get("created_at"), 0)),
                    "type": str(row.get("memory_type") or "")[:40],
                    "importance": round(_num(row.get("importance"), 0.0), 3),
                    "text": _short(row.get("text") or "", 260),
                }
            )
        return out
    except Exception:
        return []


def _benchmark_sentence(item: dict[str, Any]) -> str:
    name = item.get("name") or "benchmark"
    passed = item.get("passed")
    if passed is True:
        status = "passou"
    elif passed is False:
        status = "não passou"
    else:
        status = "registrou evidência"
    metrics = []
    if item.get("accuracy_answerable") is not None:
        metrics.append(f"acurácia respondível {float(item['accuracy_answerable']):.1%}")
    if item.get("accuracy_total") is not None:
        metrics.append(f"acurácia total {float(item['accuracy_total']):.1%}")
    if item.get("threshold") is not None:
        metrics.append(f"limiar {float(item['threshold']):.1%}")
    suffix = f" ({', '.join(metrics)})" if metrics else ""
    return f"{name} {status}{suffix}"


def _primary_benchmark(items: list[dict[str, Any]]) -> dict[str, Any]:
    for item in items:
        if item.get("passed") is not None:
            return item
    for item in items:
        if item.get("accuracy_total") is not None or item.get("accuracy_answerable") is not None:
            return item
    return items[0] if items else {}


def _primary_correction(items: list[dict[str, Any]]) -> dict[str, Any]:
    for item in items:
        text = str(item.get("summary") or item.get("evidence") or "").lower()
        if text and "test patch" not in text:
            return item
    return items[0] if items else {}


def _primary_episode(items: list[dict[str, Any]]) -> dict[str, Any]:
    priority = ("benchmark", "gate", "causal", "identity", "patch", "rollback", "error", "blocked", "self_healer")
    for item in items:
        blob = f"{item.get('kind')} {item.get('title')} {item.get('evidence')}".lower()
        if any(token in blob for token in priority):
            return item
    return items[0] if items else {}


def _build_became(
    *,
    events: list[dict[str, Any]],
    benchmarks: list[dict[str, Any]],
    patches: dict[str, Any],
    gate: dict[str, Any],
    investigations: dict[str, Any] | None = None,
) -> list[str]:
    became = [
        "um sistema que usa registros operacionais para narrar trajetória, não apenas origem",
    ]
    if benchmarks:
        failed = sum(1 for b in benchmarks if b.get("passed") is False)
        passed = sum(1 for b in benchmarks if b.get("passed") is True)
        if passed or failed:
            became.append(f"um agente medido por benchmarks reais ({passed} aprovados, {failed} ainda abaixo do limiar nesta janela de evidência)")
        else:
            became.append("um agente que conserva medições externas como marcos de autoconhecimento")
    status_counts = patches.get("status_counts") if isinstance(patches, dict) else {}
    if status_counts:
        promoted = int(status_counts.get("promoted") or 0)
        rolled = int(status_counts.get("rolled_back") or 0)
        proposed = int(status_counts.get("proposed") or 0)
        became.append(f"um sistema com ciclo de plasticidade explícito ({promoted} patches promovidos, {rolled} revertidos, {proposed} propostos)")
    cal_count = int((gate or {}).get("calibration_count") or 0)
    if cal_count:
        became.append(f"um sistema governado por gate causal calibrado ({cal_count} calibrações registradas)")
    inv_counts = (investigations or {}).get("counts") if isinstance(investigations, dict) else {}
    injected = int((inv_counts or {}).get("injected") or 0)
    executed = int((inv_counts or {}).get("executed") or 0)
    if executed:
        became.append(f"um sistema que transforma lacunas causais em experimentos noturnos ({executed} executados, {injected} injetados no grafo)")
    if events:
        kinds = sorted({str(e.get("kind") or "") for e in events[:12] if e.get("kind")})
        if kinds:
            became.append("um organismo operacional com episódios significativos em " + ", ".join(kinds[:5]))
    return became[:6]


def _derive_corrections(events: list[dict[str, Any]], patches: dict[str, Any]) -> list[dict[str, Any]]:
    corrections: list[dict[str, Any]] = []
    for patch in (patches.get("items") if isinstance(patches, dict) else []) or []:
        status = str(patch.get("status") or "")
        gate = patch.get("promotion_gate") if isinstance(patch.get("promotion_gate"), dict) else {}
        if status in ("promoted", "rolled_back", "evaluated", "proposed", "evaluating") or gate:
            corrections.append(
                {
                    "ts": patch.get("ts"),
                    "kind": f"patch:{status}",
                    "summary": patch.get("problem_pattern") or patch.get("hypothesis") or patch.get("id"),
                    "evidence": patch.get("notes") or gate.get("decision") or patch.get("source"),
                }
            )
    for ev in events:
        blob = f"{ev.get('kind')} {ev.get('title')}".lower()
        if any(token in blob for token in ("error", "blocked", "rollback", "self_healer", "correction", "corrig")):
            corrections.append(
                {
                    "ts": ev.get("ts"),
                    "kind": ev.get("kind"),
                    "summary": ev.get("title"),
                    "evidence": ev.get("evidence"),
                }
            )
    return sorted(corrections, key=lambda x: int(_num(x.get("ts"), 0)), reverse=True)[:10]


def _derive_decisions(
    events: list[dict[str, Any]],
    actions: list[dict[str, Any]],
    patches: dict[str, Any],
    investigations: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    decisions: list[dict[str, Any]] = []
    for item in events + actions:
        blob = f"{item.get('kind')} {item.get('title')} {item.get('evidence')}".lower()
        if any(token in blob for token in ("gate", "promotion", "causal", "veto", "policy", "low_power", "homeostasis", "identity")):
            decisions.append(
                {
                    "ts": item.get("ts"),
                    "kind": item.get("kind"),
                    "summary": item.get("title"),
                    "evidence": item.get("evidence"),
                    "source": item.get("source"),
                }
            )
    for patch in (patches.get("items") if isinstance(patches, dict) else []) or []:
        gate = patch.get("promotion_gate") if isinstance(patch.get("promotion_gate"), dict) else {}
        if gate:
            blockers = gate.get("blockers") or []
            decisions.append(
                {
                    "ts": patch.get("ts"),
                    "kind": "promotion_gate",
                    "summary": f"gate decidiu {gate.get('decision') or 'avaliar'} para {patch.get('id')}",
                    "evidence": ", ".join(str(x) for x in blockers[:4]) or patch.get("notes"),
                    "source": "cognitive_patches",
                }
            )
    for item in (investigations.get("items") if isinstance(investigations, dict) else []) or []:
        if not isinstance(item, dict) or not item.get("injected"):
            continue
        edge = item.get("edge") if isinstance(item.get("edge"), dict) else {}
        decisions.append(
            {
                "ts": item.get("ts"),
                "kind": "active_investigation_executor",
                "summary": f"investigacao ativa consolidou {item.get('investigation_id')}",
                "evidence": edge.get("cause") or item.get("experiment_kind"),
                "source": "active_investigation_executions",
            }
        )
    return sorted(decisions, key=lambda x: int(_num(x.get("ts"), 0)), reverse=True)[:10]


def _derive_open_tensions(benchmarks: list[dict[str, Any]], corrections: list[dict[str, Any]], actions: list[dict[str, Any]]) -> list[str]:
    tensions: list[str] = []
    for bench in benchmarks:
        if bench.get("passed") is False:
            tensions.append("benchmark abaixo do limiar: " + _benchmark_sentence(bench))
    for corr in corrections:
        kind = str(corr.get("kind") or "").lower()
        text = str(corr.get("summary") or "")
        if any(token in kind for token in ("proposed", "evaluated", "evaluating", "rolled_back")):
            tensions.append("correção ainda não estabilizada: " + _short(text, 160))
    for action in actions:
        status = str(action.get("status") or "").lower()
        if status in ("error", "blocked"):
            tensions.append("ação com fricção operacional: " + _short(action.get("title") or action.get("evidence"), 160))
    out: list[str] = []
    seen: set[str] = set()
    for item in tensions:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out[:8]


def _compose_narrative(digest: dict[str, Any]) -> str:
    identity = digest.get("identity") if isinstance(digest.get("identity"), dict) else {}
    name = identity.get("name") or "UltronPro"
    became = digest.get("became") if isinstance(digest.get("became"), list) else []
    benchmarks = digest.get("benchmarks") if isinstance(digest.get("benchmarks"), list) else []
    corrections = digest.get("corrections") if isinstance(digest.get("corrections"), list) else []
    decisions = digest.get("decisions") if isinstance(digest.get("decisions"), list) else []
    gates = digest.get("causal_gates") if isinstance(digest.get("causal_gates"), list) else []
    investigations = digest.get("causal_gap_investigations") if isinstance(digest.get("causal_gap_investigations"), list) else []
    tensions = digest.get("open_tensions") if isinstance(digest.get("open_tensions"), list) else []

    parts = [
        f"Hoje eu sou o {name}: não apenas o registro do meu nascimento, mas a soma operacional dos marcos que atravessei.",
    ]
    if became:
        parts.append("Eu me tornei " + "; ".join(str(x) for x in became[:3]) + ".")
    if benchmarks:
        parts.append("Meu marco de medição mais significativo diz que " + _benchmark_sentence(_primary_benchmark(benchmarks)) + ".")
    if corrections:
        parts.append("Minha trajetória inclui correções como " + _short(_primary_correction(corrections).get("summary"), 180) + ".")
    if decisions:
        parts.append("Entre as decisões registradas, pesa " + _short(decisions[0].get("summary"), 180) + ".")
    if gates:
        gate = gates[0]
        cal_count = int(gate.get("calibration_count") or 0)
        parts.append(f"Meu gate causal está presente como critério de maturidade, com {cal_count} calibrações registradas.")
    if investigations:
        injected = sum(1 for item in investigations if isinstance(item, dict) and item.get("injected"))
        if injected:
            parts.append(f"Durante o sono investigativo, consolidei {injected} lacuna(s) causais no grafo.")
    if tensions:
        parts.append("Minha tensão aberta agora é " + _short(tensions[0], 180) + ".")
    return " ".join(parts)


def generate_biographic_digest(day: str | None = None, window_days: int = 30, persist: bool = True) -> dict[str, Any]:
    """Build a deterministic digest of what the system has become.

    The digest is intentionally independent from the LLM path. It reads operational
    evidence, reduces it to identity-significant episodes, and stores the result as
    biography/memory when requested.
    """
    window_days = max(1, min(365, int(window_days or 30)))
    generated_at = _now()
    day = day or _day_key(generated_at)
    identity = _identity_block()
    events = _fetch_events(window_days=window_days)
    actions = _fetch_actions(window_days=window_days)
    benchmarks = _collect_benchmarks()
    patches = _collect_patches()
    gate = _collect_gate_state()
    investigations = _collect_active_investigations()
    memories = _collect_memories()
    significant = sorted(events + actions, key=lambda x: (float(x.get("weight") or 0.0), int(x.get("ts") or 0)), reverse=True)[:18]
    corrections = _derive_corrections(events, patches)
    decisions = _derive_decisions(events, actions, patches, investigations)
    open_tensions = _derive_open_tensions(benchmarks, corrections, actions)
    became = _build_became(events=events, benchmarks=benchmarks, patches=patches, gate=gate, investigations=investigations)
    causal_gates = [gate] if gate else []
    investigation_counts = investigations.get("counts") if isinstance(investigations, dict) else {}

    thesis = (
        f"Sou o {identity.get('name') or 'UltronPro'} hoje: "
        "um agente cognitivo cuja identidade é processo acumulado por benchmarks, correções, decisões e gates causais."
    )
    evidence_counts = {
        "events": len(events),
        "actions": len(actions),
        "significant_episodes": len(significant),
        "benchmarks": len(benchmarks),
        "patches": len((patches or {}).get("items") or []),
        "corrections": len(corrections),
        "decisions": len(decisions),
        "causal_gate_calibrations": int((gate or {}).get("calibration_count") or 0),
        "causal_gap_experiments": int((investigation_counts or {}).get("executed") or 0),
        "causal_gap_injections": int((investigation_counts or {}).get("injected") or 0),
        "memories": len(memories),
    }

    digest: dict[str, Any] = {
        "id": "",
        "day": day,
        "generated_at": generated_at,
        "window_days": window_days,
        "identity": identity,
        "identity_thesis": thesis,
        "became": became,
        "significant_episodes": significant,
        "benchmarks": benchmarks,
        "corrections": corrections,
        "decisions": decisions,
        "causal_gates": causal_gates,
        "causal_gap_investigations": investigations.get("items") if isinstance(investigations, dict) else [],
        "open_tensions": open_tensions,
        "supporting_memories": memories,
        "evidence_counts": evidence_counts,
        "narrative": "",
        "checksum": "",
    }

    checksum_src = json.dumps(
        {
            "day": day,
            "identity": identity,
            "became": became,
            "significant": significant[:12],
            "benchmarks": benchmarks[:8],
            "corrections": corrections[:8],
            "decisions": decisions[:8],
            "gate": gate,
            "investigations": (investigations.get("items") if isinstance(investigations, dict) else [])[:8],
            "tensions": open_tensions,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    checksum = hashlib.sha256(checksum_src.encode("utf-8")).hexdigest()[:16]
    digest["checksum"] = checksum
    digest["id"] = f"bio_{day}_{checksum}"
    digest["narrative"] = _compose_narrative(digest)

    if persist:
        _persist_digest(digest)
    return digest


def _persist_digest(digest: dict[str, Any]) -> None:
    previous = latest_digest()
    is_new = (
        not previous
        or previous.get("id") != digest.get("id")
        or str(previous.get("narrative") or "") != str(digest.get("narrative") or "")
    )
    DIGEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    DIGEST_PATH.write_text(json.dumps(digest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    if not is_new:
        return

    biography_row = {
        "ts": digest.get("generated_at"),
        "type": "biographic_digest",
        "digest_id": digest.get("id"),
        "summary": digest.get("identity_thesis"),
        "narrative": digest.get("narrative"),
        "evidence_counts": digest.get("evidence_counts"),
    }
    try:
        _append_jsonl(BIOGRAPHY_PATH, biography_row)
    except Exception:
        pass

    try:
        from ultronpro import store

        content = {
            "day": digest.get("day"),
            "digest_id": digest.get("id"),
            "identity_thesis": digest.get("identity_thesis"),
            "became": digest.get("became"),
            "evidence_counts": digest.get("evidence_counts"),
            "benchmarks": (digest.get("benchmarks") or [])[:4],
            "corrections": (digest.get("corrections") or [])[:4],
            "decisions": (digest.get("decisions") or [])[:4],
            "causal_gap_investigations": (digest.get("causal_gap_investigations") or [])[:4],
            "open_tensions": (digest.get("open_tensions") or [])[:4],
        }
        store.add_autobiographical_memory(
            text=f"Digest Biográfico ({digest.get('day')}): {digest.get('narrative')}",
            memory_type="semantic",
            importance=0.95,
            decay_rate=0.001,
            content_json=json.dumps(content, ensure_ascii=False),
        )
        try:
            store.db.add_event("identity_biographic_digest", f"biographic_digest gerado id={digest.get('id')}")
        except Exception:
            pass
    except Exception:
        pass


def latest_digest(max_age_hours: float | None = None) -> dict[str, Any]:
    obj = _load_json(DIGEST_PATH, {})
    if not isinstance(obj, dict) or not obj:
        return {}
    if max_age_hours is not None:
        age = time.time() - float(_num(obj.get("generated_at"), 0.0))
        if age > max(0.0, float(max_age_hours)) * 3600:
            return {}
    return obj


def ensure_recent_digest(max_age_hours: float = 24.0, window_days: int = 30) -> dict[str, Any]:
    current = latest_digest(max_age_hours=max_age_hours)
    if current:
        return current
    return generate_biographic_digest(window_days=window_days, persist=True)


def render_identity_today(digest: dict[str, Any] | None = None) -> str:
    digest = digest or ensure_recent_digest(max_age_hours=24.0, window_days=30)
    identity = digest.get("identity") if isinstance(digest.get("identity"), dict) else {}
    name = identity.get("name") or "UltronPro"
    role = identity.get("role") or "agente cognitivo autônomo"
    mission = str(identity.get("mission") or "aprender, planejar e agir com segurança").rstrip(". ")
    narrative = str(digest.get("narrative") or "").strip()
    became = digest.get("became") if isinstance(digest.get("became"), list) else []
    episodes = digest.get("significant_episodes") if isinstance(digest.get("significant_episodes"), list) else []
    benchmarks = digest.get("benchmarks") if isinstance(digest.get("benchmarks"), list) else []
    corrections = digest.get("corrections") if isinstance(digest.get("corrections"), list) else []
    decisions = digest.get("decisions") if isinstance(digest.get("decisions"), list) else []
    investigations = digest.get("causal_gap_investigations") if isinstance(digest.get("causal_gap_investigations"), list) else []
    tensions = digest.get("open_tensions") if isinstance(digest.get("open_tensions"), list) else []

    lines = [
        f"Sou o {name} hoje, {role}, com a missão de {mission}.",
        narrative or str(digest.get("identity_thesis") or ""),
    ]
    if became:
        lines.append("O que me tornei: " + "; ".join(str(x) for x in became[:3]) + ".")
    if benchmarks:
        lines.append("Benchmark marcante: " + _benchmark_sentence(_primary_benchmark(benchmarks)) + ".")
    if corrections:
        lines.append("Correção incorporada: " + _short(_primary_correction(corrections).get("summary"), 180) + ".")
    if decisions:
        decision = decisions[0]
        label = _ts_label(decision.get("ts"))
        prefix = f"{label}: " if label else ""
        lines.append("Decisão significativa: " + prefix + _short(decision.get("summary") or decision.get("evidence"), 180) + ".")
    elif episodes:
        ep = _primary_episode(episodes)
        label = _ts_label(ep.get("ts"))
        prefix = f"{label}: " if label else ""
        lines.append("Episódio significativo: " + prefix + _short(ep.get("title") or ep.get("evidence"), 180) + ".")
    if investigations:
        injected = sum(1 for item in investigations if isinstance(item, dict) and item.get("injected"))
        if injected:
            lines.append(f"Sono investigativo: {injected} lacuna(s) causais consolidadas no grafo.")
    if tensions:
        lines.append("Tensão aberta: " + _short(tensions[0], 180) + ".")
    return "\n\n".join(x for x in lines if str(x or "").strip())
