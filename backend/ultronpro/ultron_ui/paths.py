from __future__ import annotations

import os
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[3]
BACKEND_DIR = ROOT_DIR / "backend"
DATA_DIR = BACKEND_DIR / "data"


def _path_from_env(name: str, default: Path) -> Path:
    raw = os.getenv(name, "").strip()
    return Path(raw).expanduser() if raw else default


def vosk_model_dir() -> Path:
    full_model = DATA_DIR / "models" / "vosk" / "vosk-model-pt-fb-v0.1.1-20220516_2113"
    if os.getenv("ULTRON_UI_PREFER_FULL_VOSK", "0").strip().lower() in {"1", "true", "yes", "on"} and full_model.exists():
        return _path_from_env("ULTRON_UI_VOSK_MODEL_DIR", full_model)
    return _path_from_env(
        "ULTRON_UI_VOSK_MODEL_DIR",
        DATA_DIR / "models" / "vosk" / "vosk-model-small-pt-0.3",
    )


def piper_exe_path() -> Path:
    default_name = "piper.exe" if os.name == "nt" else "piper"
    return _path_from_env("ULTRON_UI_PIPER_EXE", BACKEND_DIR / "bin" / "piper" / default_name)


def piper_voice_path() -> Path:
    return _path_from_env(
        "ULTRON_UI_PIPER_VOICE",
        DATA_DIR / "piper" / "voices" / "pt_BR-faber-medium.onnx",
    )


def tasks_dir() -> Path:
    return _path_from_env("ULTRON_UI_TASKS_DIR", ROOT_DIR / "tasks")


def tmp_dir() -> Path:
    return _path_from_env("ULTRON_UI_TMP_DIR", BACKEND_DIR / "tmp" / "ultron_ui")
