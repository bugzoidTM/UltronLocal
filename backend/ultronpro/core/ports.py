from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any, Protocol


def payload_to_json(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value if value is not None else {}, ensure_ascii=False)
    except Exception:
        return json.dumps({"value": str(value)[:2000]}, ensure_ascii=False)


class EventSink(Protocol):
    def add_event(self, kind: str, text: str, meta: dict[str, Any] | str | None = None) -> int | None:
        ...


class WorkspacePublisher(Protocol):
    def publish(
        self,
        module: str,
        channel: str,
        payload: dict[str, Any] | str | None,
        *,
        salience: float = 0.5,
        ttl_sec: int = 900,
    ) -> int | None:
        ...


class MemoryWriter(Protocol):
    def add_experience(self, *, text: str, source_id: str | None = None, modality: str = "text") -> int | None:
        ...

    def add_insight(
        self,
        *,
        kind: str,
        title: str,
        text: str,
        priority: int = 3,
        source_id: str | None = None,
        meta: dict[str, Any] | str | None = None,
    ) -> int | None:
        ...


class MemoryReader(Protocol):
    def search_triples(self, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
        ...

    def search_insights(self, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
        ...

    def list_experiences(self, *, limit: int = 10) -> list[dict[str, Any]]:
        ...


class WorkspaceReader(Protocol):
    def read_workspace(
        self,
        *,
        channels: list[str] | None = None,
        limit: int = 30,
        include_expired: bool = False,
    ) -> list[dict[str, Any]]:
        ...


class ActionReader(Protocol):
    def list_actions(self, *, limit: int = 50) -> list[dict[str, Any]]:
        ...


class LLMClient(Protocol):
    def complete(self, prompt: str, **kwargs: Any) -> Any:
        ...


@dataclass(frozen=True)
class RuntimePorts:
    events: EventSink
    workspace: WorkspacePublisher
    memory: MemoryWriter
    actions: ActionReader
    memory_reader: MemoryReader
    workspace_reader: WorkspaceReader
    llm: LLMClient | None = None


class StoreEventSink:
    def __init__(self, store_module: Any):
        self._store = store_module

    def add_event(self, kind: str, text: str, meta: dict[str, Any] | str | None = None) -> int | None:
        meta_json = payload_to_json(meta) if meta is not None else None
        return self._store.db.add_event(str(kind), str(text), meta_json=meta_json)


class StoreWorkspacePublisher:
    def __init__(self, store_module: Any):
        self._store = store_module

    def publish(
        self,
        module: str,
        channel: str,
        payload: dict[str, Any] | str | None,
        *,
        salience: float = 0.5,
        ttl_sec: int = 900,
    ) -> int | None:
        return self._store.publish_workspace(
            str(module),
            str(channel),
            payload_to_json(payload),
            salience=float(salience),
            ttl_sec=int(ttl_sec),
        )


class StoreMemoryWriter:
    def __init__(self, store_module: Any):
        self._store = store_module

    def add_experience(self, *, text: str, source_id: str | None = None, modality: str = "text") -> int | None:
        return self._store.add_experience(text=str(text), source_id=source_id, modality=str(modality))

    def add_insight(
        self,
        *,
        kind: str,
        title: str,
        text: str,
        priority: int = 3,
        source_id: str | None = None,
        meta: dict[str, Any] | str | None = None,
    ) -> int | None:
        return self._store.add_insight(
            str(kind),
            str(title),
            str(text),
            priority=int(priority),
            source_id=source_id,
            meta_json=payload_to_json(meta) if meta is not None else None,
        )


class StoreMemoryReader:
    def __init__(self, store_module: Any):
        self._store = store_module

    def search_triples(self, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
        if hasattr(self._store, "search_triples"):
            return list(self._store.search_triples(str(query), limit=int(limit)) or [])
        return []

    def search_insights(self, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
        if hasattr(self._store, "search_insights"):
            return list(self._store.search_insights(str(query), limit=int(limit)) or [])
        return []

    def list_experiences(self, *, limit: int = 10) -> list[dict[str, Any]]:
        if hasattr(self._store, "list_experiences"):
            return list(self._store.list_experiences(limit=int(limit)) or [])
        return []


class StoreWorkspaceReader:
    def __init__(self, store_module: Any):
        self._store = store_module

    def read_workspace(
        self,
        *,
        channels: list[str] | None = None,
        limit: int = 30,
        include_expired: bool = False,
    ) -> list[dict[str, Any]]:
        if hasattr(self._store, "read_workspace"):
            return list(
                self._store.read_workspace(
                    channels=channels,
                    limit=int(limit),
                    include_expired=bool(include_expired),
                )
                or []
            )
        return []


class StoreActionReader:
    def __init__(self, store_module: Any):
        self._store = store_module

    def list_actions(self, *, limit: int = 50) -> list[dict[str, Any]]:
        try:
            return self._store.db.list_actions(limit=int(limit))
        except TypeError:
            return self._store.db.list_actions(int(limit))


class ModuleLLMClient:
    def __init__(self, llm_module: Any):
        self._llm = llm_module

    def complete(self, prompt: str, **kwargs: Any) -> Any:
        return self._llm.complete(prompt, **kwargs)


@dataclass
class StaticLLMClient:
    response: Any = ""
    calls: list[dict[str, Any]] = field(default_factory=list)

    def complete(self, prompt: str, **kwargs: Any) -> Any:
        self.calls.append({"prompt": prompt, "kwargs": dict(kwargs)})
        return self.response


class NullEventSink:
    def add_event(self, kind: str, text: str, meta: dict[str, Any] | str | None = None) -> int | None:
        return None


class NullWorkspacePublisher:
    def publish(
        self,
        module: str,
        channel: str,
        payload: dict[str, Any] | str | None,
        *,
        salience: float = 0.5,
        ttl_sec: int = 900,
    ) -> int | None:
        return None


class NullMemoryWriter:
    def add_experience(self, *, text: str, source_id: str | None = None, modality: str = "text") -> int | None:
        return None

    def add_insight(
        self,
        *,
        kind: str,
        title: str,
        text: str,
        priority: int = 3,
        source_id: str | None = None,
        meta: dict[str, Any] | str | None = None,
    ) -> int | None:
        return None


class NullActionReader:
    def list_actions(self, *, limit: int = 50) -> list[dict[str, Any]]:
        return []


class NullMemoryReader:
    def search_triples(self, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
        return []

    def search_insights(self, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
        return []

    def list_experiences(self, *, limit: int = 10) -> list[dict[str, Any]]:
        return []


class NullWorkspaceReader:
    def read_workspace(
        self,
        *,
        channels: list[str] | None = None,
        limit: int = 30,
        include_expired: bool = False,
    ) -> list[dict[str, Any]]:
        return []


@dataclass
class RecordingEventSink:
    rows: list[dict[str, Any]] = field(default_factory=list)

    def add_event(self, kind: str, text: str, meta: dict[str, Any] | str | None = None) -> int:
        self.rows.append({"kind": kind, "text": text, "meta": meta})
        return len(self.rows)


@dataclass
class RecordingWorkspacePublisher:
    rows: list[dict[str, Any]] = field(default_factory=list)

    def publish(
        self,
        module: str,
        channel: str,
        payload: dict[str, Any] | str | None,
        *,
        salience: float = 0.5,
        ttl_sec: int = 900,
    ) -> int:
        self.rows.append({
            "module": module,
            "channel": channel,
            "payload": payload,
            "salience": salience,
            "ttl_sec": ttl_sec,
        })
        return len(self.rows)


@dataclass
class RecordingMemoryWriter:
    experiences: list[dict[str, Any]] = field(default_factory=list)
    insights: list[dict[str, Any]] = field(default_factory=list)

    def add_experience(self, *, text: str, source_id: str | None = None, modality: str = "text") -> int:
        self.experiences.append({"text": text, "source_id": source_id, "modality": modality})
        return len(self.experiences)

    def add_insight(
        self,
        *,
        kind: str,
        title: str,
        text: str,
        priority: int = 3,
        source_id: str | None = None,
        meta: dict[str, Any] | str | None = None,
    ) -> int:
        self.insights.append({
            "kind": kind,
            "title": title,
            "text": text,
            "priority": priority,
            "source_id": source_id,
            "meta": meta,
        })
        return len(self.insights)


@dataclass
class StaticActionReader:
    rows: list[dict[str, Any]] = field(default_factory=list)

    def list_actions(self, *, limit: int = 50) -> list[dict[str, Any]]:
        return list(self.rows)[-max(1, int(limit)) :]


@dataclass
class StaticMemoryReader:
    triples: list[dict[str, Any]] = field(default_factory=list)
    insights: list[dict[str, Any]] = field(default_factory=list)
    experiences: list[dict[str, Any]] = field(default_factory=list)

    def search_triples(self, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
        return list(self.triples)[: max(1, int(limit))]

    def search_insights(self, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
        return list(self.insights)[: max(1, int(limit))]

    def list_experiences(self, *, limit: int = 10) -> list[dict[str, Any]]:
        return list(self.experiences)[-max(1, int(limit)) :]


@dataclass
class StaticWorkspaceReader:
    rows: list[dict[str, Any]] = field(default_factory=list)

    def read_workspace(
        self,
        *,
        channels: list[str] | None = None,
        limit: int = 30,
        include_expired: bool = False,
    ) -> list[dict[str, Any]]:
        wanted = set(channels or [])
        rows = [row for row in self.rows if not wanted or str(row.get("channel") or "") in wanted]
        return rows[-max(1, int(limit)) :]


def null_ports() -> RuntimePorts:
    return RuntimePorts(
        events=NullEventSink(),
        workspace=NullWorkspacePublisher(),
        memory=NullMemoryWriter(),
        actions=NullActionReader(),
        memory_reader=NullMemoryReader(),
        workspace_reader=NullWorkspaceReader(),
        llm=None,
    )


def recording_ports(
    *,
    actions: list[dict[str, Any]] | None = None,
    triples: list[dict[str, Any]] | None = None,
    insights: list[dict[str, Any]] | None = None,
    experiences: list[dict[str, Any]] | None = None,
    workspace_rows: list[dict[str, Any]] | None = None,
    llm: LLMClient | None = None,
) -> tuple[RuntimePorts, RecordingEventSink, RecordingWorkspacePublisher, RecordingMemoryWriter]:
    events = RecordingEventSink()
    workspace = RecordingWorkspacePublisher()
    memory = RecordingMemoryWriter()
    ports = RuntimePorts(
        events=events,
        workspace=workspace,
        memory=memory,
        actions=StaticActionReader(list(actions or [])),
        memory_reader=StaticMemoryReader(
            triples=list(triples or []),
            insights=list(insights or []),
            experiences=list(experiences or []),
        ),
        workspace_reader=StaticWorkspaceReader(list(workspace_rows or [])),
        llm=llm,
    )
    return ports, events, workspace, memory


def default_ports() -> RuntimePorts:
    from ultronpro import llm, store

    return RuntimePorts(
        events=StoreEventSink(store),
        workspace=StoreWorkspacePublisher(store),
        memory=StoreMemoryWriter(store),
        actions=StoreActionReader(store),
        memory_reader=StoreMemoryReader(store),
        workspace_reader=StoreWorkspaceReader(store),
        llm=ModuleLLMClient(llm),
    )
