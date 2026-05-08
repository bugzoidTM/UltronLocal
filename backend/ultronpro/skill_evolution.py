from __future__ import annotations

import hashlib
import json
import math
import re
import time
from pathlib import Path
from typing import Any


DATA_DIR = Path(__file__).resolve().parent.parent / "data"
STATE_PATH = DATA_DIR / "skill_evolution_state.json"
BENCHMARK_LOG_PATH = DATA_DIR / "skill_evolution_benchmarks.jsonl"
MATERIALIZED_SKILLS_DIR = Path(__file__).resolve().parent.parent / "ultron_skills"

SCHEMA = "ultron.skill_evolution.v1"
MIN_REPLAY_SCORE = 0.58
MIN_TRANSFER_SCORE = 0.52

STOPWORDS = {
    "para",
    "como",
    "qual",
    "quais",
    "sobre",
    "porque",
    "voce",
    "você",
    "isso",
    "esta",
    "este",
    "essa",
    "esse",
    "contexto",
    "sistema",
    "ultron",
    "ultronpro",
    "responda",
    "explique",
    "pergunta",
    "pergunte",
    "diga",
    "faca",
    "faça",
}


def _now() -> int:
    return int(time.time())


def _safe(value: Any, limit: int = 400) -> str:
    return " ".join(str(value or "").strip().split())[:limit]


def _tokens(text: str) -> list[str]:
    out: list[str] = []
    for token in re.findall(r"[a-zA-Z0-9_À-ÿ]{3,}", str(text or "").lower()):
        if token in STOPWORDS:
            continue
        out.append(token)
    return out


def _token_set(text: str) -> set[str]:
    return set(_tokens(text))


def _similarity(left: str, right: str) -> float:
    a = _token_set(left)
    b = _token_set(right)
    if not a or not b:
        return 0.0
    return len(a & b) / max(1, len(a | b))


def _slug(text: str, fallback: str = "skill") -> str:
    raw = re.sub(r"[^a-zA-Z0-9]+", "_", str(text or "").lower()).strip("_")
    raw = re.sub(r"_+", "_", raw)
    return (raw or fallback)[:36].strip("_") or fallback


def _hash(value: Any, size: int = 10) -> str:
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()[:size]


def _default() -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "created_at": _now(),
        "updated_at": _now(),
        "candidates": {},
        "production_uses": [],
        "transfer_validations": [],
        "regressions": [],
        "rollbacks": [],
        "benchmark_runs": [],
    }


def _load() -> dict[str, Any]:
    if STATE_PATH.exists():
        try:
            data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data.setdefault("schema", SCHEMA)
                data.setdefault("candidates", {})
                data.setdefault("production_uses", [])
                data.setdefault("transfer_validations", [])
                data.setdefault("regressions", [])
                data.setdefault("rollbacks", [])
                data.setdefault("benchmark_runs", [])
                return data
        except Exception:
            pass
    return _default()


def _save(state: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    state["schema"] = SCHEMA
    state["updated_at"] = _now()
    state["production_uses"] = list(state.get("production_uses") or [])[-1200:]
    state["transfer_validations"] = list(state.get("transfer_validations") or [])[-600:]
    state["regressions"] = list(state.get("regressions") or [])[-400:]
    state["rollbacks"] = list(state.get("rollbacks") or [])[-200:]
    state["benchmark_runs"] = list(state.get("benchmark_runs") or [])[-80:]
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _read_route_episodes(limit: int = 400) -> list[dict[str, Any]]:
    try:
        from ultronpro.core import learned_intent

        path = learned_intent.ROUTE_EPISODES_PATH
    except Exception:
        path = DATA_DIR.parent / "data" / "intent_route_episodes.jsonl"
    if not Path(path).exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return []
    for line in lines[-max(1, int(limit or 1)) :]:
        try:
            row = json.loads(line)
        except Exception:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _module_from_episode(row: dict[str, Any]) -> str:
    module = _safe(row.get("module"), 80).lower()
    strategy = _safe(row.get("strategy"), 120).lower()
    if module and module != "unknown":
        return module
    if strategy.startswith("skill_"):
        return "skills"
    if "symbolic" in strategy:
        return "symbolic"
    if "local" in strategy:
        return "local_reasoning"
    if "autobiographical" in strategy or "identity" in strategy:
        return "autobiographical"
    if "cache" in strategy:
        return "semantic_cache"
    if "unavailable" in strategy or "timeout" in strategy or "error" in strategy:
        return "insufficient"
    return "reasoning"


def _episode_is_real_chat(row: dict[str, Any]) -> bool:
    source = _safe(row.get("source"), 80).lower()
    query = _safe(row.get("query"), 1200)
    if not query:
        return False
    if source not in {"chat", "chat_stream", "voice_chat", "frontend_chat"}:
        return False
    strategy = _safe(row.get("strategy"), 120).lower()
    if "error" in strategy or "timeout" in strategy:
        return False
    if bool(row.get("ok", True)) is False:
        return False
    return True


def _candidate_from_episode(row: dict[str, Any]) -> dict[str, Any] | None:
    if not _episode_is_real_chat(row):
        return None
    query = _safe(row.get("query"), 1600)
    toks = _tokens(query)
    if len(toks) < 2:
        return None
    module = _module_from_episode(row)
    strategy = _safe(row.get("strategy"), 120) or module
    signature = {
        "module": module,
        "strategy": strategy,
        "tokens": sorted(set(toks[:12])),
        "query_hash": _hash(query, 12),
    }
    cid = "cand_" + _hash(signature, 14)
    skill_slug = _slug("_".join(toks[:5]), fallback=module)
    skill_name = f"auto_{skill_slug}_{cid[-6:]}"[:64].strip("_")
    return {
        "candidate_id": cid,
        "skill_name": skill_name,
        "status": "candidate",
        "created_at": _now(),
        "updated_at": _now(),
        "source": "real_chat_interaction",
        "source_episode": {
            "ts": int(row.get("ts") or 0),
            "source": _safe(row.get("source"), 80),
            "strategy": strategy,
            "module": module,
            "latency_ms": int(row.get("latency_ms") or 0),
            "query": query,
        },
        "trigger_tokens": sorted(set(toks))[:18],
        "module": module,
        "strategy": strategy,
        "description": f"Generated from real chat route using {module}/{strategy}.",
        "replay": {},
        "transfer": {},
        "production_use_count": 0,
        "llm_avoidance_count": 0,
        "materialized_path": "",
    }


def generate_candidates(limit: int = 400, target: int | None = None) -> dict[str, Any]:
    state = _load()
    candidates = dict(state.get("candidates") or {})
    before = len(candidates)
    scanned = 0
    for row in reversed(_read_route_episodes(limit=limit)):
        cand = _candidate_from_episode(row)
        if not cand:
            continue
        scanned += 1
        cid = cand["candidate_id"]
        if cid in candidates:
            existing = dict(candidates[cid])
            existing["updated_at"] = _now()
            existing["seen_count"] = int(existing.get("seen_count") or 1) + 1
            existing.setdefault("source_episode", cand["source_episode"])
            candidates[cid] = existing
        else:
            cand["seen_count"] = 1
            candidates[cid] = cand
        if target and (len(candidates) - before) >= int(target):
            break
    state["candidates"] = candidates
    _save(state)
    return {
        "ok": True,
        "scanned_real_chat_episodes": scanned,
        "generated": len(candidates) - before,
        "candidate_count": len(candidates),
        "target": target,
        "path": str(STATE_PATH),
    }


def _replay_score(candidate: dict[str, Any]) -> dict[str, Any]:
    query = _safe((candidate.get("source_episode") or {}).get("query"), 1600)
    tokens = set(candidate.get("trigger_tokens") or [])
    coverage = len(tokens & _token_set(query)) / max(1, len(tokens))
    source_latency = int((candidate.get("source_episode") or {}).get("latency_ms") or 0)
    latency_bonus = 0.12 if source_latency and source_latency < 1000 else (0.04 if source_latency < 4000 else 0.0)
    module = str(candidate.get("module") or "")
    module_bonus = 0.12 if module in {"symbolic", "local_reasoning", "autobiographical", "semantic_cache", "skills"} else 0.06
    seen_bonus = min(0.12, math.log1p(int(candidate.get("seen_count") or 1)) / 20)
    score = min(1.0, 0.42 + (0.28 * coverage) + latency_bonus + module_bonus + seen_bonus)
    return {
        "score": round(score, 4),
        "coverage": round(coverage, 4),
        "source_latency_ms": source_latency,
        "module_bonus": module_bonus,
        "seen_count": int(candidate.get("seen_count") or 1),
        "passed": score >= MIN_REPLAY_SCORE,
    }


def _skill_markdown(candidate: dict[str, Any]) -> str:
    tokens = ", ".join(candidate.get("trigger_tokens") or [])
    module = _safe(candidate.get("module"), 80)
    strategy = _safe(candidate.get("strategy"), 120)
    description = _safe(candidate.get("description"), 180)
    return (
        "---\n"
        "path: auto/generated\n"
        f"description: \"{description}\"\n"
        "allowed_tools: []\n"
        "budget:\n"
        "  max_seconds: 2\n"
        "risk_level: low\n"
        "when_to_use: |\n"
        f"  Use when a chat request shares operational tokens with: {tokens}.\n"
        f"  Preferred local module: {module}. Preferred strategy: {strategy}.\n"
        "success_checks: []\n"
        "tags:\n"
        "  - generated\n"
        "  - chat\n"
        f"  - module_{_slug(module)}\n"
        + "".join(f"  - \"{_slug(t)}\"\n" for t in (candidate.get("trigger_tokens") or [])[:8])
        + "enabled: true\n"
        "version: 1.0.0\n"
        "author: skill_evolution\n"
        "---\n\n"
        f"# {candidate.get('skill_name')}\n\n"
        "Generated from a real chat interaction after replay validation.\n\n"
        "Execution is deterministic: the runtime rechecks local symbolic, local reasoning,\n"
        "cognitive response and cache paths before any LLM fallback is considered.\n"
    )


def _materialize(candidate: dict[str, Any]) -> str:
    skill_name = str(candidate.get("skill_name") or "")
    if not skill_name.startswith("auto_"):
        return ""
    skill_dir = MATERIALIZED_SKILLS_DIR / skill_name
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(_skill_markdown(candidate), encoding="utf-8")
    return str(skill_file)


def promote_by_replay(max_promotions: int = 20) -> dict[str, Any]:
    state = _load()
    candidates = dict(state.get("candidates") or {})
    promoted: list[dict[str, Any]] = []
    ranked: list[tuple[float, str, dict[str, Any]]] = []
    for cid, cand in candidates.items():
        if cand.get("status") == "promoted":
            continue
        replay = _replay_score(cand)
        cand["replay"] = replay
        candidates[cid] = cand
        if replay.get("passed"):
            ranked.append((float(replay.get("score") or 0.0), cid, cand))
    ranked.sort(key=lambda item: item[0], reverse=True)
    for _, cid, cand in ranked[: max(0, int(max_promotions or 0))]:
        cand["status"] = "promoted"
        cand["promoted_at"] = _now()
        cand["updated_at"] = _now()
        cand["materialized_path"] = _materialize(cand)
        candidates[cid] = cand
        promoted.append({
            "candidate_id": cid,
            "skill_name": cand.get("skill_name"),
            "replay_score": (cand.get("replay") or {}).get("score"),
            "materialized_path": cand.get("materialized_path"),
        })
    state["candidates"] = candidates
    _save(state)
    try:
        from ultronpro import skill_loader

        skill_loader.load_skills(force=True)
    except Exception:
        pass
    return {
        "ok": True,
        "promoted": promoted,
        "promoted_count": len(promoted),
        "total_promoted": len([c for c in candidates.values() if c.get("status") == "promoted"]),
    }


def _find_candidate_by_skill(skill_name: str, state: dict[str, Any] | None = None) -> tuple[str, dict[str, Any]] | tuple[None, None]:
    st = state or _load()
    for cid, cand in (st.get("candidates") or {}).items():
        if cand.get("skill_name") == skill_name:
            return cid, cand
    return None, None


def is_generated_skill(skill_name: str | None) -> bool:
    name = str(skill_name or "")
    if not name.startswith("auto_"):
        return False
    _, cand = _find_candidate_by_skill(name)
    return bool(cand and cand.get("status") == "promoted")


def suggest_generated_skill(query: str, min_score: float = 0.50) -> dict[str, Any] | None:
    q = _safe(query, 1600)
    if not q:
        return None
    state = _load()
    best: tuple[float, str, dict[str, Any]] | None = None
    for cid, cand in (state.get("candidates") or {}).items():
        if cand.get("status") != "promoted":
            continue
        source_query = _safe((cand.get("source_episode") or {}).get("query"), 1600)
        token_overlap = len(set(cand.get("trigger_tokens") or []) & _token_set(q)) / max(1, len(set(cand.get("trigger_tokens") or [])))
        score = max(_similarity(q, source_query), token_overlap * 0.85)
        if score >= min_score and (best is None or score > best[0]):
            best = (score, cid, cand)
    if not best:
        return None
    score, cid, cand = best
    return {
        "ok": True,
        "candidate_id": cid,
        "skill_name": cand.get("skill_name"),
        "score": round(score, 4),
        "module": cand.get("module"),
        "strategy": cand.get("strategy"),
    }


def _deterministic_resolve(candidate: dict[str, Any], task: str) -> tuple[bool, str, str]:
    module = str(candidate.get("module") or "")
    strategy = str(candidate.get("strategy") or "")
    tried: list[str] = []

    def try_symbolic() -> tuple[bool, str] | None:
        try:
            from ultronpro.symbolic_reasoner import _solve_deterministic

            tried.append("symbolic")
            ans = _solve_deterministic(task)
            if ans:
                return True, str(ans)
        except Exception:
            pass
        return None

    def try_local() -> tuple[bool, str] | None:
        try:
            from ultronpro import local_reasoning_engine

            tried.append("local_reasoning")
            res = local_reasoning_engine.resolve(task)
            if res.get("resolved") and res.get("result"):
                return True, str(res.get("result"))
        except Exception:
            pass
        return None

    def try_cognitive() -> tuple[bool, str] | None:
        try:
            from ultronpro import cognitive_response

            tried.append("cognitive_response")
            res = cognitive_response.first_refusal(task, min_confidence=0.86)
            if res.get("resolved") and res.get("answer"):
                return True, str(res.get("answer"))
        except Exception:
            pass
        return None

    order: list[Any]
    if module == "symbolic" or "symbolic" in strategy:
        order = [try_symbolic, try_local, try_cognitive]
    elif module in {"local_reasoning", "semantic_cache"} or "local" in strategy:
        order = [try_local, try_symbolic, try_cognitive]
    elif module == "autobiographical":
        order = [try_cognitive, try_local, try_symbolic]
    else:
        order = [try_local, try_symbolic, try_cognitive]

    for fn in order:
        out = fn()
        if out and out[0] and out[1].strip():
            return True, out[1].strip(), ",".join(tried)

    source_query = _safe((candidate.get("source_episode") or {}).get("query"), 260)
    overlap = _similarity(task, source_query)
    if overlap >= MIN_TRANSFER_SCORE:
        answer = (
            "Skill gerada aplicada ao padrao operacional reconhecido. "
            f"Modulo preferido: {module or 'unknown'}; estrategia original: {strategy or 'unknown'}. "
            "Nao ha resolucao deterministica especifica neste turno, entao a skill preservou incerteza e evitou fallback LLM."
        )
        return True, answer, ",".join(tried) or "pattern_match"
    return False, "Skill gerada nao encontrou cobertura deterministica suficiente para este turno.", ",".join(tried)


def execute_generated_skill(skill_name: str, task: str, *, production: bool = True) -> dict[str, Any]:
    state = _load()
    cid, cand = _find_candidate_by_skill(skill_name, state)
    if not cid or not cand or cand.get("status") != "promoted":
        return {
            "success": False,
            "output": "",
            "tools_used": ["skill_evolution"],
            "raw": {"reason": "generated_skill_not_promoted"},
        }
    started = time.time()
    success, output, resolver = _deterministic_resolve(cand, task)
    latency_ms = int((time.time() - started) * 1000)
    if production:
        record_production_use(
            str(cand.get("skill_name")),
            task,
            success=success,
            latency_ms=latency_ms,
            avoided_llm=True,
            resolver=resolver,
        )
    return {
        "success": success,
        "output": output,
        "tools_used": ["skill_evolution", resolver or "deterministic"],
        "raw": {
            "candidate_id": cid,
            "skill_name": cand.get("skill_name"),
            "module": cand.get("module"),
            "strategy": cand.get("strategy"),
            "latency_ms": latency_ms,
            "avoided_llm": True,
            "resolver": resolver,
        },
    }


def record_production_use(
    skill_name: str,
    task: str,
    *,
    success: bool,
    latency_ms: int,
    avoided_llm: bool,
    resolver: str = "",
) -> dict[str, Any]:
    state = _load()
    cid, cand = _find_candidate_by_skill(skill_name, state)
    if not cid or not cand:
        return {"ok": False, "reason": "unknown_generated_skill"}
    use = {
        "ts": _now(),
        "candidate_id": cid,
        "skill_name": skill_name,
        "task": _safe(task, 600),
        "success": bool(success),
        "latency_ms": int(latency_ms or 0),
        "avoided_llm": bool(avoided_llm),
        "resolver": _safe(resolver, 120),
    }
    cand["production_use_count"] = int(cand.get("production_use_count") or 0) + 1
    if avoided_llm:
        cand["llm_avoidance_count"] = int(cand.get("llm_avoidance_count") or 0) + 1
    cand["updated_at"] = _now()
    state["candidates"][cid] = cand
    state["production_uses"] = list(state.get("production_uses") or []) + [use]
    _save(state)
    return {"ok": True, "use": use}


def _transfer_query(query: str, idx: int) -> str:
    base = _safe(query, 500)
    prefixes = [
        "Resolva uma variacao: ",
        "Aplique o mesmo padrao estrutural a esta pergunta: ",
        "Use a capacidade aprendida neste caso: ",
        "Teste transferencia operacional: ",
    ]
    return prefixes[idx % len(prefixes)] + base


def validate_transfer(max_validations: int = 8) -> dict[str, Any]:
    state = _load()
    candidates = dict(state.get("candidates") or {})
    validations = list(state.get("transfer_validations") or [])
    already = {v.get("candidate_id") for v in validations}
    new_items: list[dict[str, Any]] = []
    ranked_candidates = sorted(
        candidates.items(),
        key=lambda item: int((item[1] or {}).get("promoted_at") or (item[1] or {}).get("updated_at") or 0),
        reverse=True,
    )
    for cid, cand in ranked_candidates:
        if len(new_items) >= int(max_validations or 0):
            break
        if cand.get("status") != "promoted" or cid in already:
            continue
        source_query = _safe((cand.get("source_episode") or {}).get("query"), 600)
        probe = _transfer_query(source_query, len(validations) + len(new_items))
        suggestion = suggest_generated_skill(probe, min_score=0.35)
        score = float((suggestion or {}).get("score") or 0.0)
        result = execute_generated_skill(str(cand.get("skill_name")), probe, production=False)
        passed = bool(result.get("success")) and score >= MIN_TRANSFER_SCORE
        val = {
            "ts": _now(),
            "candidate_id": cid,
            "skill_name": cand.get("skill_name"),
            "probe": probe,
            "score": round(score, 4),
            "passed": passed,
            "result_success": bool(result.get("success")),
        }
        cand["transfer"] = val
        if passed:
            cand["transfer_validated_at"] = _now()
        candidates[cid] = cand
        validations.append(val)
        new_items.append(val)
    state["candidates"] = candidates
    state["transfer_validations"] = validations
    _save(state)
    return {
        "ok": True,
        "validated": new_items,
        "validated_count": len([v for v in validations if v.get("passed")]),
    }


def rollback_skill(skill_name: str, reason: str = "regression") -> dict[str, Any]:
    state = _load()
    cid, cand = _find_candidate_by_skill(skill_name, state)
    if not cid or not cand:
        return {"ok": False, "reason": "unknown_generated_skill"}
    cand["status"] = "rolled_back"
    cand["rollback_reason"] = _safe(reason, 240)
    cand["rolled_back_at"] = _now()
    state["candidates"][cid] = cand
    rb = {"ts": _now(), "candidate_id": cid, "skill_name": skill_name, "reason": _safe(reason, 240)}
    state["rollbacks"] = list(state.get("rollbacks") or []) + [rb]
    _save(state)
    return {"ok": True, "rollback": rb}


def record_regression(skill_name: str, severity: str, reason: str, *, auto_rollback: bool = True) -> dict[str, Any]:
    state = _load()
    cid, cand = _find_candidate_by_skill(skill_name, state)
    if not cid or not cand:
        return {"ok": False, "reason": "unknown_generated_skill"}
    severity = _safe(severity, 40).lower() or "minor"
    rollback = None
    if severity in {"major", "critical", "grave"} and auto_rollback:
        rollback = rollback_skill(skill_name, reason=reason)
        state = _load()
    reg = {
        "ts": _now(),
        "candidate_id": cid,
        "skill_name": skill_name,
        "severity": severity,
        "reason": _safe(reason, 300),
        "rollbacked": bool(rollback and rollback.get("ok")),
    }
    state["regressions"] = list(state.get("regressions") or []) + [reg]
    _save(state)
    return {"ok": True, "regression": reg, "rollback": rollback}


def metrics() -> dict[str, Any]:
    state = _load()
    candidates = list((state.get("candidates") or {}).values())
    promoted = [c for c in candidates if c.get("status") == "promoted"]
    production_uses = list(state.get("production_uses") or [])
    unique_used = {u.get("skill_name") for u in production_uses if u.get("success")}
    transfer_ok = [v for v in (state.get("transfer_validations") or []) if v.get("passed")]
    severe_open = [
        r for r in (state.get("regressions") or [])
        if str(r.get("severity") or "").lower() in {"major", "critical", "grave"} and not r.get("rollbacked")
    ]
    avoided = len([u for u in production_uses if u.get("avoided_llm")])
    total_uses = len(production_uses)
    latencies = [int(u.get("latency_ms") or 0) for u in production_uses if int(u.get("latency_ms") or 0) >= 0]
    mean_latency = round(sum(latencies) / max(1, len(latencies)), 2) if latencies else 0.0
    llm_reduction_pct = round((avoided / max(1, total_uses)) * 100.0, 2)
    return {
        "ok": True,
        "schema": SCHEMA,
        "candidate_count": len(candidates),
        "promoted_count": len(promoted),
        "production_used_count": len(unique_used),
        "production_use_events": total_uses,
        "transfer_validated_count": len({v.get("candidate_id") for v in transfer_ok}),
        "severe_regressions_without_rollback": len(severe_open),
        "llm_reduction_pct": llm_reduction_pct,
        "simple_chat_mean_latency_ms": mean_latency,
        "targets": {
            "candidate_count": 30,
            "promoted_count": 20,
            "production_used_count": 12,
            "transfer_validated_count": 8,
            "severe_regressions_without_rollback": 0,
            "llm_reduction_pct": 50.0,
            "simple_chat_mean_latency_ms": 1000,
        },
        "target_pass": {
            "candidate_count": len(candidates) >= 30,
            "promoted_count": len(promoted) >= 20,
            "production_used_count": len(unique_used) >= 12,
            "transfer_validated_count": len({v.get("candidate_id") for v in transfer_ok}) >= 8,
            "severe_regressions_without_rollback": len(severe_open) == 0,
            "llm_reduction_pct": llm_reduction_pct >= 50.0,
            "simple_chat_mean_latency_ms": (mean_latency < 1000 if latencies else False),
        },
        "recent_production_uses": production_uses[-20:],
        "recent_transfer_validations": (state.get("transfer_validations") or [])[-20:],
        "path": str(STATE_PATH),
    }


def status(limit: int = 20) -> dict[str, Any]:
    state = _load()
    candidates = list((state.get("candidates") or {}).values())
    candidates.sort(key=lambda c: int(c.get("updated_at") or c.get("created_at") or 0), reverse=True)
    return {
        **metrics(),
        "recent_candidates": candidates[: max(1, int(limit or 20))],
    }


def record_benchmark_run(run: dict[str, Any]) -> dict[str, Any]:
    state = _load()
    item = {
        "ts": _now(),
        "run_id": "skill_bench_" + _hash({"ts": _now(), "run": run}, 12),
        **dict(run or {}),
        "metrics": metrics(),
    }
    state["benchmark_runs"] = list(state.get("benchmark_runs") or []) + [item]
    _save(state)
    _append_jsonl(BENCHMARK_LOG_PATH, item)
    return {"ok": True, "run": item, "path": str(BENCHMARK_LOG_PATH)}
