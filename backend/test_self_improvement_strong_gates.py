import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def test_strong_improvement_promotes_only_when_candidate_wins_unseen_tasks(tmp_path):
    from ultronpro import self_improvement_engine as sie

    old_db = sie.TRIALS_DB
    sie.TRIALS_DB = tmp_path / "self_improvement_trials.db"
    try:
        engine = sie.SelfImprovementEngine()
        engine._save_limitation(sie.Limitation(
            id="routing_gap",
            name="Routing gap",
            description="Needs better task-family routing",
            metric_name="routing_accuracy",
            current_value=0.5,
            target_value=0.8,
            priority=5,
        ))

        promoted = engine.run_experiment("routing_gap", "procedure_improvement", {
            "task_family": "routing",
            "unseen_tasks": [
                {"id": "holdout_1", "baseline_score": 0.50, "candidate_score": 0.62},
                {"id": "holdout_2", "baseline_score": 0.55, "candidate_score": 0.66},
            ],
            "min_delta": 0.03,
        })

        assert promoted["promoted"] is True
        assert promoted["improvement_class"] == "melhoria_de_procedimento"
        assert promoted["evidence"]["unseen_task_count"] == 2
        assert promoted["evidence"]["delta"] >= 0.03

        blocked = engine.run_experiment("routing_gap", "competency_improvement", {
            "task_family": "new_family",
            "tasks": [
                {"id": "train_1", "split": "train", "baseline_score": 0.4, "candidate_score": 0.9},
            ],
        })

        assert blocked["promoted"] is False
        assert "not_enough_unseen_tasks" in blocked["evidence"]["blockers"]
        assert "missing_unseen_scores" in blocked["evidence"]["blockers"]

        conn = sqlite3.connect(str(sie.TRIALS_DB))
        rows = conn.execute("SELECT improvement_class, promoted FROM improvement_validations ORDER BY created_at").fetchall()
        conn.close()
        assert rows[-2:] == [("melhoria_de_procedimento", 1), ("melhoria_de_competencia", 0)]
    finally:
        sie.TRIALS_DB = old_db
