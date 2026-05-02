"""Privacy-first audio perception for UltronPro.

This module extracts short-lived audio into normalized events:
- speech detection, preferably via Silero VAD when available;
- local transcription only when explicitly authorized;
- simple sound-event classification by audio rules;
- context summaries suitable for the sensory bus;
- automatic raw-audio discard after event extraction.

Heavy audio dependencies are optional and loaded lazily so the backend can boot
without becoming a permanent recorder or requiring Whisper/Silero at import time.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import math
import os
import statistics
import tempfile
import time
import wave
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

try:
    from ultronpro import sensory_bus
except Exception:  # pragma: no cover - lets isolated tests import the module
    sensory_bus = None  # type: ignore[assignment]


RAW_AUDIO_DISCARD_POLICY = "discard_raw_after_event_extraction"
DEFAULT_LANGUAGE = os.getenv("ULTRON_AUDIO_LANGUAGE", "pt")
DEFAULT_WHISPER_MODEL = os.getenv("ULTRON_AUDIO_WHISPER_MODEL", "base")
DEFAULT_VAD_THRESHOLD = float(os.getenv("ULTRON_AUDIO_VAD_RMS_THRESHOLD", "0.012"))
MAX_FALLBACK_SECONDS = float(os.getenv("ULTRON_AUDIO_FALLBACK_MAX_SECONDS", "120"))

_FASTER_WHISPER_MODEL: Any = None
_WHISPER_MODEL: Any = None
_SILERO_MODEL: Any = None


@dataclass
class SpeechDetection:
    speech_detected: bool
    confidence: float
    engine: str
    segments: list[dict[str, float]] = field(default_factory=list)
    duration_sec: float = 0.0
    sample_rate: int | None = None
    rms: float | None = None
    peak: float | None = None
    reason: str = ""
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SoundEvent:
    label: str
    confidence: float
    start_sec: float = 0.0
    end_sec: float | None = None
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AudioPerceptionResult:
    ok: bool
    audio_id: str
    source: str
    authorized: bool
    consent_scope: str
    speech: SpeechDetection
    transcript: str = ""
    transcription: dict[str, Any] = field(default_factory=dict)
    sound_events: list[SoundEvent] = field(default_factory=list)
    summary: str = ""
    raw_audio_discarded: bool = False
    discard_result: dict[str, Any] = field(default_factory=dict)
    sensory_event_id: str | None = None
    bus_results: list[dict[str, Any]] = field(default_factory=list)
    chat_response: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["speech"] = self.speech.to_dict()
        data["sound_events"] = [event.to_dict() for event in self.sound_events]
        return data


def _clip01(value: float) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except Exception:
        return 0.0


def _audio_id(path: Path) -> str:
    raw = f"{path.resolve()}:{time.time_ns()}".encode("utf-8", errors="ignore")
    return "aud_" + hashlib.sha256(raw).hexdigest()[:16]


def _path_hash(path: Path) -> str:
    try:
        raw = str(path.resolve()).encode("utf-8", errors="ignore")
    except Exception:
        raw = str(path).encode("utf-8", errors="ignore")
    return hashlib.sha256(raw).hexdigest()[:16]


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _read_wav_mono_float(path: str | Path, max_seconds: float = MAX_FALLBACK_SECONDS) -> tuple[list[float], int, float]:
    """Read a PCM WAV file into mono float samples for fallback rules."""
    p = Path(path)
    with wave.open(str(p), "rb") as wf:
        channels = max(1, int(wf.getnchannels()))
        sample_rate = int(wf.getframerate())
        sample_width = int(wf.getsampwidth())
        frame_count = int(wf.getnframes())
        if sample_rate <= 0:
            raise ValueError("invalid sample rate")
        limit = min(frame_count, int(sample_rate * max(0.1, max_seconds)))
        raw = wf.readframes(limit)

    if not raw:
        return [], sample_rate, 0.0

    if sample_width == 1:
        values = [(byte - 128) / 128.0 for byte in raw]
    elif sample_width == 2:
        values = [
            int.from_bytes(raw[i : i + 2], "little", signed=True) / 32768.0
            for i in range(0, len(raw) - 1, 2)
        ]
    elif sample_width == 3:
        values = [
            int.from_bytes(raw[i : i + 3], "little", signed=True) / 8388608.0
            for i in range(0, len(raw) - 2, 3)
        ]
    elif sample_width == 4:
        values = [
            int.from_bytes(raw[i : i + 4], "little", signed=True) / 2147483648.0
            for i in range(0, len(raw) - 3, 4)
        ]
    else:
        raise ValueError(f"unsupported WAV sample width: {sample_width}")

    if channels == 1:
        samples = values
    else:
        samples = []
        for idx in range(0, len(values), channels):
            frame = values[idx : idx + channels]
            if frame:
                samples.append(sum(frame) / len(frame))

    duration = len(samples) / float(sample_rate)
    return samples, sample_rate, duration


def _rms(samples: list[float]) -> float:
    if not samples:
        return 0.0
    return math.sqrt(sum(sample * sample for sample in samples) / len(samples))


def _zero_crossing_rate(samples: list[float]) -> float:
    if len(samples) < 2:
        return 0.0
    crossings = 0
    prev = samples[0]
    for sample in samples[1:]:
        if (prev < 0 <= sample) or (prev >= 0 > sample):
            crossings += 1
        prev = sample
    return crossings / max(1, len(samples) - 1)


def _frame_features(samples: list[float], sample_rate: int, frame_ms: int = 30) -> list[dict[str, float]]:
    frame_size = max(1, int(sample_rate * frame_ms / 1000))
    frames: list[dict[str, float]] = []
    for offset in range(0, len(samples), frame_size):
        frame = samples[offset : offset + frame_size]
        if not frame:
            continue
        start = offset / float(sample_rate)
        end = (offset + len(frame)) / float(sample_rate)
        frames.append({
            "start": start,
            "end": end,
            "rms": _rms(frame),
            "peak": max(abs(sample) for sample in frame),
            "zcr": _zero_crossing_rate(frame),
        })
    return frames


def _merge_voiced_frames(frames: list[dict[str, float]]) -> list[dict[str, float]]:
    segments: list[dict[str, float]] = []
    current: dict[str, float] | None = None
    for frame in frames:
        if current is None:
            current = {"start": frame["start"], "end": frame["end"]}
            continue
        gap = frame["start"] - current["end"]
        if gap <= 0.12:
            current["end"] = frame["end"]
        else:
            segments.append(current)
            current = {"start": frame["start"], "end": frame["end"]}
    if current is not None:
        segments.append(current)
    for segment in segments:
        segment["duration"] = max(0.0, segment["end"] - segment["start"])
    return segments


def _detect_speech_silero(path: Path, vad_model: Any | None = None) -> SpeechDetection | None:
    global _SILERO_MODEL

    try:
        from silero_vad import get_speech_timestamps, load_silero_vad, read_audio  # type: ignore

        model = vad_model or _SILERO_MODEL or load_silero_vad()
        _SILERO_MODEL = model
        wav = read_audio(str(path), sampling_rate=16000)
        timestamps = get_speech_timestamps(wav, model, sampling_rate=16000)
    except ImportError:
        if os.getenv("ULTRON_AUDIO_ALLOW_TORCH_HUB", "0").lower() not in {"1", "true", "yes", "on"}:
            return None
        try:
            import torch  # type: ignore

            model, utils = torch.hub.load(
                repo_or_dir="snakers4/silero-vad",
                model="silero_vad",
                trust_repo=True,
                onnx=False,
            )
            get_speech_timestamps, _, read_audio, _, _ = utils
            _SILERO_MODEL = vad_model or model
            wav = read_audio(str(path), sampling_rate=16000)
            timestamps = get_speech_timestamps(wav, vad_model or model, sampling_rate=16000)
        except Exception as exc:
            return SpeechDetection(
                speech_detected=False,
                confidence=0.0,
                engine="silero_vad",
                reason="silero_unavailable",
                error=f"{type(exc).__name__}: {str(exc)[:180]}",
            )
    except Exception as exc:
        return SpeechDetection(
            speech_detected=False,
            confidence=0.0,
            engine="silero_vad",
            reason="silero_failed",
            error=f"{type(exc).__name__}: {str(exc)[:180]}",
        )

    segments: list[dict[str, float]] = []
    for item in timestamps:
        start = _safe_float(item.get("start")) / 16000.0
        end = _safe_float(item.get("end")) / 16000.0
        segments.append({"start": start, "end": end, "duration": max(0.0, end - start)})

    voiced = sum(segment["duration"] for segment in segments)
    duration = 0.0
    try:
        duration = len(wav) / 16000.0
    except Exception:
        duration = segments[-1]["end"] if segments else 0.0
    confidence = _clip01(0.55 + min(0.4, voiced / max(1.0, duration))) if segments else 0.05
    return SpeechDetection(
        speech_detected=bool(segments),
        confidence=confidence,
        engine="silero_vad",
        segments=segments,
        duration_sec=duration,
        sample_rate=16000,
        reason="silero_vad",
    )


def detect_speech(
    audio_path: str | Path,
    *,
    use_silero: bool = True,
    vad_model: Any | None = None,
    threshold: float = DEFAULT_VAD_THRESHOLD,
    min_speech_sec: float = 0.25,
) -> SpeechDetection:
    """Detect whether an audio file contains speech.

    Silero VAD is preferred when installed. The fallback supports PCM WAV and
    uses frame energy plus variability so non-speech tones are less likely to be
    treated as spoken commands.
    """
    path = Path(audio_path)
    if use_silero:
        silero = _detect_speech_silero(path, vad_model=vad_model)
        if silero is not None and (silero.error is None or silero.speech_detected):
            return silero

    try:
        samples, sample_rate, duration = _read_wav_mono_float(path)
    except Exception as exc:
        return SpeechDetection(
            speech_detected=False,
            confidence=0.0,
            engine="fallback_wav_energy",
            reason="wav_decode_failed",
            error=f"{type(exc).__name__}: {str(exc)[:180]}",
        )

    frames = _frame_features(samples, sample_rate)
    if not frames:
        return SpeechDetection(
            speech_detected=False,
            confidence=0.0,
            engine="fallback_wav_energy",
            duration_sec=duration,
            sample_rate=sample_rate,
            reason="empty_audio",
        )

    voiced_frames = [frame for frame in frames if frame["rms"] >= threshold and frame["peak"] >= threshold * 2.5]
    segments = _merge_voiced_frames(voiced_frames)
    voiced_duration = sum(segment["duration"] for segment in segments)
    rms_values = [frame["rms"] for frame in voiced_frames] or [0.0]
    mean_rms = statistics.fmean(rms_values)
    variability = statistics.pstdev(rms_values) / max(mean_rms, 1e-6) if len(rms_values) > 1 else 0.0
    mean_zcr = statistics.fmean(frame["zcr"] for frame in voiced_frames) if voiced_frames else 0.0
    peak = max(frame["peak"] for frame in frames)
    total_rms = _rms(samples)

    enough_voice = voiced_duration >= min_speech_sec
    voice_like = variability >= 0.08 or (0.015 <= mean_zcr <= 0.24 and voiced_duration >= 0.55)
    speech_detected = bool(enough_voice and voice_like)
    coverage = voiced_duration / max(duration, 0.001)
    confidence = _clip01(0.15 + coverage * 0.65 + min(0.2, variability * 0.25))
    if not speech_detected:
        confidence = min(confidence, 0.45)

    return SpeechDetection(
        speech_detected=speech_detected,
        confidence=confidence,
        engine="fallback_wav_energy",
        segments=segments if speech_detected else [],
        duration_sec=duration,
        sample_rate=sample_rate,
        rms=total_rms,
        peak=peak,
        reason="energy_variability_rule",
    )


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


async def _call_transcriber(transcriber: Callable[..., Any], path: Path, language: str) -> dict[str, Any]:
    try:
        raw = transcriber(str(path), language=language)
    except TypeError:
        raw = transcriber(str(path))
    raw = await _maybe_await(raw)
    if isinstance(raw, dict):
        text = str(raw.get("text") or raw.get("transcript") or "").strip()
        return {"ok": bool(text), "text": text, "engine": str(raw.get("engine") or "custom_transcriber"), "raw": raw}
    text = str(raw or "").strip()
    return {"ok": bool(text), "text": text, "engine": "custom_transcriber"}


def _get_faster_whisper_model(model_name: str) -> Any:
    global _FASTER_WHISPER_MODEL
    if _FASTER_WHISPER_MODEL is None:
        from faster_whisper import WhisperModel  # type: ignore

        compute_type = os.getenv("ULTRON_AUDIO_WHISPER_COMPUTE_TYPE", "int8")
        device = os.getenv("ULTRON_AUDIO_WHISPER_DEVICE", "auto")
        _FASTER_WHISPER_MODEL = WhisperModel(model_name, device=device, compute_type=compute_type)
    return _FASTER_WHISPER_MODEL


def _transcribe_with_faster_whisper(path: Path, language: str, model_name: str) -> dict[str, Any]:
    model = _get_faster_whisper_model(model_name)
    segments, info = model.transcribe(str(path), language=language, vad_filter=True)
    text = " ".join(segment.text.strip() for segment in segments if getattr(segment, "text", "").strip()).strip()
    return {
        "ok": bool(text),
        "text": text,
        "engine": "faster_whisper",
        "language": getattr(info, "language", language),
        "language_probability": getattr(info, "language_probability", None),
    }


def _get_whisper_model(model_name: str) -> Any:
    global _WHISPER_MODEL
    if _WHISPER_MODEL is None:
        import whisper  # type: ignore

        _WHISPER_MODEL = whisper.load_model(model_name)
    return _WHISPER_MODEL


def _transcribe_with_whisper(path: Path, language: str, model_name: str) -> dict[str, Any]:
    model = _get_whisper_model(model_name)
    result = model.transcribe(str(path), language=language)
    text = str(result.get("text") or "").strip()
    return {"ok": bool(text), "text": text, "engine": "whisper", "language": result.get("language", language)}


async def transcribe_audio_authorized(
    audio_path: str | Path,
    *,
    authorized: bool,
    transcriber: Callable[..., Any] | None = None,
    language: str = DEFAULT_LANGUAGE,
    model_name: str = DEFAULT_WHISPER_MODEL,
) -> dict[str, Any]:
    """Transcribe audio only when explicit authorization is present."""
    path = Path(audio_path)
    if not authorized:
        return {
            "ok": False,
            "text": "",
            "engine": "authorization_gate",
            "reason": "transcription_not_authorized",
        }

    if transcriber is not None:
        try:
            return await _call_transcriber(transcriber, path, language)
        except Exception as exc:
            return {
                "ok": False,
                "text": "",
                "engine": "custom_transcriber",
                "reason": "custom_transcriber_failed",
                "error": f"{type(exc).__name__}: {str(exc)[:180]}",
            }

    try:
        return await asyncio.to_thread(_transcribe_with_faster_whisper, path, language, model_name)
    except ImportError:
        pass
    except Exception as exc:
        faster_error = f"{type(exc).__name__}: {str(exc)[:180]}"
    else:  # pragma: no cover - kept for readability
        faster_error = ""

    try:
        return await asyncio.to_thread(_transcribe_with_whisper, path, language, model_name)
    except ImportError:
        whisper_error = "local whisper package not installed"
    except Exception as exc:
        whisper_error = f"{type(exc).__name__}: {str(exc)[:180]}"

    return {
        "ok": False,
        "text": "",
        "engine": "no_local_transcriber",
        "reason": "install faster-whisper or whisper, or pass a transcriber callback",
        "errors": [err for err in [locals().get("faster_error"), whisper_error] if err],
    }


def detect_sound_events(
    audio_path: str | Path,
    *,
    speech: SpeechDetection | None = None,
    silence_threshold: float = 0.003,
) -> list[SoundEvent]:
    """Classify simple sound events with deterministic rules."""
    path = Path(audio_path)
    try:
        samples, sample_rate, duration = _read_wav_mono_float(path)
    except Exception as exc:
        return [
            SoundEvent(
                label="audio_unclassified",
                confidence=0.15,
                evidence={"reason": "wav_decode_failed", "error": f"{type(exc).__name__}: {str(exc)[:120]}"},
            )
        ]

    if not samples:
        return [SoundEvent(label="silence", confidence=0.9, evidence={"reason": "empty_audio"})]

    frames = _frame_features(samples, sample_rate)
    total_rms = _rms(samples)
    peak = max(abs(sample) for sample in samples)
    mean_zcr = statistics.fmean(frame["zcr"] for frame in frames) if frames else 0.0
    frame_rms = [frame["rms"] for frame in frames] or [0.0]
    rms_std = statistics.pstdev(frame_rms) if len(frame_rms) > 1 else 0.0
    high_frames = [frame for frame in frames if frame["peak"] > 0.55]
    events: list[SoundEvent] = []

    if total_rms < silence_threshold and peak < silence_threshold * 4:
        return [
            SoundEvent(
                label="silence",
                confidence=0.92,
                end_sec=duration,
                evidence={"rms": total_rms, "peak": peak},
            )
        ]

    if speech and speech.speech_detected:
        events.append(
            SoundEvent(
                label="speech",
                confidence=max(0.55, speech.confidence),
                end_sec=duration,
                evidence={"engine": speech.engine, "segments": len(speech.segments)},
            )
        )

    if peak > 0.80 or total_rms > 0.22:
        events.append(
            SoundEvent(
                label="loud_sound",
                confidence=_clip01(0.55 + max(peak - 0.55, total_rms)),
                end_sec=duration,
                evidence={"rms": total_rms, "peak": peak},
            )
        )

    if high_frames and len(high_frames) <= max(3, int(len(frames) * 0.12)) and peak / max(total_rms, 1e-6) > 5.0:
        events.append(
            SoundEvent(
                label="sharp_impulse",
                confidence=0.72,
                start_sec=high_frames[0]["start"],
                end_sec=high_frames[-1]["end"],
                evidence={"peak": peak, "high_frames": len(high_frames), "total_frames": len(frames)},
            )
        )

    steady_energy = rms_std / max(statistics.fmean(frame_rms), 1e-6) < 0.18 if frame_rms else False
    if duration >= 0.25 and mean_zcr >= 0.04 and steady_energy and not (speech and speech.speech_detected):
        events.append(
            SoundEvent(
                label="tonal_beep_or_alarm",
                confidence=0.58,
                end_sec=duration,
                evidence={"mean_zcr": mean_zcr, "rms_stability": steady_energy},
            )
        )

    if not events:
        events.append(
            SoundEvent(
                label="ambient_audio",
                confidence=0.45,
                end_sec=duration,
                evidence={"rms": total_rms, "peak": peak, "mean_zcr": mean_zcr},
            )
        )

    return events


def summarize_context(
    *,
    transcript: str = "",
    speech: SpeechDetection | None = None,
    sound_events: list[SoundEvent] | list[dict[str, Any]] | None = None,
    authorized: bool = False,
    source: str = "microphone",
) -> str:
    """Create a compact text summary for memory and workspace publication."""
    labels: list[str] = []
    for event in sound_events or []:
        label = event.label if isinstance(event, SoundEvent) else str(event.get("label") or "")
        if label:
            labels.append(label)

    clean_transcript = str(transcript or "").strip()
    if clean_transcript:
        base = f"Audio command from {source}: {clean_transcript[:500]}"
    elif speech and speech.speech_detected and authorized:
        base = f"Speech was detected from {source}, but no transcript was produced."
    elif speech and speech.speech_detected:
        base = f"Speech-like audio was detected from {source}; transcription was not authorized."
    else:
        base = f"Audio observed from {source} without a clear speech command."

    if labels:
        base += " Sound events: " + ", ".join(dict.fromkeys(labels)) + "."
    return base[:900]


def discard_raw_audio(audio_path: str | Path, *, reason: str = RAW_AUDIO_DISCARD_POLICY) -> dict[str, Any]:
    """Delete raw audio after extracting events/transcript."""
    path = Path(audio_path)
    try:
        size = path.stat().st_size if path.exists() else 0
        if path.exists():
            path.unlink()
        return {
            "discarded": True,
            "path_hash": _path_hash(path),
            "bytes": size,
            "policy": RAW_AUDIO_DISCARD_POLICY,
            "reason": reason,
        }
    except Exception as exc:
        return {
            "discarded": False,
            "path_hash": _path_hash(path),
            "policy": RAW_AUDIO_DISCARD_POLICY,
            "reason": reason,
            "error": f"{type(exc).__name__}: {str(exc)[:180]}",
        }


async def _call_detector(detector: Callable[..., Any], path: Path) -> SpeechDetection:
    raw = detector(str(path))
    raw = await _maybe_await(raw)
    if isinstance(raw, SpeechDetection):
        return raw
    if isinstance(raw, dict):
        return SpeechDetection(
            speech_detected=bool(raw.get("speech_detected")),
            confidence=_clip01(raw.get("confidence", 0.0)),
            engine=str(raw.get("engine") or "custom_detector"),
            segments=list(raw.get("segments") or []),
            duration_sec=_safe_float(raw.get("duration_sec")),
            sample_rate=raw.get("sample_rate"),
            rms=raw.get("rms"),
            peak=raw.get("peak"),
            reason=str(raw.get("reason") or ""),
            error=raw.get("error"),
        )
    return SpeechDetection(bool(raw), 0.5 if raw else 0.0, "custom_detector")


async def _submit_audio_event(
    *,
    bus_module: Any,
    payload: dict[str, Any],
    content_text: str,
    source: str,
    consent_scope: str,
    consent_basis: str,
    consent_actor: str,
    allow_persist: bool,
    allow_workspace: bool,
    salience: float,
    process_bus: bool,
) -> tuple[str | None, list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    if bus_module is None:
        return None, [], ["sensory_bus_unavailable"]

    try:
        event = await bus_module.submit_audio(
            payload,
            source=source,
            content_text=content_text,
            metadata={
                "mime": payload.get("mime") or "",
                "audio_id": payload.get("audio_id"),
                "raw_audio_policy": RAW_AUDIO_DISCARD_POLICY,
                "raw_audio_retained": False,
            },
            consent_scope=consent_scope,
            consent_basis=consent_basis,
            consent_actor=consent_actor,
            allow_persist=allow_persist,
            allow_workspace=allow_workspace,
            retention_policy=RAW_AUDIO_DISCARD_POLICY,
            sensitivity="high" if payload.get("transcript") else "normal",
            salience=salience,
        )
        event_id = getattr(event, "event_id", None)
    except Exception as exc:
        return None, [], [f"sensory_submit_failed:{type(exc).__name__}:{str(exc)[:160]}"]

    bus_results: list[dict[str, Any]] = []
    if process_bus and hasattr(bus_module, "process_pending"):
        try:
            bus_results = await bus_module.process_pending(limit=1)
        except Exception as exc:
            errors.append(f"sensory_process_failed:{type(exc).__name__}:{str(exc)[:160]}")
    return event_id, bus_results, errors


async def perceive_audio(
    audio_path: str | Path,
    *,
    authorized: bool,
    source: str = "microphone",
    consent_scope: str | None = None,
    consent_basis: str | None = None,
    consent_actor: str = "user",
    allow_persist: bool | None = None,
    allow_workspace: bool | None = None,
    discard_raw: bool = True,
    language: str = DEFAULT_LANGUAGE,
    transcriber: Callable[..., Any] | None = None,
    speech_detector: Callable[..., Any] | None = None,
    bus_module: Any = None,
    process_bus: bool = True,
) -> AudioPerceptionResult:
    """Extract an audio file into auditable events, then discard raw audio."""
    path = Path(audio_path)
    audio_id = _audio_id(path)
    scope = str(consent_scope or ("explicit_capture" if authorized else "restricted")).strip().lower()
    persist = bool(authorized) if allow_persist is None else bool(allow_persist)
    workspace = bool(authorized and scope != "restricted") if allow_workspace is None else bool(allow_workspace)
    basis = consent_basis or ("explicit user voice capture" if authorized else "audio observed without transcription authorization")
    errors: list[str] = []
    discard_result: dict[str, Any] = {"discarded": False, "policy": RAW_AUDIO_DISCARD_POLICY}

    speech = SpeechDetection(False, 0.0, "not_run", reason="not_run")
    sound_events: list[SoundEvent] = []
    transcription: dict[str, Any] = {"ok": False, "text": "", "engine": "not_run"}
    transcript = ""
    summary = ""

    try:
        if speech_detector is not None:
            speech = await _call_detector(speech_detector, path)
        else:
            speech = await asyncio.to_thread(detect_speech, path)

        sound_events = await asyncio.to_thread(detect_sound_events, path, speech=speech)

        decode_unknown = speech.reason == "wav_decode_failed"
        if speech.speech_detected or (authorized and decode_unknown):
            transcription = await transcribe_audio_authorized(
                path,
                authorized=authorized,
                transcriber=transcriber,
                language=language,
            )
            transcript = str(transcription.get("text") or "").strip() if authorized else ""
        else:
            transcription = {
                "ok": False,
                "text": "",
                "engine": "speech_gate",
                "reason": "no_speech_detected",
            }

        summary = summarize_context(
            transcript=transcript,
            speech=speech,
            sound_events=sound_events,
            authorized=authorized,
            source=source,
        )
    except Exception as exc:
        errors.append(f"audio_perception_failed:{type(exc).__name__}:{str(exc)[:180]}")
        summary = f"Audio from {source} could not be fully processed."
    finally:
        if discard_raw:
            discard_result = discard_raw_audio(path)

    payload = {
        "audio_id": audio_id,
        "source": source,
        "source_path_hash": _path_hash(path),
        "authorized": bool(authorized),
        "consent_scope": scope,
        "speech": speech.to_dict(),
        "transcript": transcript if authorized else "",
        "transcription": {k: v for k, v in transcription.items() if k != "raw"},
        "sound_events": [event.to_dict() for event in sound_events],
        "summary": summary,
        "raw_audio_policy": RAW_AUDIO_DISCARD_POLICY,
        "raw_audio_discarded": bool(discard_result.get("discarded")),
        "raw_audio_retained": False,
        "mime": "audio/wav" if path.suffix.lower() == ".wav" else "",
    }

    salience = 0.68 if transcript else (0.55 if speech.speech_detected else 0.4)
    event_id, bus_results, bus_errors = await _submit_audio_event(
        bus_module=bus_module if bus_module is not None else sensory_bus,
        payload=payload,
        content_text=summary,
        source=source,
        consent_scope=scope,
        consent_basis=basis,
        consent_actor=consent_actor,
        allow_persist=persist,
        allow_workspace=workspace and scope != "restricted",
        salience=salience,
        process_bus=process_bus,
    )
    errors.extend(bus_errors)

    return AudioPerceptionResult(
        ok=not errors,
        audio_id=audio_id,
        source=source,
        authorized=bool(authorized),
        consent_scope=scope,
        speech=speech,
        transcript=transcript,
        transcription=transcription,
        sound_events=sound_events,
        summary=summary,
        raw_audio_discarded=bool(discard_result.get("discarded")),
        discard_result=discard_result,
        sensory_event_id=event_id,
        bus_results=bus_results,
        errors=errors,
    )


async def _default_voice_chat_callback(text: str) -> dict[str, Any]:
    from ultronpro.api.schemas import VoiceChatRequest
    from ultronpro.main import voice_chat

    return await voice_chat(VoiceChatRequest(text=text))


def _extract_chat_reply(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return {
            "ok": bool(raw.get("ok", True)),
            "reply": str(raw.get("reply") or raw.get("answer") or raw.get("text") or "").strip(),
            "strategy": str(raw.get("strategy") or "chat_callback"),
            "raw": raw,
        }
    return {"ok": bool(str(raw or "").strip()), "reply": str(raw or "").strip(), "strategy": "chat_callback"}


async def handle_voice_command(
    audio_path: str | Path,
    *,
    authorized: bool,
    chat_callback: Callable[..., Any] | None = None,
    source: str = "microphone",
    consent_scope: str | None = None,
    consent_basis: str | None = None,
    consent_actor: str = "user",
    discard_raw: bool = True,
    language: str = DEFAULT_LANGUAGE,
    transcriber: Callable[..., Any] | None = None,
    speech_detector: Callable[..., Any] | None = None,
    bus_module: Any = None,
    process_bus: bool = True,
) -> AudioPerceptionResult:
    """Turn authorized voice audio into a chat reply and sensory event."""
    result = await perceive_audio(
        audio_path,
        authorized=authorized,
        source=source,
        consent_scope=consent_scope,
        consent_basis=consent_basis,
        consent_actor=consent_actor,
        discard_raw=discard_raw,
        language=language,
        transcriber=transcriber,
        speech_detector=speech_detector,
        bus_module=bus_module,
        process_bus=process_bus,
    )

    if not authorized:
        result.chat_response = {
            "ok": False,
            "reply": "Nao transcrevi porque a captura nao foi autorizada.",
            "strategy": "authorization_gate",
        }
        return result

    transcript = result.transcript.strip()
    if not transcript:
        result.chat_response = {
            "ok": False,
            "reply": "Nao ouvi um comando claro. Pode repetir em uma frase curta?",
            "strategy": "no_transcript",
        }
        return result

    callback = chat_callback or _default_voice_chat_callback
    try:
        try:
            raw_reply = callback(transcript)
        except TypeError:
            raw_reply = callback(text=transcript)
        result.chat_response = _extract_chat_reply(await _maybe_await(raw_reply))
    except Exception as exc:
        result.errors.append(f"voice_chat_failed:{type(exc).__name__}:{str(exc)[:180]}")
        result.ok = False
        result.chat_response = {
            "ok": False,
            "reply": "Transcrevi o comando, mas o chat nao respondeu agora.",
            "strategy": "chat_error",
        }
    return result


def copy_upload_to_temp(raw: bytes, *, suffix: str = ".wav") -> Path:
    """Create a short-lived temp audio file for perception pipelines."""
    suffix = suffix if suffix.startswith(".") and len(suffix) <= 12 else ".wav"
    with tempfile.NamedTemporaryFile(prefix="ultron_audio_", suffix=suffix, delete=False) as tmp:
        tmp.write(raw)
        return Path(tmp.name)


# Portuguese aliases for callers that prefer the product wording.
detectar_fala = detect_speech
transcrever_audio_autorizado = transcribe_audio_authorized
detectar_eventos_sonoros = detect_sound_events
resumir_contexto = summarize_context
descartar_audio_bruto = discard_raw_audio
