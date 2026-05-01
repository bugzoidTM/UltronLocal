import logging
import json
import time
from typing import Dict, Any, Optional
from ultronpro import planner, symbolic_router

logger = logging.getLogger("uvicorn")

class LocalAutonomousLoop:
    """
    Motor de raciocínio local estrutural (Fase 7). 
    Regra de ouro: roteamento puro sem LLM.
    """

    @classmethod
    async def plan(cls, objective: str, context: Optional[Dict[str, Any]] = None, goal_id: Optional[str] = None) -> planner.ExecutionPlan:
        t0 = time.time()
        logger.info(f"LocalAutonomousLoop starting structural planning for: {objective[:100]}...")
        
        # 1. Decomposition (Deterministic via planner)
        plan = await planner.generate_structured_plan(objective, goal_id=goal_id)
        
        # 2. Symbolic Routing (System as Decision Maker)
        routed_plan = symbolic_router.route_plan(plan)
        
        dt = int((time.time() - t0) * 1000)
        logger.info(f"Reasoning Engine finalized plan {routed_plan.id} | ms={dt}")
        
        return routed_plan

    @classmethod
    async def evaluate(cls, objective: str, result: str) -> Dict[str, Any]:
        """
        Avalia se o resultado da execução foi satisfatório deterministicamente.
        """
        t0 = time.time()
        res_str = str(result or '').lower()
        
        status = "OK"
        feedback = "structural_pass"
        
        if "error" in res_str or "traceback" in res_str or "exception" in res_str or "failed" in res_str:
            status = "ESCALATE"
            feedback = "deterministic_error_detected"
        elif not result or len(result.strip()) < 5:
            status = "REPEAT"
            feedback = "too_short_or_empty"
            
        dt = int((time.time() - t0) * 1000)
        logger.info(f"LocalEvaluator status={status} ms={dt}")
        return {"status": status, "feedback": feedback}
