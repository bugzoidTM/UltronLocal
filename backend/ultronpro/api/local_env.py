from __future__ import annotations

import subprocess

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, Response, StreamingResponse
import httpx

router = APIRouter(prefix="/api/local-env", tags=["Local Environment"])


def _jpeg_frames_from_ffmpeg(stdout):
    buffer = b""
    while True:
        chunk = stdout.read(8192)
        if not chunk:
            break
        buffer += chunk
        while True:
            start = buffer.find(b"\xff\xd8")
            if start < 0:
                buffer = buffer[-2:]
                break
            end = buffer.find(b"\xff\xd9", start + 2)
            if end < 0:
                if start > 0:
                    buffer = buffer[start:]
                break
            frame = buffer[start : end + 2]
            buffer = buffer[end + 2 :]
            yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"


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


@router.post("/devices/{device_id}/rename")
async def local_env_rename_device(device_id: str, req: dict | None = None):
    from ultronpro import local_environment

    body = dict(req or {})
    return local_environment.rename_device(
        device_id,
        str(body.get("name") or body.get("new_name") or ""),
        aliases=body.get("aliases") if isinstance(body.get("aliases"), list) else None,
        source=str(body.get("source") or "api"),
    )


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
def local_env_camera_mjpeg(device_id: str):
    from ultronpro import local_environment

    info = local_environment.camera_stream_info(device_id)
    if not info.get("ok"):
        raise HTTPException(status_code=404, detail=info.get("error") or "camera_stream_not_available")
    if info.get("protocol") == "home_assistant":
        device = local_environment.get_device(device_id) or {}
        config = device.get("config") if isinstance(device.get("config"), dict) else {}
        headers = local_environment._ha_headers(config)  # noqa: SLF001 - local API proxy for HA camera auth
        url = str(info.get("preferred_url") or "")

        def ha_frames():
            with httpx.Client(timeout=None) as client:
                with client.stream("GET", url, headers=headers) as resp:
                    resp.raise_for_status()
                    for chunk in resp.iter_bytes():
                        if chunk:
                            yield chunk

        return StreamingResponse(ha_frames(), media_type="multipart/x-mixed-replace; boundary=frame")
    url = str(info.get("preferred_url") or "")
    decoder = info.get("decoder") if isinstance(info.get("decoder"), dict) else {}
    if not decoder.get("can_proxy"):
        raise HTTPException(
            status_code=424,
            detail="camera_rtsp_decoder_unavailable: configure Home Assistant camera entity, install/point ULTRON_FFMPEG_PATH to ffmpeg, or use VLC external player",
        )
    ffmpeg = local_environment._ffmpeg_path()  # noqa: SLF001
    if ffmpeg:

        def ffmpeg_frames():
            proc = subprocess.Popen(
                [
                    ffmpeg,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-rtsp_transport",
                    "tcp",
                    "-i",
                    url,
                    "-an",
                    "-vf",
                    "fps=8",
                    "-f",
                    "mjpeg",
                    "pipe:1",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            try:
                if proc.stdout is not None:
                    yield from _jpeg_frames_from_ffmpeg(proc.stdout)
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except Exception:
                    proc.kill()

        return StreamingResponse(ffmpeg_frames(), media_type="multipart/x-mixed-replace; boundary=frame")
    try:
        import cv2  # type: ignore
    except Exception:
        raise HTTPException(
            status_code=424,
            detail="camera_rtsp_decoder_unavailable: configure Home Assistant camera entity, install/point ULTRON_FFMPEG_PATH to ffmpeg, or use VLC external player",
        )
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


@router.get("/devices/{device_id}/camera/snapshot")
def local_env_camera_snapshot(device_id: str):
    from ultronpro import local_environment

    device = local_environment.get_device(device_id)
    if not device:
        raise HTTPException(status_code=404, detail="device_not_registered")
    config = device.get("config") if isinstance(device.get("config"), dict) else {}
    if str(device.get("adapter") or "") == "home_assistant" and str(config.get("domain") or "") == "camera":
        url = local_environment._ha_state_url(config, str(config.get("entity_id") or ""), stream=False)  # noqa: SLF001
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(url, headers=local_environment._ha_headers(config))  # noqa: SLF001
            resp.raise_for_status()
        return Response(content=resp.content, media_type=resp.headers.get("content-type") or "image/jpeg")
    info = local_environment.camera_stream_info(device_id)
    if not info.get("ok"):
        raise HTTPException(status_code=404, detail=info.get("error") or "camera_stream_not_available")
    decoder = info.get("decoder") if isinstance(info.get("decoder"), dict) else {}
    ffmpeg = local_environment._ffmpeg_path()  # noqa: SLF001
    if ffmpeg:
        proc = subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-rtsp_transport",
                "tcp",
                "-i",
                str(info.get("preferred_url") or ""),
                "-frames:v",
                "1",
                "-f",
                "image2",
                "-vcodec",
                "mjpeg",
                "pipe:1",
            ],
            capture_output=True,
            timeout=12,
        )
        if proc.returncode != 0 or not proc.stdout:
            raise HTTPException(status_code=502, detail="camera_snapshot_ffmpeg_failed")
        return Response(content=proc.stdout, media_type="image/jpeg")
    if not decoder.get("can_proxy"):
        raise HTTPException(status_code=424, detail="camera_snapshot_decoder_unavailable")
    try:
        import cv2  # type: ignore
    except Exception:
        raise HTTPException(status_code=424, detail="camera_snapshot_decoder_unavailable")
    cap = cv2.VideoCapture(str(info.get("preferred_url") or ""))
    try:
        if not cap.isOpened():
            raise HTTPException(status_code=502, detail="camera_stream_open_failed")
        ok, frame = cap.read()
        if not ok:
            raise HTTPException(status_code=502, detail="camera_frame_read_failed")
        ok, encoded = cv2.imencode(".jpg", frame)
        if not ok:
            raise HTTPException(status_code=500, detail="camera_frame_encode_failed")
        return Response(content=encoded.tobytes(), media_type="image/jpeg")
    finally:
        cap.release()


@router.get("/devices/{device_id}/camera/view")
def local_env_camera_view(device_id: str):
    from ultronpro import local_environment

    info = local_environment.camera_stream_info(device_id)
    if not info.get("ok"):
        raise HTTPException(status_code=404, detail=info.get("error") or "camera_stream_not_available")
    name = str(info.get("name") or device_id)
    mjpeg = str(info.get("mjpeg_proxy_endpoint") or f"/api/local-env/devices/{device_id}/camera/mjpeg")
    snapshot = f"/api/local-env/devices/{device_id}/camera/snapshot"
    decoder = info.get("decoder") if isinstance(info.get("decoder"), dict) else {}
    can_proxy = bool(decoder.get("can_proxy"))
    can_external = bool(decoder.get("can_open_external"))
    if can_proxy:
        body = f'<main><img src="{mjpeg}" alt="{name}" /></main>'
        script = ""
    elif can_external:
        body = (
            "<main><section>"
            "<h1>Stream RTSP aberto no player externo</h1>"
            "<p>Este ambiente nao tem decoder MJPEG no Python, entao abri a camera no VLC instalado nesta maquina.</p>"
            f'<p><button onclick="fetch(\'/api/local-env/devices/{device_id}/camera/open-external\', {{method:\'POST\'}})">Abrir novamente no VLC</button></p>'
            f'<p><code>{info.get("preferred_url") or ""}</code></p>'
            "</section></main>"
        )
        script = f"<script>fetch('/api/local-env/devices/{device_id}/camera/open-external', {{method:'POST'}}).catch(()=>{{}})</script>"
    else:
        body = (
            "<main><section>"
            "<h1>Decoder de camera indisponivel</h1>"
            "<p>O stream foi encontrado, mas RTSP precisa de um decoder local. Configure uma entidade Camera no Home Assistant, defina ULTRON_FFMPEG_PATH apontando para ffmpeg, ou instale um runtime com OpenCV.</p>"
            f'<p><code>{info.get("preferred_url") or ""}</code></p>'
            "</section></main>"
        )
        script = ""
    html = f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{name}</title>
  <style>
    body {{ margin: 0; background: #05070a; color: #eaf7ff; font-family: Segoe UI, Arial, sans-serif; }}
    header {{ padding: 12px 16px; background: #101722; border-bottom: 1px solid #203247; }}
    main {{ display: grid; place-items: center; min-height: calc(100vh - 52px); }}
    img {{ max-width: 100vw; max-height: calc(100vh - 60px); object-fit: contain; background: #000; }}
    section {{ max-width: 760px; padding: 24px; line-height: 1.5; }}
    button {{ background: #0ea5e9; border: 0; color: #001018; padding: 10px 14px; cursor: pointer; }}
    code {{ color: #9ee7ff; overflow-wrap: anywhere; }}
    a {{ color: #7bdcff; margin-left: 12px; }}
  </style>
</head>
<body>
  <header>{name}<a href="{snapshot}" target="_blank">snapshot</a></header>
  {body}
  {script}
</body>
</html>"""
    return HTMLResponse(html)


@router.post("/devices/{device_id}/camera/open-external")
def local_env_camera_open_external(device_id: str):
    from ultronpro import local_environment

    return local_environment.open_camera_external(device_id)


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


@router.get("/home-assistant/status")
async def local_env_home_assistant_status():
    from ultronpro import local_environment

    return local_environment.home_assistant_status()


@router.post("/home-assistant/import")
async def local_env_home_assistant_import(req: dict | None = None):
    from ultronpro import local_environment

    body = dict(req or {})
    domains = body.get("domains") if isinstance(body.get("domains"), list) else None
    return local_environment.import_home_assistant_entities(
        include_domains=domains,
        base_url=body.get("base_url"),
        token_env=str(body.get("token_env") or "ULTRON_HOME_ASSISTANT_TOKEN"),
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
