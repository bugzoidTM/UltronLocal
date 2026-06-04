# OpenAI-Compatible Qwen API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a public OpenAI-compatible API surface for the Qwen model behind UltronPRO.

**Architecture:** Create a small FastAPI router for `/v1/models` and `/v1/chat/completions`. The router validates Bearer auth, adapts OpenAI chat payloads to the existing Qwen `/generate` interface, and returns OpenAI-compatible responses.

**Tech Stack:** Python, FastAPI, Pydantic, pytest, httpx-style request forwarding already used by the project.

---

### Task 1: Router Core

**Files:**
- Create: `backend/ultronpro/api/openai_compat.py`
- Create: `backend/test_openai_compat_api.py`

- [ ] **Step 1: Write failing tests**

Add tests for unauthorized requests, `/v1/models`, and request-to-Qwen payload mapping.

- [ ] **Step 2: Run test to verify RED**

Run: `python -m pytest backend/test_openai_compat_api.py -q`

Expected: fail because `ultronpro.api.openai_compat` does not exist.

- [ ] **Step 3: Implement minimal router**

Create Pydantic models, auth helper, message compiler, Qwen client function, and routes.

- [ ] **Step 4: Run test to verify GREEN**

Run: `python -m pytest backend/test_openai_compat_api.py -q`

Expected: tests pass.

### Task 2: App Integration

**Files:**
- Modify: `backend/ultronpro/main.py`

- [ ] **Step 1: Write failing integration test**

Extend tests to verify the router can be included in a FastAPI app.

- [ ] **Step 2: Implement app include**

Import `openai_compat_router` and call `app.include_router(openai_compat_router)`.

- [ ] **Step 3: Run focused tests**

Run: `python -m pytest backend/test_openai_compat_api.py -q`

Expected: tests pass.

### Task 3: Operator Handoff

**Files:**
- Create: `backend/data/openai_compat_api_key.example.txt`

- [ ] **Step 1: Generate a strong key**

Run a local Python command using `secrets.token_urlsafe(32)`.

- [ ] **Step 2: Document usage**

Record the base URL, model name, and curl example in the final response.

- [ ] **Step 3: Verify no real secret is committed**

Run: `git status --short backend/data/openai_compat_api_key.txt backend/data/openai_compat_api_key.example.txt`

Expected: real key file remains untracked/private or absent from committed docs.
