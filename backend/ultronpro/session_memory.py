from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any


def _db_path() -> Path:
    from ultronpro import store

    return Path(store.DB_PATH)


def _connect() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=5000")
    except Exception:
        pass
    _ensure_schema(conn)
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS pre_causal_memory(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          created_at REAL NOT NULL,
          updated_at REAL NOT NULL,
          scope TEXT NOT NULL,
          session_id TEXT NOT NULL DEFAULT '',
          key TEXT NOT NULL,
          value TEXT NOT NULL,
          confidence REAL NOT NULL DEFAULT 1.0,
          source TEXT,
          meta_json TEXT,
          UNIQUE(scope, session_id, key)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pre_causal_memory_lookup ON pre_causal_memory(scope, session_id, key)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pre_causal_memory_updated ON pre_causal_memory(updated_at)")


def _pack(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, default=str)


def _unpack(value: str) -> Any:
    text = str(value or "")
    if not text:
        return ""
    try:
        return json.loads(text)
    except Exception:
        return text


def set_value(
    session_id: str | None,
    key: str,
    value: Any,
    *,
    scope: str = "session",
    confidence: float = 1.0,
    source: str = "pre_causal_router",
    meta: dict[str, Any] | None = None,
) -> None:
    sid = "" if scope == "long_term" else str(session_id or "default")[:120]
    now = time.time()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO pre_causal_memory(created_at, updated_at, scope, session_id, key, value, confidence, source, meta_json)
            VALUES(?,?,?,?,?,?,?,?,?)
            ON CONFLICT(scope, session_id, key) DO UPDATE SET
              updated_at=excluded.updated_at,
              value=excluded.value,
              confidence=excluded.confidence,
              source=excluded.source,
              meta_json=excluded.meta_json
            """,
            (
                now,
                now,
                str(scope or "session")[:40],
                sid,
                str(key or "")[:120],
                _pack(value)[:12000],
                max(0.0, min(1.0, float(confidence or 1.0))),
                str(source or "")[:120],
                json.dumps(meta or {}, ensure_ascii=False, default=str)[:4000],
            ),
        )


def get_value(session_id: str | None, key: str, *, include_long_term: bool = True) -> dict[str, Any] | None:
    sid = str(session_id or "default")[:120]
    lookups: list[tuple[str, str]] = [("session", sid)]
    if include_long_term:
        lookups.append(("long_term", ""))
    with _connect() as conn:
        for scope, scope_sid in lookups:
            row = conn.execute(
                """
                SELECT * FROM pre_causal_memory
                WHERE scope=? AND session_id=? AND key=?
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (scope, scope_sid, str(key or "")[:120]),
            ).fetchone()
            if row:
                data = dict(row)
                data["value"] = _unpack(str(data.get("value") or ""))
                try:
                    data["meta"] = json.loads(str(data.get("meta_json") or "{}"))
                except Exception:
                    data["meta"] = {}
                return data
    return None


def get_first(session_id: str | None, keys: list[str], *, include_long_term: bool = True) -> dict[str, Any] | None:
    for key in keys:
        hit = get_value(session_id, key, include_long_term=include_long_term)
        if hit:
            return hit
    return None


def recent_context(session_id: str | None, *, prefix: str = "context.", limit: int = 8) -> list[dict[str, Any]]:
    sid = str(session_id or "default")[:120]
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM pre_causal_memory
            WHERE scope='session' AND session_id=? AND key LIKE ?
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (sid, f"{prefix}%", max(1, min(50, int(limit or 8)))),
        ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        data = dict(row)
        data["value"] = _unpack(str(data.get("value") or ""))
        try:
            data["meta"] = json.loads(str(data.get("meta_json") or "{}"))
        except Exception:
            data["meta"] = {}
        out.append(data)
    return out


def remember_user_fact(session_id: str | None, key: str, value: str, *, source_query: str = "") -> None:
    payload_meta = {"source_query": str(source_query or "")[:500], "kind": "user_fact"}
    for scope in ("session", "long_term"):
        set_value(session_id, key, value, scope=scope, source="pre_causal_user_fact", meta=payload_meta)
    try:
        from ultronpro import store

        label = str(key or "fato").replace("_", " ")
        store.add_autobiographical_memory(
            f"O usuario informou que {label} e {value}.",
            memory_type="semantic",
            importance=0.72,
            decay_rate=0.001,
            content_json=json.dumps({"key": key, "value": value, "source": "pre_causal_session_memory"}, ensure_ascii=False),
        )
    except Exception:
        pass

