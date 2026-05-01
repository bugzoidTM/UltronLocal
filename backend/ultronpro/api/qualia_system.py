"""
Qualia system routes.
"""
from __future__ import annotations

from fastapi import APIRouter

from ultronpro import cognitive_state, conflicts, homeostasis, qualia, store

router = APIRouter(tags=["Qualia"])


# ==================== QUALIA SYSTEM ENDPOINTS ====================

@router.get("/api/qualia/status")
async def qualia_status():
    """Status do sistema de qualia."""
    try:
        q = qualia.get_qualia_system()
        state = q.get_state()
        return {
            "ok": True,
            "valence": state.valence,
            "arousal": state.arousal,
            "dominance": state.dominance,
            "coherence": state.coherence,
            "integration": state.integration,
            "mood": state.mood_descriptor,
            "narrative": state.narrative,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/api/qualia/report")
async def qualia_report():
    """RelatÃ³rio completo de experiÃªncia subjetiva."""
    try:
        q = qualia.get_qualia_system()
        report = q.generate_report()
        return report
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/api/qualia/phenomenal")
async def qualia_phenomenal():
    """RelatÃ³rio fenomenal (como se sente ser UltronPro agora)."""
    try:
        q = qualia.get_qualia_system()
        report = q.generate_phenomenal_report()
        return {"ok": True, "phenomenal_report": report}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/api/qualia/perceive")
async def qualia_perceive(
    content: str,
    source: str = "user",
    salience: float = 0.5,
    valence: float = 0.0,
    novelty: float = 0.5,
):
    """Registra uma nova percepÃ§Ã£o."""
    try:
        q = qualia.get_qualia_system()
        perception = q.perceive(content, source, salience, valence, novelty)
        return {
            "ok": True,
            "perception": perception.to_dict(),
            "current_state": q.get_state().to_dict(),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/api/qualia/update")
async def qualia_update(
    valence_delta: float = 0.0,
    arousal_delta: float = 0.0,
    dominance_delta: float = 0.0,
    coherence: float = None,
    integration: float = None,
):
    """Atualiza estado de qualia."""
    try:
        q = qualia.get_qualia_system()
        state = q.update(
            valence_delta=valence_delta,
            arousal_delta=arousal_delta,
            dominance_delta=dominance_delta,
            coherence=coherence,
            integration=integration,
        )
        return {
            "ok": True,
            "state": state.to_dict(),
            "mood": q.compute_mood(),
            "narrative": q.generate_narrative(),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/api/qualia/qualia_types")
async def qualia_types():
    """Lista todos os tipos de qualia disponÃ­veis."""
    try:
        return {
            "ok": True,
            "types": [t.value for t in qualia.QualiaType],
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/api/qualia/intensity")
async def qualia_intensity():
    """Retorna intensidade de todas as qualia."""
    try:
        q = qualia.get_qualia_system()
        intensities = q.update_all_qualia()
        return {
            "ok": True,
            "intensities": intensities,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/api/qualia/perceptions")
async def qualia_perceptions(limit: int = 10):
    """Retorna percepÃ§Ãµes recentes."""
    try:
        q = qualia.get_qualia_system()
        recent = q.get_recent_perceptions(limit)
        return {
            "ok": True,
            "perceptions": [p.to_dict() for p in recent],
            "count": len(recent),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/api/qualia/integrate/homeostasis")
async def qualia_integrate_homeostasis():
    """Integra sinais de homeostase no sistema de qualia."""
    try:
        q = qualia.get_qualia_system()
        vitals = homeostasis.evaluate(
            stats=store.db.get_stats(),
            open_conflicts=len(conflicts.get_open_conflicts()),
            decision_quality=store.db.get_recent_decision_quality(),
            queue_size=len(store.db.get_queue()),
            used_last_minute=store.db.get_used_last_minute(),
            per_minute=store.db.get_per_minute(),
            active_goal=bool(store.db.get_active_goal()),
        )
        q.integrate_homeostasis(vitals.get('mode', 'normal'), vitals.get('vitals', {}))
        return {
            "ok": True,
            "homeostasis": vitals,
            "qualia_state": q.get_state().to_dict(),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/api/qualia/integrate/cognitive")
async def qualia_integrate_cognitive():
    """Integra estado cognitivo no sistema de qualia."""
    try:
        q = qualia.get_qualia_system()
        cog_state = cognitive_state.get_state()
        q.integrate_cognitive_state(
            beliefs_count=len(cog_state.get('beliefs', {})),
            uncertainties=cog_state.get('uncertainties', []),
            constraints=cog_state.get('constraints', []),
        )
        return {
            "ok": True,
            "cognitive_state": cog_state,
            "qualia_state": q.get_state().to_dict(),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/api/qualia/reset")
async def qualia_reset():
    """Reseta estado de qualia."""
    try:
        q = qualia.get_qualia_system()
        q.reset()
        return {"ok": True, "message": "Qualia state reset"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

