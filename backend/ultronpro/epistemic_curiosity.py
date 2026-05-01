from __future__ import annotations

from dataclasses import dataclass, asdict
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any


DATA_DIR = Path(__file__).resolve().parent.parent / "data"
BACKEND_DIR = DATA_DIR.parent
QUESTION_LOG_PATH = DATA_DIR / "epistemic_curiosity_questions.jsonl"
ACTION_LOG_PATH = DATA_DIR / "epistemic_gap_actions.jsonl"
GAP_SCAN_CACHE_PATH = DATA_DIR / "epistemic_gap_scan_cache.json"
NO_CLOUD_CAMPAIGN_PATH = DATA_DIR / "no_cloud_experiment_campaign.json"
NO_CLOUD_CAMPAIGN_RUNS_PATH = DATA_DIR / "no_cloud_experiment_campaign_runs.jsonl"
NO_CLOUD_CAMPAIGN_STATE_PATH = DATA_DIR / "no_cloud_experiment_campaign_state.json"
CLOUD_ROTATION_CAMPAIGN_PATH = DATA_DIR / "cloud_rotation_contingency_campaign.json"
MAIN_PATH = Path(__file__).resolve().parent / "main.py"
_LAST_GAP_SCAN_META: dict[str, Any] = {}


@dataclass
class EpistemicGap:
    id: str
    label: str
    domain: str
    metric: str
    priority: float
    evidence: dict[str, Any]
    next_experiment: str


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
        rows: list[dict[str, Any]] = []
        for ln in lines[-max(1, int(limit)) :]:
            try:
                item = json.loads(ln)
            except Exception:
                continue
            if isinstance(item, dict):
                rows.append(item)
        return rows
    except Exception:
        return []


def _clip01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _gap_cache_ttl_sec() -> float:
    try:
        return max(0.0, float(os.getenv("ULTRON_EPISTEMIC_GAP_CACHE_TTL_SEC", "15")))
    except Exception:
        return 15.0


def _local_provider_policy() -> str:
    value = str(os.getenv("ULTRON_LOCAL_PROVIDER_POLICY", "cloud_rotation") or "cloud_rotation")
    return value.strip().lower().replace("-", "_")


def _gap_from_dict(item: dict[str, Any]) -> EpistemicGap | None:
    try:
        return EpistemicGap(
            id=str(item.get("id") or ""),
            label=str(item.get("label") or ""),
            domain=str(item.get("domain") or ""),
            metric=str(item.get("metric") or ""),
            priority=float(item.get("priority") or 0.0),
            evidence=item.get("evidence") if isinstance(item.get("evidence"), dict) else {},
            next_experiment=str(item.get("next_experiment") or ""),
        )
    except Exception:
        return None


def _load_gap_cache() -> tuple[list[EpistemicGap], dict[str, Any]] | None:
    global _LAST_GAP_SCAN_META
    ttl = _gap_cache_ttl_sec()
    if ttl <= 0:
        return None
    cached = _read_json(GAP_SCAN_CACHE_PATH, {})
    if not isinstance(cached, dict):
        return None
    age_sec = time.time() - float(cached.get("ts") or 0.0)
    if age_sec < 0 or age_sec > ttl:
        return None
    raw_gaps = cached.get("gaps") if isinstance(cached.get("gaps"), list) else []
    gaps = [gap for gap in (_gap_from_dict(item) for item in raw_gaps if isinstance(item, dict)) if gap]
    meta = dict(cached.get("meta") if isinstance(cached.get("meta"), dict) else {})
    meta.update({"cached": True, "cache_age_sec": round(age_sec, 3), "cache_ttl_sec": ttl})
    _LAST_GAP_SCAN_META = meta
    return gaps, meta


def _save_gap_cache(gaps: list[EpistemicGap], meta: dict[str, Any]) -> None:
    try:
        GAP_SCAN_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        GAP_SCAN_CACHE_PATH.write_text(
            json.dumps({
                "ts": time.time(),
                "meta": meta,
                "gaps": [asdict(g) for g in gaps],
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass


def last_gap_scan_meta() -> dict[str, Any]:
    return dict(_LAST_GAP_SCAN_META)


def _gap(
    *,
    gap_id: str,
    label: str,
    domain: str,
    metric: str,
    severity: float,
    evidence_strength: float,
    recency: float = 1.0,
    evidence: dict[str, Any],
    next_experiment: str,
) -> EpistemicGap:
    priority = (0.50 * _clip01(severity)) + (0.35 * _clip01(evidence_strength)) + (0.15 * _clip01(recency))
    return EpistemicGap(
        id=gap_id,
        label=label,
        domain=domain,
        metric=metric,
        priority=round(priority, 4),
        evidence=evidence,
        next_experiment=next_experiment,
    )


def _latest_hard_eval() -> dict[str, Any]:
    rows = _read_jsonl(DATA_DIR / "hard_cognitive_eval_runs.jsonl", 1)
    return rows[-1] if rows else {}


def _latest_intelligence_suite() -> dict[str, Any]:
    rows = _read_jsonl(DATA_DIR / "intelligence_suite_runs.jsonl", 1)
    return rows[-1] if rows else {}


def _biographic_digest() -> dict[str, Any]:
    try:
        from ultronpro import biographic_digest

        try:
            data = biographic_digest.ensure_recent_digest(max_age_hours=24)
        except TypeError:
            data = biographic_digest.ensure_recent_digest()
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _causal_graph_status() -> dict[str, Any]:
    try:
        from ultronpro import causal_graph

        status = causal_graph.status()
        graph = causal_graph.load_graph()
        edges = [e for e in (graph.get("edges") or {}).values() if isinstance(e, dict)]
        strong = sum(1 for e in edges if str(e.get("knowledge_type") or "") == "interventional_strong")
        weak = sum(1 for e in edges if str(e.get("knowledge_type") or "") == "interventional_weak")
        observational = sum(1 for e in edges if str(e.get("knowledge_type") or "observational") == "observational")
        status.update({
            "interventional_strong_edges": strong,
            "interventional_weak_edges": weak,
            "observational_edges": observational,
        })
        return status
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:160]}


def collect_epistemic_gaps(*, use_cache: bool = True) -> list[EpistemicGap]:
    global _LAST_GAP_SCAN_META
    if use_cache:
        cached = _load_gap_cache()
        if cached is not None:
            return cached[0]

    started = time.perf_counter()
    gaps: list[EpistemicGap] = []

    hard = _latest_hard_eval()
    sections = hard.get("sections") if isinstance(hard.get("sections"), dict) else {}
    external = sections.get("external_benchmark") if isinstance(sections.get("external_benchmark"), dict) else {}
    if external:
        total = max(1, int(external.get("no_cloud_probe_total") or 0))
        correct = int(external.get("no_cloud_probe_correct") or 0)
        accuracy = float(external.get("no_cloud_probe_accuracy") or 0.0)
        if accuracy < 0.8:
            provider_policy = _local_provider_policy()
            if provider_policy in {"cloud_rotation", "cloud", "cloud_only", "disabled", "no_local"}:
                gaps.append(_gap(
                    gap_id="structured_reasoning_cloud_contingency",
                    label="contingencia de linguagem por rotacao cloud",
                    domain="language_interface_resilience",
                    metric=f"no_cloud_probe={correct}/{total} accuracy={accuracy} policy={provider_policy}",
                    severity=min(0.55, 0.30 + (1.0 - accuracy) * 0.20),
                    evidence_strength=0.82,
                    evidence={
                        "hard_eval_ts": hard.get("ts"),
                        "external_benchmark": external,
                        "local_provider_policy": provider_policy,
                    },
                    next_experiment=(
                        "validar que o nucleo estruturado decide primeiro e que cloud rotation atua apenas "
                        "como verbalizador/fallback quando a investigacao ativa precisar de linguagem"
                    ),
                ))
            else:
                gaps.append(_gap(
                    gap_id="local_inference_no_cloud",
                    label="independencia local de LLM externo",
                    domain="llm_off_survival",
                    metric=f"no_cloud_probe={correct}/{total} accuracy={accuracy}",
                    severity=1.0 - accuracy,
                    evidence_strength=0.92,
                    evidence={"hard_eval_ts": hard.get("ts"), "external_benchmark": external},
                    next_experiment="rodar benchmark no-cloud com infer local ativo e comparar contra oracle",
                ))

    guard = _read_json(DATA_DIR / "background_guard.json", {})
    if isinstance(guard, dict) and (guard.get("paused") or float(guard.get("max_lag_sec") or 0.0) >= 5.0):
        max_lag = float(guard.get("max_lag_sec") or 0.0)
        blocked = int(guard.get("blocked_loops") or 0)
        gaps.append(_gap(
            gap_id="background_loop_pressure",
            label="estabilidade dos loops sob carga",
            domain="runtime_lifecycle",
            metric=f"paused={guard.get('paused')} reason={guard.get('last_pause_reason')} max_lag={max_lag}s blocked_loops={blocked}",
            severity=min(1.0, max_lag / 60.0),
            evidence_strength=0.88 if blocked > 0 else 0.72,
            evidence={"background_guard": guard},
            next_experiment="medir custo por loop e aplicar budget adaptativo sem desligar loops essenciais",
        ))

    sleep = _read_json(DATA_DIR / "sleep_cycle_report.json", {})
    if isinstance(sleep, dict):
        abstracted = int(sleep.get("abstracted") or 0)
        active = int(sleep.get("active_after") or 0)
        min_group = int(sleep.get("min_group_episodes") or 3)
        if abstracted <= 1 or active < (min_group * 10):
            gaps.append(_gap(
                gap_id="episodic_abstraction_density",
                label="densidade de abstracoes episodicas reutilizaveis",
                domain="biographic_digest",
                metric=f"abstracted={abstracted} active_after={active} min_group_episodes={min_group}",
                severity=0.70 if abstracted == 0 else 0.48,
                evidence_strength=0.80,
                evidence={"sleep_cycle": sleep},
                next_experiment="semear episodios por dominio e verificar se o sleep_cycle compila skills reutilizaveis",
            ))

    graph = _causal_graph_status()
    if graph:
        edges = int(graph.get("edges") or 0)
        strong = int(graph.get("interventional_strong_edges") or 0)
        weak = int(graph.get("interventional_weak_edges") or 0)
        if edges < 80 or strong == 0:
            severity = 0.82 if strong == 0 else max(0.25, (80 - edges) / 80.0)
            gaps.append(_gap(
                gap_id="causal_graph_interventional_coverage",
                label="cobertura interventional do grafo causal",
                domain="causal_graph",
                metric=f"edges={edges} strong={strong} weak={weak}",
                severity=severity,
                evidence_strength=0.78,
                evidence={"causal_graph": graph},
                next_experiment="converter decisoes e benchmarks recentes em arestas causais com validacao interventional",
            ))

    digest = _biographic_digest()
    tensions = digest.get("open_tensions") if isinstance(digest.get("open_tensions"), list) else []
    if tensions:
        gaps.append(_gap(
            gap_id="biographic_open_tension",
            label="tensao aberta no digest biografico",
            domain="self_model",
            metric=str(tensions[0])[:240],
            severity=0.62,
            evidence_strength=0.74,
            evidence={"digest_day": digest.get("day"), "checksum": digest.get("checksum"), "open_tension": tensions[0]},
            next_experiment="transformar a tensao principal do digest em tarefa mensuravel com criterio de fechamento",
        ))

    suite = _latest_intelligence_suite()
    if suite and not bool(suite.get("ok")):
        score = float(suite.get("score_0_10") or 0.0)
        gaps.append(_gap(
            gap_id="intelligence_suite_regression",
            label="regressao na suite de inteligencia",
            domain="intelligence_suite",
            metric=f"score={score}/10 passed={suite.get('passed')}/{suite.get('total')}",
            severity=max(0.0, (7.5 - score) / 7.5),
            evidence_strength=0.95,
            evidence={"intelligence_suite": {k: suite.get(k) for k in ("ts", "score_0_10", "passed", "total", "threshold")}},
            next_experiment="rodar casos que falharam e comparar rota/conteudo contra ultimo run verde",
        ))

    gaps.sort(key=lambda g: g.priority, reverse=True)
    meta = {
        "cached": False,
        "scan_ms": round((time.perf_counter() - started) * 1000.0, 2),
        "gap_count": len(gaps),
        "cache_ttl_sec": _gap_cache_ttl_sec(),
    }
    _LAST_GAP_SCAN_META = meta
    _save_gap_cache(gaps, meta)
    return gaps


def _render_question(top: EpistemicGap, second: EpistemicGap | None) -> str:
    if second and second.priority >= (top.priority - 0.12):
        return (
            f"voce quer que eu priorize {top.label} ({top.metric}) "
            f"ou {second.label} ({second.metric})?"
        )
    return (
        f"qual experimento voce quer que eu rode primeiro para reduzir a lacuna "
        f"{top.label} ({top.metric})?"
    )


def _record_question(payload: dict[str, Any]) -> None:
    try:
        QUESTION_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with QUESTION_LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _record_action(payload: dict[str, Any]) -> None:
    try:
        ACTION_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with ACTION_LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _append_campaign_run(payload: dict[str, Any]) -> None:
    try:
        NO_CLOUD_CAMPAIGN_RUNS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with NO_CLOUD_CAMPAIGN_RUNS_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _write_campaign_state(payload: dict[str, Any]) -> None:
    try:
        NO_CLOUD_CAMPAIGN_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        NO_CLOUD_CAMPAIGN_STATE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _latest_campaign_run() -> dict[str, Any]:
    rows = _read_jsonl(NO_CLOUD_CAMPAIGN_RUNS_PATH, 1)
    return rows[-1] if rows else {}


def _register_in_causal_graph(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        from ultronpro import causal_graph

        top = payload.get("top_gap") if isinstance(payload.get("top_gap"), dict) else {}
        question = str(payload.get("question") or "")
        return causal_graph.upsert_edge(
            cause=f"epistemic_gap:{top.get('id') or top.get('label') or 'unknown'}",
            effect=f"curiosity_question:{question[:180]}",
            condition="project_question_g2",
            evidence={
                "source": "epistemic_curiosity",
                "top_gap": top,
                "second_gap": payload.get("second_gap"),
                "selected_at": payload.get("ts"),
            },
            confidence=0.74,
            source="epistemic_curiosity",
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:160]}


def _register_action_in_causal_graph(gap: EpistemicGap, action: dict[str, Any]) -> dict[str, Any]:
    try:
        from ultronpro import causal_graph

        try:
            action_snapshot = json.loads(json.dumps(action, ensure_ascii=False, default=str))
        except Exception:
            action_snapshot = {
                "kind": str(action.get("kind") or "unknown"),
                "status": str(action.get("status") or "unknown"),
                "summary": str(action.get("summary") or "")[:400],
            }
        return causal_graph.upsert_edge(
            cause=f"epistemic_gap:{gap.id}",
            effect=f"gap_action:{str(action.get('kind') or action.get('status') or 'unknown')[:160]}",
            condition="epistemic_gap_action_runner",
            evidence={
                "source": "epistemic_curiosity",
                "gap": asdict(gap),
                "action": action_snapshot,
                "ts": int(time.time()),
            },
            confidence=0.76,
            source="epistemic_gap_action_runner",
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:160]}


def _runtime_intervention_present() -> bool:
    try:
        text = MAIN_PATH.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return False
    markers = (
        "ULTRON_AUTOFEEDER_FETCH_TIMEOUT_SEC",
        "_autofeeder_call_with_budget",
        "ULTRON_AUTOFEEDER_EXTRACT_TIMEOUT_SEC",
        "ULTRON_AUTOFEEDER_RAG_TIMEOUT_SEC",
        "ULTRON_AUTOFEEDER_LIGHTRAG_TIMEOUT_SEC",
    )
    return all(marker in text for marker in markers)


def _ensure_no_cloud_campaign(gap: EpistemicGap) -> dict[str, Any]:
    campaign = {
        "ok": True,
        "campaign": "local_inference_no_cloud_recovery",
        "status": "started",
        "created_at": int(time.time()),
        "source_gap": asdict(gap),
        "acceptance_criteria": {
            "minimal": "external benchmark no_cloud_probe >= 2/3 without cloud providers",
            "target": "no_cloud_probe accuracy >= 0.80 over expanded proxy suite",
            "hard_suite_guard": "UltronPro Intelligence Test Suite remains >= 7.5 and >= 11/13",
        },
        "experiments": [
            {
                "id": "health_ultron_infer",
                "provider": "ultron_infer",
                "probe": "GET /health and 1 JSON MCQ generation",
                "risk": "low",
            },
            {
                "id": "health_ollama_local",
                "provider": "ollama_local",
                "probe": "tags/list plus 1 JSON MCQ generation when enabled",
                "risk": "low",
            },
            {
                "id": "external_proxy_no_cloud",
                "provider": "best_available_local",
                "probe": "external_public_eval_v1 limit_per_benchmark=1 predictor=llm strategy=local",
                "risk": "low",
            },
            {
                "id": "llm_off_survival",
                "provider": "best_available_local",
                "probe": "llm_off_survival_v1 S01-S03",
                "risk": "low",
            },
        ],
        "next_action": "executar probes locais e promover o provider que atingir o criterio minimal",
    }
    try:
        previous = _read_json(NO_CLOUD_CAMPAIGN_PATH, {})
        if isinstance(previous, dict) and previous.get("campaign") == campaign["campaign"]:
            campaign["created_at"] = previous.get("created_at") or campaign["created_at"]
            campaign["status"] = previous.get("status") or campaign["status"]
        NO_CLOUD_CAMPAIGN_PATH.parent.mkdir(parents=True, exist_ok=True)
        NO_CLOUD_CAMPAIGN_PATH.write_text(json.dumps(campaign, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        campaign["ok"] = False
        campaign["error"] = str(exc)[:160]
    return campaign


def _ensure_cloud_rotation_contingency(gap: EpistemicGap) -> dict[str, Any]:
    campaign = {
        "ok": True,
        "campaign": "structured_reasoning_cloud_contingency",
        "status": "planned",
        "created_at": int(time.time()),
        "source_gap": asdict(gap),
        "policy": _local_provider_policy(),
        "principle": "structured reasoning is the source of decisions; cloud providers are language/interface capacity only",
        "acceptance_criteria": {
            "routing": "structured modules or active investigation run before any cloud verbalizer",
            "fallback": "cloud rotation is used only after evidence coverage is measured insufficient",
            "traceability": "response trace includes module, investigation id or evidence source",
        },
        "experiments": [
            {
                "id": "structured_gap_active_investigation",
                "probe": "ask an under-covered question and verify non_llm_active_investigation before LLM fallback",
                "risk": "low",
            },
            {
                "id": "cloud_rotation_language_surface",
                "probe": "verify provider rotation remains available for language formatting when explicitly needed",
                "risk": "low",
            },
            {
                "id": "intelligence_suite_guard",
                "probe": "UltronPro Intelligence Test Suite remains >= 7.5 and >= 11/13",
                "risk": "low",
            },
        ],
        "next_action": "executar probe de investigacao ativa e confirmar que a cloud nao virou arbitro cognitivo",
    }
    try:
        previous = _read_json(CLOUD_ROTATION_CAMPAIGN_PATH, {})
        if isinstance(previous, dict) and previous.get("campaign") == campaign["campaign"]:
            campaign["created_at"] = previous.get("created_at") or campaign["created_at"]
            campaign["status"] = previous.get("status") or campaign["status"]
        CLOUD_ROTATION_CAMPAIGN_PATH.parent.mkdir(parents=True, exist_ok=True)
        CLOUD_ROTATION_CAMPAIGN_PATH.write_text(json.dumps(campaign, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        campaign["ok"] = False
        campaign["error"] = str(exc)[:160]
    return campaign


def _no_cloud_campaign_cooldown_sec() -> float:
    try:
        return max(0.0, float(os.getenv("ULTRON_NO_CLOUD_CAMPAIGN_COOLDOWN_SEC", "3600")))
    except Exception:
        return 3600.0


def _no_cloud_probe_env() -> dict[str, str]:
    env = dict(os.environ)
    current_path = str(env.get("PYTHONPATH") or "")
    env["PYTHONPATH"] = str(BACKEND_DIR) if not current_path else str(BACKEND_DIR) + os.pathsep + current_path
    env["PYTHONIOENCODING"] = "utf-8"
    env["BENCHMARK_MODE"] = "1"
    env["ULTRON_DISABLE_CLOUD_PROVIDERS"] = "1"
    for name in (
        "ULTRON_DISABLE_HUGGINGFACE",
        "ULTRON_DISABLE_OPENROUTER",
        "ULTRON_DISABLE_GROQ",
        "ULTRON_DISABLE_DEEPSEEK",
        "ULTRON_DISABLE_OPENAI",
        "ULTRON_DISABLE_ANTHROPIC",
        "ULTRON_DISABLE_GEMINI",
        "ULTRON_DISABLE_NVIDIA",
        "ULTRON_DISABLE_GITHUB_MODELS",
        "ULTRON_DISABLE_OLLAMA_CLOUD",
    ):
        env[name] = "1"
    env.setdefault("ULTRON_LLM_COMPAT_TIMEOUT_SEC", "8")
    env.setdefault("ULTRON_LLM_ROUTER_TIMEOUT_SEC", "10")
    env.setdefault("ULTRON_OLLAMA_TIMEOUT_SEC", "18")
    env.setdefault("ULTRON_LOCAL_INFER_TIMEOUT_SEC", "12")
    env.setdefault("ULTRON_COGNITIVE_RESPONSE_TIMEOUT_SEC", "20")
    env.setdefault("ULTRON_SKILL_EXEC_TIMEOUT_SEC", "8")
    return env


def _extract_probe_json(stdout: str) -> dict[str, Any]:
    marker = "__NO_CLOUD_JSON__"
    for line in reversed(str(stdout or "").splitlines()):
        text = line.strip()
        if not text:
            continue
        if text.startswith(marker):
            text = text[len(marker):].strip()
        try:
            value = json.loads(text)
            return value if isinstance(value, dict) else {"value": value}
        except Exception:
            continue
    return {}


def _run_no_cloud_python_probe(probe_id: str, code: str, *, timeout_sec: float) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        proc = subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(BACKEND_DIR),
            env=_no_cloud_probe_env(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(1.0, float(timeout_sec)),
        )
        data = _extract_probe_json(proc.stdout)
        return {
            "id": probe_id,
            "ok": proc.returncode == 0 and bool(data.get("ok", bool(data))),
            "returncode": proc.returncode,
            "duration_sec": round(time.perf_counter() - started, 3),
            "data": data,
            "stdout_tail": str(proc.stdout or "")[-1200:],
            "stderr_tail": str(proc.stderr or "")[-1200:],
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "id": probe_id,
            "ok": False,
            "timeout": True,
            "duration_sec": round(time.perf_counter() - started, 3),
            "error": f"timeout after {timeout_sec}s",
            "stdout_tail": str(exc.stdout or "")[-1200:],
            "stderr_tail": str(exc.stderr or "")[-1200:],
        }
    except Exception as exc:
        return {
            "id": probe_id,
            "ok": False,
            "duration_sec": round(time.perf_counter() - started, 3),
            "error": str(exc)[:500],
        }


def _run_no_cloud_probe(probe_id: str) -> dict[str, Any]:
    marker = "__NO_CLOUD_JSON__"
    if probe_id == "health_ultron_infer":
        code = (
            "import json\n"
            "from ultronpro import llm\n"
            "r = llm.healthcheck('ultron_infer')\n"
            f"print('{marker}' + json.dumps(r, ensure_ascii=False))\n"
        )
        return _run_no_cloud_python_probe(probe_id, code, timeout_sec=20)
    if probe_id == "health_ollama_local":
        code = (
            "import json\n"
            "from ultronpro import llm\n"
            "r = llm.healthcheck('ollama_local')\n"
            f"print('{marker}' + json.dumps(r, ensure_ascii=False))\n"
        )
        return _run_no_cloud_python_probe(probe_id, code, timeout_sec=30)
    if probe_id == "external_proxy_no_cloud":
        code = (
            "import json\n"
            "from ultronpro import external_benchmarks\n"
            "r = external_benchmarks.run_suite(limit_per_benchmark=1, predictor='llm', strategy='local', tag='no_cloud_campaign')\n"
            f"print('{marker}' + json.dumps(r, ensure_ascii=False))\n"
        )
        return _run_no_cloud_python_probe(
            probe_id,
            code,
            timeout_sec=float(os.getenv("ULTRON_NO_CLOUD_EXTERNAL_TIMEOUT_SEC", "90") or 90),
        )
    if probe_id == "llm_off_survival":
        code = (
            "import json\n"
            "from pathlib import Path\n"
            "from ultronpro.benchmarks.llm_off_survival import run_survival_test, BACKEND_DIR\n"
            "run_survival_test()\n"
            "path = Path(BACKEND_DIR) / 'data' / 'benchmark_llm_off.json'\n"
            "r = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'ok': False, 'error': 'report_missing'}\n"
            "r['ok'] = float(r.get('survival_rate') or 0.0) >= 0.67\n"
            f"print('{marker}' + json.dumps(r, ensure_ascii=False))\n"
        )
        return _run_no_cloud_python_probe(
            probe_id,
            code,
            timeout_sec=float(os.getenv("ULTRON_NO_CLOUD_SURVIVAL_TIMEOUT_SEC", "120") or 120),
        )
    if probe_id == "hard_suite_guard":
        code = (
            "import asyncio, json\n"
            "from ultronpro.benchmarks.intelligence_test_suite import run_intelligence_suite\n"
            "r = asyncio.run(run_intelligence_suite())\n"
            f"print('{marker}' + json.dumps(r, ensure_ascii=False))\n"
        )
        return _run_no_cloud_python_probe(
            probe_id,
            code,
            timeout_sec=float(os.getenv("ULTRON_NO_CLOUD_GUARD_TIMEOUT_SEC", "90") or 90),
        )
    return {"id": probe_id, "ok": False, "error": "unknown_probe"}


def _campaign_acceptance(probes: list[dict[str, Any]]) -> dict[str, Any]:
    by_id = {str(p.get("id") or ""): p for p in probes}
    external = ((by_id.get("external_proxy_no_cloud") or {}).get("data") or {})
    guard = ((by_id.get("hard_suite_guard") or {}).get("data") or {})
    survival = ((by_id.get("llm_off_survival") or {}).get("data") or {})
    total = int(external.get("total") or 0)
    correct = int(external.get("correct") or 0)
    accuracy = float(external.get("overall_accuracy") or 0.0)
    guard_score = float(guard.get("score_0_10") or 0.0)
    guard_passed = int(guard.get("passed") or 0)
    guard_total = int(guard.get("total") or 13)
    minimal = total >= 3 and correct >= 2
    target = total > 0 and accuracy >= 0.80
    hard_guard = bool(guard.get("ok")) and guard_score >= 7.5 and guard_passed >= min(11, guard_total)
    survival_rate = float(survival.get("survival_rate") or 0.0)
    return {
        "minimal_passed": bool(minimal),
        "target_passed": bool(target),
        "hard_suite_guard_passed": bool(hard_guard),
        "external_no_cloud": {
            "total": total,
            "correct": correct,
            "accuracy": round(accuracy, 4),
            "run_id": external.get("run_id"),
        },
        "llm_off_survival_rate": round(survival_rate, 4),
        "health": {
            "ultron_infer": bool((by_id.get("health_ultron_infer") or {}).get("ok")),
            "ollama_local": bool((by_id.get("health_ollama_local") or {}).get("ok")),
        },
        "accepted": bool((minimal or target) and hard_guard),
    }


def _register_campaign_result_in_causal_graph(report: dict[str, Any]) -> dict[str, Any]:
    try:
        from ultronpro import causal_graph

        acceptance = report.get("acceptance") if isinstance(report.get("acceptance"), dict) else {}
        accepted = bool(acceptance.get("accepted"))
        minimal = bool(acceptance.get("minimal_passed"))
        category = "confirmed" if accepted or minimal else "refuted"
        effect = "local_inference_no_cloud_viable" if accepted else ("local_inference_no_cloud_partial" if minimal else "local_inference_no_cloud_unmet")
        return causal_graph.apply_delta_update(
            cause="epistemic_gap:local_inference_no_cloud",
            effect=f"campaign_result:{effect}",
            condition="no_cloud_experiment_campaign",
            category=category,
            evidence={
                "run_id": report.get("run_id"),
                "status": report.get("status"),
                "acceptance": acceptance,
                "probe_count": len(report.get("probes") or []),
                "duration_sec": report.get("duration_sec"),
            },
            source="no_cloud_campaign_runner",
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200]}


def run_no_cloud_experiment_campaign(*, force: bool = False, include_guard: bool = True) -> dict[str, Any]:
    campaign = _read_json(NO_CLOUD_CAMPAIGN_PATH, {})
    if not isinstance(campaign, dict) or campaign.get("campaign") != "local_inference_no_cloud_recovery":
        return {"ok": False, "status": "missing_campaign", "path": str(NO_CLOUD_CAMPAIGN_PATH)}

    now = int(time.time())
    provider_policy = _local_provider_policy()
    allow_local_probes = str(os.getenv("ULTRON_NO_CLOUD_FORCE_LOCAL_PROBES", "0")).strip().lower() in {"1", "true", "yes", "on"}
    if provider_policy in {"cloud_rotation", "cloud", "cloud_only", "disabled", "no_local"} and not allow_local_probes:
        report = {
            "ok": True,
            "status": "skipped_policy_cloud_rotation",
            "ts": now,
            "campaign": campaign.get("campaign"),
            "local_provider_policy": provider_policy,
            "forced": bool(force),
            "reason": "local providers disabled by resource policy; use cloud rotation only as language/interface fallback",
        }
        _write_campaign_state(report)
        return report

    latest = _latest_campaign_run()
    cooldown = _no_cloud_campaign_cooldown_sec()
    if not force and latest:
        age = now - int(latest.get("ts") or 0)
        if age >= 0 and age < cooldown:
            return {
                "ok": True,
                "status": "skipped_cooldown",
                "cooldown_sec": cooldown,
                "age_sec": age,
                "latest": {k: latest.get(k) for k in ("run_id", "status", "ts", "acceptance")},
            }

    run_id = f"nocc_{uuid.uuid4().hex[:10]}"
    state = {
        "ok": True,
        "status": "running",
        "run_id": run_id,
        "started_at": now,
        "campaign": campaign.get("campaign"),
    }
    _write_campaign_state(state)

    started = time.perf_counter()
    experiments = campaign.get("experiments") if isinstance(campaign.get("experiments"), list) else []
    probe_ids = [str(item.get("id") or "") for item in experiments if isinstance(item, dict) and item.get("id")]
    if include_guard and "hard_suite_guard" not in probe_ids:
        probe_ids.append("hard_suite_guard")

    probes: list[dict[str, Any]] = []
    for probe_id in probe_ids:
        probes.append(_run_no_cloud_probe(probe_id))

    acceptance = _campaign_acceptance(probes)
    if acceptance.get("accepted"):
        status = "accepted"
    elif acceptance.get("minimal_passed"):
        status = "minimal_passed"
    else:
        status = "needs_local_inference"

    report = {
        "ok": True,
        "run_id": run_id,
        "ts": int(time.time()),
        "campaign": campaign.get("campaign"),
        "status": status,
        "duration_sec": round(time.perf_counter() - started, 3),
        "no_cloud_enforced": True,
        "acceptance": acceptance,
        "probes": probes,
    }
    report["causal_graph_registration"] = _register_campaign_result_in_causal_graph(report)
    _append_campaign_run(report)

    campaign["status"] = status
    campaign["last_run_id"] = run_id
    campaign["last_run_at"] = report["ts"]
    campaign["last_acceptance"] = acceptance
    if status == "accepted":
        campaign["closed_at"] = report["ts"]
    try:
        NO_CLOUD_CAMPAIGN_PATH.write_text(json.dumps(campaign, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

    final_state = {
        "ok": True,
        "status": status,
        "run_id": run_id,
        "finished_at": report["ts"],
        "duration_sec": report["duration_sec"],
        "acceptance": acceptance,
    }
    _write_campaign_state(final_state)
    return report


def run_gap_action_cycle(*, execute_low_risk: bool = True, gaps: list[EpistemicGap] | None = None) -> dict[str, Any]:
    gaps = gaps if gaps is not None else collect_epistemic_gaps()
    actions: list[dict[str, Any]] = []
    needs_decision: list[dict[str, Any]] = []

    for gap in gaps[:5]:
        action: dict[str, Any] | None = None
        if gap.id == "background_loop_pressure":
            present = _runtime_intervention_present()
            action = {
                "gap_id": gap.id,
                "kind": "runtime_intervention",
                "risk": "low",
                "status": "applied" if present else "pending_code_patch",
                "summary": (
                    "autofeeder_loop fetch/extract/RAG paths are budgeted with to_thread + asyncio.wait_for; "
                    "loops remain enabled and future ticks should skip before piling onto lag"
                ),
                "verification_needed": "restart server or wait for next autofeeder tick, then compare max_lag_sec and blocked_loops delta",
                "evidence": gap.evidence,
            }
            if not present:
                needs_decision.append({
                    "gap_id": gap.id,
                    "reason": "runtime intervention code marker not present",
                    "risk": "medium_without_patch",
                })
        elif gap.id == "local_inference_no_cloud":
            campaign = _ensure_no_cloud_campaign(gap) if execute_low_risk else {"ok": False, "status": "dry_run"}
            latest_campaign = _latest_campaign_run()
            action = {
                "gap_id": gap.id,
                "kind": "no_cloud_campaign",
                "risk": "low",
                "status": "started" if campaign.get("ok") else "planned",
                "summary": "created/scheduled a local-inference recovery campaign with provider health probes and no-cloud benchmark acceptance criteria",
                "artifact": str(NO_CLOUD_CAMPAIGN_PATH),
                "scheduler": "no_cloud_campaign_loop",
                "latest_run": {k: latest_campaign.get(k) for k in ("run_id", "status", "ts", "acceptance")} if latest_campaign else None,
                "acceptance_criteria": campaign.get("acceptance_criteria"),
                "evidence": gap.evidence,
            }
        elif gap.id == "structured_reasoning_cloud_contingency":
            campaign = _ensure_cloud_rotation_contingency(gap) if execute_low_risk else {"ok": False, "status": "dry_run"}
            action = {
                "gap_id": gap.id,
                "kind": "cloud_rotation_contingency",
                "risk": "low",
                "status": "planned",
                "summary": (
                    "local providers are out of scope by resource policy; validate cloud rotation as a language "
                    "surface while structured reasoning and active investigation remain the cognitive source"
                ),
                "artifact": str(CLOUD_ROTATION_CAMPAIGN_PATH),
                "acceptance_criteria": campaign.get("acceptance_criteria"),
                "evidence": gap.evidence,
            }
        elif gap.id == "causal_graph_interventional_coverage":
            action = {
                "gap_id": gap.id,
                "kind": "causal_graph_enrichment_plan",
                "risk": "low",
                "status": "planned",
                "summary": "convert benchmark decisions and runtime interventions into interventional causal edges after validation",
                "next_experiment": gap.next_experiment,
                "evidence": gap.evidence,
            }
        elif gap.id in {"episodic_abstraction_density", "biographic_open_tension"}:
            action = {
                "gap_id": gap.id,
                "kind": "evidence_collection_plan",
                "risk": "low",
                "status": "planned",
                "summary": gap.next_experiment,
                "evidence": gap.evidence,
            }

        if action:
            action["causal_graph_registration"] = _register_action_in_causal_graph(gap, action)
            actions.append(action)

    report = {
        "ok": True,
        "ts": int(time.time()),
        "source": "epistemic_curiosity.gap_action_cycle",
        "execute_low_risk": bool(execute_low_risk),
        "gap_scan": last_gap_scan_meta(),
        "gaps_considered": [asdict(g) for g in gaps[:5]],
        "actions": actions,
        "needs_decision": needs_decision,
    }
    _record_action(report)
    return report


def generate_project_question(*, gaps: list[EpistemicGap] | None = None) -> dict[str, Any]:
    gaps = gaps if gaps is not None else collect_epistemic_gaps()
    if not gaps:
        payload = {
            "ok": False,
            "reason": "no_ranked_gaps",
            "question": "qual lacuna operacional voce quer que eu investigue primeiro?",
            "ts": int(time.time()),
            "gaps": [],
        }
        _record_question(payload)
        return payload

    top = gaps[0]
    second = gaps[1] if len(gaps) > 1 else None
    payload = {
        "ok": True,
        "source": "epistemic_curiosity.causal_gap_scorer",
        "question": _render_question(top, second),
        "top_gap": asdict(top),
        "second_gap": asdict(second) if second else None,
        "ranked_gaps": [asdict(g) for g in gaps[:5]],
        "gap_scan": last_gap_scan_meta(),
        "ts": int(time.time()),
    }
    payload["causal_graph_registration"] = _register_in_causal_graph(payload)
    _record_question(payload)
    return payload


def generate_project_gap_report() -> dict[str, Any]:
    started = time.perf_counter()
    gaps = collect_epistemic_gaps()
    question = generate_project_question(gaps=gaps)
    action_report = run_gap_action_cycle(execute_low_risk=True, gaps=gaps)
    actions = action_report.get("actions") if isinstance(action_report.get("actions"), list) else []
    applied = [a for a in actions if str(a.get("status") or "") in {"applied", "started"}]
    planned = [a for a in actions if str(a.get("status") or "") == "planned"]
    needs = action_report.get("needs_decision") if isinstance(action_report.get("needs_decision"), list) else []
    return {
        "ok": True,
        "ts": int(time.time()),
        "source": "epistemic_curiosity.closed_loop_report",
        "question": question,
        "action_report": action_report,
        "gap_scan": last_gap_scan_meta(),
        "duration_ms": round((time.perf_counter() - started) * 1000.0, 2),
        "applied_count": len(applied),
        "planned_count": len(planned),
        "needs_decision_count": len(needs),
    }
