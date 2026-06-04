import json
import sqlite3
from pathlib import Path

import pytest

from tools.safe_reingest_experiences import (
    Manifest,
    TransientHttpError,
    build_payload,
    read_experiences,
    run_migration,
    send_with_retries,
)


def _make_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            CREATE TABLE experiences(
                id INTEGER PRIMARY KEY,
                created_at REAL NOT NULL,
                processed_at REAL,
                user_id TEXT,
                source_id TEXT,
                modality TEXT NOT NULL DEFAULT 'text',
                text TEXT,
                blob_path TEXT,
                mime TEXT,
                embedding_json TEXT,
                curated_at REAL,
                archived_at REAL,
                utility_score REAL
            )
            """
        )
        conn.executemany(
            """
            INSERT INTO experiences(id, created_at, source_id, modality, text)
            VALUES(?,?,?,?,?)
            """,
            [
                (1, 10.0, "alpha", "text", "primeira experiencia"),
                (2, 11.0, None, "chat", ""),
                (3, 12.0, "beta", "lightrag_document", "terceira experiencia"),
            ],
        )
        conn.commit()
    finally:
        conn.close()


def test_read_experiences_returns_nonblank_rows_in_id_order(tmp_path: Path):
    db_path = tmp_path / "ultron.db"
    _make_db(db_path)

    rows = read_experiences(db_path, limit=0)

    assert [row.id for row in rows] == [1, 3]
    assert rows[0].text == "primeira experiencia"
    assert rows[1].modality == "lightrag_document"


def test_build_payload_preserves_text_and_marks_local_provenance(tmp_path: Path):
    db_path = tmp_path / "ultron.db"
    _make_db(db_path)
    row = read_experiences(db_path, limit=1)[0]

    payload = build_payload(row)

    assert payload == {
        "text": "primeira experiencia",
        "source_id": "migration:local:1:alpha",
        "modality": "text",
    }


def test_manifest_records_success_and_reload_skips_id(tmp_path: Path):
    manifest_path = tmp_path / "manifest.json"
    manifest = Manifest(manifest_path)

    manifest.record_success(42, {"experience_id": 9001})

    saved = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert saved["successes"]["42"]["remote_experience_id"] == 9001
    assert Manifest(manifest_path).is_successful(42)


def test_manifest_retries_transient_write_error(tmp_path: Path, monkeypatch):
    manifest_path = tmp_path / "manifest.json"
    original_write_text = Path.write_text
    calls = {"count": 0}

    def flaky_write_text(self, *args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise OSError(22, "Invalid argument")
        return original_write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", flaky_write_text)

    Manifest(manifest_path).record_success(7, {"experience_id": 70})

    assert calls["count"] == 2
    assert Manifest(manifest_path).is_successful(7)


class _FlakyRemote:
    def __init__(self):
        self.calls = 0

    def post_ingest(self, payload):
        self.calls += 1
        if self.calls == 1:
            raise TransientHttpError("temporary unavailable")
        return {"status": "ok", "experience_id": 55}


def test_send_with_retries_retries_transient_failure_without_sleeping():
    remote = _FlakyRemote()

    response = send_with_retries(
        remote,
        {"text": "x", "source_id": "migration:local:1:alpha", "modality": "text"},
        retries=2,
        sleep=lambda seconds: None,
    )

    assert response["experience_id"] == 55
    assert remote.calls == 2


class _RecordingRemote:
    def __init__(self):
        self.payloads = []

    def post_ingest(self, payload):
        self.payloads.append(payload)
        return {"status": "ok", "experience_id": 1000 + len(self.payloads)}


def test_run_migration_skips_successful_manifest_ids(tmp_path: Path):
    db_path = tmp_path / "ultron.db"
    manifest_path = tmp_path / "manifest.json"
    _make_db(db_path)
    Manifest(manifest_path).record_success(1, {"experience_id": 777})
    remote = _RecordingRemote()

    summary = run_migration(
        db_path=db_path,
        manifest_path=manifest_path,
        remote=remote,
        limit=0,
        sleep=lambda seconds: None,
    )

    assert summary["total_candidates"] == 2
    assert summary["skipped_success"] == 1
    assert summary["succeeded"] == 1
    assert [payload["source_id"] for payload in remote.payloads] == ["migration:local:3:beta"]
    assert Manifest(manifest_path).is_successful(3)


def test_run_migration_reports_progress_events(tmp_path: Path):
    db_path = tmp_path / "ultron.db"
    manifest_path = tmp_path / "manifest.json"
    _make_db(db_path)
    remote = _RecordingRemote()
    events = []

    run_migration(
        db_path=db_path,
        manifest_path=manifest_path,
        remote=remote,
        limit=0,
        sleep=lambda seconds: None,
        progress=events.append,
    )

    assert [event["row_id"] for event in events] == [1, 3]
    assert all(event["status"] == "success" for event in events)
