from pathlib import Path
import json
import os
import logging
from typing import Dict

SETTINGS_FILE = str(Path(__file__).resolve().parent.parent / 'data' / 'settings.json')
logger = logging.getLogger("uvicorn")

# Default settings with discovered LightRAG key
DEFAULT_SETTINGS = {
    "openai_api_key": "",
    "anthropic_api_key": "",
    "groq_api_key": "",
    "deepseek_api_key": "",
    "openrouter_api_key": "",
    "gemini_api_key": "AIzaSyAsBSMVCiOwDbxTKuY27zLXv06rS-ucJLU",
    "huggingface_api_key": "",
    "nvidia_api_key": "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",
    "github_api_key": "",
    "ollama_api_key": "",
    "lightrag_api_key": "b9714901186877fe01b1d7cd81ad65d9",  # Auto-discovered
    "lightrag_url": "http://127.0.0.1:9621/api" # Internal Docker network address
}

def load_settings() -> Dict[str, str]:
    """Load settings from persistent storage, merging with defaults."""
    settings = DEFAULT_SETTINGS.copy()
    
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r") as f:
                saved = json.load(f)
                settings.update(saved)
        except Exception as e:
            logger.error(f"Failed to load settings: {e}")
            
    return settings

def save_settings(new_settings: Dict[str, str]) -> bool:
    """Save settings to persistent storage."""
    try:
        current = load_settings()
        # Update only known keys to prevent garbage
        for k in DEFAULT_SETTINGS.keys():
            if k in new_settings:
                current[k] = new_settings[k]
        
        os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
        with open(SETTINGS_FILE, "w") as f:
            json.dump(current, f, indent=2)
        return True
    except Exception as e:
        logger.error(f"Failed to save settings: {e}")
        return False

def get_api_key(provider: str) -> str:
    """Helper to get specific API key."""
    s = load_settings()
    key_map = {
        "openai": "openai_api_key",
        "anthropic": "anthropic_api_key",
        "groq": "groq_api_key",
        "deepseek": "deepseek_api_key",
        "openrouter": "openrouter_api_key",
        "gemini": "gemini_api_key",
        "huggingface": "huggingface_api_key",
        "nvidia": "nvidia_api_key",
        "github": "github_api_key",
        "ollama": "ollama_api_key",
        "lightrag": "lightrag_api_key"
    }
    value = s.get(key_map.get(provider, ""), "")
    if value:
        return value
    env_map = {
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "groq": "GROQ_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
        "gemini": "GEMINI_API_KEY",
        "huggingface": "HUGGINGFACE_API_KEY",
        "nvidia": "NVIDIA_API_KEY",
        "github": "GITHUB_API_KEY",
        "ollama": "OLLAMA_API_KEY",
        "lightrag": "LIGHTRAG_API_KEY",
    }
    return os.getenv(env_map.get(provider, ""), "")
