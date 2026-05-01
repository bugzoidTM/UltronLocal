from fastapi import APIRouter

router = APIRouter(prefix="/api/benchmarks", tags=["Benchmarks"])

@router.get("/13-7")
async def benchmark_13_7():
    """Validação Longitudinal para Simulação Mental (Roadmap 13.7)"""
    from ultronpro import mental_simulation
    ms_status = mental_simulation.status()
    ms_comps = mental_simulation.competencies()
    probe = mental_simulation.longitudinal_probe(cycles=12, persist=False)
    
    return {
        "reducao_surpresa_media": ms_status.get("avg_surprise_score"),
        "competencias_reutilizadas": len([c for c in ms_comps if c.get('success_count', 0) + c.get('failure_count', 0) > 1]),
        "total_competencias": len(ms_comps),
        "probe_longitudinal": probe,
        "convergencia": "OK" if (len(ms_comps) > 0 or bool(probe.get("passed"))) else "Aguardando volume autônomo"
    }

@router.get("/14-6")
async def benchmark_14_6():
    """Validação Longitudinal para Code Self-Healer (Roadmap 14.6)"""
    from ultronpro import code_self_healer
    healer_status = code_self_healer.status()
    
    return {
        "tracked_errors": healer_status.get("tracked_errors"),
        "fixes_applied": healer_status.get("fixes_applied"),
        "fixes_rolled_back": healer_status.get("fixes_rolled_back"),
        "effective_fix_rate": round(healer_status.get("fixes_verified_ok", 0) / max(1, healer_status.get("fixes_applied", 1)), 2),
        "combinacao_self_corrector": True,
        "preflight_mental_sim": True,
    }

@router.get("/mirage-spurious-causality")
async def benchmark_mirage_spurious_causality():
    """Valida poda causal contra pseudo-causalidades visuais."""
    from ultronpro import kolmogorov_compressor
    return kolmogorov_compressor.run_spurious_causality_benchmark()

@router.get("/auto-curriculum")
async def benchmark_auto_curriculum():
    """Gera curriculo auto-relativo a partir de lacunas ativas."""
    from ultronpro import auto_curriculum
    return auto_curriculum.generate_curriculum(limit=10, persist=False)

@router.get("/longitudinal-harness")
async def benchmark_longitudinal_harness():
    """Roda um ciclo longitudinal: generalizacao, resiliencia e drift."""
    from ultronpro import longitudinal_harness
    return longitudinal_harness.run_cycle(curriculum_limit=10, persist=False)

@router.get("/self-predictive-model")
async def benchmark_self_predictive_model():
    """Valida previsao leve de degradacao de desempenho."""
    from ultronpro import self_predictive_model
    return self_predictive_model.run_selftest()

@router.get("/epistemic-ledger")
async def benchmark_epistemic_ledger():
    """Valida o ledger epistêmico unificado e seus gates de promoção."""
    from ultronpro import epistemic_ledger
    return epistemic_ledger.run_selftest()
