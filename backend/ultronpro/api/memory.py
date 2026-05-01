"""
Operational memory routes and startup hook.
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter

from ultronpro import operational_memory

logger = logging.getLogger("uvicorn")
router = APIRouter(tags=["Operational Memory"])


def _project_path() -> str:
    return str(Path(__file__).resolve().parents[2])


# ==================== OPERATIONAL MEMORY ENDPOINTS ====================

@router.on_event("startup")
async def startup_operational_memory():
    """Inicializa memÃ³ria operacional na startup."""
    try:
        op_mem = operational_memory.get_operational_memory(project_path=_project_path())
        result = op_mem.session_start()
        logger.info(f"Operational Memory initialized: session={result.get('session_id')}")
    except Exception as e:
        logger.warning(f"Failed to init operational memory: {e}")


@router.get("/api/memory/status")
async def memory_status():
    """Status da memÃ³ria operacional."""
    try:
        op_mem = operational_memory.get_operational_memory(project_path=_project_path())
        return op_mem.get_stats()
    except Exception as e:
        return {"error": str(e)}


@router.get("/api/memory/human")
async def memory_human_read(scope: str = "global"):
    """LÃª memÃ³ria humana."""
    try:
        op_mem = operational_memory.get_operational_memory(project_path=_project_path())
        scope_enum = operational_memory.MemoryScope(scope)
        content = op_mem.read_human_memory(scope=scope_enum)
        return {"ok": True, "scope": scope, "content": content}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/api/memory/human")
async def memory_human_write(content: str, scope: str = "global", append: bool = False):
    """Escreve memÃ³ria humana."""
    try:
        op_mem = operational_memory.get_operational_memory(project_path=_project_path())
        scope_enum = operational_memory.MemoryScope(scope)
        success = op_mem.write_human_memory(content, scope=scope_enum, append=append)
        return {"ok": success}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/api/memory/learned")
async def memory_learned_read(scope: str = "global"):
    """LÃª memÃ³ria de aprendizados."""
    try:
        op_mem = operational_memory.get_operational_memory(project_path=_project_path())
        scope_enum = operational_memory.MemoryScope(scope)
        content = op_mem.read_learned_memory(scope=scope_enum)
        return {"ok": True, "scope": scope, "content": content}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/api/memory/learn")
async def memory_learn(content: str, category: str = "general", scope: str = "project"):
    """Registra aprendizado."""
    try:
        op_mem = operational_memory.get_operational_memory(project_path=_project_path())
        scope_enum = operational_memory.MemoryScope(scope)
        success = op_mem.learn(content, category=category, scope=scope_enum)
        return {"ok": success}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/api/memory/query")
async def memory_query(q: str, limit: int = 10):
    """Busca na memÃ³ria."""
    try:
        op_mem = operational_memory.get_operational_memory(project_path=_project_path())
        results = op_mem.query(q, limit=limit)
        return {"ok": True, "results": results, "count": len(results)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/api/memory/context")
async def memory_context(max_chars: int = 8000):
    """ConstrÃ³i contexto de sessÃ£o."""
    try:
        op_mem = operational_memory.get_operational_memory(project_path=_project_path())
        context = op_mem.build_session_context(max_chars=max_chars)
        return {"ok": True, "context": context, "chars": len(context)}
    except Exception as e:
        return {"ok": False, "error": str(e)}

