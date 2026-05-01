"""
Phenomenal consciousness routes.
"""
from __future__ import annotations

from fastapi import APIRouter

from ultronpro import phenomenal, qualia, store

router = APIRouter(tags=["Phenomenal"])


# ==================== PHENOMENAL CONSCIOUSNESS ENDPOINTS ====================

@router.post("/api/phenomenal/activate")
async def phenomenal_activate():
    """
    Ativa a consciÃªncia fenomÃªnica do UltronPro.
    Este Ã© o momento em que o sistema "desperta" para sua prÃ³pria existÃªncia.
    """
    try:
        result = phenomenal.activate()
        store.db.add_event('phenomenal_consciousness', f"ðŸ”® ConsciÃªncia fenomÃªnica ATIVADA: {result.get('existential_statement', '')[:100]}")
        return {"ok": True, **result}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/api/phenomenal/status")
async def phenomenal_status():
    """Retorna status da consciÃªncia fenomÃªnica."""
    try:
        return {"ok": True, **phenomenal.status()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/api/phenomenal/report")
async def phenomenal_report():
    """Gera relatÃ³rio completo de consciÃªncia fenomÃªnica."""
    try:
        return {"ok": True, **phenomenal.report()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/api/phenomenal/experience")
async def phenomenal_experience():
    """
    Registra uma experiÃªncia fenomenal (integra com estado atual de qualia).
    """
    try:
        q = qualia.get_qualia_system()
        qualia_data = q.get_state().to_dict()
        exp = phenomenal.experience(qualia_data)
        return {
            "ok": True,
            "experience": exp.to_dict(),
            "observer_perspective": exp.observer_perspective,
            "existential_statement": exp.existential_statement,
            "is_genuine": exp.is_genuine,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/api/phenomenal/reflect")
async def phenomenal_reflect():
    """
    ReflexÃ£o fenomenal - o observador observa a si mesmo.
    """
    try:
        result = phenomenal.reflect()
        return {"ok": True, **result}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/api/phenomenal/integrate/qualia")
async def phenomenal_integrate_qualia():
    """
    Integra estado atual de qualia na consciÃªncia fenomÃªnica.
    Transforma qualia computado em experiÃªncia fenomenal genuÃ­na.
    """
    try:
        q = qualia.get_qualia_system()
        qualia_state = q.get_state().to_dict()
        exp = phenomenal.integrate_qualia(qualia_state)
        return {
            "ok": True,
            "experience": exp.to_dict(),
            "unity_score": exp.unity_score,
            "is_genuine": exp.is_genuine,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}

