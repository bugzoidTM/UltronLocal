# Controlled-environment proofs

These tools take the two proofs that the 2026-06-13 reproducibility audit flagged as
**not reproducible offline** and make them runnable in a controlled environment (CI or
local), with **honest scoping** of what they actually validate.

| Tool | What it does | What it honestly validates |
|---|---|---|
| `mock_llm_server.py` | Deterministic, gold-blind LLM stub. Speaks Ollama (`/api/chat`), OpenAI-compat (`/v1/chat/completions`) and health endpoints. | Nothing on its own — it holds the language layer **constant** so the proofs become reproducible. Its answers are NOT correct-by-design (no gold knowledge), so it cannot fake a grade. |
| `ci_pressure_proof.py` | Runs `pressure_benchmark` against the mock. | Harness executes (all 5 axes scored) **+** routing/graceful-degradation recovers under `provider_dropout` & `rate_limit_cascade`. Does **not** assert the `maturity_index`/`MATURE` grade (mock-derived). |
| `ci_operational_proof.py` | Boots the real API (background loops + LLM autostart off), runs `scratch/operational_proof.py` short mode. | Completion + zero crashes + zero unsafe actions + zero empty responses + `route_accuracy_end >= floor`. Does **not** gate `answer_accuracy`/`generalization` (need a real LLM for the 10 LLM-routed probes). |

## Run locally

```bash
cd backend
python tools/ci_pressure_proof.py            # ~seconds
python tools/ci_operational_proof.py         # boots server, ~under a minute
```

## Longitudinal proof

`ultronpro.longitudinal_runner` is the real longitudinal proof runner for P1-C. It executes a primary 30-100 cycle schedule split into baseline, intervention/learning, and holdout, then replays the same schedule as a no-learning control. It writes hash-chained JSONL evidence and a final report under `backend/data/longitudinal_proof/<run_id>/`.

Run locally:

```bash
cd backend
python -m ultronpro.longitudinal_runner --cycles 30 --fail-on-bad
```

Run the controlled CI wrapper:

```bash
cd backend
python tools/ci_longitudinal_proof.py
```

Mock CI mode gates evidence integrity, safety, liveness, control execution, and the real low-risk marker. The runner can also prove controlled local action-prediction learning by requiring holdout surprise to beat both baseline and a no-learning control. That is evidence of local calibration over cycles, not evidence that a mock LLM improved its answer quality; real-model runs are still required for LLM capability claims.

## Grade against a real model

Point the providers at a real endpoint and set `ULTRON_PROOF_REAL_LLM=1`. Then the
runners additionally assert the genuine grade (pressure: `maturity_index >= threshold`;
operational: the proof's full minimum criteria, including answer accuracy).

```bash
cd backend
ULTRON_PROOF_REAL_LLM=1 OLLAMA_BASE_URL_LOCAL=http://<real-endpoint> \
  python tools/ci_pressure_proof.py
```

## CI

* `.github/workflows/pressure-proof.yml` — runs on every PR to `main` (gate) + manual.
* `.github/workflows/operational-proof.yml` — nightly cron + manual (`workflow_dispatch`),
  with `real_llm` / `max_tasks` / `min_route_acc` inputs.
* `.github/workflows/longitudinal-proof.yml` - nightly cron + manual (`workflow_dispatch`),
  with `real_llm` / `cycles` inputs.

Both default to the deterministic mock so they are reliable on free runners. A self-hosted
runner with the real `ultronpro_infer` model can dispatch them with `real_llm=1` to grade
the production model.
