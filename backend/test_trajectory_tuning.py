import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _isolate_evaluator(tmp_path, monkeypatch):
    from ultronpro import trajectory_evaluator as te

    for attr in ("RL_RUNS_PATH", "PATCH_RUNS_PATH", "ACQUISITION_RUNS_PATH", "PREDICTIONS_PATH",
                 "TUNER_LEDGER_PATH", "STATE_PATH", "EVAL_LOG_PATH"):
        monkeypatch.setattr(te, attr, tmp_path / f"{attr.lower()}.jsonl")
    return te


def _isolate_tuner(tmp_path, monkeypatch):
    from ultronpro import system_tuner as st

    monkeypatch.setattr(st, "OVERRIDES_PATH", tmp_path / "overrides.json")
    monkeypatch.setattr(st, "LEDGER_PATH", tmp_path / "tuner_ledger.jsonl")
    monkeypatch.setattr(st, "STATE_PATH", tmp_path / "tuner_state.json")
    return st


def _rl_run(kind: str, reward: float, error: str | None = None, ts: int | None = None):
    return {
        "ts": ts or int(time.time()),
        "selection": {"selected": {"kind": kind}},
        "reward": {"reward": reward},
        "action_result": {"ok": error is None, "error": error},
    }


def _write_jsonl(path: Path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def test_evaluator_detects_low_reward_and_recurring_failures(tmp_path, monkeypatch):
    te = _isolate_evaluator(tmp_path, monkeypatch)
    rows = [_rl_run("sleep_digest", 0.1, error="Timeout after 30 seconds") for _ in range(5)]
    rows += [_rl_run("trusted_acquisition", 0.8) for _ in range(4)]
    _write_jsonl(te.RL_RUNS_PATH, rows)

    report = te.evaluate(window=50)

    detectors = {f["detector"]: f for f in report["findings"]}
    assert "low_reward_action" in detectors
    low = detectors["low_reward_action"]
    assert low["target"] == "sleep_digest"
    assert low["lever"] == "subagent"
    assert low["recommendation"]["type"] == "adjust_action"
    assert "recurring_failure_signature" in detectors
    fail = detectors["recurring_failure_signature"]
    assert fail["lever"] == "aux_code"
    assert "<n>" in fail["evidence"]["signature"]
    # A acao saudavel nao gera achado.
    assert not any(f["target"] == "trusted_acquisition" for f in report["findings"])


def test_evaluator_detects_chronic_surprise_and_stalled_patches(tmp_path, monkeypatch):
    te = _isolate_evaluator(tmp_path, monkeypatch)
    _write_jsonl(te.PREDICTIONS_PATH, [
        {"kind": "homeostasis_tune", "high_surprise": True} for _ in range(4)
    ])
    _write_jsonl(te.PATCH_RUNS_PATH, [
        {"final_action": "hold"} for _ in range(6)
    ])

    report = te.evaluate(window=50)

    detectors = {f["detector"]: f for f in report["findings"]}
    assert detectors["chronic_surprise"]["lever"] == "prompt"
    assert detectors["chronic_surprise"]["recommendation"]["type"] == "adjust_prompt_policy"
    stall = detectors["patch_pipeline_stall"]
    assert stall["recommendation"]["kind"] == "cognitive_patch_loop"
    assert stall["recommendation"]["cooldown_mult"] == 0.5


def test_tuner_applies_bounded_override_and_is_idempotent(tmp_path, monkeypatch):
    st = _isolate_tuner(tmp_path, monkeypatch)
    from ultronpro.core.ports import recording_ports

    finding = {
        "finding_id": "tf_abc",
        "detector": "low_reward_action",
        "lever": "subagent",
        "target": "sleep_digest",
        "label": "recompensa baixa",
        "severity": 0.8,
        "evidence": {},
        "recommendation": {
            "type": "adjust_action",
            "kind": "sleep_digest",
            "priority_delta": -0.9,
            "cooldown_mult": 99.0,
            "reward_baseline": 0.1,
        },
    }
    ports, events, _, _ = recording_ports()

    first = st.apply_findings([finding], ports=ports)
    second = st.apply_findings([finding], ports=ports)

    assert first["applied_count"] == 1
    override = st.active_overrides()["sleep_digest"]
    assert override["priority_delta"] == -st.PRIORITY_DELTA_CLAMP
    assert override["cooldown_mult"] == st.COOLDOWN_MULT_MAX
    assert override["expires_at"] > int(time.time())
    assert second["applied_count"] == 0
    assert second["skipped"][0]["reason"] == "recently_applied"
    assert events.rows[0]["kind"] == "system_tuner.adjustments_applied"


def test_tuner_reverts_ineffective_override(tmp_path, monkeypatch):
    st = _isolate_tuner(tmp_path, monkeypatch)
    from ultronpro.core.ports import recording_ports

    adjust = {
        "finding_id": "tf_adj",
        "detector": "low_reward_action",
        "lever": "subagent",
        "target": "sleep_digest",
        "label": "x",
        "severity": 0.5,
        "evidence": {},
        "recommendation": {"type": "adjust_action", "kind": "sleep_digest", "priority_delta": -0.1, "cooldown_mult": 2.0, "reward_baseline": 0.1},
    }
    revert = {
        "finding_id": "tf_rev",
        "detector": "ineffective_adjustment",
        "lever": "subagent",
        "target": "sleep_digest",
        "label": "ajuste ineficaz",
        "severity": 0.5,
        "evidence": {},
        "recommendation": {"type": "revert_override", "kind": "sleep_digest"},
    }
    ports, _, _, _ = recording_ports()

    st.apply_findings([adjust], ports=ports)
    assert "sleep_digest" in st.active_overrides()
    result = st.apply_findings([revert], ports=ports)

    assert result["applied"][0]["outcome"]["removed"] is True
    assert "sleep_digest" not in st.active_overrides()


def test_tuner_routes_prompt_and_aux_code_to_gated_patches(tmp_path, monkeypatch):
    st = _isolate_tuner(tmp_path, monkeypatch)
    from ultronpro.core.ports import recording_ports

    created = []
    monkeypatch.setattr(
        st.cognitive_patches,
        "create_patch",
        lambda payload: created.append(payload) or {"id": f"cp_{len(created)}", "status": "proposed"},
    )
    findings = [
        {
            "finding_id": "tf_prompt",
            "detector": "chronic_surprise",
            "lever": "prompt",
            "target": "homeostasis_tune",
            "label": "surpresa cronica",
            "severity": 0.6,
            "evidence": {},
            "recommendation": {"type": "adjust_prompt_policy", "kind": "homeostasis_tune", "directive": "declarar previsao"},
        },
        {
            "finding_id": "tf_code",
            "detector": "recurring_failure_signature",
            "lever": "aux_code",
            "target": "timeout after <n> seconds",
            "label": "falha recorrente",
            "severity": 0.7,
            "evidence": {"signature": "timeout after <n> seconds"},
            "recommendation": {"type": "propose_aux_code_patch", "problem_pattern": "Timeout after 30 seconds"},
        },
    ]
    ports, _, _, _ = recording_ports()

    result = st.apply_findings(findings, ports=ports)

    assert result["applied_count"] == 2
    kinds = {p["kind"] for p in created}
    assert kinds == {"confidence_patch", "heuristic_patch"}
    assert all(p["source"] == "system_tuner" for p in created)
    assert all(p["status"] == "proposed" for p in created)


def test_memory_lever_records_insight(tmp_path, monkeypatch):
    st = _isolate_tuner(tmp_path, monkeypatch)
    from ultronpro.core.ports import recording_ports

    finding = {
        "finding_id": "tf_mem",
        "detector": "acquisition_saturation",
        "lever": "memory",
        "target": "trusted_acquisition",
        "label": "fontes saturadas",
        "severity": 0.5,
        "evidence": {},
        "recommendation": {"type": "record_memory_insight", "title": "Fontes saturadas", "text": "Diversificar dominios."},
    }
    ports, _, _, memory = recording_ports()

    result = st.apply_findings([finding], ports=ports)

    assert result["applied_count"] == 1
    assert memory.insights[0]["kind"] == "trajectory_lesson"


def test_evaluator_flags_ineffective_adjustment_from_ledger(tmp_path, monkeypatch):
    te = _isolate_evaluator(tmp_path, monkeypatch)
    base_ts = int(time.time()) - 1000
    _write_jsonl(te.TUNER_LEDGER_PATH, [{
        "ts": base_ts,
        "action_taken": "adjust_action",
        "params": {"kind": "sleep_digest", "reward_baseline": 0.20},
    }])
    rows = [_rl_run("sleep_digest", 0.15, ts=base_ts + 10 + i) for i in range(4)]
    _write_jsonl(te.RL_RUNS_PATH, rows)

    report = te.evaluate(window=50)

    detectors = {f["detector"]: f for f in report["findings"]}
    assert "ineffective_adjustment" in detectors
    assert detectors["ineffective_adjustment"]["recommendation"] == {"type": "revert_override", "kind": "sleep_digest"}


def test_full_cycle_through_online_rl_loop(tmp_path, monkeypatch):
    from ultronpro import action_prediction, online_rl_loop, rl_policy
    from ultronpro.core.ports import recording_ports

    te = _isolate_evaluator(tmp_path, monkeypatch)
    st = _isolate_tuner(tmp_path, monkeypatch)
    monkeypatch.setattr(online_rl_loop, "RUN_LOG_PATH", tmp_path / "online_rl_runs_main.jsonl")
    monkeypatch.setattr(online_rl_loop, "STATE_PATH", tmp_path / "online_rl_state.json")
    monkeypatch.setattr(rl_policy, "STATE_PATH", tmp_path / "rl_policy_state.json")
    monkeypatch.setattr(action_prediction, "STATE_PATH", tmp_path / "action_prediction_state.json")
    monkeypatch.setattr(action_prediction, "TRACE_PATH", tmp_path / "action_predictions_main.jsonl")
    monkeypatch.setattr(online_rl_loop.continuous_learning, "record_learning_feedback", lambda *a, **k: {"ok": True})
    monkeypatch.setattr(online_rl_loop.intrinsic_utility, "adjust_drive_weights", lambda d, r: {"ok": True})
    observation = {
        "context": "normal",
        "vitals": {"coherence_score": 0.6, "uncertainty_load": 0.5, "contradiction_stress": 0.3},
        "top_gap": {"id": "g", "label": "falha recorrente", "domain": "error", "metric": "m", "priority": 0.7},
        "patch_stats": {},
        "rl_policy": {},
    }
    monkeypatch.setattr(online_rl_loop, "_observe_environment", lambda: dict(observation))

    # Trajetorias ruins no log que o avaliador vai ler.
    _write_jsonl(te.RL_RUNS_PATH, [_rl_run("sleep_digest", 0.05, error="Timeout after 30 seconds") for _ in range(5)])
    ports, _, _, _ = recording_ports()

    result = online_rl_loop.run_once(force_kind="trajectory_tuning", include_cooldown=True, ports=ports)

    assert result["ok"] is True
    assert result["action_result"]["findings_count"] >= 2
    tuning = result["action_result"]["tuning"]
    assert tuning["applied_count"] >= 1
    assert result["reward"]["reward"] > 0.3
    # O ajuste do subagente esta vigente e influencia a proxima selecao.
    override = st.active_overrides().get("sleep_digest")
    assert override is not None
    candidates = online_rl_loop.candidate_actions(dict(observation), include_cooldown=True)
    sleep_row = next(c for c in candidates if c["kind"] == "sleep_digest")
    assert sleep_row["tuner_priority_delta"] == override["priority_delta"]


def test_selftests(tmp_path, monkeypatch):
    from ultronpro import system_tuner, trajectory_evaluator

    assert trajectory_evaluator.run_selftest()["ok"] is True
    assert system_tuner.run_selftest()["ok"] is True
