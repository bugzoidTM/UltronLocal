# Safe API Reingest Design

## Goal

Transfer local UltronPRO experiences from `backend/data/ultron.db` to `https://ultronpro.nutef.com/` through the public `/api/ingest` endpoint, without direct writes to the remote database.

## Current State

- Local `/api/status`: 8948 experiences, 4681 triples.
- Remote `/api/status`: 3 experiences, 5 triples.
- Both environments expose the same FastAPI contract for `/api/ingest`.
- `/api/ingest` stores the raw experience and re-extracts triples in the receiving environment.

## Approach

Create a standalone migration CLI under `tools/` that reads local SQLite experiences in ascending ID order and posts each one to the remote API. Each remote ingest keeps the original text and modality, while adding migration provenance to `source_id`.

The CLI must be resumable through a local manifest file. It should skip IDs already recorded as successful, retry transient HTTP failures with exponential backoff, and write a summary report at the end.

## Data Flow

1. Read rows from local `experiences`.
2. Skip blank text and rows already successful in the manifest.
3. Build payload:
   - `text`: original text.
   - `modality`: original modality or `text`.
   - `source_id`: `migration:local:<original_id>:<original_source_id>`.
4. POST to `<remote>/api/ingest`.
5. Record success or failure in manifest.
6. Validate by comparing remote `/api/status` before and after.

## Safety

- No remote database access.
- No local data mutation except the manifest file.
- Dry-run support remains available, but the user requested real execution.
- Default batch size is conservative to avoid overwhelming the remote service.
- Failed IDs remain retryable in a later run.

## Testing

Add unit tests for row selection, payload construction, manifest behavior, and HTTP retry handling using local fakes.
