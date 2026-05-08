from __future__ import annotations

import json
from typing import Any

from ultronpro.core.ports import RuntimePorts, default_ports, payload_to_json


def _payload_dict(payload: dict[str, Any] | str | None) -> dict[str, Any]:
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, str):
        text = payload.strip()
        if text.startswith("{"):
            try:
                data = json.loads(text)
            except Exception:
                data = {}
            if isinstance(data, dict):
                return data
    return {}


def publish_sync(
    module: str,
    channel: str,
    payload: dict[str, Any] | str | None,
    *,
    salience: float = 0.5,
    ttl_sec: int = 900,
    ports: RuntimePorts | None = None,
) -> int:
    ports = ports or default_ports()
    try:
        wid = ports.workspace.publish(
            str(module),
            str(channel),
            payload or {},
            salience=float(salience),
            ttl_sec=int(ttl_sec),
        )
        workspace_id = int(wid or 0)
        try:
            from ultronpro import working_memory

            payload_str = payload_to_json(payload or {})
            working_memory.add_to_working_memory(
                content=f"[{module}:{channel}] " + payload_str[:350],
                source=str(module),
                item_type=str(channel),
                salience=float(salience),
                metadata={"workspace_id": workspace_id},
            )
        except Exception:
            pass
        return workspace_id
    except Exception:
        return 0


def publish(
    module: str,
    channel: str,
    payload: dict[str, Any] | str | None,
    *,
    salience: float = 0.5,
    ttl_sec: int = 900,
    ports: RuntimePorts | None = None,
) -> int:
    try:
        from ultronpro import runtime_guard

        loop_name = runtime_guard.current_loop_name()
    except Exception:
        loop_name = None

    if loop_name:
        try:
            from ultronpro import background_binary_bus

            background_binary_bus.register_workspace_sink(
                lambda module, channel, payload, salience=0.5, ttl_sec=900: publish_sync(
                    module,
                    channel,
                    payload,
                    salience=salience,
                    ttl_sec=ttl_sec,
                    ports=ports,
                )
            )
            if background_binary_bus.publish_workspace_task(
                loop_name=loop_name,
                module=str(module),
                channel=str(channel),
                payload=_payload_dict(payload),
                salience=float(salience),
                ttl_sec=int(ttl_sec),
            ):
                return 0
        except Exception:
            pass
    return publish_sync(module, channel, payload or {}, salience=salience, ttl_sec=ttl_sec, ports=ports)
