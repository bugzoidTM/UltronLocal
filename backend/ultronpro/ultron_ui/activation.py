from __future__ import annotations

import hashlib
import hmac
import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable


_KEYWORD_SALT_HEX = "f6a9421915c20ce3453ee746449dd6c7"
_KEYWORD_HASH_HEX = "782b4b847367dfb526b9a7caf4851ad7e0bb7471db7c1b375252f5ac2dfabbe7"
_PBKDF2_ROUNDS = 200_000
_WAKE_HINT_XOR_HEX = "4559544c575a4c4f5c5b5d5a"
_WAKE_HINT_XOR_KEY = 0x35


def wake_phrase_hint() -> str:
    """Runtime-only phrase hint for the recognizer; security remains PBKDF2 based."""
    raw = bytes.fromhex(_WAKE_HINT_XOR_HEX)
    return "".join(chr(byte ^ _WAKE_HINT_XOR_KEY) for byte in raw)


def wake_phrase_variants() -> list[str]:
    hint = wake_phrase_hint()
    return [
        hint,
        f"{hint[:4]} {hint[4:]}",
        f"{hint[:7]} {hint[7:]}",
        f"{hint[:4]} {hint[4:7]} {hint[7:]}",
        f"{hint[:4]} {hint[4:7]}zinho",
    ]


def normalize_keyword_candidate(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(text or "").strip().lower())
    ascii_text = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", "", ascii_text)


def _keyword_digest(candidate: str) -> bytes:
    clean = normalize_keyword_candidate(candidate)
    salt = bytes.fromhex(_KEYWORD_SALT_HEX)
    return hashlib.pbkdf2_hmac("sha256", clean.encode("utf-8"), salt, _PBKDF2_ROUNDS)


def verify_keyword_candidate(candidate: str) -> bool:
    clean = normalize_keyword_candidate(candidate)
    if not clean:
        return False
    expected = bytes.fromhex(_KEYWORD_HASH_HEX)
    return hmac.compare_digest(_keyword_digest(clean), expected)


def keyword_candidates(transcript: str) -> Iterable[str]:
    text = str(transcript or "").strip().lower()
    if not text:
        return []
    tokens = re.findall(r"[\wÀ-ÿ]+", text, flags=re.UNICODE)
    out: list[str] = [text]
    for size in range(1, min(4, len(tokens)) + 1):
        for idx in range(0, len(tokens) - size + 1):
            out.append(" ".join(tokens[idx : idx + size]))
    return out


def transcript_has_keyword(transcript: str) -> bool:
    for candidate in keyword_candidates(transcript):
        if verify_keyword_candidate(candidate):
            return True
        if _looks_like_wakeword_transcription(candidate):
            return True
    return False


def _looks_like_wakeword_transcription(candidate: str) -> bool:
    clean = normalize_keyword_candidate(candidate)
    if len(clean) < 8:
        return False
    expected = normalize_keyword_candidate(wake_phrase_hint())
    direct_distance = _levenshtein(clean, expected)
    if direct_distance <= 2 and abs(len(clean) - len(expected)) <= 2:
        return True

    phonetic = _wake_phonetic(clean)
    expected_phonetic = _wake_phonetic(expected)
    distance = _levenshtein(phonetic, expected_phonetic)
    max_distance = 3 if len(phonetic) >= 10 else 2
    return distance <= max_distance and ("play" in phonetic or "plei" in clean)


def _wake_phonetic(text: str) -> str:
    out = normalize_keyword_candidate(text)
    replacements = (
        ("plei", "play"),
        ("pley", "play"),
        ("ple", "play"),
        ("boi", "boy"),
        ("boiz", "boyz"),
        ("sinho", "zinho"),
        ("cinho", "zinho"),
        ("zinho", "zinho"),
        ("zino", "zinho"),
        ("sino", "zinho"),
    )
    for src, dst in replacements:
        out = out.replace(src, dst)
    return out


def _levenshtein(left: str, right: str) -> int:
    if left == right:
        return 0
    if not left:
        return len(right)
    if not right:
        return len(left)
    prev = list(range(len(right) + 1))
    for i, lc in enumerate(left, start=1):
        cur = [i]
        for j, rc in enumerate(right, start=1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (0 if lc == rc else 1)))
        prev = cur
    return prev[-1]


@dataclass
class ActivationResult:
    state: str
    message: str
    denied_attempts: int


class ActivationGate:
    def __init__(self, *, max_denied_attempts: int = 3) -> None:
        self.max_denied_attempts = max(1, int(max_denied_attempts))
        self.denied_attempts = 0
        self.activated = False

    def handle_transcript(self, transcript: str) -> ActivationResult:
        if self.activated:
            return ActivationResult("already_active", "Acesso já autorizado.", self.denied_attempts)
        if transcript_has_keyword(transcript):
            self.activated = True
            self.denied_attempts = 0
            return ActivationResult("activated", "Acesso autorizado.", self.denied_attempts)

        self.denied_attempts += 1
        if self.denied_attempts > self.max_denied_attempts:
            return ActivationResult("lockout", "Você não é a mamãe!", self.denied_attempts)
        return ActivationResult("denied", "Acesso negado!", self.denied_attempts)
