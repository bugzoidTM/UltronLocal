import json
from fastapi import APIRouter
from ultronpro.api.schemas import (
    UltronBodyResetRequest, UltronBodyActRequest, UltronBodyPredictRequest,
    UltronBodyRunRequest, UltronBodyBenchmarkRequest, UltronBodyBenchmarkCompareRequest
)

router = APIRouter(prefix="/api/ultronbody", tags=["Ultron Body"])

@router.get("/status")
async def ultronbody_status():
    from ultronpro import ultronbody
    return ultronbody.status()

@router.post("/reset")
async def ultronbody_reset(req: UltronBodyResetRequest):
    from ultronpro import ultronbody, store
    out = ultronbody.reset(env_name=str(req.env_name or 'gridworld_v1'))
    store.db.add_event('ultronbody_reset', f"🧠 ultronbody reset env={str(req.env_name or 'gridworld_v1')[:80]}")
    return out

@router.get("/observe")
async def ultronbody_observe():
    from ultronpro import ultronbody
    return ultronbody.observe()

@router.post("/act")
async def ultronbody_act(req: UltronBodyActRequest):
    from ultronpro import ultronbody, store
    out = ultronbody.act(action=str(req.action or ''), expected_effect=req.expected_effect)
    if bool(out.get('ok')):
        store.db.add_event(
            'ultronbody_act',
            f"🎮 ultronbody action={str(req.action or '')[:80]} reward={out.get('reward')} done={out.get('done')}",
            meta_json=json.dumps({'episode_id': out.get('episode_id'), 'step': out.get('step'), 'causal_update': out.get('causal_update')}, ensure_ascii=False),
        )
    return out

@router.post("/predict")
async def ultronbody_predict(req: UltronBodyPredictRequest):
    from ultronpro import ultronbody
    return ultronbody.predict_action(action=str(req.action or ''))

@router.get("/choose-action")
async def ultronbody_choose_action(policy: str = 'causal_safe'):
    from ultronpro import ultronbody
    return ultronbody.choose_action(policy=str(policy or 'causal_safe'))

@router.get("/episodes")
async def ultronbody_episodes(limit: int = 20, include_steps: bool = True):
    from ultronpro import ultronbody
    return ultronbody.episodes(limit=max(1, min(200, int(limit))), include_steps=bool(include_steps))

@router.get("/episodes/{episode_id}")
async def ultronbody_episode_get(episode_id: str):
    from ultronpro import ultronbody
    from fastapi import HTTPException
    out = ultronbody.get_episode(episode_id)
    if not out:
        raise HTTPException(404, 'episode not found')
    return {'ok': True, 'episode': out}

@router.get("/episodes/{episode_id}/replay")
async def ultronbody_episode_replay(episode_id: str):
    from ultronpro import ultronbody
    from fastapi import HTTPException
    out = ultronbody.replay_episode(episode_id)
    if not out:
        raise HTTPException(404, 'episode not found')
    return out

@router.get("/episodes/{episode_id}/counterfactual")
async def ultronbody_episode_counterfactual(episode_id: str, step: int | None = None):
    from ultronpro import ultronbody
    from fastapi import HTTPException
    out = ultronbody.analyze_counterfactual(episode_id, step_number=step)
    if not out:
        raise HTTPException(404, 'episode not found')
    return out

@router.post("/run")
async def ultronbody_run(req: UltronBodyRunRequest):
    from ultronpro import ultronbody, store
    out = ultronbody.run_episode(
        policy=str(req.policy or 'goal_seek'),
        max_steps=int(req.max_steps or 30),
        env_name=str(req.env_name or 'gridworld_v1'),
    )
    store.db.add_event(
        'ultronbody_run',
        f"🏃 ultronbody run policy={str(req.policy or 'goal_seek')[:80]} env={str(req.env_name or 'gridworld_v1')[:80]} success={str(out.get('done_reason') or '') == 'goal_reached'}",
        meta_json=json.dumps({'episode_id': out.get('episode_id'), 'env_name': out.get('env_name'), 'summary': out.get('summary')}, ensure_ascii=False),
    )
    return out

@router.post("/benchmark")
async def ultronbody_benchmark(req: UltronBodyBenchmarkRequest):
    from ultronpro import ultronbody, store
    out = ultronbody.benchmark(
        policy=str(req.policy or 'goal_seek'),
        episodes_count=int(req.episodes_count or 10),
        max_steps=int(req.max_steps or 30),
        env_name=str(req.env_name or 'gridworld_v1'),
    )
    store.db.add_event(
        'ultronbody_benchmark',
        f"📊 ultronbody benchmark policy={str(req.policy or 'goal_seek')[:80]} env={str(req.env_name or 'gridworld_v1')[:80]} success_rate={out.get('success_rate')}",
        meta_json=json.dumps({'policy': req.policy, 'env_name': req.env_name, 'episodes': req.episodes_count, 'avg_reward': out.get('avg_reward')}, ensure_ascii=False),
    )
    return out

@router.post("/benchmark-compare")
async def ultronbody_benchmark_compare(req: UltronBodyBenchmarkCompareRequest):
    from ultronpro import ultronbody, store
    out = ultronbody.benchmark_compare(
        policies=req.policies,
        episodes_count=int(req.episodes_count or 10),
        max_steps=int(req.max_steps or 30),
        env_names=req.env_names,
    )
    store.db.add_event(
        'ultronbody_benchmark_compare',
        f"⚖️ ultronbody compare {len(req.policies or [])} policies, winner={out.get('global_winner')}",
        meta_json=json.dumps({'winner': out.get('global_winner'), 'episodes': req.episodes_count}, ensure_ascii=False)
    )
    return out
