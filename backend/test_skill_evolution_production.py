import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _isolate(tmp_path, monkeypatch):
    from ultronpro import skill_evolution, skill_loader, skill_executor
    from ultronpro.core import learned_intent

    skills_dir = tmp_path / "ultron_skills"
    monkeypatch.setattr(skill_evolution, "STATE_PATH", tmp_path / "skill_evolution_state.json")
    monkeypatch.setattr(skill_evolution, "BENCHMARK_LOG_PATH", tmp_path / "skill_evolution_benchmarks.jsonl")
    monkeypatch.setattr(skill_evolution, "MATERIALIZED_SKILLS_DIR", skills_dir)
    monkeypatch.setattr(learned_intent, "ROUTE_EPISODES_PATH", tmp_path / "intent_route_episodes.jsonl")
    monkeypatch.setattr(skill_loader, "SKILLS_DIR", skills_dir)
    monkeypatch.setattr(skill_loader, "_loader", skill_loader.SkillLoader(skills_dir))
    monkeypatch.setattr(skill_executor, "_executor", None)
    return skill_evolution, skill_loader, skill_executor, learned_intent


def _seed_real_chat_routes(learned_intent, n=30):
    for i in range(n):
        learned_intent.record_route_episode(
            f"calcule soma inteira {10 + i} mais {20 + i}",
            module="symbolic",
            strategy="symbolic_pure",
            ok=True,
            latency_ms=80 + i,
            source="chat_stream",
            outcome="success",
            meta={"benchmark_seed": True},
        )


def test_skill_evolution_reaches_candidate_promotion_use_and_transfer_targets(tmp_path, monkeypatch):
    skill_evolution, skill_loader, _, learned_intent = _isolate(tmp_path, monkeypatch)
    _seed_real_chat_routes(learned_intent, n=30)

    generated = skill_evolution.generate_candidates(limit=80, target=30)
    promoted = skill_evolution.promote_by_replay(max_promotions=20)
    loaded = skill_loader.load_skills(force=True)

    assert generated["candidate_count"] >= 30
    assert promoted["promoted_count"] == 20
    assert len([name for name in loaded if name.startswith("auto_")]) >= 20
    assert all(Path(item["materialized_path"]).exists() for item in promoted["promoted"])

    promoted_candidates = [c for c in skill_evolution.status(limit=80)["recent_candidates"] if c["status"] == "promoted"]
    for item in promoted_candidates[:12]:
        result = skill_evolution.execute_generated_skill(
            item["skill_name"],
            "teste producao skill gerada: " + item["source_episode"]["query"],
        )
        assert result["success"] is True
        assert result["raw"]["avoided_llm"] is True

    transfer = skill_evolution.validate_transfer(max_validations=8)
    metrics = skill_evolution.metrics()

    assert transfer["validated_count"] >= 8
    assert metrics["candidate_count"] >= 30
    assert metrics["promoted_count"] >= 20
    assert metrics["production_used_count"] >= 12
    assert metrics["transfer_validated_count"] >= 8
    assert metrics["severe_regressions_without_rollback"] == 0
    assert metrics["llm_reduction_pct"] >= 50.0
    assert metrics["simple_chat_mean_latency_ms"] < 1000
    assert all(metrics["target_pass"].values())


def test_generated_skill_executor_survives_provider_unavailable(tmp_path, monkeypatch):
    skill_evolution, _, skill_executor, learned_intent = _isolate(tmp_path, monkeypatch)
    _seed_real_chat_routes(learned_intent, n=3)
    skill_evolution.generate_candidates(limit=10)
    promoted = skill_evolution.promote_by_replay(max_promotions=1)
    skill_name = promoted["promoted"][0]["skill_name"]

    from ultronpro import llm

    monkeypatch.setattr(llm, "complete", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("provider offline")))

    executor = skill_executor.SkillExecutor()
    result = asyncio.run(executor.execute("calcule soma inteira 5 mais 6", suggested_skill=skill_name))

    assert result.success is True
    assert result.skill_name == skill_name
    assert result.execution_time_ms < 1000
    assert "provider offline" not in str(result.output)
    assert skill_evolution.metrics()["severe_regressions_without_rollback"] == 0
