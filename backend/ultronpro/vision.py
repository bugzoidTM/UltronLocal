"""
Vision System — Percepção Visual Multimodal
==========================================

Sistema de percepção visual que utiliza LLMs com capacidade de visão
(GPT-4V, Claude Vision, ou modelos locais como LLaVA) para analisar imagens.

Funcionalidades:
- Análise de conteúdo de imagens
- Extração de texto (OCR)
- Descrição de cenas
- Detecção de objetos
- Compreensão de diagrams/screenshots
- Integração com o grafo de conhecimento

"""

from __future__ import annotations

import base64
import io
import json
from pathlib import Path
from typing import Any, Optional
from dataclasses import dataclass

import requests

from ultronpro import settings


DATA_DIR = Path(__file__).resolve().parent.parent.parent / 'data'
VISION_CACHE_PATH = DATA_DIR / 'vision_cache.json'


def _setting(name: str, default: Any = None) -> Any:
    try:
        value = settings.load_settings().get(name)
        if value:
            return value
    except Exception:
        pass
    import os
    return os.getenv(name, default)


@dataclass
class VisionResult:
    description: str
    objects: list[str]
    text: str
    scene_type: str
    confidence: float
    raw_response: dict


class VisionSystem:
    DEFAULT_PROVIDER = "openai"
    DEFAULT_MODEL = "gpt-4o"
    
    def __init__(self, provider: str | None = None, model: str | None = None):
        self.provider = provider or _setting("VISION_PROVIDER") or self.DEFAULT_PROVIDER
        self.model = model or _setting("VISION_MODEL") or self.DEFAULT_MODEL
        self._cache = self._load_cache()

    def _load_cache(self) -> dict:
        if not VISION_CACHE_PATH.exists():
            return {}
        try:
            return json.loads(VISION_CACHE_PATH.read_text(encoding='utf-8'))
        except Exception:
            return {}

    def _save_cache(self):
        VISION_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        VISION_CACHE_PATH.write_text(json.dumps(self._cache, ensure_ascii=False, indent=2))

    def _get_cache_key(self, image_data: bytes | str) -> str:
        import hashlib
        if isinstance(image_data, str):
            image_data = image_data.encode()
        return hashlib.sha256(image_data).hexdigest()[:16]

    def _encode_image(self, image_path: str | Path | bytes) -> str:
        if isinstance(image_path, (str, Path)):
            p = Path(image_path)
            if p.exists():
                image_data = p.read_bytes()
            else:
                image_data = image_path.encode()
        else:
            image_data = image_path
        
        return base64.b64encode(image_data).decode('utf-8')

    def analyze(self, image_path: str | Path | bytes, prompt: str | None = None,
                use_cache: bool = True) -> VisionResult:
        """Analisa uma imagem usando LLM com visão."""
        
        b64_image = self._encode_image(image_path)
        cache_key = self._get_cache_key(b64_image.encode())
        
        if use_cache and cache_key in self._cache:
            cached = self._cache[cache_key]
            return VisionResult(**cached)
        
        default_prompt = prompt or """Analise esta imagem detalhadamente. Forneça:
1. Descrição geral do conteúdo
2. Lista de objetos principais identificados
3. Qualquer texto visível
4. Tipo de cena (foto, screenshot, diagrama, etc)
5. Nível de confiança na análise (0-1)

Responda em JSON com as chaves: description, objects, text, scene_type, confidence"""

        if self.provider == "openai":
            result = self._analyze_openai(b64_image, default_prompt)
        elif self.provider == "anthropic":
            result = self._analyze_anthropic(b64_image, default_prompt)
        elif self.provider == "ollama":
            result = self._analyze_ollama(b64_image, default_prompt)
        else:
            result = self._analyze_openai(b64_image, default_prompt)
        
        if use_cache:
            self._cache[cache_key] = {
                'description': result.description,
                'objects': result.objects,
                'text': result.text,
                'scene_type': result.scene_type,
                'confidence': result.confidence,
                'raw_response': result.raw_response,
            }
            self._save_cache()
        
        return result

    def _analyze_openai(self, b64_image: str, prompt: str) -> VisionResult:
        api_key = _setting("openai_api_key") or settings.get_api_key("openai")
        if not api_key:
            raise ValueError("OpenAI API key não configurada")
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
        
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_image}"}}
                    ]
                }
            ],
            "max_tokens": 1000
        }
        
        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=60
        )
        
        if not resp.ok:
            raise ValueError(f"OpenAI API error: {resp.text}")
        
        content = resp.json()["choices"][0]["message"]["content"]
        
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            parsed = {"description": content, "objects": [], "text": "", "scene_type": "unknown", "confidence": 0.5}
        
        return VisionResult(
            description=parsed.get("description", ""),
            objects=parsed.get("objects", []),
            text=parsed.get("text", ""),
            scene_type=parsed.get("scene_type", "unknown"),
            confidence=parsed.get("confidence", 0.5),
            raw_response=parsed
        )

    def _analyze_anthropic(self, b64_image: str, prompt: str) -> VisionResult:
        api_key = _setting("anthropic_api_key") or settings.get_api_key("anthropic")
        if not api_key:
            raise ValueError("Anthropic API key não configurada")
        
        headers = {
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01"
        }
        
        payload = {
            "model": "claude-3-5-sonnet-20241022",
            "max_tokens": 1000,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64_image}}
                    ]
                }
            ]
        }
        
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers=headers,
            json=payload,
            timeout=60
        )
        
        if not resp.ok:
            raise ValueError(f"Anthropic API error: {resp.text}")
        
        content = resp.json()["content"][0]["text"]
        
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            parsed = {"description": content, "objects": [], "text": "", "scene_type": "unknown", "confidence": 0.5}
        
        return VisionResult(
            description=parsed.get("description", ""),
            objects=parsed.get("objects", []),
            text=parsed.get("text", ""),
            scene_type=parsed.get("scene_type", "unknown"),
            confidence=parsed.get("confidence", 0.5),
            raw_response=parsed
        )

    def _analyze_ollama(self, b64_image: str, prompt: str) -> VisionResult:
        ollama_url = _setting("OLLAMA_URL") or "http://localhost:11434"
        
        payload = {
            "model": "llava",
            "prompt": prompt,
            "images": [b64_image],
            "stream": False
        }
        
        resp = requests.post(
            f"{ollama_url}/api/generate",
            json=payload,
            timeout=120
        )
        
        if not resp.ok:
            raise ValueError(f"Ollama API error: {resp.text}")
        
        content = resp.json().get("response", "")
        
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            parsed = {"description": content, "objects": [], "text": "", "scene_type": "unknown", "confidence": 0.5}
        
        return VisionResult(
            description=parsed.get("description", ""),
            objects=parsed.get("objects", []),
            text=parsed.get("text", ""),
            scene_type=parsed.get("scene_type", "unknown"),
            confidence=parsed.get("confidence", 0.5),
            raw_response=parsed
        )

    def extract_text(self, image_path: str | Path) -> str:
        """Extrai texto de uma imagem (OCR simples via LLM)."""
        result = self.analyze(image_path, prompt="""
Extraia TODO o texto visível nesta imagem.
Responda apenas com o texto encontrado, em JSON: {"text": "..."}
""")
        return result.text

    def describe_scene(self, image_path: str | Path) -> str:
        """Descreve a cena em uma imagem."""
        result = self.analyze(image_path)
        return result.description

    def get_objects(self, image_path: str | Path) -> list[str]:
        """Retorna lista de objetos detectados."""
        result = self.analyze(image_path)
        return result.objects

    def analyze_screenshot(self, image_path: str | Path) -> dict:
        """Analisa um screenshot e extrai informações estruturadas."""
        result = self.analyze(image_path, prompt="""
Este é um screenshot de uma interface. Analise e forneça:
1. Tipo de interface (app, website, terminal, etc)
2. Elementos UI principais (botões, menus, campos)
3. Estado aparente (carregando, erro, sucesso, etc)
4. Texto relevante

Responda em JSON:
{"interface_type": "...", "ui_elements": [...], "state": "...", "relevant_text": "..."}
""")
        return result.raw_response

    def clear_cache(self):
        """Limpa o cache de visões."""
        self._cache = {}
        self._save_cache()


_vision_system: Optional[VisionSystem] = None


def get_vision_system() -> VisionSystem:
    global _vision_system
    if _vision_system is None:
        _vision_system = VisionSystem()
    return _vision_system


def analyze_image(image_path: str | Path, prompt: str | None = None) -> VisionResult:
    return get_vision_system().analyze(image_path, prompt)


def extract_text_from_image(image_path: str | Path) -> str:
    return get_vision_system().extract_text(image_path)


def describe_scene(image_path: str | Path) -> str:
    return get_vision_system().describe_scene(image_path)


def get_detected_objects(image_path: str | Path) -> list[str]:
    return get_vision_system().get_objects(image_path)


def analyze_screenshot(image_path: str | Path) -> dict:
    return get_vision_system().analyze_screenshot(image_path)
