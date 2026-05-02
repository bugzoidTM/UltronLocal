"""Unified sensory event bus for UltronPro.

Every external or internal input enters the system as a normalized event with
an explicit consent scope. The bus uses asyncio.Queue for ingestion and reuses
the existing SQLite-backed store for audit, experiences, autobiographical
memory, and Global Workspace publication.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

from ultronpro import store


SOURCE_TYPES = {"vision", "audio", "logs", "browser", "filesystem", "tool"}
CONSENT_SCOPES = {
    "user_provided",
    "explicit_capture",
    "system_internal",
    "public_web",
    "filesystem_allowed",
    "tool_output",
    "diagnostic_log",
    "restricted",
}
DEFAULT_CONSENT_BY_SOURCE = {
    "vision": "explicit_capture",
    "audio": "explicit_capture",
    "logs": "diagnostic_log",
    "browser": "public_web",
    "filesystem": "filesystem_allowed",
    "tool": "tool_output",
}
DEFAULT_MODALITY_BY_SOURCE = {
    "vision": "image",
    "audio": "audio",
    "logs": "log",
    "browser": "web",
    "filesystem": "file",
    "tool": "tool",
}

SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|token|secret|password|senha)\s*[:=]\s*([^\s,;]{8,})"),
    re.compile(r"(?i)(bearer\s+)([a-z0-9._\-]{16,})"),
]


def _now() -> int:
    return int(time.time())


def _clip01(value: float) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except Exception:
        return 0.0


def _json_dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str)


def _jsonable(payload: Any) -> Any:
    try:
        json.dumps(payload, ensure_ascii=False, default=str)
        return payload
    except Exception:
        return str(payload)


def _redact_text(text: str) -> tuple[str, list[dict[str, Any]]]:
    redactions: list[dict[str, Any]] = []
    out = str(text or "")
    for pattern in SECRET_PATTERNS:
        def repl(match: re.Match[str]) -> str:
            redactions.append({"pattern": pattern.pattern, "start": match.start(), "end": match.end()})
            if len(match.groups()) >= 2:
                return f"{match.group(1)}=[REDACTED]"
            return "[REDACTED]"

        out = pattern.sub(repl, out)
    return out, redactions


def _redact_payload(payload: Any) -> tuple[Any, list[dict[str, Any]]]:
    if isinstance(payload, str):
        return _redact_text(payload)
    if isinstance(payload, dict):
        out: dict[str, Any] = {}
        redactions: list[dict[str, Any]] = []
        for key, value in payload.items():
            cleaned, found = _redact_payload(value)
            out[str(key)] = cleaned
            for item in found:
                item = dict(item)
                item["path"] = str(key) if not item.get("path") else f"{key}.{item['path']}"
                redactions.append(item)
        return out, redactions
    if isinstance(payload, list):
        out_list = []
        redactions = []
        for idx, value in enumerate(payload):
            cleaned, found = _redact_payload(value)
            out_list.append(cleaned)
            for item in found:
                item = dict(item)
                item["path"] = str(idx) if not item.get("path") else f"{idx}.{item['path']}"
                redactions.append(item)
        return out_list, redactions
    return _jsonable(payload), []


def _infer_text(payload: Any) -> str:
    if payload is None:
        return ""
    if isinstance(payload, str):
        return payload
    if isinstance(payload, dict):
        for key in ("text", "message", "description", "summary", "transcript", "url", "path", "action"):
            val = payload.get(key)
            if val:
                return str(val)
        return _json_dumps(payload)[:1200]
    return str(payload)


def _content_hash(event: "SensoryEvent") -> str:
    raw = _json_dumps({"text": event.content_text, "payload": event.payload})
    return hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()[:24]


def _audit_payload(event: "SensoryEvent") -> dict[str, Any]:
    payload = event.to_dict()
    payload["content_hash"] = _content_hash(event)
    if not event.allow_persist:
        payload["content_text"] = "[NOT_PERSISTED_BY_CONSENT]"
        payload["payload"] = "[NOT_PERSISTED_BY_CONSENT]"
        payload["summary"] = f"{event.source_type}:{event.source}:restricted"
    return payload


@dataclass
class SensoryEvent:
    event_id: str
    created_at: int
    source_type: str
    source: str
    modality: str
    content_text: str
    payload: Any
    consent_scope: str
    consent_basis: str
    consent_actor: str = "system"
    consent_expires_at: int | None = None
    allow_persist: bool = True
    allow_workspace: bool = True
    retention_policy: str = "default"
    sensitivity: str = "normal"
    salience: float = 0.45
    correlation_id: str = ""
    parent_event_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    redactions: list[dict[str, Any]] = field(default_factory=list)

    @property
    def summary(self) -> str:
        text = self.content_text.strip()
        if not text:
            text = f"{self.source_type}:{self.source}"
        return text[:240]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["payload"] = _jsonable(self.payload)
        data["summary"] = self.summary
        data["consent"] = {
            "scope": self.consent_scope,
            "basis": self.consent_basis,
            "actor": self.consent_actor,
            "expires_at": self.consent_expires_at,
            "allow_persist": self.allow_persist,
            "allow_workspace": self.allow_workspace,
            "retention_policy": self.retention_policy,
        }
        return data


def normalize_event(
    *,
    source_type: str,
    payload: Any,
    source: str | None = None,
    modality: str | None = None,
    content_text: str | None = None,
    metadata: dict[str, Any] | None = None,
    consent_scope: str | None = None,
    consent_basis: str | None = None,
    consent_actor: str = "system",
    consent_expires_at: int | None = None,
    allow_persist: bool = True,
    allow_workspace: bool = True,
    retention_policy: str = "default",
    sensitivity: str | None = None,
    salience: float | None = None,
    correlation_id: str = "",
    parent_event_id: str = "",
) -> SensoryEvent:
    stype = str(source_type or "").strip().lower()
    if stype not in SOURCE_TYPES:
        raise ValueError(f"invalid sensory source_type: {source_type!r}")

    scope = str(consent_scope or DEFAULT_CONSENT_BY_SOURCE[stype]).strip().lower()
    if scope not in CONSENT_SCOPES:
        raise ValueError(f"invalid consent_scope: {consent_scope!r}")

    inferred_text = content_text if content_text is not None else _infer_text(payload)
    redacted_text, text_redactions = _redact_text(str(inferred_text or ""))
    redacted_payload, payload_redactions = _redact_payload(payload)
    redactions = text_redactions + payload_redactions
    sens = str(sensitivity or ("high" if redactions else "normal")).strip().lower()
    if scope == "restricted":
        allow_workspace = False

    basis = str(consent_basis or f"default_policy:{scope}").strip()
    return SensoryEvent(
        event_id=f"se_{_now()}_{uuid.uuid4().hex[:10]}",
        created_at=_now(),
        source_type=stype,
        source=str(source or stype)[:120],
        modality=str(modality or DEFAULT_MODALITY_BY_SOURCE[stype])[:40],
        content_text=redacted_text[:8000],
        payload=_jsonable(redacted_payload),
        metadata=dict(metadata or {}),
        consent_scope=scope,
        consent_basis=basis[:240],
        consent_actor=str(consent_actor or "system")[:80],
        consent_expires_at=consent_expires_at,
        allow_persist=bool(allow_persist),
        allow_workspace=bool(allow_workspace),
        retention_policy=str(retention_policy or "default")[:80],
        sensitivity=sens[:40],
        salience=_clip01(0.65 if redactions and salience is None else (salience if salience is not None else 0.45)),
        correlation_id=str(correlation_id or "")[:120],
        parent_event_id=str(parent_event_id or "")[:120],
        redactions=redactions,
    )


class SensoryBus:
    def __init__(self, maxsize: int = 1000, store_module: Any = None):
        self.queue: asyncio.Queue[SensoryEvent] = asyncio.Queue(maxsize=max(1, int(maxsize or 1000)))
        self.store = store_module or store
        self._worker: asyncio.Task | None = None
        self._running = False
        self.processed_count = 0
        self.failed_count = 0
        self.last_error: str | None = None

    async def submit(self, **kwargs: Any) -> SensoryEvent:
        event = normalize_event(**kwargs)
        await self.queue.put(event)
        return event

    def submit_nowait(self, **kwargs: Any) -> SensoryEvent:
        event = normalize_event(**kwargs)
        self.queue.put_nowait(event)
        return event

    def start(self) -> None:
        if self._worker and not self._worker.done():
            return
        self._running = True
        self._worker = asyncio.create_task(self._run_forever())

    async def stop(self, *, drain: bool = True) -> None:
        self._running = False
        if drain:
            await self.queue.join()
        if self._worker and not self._worker.done():
            self._worker.cancel()
            try:
                await self._worker
            except asyncio.CancelledError:
                pass

    async def _run_forever(self) -> None:
        while self._running:
            await self.process_one()

    async def process_one(self, timeout: float | None = None) -> dict[str, Any] | None:
        try:
            if timeout is None:
                event = await self.queue.get()
            else:
                event = await asyncio.wait_for(self.queue.get(), timeout=float(timeout))
        except asyncio.TimeoutError:
            return None

        try:
            result = await asyncio.to_thread(self._persist_event, event)
            self.processed_count += 1
            return result
        except Exception as exc:
            self.failed_count += 1
            self.last_error = f"{type(exc).__name__}: {str(exc)[:240]}"
            raise
        finally:
            self.queue.task_done()

    async def drain(self, limit: int | None = None) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        max_items = int(limit) if limit is not None else self.queue.qsize()
        while max_items > 0 and not self.queue.empty():
            item = await self.process_one(timeout=0.01)
            if item:
                out.append(item)
            max_items -= 1
        return out

    def _persist_event(self, event: SensoryEvent) -> dict[str, Any]:
        payload = _audit_payload(event)
        source_id = f"sensory:{event.source_type}:{event.source}"
        audit_meta = _json_dumps(payload)
        audit_id = self.store.db.add_event(
            kind=f"sensory_{event.source_type}",
            text=f"{event.source_type}:{event.summary}",
            meta_json=audit_meta,
        )

        experience_id = None
        if event.allow_persist:
            experience_id = self.store.db.add_experience(
                user_id=event.consent_actor if event.consent_actor != "system" else None,
                source_id=source_id,
                modality=event.modality,
                text=event.content_text,
                mime=str(event.metadata.get("mime") or "") or None,
                blob_path=event.metadata.get("blob_path"),
            )
            if event.salience >= 0.55:
                self.store.db.add_autobiographical_memory(
                    text=f"[sensory:{event.source_type}] {event.summary}",
                    memory_type="short_term",
                    importance=event.salience,
                    decay_rate=0.02,
                    content_json=_json_dumps({"event_id": event.event_id, "experience_id": experience_id, "consent": payload["consent"]}),
                )

        workspace_id = None
        if event.allow_workspace:
            workspace_id = self.store.publish_workspace(
                module="sensory_bus",
                channel=f"sensory.{event.source_type}",
                payload_json=_json_dumps({
                    "event_id": event.event_id,
                    "source_type": event.source_type,
                    "source": event.source,
                    "modality": event.modality,
                    "summary": event.summary,
                    "consent": payload["consent"],
                    "audit_event_id": audit_id,
                    "experience_id": experience_id,
                    "sensitivity": event.sensitivity,
                    "redacted": bool(event.redactions),
                }),
                salience=event.salience,
                ttl_sec=900,
            )

        return {
            "ok": True,
            "event_id": event.event_id,
            "audit_event_id": audit_id,
            "experience_id": experience_id,
            "workspace_id": workspace_id,
            "consent_scope": event.consent_scope,
            "queued_remaining": self.queue.qsize(),
        }

    def status(self) -> dict[str, Any]:
        return {
            "ok": True,
            "queue_size": self.queue.qsize(),
            "processed_count": self.processed_count,
            "failed_count": self.failed_count,
            "last_error": self.last_error,
            "worker_active": self._worker is not None and not self._worker.done(),
            "source_types": sorted(SOURCE_TYPES),
            "consent_scopes": sorted(CONSENT_SCOPES),
        }


_bus: SensoryBus | None = None


def get_sensory_bus() -> SensoryBus:
    global _bus
    if _bus is None:
        _bus = SensoryBus()
    return _bus


async def submit_event(**kwargs: Any) -> SensoryEvent:
    return await get_sensory_bus().submit(**kwargs)


async def submit_vision(payload: Any, **kwargs: Any) -> SensoryEvent:
    return await submit_event(source_type="vision", payload=payload, **kwargs)


async def submit_audio(payload: Any, **kwargs: Any) -> SensoryEvent:
    return await submit_event(source_type="audio", payload=payload, **kwargs)


async def submit_log(payload: Any, **kwargs: Any) -> SensoryEvent:
    return await submit_event(source_type="logs", payload=payload, **kwargs)


async def submit_browser(payload: Any, **kwargs: Any) -> SensoryEvent:
    return await submit_event(source_type="browser", payload=payload, **kwargs)


async def submit_filesystem(payload: Any, **kwargs: Any) -> SensoryEvent:
    return await submit_event(source_type="filesystem", payload=payload, **kwargs)


async def submit_tool(payload: Any, **kwargs: Any) -> SensoryEvent:
    return await submit_event(source_type="tool", payload=payload, **kwargs)


async def process_pending(limit: int | None = None) -> list[dict[str, Any]]:
    return await get_sensory_bus().drain(limit=limit)


def status() -> dict[str, Any]:
    return get_sensory_bus().status()
