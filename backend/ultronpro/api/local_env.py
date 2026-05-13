from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

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


@router.get("/devices/{device_id}/events")
async def local_env_device_events(device_id: str):
    from ultronpro import local_environment

    device = local_environment.get_device(device_id)
    if not device:
        return {"ok": False, "device_id": device_id, "error": "device_not_registered", "events": []}
    return {"ok": True, "device_id": device_id, "type": device.get("type"), "events": local_environment.device_events(device)}


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


@router.get("/events")
async def local_env_events(include_disabled: bool = True):
    from ultronpro import local_environment

    return local_environment.event_matrix(include_disabled=include_disabled)


@router.get("/cameras")
async def local_env_cameras(include_disabled: bool = True):
    from ultronpro import local_environment

    return local_environment.list_cameras(include_disabled=include_disabled)


@router.get("/devices/{device_id}/camera/stream-info")
async def local_env_camera_stream_info(device_id: str):
    from ultronpro import local_environment

    return local_environment.camera_stream_info(device_id)


@router.get("/devices/{device_id}/camera/mjpeg")
async def local_env_camera_mjpeg(device_id: str):
    from ultronpro import local_environment

    info = local_environment.camera_stream_info(device_id)
    if not info.get("ok"):
        raise HTTPException(status_code=404, detail=info.get("error") or "camera_stream_not_available")
    try:
        import cv2  # type: ignore
    except Exception:
        raise HTTPException(
            status_code=501,
            detail="camera_mjpeg_proxy_requires_opencv_python_headless_or_ffmpeg_runtime",
        )
    url = str(info.get("preferred_url") or "")
    cap = cv2.VideoCapture(url)
    if not cap.isOpened():
        cap.release()
        raise HTTPException(status_code=502, detail="camera_stream_open_failed")

    def frames():
        try:
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                ok, encoded = cv2.imencode(".jpg", frame)
                if not ok:
                    continue
                data = encoded.tobytes()
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + data + b"\r\n"
        finally:
            cap.release()

    return StreamingResponse(frames(), media_type="multipart/x-mixed-replace; boundary=frame")


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


@router.post("/access-battery")
async def local_env_access_battery(req: dict | None = None):
    from ultronpro import local_environment

    body = dict(req or {})
    return local_environment.run_access_battery(
        timeout_ms=int(body.get("timeout_ms") or 800),
        include_disabled=bool(body.get("include_disabled", True)),
        grant_control=bool(body.get("grant_control", False)),
    )


@router.post("/grant-control")
async def local_env_grant_control(req: dict | None = None):
    from ultronpro import local_environment

    body = dict(req or {})
    return local_environment.grant_full_control(
        device_id=body.get("device_id"),
        include_unreachable=bool(body.get("include_unreachable", False)),
        reason=str(body.get("reason") or "api_requested_full_control"),
    )


@router.get("/actions")
async def local_env_actions(limit: int = 50):
    from ultronpro import local_environment

    return local_environment.recent_actions(limit=max(1, min(500, int(limit))))


@router.get("/selftest")
async def local_env_selftest():
    from ultronpro import local_environment

    return local_environment.run_selftest()
