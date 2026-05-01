"""
System and UI support routes.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter

from ultronpro import llm, settings
from ultronpro.api.schemas import SettingsModel, WebExploreRequest

logger = logging.getLogger("uvicorn")
router = APIRouter(tags=["System"])


@router.get("/api/settings")
async def get_settings():
    """Get current settings (masked keys)."""
    s = settings.load_settings()
    masked = {}
    for k, v in s.items():
        if "key" in k and v:
            masked[k] = "..." + v[-4:]  # Show only last 4 chars
        else:
            masked[k] = v
    return {"settings": masked}


@router.post("/api/settings")
async def update_settings(new_settings: SettingsModel):
    """Update settings."""
    current = settings.load_settings()
    to_save = {}

    # Only update provided fields (ignore empty strings if user didn't change)
    data = new_settings.dict(exclude_unset=True)

    for k, v in data.items():
        if v and v != "..." + current.get(k, "")[-4:]:  # Check if it's not the masked value sent back
            to_save[k] = v

    if to_save:
        settings.save_settings(to_save)
        # Invalidate LLM clients cache to force reload with new keys
        llm.router.clients = {}

    return {"status": "updated", "updated_keys": list(to_save.keys())}


@router.get("/api/web/status")
async def get_web_status():
    from ultronpro import web_explorer
    return web_explorer.get_web_explorer().get_status()


@router.get("/api/web/logs")
async def get_web_logs(limit: int = 50):
    log_path = Path(__file__).resolve().parents[2] / "data" / "web_explorer_log.jsonl"
    if not log_path.exists():
        return {"logs": []}

    logs = []
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
            for line in lines[-limit:]:
                logs.append(json.loads(line))
    except Exception as e:
        logger.error(f"Erro ao ler logs web: {e}")

    return {"logs": logs}


@router.post("/api/web/explore")
async def force_web_explore(req: WebExploreRequest):
    """Force Web Explorer to investigate a topic immediately."""
    from ultronpro import web_explorer
    if not req.topic:
        return {"ok": False, "error": "T\u00f3pico vazio"}

    explorer = web_explorer.get_web_explorer()
    explorer.target_topics.append(req.topic)
    explorer._log_event("manual_trigger", f"Explora\u00e7\u00e3o manual iniciada: {req.topic}")

    return {"ok": True, "topic": req.topic, "status": "added_to_queue"}
