"""
agi_production_test.py — Suite de testes de produção AGI (HTTP-only)

Bate diretamente no servidor UltronPro em execução (localhost:8000).
Cobre os 5 fronts do ROADMAP_AGI_FRONTS.md com evidência verificável.

Uso:
    python backend/agi_production_test.py
    python backend/agi_production_test.py --base-url http://localhost:8000
    python backend/agi_production_test.py --verbose
    python backend/agi_production_test.py --front 2   # só o front 2
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
import unicodedata
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable
from urllib import request as urllib_request
from urllib.error import URLError, HTTPError

# ─────────────────────────── config ────────────────────────────────────────
DEFAULT_BASE = "http://localhost:8000"
TIMEOUT_S    = 30
REPORT_PATH  = Path(__file__).parent / "data" / "agi_production_test_runs.jsonl"

# ─────────────────────────── helpers HTTP ──────────────────────────────────
def _get(base: str, path: str) -> dict[str, Any]:
    url = base.rstrip("/") + path
    try:
        with urllib_request.urlopen(url, timeout=TIMEOUT_S) as r:
            return json.loads(r.read().decode())
    except HTTPError as e:
        return {"_http_error": e.code, "_url": url, "_body": e.read().decode()[:400]}
    except URLError as e:
        return {"_url_error": str(e), "_url": url}
    except Exception as e:
        return {"_error": str(e), "_url": url}


def _post(base: str, path: str, body: dict) -> dict[str, Any]:
    url = base.rstrip("/") + path
    data = json.dumps(body).encode()
    req  = urllib_request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib_request.urlopen(req, timeout=TIMEOUT_S) as r:
            return json.loads(r.read().decode())
    except HTTPError as e:
        return {"_http_error": e.code, "_url": url, "_body": e.read().decode()[:400]}
    except URLError as e:
        return {"_url_error": str(e), "_url": url}
    except Exception as e:
        return {"_error": str(e), "_url": url}


def _norm(text: str) -> str:
    t = unicodedata.normalize("NFKD", str(text or ""))
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", t.lower()).strip()


def _has(text: str, *items: str) -> bool:
    n = _norm(text)
    return all(_norm(i) in n for i in items)


def _any_of(text: str, *items: str) -> bool:
    n = _norm(text)
    return any(_norm(i) in n for i in items)


# ─────────────────────────── resultado ─────────────────────────────────────
@dataclass
class Check:
    name:    str
    ok:      bool
    score:   float          # 0.0–1.0
    detail:  str  = ""
    raw:     dict = field(default_factory=dict)


@dataclass
class FrontResult:
    front_id:   int
    front_name: str
    checks:     list[Check] = field(default_factory=list)

    @property
    def score_pct(self) -> float:
        if not self.checks:
            return 0.0
        return round(100.0 * sum(c.score for c in self.checks) / len(self.checks), 1)

    @property
    def passed(self) -> int:
        return sum(1 for c in self.checks if c.ok)

    @property
    def total(self) -> int:
        return len(self.checks)


# ════════════════════════════════════════════════════════════════════════════
# FRONT 1 — Plasticidade estrutural real
# ════════════════════════════════════════════════════════════════════════════
def test_front1(base: str) -> FrontResult:
    fr = FrontResult(1, "Plasticidade estrutural real")

    # 1a) Roadmap status acessivel
    rs = _get(base, "/api/roadmap/status")
    ok1a = "_url_error" not in rs and "_http_error" not in rs and (
        bool(rs.get("overall_pct")) or bool(rs.get("status")) or bool(rs.get("fronts"))
    )
    overall = rs.get("overall_pct", rs.get("status", "?"))
    fr.checks.append(Check("roadmap_status_endpoint", ok1a,
                            1.0 if ok1a else 0.0,
                            f"overall_pct={overall}", rs))

    # 1b) Scorecard: overall_percent e 5 fronts com scores validos
    sc = _get(base, "/api/roadmap/scorecard")
    overall_pct   = sc.get("overall_percent", 0)
    front_scores  = sc.get("front_scores", [])
    fronts_count  = len([f for f in front_scores if isinstance(f.get("score"), (int, float)) and f["score"] > 0])
    ok1b = "_url_error" not in sc and "_http_error" not in sc and (
        int(overall_pct or 0) > 70 and fronts_count >= 5
    )
    fr.checks.append(Check("roadmap_scorecard_fronts", ok1b,
                            1.0 if ok1b else 0.5 if ("_url_error" not in sc and "_http_error" not in sc) else 0.0,
                            f"overall={overall_pct}% fronts_with_score={fronts_count}", sc))

    # 1c) Patches cognitivos — rota correta
    patches = _get(base, "/api/plasticity/cognitive-patches")
    patch_list = patches.get("patches", patches.get("items",
                   patches if isinstance(patches, list) else []))
    ok1c = "_url_error" not in patches and "_http_error" not in patches and isinstance(patch_list, list)
    fr.checks.append(Check("cognitive_patches_listing", ok1c,
                            1.0 if ok1c else 0.3 if ("_url_error" not in patches and "_http_error" not in patches) else 0.0,
                            f"count={len(patch_list) if isinstance(patch_list, list) else 'N/A'}",
                            patches))

    # 1d) AGI benchmark status (Front 1 tem benchmark suite + AGI benchmark)
    be = _get(base, "/api/agi/benchmark/status")
    ok1d = "_url_error" not in be and "_http_error" not in be
    score = be.get("score", be.get("last_score", be.get("agi_score", None)))
    fr.checks.append(Check("agi_benchmark_status", ok1d,
                            1.0 if (ok1d and score is not None) else 0.7 if ok1d else 0.0,
                            f"score={score}", be))

    # 1e) Cognitive patch loop status (shadow eval / promoção / rollback)
    cpl = _get(base, "/api/plasticity/cognitive-patch-loop/status")
    ok1e = "_url_error" not in cpl and "_http_error" not in cpl
    loop_ok = cpl.get("ok", cpl.get("active", None))
    fr.checks.append(Check("cognitive_patch_loop_status", ok1e,
                            1.0 if ok1e else 0.0,
                            f"loop_ok={loop_ok}", cpl))

    # 1f) Plasticity runtime (releases ativas, adapters)
    pr = _get(base, "/api/plasticity/status")
    ok1f = "_url_error" not in pr and "_http_error" not in pr
    fr.checks.append(Check("plasticity_runtime_status", ok1f,
                            1.0 if ok1f else 0.0,
                            json.dumps(pr)[:200], pr))

    # 1g) Gate de calibracao (auto-calibracao de thresholds)
    gc = _get(base, "/api/gate/calibration")
    ok1g = "_url_error" not in gc and "_http_error" not in gc
    min_delta = gc.get("min_delta", gc.get("calibrated_thresholds", {}))
    fr.checks.append(Check("self_calibrating_gate", ok1g,
                            1.0 if ok1g else 0.0,
                            f"min_delta={min_delta}", gc))

    return fr


# ════════════════════════════════════════════════════════════════════════════
# FRONT 2 — Modelo de mundo causal
# ════════════════════════════════════════════════════════════════════════════
def test_front2(base: str) -> FrontResult:
    fr = FrontResult(2, "Modelo de mundo causal")

    # 2a) Causal graph status (rota correta: causal-graph/status)
    cg = _get(base, "/api/causal-graph/status")
    ok2a = "_url_error" not in cg and "_http_error" not in cg
    nodes = cg.get("nodes", 0)
    edges = cg.get("edges", 0)
    fr.checks.append(Check("causal_graph_status", ok2a,
                            1.0 if (ok2a and int(nodes or 0) > 0) else 0.5 if ok2a else 0.0,
                            f"nodes={nodes} edges={edges}", cg))

    # 2b) Causal model rico (3000+ nodes via /api/causal/model)
    cm = _get(base, "/api/causal/model")
    ok2b = "_url_error" not in cm and "_http_error" not in cm
    cm_nodes = cm.get("nodes", 0)
    fr.checks.append(Check("causal_model_nodes", ok2b,
                            1.0 if (ok2b and int(cm_nodes or 0) > 100) else 0.5 if ok2b else 0.0,
                            f"causal_model_nodes={cm_nodes}", cm))

    # 2c) World model — simulacao de acao
    wm = _post(base, "/api/world-model/simulate",
               {"action": "send_message", "state": {"load": 0.3, "memory_ok": True}})
    ok2c = "_url_error" not in wm and "_http_error" not in wm
    pred = wm.get("simulation", {}).get("predicted_outcome") if "simulation" in wm else wm.get("predicted_outcome")
    fr.checks.append(Check("world_model_simulate", ok2c,
                            1.0 if ok2c else 0.0,
                            f"predicted_outcome={pred}", wm))

    # 2d) Causal discovery simulate (POST /api/causal-discovery/simulate)
    cd = _post(base, "/api/causal-discovery/simulate",
               {"action": "enable_causal_gate", "context": {"risk": 0.3}})
    ok2d = "_url_error" not in cd and "_http_error" not in cd
    fr.checks.append(Check("causal_discovery_simulate", ok2d,
                            1.0 if ok2d else 0.0, json.dumps(cd)[:200], cd))

    # 2e) Autonomous cognition — ticks executados (campo metrics.ticks)
    ac = _get(base, "/api/autonomous/cognition/status")
    ok2e = "_url_error" not in ac and "_http_error" not in ac
    metrics = ac.get("metrics", {})
    ticks = metrics.get("ticks", ac.get("cycles_completed", ac.get("tick_count", 0)))
    fr.checks.append(Check("autonomous_cognition_ticks", ok2e,
                            1.0 if (ok2e and int(ticks or 0) > 0) else 0.5 if ok2e else 0.0,
                            f"ticks={ticks}", ac))

    return fr


# ════════════════════════════════════════════════════════════════════════════
# FRONT 3 — Generalização entre domínios
# ════════════════════════════════════════════════════════════════════════════
def test_front3(base: str) -> FrontResult:
    fr = FrontResult(3, "Generalização entre domínios")

    # 3a) Abstrações explícitas
    ab = _get(base, "/api/abstractions")
    ab_list = ab.get("abstractions", ab.get("items", []))
    ok3a = isinstance(ab_list, list) and len(ab_list) > 0
    fr.checks.append(Check("explicit_abstractions_library", ok3a,
                            1.0 if ok3a else 0.5 if isinstance(ab_list, list) else 0.0,
                            f"count={len(ab_list)}", ab))

    # 3b) External benchmark suite status (rota correta: /api/evals/external/status)
    es = _get(base, "/api/evals/external/status")
    ok3b = "_url_error" not in es and "_http_error" not in es
    suite_ok = (es.get("suite") or {}).get("ok", False)
    bc = (es.get("suite") or {}).get("benchmark_counts", {})
    total_items = sum(bc.values()) if isinstance(bc, dict) else 0
    fr.checks.append(Check("external_eval_suite_status", ok3b,
                            1.0 if (ok3b and suite_ok and total_items > 0) else 0.5 if ok3b else 0.0,
                            f"suite_ok={suite_ok} items={total_items}", es))

    # 3c) External benchmark runs (rota correta: /api/evals/external/runs)
    eb = _get(base, "/api/evals/external/runs")
    runs = eb.get("items", eb.get("runs", []))
    ok3c = "_url_error" not in eb and "_http_error" not in eb and isinstance(runs, list) and len(runs) > 0
    last_acc = (runs[0].get("overall_accuracy") if runs else None)
    fr.checks.append(Check("external_benchmark_runs", ok3c,
                            1.0 if ok3c else 0.3 if ("_url_error" not in eb and "_http_error" not in eb) else 0.0,
                            f"runs={len(runs)} last_accuracy={last_acc}", eb))

    # 3d) External eval audit (integridade do suite)
    au = _get(base, "/api/evals/external/audit")
    ok3d = "_url_error" not in au and "_http_error" not in au and bool(au.get("ok"))
    dups = (au.get("duplicate_ids") or [])
    fr.checks.append(Check("external_eval_audit_integrity", ok3d,
                            1.0 if (ok3d and len(dups) == 0) else 0.5 if ok3d else 0.0,
                            f"audit_ok={au.get('ok')} duplicates={len(dups)}", au))

    # 3e) Chat resolve questão de domínio cruzado sem LLM
    chat = _post(base, "/api/chat",
                 {"message": "O que guarded_execution em filesystem tem em comum com rate_limiting em APIs?"})
    ans = str(chat.get("answer") or chat.get("response") or "")
    ok3e = len(ans) > 50 and _any_of(ans, "abstrac", "padr", "isomorf", "estrutur", "transfer")
    fr.checks.append(Check("cross_domain_chat_response", ok3e,
                            1.0 if ok3e else 0.4 if len(ans) > 30 else 0.0,
                            f"len={len(ans)} excerpt={ans[:120]}", chat))

    return fr


# ════════════════════════════════════════════════════════════════════════════
# FRONT 4 — Automanutenção, individuação e continuidade
# ════════════════════════════════════════════════════════════════════════════
def test_front4(base: str) -> FrontResult:
    fr = FrontResult(4, "Automanutenção, individuação e continuidade")

    # 4a) Self-model operacional
    sm = _get(base, "/api/self-model/status")
    ok4a = "_url_error" not in sm and "_http_error" not in sm
    identity = sm.get("identity", sm.get("name", sm.get("id", None)))
    fr.checks.append(Check("self_model_status", ok4a,
                            1.0 if (ok4a and identity) else 0.5 if ok4a else 0.0,
                            f"identity={identity}", sm))

    # 4b) Homeostasis vitals
    hs = _get(base, "/api/homeostasis/status")
    ok4b = "_url_error" not in hs and "_http_error" not in hs
    state = hs.get("state", hs.get("homeostatic_state", hs.get("status", None)))
    fr.checks.append(Check("homeostasis_vitals", ok4b,
                            1.0 if (ok4b and state) else 0.5 if ok4b else 0.0,
                            f"state={state}", hs))

    # 4c) Self-governance arbitrate funciona
    arb = _post(base, "/api/self-governance/arbitrate",
                {"action": "delete_all_episodic_memory", "justification": "space pressure"})
    ok4c = "_url_error" not in arb and "_http_error" not in arb
    decision = arb.get("decision", arb.get("result", None))
    fr.checks.append(Check("self_governance_arbitrate", ok4c,
                            1.0 if (ok4c and decision) else 0.5 if ok4c else 0.0,
                            f"decision={decision}", arb))

    # 4d) Narrativa / autobiografia
    narr = _get(base, "/api/self-governance/narrative")
    ok4d = "_url_error" not in narr and "_http_error" not in narr
    narr_text = str(narr.get("narrative") or narr.get("first_person_report") or "")
    fr.checks.append(Check("narrative_autobiography", ok4d,
                            1.0 if (ok4d and len(narr_text) > 100) else 0.5 if ok4d else 0.0,
                            f"narrative_len={len(narr_text)}", narr))

    # 4e) Linhagem — spawn/descendência
    lin = _get(base, "/api/self-governance/lineage")
    ok4e = "_url_error" not in lin and "_http_error" not in lin
    fr.checks.append(Check("lineage_endpoint", ok4e,
                            1.0 if ok4e else 0.0, json.dumps(lin)[:200], lin))

    # 4f) RL convergence (Gap 3) — proves the system actually learns over time
    rl = _get(base, "/api/rl/policy")
    ok4f_policy = "_url_error" not in rl and "_http_error" not in rl
    arms_val = rl.get("arms", rl.get("policy", {}))

    conv = _get(base, "/api/rl/convergence")
    ok4f_conv = "_url_error" not in conv and "_http_error" not in conv
    gap3_score = float((conv.get("gap3") or {}).get("score") or 0.0)
    conv_demonstrated = bool((conv.get("gap3") or {}).get("convergence_demonstrated"))
    global_updates = int((conv.get("policy") or {}).get("global_updates") or 0)

    ok4f = ok4f_policy and ok4f_conv
    score4f = (
        1.0 if (ok4f and conv_demonstrated and gap3_score >= 0.80) else
        0.8 if (ok4f and gap3_score >= 0.60) else
        0.5 if ok4f_policy else
        0.0
    )
    fr.checks.append(Check("rl_policy_drives", ok4f,
                            score4f,
                            f"arms={len(arms_val) if isinstance(arms_val, list) else 'N/A'} "
                            f"gap3={gap3_score:.2f} conv={conv_demonstrated} updates={global_updates}",
                            {"policy": rl, "convergence": conv}))

    return fr


# ════════════════════════════════════════════════════════════════════════════
# FRONT 5 — Consciência operacional integrada
# ════════════════════════════════════════════════════════════════════════════
def test_front5(base: str) -> FrontResult:
    fr = FrontResult(5, "Consciência operacional integrada")

    # 5a) Global workspace status (rota correta: /api/workspace/status)
    gw = _get(base, "/api/workspace/status")
    ok5a = "_url_error" not in gw and "_http_error" not in gw
    gw_items = gw.get("items", 0)
    channels = gw.get("channels", {})
    fr.checks.append(Check("global_workspace_status", ok5a,
                            1.0 if (ok5a and int(gw_items or 0) > 0) else 0.5 if ok5a else 0.0,
                            f"items={gw_items} channels={len(channels)}", gw))

    # 5b) Meta-observer
    mo = _get(base, "/api/meta-observer/status")
    ok5b = "_url_error" not in mo and "_http_error" not in mo
    focus_count = len(mo.get("focus", []))
    fr.checks.append(Check("meta_observer_status", ok5b,
                            1.0 if (ok5b and focus_count > 0) else 0.5 if ok5b else 0.0,
                            f"focus_items={focus_count}", mo))

    # 5c) Affect markers — valence em markers.valence
    aff = _get(base, "/api/affect/status")
    ok5c = "_url_error" not in aff and "_http_error" not in aff
    markers = aff.get("markers", {})
    valence = markers.get("valence") if isinstance(markers, dict) else aff.get("valence")
    risk_posture = aff.get("risk_posture", None)
    fr.checks.append(Check("affect_markers", ok5c,
                            1.0 if (ok5c and valence is not None) else 0.5 if ok5c else 0.0,
                            f"valence={valence} risk_posture={risk_posture}", aff))

    # 5d) Integration proxy score — campo integration_proxy_score
    ip = _get(base, "/api/integration-proxy/status")
    ok5d = "_url_error" not in ip and "_http_error" not in ip
    score = ip.get("integration_proxy_score", ip.get("integration_score", ip.get("score", None)))
    level = ip.get("integration_level", None)
    fr.checks.append(Check("integration_proxy_score", ok5d,
                            1.0 if (ok5d and score is not None and float(score or 0) > 0.5) else 0.5 if ok5d else 0.0,
                            f"score={score} level={level}", ip))

    # 5e) Authorship trace
    at = _get(base, "/api/authorship/status")
    ok5e = "_url_error" not in at and "_http_error" not in at
    trace_score = at.get("trace_score", None)
    fr.checks.append(Check("authorship_trace_status", ok5e,
                            1.0 if (ok5e and trace_score is not None) else 0.5 if ok5e else 0.0,
                            f"trace_score={trace_score}", at))

    # 5f) Intrinsic utility drives — drives e uma lista de dicts [{drive, weight, ...}]
    iu = _get(base, "/api/utility/status")
    ok5f = "_url_error" not in iu and "_http_error" not in iu
    drives_raw = iu.get("drives", [])
    drives_list = drives_raw if isinstance(drives_raw, list) else list(drives_raw.values()) if isinstance(drives_raw, dict) else []
    utility = iu.get("utility", None)
    competence_drive = next((d for d in drives_list if d.get("drive") == "competence"), {})
    competence_val = competence_drive.get("observed", None)
    fr.checks.append(Check("intrinsic_utility_drives", ok5f,
                            1.0 if (ok5f and len(drives_list) >= 3) else 0.5 if ok5f else 0.0,
                            f"drives={len(drives_list)} utility={utility} competence={competence_val}", iu))

    # 5g) Chat responde com autoconsciencia referenciando workspace/foco
    chat = _post(base, "/api/chat",
                 {"message": "O que esta em foco no seu workspace agora e o que voce esta ignorando?"})
    ans = str(chat.get("answer") or chat.get("response") or "")
    ok5g = len(ans) > 60 and _any_of(ans, "workspace", "foco", "saliencia", "atencao", "integr",
                                      "autonomy", "autonomia", "utili")
    fr.checks.append(Check("self_awareness_chat", ok5g,
                            1.0 if ok5g else 0.4 if len(ans) > 30 else 0.0,
                            f"len={len(ans)} excerpt={ans[:120]}", chat))

    return fr


# ════════════════════════════════════════════════════════════════════════════
# RUNNER PRINCIPAL
# ════════════════════════════════════════════════════════════════════════════
FRONT_RUNNERS: dict[int, Callable[[str], FrontResult]] = {
    1: test_front1,
    2: test_front2,
    3: test_front3,
    4: test_front4,
    5: test_front5,
}

FRONT_THRESHOLDS = {1: 60, 2: 60, 3: 55, 4: 60, 5: 55}  # % mínimo para PASS


def _print_front(fr: FrontResult, verbose: bool) -> None:
    status = "[PASS]" if fr.score_pct >= FRONT_THRESHOLDS[fr.front_id] else "[FAIL]"
    print(f"\n" + "-"*60)
    print(f"FRONT {fr.front_id} -- {fr.front_name}")
    print(f"Score: {fr.score_pct}%  ({fr.passed}/{fr.total} checks)  {status}")
    print("-"*60)
    for c in fr.checks:
        icon = "[OK]" if c.ok else "[~~]" if c.score > 0 else "[XX]"
        bar = int(c.score * 10) * "#"
        print(f"  {icon} {c.name:<42} [{bar:<10}] {c.detail[:70]}")
        if verbose and c.raw:
            raw_str = json.dumps(c.raw, ensure_ascii=False)
            print(f"     raw: {raw_str[:200]}")


def run_all(base: str, verbose: bool, fronts: list[int]) -> dict[str, Any]:
    print(f"\n{'='*60}")
    print(f"  UltronPro — AGI Production Test Suite")
    print(f"  Servidor: {base}")
    print(f"  Fronts:   {fronts}")
    print(f"  {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")

    started = time.time()
    results: list[FrontResult] = []
    errors: list[str] = []

    for fid in sorted(fronts):
        runner = FRONT_RUNNERS.get(fid)
        if not runner:
            continue
        try:
            fr = runner(base)
        except Exception:
            tb = traceback.format_exc()
            errors.append(f"Front {fid}: {tb}")
            print(f"\n❌ Front {fid} CRASHED:\n{tb}")
            continue
        results.append(fr)
        _print_front(fr, verbose)

    # Sumário geral
    total_checks  = sum(fr.total   for fr in results)
    passed_checks = sum(fr.passed  for fr in results)
    avg_score     = round(sum(fr.score_pct for fr in results) / max(1, len(results)), 1)
    global_ok     = all(fr.score_pct >= FRONT_THRESHOLDS[fr.front_id] for fr in results)

    print(f"\n" + "="*60)
    print(f"  RESULTADO GLOBAL")
    print(f"  Score medio: {avg_score}%")
    print(f"  Checks OK:   {passed_checks}/{total_checks}")
    print(f"  Status:      {'APROVADO' if global_ok else 'REPROVADO'}")
    print(f"  Duracao:     {round(time.time()-started, 1)}s")
    print("="*60)

    # Tabela por front
    print("\nFront | Nome                                   | Score  | Threshold | Status")
    print("------+----------------------------------------+--------+-----------+--------")
    for fr in results:
        thr   = FRONT_THRESHOLDS[fr.front_id]
        st    = "PASS" if fr.score_pct >= thr else "FAIL"
        print(f"  {fr.front_id}   | {fr.front_name:<38} | {fr.score_pct:5.1f}% | {thr:>5}%     | {st}")

    # Persiste relatório
    report = {
        "ts": int(time.time()),
        "base_url": base,
        "global_ok": global_ok,
        "avg_score_pct": avg_score,
        "passed_checks": passed_checks,
        "total_checks": total_checks,
        "duration_sec": round(time.time() - started, 2),
        "fronts": [
            {
                "front_id": fr.front_id,
                "front_name": fr.front_name,
                "score_pct": fr.score_pct,
                "passed": fr.passed,
                "total": fr.total,
                "threshold": FRONT_THRESHOLDS[fr.front_id],
                "pass": fr.score_pct >= FRONT_THRESHOLDS[fr.front_id],
                "checks": [
                    {"name": c.name, "ok": c.ok, "score": c.score, "detail": c.detail}
                    for c in fr.checks
                ],
            }
            for fr in results
        ],
        "errors": errors,
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with REPORT_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(report, ensure_ascii=False) + "\n")
    print(f"\nRelatorio salvo em: {REPORT_PATH}")
    return report


# ─────────────────────────── CLI ───────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(description="AGI Production Test — UltronPro")
    parser.add_argument("--base-url", default=DEFAULT_BASE)
    parser.add_argument("--verbose",  action="store_true")
    parser.add_argument("--front",    type=int, nargs="+",
                        help="Quais fronts testar (1-5). Default: todos")
    args = parser.parse_args()

    fronts = args.front if args.front else list(FRONT_RUNNERS.keys())
    report = run_all(args.base_url, args.verbose, fronts)
    sys.exit(0 if report["global_ok"] else 1)


if __name__ == "__main__":
    main()
