from fastapi import APIRouter
from ultronpro.api.schemas import HealAnalyzeRequest, HealApplyRequest

router = APIRouter(prefix="/api/self-healer", tags=["Self Healer"])

@router.get("/status")
async def self_healer_status():
    """Status do Code Self-Healer."""
    from ultronpro import code_self_healer
    return code_self_healer.status()

@router.post("/analyze")
async def self_healer_analyze(req: HealAnalyzeRequest):
    """Analisar erro e gerar fix."""
    from ultronpro import code_self_healer
    result = code_self_healer.analyze(req.error_id)
    if result is None:
        return {"ok": False, "error": "no_fix_generated"}
    return result

@router.post("/apply")
async def self_healer_apply(req: HealApplyRequest):
    """Aplicar fix gerado."""
    from ultronpro import code_self_healer
    return code_self_healer.apply(req.attempt_id)

@router.post("/verify")
async def self_healer_verify(req: HealApplyRequest):
    """Verificar se fix está funcionando."""
    from ultronpro import code_self_healer
    return code_self_healer.verify(req.attempt_id)

@router.post("/autorun")
async def self_healer_autorun(limit: int = 3):
    """Analisar e aplicar fixes pendentes com gates sandbox/testes."""
    from ultronpro import code_self_healer
    return code_self_healer.autorun_pending(limit=limit)

@router.post("/rollback")
async def self_healer_rollback(req: HealApplyRequest):
    """Rollback de um fix."""
    from ultronpro import code_self_healer
    return code_self_healer.rollback(req.attempt_id)
