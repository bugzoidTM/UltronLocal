"""Entropy-aware compression utilities for UltronPro.

Inspired by Crompressor's practical routing rules:
- sample data before compressing;
- bypass data that is already compressed or high entropy;
- keep lossless archive semantics for internal state;
- expose lightweight metrics so external behavior can be tested.
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import json
import math
import os
import time
from dataclasses import dataclass
from typing import Any, Iterable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


ENVELOPE_PREFIX = "ULTRONC1:"
DEFAULT_MIN_BYTES = int(os.getenv("ULTRON_COMPRESSION_MIN_BYTES", "1024") or 1024)
DEFAULT_MAX_HTTP_BYTES = int(os.getenv("ULTRON_HTTP_COMPRESSION_MAX_BYTES", str(4 * 1024 * 1024)) or (4 * 1024 * 1024))
DEFAULT_ENTROPY_BYPASS = float(os.getenv("ULTRON_COMPRESSION_ENTROPY_BYPASS", "7.75") or 7.75)
DEFAULT_MIN_GAIN = float(os.getenv("ULTRON_COMPRESSION_MIN_GAIN", "0.08") or 0.08)

COMPRESSED_MAGIC = (
    b"\x1f\x8b",  # gzip
    b"PK\x03\x04",  # zip/jar/docx/xlsx
    b"\x89PNG",
    b"\xff\xd8\xff",  # jpeg
    b"GIF8",
    b"RIFF",  # webp/wav/avi; usually avoid blind recompression
    b"7z\xbc\xaf\x27\x1c",
    b"\xfd7zXZ",
    b"\x28\xb5\x2f\xfd",  # zstd
    b"BZh",
)

HTTP_COMPRESSIBLE_TYPES = (
    "application/json",
    "application/problem+json",
    "application/javascript",
    "application/xml",
    "text/",
)

HTTP_BYPASS_TYPES = (
    "text/event-stream",
    "image/",
    "audio/",
    "video/",
    "application/octet-stream",
    "application/zip",
    "application/gzip",
    "application/x-gzip",
    "application/x-7z-compressed",
    "application/pdf",
)


@dataclass
class CompressionDecision:
    compress: bool
    reason: str
    entropy: float
    original_size: int
    compressed_size: int = 0
    ratio: float = 1.0

    def to_header(self) -> str:
        if self.compress:
            return f"gzip; ratio={self.ratio:.3f}; entropy={self.entropy:.2f}"
        return f"skip; reason={self.reason}; entropy={self.entropy:.2f}"


def shannon_entropy(data: bytes, *, sample_size: int = 65536) -> float:
    sample = bytes(data[: max(1, int(sample_size))])
    if not sample:
        return 0.0
    counts = [0] * 256
    for byte in sample:
        counts[byte] += 1
    total = float(len(sample))
    entropy = 0.0
    for count in counts:
        if count:
            p = count / total
            entropy -= p * math.log2(p)
    return entropy


def looks_precompressed(data: bytes) -> bool:
    head = bytes(data[:16])
    if any(head.startswith(magic) for magic in COMPRESSED_MAGIC):
        return True
    if len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] in (b"WEBP", b"WAVE"):
        return True
    if len(head) >= 4 and head[:4] == b"GGUF":
        return True
    return False


def should_bypass_payload(
    data: bytes,
    *,
    content_type: str = "",
    min_bytes: int = DEFAULT_MIN_BYTES,
    entropy_bypass: float = DEFAULT_ENTROPY_BYPASS,
) -> tuple[bool, str, float]:
    size = len(data)
    if size < max(1, int(min_bytes)):
        return True, "below_min_bytes", shannon_entropy(data)
    ctype = str(content_type or "").split(";", 1)[0].strip().lower()
    if ctype and any(ctype.startswith(prefix) for prefix in HTTP_BYPASS_TYPES):
        return True, "content_type_bypass", shannon_entropy(data)
    if looks_precompressed(data):
        return True, "magic_precompressed", shannon_entropy(data)
    entropy = shannon_entropy(data)
    if entropy >= float(entropy_bypass):
        return True, "high_entropy", entropy
    return False, "compressible", entropy


def gzip_decision(
    data: bytes,
    *,
    content_type: str = "",
    level: int = 5,
    min_bytes: int = DEFAULT_MIN_BYTES,
    entropy_bypass: float = DEFAULT_ENTROPY_BYPASS,
    min_gain: float = DEFAULT_MIN_GAIN,
) -> tuple[bytes, CompressionDecision]:
    original_size = len(data)
    bypass, reason, entropy = should_bypass_payload(
        data,
        content_type=content_type,
        min_bytes=min_bytes,
        entropy_bypass=entropy_bypass,
    )
    if bypass:
        return data, CompressionDecision(False, reason, entropy, original_size)
    compressed = gzip.compress(data, compresslevel=max(1, min(9, int(level or 5))))
    ratio = len(compressed) / max(1, original_size)
    if ratio >= (1.0 - float(min_gain)):
        return data, CompressionDecision(False, "insufficient_gain", entropy, original_size, len(compressed), ratio)
    return compressed, CompressionDecision(True, "compressed", entropy, original_size, len(compressed), ratio)


def pack_text(
    text: str | None,
    *,
    min_bytes: int | None = None,
    level: int = 5,
    min_gain: float = DEFAULT_MIN_GAIN,
) -> str | None:
    if text is None:
        return None
    raw_text = str(text)
    if raw_text.startswith(ENVELOPE_PREFIX):
        return raw_text
    data = raw_text.encode("utf-8", errors="ignore")
    threshold = int(min_bytes if min_bytes is not None else os.getenv("ULTRON_STORAGE_COMPRESSION_MIN_BYTES", "2048") or 2048)
    packed, decision = gzip_decision(data, content_type="text/plain", level=level, min_bytes=threshold, min_gain=min_gain)
    if not decision.compress:
        return raw_text
    envelope = {
        "codec": "gzip",
        "original_size": decision.original_size,
        "compressed_size": decision.compressed_size,
        "entropy": round(decision.entropy, 4),
        "sha256": hashlib.sha256(data).hexdigest(),
        "data_b64": base64.b64encode(packed).decode("ascii"),
    }
    return ENVELOPE_PREFIX + base64.b64encode(json.dumps(envelope, separators=(",", ":")).encode("utf-8")).decode("ascii")


def unpack_text(text: str | None) -> str | None:
    if text is None:
        return None
    raw_text = str(text)
    if not raw_text.startswith(ENVELOPE_PREFIX):
        return raw_text
    try:
        envelope = json.loads(base64.b64decode(raw_text[len(ENVELOPE_PREFIX) :]).decode("utf-8"))
        if envelope.get("codec") != "gzip":
            return raw_text
        compressed = base64.b64decode(str(envelope.get("data_b64") or ""))
        data = gzip.decompress(compressed)
        expected = str(envelope.get("sha256") or "")
        if expected and hashlib.sha256(data).hexdigest() != expected:
            return raw_text
        return data.decode("utf-8", errors="replace")
    except Exception:
        return raw_text


def decode_row_fields(row: dict[str, Any], fields: Iterable[str]) -> dict[str, Any]:
    out = dict(row)
    for field in fields:
        if field in out:
            out[field] = unpack_text(out.get(field))
    return out


class EntropyAwareCompressionMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app: Any,
        *,
        min_bytes: int = DEFAULT_MIN_BYTES,
        max_bytes: int = DEFAULT_MAX_HTTP_BYTES,
        level: int = 5,
        entropy_bypass: float = DEFAULT_ENTROPY_BYPASS,
        min_gain: float = DEFAULT_MIN_GAIN,
    ):
        super().__init__(app)
        self.min_bytes = max(1, int(min_bytes))
        self.max_bytes = max(self.min_bytes, int(max_bytes))
        self.level = int(level)
        self.entropy_bypass = float(entropy_bypass)
        self.min_gain = float(min_gain)

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        accept = str(request.headers.get("accept-encoding") or "").lower()
        if "gzip" not in accept:
            return await call_next(request)

        response = await call_next(request)
        content_type = str(response.headers.get("content-type") or "")
        content_type_base = content_type.split(";", 1)[0].strip().lower()

        if (
            response.status_code < 200
            or response.status_code in (204, 304)
            or response.headers.get("content-encoding")
            or content_type_base == "text/event-stream"
            or (content_type_base and not any(content_type_base.startswith(prefix) for prefix in HTTP_COMPRESSIBLE_TYPES))
        ):
            return response

        try:
            content_length = int(response.headers.get("content-length") or "0")
        except Exception:
            content_length = 0
        if content_length and content_length > self.max_bytes:
            return response

        chunks: list[bytes] = []
        exceeded_max_bytes = False
        total_bytes = 0
        async for chunk in response.body_iterator:
            if isinstance(chunk, str):
                chunk = chunk.encode("utf-8")
            chunk_bytes = bytes(chunk)
            chunks.append(chunk_bytes)
            total_bytes += len(chunk_bytes)
            if total_bytes > self.max_bytes:
                exceeded_max_bytes = True

        body = b"".join(chunks)
        if exceeded_max_bytes:
            headers = dict(response.headers)
            headers.pop("content-length", None)
            headers["content-length"] = str(len(body))
            headers["vary"] = "Accept-Encoding"
            headers["x-ultron-compression"] = "skip; reason=max_bytes"
            return Response(content=body, status_code=response.status_code, headers=headers, media_type=content_type)

        packed, decision = gzip_decision(
            body,
            content_type=content_type,
            level=self.level,
            min_bytes=self.min_bytes,
            entropy_bypass=self.entropy_bypass,
            min_gain=self.min_gain,
        )
        headers = dict(response.headers)
        headers.pop("content-length", None)
        headers["vary"] = "Accept-Encoding"
        headers["x-ultron-compression"] = decision.to_header()
        if decision.compress:
            headers["content-encoding"] = "gzip"
            headers["content-length"] = str(len(packed))
        else:
            headers["content-length"] = str(len(body))
        return Response(content=packed, status_code=response.status_code, headers=headers, media_type=content_type)
