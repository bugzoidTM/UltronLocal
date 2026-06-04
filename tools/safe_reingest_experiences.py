from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


DEFAULT_REMOTE = "https://ultronpro.nutef.com"
DEFAULT_DB = Path("backend/data/ultron.db")
DEFAULT_MANIFEST = Path("backend/data/remote_reingest_manifest.json")


@dataclass(frozen=True)
class ExperienceRow:
    id: int
    created_at: float
    source_id: str | None
    modality: str
    text: str


class TransientHttpError(RuntimeError):
    pass


class PermanentHttpError(RuntimeError):
    pass


class Manifest:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.data = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"schema": 1, "successes": {}, "failures": {}}
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return {"schema": 1, "successes": {}, "failures": {}}
        raw.setdefault("schema", 1)
        raw.setdefault("successes", {})
        raw.setdefault("failures", {})
        return raw

    def is_successful(self, original_id: int) -> bool:
        return str(int(original_id)) in self.data.get("successes", {})

    def record_success(self, original_id: int, response: dict[str, Any]) -> None:
        remote_id = response.get("experience_id")
        self.data.setdefault("successes", {})[str(int(original_id))] = {
            "remote_experience_id": remote_id,
            "response": response,
            "ts": time.time(),
        }
        self.data.setdefault("failures", {}).pop(str(int(original_id)), None)
        self._save()

    def record_failure(self, original_id: int, error: str) -> None:
        self.data.setdefault("failures", {})[str(int(original_id))] = {
            "error": str(error)[:1000],
            "ts": time.time(),
        }
        self._save()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data["updated_at"] = time.time()
        _atomic_write_text(
            self.path,
            json.dumps(self.data, ensure_ascii=False, indent=2, sort_keys=True),
        )


def _atomic_write_text(path: Path, text: str, *, retries: int = 5) -> None:
    tmp_path = path.with_name(f"{path.name}.tmp")
    last_error: OSError | None = None
    for attempt in range(max(1, int(retries))):
        try:
            tmp_path.write_text(text, encoding="utf-8")
            tmp_path.replace(path)
            return
        except OSError as exc:
            last_error = exc
            time.sleep(0.05 * (2**attempt))
    if last_error is not None:
        raise last_error


class RemoteApi:
    def __init__(self, base_url: str, *, timeout: float = 60.0):
        self.base_url = str(base_url).rstrip("/")
        self.timeout = float(timeout)

    def status(self) -> dict[str, Any]:
        return self._request_json("GET", "/api/status")

    def post_ingest(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request_json("POST", "/api/ingest", payload)

    def _request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                text = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:1000]
            if exc.code == 429 or exc.code >= 500:
                raise TransientHttpError(f"HTTP {exc.code}: {detail}") from exc
            raise PermanentHttpError(f"HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise TransientHttpError(str(exc.reason)) from exc
        if not text.strip():
            return {}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise PermanentHttpError(f"invalid JSON response: {text[:500]}") from exc
        if not isinstance(parsed, dict):
            raise PermanentHttpError("expected JSON object response")
        return parsed


def read_experiences(db_path: str | Path, *, limit: int = 0, after_id: int = 0) -> list[ExperienceRow]:
    path = Path(db_path)
    if not path.exists():
        raise FileNotFoundError(path)

    sql = """
        SELECT id, created_at, source_id, modality, text
        FROM experiences
        WHERE id > ? AND text IS NOT NULL AND length(trim(text)) > 0
        ORDER BY id ASC
    """
    params: list[Any] = [int(after_id)]
    if int(limit or 0) > 0:
        sql += " LIMIT ?"
        params.append(int(limit))

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()

    return [
        ExperienceRow(
            id=int(row["id"]),
            created_at=float(row["created_at"]),
            source_id=row["source_id"],
            modality=str(row["modality"] or "text"),
            text=str(row["text"] or ""),
        )
        for row in rows
    ]


def build_payload(row: ExperienceRow) -> dict[str, str]:
    original_source = _compact_source_id(row.source_id)
    return {
        "text": row.text,
        "source_id": f"migration:local:{row.id}:{original_source}",
        "modality": row.modality or "text",
    }


def _compact_source_id(source_id: str | None) -> str:
    compact = str(source_id or "none").strip().replace("\r", " ").replace("\n", " ")
    compact = " ".join(compact.split())
    return compact[:180] or "none"


def send_with_retries(
    remote: Any,
    payload: dict[str, Any],
    *,
    retries: int = 3,
    backoff: float = 1.0,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    attempt = 0
    while True:
        attempt += 1
        try:
            return remote.post_ingest(payload)
        except TransientHttpError:
            if attempt > int(retries):
                raise
            sleep(float(backoff) * (2 ** (attempt - 1)))


def run_migration(
    *,
    db_path: str | Path,
    manifest_path: str | Path,
    remote: Any,
    limit: int = 0,
    retries: int = 3,
    dry_run: bool = False,
    sleep: Callable[[float], None] = time.sleep,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    rows = read_experiences(db_path, limit=limit)
    manifest = Manifest(manifest_path)
    summary = {
        "total_candidates": len(rows),
        "skipped_success": 0,
        "attempted": 0,
        "succeeded": 0,
        "failed": 0,
        "dry_run": bool(dry_run),
    }

    for row in rows:
        if manifest.is_successful(row.id):
            summary["skipped_success"] += 1
            continue

        payload = build_payload(row)
        if dry_run:
            summary["attempted"] += 1
            _emit_progress(progress, row.id, "dry_run", summary)
            continue

        summary["attempted"] += 1
        try:
            response = send_with_retries(remote, payload, retries=retries, sleep=sleep)
        except Exception as exc:
            summary["failed"] += 1
            manifest.record_failure(row.id, f"{type(exc).__name__}: {exc}")
            _emit_progress(progress, row.id, "failure", summary)
        else:
            summary["succeeded"] += 1
            manifest.record_success(row.id, response)
            _emit_progress(progress, row.id, "success", summary)

    return summary


def _emit_progress(
    progress: Callable[[dict[str, Any]], None] | None,
    row_id: int,
    status: str,
    summary: dict[str, Any],
) -> None:
    if progress is None:
        return
    event = dict(summary)
    event.update({"row_id": int(row_id), "status": status})
    progress(event)


def fetch_status(remote: Any) -> dict[str, Any]:
    status = remote.status()
    stats = status.get("stats") if isinstance(status, dict) else None
    if not isinstance(stats, dict):
        raise PermanentHttpError("status response did not include stats")
    return status


def _print_json(obj: Any) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Safely reingest local UltronPRO experiences through a remote API.")
    parser.add_argument("--remote", default=DEFAULT_REMOTE, help="Remote UltronPRO base URL.")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="Local SQLite database path.")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST), help="Local JSON manifest path.")
    parser.add_argument("--limit", type=int, default=0, help="Maximum rows to scan; 0 means all nonblank rows.")
    parser.add_argument("--retries", type=int, default=3, help="Transient HTTP retries per experience.")
    parser.add_argument("--timeout", type=float, default=60.0, help="HTTP timeout in seconds.")
    parser.add_argument("--progress-every", type=int, default=25, help="Print progress every N attempted rows.")
    parser.add_argument("--dry-run", action="store_true", help="Build payloads without posting to the remote API.")
    parser.add_argument("--status-only", action="store_true", help="Only fetch and print remote /api/status.")
    return parser.parse_args(argv)


def make_progress_printer(every: int) -> Callable[[dict[str, Any]], None]:
    interval = max(1, int(every or 1))

    def emit(event: dict[str, Any]) -> None:
        attempted = int(event.get("attempted") or 0)
        status = str(event.get("status") or "")
        if status == "failure" or attempted == 1 or attempted % interval == 0:
            print(
                "progress "
                f"attempted={attempted} "
                f"succeeded={int(event.get('succeeded') or 0)} "
                f"failed={int(event.get('failed') or 0)} "
                f"skipped={int(event.get('skipped_success') or 0)} "
                f"row_id={int(event.get('row_id') or 0)} "
                f"status={status}",
                file=sys.stderr,
                flush=True,
            )

    return emit


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    remote = RemoteApi(args.remote, timeout=args.timeout)

    if args.status_only:
        _print_json(fetch_status(remote))
        return 0

    before = fetch_status(remote)
    summary = run_migration(
        db_path=args.db,
        manifest_path=args.manifest,
        remote=remote,
        limit=args.limit,
        retries=args.retries,
        dry_run=args.dry_run,
        progress=make_progress_printer(args.progress_every),
    )
    after = fetch_status(remote)
    _print_json({"before": before.get("stats"), "summary": summary, "after": after.get("stats")})
    return 1 if summary.get("failed") else 0


if __name__ == "__main__":
    raise SystemExit(main())
