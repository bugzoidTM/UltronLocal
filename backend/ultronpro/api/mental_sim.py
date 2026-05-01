from fastapi import APIRouter
from ultronpro.api.schemas import (
    MentalImagineRequest,
    MentalCompareRequest, 
    MentalTestPathsRequest,
    MentalLearnRequest,
    CompetencyFailureRequest
)

router = APIRouter(prefix="/api/mental-sim", tags=["Mental Simulation Engine"])

@router.get("/status")
async def mental_sim_status(limit: int = 20):
    """Status do Motor de Simulação Mental, cenários e competências."""
    from ultronpro import mental_simulation
    return mental_simulation.status(limit)

@router.post("/imagine")
async def mental_sim_imagine(req: MentalImagineRequest):
    """Imaginar consequências de uma ação ANTES de executá-la."""
    from ultronpro import mental_simulation
    result = mental_simulation.imagine(req.action_kind, req.action_text, req.context)
    return result

@router.post("/compare")
async def mental_sim_compare(req: MentalCompareRequest):
    """Comparar hipóteses rivais e escolher a melhor."""
    from ultronpro import mental_simulation
    return mental_simulation.compare(req.scenario_name, req.hypotheses)

@router.post("/test-paths")
async def mental_sim_test_paths(req: MentalTestPathsRequest):
    """Testar mentalmente caminhos alternativos para um objetivo."""
    from ultronpro import mental_simulation
    return mental_simulation.test_paths(req.objective, req.paths)

@router.post("/learn")
async def mental_sim_learn(req: MentalLearnRequest):
    """Registrar resultado real e extrair lições + competências."""
    from ultronpro import mental_simulation
    return mental_simulation.learn(req.scenario_id, req.actual_outcome)

@router.get("/competencies")
async def mental_sim_competencies():
    """Biblioteca de competências reutilizáveis extraídas de experiência."""
    from ultronpro import mental_simulation
    return {"competencies": mental_simulation.competencies()}

@router.post("/competency-failure")
async def mental_sim_competency_failure(req: CompetencyFailureRequest):
    """Registrar falha ao usar uma competência."""
    from ultronpro import mental_simulation
    return mental_simulation.record_failure(req.competency_id)
