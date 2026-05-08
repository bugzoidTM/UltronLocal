from __future__ import annotations

import os
import queue
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Callable

from . import paths


class PiperSpeaker:
    def __init__(
        self,
        *,
        executable: Path | None = None,
        voice: Path | None = None,
        status_callback: Callable[[str], None] | None = None,
    ) -> None:
        self.executable = executable or paths.piper_exe_path()
        self.voice = voice or paths.piper_voice_path()
        self.status_callback = status_callback
        self._lock = threading.Lock()
        self._queue: queue.Queue[str | None] = queue.Queue(maxsize=2)
        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker.start()

    def available(self) -> bool:
        return self.executable.exists() and self.voice.exists()

    def speak_async(self, text: str) -> None:
        phrase = str(text or "").strip()
        if not phrase:
            return
        while self._queue.full():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
        try:
            self._queue.put_nowait(phrase)
        except queue.Full:
            pass

    def _worker_loop(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                return
            self.speak(item)

    def speak(self, text: str) -> bool:
        phrase = str(text or "").strip()
        if not phrase:
            return False
        phrase = _speech_text(phrase)
        if not self.available():
            self._status("Piper TTS não encontrado; fala pulada.")
            return False
        with self._lock:
            try:
                out_dir = paths.tmp_dir() / "tts"
                out_dir.mkdir(parents=True, exist_ok=True)
                fd, wav_name = tempfile.mkstemp(prefix="ultron-ui-", suffix=".wav", dir=str(out_dir))
                os.close(fd)
                wav_path = Path(wav_name)
                cmd = [
                    str(self.executable),
                    "--model",
                    str(self.voice),
                    "--output_file",
                    str(wav_path),
                ]
                proc = subprocess.run(
                    cmd,
                    input=phrase,
                    text=True,
                    capture_output=True,
                    timeout=_tts_timeout(phrase),
                )
                if proc.returncode != 0:
                    self._status((proc.stderr or proc.stdout or "Falha no Piper TTS.")[:240])
                    return False
                self._play_wav(wav_path)
                return True
            except Exception as exc:
                self._status(f"Erro TTS: {type(exc).__name__}: {str(exc)[:160]}")
                return False

    def _play_wav(self, path: Path) -> None:
        if os.name == "nt":
            import winsound

            winsound.PlaySound(str(path), winsound.SND_FILENAME)
            return
        player = os.getenv("ULTRON_UI_AUDIO_PLAYER", "").strip()
        if player:
            subprocess.run([player, str(path)], timeout=30)
            return
        subprocess.run(["aplay", str(path)], timeout=30)

    def _status(self, message: str) -> None:
        if self.status_callback:
            try:
                self.status_callback(str(message))
            except Exception:
                pass


def _speech_text(text: str) -> str:
    value = " ".join(str(text or "").strip().split())
    max_chars = int(os.getenv("ULTRON_UI_TTS_MAX_CHARS", "240") or 240)
    if len(value) > max_chars:
        value = value[: max_chars - 1].rstrip() + "."
    return value


def _tts_timeout(text: str) -> float:
    base = float(os.getenv("ULTRON_UI_TTS_TIMEOUT_SEC", "45") or 45)
    dynamic = 12.0 + (len(str(text or "")) / 7.5)
    return max(base, min(90.0, dynamic))
