import json
from fastapi import APIRouter, HTTPException
from ultronpro.api.schemas import (
    ExplicitAbstractionCreateRequest,
    ExplicitAbstractionTransferRequest,
    AbstractionBatchExtractRequest,
    StructuralMapRequest,
    TransferBenchmarkRequest
)

router = APIRouter(prefix="/api/abstractions", tags=["Abstractions"])

@router.get("/status")
async def abstractions_status():
    from ultronpro import explicit_abstractions
    return explicit_abstractions.stats()

@router.get("/portfolio-summary")
async def abstractions_portfolio_summary():
    from ultronpro import explicit_abstractions
    return explicit_abstractions.portfolio_summary()

@router.get("")
async def abstractions_list(limit: int = 50, domain: str | None = None):
    from ultronpro import explicit_abstractions
    return explicit_abstractions.list_abstractions(limit=max(1, min(500, int(limit))), domain=domain)

@router.get("/{abstraction_id}")
async def abstractions_get(abstraction_id: str):
    from ultronpro import explicit_abstractions
    out = explicit_abstractions.get_abstraction(abstraction_id)
    if not out:
        raise HTTPException(404, 'abstraction not found')
    return {'ok': True, 'item': out}

@router.post("")
async def abstractions_create(req: ExplicitAbstractionCreateRequest):
    from ultronpro import explicit_abstractions, store
    out = explicit_abstractions.create_abstraction(
        principle=req.principle,
        source_domains=req.source_domains,
        applicability_conditions=req.applicability_conditions,
        procedure_template=req.procedure_template,
        confidence=float(req.confidence or 0.5),
        notes=req.notes,
    )
    store.db.add_event('explicit_abstraction_created', f"🧩 abstraction criada: {str(out.get('id') or '')[:80]}")
    return {'ok': True, 'item': out}

@router.post("/{abstraction_id}/transfer")
async def abstractions_transfer(abstraction_id: str, req: ExplicitAbstractionTransferRequest):
    from ultronpro import explicit_abstractions, store
    out = explicit_abstractions.update_transfer_history(
        abstraction_id,
        target_domain=req.target_domain,
        outcome=req.outcome,
        evidence_ref=req.evidence_ref,
        score=req.score,
        notes=req.notes,
    )
    if not out:
        raise HTTPException(404, 'abstraction not found')
    store.db.add_event('explicit_abstraction_transfer', f"🔁 abstraction transfer: {str(abstraction_id)[:80]} -> {str(req.target_domain or '')[:80]}")
    return {'ok': True, 'item': out}

@router.post("/{abstraction_id}/consolidate")
async def abstractions_consolidate(abstraction_id: str):
    from ultronpro import transfer_benchmark, store
    out = transfer_benchmark.consolidate_from_latest(abstraction_id)
    if not out:
        raise HTTPException(404, 'abstraction or benchmark not found')
    store.db.add_event(
        'explicit_abstraction_consolidated', 
        f"🏷️ abstraction consolidada: {str(abstraction_id)[:80]}", 
        meta_json=json.dumps({'status': ((out.get('item') or {}).get('status')), 'benchmark_score': (((out.get('item') or {}).get('benchmark_summary') or {}).get('benchmark_score'))}, ensure_ascii=False)
    )
    return out

@router.post("/ingest-from-ultronbody/{episode_id}")
async def abstractions_ingest_from_ultronbody(episode_id: str):
    from ultronpro import ultronbody, explicit_abstractions, store
    episode = ultronbody.get_episode(episode_id)
    if not episode:
        raise HTTPException(404, 'episode not found')
    out = explicit_abstractions.ingest_ultronbody_episode(episode)
    store.db.add_event('explicit_abstraction_ingest', f"🧠 abstractions ingestidas do episódio: {str(episode_id)[:80]}", meta_json=json.dumps({'count': out.get('count')}, ensure_ascii=False))
    return out

@router.post("/extract-from-ultronbody/recent")
async def abstractions_extract_from_ultronbody_recent(req: AbstractionBatchExtractRequest):
    from ultronpro import ultronbody, explicit_abstractions, store
    episodes_out = ultronbody.episodes(limit=max(1, min(200, int(req.limit or 20))), include_steps=True)
    items = episodes_out.get('items') if isinstance(episodes_out, dict) else []
    out = explicit_abstractions.batch_extract_from_ultronbody_episodes(items if isinstance(items, list) else [], min_cluster_size=max(1, min(10, int(req.min_cluster_size or 2))))
    store.db.add_event('explicit_abstraction_batch_extract', f"🧪 abstractions extraídas em lote do ultronbody: created={out.get('created_count')}", meta_json=json.dumps({'clusters': out.get('clusters'), 'created_count': out.get('created_count')}, ensure_ascii=False))
    return out

@router.get("/mappings/recent")
async def abstractions_mappings_recent(limit: int = 20):
    from ultronpro import structural_mapper
    return structural_mapper.recent_mappings(limit=max(1, min(200, int(limit))))

@router.post("/{abstraction_id}/map")
async def abstractions_map(abstraction_id: str, req: StructuralMapRequest):
    from ultronpro import structural_mapper, store
    out = structural_mapper.map_abstraction(abstraction_id, target_domain=req.target_domain, target_text=req.target_text)
    if not out:
        raise HTTPException(404, 'abstraction not found')
    store.db.add_event('explicit_abstraction_mapped', f"🗺️ abstraction mapeada: {str(abstraction_id)[:80]} -> {str(req.target_domain or '')[:80]}", meta_json=json.dumps({'similarity': out.get('structural_similarity'), 'recommended': out.get('recommended')}, ensure_ascii=False))
    return {'ok': True, 'mapping': out}

@router.post("/{abstraction_id}/apply")
async def abstractions_apply(abstraction_id: str, req: StructuralMapRequest):
    from ultronpro import structural_mapper, store
    out = structural_mapper.apply_mapped_abstraction(abstraction_id, target_domain=req.target_domain, target_text=req.target_text)
    if not out:
        raise HTTPException(404, 'abstraction not found')
    store.db.add_event('explicit_abstraction_applied', f"🧩 abstraction aplicada: {str(abstraction_id)[:80]} -> {str(req.target_domain or '')[:80]}", meta_json=json.dumps({'recommended': ((out.get('mapping') or {}).get('recommended')), 'similarity': ((out.get('mapping') or {}).get('structural_similarity'))}, ensure_ascii=False))
    return out

@router.get("/transfer-benchmark/scenarios")
async def abstractions_transfer_benchmark_scenarios():
    from ultronpro import transfer_benchmark
    return transfer_benchmark.scenarios()

@router.get("/transfer-benchmark/recent")
async def abstractions_transfer_benchmark_recent(limit: int = 20):
    from ultronpro import transfer_benchmark
    return transfer_benchmark.recent_reports(limit=max(1, min(200, int(limit))))

@router.post("/{abstraction_id}/transfer-benchmark")
async def abstractions_transfer_benchmark_run(abstraction_id: str, req: TransferBenchmarkRequest):
    from ultronpro import transfer_benchmark, store
    out = transfer_benchmark.benchmark_abstraction(abstraction_id, scenario_ids=req.scenario_ids)
    if not out:
        raise HTTPException(404, 'abstraction not found')
    store.db.add_event('explicit_abstraction_transfer_benchmark', f"📚 transfer benchmark: {str(abstraction_id)[:80]} avg_improvement={out.get('avg_improvement')}", meta_json=json.dumps({'scenarios': out.get('scenarios'), 'zero_shot_win_rate': out.get('zero_shot_win_rate')}, ensure_ascii=False))
    return out
