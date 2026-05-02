import asyncio
import math
import struct
import sys
import wave
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))


class FakeBusModule:
    def __init__(self):
        self.events = []
        self.processed = []

    async def submit_audio(self, payload, **kwargs):
        self.events.append({"payload": payload, "kwargs": kwargs})
        return SimpleNamespace(event_id=f"se_test_{len(self.events)}")

    async def process_pending(self, limit=None):
        item = {"ok": True, "limit": limit}
        self.processed.append(item)
        return [item]


def _write_wav(path: Path, samples, rate=16000):
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        frames = b"".join(struct.pack("<h", max(-32767, min(32767, int(sample * 32767)))) for sample in samples)
        wf.writeframes(frames)


def _tone_samples(seconds=0.6, rate=16000, hz=440.0, amp=0.25):
    total = int(seconds * rate)
    return [amp * math.sin(2 * math.pi * hz * i / rate) for i in range(total)]


def test_authorized_voice_command_transcribes_routes_chat_and_discards_raw(tmp_path):
    from ultronpro import audio_perception

    audio_path = tmp_path / "voice.wav"
    _write_wav(audio_path, _tone_samples())
    bus = FakeBusModule()

    async def run():
        return await audio_perception.handle_voice_command(
            audio_path,
            authorized=True,
            transcriber=lambda path, language="pt": {"text": "abrir painel", "engine": "unit_whisper"},
            speech_detector=lambda path: audio_perception.SpeechDetection(
                speech_detected=True,
                confidence=0.91,
                engine="unit_vad",
                segments=[{"start": 0.0, "end": 0.6, "duration": 0.6}],
                duration_sec=0.6,
                sample_rate=16000,
            ),
            chat_callback=lambda text: {"ok": True, "reply": f"Comando recebido: {text}", "strategy": "unit_chat"},
            bus_module=bus,
        )

    result = asyncio.run(run())

    assert result.ok is True
    assert result.transcript == "abrir painel"
    assert result.chat_response["reply"] == "Comando recebido: abrir painel"
    assert result.raw_audio_discarded is True
    assert not audio_path.exists()
    assert bus.events[0]["payload"]["raw_audio_retained"] is False
    assert bus.events[0]["payload"]["transcript"] == "abrir painel"
    assert bus.events[0]["kwargs"]["consent_scope"] == "explicit_capture"


def test_unauthorized_audio_never_calls_transcriber_and_registers_restricted_event(tmp_path):
    from ultronpro import audio_perception

    audio_path = tmp_path / "private.wav"
    _write_wav(audio_path, _tone_samples())
    bus = FakeBusModule()

    def forbidden_transcriber(*args, **kwargs):
        raise AssertionError("transcriber must not run without authorization")

    async def run():
        return await audio_perception.perceive_audio(
            audio_path,
            authorized=False,
            transcriber=forbidden_transcriber,
            speech_detector=lambda path: {"speech_detected": True, "confidence": 0.8, "engine": "unit_vad"},
            bus_module=bus,
        )

    result = asyncio.run(run())

    assert result.transcript == ""
    assert result.consent_scope == "restricted"
    assert result.raw_audio_discarded is True
    assert not audio_path.exists()
    assert bus.events[0]["payload"]["transcript"] == ""
    assert bus.events[0]["kwargs"]["allow_persist"] is False
    assert bus.events[0]["kwargs"]["allow_workspace"] is False


def test_sound_event_rules_classify_silence_and_impulse(tmp_path):
    from ultronpro import audio_perception

    silence_path = tmp_path / "silence.wav"
    impulse_path = tmp_path / "impulse.wav"
    _write_wav(silence_path, [0.0] * 8000)
    impulse = [0.0] * 8000
    impulse[1200] = 0.95
    _write_wav(impulse_path, impulse)

    silence = audio_perception.detect_sound_events(silence_path)
    impulse_events = audio_perception.detect_sound_events(impulse_path)
    impulse_labels = {event.label for event in impulse_events}

    assert silence[0].label == "silence"
    assert "sharp_impulse" in impulse_labels

