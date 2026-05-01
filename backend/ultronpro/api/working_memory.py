"""
Working memory routes.
"""
from __future__ import annotations

from fastapi import APIRouter

from ultronpro import working_memory

router = APIRouter(tags=["Working Memory"])


def _wm():
    return working_memory.get_working_memory()


# ==================== Working Memory ====================

@router.get('/api/working-memory/status')
async def working_memory_status():
    """Retorna status da memÃ³ria de trabalho."""
    return _wm().get_status()


@router.get('/api/working-memory/context')
async def working_memory_context(max_tokens: int = 2000):
    """Retorna contexto da memÃ³ria de trabalho para prompts."""
    return {'ok': True, 'context': _wm().get_context_window(max_tokens)}


@router.get('/api/working-memory/top')
async def working_memory_top(n: int = 10, min_salience: float = 0.0):
    """Retorna os top itens por saliÃªncia."""
    items = _wm().get_top(n, min_salience)
    return {
        'ok': True,
        'items': [
            {
                'id': item.id,
                'content': item.content,
                'salience': round(item.salience, 3),
                'type': item.item_type,
                'source': item.source,
                'created_at': item.created_at,
            }
            for item in items
        ]
    }


@router.post('/api/working-memory/add')
async def working_memory_add(
    content: str,
    source: str = 'system',
    item_type: str = 'observation',
    salience: float | None = None
):
    """Adiciona item Ã  memÃ³ria de trabalho."""
    item = _wm().add(content, source, item_type, salience)
    return {'ok': True, 'item': {
        'id': item.id,
        'salience': round(item.salience, 3),
    }}


@router.post('/api/working-memory/access')
async def working_memory_access(item_id: str):
    """Acessa um item (aumenta attention)."""
    item = _wm().access(item_id)
    if not item:
        return {'ok': False, 'error': 'Item nÃ£o encontrado'}
    return {'ok': True, 'item': {
        'id': item.id,
        'content': item.content,
        'salience': round(item.salience, 3),
    }}


@router.post('/api/working-memory/focus')
async def working_memory_set_focus(item_id: str | None = None):
    """Define item em foco."""
    _wm().set_focus(item_id)
    return {'ok': True}


@router.post('/api/working-memory/attention-state')
async def working_memory_attention_state(state: str):
    """Define estado de atenÃ§Ã£o (focused, distracted, deep, broad)."""
    _wm().set_attention_state(state)
    return {'ok': True}


@router.delete('/api/working-memory')
async def working_memory_clear(item_type: str | None = None):
    """Limpa memÃ³ria de trabalho."""
    _wm().clear(item_type)
    return {'ok': True}
