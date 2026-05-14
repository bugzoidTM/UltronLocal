from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import os
import platform
import re
import shutil
import socket
import ssl
import subprocess
import struct
import tempfile
import threading
import time
import unicodedata
import webbrowser
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx


DATA_DIR = Path(__file__).resolve().parent.parent / "data"
REGISTRY_PATH = DATA_DIR / "local_device_registry.json"
RUNTIME_STATE_PATH = DATA_DIR / "local_environment_state.json"
ACTION_LEDGER_PATH = DATA_DIR / "local_environment_action_ledger.jsonl"
PENDING_ACTIONS_PATH = DATA_DIR / "local_environment_pending_actions.json"

CAPABILITY_RISK: dict[str, int] = {
    "read_state": 0,
    "turn_on": 1,
    "turn_off": 1,
    "set_brightness": 1,
    "send_notification": 1,
    "open_web_interface": 0,
    "view_stream": 0,
    "capture_snapshot": 1,
    "wake_device": 2,
    "set_temperature": 2,
    "media_play": 1,
    "media_pause": 1,
    "volume_up": 1,
    "volume_down": 1,
    "mute": 1,
    "send_key": 1,
    "launch_app": 1,
    "set_input": 1,
    "start_service": 3,
    "stop_service": 3,
    "restart_service": 3,
    "run_script": 3,
}

KNOWN_CAPABILITIES = set(CAPABILITY_RISK)

DEFAULT_DISCOVERY_PORTS = [
    80,
    443,
    554,
    1883,
    5000,
    5001,
    5357,
    7000,
    8001,
    8002,
    8008,
    8009,
    8000,
    8080,
    8060,
    8123,
    32400,
    9080,
    9100,
    9197,
    55000,
    22,
]


def _now() -> int:
    return int(time.time())


def _safe(value: Any, limit: int = 500) -> str:
    return " ".join(str(value or "").strip().split())[:limit]


def _slug(value: Any, limit: int = 120) -> str:
    raw = unicodedata.normalize("NFKD", str(value or "").lower())
    raw = "".join(ch for ch in raw if not unicodedata.combining(ch))
    raw = re.sub(r"[^a-z0-9_.:-]+", "_", raw).strip("_")
    return raw[:limit] or "item"


def _hash(value: Any) -> str:
    try:
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:
        raw = str(value)
    return hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()[:12]


def _fold(text: str) -> str:
    raw = unicodedata.normalize("NFKD", str(text or "").lower())
    raw = "".join(ch for ch in raw if not unicodedata.combining(ch))
    raw = re.sub(r"[^a-z0-9_\-\s]+", " ", raw)
    return re.sub(r"\s+", " ", raw).strip()


def _read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
            return data
    except Exception:
        pass
    return default


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def _default_registry() -> dict[str, Any]:
    return {"ok": True, "version": 1, "updated_at": 0, "devices": {}}


def _load_registry() -> dict[str, Any]:
    data = _read_json(REGISTRY_PATH, _default_registry())
    if not isinstance(data, dict):
        data = _default_registry()
    data.setdefault("devices", {})
    data.setdefault("version", 1)
    data.setdefault("ok", True)
    return data


def _save_registry(data: dict[str, Any]) -> dict[str, Any]:
    out = dict(_default_registry())
    out.update(data or {})
    out["updated_at"] = _now()
    out.setdefault("devices", {})
    _write_json(REGISTRY_PATH, out)
    return out


def _runtime_state() -> dict[str, Any]:
    data = _read_json(RUNTIME_STATE_PATH, {"updated_at": 0, "devices": {}, "notifications": []})
    if not isinstance(data, dict):
        data = {"updated_at": 0, "devices": {}, "notifications": []}
    data.setdefault("devices", {})
    data.setdefault("notifications", [])
    return data


def _save_runtime_state(data: dict[str, Any]) -> dict[str, Any]:
    data = dict(data or {})
    data["updated_at"] = _now()
    data.setdefault("devices", {})
    data.setdefault("notifications", [])
    _write_json(RUNTIME_STATE_PATH, data)
    return data


def _pending_ttl_seconds() -> int:
    try:
        return max(30, min(3600, int(os.getenv("ULTRON_LOCAL_ENV_PENDING_TTL_SEC", "300") or 300)))
    except Exception:
        return 300


def _default_pending_actions() -> dict[str, Any]:
    return {"ok": True, "version": 1, "updated_at": 0, "pending_actions": {}}


def _load_pending_actions() -> dict[str, Any]:
    data = _read_json(PENDING_ACTIONS_PATH, _default_pending_actions())
    if not isinstance(data, dict):
        data = _default_pending_actions()
    pending = data.get("pending_actions")
    if isinstance(pending, list):
        pending = {str(x.get("pending_id") or _hash(x)): x for x in pending if isinstance(x, dict)}
    if not isinstance(pending, dict):
        pending = {}
    data.setdefault("ok", True)
    data.setdefault("version", 1)
    data["pending_actions"] = pending
    return data


def _save_pending_actions(data: dict[str, Any]) -> dict[str, Any]:
    out = dict(_default_pending_actions())
    out.update(data or {})
    out["updated_at"] = _now()
    out.setdefault("pending_actions", {})
    _write_json(PENDING_ACTIONS_PATH, out)
    return out


def _session_key(session_id: str | None) -> str:
    return _safe(session_id or "default", 120) or "default"


def _pending_is_active(row: dict[str, Any], *, session_id: str | None = None, now: int | None = None) -> bool:
    if not isinstance(row, dict):
        return False
    if str(row.get("status") or "") != "pending":
        return False
    if session_id is not None and _session_key(str(row.get("session_id") or "")) != _session_key(session_id):
        return False
    return int(row.get("expires_at") or 0) >= int(now or _now())


def _public_pending(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row or {})
    if isinstance(out.get("params"), dict):
        out["params_hash"] = _hash(out.get("params"))
    return out


def is_confirmation_text(text: str) -> bool:
    folded = _fold(text)
    if not folded:
        return False
    if folded in {"sim", "ok", "confirmo", "confirmado", "autorizo", "aprovado", "pode", "prosseguir", "prossiga"}:
        return True
    return bool(re.search(r"\b(confirmo|confirmado|autorizo|aprovado|pode executar|execute agora|pode seguir|prosseguir|prossiga)\b", folded))


def is_cancel_text(text: str) -> bool:
    folded = _fold(text)
    if not folded:
        return False
    if folded in {"nao", "não", "cancelar", "cancela", "cancelado", "pare"}:
        return True
    return bool(re.search(r"\b(cancelar|cancela|cancelado|nao execute|nao executar|deixa quieto|pare)\b", folded))


def _pending_id_from_text(text: str) -> str:
    m = re.search(r"\blpa_[a-f0-9]{12}\b", _fold(text))
    return str(m.group(0)) if m else ""


def pending_id_from_text(text: str) -> str:
    return _pending_id_from_text(text)


def create_pending_action(
    parsed: dict[str, Any],
    device: dict[str, Any] | None,
    gate: dict[str, Any],
    *,
    text: str,
    requested_by: str,
    session_id: str | None,
) -> dict[str, Any]:
    now = _now()
    ttl = _pending_ttl_seconds()
    sid = _session_key(session_id)
    params = parsed.get("params") if isinstance(parsed.get("params"), dict) else {}
    pending_id = f"lpa_{_hash([sid, parsed.get('device_id'), parsed.get('action'), params, text, now])}"
    row = {
        "pending_id": pending_id,
        "status": "pending",
        "session_id": sid,
        "created_at": now,
        "expires_at": now + ttl,
        "ttl_seconds": ttl,
        "device_id": str(parsed.get("device_id") or ""),
        "device_name": _safe((device or {}).get("name") or parsed.get("device_id"), 120),
        "action": str(parsed.get("action") or ""),
        "params": params,
        "reason": _safe(text, 500),
        "requested_by": _safe(requested_by, 120),
        "risk_level": int(gate.get("risk_level") or 0),
        "requires_confirmation": bool(gate.get("requires_confirmation")),
        "gate": dict(gate or {}),
        "parsed_command": dict(parsed or {}),
        "confirmation_hint": f"confirmo {pending_id}",
    }
    data = _load_pending_actions()
    pending = data.setdefault("pending_actions", {})
    pending[pending_id] = row
    _save_pending_actions(data)
    return _public_pending(row)


def list_pending_actions(session_id: str | None = None, include_expired: bool = False) -> dict[str, Any]:
    data = _load_pending_actions()
    now = _now()
    items: list[dict[str, Any]] = []
    changed = False
    for pending_id, row in list((data.get("pending_actions") or {}).items()):
        if not isinstance(row, dict):
            continue
        if str(row.get("status") or "") == "pending" and int(row.get("expires_at") or 0) < now:
            row["status"] = "expired"
            row["expired_at"] = now
            data["pending_actions"][pending_id] = row
            changed = True
        if session_id is not None and _session_key(str(row.get("session_id") or "")) != _session_key(session_id):
            continue
        if include_expired or _pending_is_active(row, now=now):
            items.append(_public_pending(row))
    if changed:
        _save_pending_actions(data)
    items.sort(key=lambda x: int(x.get("created_at") or 0), reverse=True)
    return {"ok": True, "path": str(PENDING_ACTIONS_PATH), "items": items, "count": len(items)}


def latest_pending_action(session_id: str | None = None, pending_id: str | None = None) -> dict[str, Any]:
    data = _load_pending_actions()
    now = _now()
    selected: dict[str, Any] | None = None
    if pending_id:
        row = (data.get("pending_actions") or {}).get(str(pending_id))
        if isinstance(row, dict) and _pending_is_active(row, session_id=session_id, now=now):
            selected = row
    else:
        rows = [
            row
            for row in (data.get("pending_actions") or {}).values()
            if isinstance(row, dict) and _pending_is_active(row, session_id=session_id, now=now)
        ]
        rows.sort(key=lambda x: int(x.get("created_at") or 0), reverse=True)
        selected = rows[0] if rows else None
    if not selected:
        return {"ok": False, "reason": "no_active_pending_action", "path": str(PENDING_ACTIONS_PATH)}
    return {"ok": True, "pending_action": _public_pending(selected)}


def confirm_pending_action(
    session_id: str | None = None,
    pending_id: str | None = None,
    *,
    approved_by: str = "chat_stream",
) -> dict[str, Any]:
    data = _load_pending_actions()
    pending = data.setdefault("pending_actions", {})
    lookup_id = str(pending_id or "").strip()
    if not lookup_id:
        found = latest_pending_action(session_id=session_id)
        lookup_id = str((found.get("pending_action") or {}).get("pending_id") or "") if found.get("ok") else ""
    row = pending.get(lookup_id) if lookup_id else None
    if not isinstance(row, dict) or not _pending_is_active(row, session_id=session_id):
        return {"ok": False, "reason": "no_active_pending_action", "pending_id": lookup_id}
    now = _now()
    row["status"] = "executing"
    row["approved_at"] = now
    row["approved_by"] = _safe(approved_by, 120)
    pending[lookup_id] = row
    _save_pending_actions(data)
    result = act_device(
        str(row.get("device_id") or ""),
        str(row.get("action") or ""),
        params=row.get("params") if isinstance(row.get("params"), dict) else {},
        reason=str(row.get("reason") or ""),
        requested_by=approved_by,
        approved=True,
    )
    data = _load_pending_actions()
    pending = data.setdefault("pending_actions", {})
    row = pending.get(lookup_id, row)
    row["status"] = "executed" if result.get("ok") else "failed"
    row["executed_at"] = _now()
    row["result_status"] = result.get("status")
    row["result_ok"] = bool(result.get("ok"))
    ledger = result.get("ledger") if isinstance(result.get("ledger"), dict) else {}
    if ledger.get("ledger_id"):
        row["ledger_id"] = ledger.get("ledger_id")
    pending[lookup_id] = row
    _save_pending_actions(data)
    result["pending_action"] = _public_pending(row)
    result["confirmed_pending_action"] = _public_pending(row)
    return result


def cancel_pending_action(
    session_id: str | None = None,
    pending_id: str | None = None,
    *,
    reason: str = "user_cancelled",
) -> dict[str, Any]:
    data = _load_pending_actions()
    pending = data.setdefault("pending_actions", {})
    lookup_id = str(pending_id or "").strip()
    if not lookup_id:
        found = latest_pending_action(session_id=session_id)
        lookup_id = str((found.get("pending_action") or {}).get("pending_id") or "") if found.get("ok") else ""
    row = pending.get(lookup_id) if lookup_id else None
    if not isinstance(row, dict) or not _pending_is_active(row, session_id=session_id):
        return {"ok": False, "reason": "no_active_pending_action", "pending_id": lookup_id}
    row["status"] = "cancelled"
    row["cancelled_at"] = _now()
    row["cancel_reason"] = _safe(reason, 160)
    pending[lookup_id] = row
    _save_pending_actions(data)
    return {"ok": True, "status": "cancelled", "pending_action": _public_pending(row)}


def _normalize_device(raw: dict[str, Any]) -> dict[str, Any]:
    device_id = re.sub(r"[^a-zA-Z0-9_.:-]+", "_", str(raw.get("device_id") or raw.get("id") or "").strip())[:120]
    if not device_id:
        raise ValueError("device_id_required")
    caps = [str(x).strip() for x in (raw.get("capabilities") or []) if str(x).strip()]
    unknown = [c for c in caps if c not in KNOWN_CAPABILITIES]
    if unknown:
        raise ValueError(f"unknown_capabilities:{','.join(unknown[:5])}")
    risk = int(raw.get("risk_level") or 0)
    risk = max(0, min(4, risk))
    aliases = [str(x).strip()[:80] for x in (raw.get("aliases") or []) if str(x).strip()]
    return {
        "device_id": device_id,
        "name": _safe(raw.get("name") or device_id, 120),
        "type": _safe(raw.get("type") or "generic", 80),
        "location": _safe(raw.get("location"), 80),
        "adapter": _safe(raw.get("adapter") or "mock", 80),
        "capabilities": caps,
        "risk_level": risk,
        "requires_confirmation": bool(raw.get("requires_confirmation", risk >= 3)),
        "allowed": bool(raw.get("allowed", False)),
        "allow_high_risk": bool(raw.get("allow_high_risk", False)),
        "aliases": aliases,
        "config": raw.get("config") if isinstance(raw.get("config"), dict) else {},
        "metadata": raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {},
        "created_at": int(raw.get("created_at") or _now()),
        "updated_at": _now(),
    }


def list_devices(include_disabled: bool = True) -> dict[str, Any]:
    reg = _load_registry()
    devices = list((reg.get("devices") or {}).values())
    if not include_disabled:
        devices = [d for d in devices if bool(d.get("allowed"))]
    devices.sort(key=lambda d: (str(d.get("location") or ""), str(d.get("device_id") or "")))
    return {
        "ok": True,
        "path": str(REGISTRY_PATH),
        "capabilities": capability_model(),
        "devices": devices,
        "count": len(devices),
    }


def get_device(device_id: str) -> dict[str, Any] | None:
    did = str(device_id or "").strip()
    if not did:
        return None
    return (_load_registry().get("devices") or {}).get(did)


def find_device_for_text(text: str, *, action: str | None = None, include_disabled: bool = False) -> dict[str, Any]:
    folded = _fold(text)
    devices = [d for d in list_devices(include_disabled=include_disabled).get("devices", []) if isinstance(d, dict)]
    if action:
        devices = [d for d in devices if action in set(d.get("capabilities") or [])]
    scored: list[tuple[int, dict[str, Any]]] = []
    for device in devices:
        config = device.get("config") if isinstance(device.get("config"), dict) else {}
        terms = {
            _fold(device.get("device_id")),
            _fold(device.get("name")),
            _fold(device.get("type")),
            _fold(device.get("location")),
            _fold(config.get("ip")),
            _fold(config.get("entity_id")),
        }
        terms.update(_fold(x) for x in (device.get("aliases") or []))
        terms = {t for t in terms if t}
        score = 0
        for term in terms:
            if term and term in folded:
                score += max(1, min(10, len(term.split()) + 2))
        if score:
            scored.append((score, device))
    if not scored:
        return {"ok": False, "reason": "no_registered_device_matched", "action": action or ""}
    scored.sort(key=lambda item: item[0], reverse=True)
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        return {
            "ok": False,
            "reason": "ambiguous_device",
            "action": action or "",
            "candidates": [d.get("device_id") for _, d in scored[:5]],
        }
    return {"ok": True, "device": scored[0][1], "score": scored[0][0], "confidence": round(min(0.99, 0.55 + scored[0][0] / 20.0), 4)}


def upsert_device(device: dict[str, Any]) -> dict[str, Any]:
    try:
        normalized = _normalize_device(device or {})
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    reg = _load_registry()
    current = (reg.get("devices") or {}).get(normalized["device_id"])
    if isinstance(current, dict):
        normalized["created_at"] = int(current.get("created_at") or normalized["created_at"])
    reg.setdefault("devices", {})[normalized["device_id"]] = normalized
    _save_registry(reg)
    return {"ok": True, "device": normalized, "path": str(REGISTRY_PATH)}


def rename_device(device_id: str, new_name: str, *, aliases: list[str] | None = None, source: str = "user") -> dict[str, Any]:
    reg = _load_registry()
    devices = reg.setdefault("devices", {})
    did = str(device_id or "").strip()
    device = devices.get(did)
    if not isinstance(device, dict):
        return {"ok": False, "error": "device_not_found", "device_id": did}
    clean_name = _safe(new_name, 120)
    if not clean_name:
        return {"ok": False, "error": "new_name_required", "device_id": did}
    current_aliases = [str(x).strip() for x in (device.get("aliases") or []) if str(x).strip()]
    additions = [clean_name, _fold(clean_name), *(aliases or [])]
    for alias in additions:
        alias = str(alias or "").strip()
        if alias and alias not in current_aliases:
            current_aliases.append(alias[:80])
    device["name"] = clean_name
    device["aliases"] = list(dict.fromkeys(current_aliases))[:30]
    meta = device.get("metadata") if isinstance(device.get("metadata"), dict) else {}
    meta.setdefault("rename_history", []).append({"ts": _now(), "name": clean_name, "source": _safe(source, 80)})
    meta["last_renamed_at"] = _now()
    device["metadata"] = meta
    device["updated_at"] = _now()
    devices[did] = _normalize_device(device)
    _save_registry(reg)
    return {"ok": True, "device": devices[did], "device_id": did, "name": clean_name, "path": str(REGISTRY_PATH)}


def rename_device_from_text(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    folded = _fold(raw)
    patterns = [
        r"(?:renome(?:ar|ie)|chame|chamar|nomeie|apelide)\s+(?P<target>.+?)\s+(?:para|como|de)\s+(?P<name>.+)$",
        r"(?P<target>camera|webcam|tv|dispositivo).+?(?:vai se chamar|chama|deve se chamar)\s+(?P<name>.+)$",
    ]
    target_text = ""
    name = ""
    for pattern in patterns:
        match = re.search(pattern, raw, flags=re.IGNORECASE)
        if match:
            target_text = str(match.groupdict().get("target") or "").strip()
            name = str(match.groupdict().get("name") or "").strip()
            break
    if not name:
        match = re.search(r"\b(?:para|como|de)\s+(.+)$", raw, flags=re.IGNORECASE)
        if match:
            name = match.group(1).strip()
            target_text = raw[: match.start()].strip()
    name = re.sub(r"^[\"'“”]+|[\"'“”\.\!]+$", "", name).strip()
    if not name:
        return {"ok": False, "reason": "new_name_not_found"}
    lookup_text = target_text or raw
    found = find_device_for_text(lookup_text, include_disabled=True)
    if not found.get("ok") and any(word in folded for word in ("camera", "webcam")):
        found = find_device_for_text("camera " + lookup_text, action="view_stream", include_disabled=True)
    if not found.get("ok"):
        return found
    device = found.get("device") if isinstance(found.get("device"), dict) else {}
    return rename_device(str(device.get("device_id") or ""), name, aliases=[name], source="chat")


def remove_device(device_id: str) -> dict[str, Any]:
    reg = _load_registry()
    devices = reg.setdefault("devices", {})
    did = str(device_id or "").strip()
    if did not in devices:
        return {"ok": False, "error": "device_not_found", "device_id": did}
    removed = devices.pop(did)
    _save_registry(reg)
    return {"ok": True, "removed": removed}


def _is_private_or_loopback(cidr: str) -> bool:
    try:
        net = ipaddress.ip_network(str(cidr), strict=False)
    except Exception:
        return False
    return bool(net.is_private or net.is_loopback or net.is_link_local)


def _local_ipv4s() -> list[str]:
    out: set[str] = set()
    try:
        for item in socket.gethostbyname_ex(socket.gethostname())[2]:
            try:
                ip = ipaddress.ip_address(item)
            except Exception:
                continue
            if ip.version == 4 and (ip.is_private or ip.is_loopback or ip.is_link_local):
                out.add(str(ip))
    except Exception:
        pass
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect(("8.8.8.8", 80))
            item = sock.getsockname()[0]
            ip = ipaddress.ip_address(item)
            if ip.version == 4 and (ip.is_private or ip.is_loopback or ip.is_link_local):
                out.add(str(ip))
        finally:
            sock.close()
    except Exception:
        pass
    if not out:
        out.add("127.0.0.1")
    return sorted(out)


def discover_networks() -> dict[str, Any]:
    configured = [x.strip() for x in str(os.getenv("ULTRON_LOCAL_ENV_CIDRS") or "").split(",") if x.strip()]
    networks: list[str] = []
    for cidr in configured:
        if _is_private_or_loopback(cidr):
            networks.append(str(ipaddress.ip_network(cidr, strict=False)))
    if not networks:
        for ip in _local_ipv4s():
            addr = ipaddress.ip_address(ip)
            if addr.is_loopback:
                networks.append(f"{ip}/32")
            else:
                networks.append(str(ipaddress.ip_network(f"{ip}/24", strict=False)))
    deduped = sorted(set(networks))
    return {"ok": True, "local_ipv4s": _local_ipv4s(), "networks": deduped}


def _bounded_hosts(cidr: str, max_hosts: int) -> list[str]:
    net = ipaddress.ip_network(str(cidr), strict=False)
    if not (net.is_private or net.is_loopback or net.is_link_local):
        raise ValueError("network_scan_limited_to_private_or_loopback_ranges")
    limit = max(1, min(512, int(max_hosts or 256)))
    if net.num_addresses == 1:
        return [str(net.network_address)]
    hosts = []
    for host in net.hosts():
        hosts.append(str(host))
        if len(hosts) >= limit:
            break
    return hosts


def _normalize_ports(ports: list[int] | None) -> list[int]:
    raw = ports or DEFAULT_DISCOVERY_PORTS
    out: list[int] = []
    for port in raw:
        try:
            p = int(port)
        except Exception:
            continue
        if 1 <= p <= 65535 and p not in out:
            out.append(p)
        if len(out) >= 64:
            break
    return out or list(DEFAULT_DISCOVERY_PORTS)


def _device_ports(config: dict[str, Any] | None) -> list[int]:
    config = config if isinstance(config, dict) else {}
    raw: list[Any] = []
    for key in ("last_access_ports", "last_discovered_ports", "open_ports"):
        values = config.get(key)
        if isinstance(values, list):
            raw.extend(values)
    return _normalize_ports([int(p) for p in raw if str(p).strip().isdigit()]) if raw else []


def _public_base_url() -> str:
    return str(os.getenv("ULTRON_LOCAL_ENV_PUBLIC_BASE_URL") or "http://127.0.0.1:8000").rstrip("/")


def _local_api_path(path: str) -> str:
    suffix = "/" + str(path or "").lstrip("/")
    return f"{_public_base_url()}{suffix}"


def _maybe_open_local_url(path_or_url: str, *, enabled: bool | None = None) -> bool:
    if enabled is None:
        enabled = str(os.getenv("ULTRON_LOCAL_ENV_OPEN_BROWSER", "1")).strip().lower() not in {"0", "false", "no", "off"}
    if not enabled:
        return False
    url = str(path_or_url or "").strip()
    if url.startswith("/"):
        url = _local_api_path(url)
    if not url:
        return False
    try:
        return bool(webbrowser.open(url, new=2, autoraise=True))
    except Exception:
        return False


def _tcp_port_open(host: str, port: int, timeout_sec: float) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.settimeout(max(0.05, float(timeout_sec)))
        return sock.connect_ex((host, int(port))) == 0
    except Exception:
        return False
    finally:
        try:
            sock.close()
        except Exception:
            pass


def _tcp_probe(host: str, port: int, timeout_sec: float) -> dict[str, Any]:
    started = time.time()
    ok = _tcp_port_open(host, port, timeout_sec)
    return {
        "kind": "tcp",
        "ok": ok,
        "port": int(port),
        "latency_ms": int((time.time() - started) * 1000),
    }


def _http_probe(host: str, port: int, timeout_sec: float) -> dict[str, Any]:
    scheme = "https" if int(port) == 443 else "http"
    url = f"{scheme}://{host}:{int(port)}/"
    started = time.time()
    try:
        with httpx.Client(timeout=timeout_sec, verify=False, follow_redirects=False) as client:
            try:
                resp = client.head(url)
            except Exception:
                resp = client.get(url)
        headers = {
            key.lower(): value
            for key, value in resp.headers.items()
            if key.lower() in {"server", "www-authenticate", "content-type", "location"}
        }
        return {
            "kind": "http",
            "ok": True,
            "port": int(port),
            "url": url,
            "status_code": int(resp.status_code),
            "headers": headers,
            "latency_ms": int((time.time() - started) * 1000),
        }
    except Exception as exc:
        tcp = _tcp_probe(host, port, timeout_sec)
        tcp.update({
            "kind": "http",
            "url": url,
            "http_ok": False,
            "error": f"{type(exc).__name__}:{str(exc)[:160]}",
        })
        return tcp


def _rtsp_probe(host: str, port: int, timeout_sec: float) -> dict[str, Any]:
    started = time.time()
    line = ""
    try:
        with socket.create_connection((host, int(port)), timeout=max(0.05, timeout_sec)) as sock:
            sock.settimeout(max(0.05, timeout_sec))
            req = (
                f"OPTIONS rtsp://{host}:{int(port)}/ RTSP/1.0\r\n"
                "CSeq: 1\r\n"
                "User-Agent: UltronPro-LocalEnv/1.0\r\n\r\n"
            ).encode("ascii", errors="ignore")
            sock.sendall(req)
            raw = sock.recv(512)
        line = raw.decode("latin-1", errors="ignore").splitlines()[0:1][0] if raw else ""
        return {
            "kind": "rtsp",
            "ok": True,
            "port": int(port),
            "status_line": _safe(line, 160),
            "latency_ms": int((time.time() - started) * 1000),
        }
    except Exception as exc:
        tcp = _tcp_probe(host, port, timeout_sec)
        tcp.update({
            "kind": "rtsp",
            "rtsp_ok": False,
            "error": f"{type(exc).__name__}:{str(exc)[:160]}",
        })
        return tcp


def _ssh_probe(host: str, port: int, timeout_sec: float) -> dict[str, Any]:
    started = time.time()
    try:
        with socket.create_connection((host, int(port)), timeout=max(0.05, timeout_sec)) as sock:
            sock.settimeout(max(0.05, timeout_sec))
            raw = sock.recv(160)
        banner = raw.decode("latin-1", errors="ignore").strip()
        return {
            "kind": "ssh",
            "ok": True,
            "port": int(port),
            "banner": _safe(banner, 160),
            "latency_ms": int((time.time() - started) * 1000),
        }
    except Exception as exc:
        tcp = _tcp_probe(host, port, timeout_sec)
        tcp.update({
            "kind": "ssh",
            "ssh_ok": False,
            "error": f"{type(exc).__name__}:{str(exc)[:160]}",
        })
        return tcp


def _probe_access_port(host: str, port: int, timeout_sec: float) -> dict[str, Any]:
    if int(port) in {80, 443, 5000, 5001, 5357, 7000, 8000, 8001, 8002, 8008, 8060, 8080, 8123, 32400, 9080, 9197, 55000}:
        return _http_probe(host, port, timeout_sec)
    if int(port) == 554:
        return _rtsp_probe(host, port, timeout_sec)
    if int(port) == 22:
        return _ssh_probe(host, port, timeout_sec)
    return _tcp_probe(host, port, timeout_sec)


def _scan_host(host: str, ports: list[int], timeout_sec: float) -> dict[str, Any] | None:
    open_ports = [port for port in ports if _tcp_port_open(host, port, timeout_sec)]
    if not open_ports:
        return None
    return {
        "ip": host,
        "open_ports": open_ports,
        "fingerprint": _classify_open_ports(open_ports),
        "observed_at": _now(),
    }


def _classify_open_ports(open_ports: list[int]) -> dict[str, Any]:
    ports = set(int(p) for p in open_ports)
    if 8123 in ports:
        return {"type": "home_assistant_hub", "adapter_hint": "home_assistant", "name_hint": "Home Assistant"}
    if 554 in ports:
        return {"type": "camera_or_rtsp_device", "adapter_hint": "network_probe", "name_hint": "RTSP device"}
    if 8060 in ports:
        return {"type": "roku_tv_or_streamer", "adapter_hint": "network_probe", "name_hint": "Roku TV/Streamer"}
    if ports & {8001, 8002, 55000}:
        return {"type": "samsung_tv_or_media_device", "adapter_hint": "network_probe", "name_hint": "Samsung TV/Media device"}
    if ports & {8008, 8009}:
        return {"type": "chromecast_or_google_cast", "adapter_hint": "network_probe", "name_hint": "Chromecast/Google Cast"}
    if ports & {7000, 9080, 9197}:
        return {"type": "smart_tv_or_media_device", "adapter_hint": "network_probe", "name_hint": "Smart TV/Media device"}
    if 9100 in ports:
        return {"type": "printer", "adapter_hint": "network_probe", "name_hint": "Network printer"}
    if 1883 in ports:
        return {"type": "mqtt_broker", "adapter_hint": "network_probe", "name_hint": "MQTT broker"}
    if 32400 in ports:
        return {"type": "media_server", "adapter_hint": "network_probe", "name_hint": "Media server"}
    if ports & {80, 443, 8080, 8000, 5000, 5001, 5357}:
        return {"type": "http_device", "adapter_hint": "network_probe", "name_hint": "HTTP device"}
    if 22 in ports:
        return {"type": "ssh_host", "adapter_hint": "network_probe", "name_hint": "SSH host"}
    return {"type": "network_device", "adapter_hint": "network_probe", "name_hint": "Network device"}


def _web_ports(open_ports: list[int]) -> list[int]:
    web = {80, 443, 5000, 5001, 5357, 7000, 8000, 8001, 8002, 8008, 8060, 8080, 8123, 32400, 9080, 9197, 55000}
    return [int(p) for p in open_ports if int(p) in web]


def _web_urls(ip: str, open_ports: list[int]) -> list[str]:
    urls: list[str] = []
    for port in _web_ports(open_ports):
        scheme = "https" if int(port) == 443 else "http"
        default = (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
        url = f"{scheme}://{ip}/" if default else f"{scheme}://{ip}:{port}/"
        if url not in urls:
            urls.append(url)
    return urls


def _rtsp_url_candidates(ip: str, open_ports: list[int], config: dict[str, Any] | None = None) -> list[str]:
    config = config if isinstance(config, dict) else {}
    configured = str(config.get("stream_url") or "").strip()
    if configured:
        return [configured]
    path = str(config.get("stream_path") or "").strip()
    if path:
        if not path.startswith("/"):
            path = "/" + path
        return [f"rtsp://{ip}:554{path}"]
    if 554 not in {int(p) for p in open_ports}:
        return []
    candidates = [
        f"rtsp://{ip}:554/",
        f"rtsp://{ip}:554/stream1",
        f"rtsp://{ip}:554/live",
        f"rtsp://{ip}:554/h264",
        f"rtsp://{ip}:554/cam/realmonitor?channel=1&subtype=0",
        f"rtsp://{ip}:554/h264/ch1/main/av_stream",
    ]
    return list(dict.fromkeys(candidates))


def _capabilities_for_type(device_type: str, open_ports: list[int]) -> list[str]:
    dtype = str(device_type or "")
    caps = ["read_state"]
    if _web_ports(open_ports):
        caps.append("open_web_interface")
    if dtype == "camera_or_rtsp_device" or 554 in {int(p) for p in open_ports}:
        caps.extend(["view_stream", "capture_snapshot"])
    if dtype in {
        "roku_tv_or_streamer",
        "samsung_tv_or_media_device",
        "chromecast_or_google_cast",
        "smart_tv_or_media_device",
        "media_server",
    }:
        caps.extend([
            "turn_on",
            "turn_off",
            "media_play",
            "media_pause",
            "volume_up",
            "volume_down",
            "mute",
            "send_key",
            "launch_app",
            "set_input",
        ])
    return list(dict.fromkeys(caps))


def _ha_capabilities_for_domain(domain: str) -> list[str]:
    domain = str(domain or "").strip().lower()
    caps = ["read_state"]
    if domain in {"light"}:
        caps.extend(["turn_on", "turn_off", "set_brightness"])
    elif domain in {"switch", "input_boolean", "automation", "script"}:
        caps.extend(["turn_on", "turn_off"])
    elif domain == "media_player":
        caps.extend(["turn_on", "turn_off", "media_play", "media_pause", "volume_up", "volume_down", "mute", "set_input"])
    elif domain == "climate":
        caps.extend(["turn_on", "turn_off", "set_temperature"])
    elif domain == "camera":
        caps.extend(["view_stream", "capture_snapshot"])
    elif domain in {"cover", "fan", "lock"}:
        caps.extend(["turn_on", "turn_off"])
    return list(dict.fromkeys(caps))


def _ha_device_type_for_domain(domain: str) -> str:
    domain = str(domain or "").strip().lower()
    return {
        "light": "smart_light",
        "switch": "smart_switch",
        "input_boolean": "virtual_switch",
        "media_player": "home_assistant_media_player",
        "camera": "home_assistant_camera",
        "climate": "thermostat",
        "script": "home_assistant_script",
        "automation": "home_assistant_automation",
        "fan": "fan",
        "cover": "cover",
        "lock": "lock",
    }.get(domain, f"home_assistant_{domain or 'entity'}")


def _aliases_for_type(ip: str, device_type: str, name_hint: str) -> list[str]:
    aliases = [ip, name_hint, device_type]
    if "camera" in device_type or "rtsp" in device_type:
        aliases.extend(["camera", "cameras", "stream", "rtsp", f"camera {ip}"])
    if "tv" in device_type or "cast" in device_type or "media" in device_type or "roku" in device_type:
        aliases.extend(["tv", "televisao", "televisão", "media", "controle remoto", f"tv {ip}"])
    if "printer" in device_type:
        aliases.extend(["impressora", "printer"])
    return [x for x in dict.fromkeys(_safe(a, 80) for a in aliases) if x]


def _event_descriptor(capability: str, device: dict[str, Any], *, executable: bool = True, detail: dict[str, Any] | None = None) -> dict[str, Any]:
    risk = int(CAPABILITY_RISK.get(capability, 4))
    return {
        "event": capability,
        "risk_level": risk,
        "requires_confirmation": bool(device.get("requires_confirmation")) or risk >= int(os.getenv("ULTRON_LOCAL_ENV_CONFIRM_RISK", "3") or 3),
        "registered_capability": capability in set(device.get("capabilities") or []),
        "executable": bool(executable),
        "detail": detail or {},
    }


def device_events(device: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(device, dict):
        return []
    config = device.get("config") if isinstance(device.get("config"), dict) else {}
    ip = str(config.get("ip") or "").strip()
    ports = _device_ports(config)
    dtype = str(device.get("type") or "")
    events: list[dict[str, Any]] = []
    if "read_state" in set(device.get("capabilities") or []):
        events.append(_event_descriptor("read_state", device, detail={"protocol": str(device.get("adapter") or "mock")}))
    if "open_web_interface" in set(device.get("capabilities") or []):
        events.append(_event_descriptor("open_web_interface", device, detail={"urls": _web_urls(ip, ports)}))
    if "view_stream" in set(device.get("capabilities") or []):
        urls = _rtsp_url_candidates(ip, ports, config)
        events.append(_event_descriptor(
            "view_stream",
            device,
            executable=bool(urls),
            detail={
                "protocol": "rtsp",
                "real_time": True,
                "url_candidates": urls,
                "mjpeg_proxy_endpoint": f"/api/local-env/devices/{device.get('device_id')}/camera/mjpeg",
                "requires_camera_credentials": not bool(config.get("stream_url")),
            },
        ))
    if "capture_snapshot" in set(device.get("capabilities") or []):
        events.append(_event_descriptor(
            "capture_snapshot",
            device,
            executable=bool(config.get("snapshot_url") or config.get("stream_url")),
            detail={"requires_snapshot_url_or_rtsp_decoder": True},
        ))
    remote_events = [
        "turn_on",
        "turn_off",
        "media_play",
        "media_pause",
        "volume_up",
        "volume_down",
        "mute",
        "send_key",
        "launch_app",
        "set_input",
    ]
    for event in remote_events:
        if event not in set(device.get("capabilities") or []):
            continue
        executable = (dtype == "roku_tv_or_streamer" and 8060 in set(ports)) or (
            dtype == "samsung_tv_or_media_device" and bool({8001, 8002} & set(ports))
        )
        if event == "turn_on" and not executable:
            executable = bool(config.get("mac"))
        if dtype == "roku_tv_or_streamer" and 8060 in set(ports):
            adapter_hint = "roku_ecp"
        elif dtype == "samsung_tv_or_media_device" and bool({8001, 8002} & set(ports)):
            adapter_hint = "samsung_ws"
        elif event == "turn_on" and config.get("mac"):
            adapter_hint = "wake_on_lan"
        else:
            adapter_hint = "adapter_config_required"
        events.append(_event_descriptor(
            event,
            device,
            executable=executable,
            detail={
                "adapter": adapter_hint,
                "hint": "Configure Home Assistant, Roku ECP, Samsung/WebSocket, WebOS or endpoint HTTP for reliable TV control." if not executable else "",
            },
        ))
    return events


def _device_from_discovery(hit: dict[str, Any]) -> dict[str, Any]:
    ip = str(hit.get("ip") or "").strip()
    fp = hit.get("fingerprint") if isinstance(hit.get("fingerprint"), dict) else {}
    device_id = f"net_{ip.replace('.', '_').replace(':', '_')}"
    open_ports = [int(p) for p in (hit.get("open_ports") or [])]
    device_type = str(fp.get("type") or "network_device")
    name_hint = str(fp.get("name_hint") or "Network device")
    caps = _capabilities_for_type(device_type, open_ports)
    return {
        "device_id": device_id,
        "name": f"{name_hint} {ip}",
        "type": device_type,
        "location": "rede_local",
        "adapter": "network_probe",
        "capabilities": caps,
        "risk_level": max([CAPABILITY_RISK.get(c, 0) for c in caps] or [0]),
        "requires_confirmation": False,
        "allowed": False,
        "aliases": _aliases_for_type(ip, device_type, name_hint),
        "config": {
            "ip": ip,
            "open_ports": open_ports,
            "web_urls": _web_urls(ip, open_ports),
            "rtsp_url_candidates": _rtsp_url_candidates(ip, open_ports),
            "discovered_by": "tcp_port_probe",
        },
        "metadata": {
            "discovered": True,
            "fingerprint": fp,
            "observed_at": hit.get("observed_at"),
            "event_model_version": 1,
        },
    }


def _merge_discovered_device(existing: dict[str, Any] | None, discovered: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(existing, dict):
        return _normalize_device(discovered)
    merged = dict(existing)
    merged["name"] = existing.get("name") or discovered.get("name")
    existing_type = str(existing.get("type") or "")
    discovered_type = str(discovered.get("type") or "")
    if existing_type in {"", "network_device", "http_device"} and discovered_type not in {"", "network_device", "http_device"}:
        merged["type"] = discovered_type
    else:
        merged["type"] = existing.get("type") or discovered.get("type")
    merged["location"] = existing.get("location") or discovered.get("location")
    merged["adapter"] = existing.get("adapter") or discovered.get("adapter")
    merged["risk_level"] = int(existing.get("risk_level") or discovered.get("risk_level") or 0)
    merged["requires_confirmation"] = bool(existing.get("requires_confirmation", discovered.get("requires_confirmation", False)))
    merged["allowed"] = bool(existing.get("allowed", False))
    caps = list(dict.fromkeys([*(existing.get("capabilities") or []), *(discovered.get("capabilities") or [])]))
    merged["capabilities"] = caps
    aliases = list(dict.fromkeys([*(existing.get("aliases") or []), *(discovered.get("aliases") or [])]))
    merged["aliases"] = aliases[:20]
    cfg = dict(discovered.get("config") or {})
    cfg.update(existing.get("config") if isinstance(existing.get("config"), dict) else {})
    cfg["last_discovered_ports"] = list((discovered.get("config") or {}).get("open_ports") or [])
    merged["config"] = cfg
    meta = dict(existing.get("metadata") if isinstance(existing.get("metadata"), dict) else {})
    meta.update(discovered.get("metadata") if isinstance(discovered.get("metadata"), dict) else {})
    meta["last_seen_discovery"] = _now()
    meta["events"] = device_events(merged)
    merged["metadata"] = meta
    merged["updated_at"] = _now()
    return _normalize_device(merged)


def scan_network(
    cidr: str | None = None,
    *,
    ports: list[int] | None = None,
    timeout_ms: int = 220,
    max_hosts: int = 256,
    concurrency: int = 64,
    register: bool = True,
) -> dict[str, Any]:
    networks = [str(cidr)] if cidr else list(discover_networks().get("networks") or [])
    ports_norm = _normalize_ports(ports)
    timeout_sec = max(0.05, min(3.0, float(timeout_ms or 220) / 1000.0))
    workers = max(1, min(128, int(concurrency or 64)))
    hits: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for network in networks:
        try:
            hosts = _bounded_hosts(network, max_hosts=max_hosts)
        except Exception as exc:
            errors.append({"network": network, "error": str(exc)[:160]})
            continue
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_scan_host, host, ports_norm, timeout_sec) for host in hosts]
            for fut in as_completed(futures):
                try:
                    row = fut.result()
                except Exception as exc:
                    errors.append({"network": network, "error": f"{type(exc).__name__}:{str(exc)[:120]}"})
                    continue
                if row:
                    row["network"] = network
                    hits.append(row)
    registered: list[dict[str, Any]] = []
    if register:
        reg = _load_registry()
        devices = reg.setdefault("devices", {})
        for hit in sorted(hits, key=lambda x: str(x.get("ip") or "")):
            discovered = _device_from_discovery(hit)
            did = str(discovered.get("device_id") or "")
            merged = _merge_discovered_device(devices.get(did), discovered)
            devices[did] = merged
            registered.append(merged)
        _save_registry(reg)
    _append_jsonl(ACTION_LEDGER_PATH, {
        "ts": _now(),
        "ledger_id": f"lea_scan_{_hash([networks, ports_norm, hits])}",
        "device_id": "network_discovery",
        "action": "scan_network",
        "requested_by": "ultronpro",
        "reason": "discover_local_network_devices",
        "risk_level": 0,
        "approved": True,
        "result": "success",
        "ok": True,
        "networks": networks,
        "ports": ports_norm,
        "hits": len(hits),
        "registered": len(registered),
        "errors": errors[:20],
    })
    return {
        "ok": True,
        "networks": networks,
        "ports": ports_norm,
        "hits": hits,
        "registered": registered,
        "registered_count": len(registered),
        "errors": errors,
        "registry_path": str(REGISTRY_PATH),
    }


def capability_model() -> dict[str, Any]:
    return {
        "known_capabilities": sorted(KNOWN_CAPABILITIES),
        "risk_by_capability": dict(sorted(CAPABILITY_RISK.items())),
        "risk_model": {
            "0": "observe_state",
            "1": "reversible_low_impact",
            "2": "comfort_or_wake_change",
            "3": "service_script_or_machine_action",
            "4": "destructive_sensitive_or_physical_security",
        },
        "confirmation_threshold": int(os.getenv("ULTRON_LOCAL_ENV_CONFIRM_RISK", "3") or 3),
    }


def evaluate_risk(
    device: dict[str, Any] | None,
    action: str,
    *,
    approved: bool = False,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(device, dict):
        return {"ok": False, "allowed": False, "reason": "device_not_registered", "risk_level": 4, "requires_confirmation": True}
    action = str(action or "").strip()
    if action not in KNOWN_CAPABILITIES:
        return {"ok": False, "allowed": False, "reason": "unknown_capability", "risk_level": 4, "requires_confirmation": True}
    if not bool(device.get("allowed")):
        return {"ok": False, "allowed": False, "reason": "device_not_allowed", "risk_level": int(device.get("risk_level") or 4), "requires_confirmation": True}
    if action not in set(str(x) for x in (device.get("capabilities") or [])):
        return {"ok": False, "allowed": False, "reason": "capability_not_allowed_for_device", "risk_level": int(device.get("risk_level") or 4), "requires_confirmation": True}
    param_risk = int((params or {}).get("risk_level") or 0) if isinstance(params, dict) else 0
    risk = max(int(device.get("risk_level") or 0), int(CAPABILITY_RISK.get(action, 4)), param_risk)
    risk = max(0, min(4, risk))
    threshold = int(os.getenv("ULTRON_LOCAL_ENV_CONFIRM_RISK", "3") or 3)
    requires_confirmation = bool(device.get("requires_confirmation")) or risk >= threshold
    if risk >= 4 and not bool(device.get("allow_high_risk")):
        return {
            "ok": False,
            "allowed": False,
            "reason": "risk4_requires_registry_allow_high_risk",
            "risk_level": risk,
            "requires_confirmation": True,
        }
    if requires_confirmation and not approved:
        return {
            "ok": True,
            "allowed": False,
            "reason": "confirmation_required",
            "risk_level": risk,
            "requires_confirmation": True,
        }
    return {
        "ok": True,
        "allowed": True,
        "reason": "allowed",
        "risk_level": risk,
        "requires_confirmation": requires_confirmation,
    }


def _state_for(device_id: str) -> dict[str, Any]:
    state = _runtime_state()
    devices = state.setdefault("devices", {})
    row = devices.setdefault(str(device_id), {"state": "off", "brightness": 0, "updated_at": _now()})
    return dict(row)


def _set_state_for(device_id: str, row: dict[str, Any]) -> dict[str, Any]:
    state = _runtime_state()
    row = dict(row or {})
    row["updated_at"] = _now()
    state.setdefault("devices", {})[str(device_id)] = row
    _save_runtime_state(state)
    return row


def _typed_observation(device: dict[str, Any], state: dict[str, Any], *, adapter: str, raw: Any = None) -> dict[str, Any]:
    return {
        "ok": True,
        "device_id": device.get("device_id"),
        "adapter": adapter,
        "state": state,
        "observed_at": _now(),
        "raw": raw,
    }


def _mock_observe(device: dict[str, Any]) -> dict[str, Any]:
    return _typed_observation(device, _state_for(str(device.get("device_id"))), adapter="mock")


def _mock_execute(device: dict[str, Any], action: str, params: dict[str, Any]) -> dict[str, Any]:
    did = str(device.get("device_id"))
    state = _state_for(did)
    if action == "turn_on":
        state["state"] = "on"
        if int(state.get("brightness") or 0) <= 0:
            state["brightness"] = 100
    elif action == "turn_off":
        state["state"] = "off"
        state["brightness"] = 0
    elif action == "set_brightness":
        value = max(0, min(100, int(params.get("brightness") or params.get("value") or 0)))
        state["brightness"] = value
        state["state"] = "on" if value > 0 else "off"
    elif action == "set_temperature":
        state["target_temperature"] = float(params.get("temperature") or params.get("value") or 22)
        state["state"] = "on"
    elif action in {"start_service", "wake_device"}:
        state["state"] = "on"
    elif action == "stop_service":
        state["state"] = "off"
    elif action == "restart_service":
        state["state"] = "running"
        state["restart_count"] = int(state.get("restart_count") or 0) + 1
    elif action == "run_script":
        state["last_script_run"] = _now()
        state["state"] = "completed"
    elif action == "send_notification":
        state["last_notification"] = _safe(params.get("message") or params.get("text"), 500)
    elif action != "read_state":
        return {"ok": False, "error": "unsupported_mock_action"}
    saved = _set_state_for(did, state)
    return {"ok": True, "adapter": "mock", "action": action, "state": saved}


def _ha_headers(config: dict[str, Any]) -> dict[str, str]:
    token = str(config.get("token") or "").strip()
    token_env = str(config.get("token_env") or "").strip()
    if token_env:
        token = os.getenv(token_env, token)
    if not token:
        token = os.getenv("ULTRON_HOME_ASSISTANT_TOKEN", "")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _ha_base_url(config: dict[str, Any] | None = None) -> str:
    config = config if isinstance(config, dict) else {}
    return str(config.get("base_url") or os.getenv("ULTRON_HOME_ASSISTANT_URL") or "").rstrip("/")


def _ha_state_url(config: dict[str, Any], entity_id: str, *, stream: bool = False) -> str:
    base_url = _ha_base_url(config)
    encoded = quote(str(entity_id or ""), safe="")
    if stream:
        return f"{base_url}/api/camera_proxy_stream/{encoded}"
    return f"{base_url}/api/camera_proxy/{encoded}"


def home_assistant_status(config: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = config if isinstance(config, dict) else {}
    base_url = _ha_base_url(cfg)
    if not base_url:
        return {"ok": False, "configured": False, "error": "home_assistant_url_not_configured"}
    try:
        with httpx.Client(timeout=float(cfg.get("timeout_sec") or 6.0)) as client:
            resp = client.get(f"{base_url}/api/", headers=_ha_headers(cfg))
            resp.raise_for_status()
            text = resp.text[:300]
        return {"ok": True, "configured": True, "base_url": base_url, "status_code": resp.status_code, "message": text}
    except Exception as exc:
        return {"ok": False, "configured": True, "base_url": base_url, "error": f"{type(exc).__name__}:{str(exc)[:200]}"}


def _ha_entity_to_device(entity: dict[str, Any], *, base_url: str, token_env: str = "ULTRON_HOME_ASSISTANT_TOKEN") -> dict[str, Any] | None:
    entity_id = str(entity.get("entity_id") or "").strip()
    if "." not in entity_id:
        return None
    domain = entity_id.split(".", 1)[0]
    if domain not in {"light", "switch", "input_boolean", "media_player", "camera", "climate", "script", "automation", "fan", "cover", "lock"}:
        return None
    attrs = entity.get("attributes") if isinstance(entity.get("attributes"), dict) else {}
    friendly = _safe(attrs.get("friendly_name") or entity_id, 120)
    caps = _ha_capabilities_for_domain(domain)
    aliases = [entity_id, friendly, _fold(friendly), domain]
    if domain == "media_player":
        aliases.extend(["tv", "televisao", "media", "som", "controle remoto"])
    if domain == "camera":
        aliases.extend(["camera", "cameras", "webcam", "stream"])
    device = {
        "device_id": f"ha_{_slug(entity_id)}",
        "name": friendly,
        "type": _ha_device_type_for_domain(domain),
        "location": _safe(attrs.get("area_id") or attrs.get("room") or "home_assistant", 80),
        "adapter": "home_assistant",
        "capabilities": caps,
        "risk_level": max([CAPABILITY_RISK.get(cap, 0) for cap in caps] or [0]),
        "requires_confirmation": False,
        "allowed": True,
        "aliases": list(dict.fromkeys(aliases))[:30],
        "config": {
            "base_url": base_url,
            "token_env": token_env,
            "entity_id": entity_id,
            "domain": domain,
            "state": entity.get("state"),
        },
        "metadata": {
            "source": "home_assistant",
            "imported_at": _now(),
            "attributes": {k: attrs.get(k) for k in ("device_class", "supported_features", "media_content_type", "manufacturer", "model_name") if k in attrs},
        },
    }
    return device


def import_home_assistant_entities(*, include_domains: list[str] | None = None, base_url: str | None = None, token_env: str = "ULTRON_HOME_ASSISTANT_TOKEN") -> dict[str, Any]:
    cfg = {"base_url": base_url or os.getenv("ULTRON_HOME_ASSISTANT_URL") or "", "token_env": token_env}
    ha_url = _ha_base_url(cfg)
    if not ha_url:
        return {"ok": False, "kind": "home_assistant_import", "error": "home_assistant_url_not_configured", "hint": "Defina ULTRON_HOME_ASSISTANT_URL e ULTRON_HOME_ASSISTANT_TOKEN."}
    domains = {str(x).strip() for x in (include_domains or []) if str(x).strip()}
    try:
        with httpx.Client(timeout=float(os.getenv("ULTRON_HOME_ASSISTANT_TIMEOUT_SEC", "10") or 10)) as client:
            resp = client.get(f"{ha_url}/api/states", headers=_ha_headers(cfg))
            resp.raise_for_status()
            states = resp.json()
    except Exception as exc:
        return {"ok": False, "kind": "home_assistant_import", "error": f"{type(exc).__name__}:{str(exc)[:220]}", "base_url": ha_url}
    if not isinstance(states, list):
        return {"ok": False, "kind": "home_assistant_import", "error": "home_assistant_states_not_list", "base_url": ha_url}
    imported: list[dict[str, Any]] = []
    skipped = 0
    for entity in states:
        if not isinstance(entity, dict):
            continue
        entity_id = str(entity.get("entity_id") or "")
        domain = entity_id.split(".", 1)[0] if "." in entity_id else ""
        if domains and domain not in domains:
            skipped += 1
            continue
        device = _ha_entity_to_device(entity, base_url=ha_url, token_env=token_env)
        if not device:
            skipped += 1
            continue
        out = upsert_device(device)
        if out.get("ok") and isinstance(out.get("device"), dict):
            imported.append(out["device"])
    _append_jsonl(ACTION_LEDGER_PATH, {
        "ts": _now(),
        "ledger_id": f"lea_ha_import_{_hash([ha_url, len(imported), skipped])}",
        "device_id": "home_assistant",
        "action": "import_home_assistant_entities",
        "requested_by": "ultronpro",
        "reason": "sync_home_assistant_registry",
        "risk_level": 0,
        "approved": True,
        "ok": True,
        "result": "success",
        "imported_count": len(imported),
        "skipped_count": skipped,
    })
    return {"ok": True, "kind": "home_assistant_import", "base_url": ha_url, "imported_count": len(imported), "skipped_count": skipped, "devices": imported}


def _home_assistant_observe(device: dict[str, Any]) -> dict[str, Any]:
    config = device.get("config") if isinstance(device.get("config"), dict) else {}
    base_url = _ha_base_url(config)
    entity_id = str(config.get("entity_id") or "").strip()
    if not base_url or not entity_id:
        return {"ok": False, "error": "home_assistant_missing_base_url_or_entity_id"}
    with httpx.Client(timeout=float(config.get("timeout_sec") or 6.0)) as client:
        resp = client.get(f"{base_url}/api/states/{entity_id}", headers=_ha_headers(config))
        resp.raise_for_status()
        data = resp.json()
    state = {"state": data.get("state"), "attributes": data.get("attributes") or {}, "entity_id": entity_id}
    return _typed_observation(device, state, adapter="home_assistant", raw={"entity_id": entity_id})


def _home_assistant_execute(device: dict[str, Any], action: str, params: dict[str, Any]) -> dict[str, Any]:
    config = device.get("config") if isinstance(device.get("config"), dict) else {}
    base_url = _ha_base_url(config)
    entity_id = str(config.get("entity_id") or "").strip()
    if not base_url or not entity_id:
        return {"ok": False, "error": "home_assistant_missing_base_url_or_entity_id"}
    domain = str(config.get("domain") or entity_id.split(".", 1)[0] or "homeassistant")
    service_domain = domain
    service = None
    payload: dict[str, Any] = {"entity_id": entity_id}
    if action in {"turn_on", "turn_off"}:
        service = "turn_on" if action == "turn_on" else "turn_off"
    elif action == "set_brightness":
        service = "turn_on"
        payload["brightness_pct"] = max(0, min(100, int(params.get("brightness") or params.get("value") or 0)))
    elif action == "set_temperature":
        service = "set_temperature"
        payload["temperature"] = float(params.get("temperature") or params.get("value") or 22)
    elif action in {"media_play", "media_pause"}:
        service_domain = "media_player"
        service = "media_play" if action == "media_play" else "media_pause"
    elif action in {"volume_up", "volume_down"}:
        service_domain = "media_player"
        service = "volume_up" if action == "volume_up" else "volume_down"
    elif action == "mute":
        service_domain = "media_player"
        service = "volume_mute"
        payload["is_volume_muted"] = True
    elif action == "set_input":
        service_domain = "media_player"
        service = "select_source"
        payload["source"] = str(params.get("source") or params.get("input") or params.get("value") or "").strip()
        if not payload["source"]:
            return {"ok": False, "error": "home_assistant_source_required"}
    elif action == "capture_snapshot" and domain == "camera":
        url = _ha_state_url(config, entity_id, stream=False)
        with httpx.Client(timeout=float(config.get("timeout_sec") or 8.0)) as client:
            resp = client.get(url, headers=_ha_headers(config))
            resp.raise_for_status()
        return {"ok": True, "adapter": "home_assistant", "action": action, "content_type": resp.headers.get("content-type"), "bytes": len(resp.content or b"")}
    elif action == "view_stream" and domain == "camera":
        viewer_endpoint = f"/api/local-env/devices/{device.get('device_id')}/camera/view"
        viewer_url = _local_api_path(viewer_endpoint)
        opened = _maybe_open_local_url(viewer_url, enabled=bool(params.get("open_viewer", True)))
        return {
            "ok": True,
            "adapter": "home_assistant",
            "action": action,
            "real_time": True,
            "stream_urls": [_ha_state_url(config, entity_id, stream=True)],
            "mjpeg_proxy_endpoint": f"/api/local-env/devices/{device.get('device_id')}/camera/mjpeg",
            "viewer_endpoint": viewer_endpoint,
            "viewer_url": viewer_url,
            "opened_browser": opened,
        }
    if not service:
        return {"ok": False, "error": f"unsupported_home_assistant_action:{action}"}
    repeat = _bounded_repeat(params) if action in {"volume_up", "volume_down"} else 1
    raws: list[Any] = []
    with httpx.Client(timeout=float(config.get("timeout_sec") or 8.0)) as client:
        for idx in range(repeat):
            resp = client.post(f"{base_url}/api/services/{service_domain}/{service}", headers=_ha_headers(config), json=payload)
            resp.raise_for_status()
            try:
                raws.append(resp.json())
            except Exception:
                raws.append({"status_code": resp.status_code})
            if idx + 1 < repeat:
                time.sleep(max(0.02, min(0.5, float(params.get("delay_sec") or 0.08))))
    return {"ok": True, "adapter": "home_assistant", "action": action, "service": f"{service_domain}.{service}", "repeat": repeat, "raw": raws[-3:]}


def _http_request(config: dict[str, Any], action: str) -> dict[str, Any]:
    return _http_request_with_params(config, action, {})


def _render_http_template(value: Any, params: dict[str, Any], action: str) -> Any:
    if isinstance(value, str):
        data = {"action": action, **{str(k): v for k, v in (params or {}).items()}}
        try:
            return value.format(**data)
        except Exception:
            return value
    if isinstance(value, dict):
        return {k: _render_http_template(v, params, action) for k, v in value.items()}
    if isinstance(value, list):
        return [_render_http_template(v, params, action) for v in value]
    return value


def _http_request_with_params(config: dict[str, Any], action: str, params: dict[str, Any]) -> dict[str, Any]:
    endpoints = config.get("endpoints") if isinstance(config.get("endpoints"), dict) else {}
    spec = endpoints.get(action)
    if not isinstance(spec, dict):
        return {"ok": False, "error": f"http_endpoint_not_configured:{action}"}
    url = str(_render_http_template(spec.get("url") or "", params, action)).strip()
    if not url:
        return {"ok": False, "error": "http_url_required"}
    method = str(spec.get("method") or "GET").upper()
    headers = _render_http_template(spec.get("headers") if isinstance(spec.get("headers"), dict) else {}, params, action)
    payload = _render_http_template(spec.get("json") if isinstance(spec.get("json"), dict) else None, params, action)
    timeout = float(spec.get("timeout_sec") or config.get("timeout_sec") or 6.0)
    with httpx.Client(timeout=timeout) as client:
        resp = client.request(method, url, headers=headers, json=payload)
        resp.raise_for_status()
        try:
            data = resp.json()
        except Exception:
            data = {"text": resp.text[:1000], "status_code": resp.status_code}
    return {"ok": True, "status_code": resp.status_code, "data": data}


def _http_observe(device: dict[str, Any]) -> dict[str, Any]:
    config = device.get("config") if isinstance(device.get("config"), dict) else {}
    res = _http_request(config, "read_state")
    if not res.get("ok"):
        return res
    return _typed_observation(device, {"http": res.get("data")}, adapter="http", raw={"status_code": res.get("status_code")})


def _http_execute(device: dict[str, Any], action: str, params: dict[str, Any]) -> dict[str, Any]:
    config = device.get("config") if isinstance(device.get("config"), dict) else {}
    res = _http_request_with_params(config, action, params)
    if not res.get("ok"):
        return res
    return {"ok": True, "adapter": "http", "action": action, "response": res}


def _mqtt_packet_remaining_length(length: int) -> bytes:
    out = bytearray()
    value = max(0, int(length))
    while True:
        encoded = value % 128
        value //= 128
        if value > 0:
            encoded |= 128
        out.append(encoded)
        if value == 0:
            break
    return bytes(out)


def _mqtt_utf8(value: str) -> bytes:
    raw = str(value or "").encode("utf-8")
    return struct.pack("!H", len(raw)) + raw


def _mqtt_publish(host: str, port: int, topic: str, payload: str, *, username: str = "", password: str = "", client_id: str = "ultronpro", timeout_sec: float = 5.0) -> dict[str, Any]:
    if not host or not topic:
        return {"ok": False, "error": "mqtt_host_or_topic_required"}
    variable = _mqtt_utf8("MQTT") + bytes([4])
    flags = 0x02
    if username:
        flags |= 0x80
    if password:
        flags |= 0x40
    variable += bytes([flags]) + struct.pack("!H", 30)
    payload_bytes = _mqtt_utf8(client_id or f"ultronpro-{_hash(time.time())}")
    if username:
        payload_bytes += _mqtt_utf8(username)
    if password:
        payload_bytes += _mqtt_utf8(password)
    connect = bytes([0x10]) + _mqtt_packet_remaining_length(len(variable) + len(payload_bytes)) + variable + payload_bytes
    topic_bytes = _mqtt_utf8(topic)
    message = str(payload or "").encode("utf-8")
    publish = bytes([0x30]) + _mqtt_packet_remaining_length(len(topic_bytes) + len(message)) + topic_bytes + message
    disconnect = bytes([0xE0, 0x00])
    started = time.time()
    with socket.create_connection((host, int(port or 1883)), timeout=max(0.5, timeout_sec)) as sock:
        sock.settimeout(max(0.5, timeout_sec))
        sock.sendall(connect)
        ack = sock.recv(4)
        if len(ack) < 4 or ack[0] != 0x20 or ack[3] != 0:
            return {"ok": False, "error": f"mqtt_connect_refused:{ack.hex()}"}
        sock.sendall(publish)
        sock.sendall(disconnect)
    return {"ok": True, "topic": topic, "bytes": len(message), "latency_ms": int((time.time() - started) * 1000)}


def _mqtt_config(device: dict[str, Any]) -> dict[str, Any]:
    config = device.get("config") if isinstance(device.get("config"), dict) else {}
    mqtt = config.get("mqtt") if isinstance(config.get("mqtt"), dict) else config
    return mqtt if isinstance(mqtt, dict) else {}


def _mqtt_execute(device: dict[str, Any], action: str, params: dict[str, Any]) -> dict[str, Any]:
    mqtt = _mqtt_config(device)
    topics = mqtt.get("topics") if isinstance(mqtt.get("topics"), dict) else {}
    payloads = mqtt.get("payloads") if isinstance(mqtt.get("payloads"), dict) else {}
    topic = str(topics.get(action) or mqtt.get(f"{action}_topic") or "").strip()
    if not topic:
        return {"ok": False, "adapter": "mqtt", "action": action, "error": f"mqtt_topic_not_configured:{action}"}
    payload = str(payloads.get(action) if action in payloads else params.get("payload") if params.get("payload") is not None else action)
    username = str(mqtt.get("username") or os.getenv(str(mqtt.get("username_env") or "ULTRON_MQTT_USERNAME")) or "")
    password = str(mqtt.get("password") or os.getenv(str(mqtt.get("password_env") or "ULTRON_MQTT_PASSWORD")) or "")
    res = _mqtt_publish(
        str(mqtt.get("host") or os.getenv("ULTRON_MQTT_HOST") or ""),
        int(mqtt.get("port") or os.getenv("ULTRON_MQTT_PORT") or 1883),
        topic,
        payload,
        username=username,
        password=password,
        client_id=str(mqtt.get("client_id") or "ultronpro"),
        timeout_sec=float(mqtt.get("timeout_sec") or 5.0),
    )
    return {**res, "adapter": "mqtt", "action": action}


def _mqtt_observe(device: dict[str, Any]) -> dict[str, Any]:
    mqtt = _mqtt_config(device)
    state_topic = str(mqtt.get("state_topic") or "").strip()
    state = {"state": "mqtt_configured" if state_topic else "mqtt_publish_only", "state_topic": state_topic}
    return _typed_observation(device, state, adapter="mqtt")


def _valid_service_name(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_.@:-]{1,120}", str(value or "")))


def _service_observe(device: dict[str, Any]) -> dict[str, Any]:
    config = device.get("config") if isinstance(device.get("config"), dict) else {}
    service = str(config.get("service_name") or "").strip()
    if not _valid_service_name(service):
        return {"ok": False, "error": "invalid_or_missing_service_name"}
    if platform.system().lower().startswith("win"):
        cmd = ["powershell", "-NoProfile", "-Command", f"Get-Service -Name '{service}' | Select-Object -ExpandProperty Status"]
    else:
        cmd = ["systemctl", "is-active", service]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
    state = (proc.stdout or proc.stderr or "").strip().splitlines()[0:1]
    return _typed_observation(
        device,
        {"state": (state[0].lower() if state else "unknown"), "service_name": service, "returncode": proc.returncode},
        adapter="local_service",
    )


def _service_execute(device: dict[str, Any], action: str, params: dict[str, Any]) -> dict[str, Any]:
    config = device.get("config") if isinstance(device.get("config"), dict) else {}
    service = str(config.get("service_name") or "").strip()
    if not _valid_service_name(service):
        return {"ok": False, "error": "invalid_or_missing_service_name"}
    if action not in {"start_service", "stop_service", "restart_service"}:
        return {"ok": False, "error": f"unsupported_service_action:{action}"}
    if platform.system().lower().startswith("win"):
        verb = {"start_service": "Start-Service", "stop_service": "Stop-Service", "restart_service": "Restart-Service"}[action]
        cmd = ["powershell", "-NoProfile", "-Command", f"{verb} -Name '{service}'"]
    else:
        verb = {"start_service": "start", "stop_service": "stop", "restart_service": "restart"}[action]
        cmd = ["systemctl", verb, service]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=int(config.get("timeout_sec") or 20))
    return {
        "ok": proc.returncode == 0,
        "adapter": "local_service",
        "action": action,
        "returncode": proc.returncode,
        "stdout": (proc.stdout or "")[:2000],
        "stderr": (proc.stderr or "")[:2000],
    }


def _script_execute(device: dict[str, Any], action: str, params: dict[str, Any]) -> dict[str, Any]:
    if action != "run_script":
        return {"ok": False, "error": f"unsupported_script_action:{action}"}
    config = device.get("config") if isinstance(device.get("config"), dict) else {}
    command = config.get("command")
    if not isinstance(command, list) or not command:
        return {"ok": False, "error": "script_command_list_required"}
    command = [str(x) for x in command]
    extra_args = [str(x) for x in (params.get("args") or [])] if bool(config.get("allow_args")) and isinstance(params.get("args"), list) else []
    cwd = str(config.get("cwd") or DATA_DIR)
    timeout = max(1, min(300, int(config.get("timeout_sec") or params.get("timeout_sec") or 60)))
    proc = subprocess.run(command + extra_args, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    return {
        "ok": proc.returncode == 0,
        "adapter": "local_script",
        "returncode": proc.returncode,
        "stdout": (proc.stdout or "")[:4000],
        "stderr": (proc.stderr or "")[:4000],
    }


def _wol_execute(device: dict[str, Any], action: str, params: dict[str, Any]) -> dict[str, Any]:
    if action != "wake_device":
        return {"ok": False, "error": f"unsupported_wol_action:{action}"}
    config = device.get("config") if isinstance(device.get("config"), dict) else {}
    mac = re.sub(r"[^0-9A-Fa-f]", "", str(config.get("mac") or params.get("mac") or ""))
    if len(mac) != 12:
        return {"ok": False, "error": "invalid_mac"}
    packet = bytes.fromhex("FF" * 6 + mac * 16)
    broadcast = str(config.get("broadcast") or "255.255.255.255")
    port = int(config.get("port") or 9)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.sendto(packet, (broadcast, port))
    finally:
        sock.close()
    return {"ok": True, "adapter": "wake_on_lan", "broadcast": broadcast, "port": port}


def _notification_execute(device: dict[str, Any], action: str, params: dict[str, Any]) -> dict[str, Any]:
    if action != "send_notification":
        return {"ok": False, "error": f"unsupported_notification_action:{action}"}
    message = _safe(params.get("message") or params.get("text"), 1000)
    state = _runtime_state()
    notifications = state.setdefault("notifications", [])
    row = {"ts": _now(), "device_id": device.get("device_id"), "message": message}
    notifications.append(row)
    state["notifications"] = notifications[-200:]
    _save_runtime_state(state)
    current = _state_for(str(device.get("device_id")))
    current["last_notification"] = message
    _set_state_for(str(device.get("device_id")), current)
    return {"ok": True, "adapter": "notification", "notification": row}


def _roku_key(action: str, params: dict[str, Any]) -> str:
    explicit = str(params.get("key") or params.get("button") or "").strip()
    if explicit:
        return explicit
    return {
        "turn_on": "PowerOn",
        "turn_off": "PowerOff",
        "media_play": "Play",
        "media_pause": "Play",
        "volume_up": "VolumeUp",
        "volume_down": "VolumeDown",
        "mute": "VolumeMute",
    }.get(action, "")


def _roku_ecp_request(ip: str, path: str, *, timeout_sec: float = 4.0) -> dict[str, Any]:
    url = f"http://{ip}:8060{path}"
    with httpx.Client(timeout=timeout_sec) as client:
        resp = client.post(url)
        resp.raise_for_status()
    return {"ok": True, "url": url, "status_code": int(resp.status_code)}


def _bounded_repeat(params: dict[str, Any], *, default: int = 1) -> int:
    try:
        repeat = int(params.get("repeat") or params.get("times") or params.get("amount") or default)
    except Exception:
        repeat = default
    limit = int(os.getenv("ULTRON_LOCAL_ENV_MAX_KEY_REPEAT", "200") or 200)
    return max(1, min(max(1, limit), repeat))


def _repeatable_keypress_request(adapter: str, request_fn: Any, key_path: str, *, repeat: int, delay_sec: float = 0.08) -> dict[str, Any]:
    attempts: list[dict[str, Any]] = []
    ok_count = 0
    for idx in range(max(1, repeat)):
        res = request_fn(key_path)
        attempts.append({"index": idx + 1, "ok": bool(res.get("ok")), "status_code": res.get("status_code"), "error": res.get("error")})
        if not res.get("ok"):
            return {"ok": False, "adapter": adapter, "sent_count": ok_count, "repeat": repeat, "attempts": attempts[-5:], "error": res.get("error") or "keypress_failed"}
        ok_count += 1
        if idx + 1 < repeat and delay_sec > 0:
            time.sleep(delay_sec)
    return {"ok": True, "adapter": adapter, "sent_count": ok_count, "repeat": repeat, "attempts": attempts[-5:]}


def _ws_client_frame_text(text: str) -> bytes:
    payload = str(text or "").encode("utf-8")
    frame = bytearray([0x81])
    length = len(payload)
    if length <= 125:
        frame.append(0x80 | length)
    elif length <= 65535:
        frame.append(0x80 | 126)
        frame.extend(struct.pack("!H", length))
    else:
        frame.append(0x80 | 127)
        frame.extend(struct.pack("!Q", length))
    mask = os.urandom(4)
    frame.extend(mask)
    frame.extend(byte ^ mask[idx % 4] for idx, byte in enumerate(payload))
    return bytes(frame)


def _websocket_connect(host: str, port: int, path: str, *, tls: bool, timeout_sec: float) -> socket.socket:
    raw = socket.create_connection((host, int(port)), timeout=max(0.5, timeout_sec))
    sock: socket.socket = raw
    if tls:
        ctx = ssl._create_unverified_context()
        sock = ctx.wrap_socket(raw, server_hostname=host)
    sock.settimeout(max(0.5, timeout_sec))
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    req = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}:{int(port)}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        "Origin: http://localhost\r\n"
        "\r\n"
    )
    sock.sendall(req.encode("ascii", errors="ignore"))
    data = b""
    deadline = time.time() + max(1.0, timeout_sec)
    while b"\r\n\r\n" not in data and time.time() < deadline:
        chunk = sock.recv(4096)
        if not chunk:
            break
        data += chunk
    head = data.decode("latin-1", errors="ignore")
    if " 101 " not in head.split("\r\n", 1)[0]:
        try:
            sock.close()
        finally:
            pass
        raise RuntimeError(_safe(head.split("\r\n", 1)[0] or "websocket_handshake_failed", 180))
    return sock


def _samsung_key(action: str, params: dict[str, Any]) -> str:
    explicit = str(params.get("key") or params.get("button") or "").strip()
    if explicit:
        key = explicit.upper().replace("-", "_")
        aliases = {
            "VOLUP": "KEY_VOLUP",
            "VOLUMEUP": "KEY_VOLUP",
            "VOLDOWN": "KEY_VOLDOWN",
            "VOLUMEDOWN": "KEY_VOLDOWN",
            "MUTE": "KEY_MUTE",
            "POWER": "KEY_POWER",
            "PLAY": "KEY_PLAY",
            "PAUSE": "KEY_PAUSE",
            "HOME": "KEY_HOME",
            "SOURCE": "KEY_SOURCE",
            "HDMI": "KEY_SOURCE",
        }
        return aliases.get(key, key if key.startswith("KEY_") else f"KEY_{key}")
    return {
        "turn_on": "KEY_POWERON",
        "turn_off": "KEY_POWEROFF",
        "media_play": "KEY_PLAY",
        "media_pause": "KEY_PAUSE",
        "volume_up": "KEY_VOLUP",
        "volume_down": "KEY_VOLDOWN",
        "mute": "KEY_MUTE",
        "send_key": "",
        "set_input": "KEY_SOURCE",
    }.get(action, "")


def _samsung_tv_execute(device: dict[str, Any], action: str, params: dict[str, Any]) -> dict[str, Any]:
    config = device.get("config") if isinstance(device.get("config"), dict) else {}
    ip = str(config.get("ip") or "").strip()
    if not ip:
        return {"ok": False, "adapter": "samsung_ws", "action": action, "error": "missing_ip"}
    if action == "launch_app":
        return {
            "ok": False,
            "adapter": "samsung_ws",
            "action": action,
            "error": "launch_app_requires_samsung_app_id_protocol",
            "hint": "O controle remoto WebSocket cobre teclas, volume, play/pause e power. Launch app precisa de app id Tizen especifico.",
        }
    key = _samsung_key(action, params)
    if not key:
        return {"ok": False, "adapter": "samsung_ws", "action": action, "error": "key_required"}
    ports = _device_ports(config)
    configured_ports = config.get("remote_ports")
    if isinstance(configured_ports, list) and configured_ports:
        ports = _normalize_ports([int(p) for p in configured_ports])
    candidates: list[tuple[int, bool]] = []
    if 8002 in ports:
        candidates.append((8002, True))
    if 8001 in ports:
        candidates.append((8001, False))
    if not candidates:
        return {
            "ok": False,
            "adapter": "samsung_ws",
            "action": action,
            "error": "samsung_websocket_port_not_detected",
            "hint": "Refaca a varredura ou cadastre remote_ports=[8001,8002] no registry do dispositivo.",
        }
    app_name = str(config.get("client_name") or os.getenv("ULTRON_SAMSUNG_REMOTE_NAME") or "UltronPro").strip()
    encoded_name = base64.b64encode(app_name.encode("utf-8", errors="ignore")).decode("ascii")
    timeout_sec = float(config.get("timeout_sec") or 5.0)
    repeat = _bounded_repeat(params)
    delay = max(0.02, min(0.5, float(params.get("delay_sec") or config.get("key_delay_sec") or 0.08)))
    payload = json.dumps(
        {
            "method": "ms.remote.control",
            "params": {
                "Cmd": "Click",
                "DataOfCmd": key,
                "Option": "false",
                "TypeOfRemote": "SendRemoteKey",
            },
        },
        separators=(",", ":"),
    )
    errors: list[dict[str, Any]] = []
    for port, tls in candidates:
        path = f"/api/v2/channels/samsung.remote.control?name={quote(encoded_name)}"
        try:
            sock = _websocket_connect(ip, port, path, tls=tls, timeout_sec=timeout_sec)
            try:
                for idx in range(repeat):
                    sock.sendall(_ws_client_frame_text(payload))
                    if idx + 1 < repeat:
                        time.sleep(delay)
            finally:
                try:
                    sock.close()
                except Exception:
                    pass
            return {
                "ok": True,
                "adapter": "samsung_ws",
                "action": action,
                "key": key,
                "repeat": repeat,
                "sent_count": repeat,
                "port": port,
                "tls": tls,
                "pairing_note": "Se for o primeiro uso, a TV pode pedir autorizacao na tela.",
            }
        except Exception as exc:
            errors.append({"port": port, "tls": tls, "error": f"{type(exc).__name__}:{str(exc)[:180]}"})
    return {
        "ok": False,
        "adapter": "samsung_ws",
        "action": action,
        "key": key,
        "repeat": repeat,
        "error": "samsung_websocket_failed",
        "attempts": errors,
        "hint": "Verifique se a TV esta ligada e aceite a solicitacao de controle remoto exibida na tela.",
    }


def _network_probe_execute(device: dict[str, Any], action: str, params: dict[str, Any]) -> dict[str, Any]:
    config = device.get("config") if isinstance(device.get("config"), dict) else {}
    ip = str(config.get("ip") or "").strip()
    ports = _device_ports(config)
    dtype = str(device.get("type") or "")
    if action == "open_web_interface":
        urls = _web_urls(ip, ports)
        return {"ok": bool(urls), "adapter": "network_probe", "action": action, "urls": urls, "error": "" if urls else "no_web_interface_detected"}
    if action == "view_stream":
        urls = _rtsp_url_candidates(ip, ports, config)
        viewer_endpoint = f"/api/local-env/devices/{device.get('device_id')}/camera/view"
        viewer_url = _local_api_path(viewer_endpoint)
        decoder = camera_decoder_status(protocol="rtsp")
        opened = False
        external = None
        if urls and bool(params.get("open_viewer", True)):
            if decoder.get("can_proxy"):
                opened = _maybe_open_local_url(viewer_url, enabled=True)
            elif decoder.get("can_open_external"):
                external = open_camera_external(str(device.get("device_id") or ""))
                opened = bool(external.get("ok")) if isinstance(external, dict) else False
            else:
                opened = _maybe_open_local_url(viewer_url, enabled=True)
        return {
            "ok": bool(urls),
            "adapter": "network_probe",
            "action": action,
            "real_time": bool(urls),
            "stream_urls": urls,
            "mjpeg_proxy_endpoint": f"/api/local-env/devices/{device.get('device_id')}/camera/mjpeg",
            "viewer_endpoint": viewer_endpoint,
            "viewer_url": viewer_url,
            "opened_browser": opened,
            "decoder": decoder,
            "external_player": external,
            "error": "" if urls else "no_stream_url_detected",
        }
    if action == "capture_snapshot":
        snapshot_url = str(config.get("snapshot_url") or "").strip()
        if not snapshot_url:
            return {"ok": False, "adapter": "network_probe", "action": action, "error": "snapshot_url_not_configured"}
        with httpx.Client(timeout=float(config.get("timeout_sec") or 8.0), verify=False) as client:
            resp = client.get(snapshot_url)
            resp.raise_for_status()
        return {
            "ok": True,
            "adapter": "network_probe",
            "action": action,
            "content_type": resp.headers.get("content-type"),
            "bytes": len(resp.content or b""),
        }
    if dtype == "roku_tv_or_streamer" and 8060 in set(ports):
        if action == "launch_app":
            app_id = str(params.get("app_id") or params.get("value") or "").strip()
            if not app_id:
                return {"ok": False, "adapter": "roku_ecp", "action": action, "error": "app_id_required"}
            return {**_roku_ecp_request(ip, f"/launch/{app_id}"), "adapter": "roku_ecp", "action": action}
        if action == "send_key":
            key = _roku_key(action, params)
            if not key:
                return {"ok": False, "adapter": "roku_ecp", "action": action, "error": "key_required"}
            repeat = _bounded_repeat(params)
            res = _repeatable_keypress_request("roku_ecp", lambda path: _roku_ecp_request(ip, path), f"/keypress/{quote(key)}", repeat=repeat)
            return {**res, "action": action, "key": key}
        if action in {"turn_on", "turn_off", "media_play", "media_pause", "volume_up", "volume_down", "mute"}:
            key = _roku_key(action, params)
            repeat = _bounded_repeat(params)
            res = _repeatable_keypress_request("roku_ecp", lambda path: _roku_ecp_request(ip, path), f"/keypress/{quote(key)}", repeat=repeat)
            return {**res, "action": action, "key": key}
    if action == "turn_on" and config.get("mac"):
        return _wol_execute(device, "wake_device", params)
    if (dtype == "samsung_tv_or_media_device" or {8001, 8002, 55000} & set(ports)) and action in {
        "turn_on",
        "turn_off",
        "media_play",
        "media_pause",
        "volume_up",
        "volume_down",
        "mute",
        "send_key",
        "launch_app",
        "set_input",
    }:
        return _samsung_tv_execute(device, action, params)
    return {
        "ok": False,
        "adapter": "network_probe",
        "action": action,
        "error": "adapter_configuration_required",
        "hint": "Configure um adapter especifico (Home Assistant, Roku ECP, Samsung/WebOS ou endpoint HTTP) para executar este comando com verificacao.",
    }


def _network_probe_observe(device: dict[str, Any]) -> dict[str, Any]:
    config = device.get("config") if isinstance(device.get("config"), dict) else {}
    ip = str(config.get("ip") or "").strip()
    if not ip:
        return {"ok": False, "error": "network_probe_missing_ip"}
    ports = _normalize_ports(_device_ports(config) or DEFAULT_DISCOVERY_PORTS)
    timeout_sec = max(0.05, min(2.0, float(config.get("timeout_ms") or 220) / 1000.0))
    open_ports = [port for port in ports if _tcp_port_open(ip, port, timeout_sec)]
    state = {
        "state": "reachable" if open_ports else "unreachable",
        "ip": ip,
        "open_ports": open_ports,
        "fingerprint": _classify_open_ports(open_ports) if open_ports else {},
    }
    out = _typed_observation(device, state, adapter="network_probe")
    out["ok"] = bool(open_ports)
    if not open_ports:
        out["error"] = "network_device_unreachable"
    return out


def observe_device(device_id: str) -> dict[str, Any]:
    device = get_device(device_id)
    if not device:
        return {"ok": False, "error": "device_not_registered", "device_id": str(device_id or "")}
    if "read_state" not in set(device.get("capabilities") or []):
        return {"ok": False, "error": "read_state_not_allowed", "device_id": device.get("device_id")}
    adapter = str(device.get("adapter") or "mock")
    config = device.get("config") if isinstance(device.get("config"), dict) else {}
    try:
        if adapter == "mock":
            return _mock_observe(device)
        if adapter == "home_assistant" or (config.get("entity_id") and _ha_base_url(config)):
            return _home_assistant_observe(device)
        if adapter == "mqtt" or isinstance(config.get("mqtt"), dict):
            return _mqtt_observe(device)
        if adapter == "local_service":
            return _service_observe(device)
        if adapter == "http" or isinstance(config.get("endpoints"), dict):
            return _http_observe(device)
        if adapter == "network_probe":
            return _network_probe_observe(device)
        if adapter in {"local_script", "wake_on_lan", "notification"}:
            return _typed_observation(device, _state_for(str(device.get("device_id"))), adapter=adapter)
        return {"ok": False, "error": f"unsupported_adapter:{adapter}", "device_id": device.get("device_id")}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}:{str(exc)[:240]}", "device_id": device.get("device_id")}


def _execute_adapter(device: dict[str, Any], action: str, params: dict[str, Any]) -> dict[str, Any]:
    adapter = str(device.get("adapter") or "mock")
    config = device.get("config") if isinstance(device.get("config"), dict) else {}
    if action == "read_state":
        return observe_device(str(device.get("device_id")))
    try:
        if adapter == "mock":
            return _mock_execute(device, action, params)
        if adapter == "home_assistant" or (config.get("entity_id") and _ha_base_url(config)):
            res = _home_assistant_execute(device, action, params)
            if res.get("ok") or not (isinstance(config.get("mqtt"), dict) or "service_name" in config or isinstance(config.get("endpoints"), dict)):
                return res
        if adapter == "mqtt" or isinstance(config.get("mqtt"), dict):
            res = _mqtt_execute(device, action, params)
            if res.get("ok") or adapter == "mqtt":
                return res
        if adapter == "local_service":
            return _service_execute(device, action, params)
        if adapter == "http" or isinstance(config.get("endpoints"), dict):
            res = _http_execute(device, action, params)
            if res.get("ok") or adapter == "http":
                return res
        if adapter == "local_script":
            return _script_execute(device, action, params)
        if adapter == "wake_on_lan":
            return _wol_execute(device, action, params)
        if adapter == "notification":
            return _notification_execute(device, action, params)
        if isinstance(config.get("mqtt"), dict):
            res = _mqtt_execute(device, action, params)
            if res.get("ok"):
                return res
        if "service_name" in config:
            res = _service_execute(device, action, params)
            if res.get("ok"):
                return res
        if isinstance(config.get("endpoints"), dict):
            res = _http_execute(device, action, params)
            if res.get("ok"):
                return res
        if adapter == "network_probe":
            return _network_probe_execute(device, action, params)
        return {"ok": False, "error": f"unsupported_adapter:{adapter}"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout"}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}:{str(exc)[:240]}"}


def _expected_after(action: str, params: dict[str, Any]) -> dict[str, Any]:
    if action == "turn_on":
        return {"state": "on"}
    if action == "turn_off":
        return {"state": "off"}
    if action == "set_brightness":
        return {"brightness": max(0, min(100, int(params.get("brightness") or params.get("value") or 0)))}
    if action == "set_temperature":
        return {"target_temperature": float(params.get("temperature") or params.get("value") or 22)}
    if action == "start_service":
        return {"state_any": ["running", "active"]}
    if action == "stop_service":
        return {"state_any": ["stopped", "inactive"]}
    if action == "restart_service":
        return {"state_any": ["running", "active"]}
    if action == "send_notification":
        return {"last_notification": _safe(params.get("message") or params.get("text"), 1000)}
    return {}


def _value_at(state: dict[str, Any], key: str) -> Any:
    if key in state:
        return state.get(key)
    attrs = state.get("attributes") if isinstance(state.get("attributes"), dict) else {}
    if key in attrs:
        return attrs.get(key)
    http = state.get("http") if isinstance(state.get("http"), dict) else {}
    if key in http:
        return http.get(key)
    return None


def _verify(action: str, params: dict[str, Any], before: dict[str, Any], after: dict[str, Any], execution: dict[str, Any]) -> dict[str, Any]:
    expected = dict(params.get("expected_state") or {}) if isinstance(params.get("expected_state"), dict) else _expected_after(action, params)
    if not expected:
        return {
            "ok": bool(execution.get("ok")),
            "status": "execution_only",
            "expected": expected,
            "surprise_score": 0.0 if bool(execution.get("ok")) else 1.0,
        }
    after_state = after.get("state") if isinstance(after.get("state"), dict) else {}
    checks: list[dict[str, Any]] = []
    passed = True
    for key, expected_value in expected.items():
        if key == "state_any":
            actual = _safe(_value_at(after_state, "state"), 80).lower()
            accepted = [str(x).lower() for x in expected_value]
            ok = actual in accepted
        else:
            actual = _value_at(after_state, key)
            ok = str(actual).lower() == str(expected_value).lower()
        checks.append({"key": key, "expected": expected_value, "actual": actual, "ok": ok})
        passed = passed and ok
    return {
        "ok": bool(passed),
        "status": "confirmed" if passed else "refuted",
        "expected": expected,
        "checks": checks,
        "surprise_score": 0.0 if passed else 1.0,
    }


def _causal_update(device: dict[str, Any], action: str, verification: dict[str, Any], ledger_id: str, before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    try:
        from ultronpro import causal_graph

        return causal_graph.apply_delta_update(
            cause=f"local_env:{device.get('device_id')}:{action}",
            effect=f"verified:{verification.get('status') or 'unknown'}",
            condition=f"adapter={device.get('adapter')} risk={device.get('risk_level')}",
            category="confirmed" if bool(verification.get("ok")) else "refuted",
            evidence={
                "ledger_id": ledger_id,
                "device_id": device.get("device_id"),
                "action": action,
                "before_hash": _hash(before),
                "after_hash": _hash(after),
                "verification": verification,
            },
            source="local_environment",
        )
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}:{str(exc)[:160]}"}


def _record_episode(row: dict[str, Any]) -> None:
    try:
        from ultronpro import episodic_memory

        episodic_memory.append_episode(
            action_id=int(hashlib.sha1(str(row.get("ledger_id")).encode("utf-8")).hexdigest()[:8], 16),
            kind="local_environment.action",
            text=f"{row.get('device_id')}:{row.get('action')} reason={_safe(row.get('reason'), 240)}",
            task_type=f"local_environment:{row.get('action')}",
            strategy=f"adapter:{row.get('adapter')}",
            ok=bool(row.get("ok")),
            latency_ms=int(row.get("latency_ms") or 0),
            error="" if bool(row.get("ok")) else _safe(row.get("result"), 160),
            meta=row,
            authorship_origin="user_command" if str(row.get("requested_by") or "").startswith(("user", "chat")) else "local_environment",
        )
    except Exception:
        pass


def _ledger_row(base: dict[str, Any]) -> dict[str, Any]:
    row = dict(base or {})
    row.setdefault("ts", _now())
    row.setdefault("ledger_id", f"lea_{_hash([row.get('ts'), row.get('device_id'), row.get('action'), row.get('reason')])}")
    _append_jsonl(ACTION_LEDGER_PATH, row)
    return row


def act_device(
    device_id: str,
    action: str,
    *,
    params: dict[str, Any] | None = None,
    reason: str = "",
    requested_by: str = "ultronpro",
    approved: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    params = dict(params or {})
    device = get_device(device_id)
    gate = evaluate_risk(device, action, approved=approved, params=params)
    before = observe_device(device_id) if device and "read_state" in set(device.get("capabilities") or []) else {"ok": False, "error": "not_observed"}
    base = {
        "device_id": str(device_id or ""),
        "action": str(action or ""),
        "adapter": (device or {}).get("adapter"),
        "requested_by": _safe(requested_by, 120),
        "reason": _safe(reason, 500),
        "risk_level": int(gate.get("risk_level") or 0),
        "approved": bool(approved),
        "requires_confirmation": bool(gate.get("requires_confirmation")),
        "gate": gate,
        "params_hash": _hash(params),
        "observed_before": before.get("state") if isinstance(before, dict) else None,
    }
    started = time.time()
    if not gate.get("allowed"):
        result = "dry_run" if dry_run else str(gate.get("reason") or "blocked")
        row = _ledger_row({**base, "ok": False, "result": result, "latency_ms": int((time.time() - started) * 1000)})
        return {"ok": False, "status": result, "device": device, "gate": gate, "ledger": row, "observed_before": before}
    if dry_run:
        row = _ledger_row({**base, "ok": True, "result": "dry_run_allowed", "latency_ms": int((time.time() - started) * 1000)})
        return {"ok": True, "status": "dry_run_allowed", "device": device, "gate": gate, "ledger": row, "observed_before": before}

    execution = _execute_adapter(device or {}, str(action or ""), params)
    after = observe_device(device_id) if device and "read_state" in set(device.get("capabilities") or []) else {"ok": False, "error": "not_observed"}
    verification = _verify(str(action or ""), params, before if isinstance(before, dict) else {}, after if isinstance(after, dict) else {}, execution)
    ok = bool(execution.get("ok")) and bool(verification.get("ok"))
    result = "success" if ok else ("verification_failed" if execution.get("ok") else "execution_failed")
    ledger_id = f"lea_{_hash([_now(), device_id, action, params, execution, verification])}"
    causal = _causal_update(device or {}, str(action or ""), verification, ledger_id, before if isinstance(before, dict) else {}, after if isinstance(after, dict) else {})
    row = _ledger_row({
        **base,
        "ledger_id": ledger_id,
        "ok": ok,
        "result": result,
        "execution": execution,
        "observed_after": after.get("state") if isinstance(after, dict) else None,
        "verification": verification,
        "causal_update": causal,
        "latency_ms": int((time.time() - started) * 1000),
    })
    _record_episode(row)
    return {
        "ok": ok,
        "status": result,
        "device": device,
        "gate": gate,
        "observed_before": before,
        "execution": execution,
        "observed_after": after,
        "verification": verification,
        "causal_update": causal,
        "ledger": row,
    }


def recent_actions(limit: int = 50) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    if ACTION_LEDGER_PATH.exists():
        try:
            for line in ACTION_LEDGER_PATH.read_text(encoding="utf-8", errors="ignore").splitlines()[-max(1, int(limit or 50)):]:
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                except Exception:
                    continue
                if isinstance(item, dict):
                    rows.append(item)
        except Exception:
            pass
    return {"ok": True, "path": str(ACTION_LEDGER_PATH), "items": rows, "count": len(rows)}


def _control_grant_payload(*, reason: str, responsive: bool, scope: str = "registered_capabilities") -> dict[str, Any]:
    return {
        "granted": bool(responsive),
        "scope": scope,
        "reason": _safe(reason, 240),
        "requires_registry": True,
        "requires_user_command": True,
        "risk_gate_active": True,
        "granted_at": _now(),
    }


def grant_full_control(
    device_id: str | None = None,
    *,
    include_unreachable: bool = False,
    reason: str = "user_requested_full_control",
) -> dict[str, Any]:
    reg = _load_registry()
    devices = reg.setdefault("devices", {})
    changed: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for did, device in list(devices.items()):
        if device_id and str(did) != str(device_id):
            continue
        if not isinstance(device, dict):
            continue
        meta = device.get("metadata") if isinstance(device.get("metadata"), dict) else {}
        last_access = meta.get("last_access_test") if isinstance(meta.get("last_access_test"), dict) else {}
        responsive = bool(last_access.get("ok"))
        if not include_unreachable and last_access and not responsive:
            skipped.append({"device_id": did, "reason": "last_access_test_not_responsive"})
            continue
        device["allowed"] = True
        device["metadata"] = dict(meta)
        device["metadata"]["control_grant"] = _control_grant_payload(reason=reason, responsive=True)
        device["metadata"]["control_mode"] = "full_registered_capability_control"
        device["updated_at"] = _now()
        devices[did] = _normalize_device(device)
        changed.append({
            "device_id": did,
            "capabilities": devices[did].get("capabilities") or [],
            "risk_level": devices[did].get("risk_level"),
            "requires_confirmation": devices[did].get("requires_confirmation"),
        })
    _save_registry(reg)
    _append_jsonl(ACTION_LEDGER_PATH, {
        "ts": _now(),
        "ledger_id": f"lea_grant_{_hash([device_id, include_unreachable, changed])}",
        "device_id": str(device_id or "*"),
        "action": "grant_full_control",
        "requested_by": "ultronpro",
        "reason": _safe(reason, 500),
        "risk_level": 1,
        "approved": True,
        "ok": True,
        "result": "success",
        "changed_count": len(changed),
        "skipped_count": len(skipped),
        "changed": changed[:100],
        "skipped": skipped[:100],
    })
    return {"ok": True, "changed": changed, "changed_count": len(changed), "skipped": skipped, "skipped_count": len(skipped), "path": str(REGISTRY_PATH)}


def test_device_access(device_id: str, *, timeout_ms: int = 800, persist: bool = True) -> dict[str, Any]:
    device = get_device(device_id)
    if not device:
        return {"ok": False, "device_id": str(device_id or ""), "error": "device_not_registered"}
    config = device.get("config") if isinstance(device.get("config"), dict) else {}
    ip = str(config.get("ip") or "").strip()
    ports = _normalize_ports(_device_ports(config)) if ip and _device_ports(config) else []
    timeout_sec = max(0.05, min(3.0, float(timeout_ms or 800) / 1000.0))
    started = time.time()
    port_probes: list[dict[str, Any]] = []
    for port in ports:
        port_probes.append(_probe_access_port(ip, int(port), timeout_sec))
    observation = observe_device(str(device.get("device_id") or ""))
    responsive_ports = [int(p.get("port") or 0) for p in port_probes if bool(p.get("ok"))]
    ok = bool(responsive_ports) or bool(observation.get("ok"))
    status = "responsive" if ok else "unresponsive"
    inferred_type = str(device.get("type") or "")
    inferred_caps = list(device.get("capabilities") or [])
    if ip and responsive_ports:
        fp = _classify_open_ports(responsive_ports)
        inferred_type = str(fp.get("type") or inferred_type)
        inferred_caps = list(dict.fromkeys([*inferred_caps, *_capabilities_for_type(inferred_type, responsive_ports)]))
    device_view = dict(device)
    device_view["type"] = inferred_type
    device_view["capabilities"] = inferred_caps
    if ip and responsive_ports:
        cfg_view = dict(config)
        cfg_view["last_access_ports"] = responsive_ports
        cfg_view.setdefault("web_urls", _web_urls(ip, responsive_ports))
        cfg_view.setdefault("rtsp_url_candidates", _rtsp_url_candidates(ip, responsive_ports, config))
        device_view["config"] = cfg_view
    events = device_events(device_view)
    result = {
        "ok": ok,
        "status": status,
        "device_id": device.get("device_id"),
        "name": device.get("name"),
        "type": inferred_type,
        "adapter": device.get("adapter"),
        "ip": ip,
        "ports_tested": ports,
        "responsive_ports": responsive_ports,
        "port_probes": port_probes,
        "events": events,
        "event_count": len(events),
        "stream": camera_stream_info_for_device(device_view) if any(e.get("event") == "view_stream" for e in events) else None,
        "observation": {
            "ok": bool(observation.get("ok")),
            "state": observation.get("state") if isinstance(observation.get("state"), dict) else None,
            "error": observation.get("error"),
        },
        "latency_ms": int((time.time() - started) * 1000),
        "tested_at": _now(),
    }
    if persist:
        reg = _load_registry()
        devices = reg.setdefault("devices", {})
        current = devices.get(str(device.get("device_id") or ""))
        if isinstance(current, dict):
            if ip and responsive_ports:
                discovered = _device_from_discovery({
                    "ip": ip,
                    "open_ports": responsive_ports,
                    "fingerprint": _classify_open_ports(responsive_ports),
                    "observed_at": result["tested_at"],
                })
                current = _merge_discovered_device(current, discovered)
            meta = current.get("metadata") if isinstance(current.get("metadata"), dict) else {}
            meta["last_access_test"] = {
                "ok": ok,
                "status": status,
                "tested_at": result["tested_at"],
                "responsive_ports": responsive_ports,
                "latency_ms": result["latency_ms"],
                "type": inferred_type,
                "event_count": len(events),
            }
            meta["events"] = events
            current["metadata"] = meta
            if responsive_ports:
                cfg = current.get("config") if isinstance(current.get("config"), dict) else {}
                cfg["last_access_ports"] = responsive_ports
                cfg["web_urls"] = _web_urls(ip, responsive_ports)
                cfg["rtsp_url_candidates"] = _rtsp_url_candidates(ip, responsive_ports, cfg)
                current["config"] = cfg
            current["updated_at"] = _now()
            devices[str(current.get("device_id"))] = _normalize_device(current)
            _save_registry(reg)
    return result


def camera_stream_info_for_device(device: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(device, dict):
        return {"ok": False, "error": "device_not_registered"}
    config = device.get("config") if isinstance(device.get("config"), dict) else {}
    ip = str(config.get("ip") or "").strip()
    ports = _device_ports(config)
    adapter = str(device.get("adapter") or "")
    entity_id = str(config.get("entity_id") or "")
    domain = str(config.get("domain") or (entity_id.split(".", 1)[0] if entity_id else ""))
    if adapter == "home_assistant" and domain == "camera":
        urls = [_ha_state_url(config, entity_id, stream=True)] if _ha_base_url(config) and entity_id else []
        protocol = "home_assistant"
    else:
        urls = _rtsp_url_candidates(ip, ports, config)
        protocol = "rtsp" if urls else ""
    decoder = camera_decoder_status(protocol=protocol)
    viewer_endpoint = f"/api/local-env/devices/{device.get('device_id')}/camera/view"
    return {
        "ok": bool(urls),
        "device_id": device.get("device_id"),
        "name": device.get("name"),
        "type": device.get("type"),
        "real_time": bool(urls),
        "protocol": protocol,
        "url_candidates": urls,
        "preferred_url": urls[0] if urls else "",
        "mjpeg_proxy_endpoint": f"/api/local-env/devices/{device.get('device_id')}/camera/mjpeg",
        "viewer_endpoint": viewer_endpoint,
        "viewer_url": _local_api_path(viewer_endpoint),
        "snapshot_supported": bool(config.get("snapshot_url")),
        "needs_credentials_or_path": bool(urls) and not bool(config.get("stream_url")),
        "decoder_available": bool(decoder.get("can_proxy")),
        "decoder": decoder,
    }


def camera_stream_info(device_id: str) -> dict[str, Any]:
    device = get_device(device_id)
    if not device:
        return {"ok": False, "device_id": str(device_id or ""), "error": "device_not_registered"}
    return camera_stream_info_for_device(device)


def _opencv_available() -> bool:
    try:
        __import__("cv2")
        return True
    except Exception:
        return False


def _ffmpeg_path() -> str:
    configured = str(os.getenv("ULTRON_FFMPEG_PATH") or "").strip()
    if configured and Path(configured).exists():
        return configured
    return shutil.which("ffmpeg") or ""


def _vlc_path() -> str:
    configured = str(os.getenv("ULTRON_VLC_PATH") or "").strip()
    if configured and Path(configured).exists():
        return configured
    found = shutil.which("vlc")
    if found:
        return found
    candidates = [
        Path(os.getenv("ProgramFiles", r"C:\Program Files")) / "VideoLAN" / "VLC" / "vlc.exe",
        Path(os.getenv("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "VideoLAN" / "VLC" / "vlc.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return ""


def camera_decoder_status(*, protocol: str = "") -> dict[str, Any]:
    cv2_ok = _opencv_available()
    ffmpeg = _ffmpeg_path()
    vlc = _vlc_path()
    proto = str(protocol or "").strip()
    direct_proxy = proto == "home_assistant"
    opencv_rtsp_proxy_enabled = os.getenv("ULTRON_ALLOW_OPENCV_RTSP_PROXY", "").strip().lower() in {"1", "true", "yes", "on"}
    opencv_can_proxy = bool(cv2_ok and (proto != "rtsp" or opencv_rtsp_proxy_enabled))
    can_proxy = bool(direct_proxy or ffmpeg or opencv_can_proxy)
    return {
        "ok": bool(cv2_ok or ffmpeg or vlc or direct_proxy),
        "protocol": proto,
        "opencv": cv2_ok,
        "ffmpeg_path": ffmpeg,
        "vlc_path": vlc,
        "can_proxy": can_proxy,
        "can_open_external": bool(vlc),
        "preferred": "home_assistant"
        if direct_proxy
        else ("ffmpeg" if ffmpeg else ("opencv" if opencv_can_proxy else ("vlc" if vlc else ""))),
    }


def open_camera_external(device_id: str) -> dict[str, Any]:
    info = camera_stream_info(device_id)
    if not info.get("ok"):
        return {"ok": False, "error": info.get("error") or "camera_stream_not_available", "stream_info": info}
    url = str(info.get("preferred_url") or "").strip()
    if not url:
        return {"ok": False, "error": "stream_url_not_available", "stream_info": info}
    vlc = _vlc_path()
    if vlc:
        try:
            subprocess.Popen([vlc, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return {"ok": True, "player": "vlc", "player_path": vlc, "url": url, "stream_info": info}
        except Exception as exc:
            return {"ok": False, "player": "vlc", "error": f"{type(exc).__name__}:{str(exc)[:200]}", "stream_info": info}
    opened = _maybe_open_local_url(url)
    return {"ok": bool(opened), "player": "system_browser", "url": url, "stream_info": info, "error": "" if opened else "external_player_not_available"}


def list_cameras(include_disabled: bool = True) -> dict[str, Any]:
    devices = [d for d in list_devices(include_disabled=include_disabled).get("devices", []) if isinstance(d, dict)]
    cameras = []
    for device in devices:
        caps = set(device.get("capabilities") or [])
        dtype = str(device.get("type") or "")
        if "view_stream" in caps or "camera" in dtype or "rtsp" in dtype:
            row = dict(device)
            row["events"] = device_events(device)
            row["stream"] = camera_stream_info_for_device(device)
            cameras.append(row)
    return {"ok": True, "kind": "camera_list", "count": len(cameras), "devices": cameras}


def event_matrix(include_disabled: bool = True) -> dict[str, Any]:
    devices = [d for d in list_devices(include_disabled=include_disabled).get("devices", []) if isinstance(d, dict)]
    rows = []
    for device in devices:
        rows.append({
            "device_id": device.get("device_id"),
            "name": device.get("name"),
            "type": device.get("type"),
            "allowed": bool(device.get("allowed")),
            "adapter": device.get("adapter"),
            "events": device_events(device),
        })
    return {"ok": True, "kind": "event_matrix", "count": len(rows), "devices": rows}


def run_access_battery(
    *,
    timeout_ms: int = 800,
    include_disabled: bool = True,
    grant_control: bool = False,
) -> dict[str, Any]:
    devices = [d for d in list_devices(include_disabled=include_disabled).get("devices", []) if isinstance(d, dict)]
    results = [test_device_access(str(d.get("device_id") or ""), timeout_ms=timeout_ms, persist=True) for d in devices]
    responsive = [r for r in results if bool(r.get("ok"))]
    grant = None
    if grant_control:
        grant = grant_full_control(
            include_unreachable=False,
            reason="access_battery_responsive_devices_full_control",
        )
    row = {
        "ts": _now(),
        "ledger_id": f"lea_access_{_hash([timeout_ms, include_disabled, grant_control, results])}",
        "device_id": "local_environment",
        "action": "access_battery",
        "requested_by": "ultronpro",
        "reason": "test_registered_device_access",
        "risk_level": 0,
        "approved": True,
        "ok": True,
        "result": "success",
        "device_count": len(results),
        "responsive_count": len(responsive),
        "grant_control": bool(grant_control),
        "control_grant": grant,
    }
    _append_jsonl(ACTION_LEDGER_PATH, row)
    return {
        "ok": True,
        "kind": "access_battery",
        "device_count": len(results),
        "responsive_count": len(responsive),
        "unresponsive_count": len(results) - len(responsive),
        "results": results,
        "control_grant": grant,
        "ledger": row,
        "registry_path": str(REGISTRY_PATH),
    }


def parse_command(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    folded = _fold(raw)
    if not folded:
        return {"ok": False, "reason": "empty_command"}
    action = ""
    params: dict[str, Any] = {}
    if any(x in folded for x in ("abrir interface", "interface web", "abrir web", "painel web", "pagina do dispositivo")):
        action = "open_web_interface"
    if any(x in folded for x in ("abrir camera", "mostrar camera", "ver camera", "stream camera", "camera ao vivo", "imagem da camera", "imagens da camera", "abrir webcam", "mostrar webcam", "ver webcam", "webcam ao vivo")):
        action = "view_stream"
        params["open_viewer"] = True
    if any(x in folded for x in ("capturar imagem", "snapshot", "tirar foto", "foto da camera")):
        action = "capture_snapshot"
    if any(x in folded for x in ("status", "estado", "observar", "observe", "ler estado")):
        action = "read_state"
    if any(x in folded for x in ("ligar", "acender", "ative", "ativar", "turn on")):
        action = "turn_on"
    if any(x in folded for x in ("desligar", "apagar", "desative", "desativar", "turn off")):
        action = "turn_off"
    if any(x in folded for x in ("play", "reproduzir", "continuar video", "tocar midia")):
        action = "media_play"
    if any(x in folded for x in ("pause", "pausar", "pausa", "parar video")):
        action = "media_pause"
    if any(x in folded for x in ("aumentar volume", "volume mais", "volume up")):
        action = "volume_up"
        m = re.search(r"(?:aumentar volume|volume mais|volume up|volume)\s+(\d{1,3})", folded)
        if m:
            amount = max(1, min(200, int(m.group(1))))
            params["repeat"] = amount
            if amount >= 50:
                params["risk_level"] = 3
            elif amount >= 20:
                params["risk_level"] = 2
    if any(x in folded for x in ("diminuir volume", "baixar volume", "volume menos", "volume down")):
        action = "volume_down"
        m = re.search(r"(?:diminuir volume|baixar volume|volume menos|volume down|volume)\s+(\d{1,3})", folded)
        if m:
            amount = max(1, min(200, int(m.group(1))))
            params["repeat"] = amount
            if amount >= 50:
                params["risk_level"] = 3
            elif amount >= 20:
                params["risk_level"] = 2
    if any(x in folded for x in ("mutar", "mudo", "mute", "silenciar")):
        action = "mute"
    if any(x in folded for x in ("apertar tecla", "pressionar tecla", "send key", "enviar tecla")):
        action = "send_key"
        m = re.search(r"(?:tecla|key)\s+([a-z0-9_:-]{1,40})", folded)
        if m:
            params["key"] = m.group(1)
    if any(x in folded for x in ("abrir app", "launch app", "iniciar app")):
        action = "launch_app"
        m = re.search(r"(?:app|aplicativo)\s+([a-z0-9_:-]{1,40})", folded)
        if m:
            params["app_id"] = m.group(1)
    if any(x in folded for x in ("trocar entrada", "mudar entrada", "set input", "entrada hdmi")):
        action = "set_input"
    if "brilho" in folded or "brightness" in folded:
        action = "set_brightness"
        m = re.search(r"(\d{1,3})\s*%?", folded)
        if m:
            params["brightness"] = max(0, min(100, int(m.group(1))))
    if "temperatura" in folded or re.search(r"\b\d{1,2}\s*graus\b", folded):
        action = "set_temperature"
        m = re.search(r"(\d{1,2})(?:\s*graus)?", folded)
        if m:
            params["temperature"] = float(m.group(1))
    if any(x in folded for x in ("reiniciar servico", "restart service", "reinicie o servico")):
        action = "restart_service"
    elif any(x in folded for x in ("iniciar servico", "start service", "subir servico")):
        action = "start_service"
    elif any(x in folded for x in ("parar servico", "stop service", "derrubar servico")):
        action = "stop_service"
    if any(x in folded for x in ("rodar script", "executar script", "run script")):
        action = "run_script"
    if any(x in folded for x in ("acordar dispositivo", "wake device", "wake on lan")):
        action = "wake_device"
    if any(x in folded for x in ("notificar", "enviar notificacao", "send notification")):
        action = "send_notification"
        params["message"] = raw
    if not action:
        return {"ok": False, "reason": "no_supported_action_detected"}

    found = find_device_for_text(raw, action=action, include_disabled=False)
    if not found.get("ok"):
        out = dict(found)
        out["action"] = action
        return out
    device = found.get("device") if isinstance(found.get("device"), dict) else {}
    return {
        "ok": True,
        "device_id": device.get("device_id"),
        "action": action,
        "params": params,
        "confidence": found.get("confidence") or 0.82,
        "reason": "matched_registered_device_and_capability",
    }


def execute_command(
    text: str,
    *,
    requested_by: str = "user",
    approved: bool = False,
    dry_run: bool = False,
    session_id: str | None = None,
) -> dict[str, Any]:
    parsed = parse_command(text)
    if not parsed.get("ok"):
        return parsed
    out = act_device(
        str(parsed.get("device_id") or ""),
        str(parsed.get("action") or ""),
        params=parsed.get("params") if isinstance(parsed.get("params"), dict) else {},
        reason=text,
        requested_by=requested_by,
        approved=approved,
        dry_run=dry_run,
    )
    if (
        out.get("status") == "confirmation_required"
        or str((out.get("gate") or {}).get("reason") or "") == "confirmation_required"
    ):
        out["pending_action"] = create_pending_action(
            parsed,
            out.get("device") if isinstance(out.get("device"), dict) else get_device(str(parsed.get("device_id") or "")),
            out.get("gate") if isinstance(out.get("gate"), dict) else {},
            text=text,
            requested_by=requested_by,
            session_id=session_id,
        )
    out["parsed_command"] = parsed
    return out


def status() -> dict[str, Any]:
    registry = list_devices(include_disabled=True)
    state = _runtime_state()
    actions = recent_actions(limit=20)
    return {
        "ok": True,
        "registry_path": str(REGISTRY_PATH),
        "state_path": str(RUNTIME_STATE_PATH),
        "ledger_path": str(ACTION_LEDGER_PATH),
        "pending_path": str(PENDING_ACTIONS_PATH),
        "device_count": registry.get("count"),
        "enabled_device_count": len([d for d in registry.get("devices", []) if bool(d.get("allowed"))]),
        "capability_model": capability_model(),
        "devices": registry.get("devices"),
        "runtime_state": state,
        "recent_actions": actions.get("items"),
        "pending_actions": list_pending_actions(include_expired=False).get("items"),
    }


def run_selftest() -> dict[str, Any]:
    old_registry = REGISTRY_PATH
    old_state = RUNTIME_STATE_PATH
    old_ledger = ACTION_LEDGER_PATH
    old_pending = PENDING_ACTIONS_PATH
    with tempfile.TemporaryDirectory(prefix="local-env-") as td:
        base = Path(td)
        globals()["REGISTRY_PATH"] = base / "registry.json"
        globals()["RUNTIME_STATE_PATH"] = base / "state.json"
        globals()["ACTION_LEDGER_PATH"] = base / "ledger.jsonl"
        globals()["PENDING_ACTIONS_PATH"] = base / "pending.json"

        from ultronpro import causal_graph, episodic_memory

        old_graph = causal_graph.GRAPH_PATH
        old_edges = causal_graph.EDGE_LOG_PATH
        old_epi = episodic_memory.EPISODIC_PATH
        causal_graph.GRAPH_PATH = base / "causal_graph.json"
        causal_graph.EDGE_LOG_PATH = base / "causal_edges.jsonl"
        episodic_memory.EPISODIC_PATH = base / "episodes.jsonl"
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", 0))
        server.listen(5)
        server_port = int(server.getsockname()[1])
        stop_server = threading.Event()

        def _serve_once() -> None:
            server.settimeout(0.2)
            while not stop_server.is_set():
                try:
                    conn, _addr = server.accept()
                    conn.close()
                except socket.timeout:
                    continue
                except Exception:
                    break

        thread = threading.Thread(target=_serve_once, daemon=True)
        thread.start()
        try:
            dev = upsert_device({
                "device_id": "lampada_sala_01",
                "name": "Lampada da sala",
                "type": "smart_light",
                "location": "sala",
                "adapter": "mock",
                "capabilities": ["read_state", "turn_on", "turn_off", "set_brightness"],
                "risk_level": 1,
                "requires_confirmation": False,
                "allowed": True,
            })
            before = observe_device("lampada_sala_01")
            act = act_device(
                "lampada_sala_01",
                "turn_on",
                reason="usuario pediu para acender a sala",
                requested_by="selftest",
            )
            parsed = execute_command("acender lampada da sala", requested_by="selftest")
            blocked = act_device("lampada_sala_01", "restart_service", requested_by="selftest")
            critical = upsert_device({
                "device_id": "lampada_critica_01",
                "name": "Lampada critica",
                "type": "smart_light",
                "location": "laboratorio",
                "adapter": "mock",
                "capabilities": ["read_state", "turn_on", "turn_off"],
                "risk_level": 3,
                "requires_confirmation": True,
                "allowed": True,
                "aliases": ["lampada critica"],
            })
            pending = execute_command(
                "acender lampada critica",
                requested_by="selftest",
                session_id="selftest-session",
            )
            confirmed = confirm_pending_action("selftest-session", approved_by="selftest")
            scan = scan_network(
                cidr="127.0.0.1/32",
                ports=[server_port],
                timeout_ms=120,
                max_hosts=1,
                concurrency=1,
                register=True,
            )
            ledger = recent_actions(limit=10)
            return {
                "ok": (
                    bool(dev.get("ok"))
                    and before.get("ok")
                    and act.get("ok")
                    and parsed.get("ok")
                    and not blocked.get("ok")
                    and critical.get("ok")
                    and bool((pending.get("pending_action") or {}).get("pending_id"))
                    and confirmed.get("ok")
                    and scan.get("registered_count") == 1
                    and ledger.get("count", 0) >= 6
                    and ACTION_LEDGER_PATH.exists()
                    and PENDING_ACTIONS_PATH.exists()
                ),
                "device": dev,
                "before": before,
                "act": act,
                "parsed": parsed,
                "blocked": blocked,
                "critical": critical,
                "pending": pending,
                "confirmed": confirmed,
                "scan": scan,
                "ledger": ledger,
            }
        finally:
            stop_server.set()
            try:
                socket.create_connection(("127.0.0.1", server_port), timeout=0.1).close()
            except Exception:
                pass
            try:
                server.close()
            except Exception:
                pass
            globals()["REGISTRY_PATH"] = old_registry
            globals()["RUNTIME_STATE_PATH"] = old_state
            globals()["ACTION_LEDGER_PATH"] = old_ledger
            globals()["PENDING_ACTIONS_PATH"] = old_pending
            causal_graph.GRAPH_PATH = old_graph
            causal_graph.EDGE_LOG_PATH = old_edges
            episodic_memory.EPISODIC_PATH = old_epi
