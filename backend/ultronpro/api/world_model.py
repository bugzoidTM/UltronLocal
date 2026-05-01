"""
World model routes.
"""
from __future__ import annotations

from fastapi import APIRouter

from ultronpro import world_model

router = APIRouter(tags=["World Model"])


def _world():
    return world_model.get_world_model()


# ==================== World Model ====================

@router.get('/api/world-model/status')
async def world_model_status():
    """Retorna status do modelo do mundo."""
    return _world().get_state_summary()


@router.get('/api/world-model/observations')
async def world_model_observations(n: int = 20, event_type: str | None = None):
    """Retorna observaÃ§Ãµes recentes."""
    return {
        'ok': True,
        'observations': _world().get_recent_observations(n, event_type)
    }


@router.post('/api/world-model/observe')
async def world_model_observe(
    source: str,
    event_type: str,
    content: str,
    state_before: dict | None = None,
    state_after: dict | None = None,
    outcome: str = 'unknown'
):
    """Registra uma observaÃ§Ã£o."""
    obs = world_model.observe(source, event_type, content, state_before, state_after, outcome)
    return {
        'ok': True,
        'observation': {
            'id': obs.id,
            'ts': obs.ts,
        }
    }


@router.post('/api/world-model/entity')
async def world_model_update_entity(entity_id: str, data: dict):
    """Atualiza uma entidade."""
    world_model.update_entity(entity_id, data)
    return {'ok': True}


@router.get('/api/world-model/entity/{entity_id}')
async def world_model_get_entity(entity_id: str):
    """Retorna dados de uma entidade."""
    entity = world_model.get_entity(entity_id)
    if not entity:
        return {'ok': False, 'error': 'Entidade nÃ£o encontrada'}
    return {'ok': True, 'entity': entity}


@router.get('/api/world-model/predict/{event_type}')
async def world_model_predict(event_type: str):
    """Prediz prÃ³ximo estado baseado em padrÃµes."""
    prediction = world_model.predict_next(event_type)
    if not prediction:
        return {'ok': False, 'error': 'Dados insuficientes para prediÃ§Ã£o'}
    return {'ok': True, 'prediction': prediction}


@router.delete('/api/world-model')
async def world_model_clear():
    """Limpa o modelo do mundo."""
    _world().clear()
    return {'ok': True}


@router.post('/api/world-model/simulate')
async def world_model_simulate(payload: dict):
    """
    Simula uma aÃ§Ã£o no ambiente e retorna as prediÃ§Ãµes.
    {'action_type': '...', 'params': {}}
    """
    action_type = payload.get('action_type', 'unknown')
    params = payload.get('params', {})
    prediction = world_model.simulate_action(action_type, params)
    import logging
    logging.getLogger('uvicorn').info(f"Ultron simulou a acao antes de tentar: {prediction}")
    return {'ok': True, 'simulation': prediction}

