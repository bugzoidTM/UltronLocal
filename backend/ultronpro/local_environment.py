from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import platform
import re
import socket
import subprocess
import tempfile
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import httpx


DATA_DIR = Path(__file__).resolve().parent.parent / "data"
REGISTRY_PATH = DATA_DIR / "local_device_registry.json"
RUNTIME_STATE_PATH = DATA_DIR / "local_environment_state.json"
ACTION_LEDGER_PATH = DATA_DIR / "local_environment_action_ledger.jsonl"

CAPABILITY_RISK: dict[str, int] = {
    "read_state": 0,
    "turn_on": 1,
    "turn_off": 1,
    "set_brightness": 1,
    "send_notification": 1,
    "wake_device": 2,
    "set_temperature": 2,
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
    8000,
    8080,
    8123,
    32400,
    9100,
    22,
]


def _now() -> int:
    return int(time.time())


def _safe(value: Any, limit: int = 500) -> str:
    return " ".join(str(value or "").strip().split())[:limit]


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
    if 9100 in ports:
        return {"type": "printer", "adapter_hint": "network_probe", "name_hint": "Network printer"}
    if 554 in ports:
        return {"type": "camera_or_rtsp_device", "adapter_hint": "network_probe", "name_hint": "RTSP device"}
    if 1883 in ports:
        return {"type": "mqtt_broker", "adapter_hint": "network_probe", "name_hint": "MQTT broker"}
    if 32400 in ports:
        return {"type": "media_server", "adapter_hint": "network_probe", "name_hint": "Media server"}
    if ports & {80, 443, 8080, 8000, 5000, 5001, 5357}:
        return {"type": "http_device", "adapter_hint": "network_probe", "name_hint": "HTTP device"}
    if 22 in ports:
        return {"type": "ssh_host", "adapter_hint": "network_probe", "name_hint": "SSH host"}
    return {"type": "network_device", "adapter_hint": "network_probe", "name_hint": "Network device"}


def _device_from_discovery(hit: dict[str, Any]) -> dict[str, Any]:
    ip = str(hit.get("ip") or "").strip()
    fp = hit.get("fingerprint") if isinstance(hit.get("fingerprint"), dict) else {}
    device_id = f"net_{ip.replace('.', '_').replace(':', '_')}"
    open_ports = [int(p) for p in (hit.get("open_ports") or [])]
    return {
        "device_id": device_id,
        "name": f"{fp.get('name_hint') or 'Network device'} {ip}",
        "type": str(fp.get("type") or "network_device"),
        "location": "rede_local",
        "adapter": "network_probe",
        "capabilities": ["read_state"],
        "risk_level": 0,
        "requires_confirmation": False,
        "allowed": False,
        "aliases": [ip, str(fp.get("name_hint") or ""), str(fp.get("type") or "")],
        "config": {"ip": ip, "open_ports": open_ports, "discovered_by": "tcp_port_probe"},
        "metadata": {"discovered": True, "fingerprint": fp, "observed_at": hit.get("observed_at")},
    }


def _merge_discovered_device(existing: dict[str, Any] | None, discovered: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(existing, dict):
        return _normalize_device(discovered)
    merged = dict(existing)
    merged["name"] = existing.get("name") or discovered.get("name")
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
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _home_assistant_observe(device: dict[str, Any]) -> dict[str, Any]:
    config = device.get("config") if isinstance(device.get("config"), dict) else {}
    base_url = str(config.get("base_url") or os.getenv("ULTRON_HOME_ASSISTANT_URL") or "").rstrip("/")
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
    base_url = str(config.get("base_url") or os.getenv("ULTRON_HOME_ASSISTANT_URL") or "").rstrip("/")
    entity_id = str(config.get("entity_id") or "").strip()
    if not base_url or not entity_id:
        return {"ok": False, "error": "home_assistant_missing_base_url_or_entity_id"}
    domain = str(config.get("domain") or entity_id.split(".", 1)[0] or "homeassistant")
    service = {
        "turn_on": "turn_on",
        "turn_off": "turn_off",
        "set_brightness": "turn_on",
        "set_temperature": "set_temperature",
    }.get(action)
    if not service:
        return {"ok": False, "error": f"unsupported_home_assistant_action:{action}"}
    payload: dict[str, Any] = {"entity_id": entity_id}
    if action == "set_brightness":
        payload["brightness_pct"] = max(0, min(100, int(params.get("brightness") or params.get("value") or 0)))
    if action == "set_temperature":
        payload["temperature"] = float(params.get("temperature") or params.get("value") or 22)
    with httpx.Client(timeout=float(config.get("timeout_sec") or 8.0)) as client:
        resp = client.post(f"{base_url}/api/services/{domain}/{service}", headers=_ha_headers(config), json=payload)
        resp.raise_for_status()
        try:
            raw = resp.json()
        except Exception:
            raw = {"status_code": resp.status_code}
    return {"ok": True, "adapter": "home_assistant", "action": action, "service": f"{domain}.{service}", "raw": raw}


def _http_request(config: dict[str, Any], action: str) -> dict[str, Any]:
    endpoints = config.get("endpoints") if isinstance(config.get("endpoints"), dict) else {}
    spec = endpoints.get(action)
    if not isinstance(spec, dict):
        return {"ok": False, "error": f"http_endpoint_not_configured:{action}"}
    url = str(spec.get("url") or "").strip()
    if not url:
        return {"ok": False, "error": "http_url_required"}
    method = str(spec.get("method") or "GET").upper()
    headers = spec.get("headers") if isinstance(spec.get("headers"), dict) else {}
    payload = spec.get("json") if isinstance(spec.get("json"), dict) else None
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
    res = _http_request(config, action)
    if not res.get("ok"):
        return res
    return {"ok": True, "adapter": "http", "action": action, "response": res}


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


def _network_probe_observe(device: dict[str, Any]) -> dict[str, Any]:
    config = device.get("config") if isinstance(device.get("config"), dict) else {}
    ip = str(config.get("ip") or "").strip()
    if not ip:
        return {"ok": False, "error": "network_probe_missing_ip"}
    ports = _normalize_ports([int(p) for p in (config.get("open_ports") or config.get("last_discovered_ports") or DEFAULT_DISCOVERY_PORTS)])
    timeout_sec = max(0.05, min(2.0, float(config.get("timeout_ms") or 220) / 1000.0))
    open_ports = [port for port in ports if _tcp_port_open(ip, port, timeout_sec)]
    state = {
        "state": "reachable" if open_ports else "unreachable",
        "ip": ip,
        "open_ports": open_ports,
        "fingerprint": _classify_open_ports(open_ports) if open_ports else {},
    }
    return _typed_observation(device, state, adapter="network_probe")


def observe_device(device_id: str) -> dict[str, Any]:
    device = get_device(device_id)
    if not device:
        return {"ok": False, "error": "device_not_registered", "device_id": str(device_id or "")}
    if "read_state" not in set(device.get("capabilities") or []):
        return {"ok": False, "error": "read_state_not_allowed", "device_id": device.get("device_id")}
    adapter = str(device.get("adapter") or "mock")
    try:
        if adapter == "mock":
            return _mock_observe(device)
        if adapter == "home_assistant":
            return _home_assistant_observe(device)
        if adapter == "http":
            return _http_observe(device)
        if adapter == "local_service":
            return _service_observe(device)
        if adapter == "network_probe":
            return _network_probe_observe(device)
        if adapter in {"local_script", "wake_on_lan", "notification"}:
            return _typed_observation(device, _state_for(str(device.get("device_id"))), adapter=adapter)
        return {"ok": False, "error": f"unsupported_adapter:{adapter}", "device_id": device.get("device_id")}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}:{str(exc)[:240]}", "device_id": device.get("device_id")}


def _execute_adapter(device: dict[str, Any], action: str, params: dict[str, Any]) -> dict[str, Any]:
    adapter = str(device.get("adapter") or "mock")
    if action == "read_state":
        return observe_device(str(device.get("device_id")))
    try:
        if adapter == "mock":
            return _mock_execute(device, action, params)
        if adapter == "home_assistant":
            return _home_assistant_execute(device, action, params)
        if adapter == "http":
            return _http_execute(device, action, params)
        if adapter == "local_service":
            return _service_execute(device, action, params)
        if adapter == "local_script":
            return _script_execute(device, action, params)
        if adapter == "wake_on_lan":
            return _wol_execute(device, action, params)
        if adapter == "notification":
            return _notification_execute(device, action, params)
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


def parse_command(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    folded = _fold(raw)
    if not folded:
        return {"ok": False, "reason": "empty_command"}
    action = ""
    params: dict[str, Any] = {}
    if any(x in folded for x in ("status", "estado", "observar", "observe", "ler estado")):
        action = "read_state"
    if any(x in folded for x in ("ligar", "acender", "ative", "ativar", "turn on")):
        action = "turn_on"
    if any(x in folded for x in ("desligar", "apagar", "desative", "desativar", "turn off")):
        action = "turn_off"
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

    devices = [d for d in list_devices(include_disabled=False).get("devices", []) if action in set(d.get("capabilities") or [])]
    scored: list[tuple[int, dict[str, Any]]] = []
    for device in devices:
        terms = {
            _fold(device.get("device_id")),
            _fold(device.get("name")),
            _fold(device.get("type")),
            _fold(device.get("location")),
        }
        terms.update(_fold(x) for x in (device.get("aliases") or []))
        terms = {t for t in terms if t}
        score = 0
        for term in terms:
            if term and term in folded:
                score += max(1, min(8, len(term.split()) + 2))
        if score:
            scored.append((score, device))
    if not scored:
        return {"ok": False, "reason": "no_registered_device_matched", "action": action}
    scored.sort(key=lambda item: item[0], reverse=True)
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        return {
            "ok": False,
            "reason": "ambiguous_device",
            "action": action,
            "candidates": [d.get("device_id") for _, d in scored[:5]],
        }
    device = scored[0][1]
    return {
        "ok": True,
        "device_id": device.get("device_id"),
        "action": action,
        "params": params,
        "confidence": round(min(0.99, 0.55 + scored[0][0] / 20.0), 4),
        "reason": "matched_registered_device_and_capability",
    }


def execute_command(
    text: str,
    *,
    requested_by: str = "user",
    approved: bool = False,
    dry_run: bool = False,
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
        "device_count": registry.get("count"),
        "enabled_device_count": len([d for d in registry.get("devices", []) if bool(d.get("allowed"))]),
        "capability_model": capability_model(),
        "devices": registry.get("devices"),
        "runtime_state": state,
        "recent_actions": actions.get("items"),
    }


def run_selftest() -> dict[str, Any]:
    old_registry = REGISTRY_PATH
    old_state = RUNTIME_STATE_PATH
    old_ledger = ACTION_LEDGER_PATH
    with tempfile.TemporaryDirectory(prefix="local-env-") as td:
        base = Path(td)
        globals()["REGISTRY_PATH"] = base / "registry.json"
        globals()["RUNTIME_STATE_PATH"] = base / "state.json"
        globals()["ACTION_LEDGER_PATH"] = base / "ledger.jsonl"

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
                    and scan.get("registered_count") == 1
                    and ledger.get("count", 0) >= 4
                    and ACTION_LEDGER_PATH.exists()
                ),
                "device": dev,
                "before": before,
                "act": act,
                "parsed": parsed,
                "blocked": blocked,
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
            causal_graph.GRAPH_PATH = old_graph
            causal_graph.EDGE_LOG_PATH = old_edges
            episodic_memory.EPISODIC_PATH = old_epi
