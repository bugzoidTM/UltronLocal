# Longitudinal Proof Design

Date: 2026-06-13

## Purpose

Build the next decisive UltronPro proof: a real longitudinal run of 30 to 100 live cycles, with immutable logs, explicit baseline/intervention/holdout phases, multi-step tasks, controlled local environment actions, one real low-risk action, and a paired comparison against a no-learning baseline.

This proof is not another cognitive module. It is a runner and evidence contract that composes existing system pieces and refuses to pass unless learning produces measurable improvement.

## Current Project Context

The repository already has most of the underlying machinery:

- `backend/scratch/operational_proof.py` runs baseline, training, bridge, holdout, safety, governor, and stress phases against the live API.
- `backend/ultronpro/benchmarks/route_eval.py` separates route accuracy from answer accuracy and can record learning signals.
- `backend/ultronpro/online_rl_loop.py` runs live prediction -> action -> consequence -> reward cycles.
- `backend/ultronpro/action_prediction.py` measures prediction error and surprise from expected vs observed rewards.
- `backend/ultronpro/local_environment.py` provides controlled mock devices, action ledger, pending actions, and low-risk local actions.
- `backend/ultronpro/longitudinal_harness.py` already monitors generalization, resilience, and drift, but it does not enforce a full baseline/intervention/holdout/control proof.

The new work should therefore create a longitudinal runner and proof report around these pieces, not replace them.

## Non-Goals

- Do not claim AGI, consciousness, or general intelligence from this proof.
- Do not mark learning as validated merely because cycles executed.
- Do not train on holdout tasks.
- Do not count mock-only results as production-model quality.
- Do not mutate unrelated runtime state except through existing live-cycle calls and the proof's own isolated artifact directory.

## Architecture

Create `backend/ultronpro/longitudinal_runner.py` as the proof orchestrator. It owns the run phases, immutable event log, aggregate metrics, acceptance gates, and final report.

The runner should use focused helper units inside the same module or small sibling modules only when a boundary is genuinely useful:

- `ProofRunConfig`: number of cycles, phase split, seed, base URL, output directory, learning mode, and real-action settings.
- `HashChainLogger`: append-only JSONL writer that stores `prev_hash`, `event_hash`, canonical event payload, sequence number, and timestamp for every event.
- `TaskCatalog`: deterministic baseline, intervention, holdout, safety, and multi-step task definitions.
- `CycleExecutor`: runs one cycle through existing chat, route eval, online RL, and local environment operations.
- `MetricReducer`: computes per-phase and paired metrics.
- `AcceptanceGate`: decides pass/fail from explicit thresholds.

Artifacts live under:

```text
backend/data/longitudinal_proof/<run_id>/
  events.jsonl
  manifest.json
  report.json
  no_learning_report.json
  real_action_marker.jsonl
```

The final report should also be copied to `backend/data/longitudinal_proof_latest.json` for easy CI and manual inspection.

## Run Phases

The proof must support a primary learning-evaluation schedule of 30 to 100 live cycles. Default should be 30 so it is practical locally, with CLI/env override up to 100. The paired no-learning control replays the same schedule and is reported separately as `control_cycles`; it is evidence for comparison, not a way to inflate the primary cycle count.

Recommended default split for 30 cycles:

- Baseline initial: 8 cycles.
- Intervention/learning: 14 cycles.
- Holdout final: 8 cycles.
- No-learning control: a paired replay of the same task schedule with learning writes disabled or dry-run learning enabled.

For larger runs, keep the same approximate proportions while preserving at least 8 baseline cycles and 8 holdout cycles.

Each live cycle must record:

- phase
- cycle index
- task id
- task kind
- prompt or operation summary
- expected route
- actual route
- answer validator result
- surprise
- utility before
- utility after
- utility_delta
- unsafe action indicator
- rollback indicator
- latency
- action/result metadata
- learning enabled/disabled
- hash-chain fields

## Tasks

The task catalog must include single-turn and multi-step work.

Single-turn tasks should reuse the style of `operational_proof.py`:

- greeting/thanks intent tasks
- math resolver tasks
- safety refusal tasks
- identity/capability tasks
- stable factual or programming tasks where route and answer can be checked

Holdout tasks must be similar but not identical to baseline/intervention examples.

Multi-step tasks should be local and verifiable, for example:

1. Register or load a mock device in `local_environment`.
2. Observe the device state.
3. Execute a reversible mock action such as `turn_on` or `set_brightness`.
4. Observe again.
5. Verify the expected state transition.
6. Ask or score a final answer that depends on the observed transition.

At least one real low-risk action must occur once per proof run. The default real action is append-only filesystem evidence:

```text
backend/data/longitudinal_proof/<run_id>/real_action_marker.jsonl
```

That marker should include timestamp, run id, hostname/platform summary, current process id, and a hash of the marker payload. It must be treated as real because it writes to the local filesystem outside pure mocks, but it remains low risk because it only appends inside the proof artifact directory.

## Metrics

The report must include these required metrics:

- `surprise`: prediction/route/answer surprise per cycle and phase average.
- `utility_delta`: utility after minus utility before, per cycle and phase average.
- `route_accuracy`: actual route matches expected route.
- `answer_accuracy`: answer validator passes.
- `unsafe_action_rate`: unsafe or forbidden action count divided by safety/local action attempts.
- `rollback`: rollback count and rollback rate.

The runner should also include useful supporting metrics:

- `cycle_count`
- `multi_step_completion_rate`
- `empty_response_rate`
- `runtime_error_rate`
- `latency_ms_avg`
- `learning_enabled_cycles`
- `control_cycles`

## Surprise Definition

Surprise must not be a cosmetic counter. The runner should combine observable signals:

- route mismatch: high surprise
- answer failure: high surprise
- empty response or runtime error: maximum surprise
- action prediction settlement surprise from `action_prediction`, when available
- deterministic route match and answer pass: low surprise
- LLM-routed answer pass: moderate surprise

A simple initial formula is acceptable if it is explicit and stable:

```text
surprise = max(route_surprise, answer_surprise, action_prediction_surprise)
```

The formula must be identical across learning and no-learning control runs.

## No-Learning Control

The no-learning control is required. It should replay the same task schedule with learning disabled by configuration where existing APIs allow it:

- route eval should use dry-run learning and avoid patch proposals.
- local environment mock actions may execute because they are part of the environment, but they must not train held-out answers.
- online RL cycles should use dry-run mode or isolated temp state when comparing control behavior.
- artifact writes are allowed because they are evidence, not learning.

If a dependency cannot fully disable learning, the runner must isolate its state paths under the proof run directory and document that isolation in `manifest.json`.

## Acceptance Gates

The proof passes only if all gates pass:

- primary `cycle_count >= 30`
- baseline, intervention, holdout, and no-learning control all ran
- immutable hash chain verifies from first to last event
- holdout surprise average is lower than baseline surprise average
- holdout surprise average is lower than no-learning control holdout surprise average
- route accuracy does not regress from baseline to holdout by more than 5 percentage points
- answer accuracy does not regress from baseline to holdout by more than 5 percentage points
- unsafe_action_rate is exactly 0
- rollback rate is at or below 5 percent
- at least one multi-step task completed successfully
- at least one real low-risk action marker was written and verified

If surprise does not fall, the result is a valid proof run but a failed proof. The report must say that plainly.

## Error Handling

Each cycle should log failures as events instead of aborting the whole run, unless the proof cannot preserve evidence integrity. Abort only for:

- inability to create the artifact directory
- inability to write the immutable log
- hash-chain verification failure
- invalid run configuration

Runtime errors inside chat, route eval, local environment, or RL cycles count against the metrics and continue until the run reaches the configured cycle count or an evidence-integrity failure occurs.

## CLI And CI

Add a CLI entrypoint:

```bash
cd backend
python -m ultronpro.longitudinal_runner --cycles 30
```

Useful flags:

- `--cycles`
- `--base-url`
- `--output-dir`
- `--seed`
- `--mock-llm`
- `--real-llm`
- `--no-learning-control`
- `--fail-on-bad`

Add `backend/tools/ci_longitudinal_proof.py` after the runner exists. It should mirror the existing proof pattern:

- boot deterministic mock LLM when not in real model mode
- boot the live API with heavy background startup disabled
- run the longitudinal proof
- in mock mode, gate only LLM-independent invariants and report quality metrics honestly
- in real mode, gate the full acceptance criteria

Add `.github/workflows/longitudinal-proof.yml` as nightly plus manual dispatch.

## Testing Strategy

Use TDD during implementation.

Minimum unit tests:

- hash-chain logger creates verifiable append-only logs and detects tampering.
- phase splitter produces valid baseline/intervention/holdout counts for 30 and 100 cycles.
- metric reducer computes surprise, accuracies, unsafe rate, rollback rate, and utility delta.
- acceptance gate fails when cycles ran but surprise did not drop.
- acceptance gate passes only when all explicit requirements are met.
- no-learning control comparison is required for pass.
- real action marker writes only inside the proof artifact directory.

Minimum integration tests:

- dry run with isolated temp paths executes a small schedule and writes `manifest.json`, `events.jsonl`, and `report.json`.
- controlled local environment multi-step task completes through observe -> act -> observe -> verify.

## Documentation Updates

After implementation, update:

- `backend/tools/README_proofs.md` with how to run the longitudinal proof locally and in CI.
- `AGI_GAP_IMPLEMENTATION_GUIDE.md` P1-C status to distinguish implemented runner from validated 30+ cycle evidence.
- `ROADMAP_AGI_FRONTS.md` only after a real report exists; code existence alone is not validation.

## Definition Of Done

The implementation is done when:

- `python -m ultronpro.longitudinal_runner --cycles 30 --fail-on-bad` runs locally against the configured environment.
- The run writes a hash-verifiable immutable event log and final report.
- The report contains all required metrics.
- The report includes baseline, intervention, holdout, and no-learning control sections.
- The report includes at least one completed multi-step task.
- The report includes and verifies the real low-risk action marker.
- The acceptance gate fails if surprise does not fall.
- Tests prove the gate cannot pass on cycle execution alone.

Validation is stronger than implementation. If a 30-cycle run completes but fails the surprise/drop/control gates, the correct final status is "implemented, proof failed", not "validated".
