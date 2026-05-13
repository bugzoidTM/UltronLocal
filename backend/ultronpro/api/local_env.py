from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api/local-env", tags=["Local Environment"])


@router.get("/status")
async def local_env_status():
    from ultronpro import local_environment

    return local_environment.status()


@router.get("/devices")
async def local_env_devices(include_disabled: bool = True):
    from ultronpro import local_environment

    return local_environment.list_devices(include_disabled=include_disabled)


@router.post("/devices")
async def local_env_upsert_device(req: dict):
    from ultronpro import local_environment

    return local_environment.upsert_device(req or {})


@router.delete("/devices/{device_id}")
async def local_env_remove_device(device_id: str):
    from ultronpro import local_environment

    return local_environment.remove_device(device_id)


@router.get("/devices/{device_id}/observe")
async def local_env_observe_device(device_id: str):
    from ultronpro import local_environment

    return local_environment.observe_device(device_id)


@router.post("/devices/{device_id}/act")
async def local_env_act_device(device_id: str, req: dict | None = None):
    from ultronpro import local_environment

    body = dict(req or {})
    return local_environment.act_device(
        device_id,
        str(body.get("action") or ""),
        params=body.get("params") if isinstance(body.get("params"), dict) else {},
        reason=str(body.get("reason") or ""),
        requested_by=str(body.get("requested_by") or "api"),
        approved=bool(body.get("approved")),
        dry_run=bool(body.get("dry_run")),
    )


@router.post("/command")
async def local_env_command(req: dict):
    from ultronpro import local_environment

    body = dict(req or {})
    return local_environment.execute_command(
        str(body.get("text") or body.get("command") or ""),
        requested_by=str(body.get("requested_by") or "api"),
        approved=bool(body.get("approved")),
        dry_run=bool(body.get("dry_run")),
        session_id=str(body.get("session_id") or "api"),
    )


@router.get("/pending")
async def local_env_pending(session_id: str | None = None, include_expired: bool = False):
    from ultronpro import local_environment

    return local_environment.list_pending_actions(session_id=session_id, include_expired=include_expired)


@router.post("/pending/{pending_id}/confirm")
async def local_env_confirm_pending(pending_id: str, req: dict | None = None):
    from ultronpro import local_environment

    body = dict(req or {})
    return local_environment.confirm_pending_action(
        session_id=str(body.get("session_id") or "api"),
        pending_id=pending_id,
        approved_by=str(body.get("approved_by") or body.get("requested_by") or "api"),
    )


@router.post("/pending/{pending_id}/cancel")
async def local_env_cancel_pending(pending_id: str, req: dict | None = None):
    from ultronpro import local_environment

    body = dict(req or {})
    return local_environment.cancel_pending_action(
        session_id=str(body.get("session_id") or "api"),
        pending_id=pending_id,
        reason=str(body.get("reason") or "api_cancelled"),
    )


@router.get("/networks")
async def local_env_networks():
    from ultronpro import local_environment

    return local_environment.discover_networks()


@router.post("/scan")
async def local_env_scan(req: dict | None = None):
    from ultronpro import local_environment

    body = dict(req or {})
    ports = body.get("ports") if isinstance(body.get("ports"), list) else None
    return local_environment.scan_network(
        cidr=body.get("cidr"),
        ports=ports,
        timeout_ms=int(body.get("timeout_ms") or 220),
        max_hosts=int(body.get("max_hosts") or 256),
        concurrency=int(body.get("concurrency") or 64),
        register=bool(body.get("register", True)),
    )


@router.get("/actions")
async def local_env_actions(limit: int = 50):
    from ultronpro import local_environment

    return local_environment.recent_actions(limit=max(1, min(500, int(limit))))


@router.get("/selftest")
async def local_env_selftest():
    from ultronpro import local_environment

    return local_environment.run_selftest()
