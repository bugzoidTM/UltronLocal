# Longitudinal Seed Effectiveness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make longitudinal proof seeds alter the actual task sequence and add strict multi-seed verification.

**Architecture:** Extend `ultronpro.longitudinal_runner` with a seeded scheduler that produces explicit sequence items and a canonical `task_sequence_hash`. Add a small CLI verifier under `backend/tools` to compare multiple reports and fail strict mode when seed diversity or v2 gates fail.

**Tech Stack:** Python 3.12, pytest, deterministic `random.Random`, JSON report artifacts, existing `HashChainLogger`.

---

## File Structure

- Modify `backend/ultronpro/longitudinal_runner.py`: add task families, prompt variants, seeded sequence generation, sequence hash, seed effectiveness metadata, and event prompt overrides.
- Modify `backend/test_longitudinal_runner.py`: add failing tests for different seeds producing different hashes and for report metadata.
- Create `backend/tools/verify_longitudinal_seed_diversity.py`: aggregate report verifier with `--strict`.
- Create `backend/test_longitudinal_seed_diversity.py`: tests for strict verifier behavior.
- Modify `backend/tools/README_proofs.md`: document v2 multi-seed verification.

### Task 1: Seeded Task Sequence

- [ ] Write failing tests in `backend/test_longitudinal_runner.py` asserting seeds 17, 29, and 41 produce distinct `task_sequence_hash` values and different prompts/orders while each run still passes.
- [ ] Implement `ScheduledTask`, `build_task_sequence`, and `task_sequence_hash` in `backend/ultronpro/longitudinal_runner.py`.
- [ ] Update `run_proof` to execute the scheduled prompt instead of fixed task prompts.
- [ ] Run `python -m pytest test_longitudinal_runner.py -q`.

### Task 2: Strict Multi-Seed Verifier

- [ ] Write failing tests in `backend/test_longitudinal_seed_diversity.py` for duplicate hashes producing `seed_registered_but_not_effective=true` and strict failure.
- [ ] Implement `backend/tools/verify_longitudinal_seed_diversity.py` with report loading, hash verification, v2 gates, JSON output, and strict exit code.
- [ ] Run `python -m pytest test_longitudinal_seed_diversity.py test_longitudinal_runner.py -q`.

### Task 3: Docs And Reproduction

- [ ] Update `backend/tools/README_proofs.md` with seed-v2 commands.
- [ ] Run focused tests and three proof runs for seeds 17, 29, and 41 using new run ids.
- [ ] Run the strict verifier over those three run ids.
- [ ] Commit source/docs changes only, leaving runtime proof artifacts unstaged.

