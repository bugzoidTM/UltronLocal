from fastapi import APIRouter

router = APIRouter(tags=["Self Talk & Low Power"])

@router.get("/api/self-talk/status")
async def self_talk_status():
    """Status do Self-Talk OODA Loop."""
    from ultronpro import self_talk_loop
    return self_talk_loop.status()

@router.post("/api/self-talk/start")
async def self_talk_start():
    """Inicia o Self-Talk loop se estiver parado."""
    from ultronpro import self_talk_loop
    self_talk_loop.start()
    return {"ok": True, "status": "started"}

@router.post("/api/self-talk/stop")
async def self_talk_stop():
    """Para o Self-Talk loop."""
    from ultronpro import self_talk_loop
    self_talk_loop.stop()
    return {"ok": True, "status": "stopped"}

@router.get("/api/low-power/status")
async def low_power_status():
    """Status operacional do modo degradado/low_power."""
    from ultronpro import low_power
    return low_power.status()
