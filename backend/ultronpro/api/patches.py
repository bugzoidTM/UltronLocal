"""
Patch worktree routes.
"""
from __future__ import annotations

from fastapi import APIRouter

from ultronpro import patch_worktree

router = APIRouter(tags=["Patch Worktree"])


# ==================== PATCH WORKTREE ENDPOINTS ====================

@router.get("/api/patch/status")
async def patch_status():
    """Status do sistema de patches."""
    try:
        manager = patch_worktree.get_patch_worktree_manager()
        return manager.get_status()
    except Exception as e:
        return {"error": str(e)}


@router.post("/api/patch/process")
async def patch_process(patch_id: str, patch_content: str):
    """
    Processa um patch pelo pipeline completo:
    1. Criar worktree isolada
    2. Aplicar patch
    3. Rodar benchmark
    4. Avaliar judge
    5. Comparar delta
    6. Merge se aprovado
    """
    try:
        manager = patch_worktree.get_patch_worktree_manager()
        result = manager.process_patch(patch_id, patch_content)
        return result
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/api/patch/create")
async def patch_create(patch_id: str, patch_content: str):
    """Cria worktree isolada para um patch."""
    try:
        manager = patch_worktree.get_patch_worktree_manager()
        patch = manager.create_worktree(patch_id, patch_content)
        if patch:
            return {
                "ok": True,
                "patch_id": patch.patch_id,
                "branch": patch.branch_name,
                "worktree_path": patch.worktree_path,
                "status": patch.status.value,
            }
        return {"ok": False, "error": manager.error}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/api/patch/apply/{patch_id}")
async def patch_apply(patch_id: str):
    """Aplica patch no worktree."""
    try:
        manager = patch_worktree.get_patch_worktree_manager()
        patch = manager.get_patch(patch_id)
        if not patch:
            return {"ok": False, "error": "Patch not found"}
        
        success = manager.apply_patch(patch)
        return {
            "ok": success,
            "patch_id": patch_id,
            "status": patch.status.value,
            "error": patch.error,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/api/patch/benchmark/{patch_id}")
async def patch_benchmark(patch_id: str):
    """Executa benchmark no worktree do patch."""
    try:
        manager = patch_worktree.get_patch_worktree_manager()
        patch = manager.get_patch(patch_id)
        if not patch:
            return {"ok": False, "error": "Patch not found"}
        
        result = manager.run_benchmark(patch)
        
        if result.passed:
            try:
                from ultronpro.self_model import apply_environmental_reward
                apply_environmental_reward('benchmark_pass', {'patch_id': patch_id})
            except Exception: pass
            
        cost_increased = any(d.metric == 'cost' and d.delta > 0 for d in patch.deltas)
        if cost_increased:
            try:
                from ultronpro.self_model import apply_environmental_reward
                apply_environmental_reward('cost_increase', {'patch_id': patch_id})
            except Exception: pass
        return {
            "ok": True,
            "patch_id": patch_id,
            "passed": result.passed,
            "tests_passed": result.tests_passed,
            "tests_failed": result.tests_failed,
            "metrics": result.metrics,
            "deltas": [
                {
                    "metric": d.metric,
                    "before": d.before,
                    "after": d.after,
                    "delta": d.delta,
                    "result": d.result.value,
                }
                for d in patch.deltas
            ],
            "duration_ms": result.duration_ms,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/api/patch/judge/{patch_id}")
async def patch_judge(patch_id: str):
    """Avalia patch com judge."""
    try:
        manager = patch_worktree.get_patch_worktree_manager()
        patch = manager.get_patch(patch_id)
        if not patch:
            return {"ok": False, "error": "Patch not found"}
        
        result = manager.evaluate_judge(patch)
        return {
            "ok": True,
            "patch_id": patch_id,
            "passed": result.passed,
            "quality_score": result.quality_score,
            "risk_score": result.risk_score,
            "recommendation": result.recommendation,
            "reasoning": result.reasoning,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/api/patch/delta/{patch_id}")
async def patch_delta(patch_id: str):
    """Retorna delta do patch."""
    try:
        manager = patch_worktree.get_patch_worktree_manager()
        patch = manager.get_patch(patch_id)
        if not patch:
            return {"ok": False, "error": "Patch not found"}
        
        return manager.get_delta_summary(patch)
    except Exception as e:
        return {"ok": False, "error": str(e)}




@router.post("/api/patch/merge/{patch_id}")
async def patch_merge(patch_id: str):
    """Tenta fazer merge do patch."""
    try:
        manager = patch_worktree.get_patch_worktree_manager()
        patch = manager.get_patch(patch_id)
        if not patch:
            return {"ok": False, "error": "Patch not found"}
        
        success = manager.attempt_merge(patch)
        return {
            "ok": success,
            "patch_id": patch_id,
            "status": patch.status.value,
            "merged": success,
            "error": patch.error,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/api/patch/revert/{patch_id}")
async def patch_revert(patch_id: str):
    """Reverte um patch mergeado."""
    try:
        manager = patch_worktree.get_patch_worktree_manager()
        patch = manager.get_patch(patch_id)
        if not patch:
            return {"ok": False, "error": "Patch not found"}
        
        success = manager.revert_patch(patch)
        
        if success:
            try:
                from ultronpro.self_model import apply_environmental_reward
                apply_environmental_reward('rollback', {'patch_id': patch_id})
            except Exception: pass
        return {
            "ok": success,
            "patch_id": patch_id,
            "status": patch.status.value,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/api/patch/remove/{patch_id}")
async def patch_remove(patch_id: str):
    """Remove worktree do patch."""
    try:
        manager = patch_worktree.get_patch_worktree_manager()
        patch = manager.get_patch(patch_id)
        if not patch:
            return {"ok": False, "error": "Patch not found"}
        
        success = manager.remove_worktree(patch)
        return {"ok": success}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/api/patch/audit")
async def patch_audit(patch_id: str = None, limit: int = 50):
    """Retorna log de auditoria de patches."""
    try:
        manager = patch_worktree.get_patch_worktree_manager()
        entries = manager.get_audit_log(patch_id, limit)
        return {"ok": True, "entries": entries, "count": len(entries)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/api/patch/{patch_id}")
async def patch_get(patch_id: str):
    """Obtém detalhes de um patch."""
    try:
        manager = patch_worktree.get_patch_worktree_manager()
        patch = manager.get_patch(patch_id)
        if not patch:
            return {"ok": False, "error": "Patch not found"}
        
        return {
            "ok": True,
            "patch": {
                "patch_id": patch.patch_id,
                "branch_name": patch.branch_name,
                "worktree_path": patch.worktree_path,
                "base_commit": patch.base_commit,
                "status": patch.status.value,
                "created_at": patch.created_at,
                "merged_at": patch.merged_at,
                "error": patch.error,
                "benchmark_passed": patch.benchmark.passed if patch.benchmark else None,
                "judge_passed": patch.judge.passed if patch.judge else None,
            },
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}
