"""
Secondary skill system routes.
"""
from __future__ import annotations

from fastapi import APIRouter

from ultronpro import skill_executor, skill_loader

router = APIRouter(tags=["Skills2"])


# ==================== SKILL SYSTEM ENDPOINTS ====================

@router.get("/api/skill-memory-bridge/status")
async def skill_memory_bridge_status():
    """Status da ponte de aprendizado de skills."""
    try:
        from ultronpro import skill_memory_bridge
        return skill_memory_bridge.status()
    except Exception as e:
        return {"ok": False, "error": str(e)}

@router.post("/api/skill-memory-bridge/run")
async def skill_memory_bridge_run(dry_run: bool = False, limit: int = 20):
    """Executa a materialização de skills aprendidas."""
    try:
        from ultronpro import skill_memory_bridge
        return skill_memory_bridge.run_bridge(dry_run=dry_run, limit=limit)
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/api/skills2/status")
async def skills2_status():
    """Status do sistema de skills."""
    try:
        loader = skill_loader.get_skill_loader()
        status = loader.get_status()
        return {"ok": True, **status}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/api/skills2/list")
async def skills2_list():
    """Lista todos os skills."""
    try:
        loader = skill_loader.get_skill_loader()
        skills = loader.get_enabled_skills()
        return {"ok": True, "skills": [s.to_dict() for s in skills], "count": len(skills)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/api/skills2/suggest")
async def skills2_suggest(q: str = ""):
    """Sugere skill para uma tarefa."""
    try:
        skill = skill_loader.suggest_skill(q)
        if skill:
            return {
                "ok": True,
                "suggested": skill.name,
                "description": skill.description,
                "risk_level": skill.risk_level,
                "allowed_tools": skill.allowed_tools,
            }
        return {"ok": True, "suggested": None}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/api/skills2/execute")
async def skills2_execute(task: str, skill_name: str = None):
    """Executa um skill."""
    try:
        executor = skill_executor.get_skill_executor()
        result = await executor.execute(task, suggested_skill=skill_name)
        return {
            "ok": result.success,
            "skill_name": result.skill_name,
            "status": result.status.value,
            "output": result.output,
            "execution_time_ms": result.execution_time_ms,
            "checks_passed": result.checks_passed,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/api/skills2/{skill_name}")
async def skills2_get(skill_name: str):
    """Detalhes de um skill."""
    try:
        loader = skill_loader.get_skill_loader()
        skill = loader.get_skill(skill_name)
        if skill:
            return {"ok": True, "skill": skill.to_dict()}
        return {"ok": False, "error": f"Skill {skill_name} not found"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

