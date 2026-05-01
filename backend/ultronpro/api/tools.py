"""
Tool registry routes.
"""
from __future__ import annotations

from fastapi import APIRouter

from ultronpro import tool_registry, tool_registry_specs

router = APIRouter(tags=["Tools"])


# ==================== TOOL REGISTRY ENDPOINTS ====================

@router.get("/api/tools/status")
async def tools_status():
    """Status do registry de tools."""
    try:
        registry = tool_registry.get_tool_registry()
        return {
            "ok": True,
            "tools_count": len(registry._tools),
            "categories": registry.get_categories(),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/api/tools/list")
async def tools_list(category: str = None):
    """Lista todas as tools."""
    try:
        registry = tool_registry.get_tool_registry()
        if category:
            cat = tool_registry_specs.ToolCategory(category)
            tools = registry.get_by_category(cat)
        else:
            tools = [registry.get(name) for name in registry._tools]
        return {
            "ok": True,
            "tools": [t.to_dict() for t in tools if t],
            "count": len(tools),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/api/tools/suggest")
async def tools_suggest(task: str, safe_only: bool = False):
    """Sugere tools para uma tarefa."""
    try:
        registry = tool_registry.get_tool_registry()
        suggested = registry.suggest(task, safe_only=safe_only)
        return {
            "ok": True,
            "suggested": [t.to_dict() for t in suggested],
            "count": len(suggested),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/api/tools/execute")
async def tools_execute(tool_name: str, args: dict = None):
    """Executa uma tool."""
    try:
        registry = tool_registry.get_tool_registry()
        result = await registry.execute(tool_name, args or {})
        return result
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/api/tools/{tool_name}")
async def tools_get(tool_name: str):
    """Detalhes de uma tool."""
    try:
        registry = tool_registry.get_tool_registry()
        tool = registry.get(tool_name)
        if tool:
            return {"ok": True, "tool": tool.to_dict()}
        return {"ok": False, "error": f"Tool {tool_name} not found"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/api/tools/{tool_name}/stats")
async def tools_stats(tool_name: str):
    """EstatÃ­sticas de uma tool."""
    try:
        registry = tool_registry.get_tool_registry()
        return registry.get_stats(tool_name)
    except Exception as e:
        return {"error": str(e)}


@router.get("/api/tools/{tool_name}/authorize")
async def tools_authorize(tool_name: str, is_admin: bool = False):
    """Verifica autorizaÃ§Ã£o de uma tool."""
    try:
        registry = tool_registry.get_tool_registry()
        auth = registry.check_authorization(tool_name, {"is_admin": is_admin})
        return {
            "ok": True,
            "allowed": auth.allowed,
            "reason": auth.reason,
            "requires_confirmation": auth.requires_confirmation,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}

