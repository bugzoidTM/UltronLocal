"""
Vision system routes.
"""
from __future__ import annotations

from fastapi import APIRouter

from ultronpro import vision

router = APIRouter(tags=["Vision"])


# ==================== Vision System ====================

@router.post('/api/vision/analyze')
async def vision_analyze(image_url: str | None = None, prompt: str | None = None):
    """Analisa uma imagem via LLM com visÃ£o."""
    if not image_url:
        return {'ok': False, 'error': 'ForneÃ§a image_url'}
    try:
        result = vision.analyze_image(image_url, prompt)
        return {
            'ok': True,
            'result': {
                'description': result.description,
                'objects': result.objects,
                'text': result.text,
                'scene_type': result.scene_type,
                'confidence': result.confidence,
            }
        }
    except Exception as e:
        return {'ok': False, 'error': str(e)}


@router.post('/api/vision/extract-text')
async def vision_extract_text(image_url: str):
    """Extrai texto de uma imagem (OCR)."""
    try:
        text = vision.extract_text_from_image(image_url)
        return {'ok': True, 'text': text}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


@router.post('/api/vision/describe-scene')
async def vision_describe_scene(image_url: str):
    """Descreve a cena em uma imagem."""
    try:
        desc = vision.describe_scene(image_url)
        return {'ok': True, 'description': desc}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


@router.post('/api/vision/screenshot')
async def vision_screenshot(image_url: str):
    """Analisa um screenshot de interface."""
    try:
        result = vision.analyze_screenshot(image_url)
        return {'ok': True, 'result': result}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


@router.post('/api/vision/clear-cache')
async def vision_clear_cache():
    """Limpa cache de visÃµes."""
    vision.get_vision_system().clear_cache()
    return {'ok': True}
