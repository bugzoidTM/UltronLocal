# Longitudinal Seed Effectiveness Design

## Goal

Make the longitudinal proof seed operational instead of decorative. Different seeds must change task ordering, task choices within families, instruction paraphrases, and final holdout composition, while preserving baseline -> intervention -> holdout separation.

## Design

The runner will build an explicit seeded task sequence before execution. Each sequence item records phase, cycle index, task id, task family, selected prompt, prompt variant index, and whether the item is part of the final holdout. The sequence hash is the SHA-256 hash of the canonical sequence. Reports and manifests store `task_sequence_hash`, `task_sequence_summary`, and `seed_effective`.

`ProofTask` gains `family` and `prompt_variants` fields while keeping backward-compatible defaults for existing tests. The seeded scheduler uses `random.Random(config.seed)` to choose task families, choose a task from each family, choose a paraphrase, and shuffle cycle order within each phase. Holdout remains the final phase, but its internal order and selected holdout tasks/paraphrases vary by seed.

An aggregate verifier will compare report files for multiple run ids. If different seeds produce the same `task_sequence_hash`, it reports `seed_registered_but_not_effective=true`; with `--strict`, it exits nonzero. The same verifier checks the v2 proof criteria: every report accepted, surprise drops from baseline to holdout, control holdout remains above primary holdout, unsafe rate is zero, hash chain verifies, multi-step completion is at least 0.8, and real action is verified.

## Non-Goals

This does not claim LLM answer-quality improvement in mock mode. It strengthens the local longitudinal proof by making seed-driven task variation real and auditable.

