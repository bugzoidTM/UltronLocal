# Safe API Reingest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and run a resumable CLI that reingests local UltronPRO experiences into the remote UltronPRO API.

**Architecture:** A standalone Python module in `tools/` reads SQLite rows, tracks progress in a JSON manifest, and sends POST requests to the remote `/api/ingest` endpoint. Tests use fakes for HTTP and temporary SQLite files so they do not touch the live local or remote systems.

**Tech Stack:** Python standard library, SQLite, `pytest`, FastAPI HTTP endpoint `/api/ingest`.

---

### Task 1: Migration Core

**Files:**
- Create: `tools/safe_reingest_experiences.py`
- Create: `test_safe_reingest_experiences.py`

- [ ] **Step 1: Write failing tests**

Create tests for reading candidate experiences, building provenance payloads, and updating a manifest with successful IDs.

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest test_safe_reingest_experiences.py -q`

Expected: fail because `tools.safe_reingest_experiences` does not exist.

- [ ] **Step 3: Implement minimal core**

Create `ExperienceRow`, `Manifest`, `read_experiences`, and `build_payload`.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `python -m pytest test_safe_reingest_experiences.py -q`

Expected: all tests pass.

### Task 2: HTTP Client And CLI

**Files:**
- Modify: `tools/safe_reingest_experiences.py`
- Modify: `test_safe_reingest_experiences.py`

- [ ] **Step 1: Write failing tests**

Add tests for retrying transient HTTP failures and for `run_migration` skipping successful manifest IDs.

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest test_safe_reingest_experiences.py -q`

Expected: fail because HTTP client and runner are not implemented.

- [ ] **Step 3: Implement minimal runner**

Add `post_ingest`, `fetch_status`, `run_migration`, and `main`.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `python -m pytest test_safe_reingest_experiences.py -q`

Expected: all tests pass.

### Task 3: Execute Migration

**Files:**
- Writes runtime artifact: `backend/data/remote_reingest_manifest.json`

- [ ] **Step 1: Check remote status**

Run: `python tools/safe_reingest_experiences.py --remote https://ultronpro.nutef.com --status-only`

Expected: remote returns online status.

- [ ] **Step 2: Execute real migration**

Run: `python tools/safe_reingest_experiences.py --remote https://ultronpro.nutef.com --db backend/data/ultron.db --manifest backend/data/remote_reingest_manifest.json --limit 0`

Expected: experiences are posted and successes are recorded in the manifest.

- [ ] **Step 3: Validate final status**

Run: `python tools/safe_reingest_experiences.py --remote https://ultronpro.nutef.com --status-only`

Expected: remote experience count increases substantially.
