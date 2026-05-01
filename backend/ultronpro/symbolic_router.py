from __future__ import annotations
import logging
from typing import Any
from ultronpro import self_model, planner

logger = logging.getLogger("uvicorn")

def route_plan(plan: planner.ExecutionPlan) -> planner.ExecutionPlan:
    """
    Symbolic router that decides the best model for each step of an ExecutionPlan
    based on historical evidence from the self_model.
    """
    logger.info(f"Routing ExecutionPlan {plan.id} with {len(plan.steps)} steps")
    
    for step in plan.steps:
        # 1. Get sufficiency score from self_model
        # We use the step kind (code, research, logic, etc.)
        score = self_model.get_sufficiency_score(step.kind)
        
        # 2. Symbolic Decision Logic
        if score >= 0.75:
            step.assigned_model = "local_gemma"
            reason = f"High local proficiency (score={score})"
        elif score >= 0.45:
            step.assigned_model = "external_specialist"
            reason = f"Moderate proficiency (score={score}), escalating to specialist"
        else:
            step.assigned_model = "external_backbone"
            reason = f"Low local proficiency (score={score}), escalating to backbone model"
            
        step.routing_audit = f"Router decision at {planner.time.ctime()}: {reason}"
        logger.info(f"Step {step.id} ({step.kind}) -> {step.assigned_model} | {reason}")
        
    return plan
