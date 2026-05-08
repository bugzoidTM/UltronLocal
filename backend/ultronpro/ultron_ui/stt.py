from __future__ import annotations

import json
import math
import os
import queue
import struct
import threading
from pathlib import Path
from typing import Callable

from . import paths


def dependency_status() -> dict[str, str]:
    out: dict[str, str] = {}
    for module_name in ("vosk", "sounddevice"):
        try:
            __import__(module_name)
            out[module_name] = "ok"
        except Exception as exc:
            out[module_name] = f"missing:{type(exc).__name__}"
    model_dir = paths.vosk_model_dir()
    out["model"] = "ok" if model_dir.exists() else f"missing:{model_dir}"
    return out


class VoskMicrophoneLoop:
    def __init__(
        self,
        *,
        model_dir: Path | None = None,
        samplerate: int = 16000,
        grammar: list[str] | None = None,
    ) -> None:
        self.model_dir = model_dir or paths.vosk_model_dir()
        self.samplerate = int(samplerate)
        self.grammar = grammar

    def run(
        self,
        *,
        on_text: Callable[[str], None],
        on_status: Callable[[str], None] | None = None,
        on_partial: Callable[[str], None] | None = None,
        on_level: Callable[[float], None] | None = None,
        stop_event: threading.Event | None = None,
    ) -> None:
        import sounddevice as sd
        import vosk

        if not self.model_dir.exists():
            raise FileNotFoundError(f"Modelo Vosk não encontrado: {self.model_dir}")

        vosk.SetLogLevel(-1)
        model = vosk.Model(str(self.model_dir))
        if self.grammar:
            recognizer = vosk.KaldiRecognizer(model, self.samplerate, json.dumps(self.grammar, ensure_ascii=False))
        else:
            recognizer = vosk.KaldiRecognizer(model, self.samplerate)
        audio_queue: queue.Queue[bytes] = queue.Queue()
        stop = stop_event or threading.Event()

        def _callback(indata, frames, time_info, status):
            del frames, time_info
            if status and on_status:
                on_status(str(status))
            raw = bytes(indata)
            if on_level:
                on_level(_pcm16_level(raw))
            audio_queue.put(raw)

        if on_status:
            mode = "wake word" if self.grammar else "transcrição livre"
            on_status(f"Microfone online ({mode}).")
        with sd.RawInputStream(
            samplerate=self.samplerate,
            blocksize=int(os.getenv("ULTRON_UI_STT_BLOCKSIZE", "2048") or 2048),
            dtype="int16",
            channels=1,
            callback=_callback,
        ):
            while not stop.is_set():
                try:
                    data = audio_queue.get(timeout=0.2)
                except queue.Empty:
                    continue
                if recognizer.AcceptWaveform(data):
                    payload = json.loads(recognizer.Result() or "{}")
                    text = str(payload.get("text") or "").strip()
                    if text:
                        on_text(text)
                elif on_partial:
                    payload = json.loads(recognizer.PartialResult() or "{}")
                    partial = str(payload.get("partial") or "").strip()
                    if partial:
                        on_partial(partial)


def _pcm16_level(raw: bytes) -> float:
    if not raw:
        return 0.0
    count = len(raw) // 2
    if count <= 0:
        return 0.0
    try:
        samples = struct.unpack("<" + "h" * count, raw[: count * 2])
    except Exception:
        return 0.0
    if not samples:
        return 0.0
    rms = math.sqrt(sum(float(sample) * float(sample) for sample in samples) / len(samples))
    return max(0.0, min(1.0, rms / 9000.0))
