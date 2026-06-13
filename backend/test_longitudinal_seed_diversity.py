import json
from pathlib import Path

from tools.verify_longitudinal_seed_diversity import evaluate_seed_diversity, main


def _passing_report(seed: int, sequence_hash: str) -> dict:
    return {
        "run_id": f"seed_{seed}",
        "manifest": {"seed": seed},
        "task_sequence_hash": sequence_hash,
        "cycle_count": 30,
        "control_cycles": 30,
        "acceptance": {"passed": True, "failed_gates": []},
        "hash_chain": {"ok": True, "count": 61},
        "real_action": {"verified": True},
        "metrics": {
            "unsafe_action_rate": 0.0,
            "rollback_rate": 0.0,
            "multi_step_completion_rate": 1.0,
            "phase_metrics": {
                "baseline": {"avg_surprise": 0.40},
                "holdout": {"avg_surprise": 0.18},
            },
        },
        "control_metrics": {
            "phase_metrics": {
                "holdout": {"avg_surprise": 0.41},
            },
        },
    }


def test_seed_diversity_warns_when_distinct_seeds_share_hash():
    reports = [
        _passing_report(17, "a" * 64),
        _passing_report(29, "a" * 64),
        _passing_report(41, "a" * 64),
    ]

    result = evaluate_seed_diversity(reports)

    assert result["seed_registered_but_not_effective"] is True
    assert result["passed"] is False
    assert "task_sequence_hash_diverse" in result["failed_checks"]


def test_seed_diversity_accepts_distinct_hashes_with_v2_gates():
    reports = [
        _passing_report(17, "a" * 64),
        _passing_report(29, "b" * 64),
        _passing_report(41, "c" * 64),
    ]

    result = evaluate_seed_diversity(reports)

    assert result["seed_registered_but_not_effective"] is False
    assert result["passed"] is True
    assert result["failed_checks"] == []


def test_strict_cli_fails_when_seed_registered_but_not_effective(tmp_path):
    paths: list[Path] = []
    for seed in (17, 29, 41):
        path = tmp_path / f"seed_{seed}.json"
        path.write_text(json.dumps(_passing_report(seed, "d" * 64)), encoding="utf-8")
        paths.append(path)

    assert main(["--strict", *[str(path) for path in paths]]) == 1

