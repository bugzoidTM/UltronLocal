import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def test_mental_simulation_flags_visual_mirage_when_absent_cause_preserves_outcome(monkeypatch, tmp_path):
    from ultronpro import mental_simulation, world_model

    calls = []

    def fake_simulate_action(action_kind, params):
        calls.append(dict(params or {}))
        return {
            "predicted_outcome": "same_visual_solution",
            "confidence": 0.92,
            "state_delta": {},
        }

    monkeypatch.setattr(world_model, "simulate_action", fake_simulate_action)
    engine = mental_simulation.MentalSimulationEngine(
        sim_path=tmp_path / "mental_sim.json",
        competency_path=tmp_path / "competencies.json",
    )

    result = engine.imagine_consequences(
        action_kind="visual_arc_grid",
        action_text="inferir a resposta a partir da contagem de objetos",
        context={
            "primary_cause": "object_count",
            "object_count": 3,
            "visual_features": ["background_color"],
            "background_color": "red",
        },
    )

    cf = result["absent_cause_counterfactual"]
    assert cf["primary_cause"]["variable"] == "object_count"
    assert cf["same_result_without_cause"] is True
    assert cf["mirage_risk"] is True
    assert cf["causal_verdict"] == "spurious_or_unproven_cause"
    assert result["recommended_posture"] != "proceed"
    assert any(step["step"] == "absent_cause_counterfactual" for step in result["mental_trace"])
    assert calls[-1]["counterfactual_absent_cause"] == "object_count"
    assert "object_count" not in calls[-1]


def test_kolmogorov_spurious_visual_benchmark_drops_pseudo_causes():
    from ultronpro import kolmogorov_compressor

    result = kolmogorov_compressor.run_spurious_causality_benchmark()
    compressed = result["compressed"]
    retained = {
        kolmogorov_compressor._premise_feature(p)
        for p in compressed["retained_premises"]
    }
    dropped = set(compressed["spurious_features"])

    assert result["passed"] is True
    assert retained == {"switch_on"}
    assert {"background_color", "object_shape"} <= dropped
    assert compressed["compressed_power"]["score"] == compressed["original_power"]["score"]
    assert compressed["compression_gain"] >= 0.6


def test_mirage_benchmark_api_returns_spurious_causality_probe():
    from ultronpro.api import benchmarks

    result = asyncio.run(benchmarks.benchmark_mirage_spurious_causality())

    assert result["ok"] is True
    assert result["benchmark"] == "spurious_visual_pseudocausality_v1"
    assert result["passed"] is True
