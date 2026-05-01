from __future__ import annotations

import hmac
import hashlib
import os
import socket
import struct
import zlib
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse


MAGIC = b"UB"
VERSION = 1
HELLO_SIZE = 5
FRAME_HEADER = struct.Struct("!2sBBBQII16s")

OP_HELLO = 0x01
OP_CHALLENGE = 0x02
OP_INFER_REQUEST = 0x10
OP_INFER_RESPONSE = 0x11
OP_LOOP_EVENT = 0x20
OP_LOOP_CONTROL = 0x21
OP_ERROR = 0x7F

FLAG_COMPRESSED = 0x01
FLAG_JSON_MODE = 0x02

LOOP_KIND_CODES = {
    "event": 1,
    "workspace": 2,
    "runtime_health": 3,
    "guard_state": 4,
    "control": 5,
}
LOOP_KIND_NAMES = {v: k for k, v in LOOP_KIND_CODES.items()}
SEVERITY_CODES = {
    "debug": 0,
    "info": 1,
    "warning": 2,
    "error": 3,
    "critical": 4,
}
SEVERITY_NAMES = {v: k for k, v in SEVERITY_CODES.items()}

MAX_PAYLOAD_BYTES = int(os.getenv("ULTRON_BINARY_MAX_PAYLOAD_BYTES", str(8 * 1024 * 1024)) or (8 * 1024 * 1024))
COMPRESS_THRESHOLD_BYTES = int(os.getenv("ULTRON_BINARY_COMPRESS_THRESHOLD_BYTES", "768") or 768)


class BinaryProtocolError(ValueError):
    pass


@dataclass(frozen=True)
class BinaryFrame:
    opcode: int
    flags: int
    nonce: int
    payload: bytes
    sequence: int = 0


def make_hello() -> bytes:
    return struct.pack("!2sBBB", MAGIC, VERSION, OP_HELLO, 0)


def parse_hello(data: bytes) -> None:
    if len(data) != HELLO_SIZE:
        raise BinaryProtocolError("invalid_hello_size")
    magic, version, opcode, _flags = struct.unpack("!2sBBB", data)
    if magic != MAGIC or version != VERSION or opcode != OP_HELLO:
        raise BinaryProtocolError("invalid_hello")


def make_challenge(nonce: int) -> bytes:
    return struct.pack("!2sBBBQ", MAGIC, VERSION, OP_CHALLENGE, 0, int(nonce) & 0xFFFFFFFFFFFFFFFF)


def parse_challenge(data: bytes) -> int:
    if len(data) != 13:
        raise BinaryProtocolError("invalid_challenge_size")
    magic, version, opcode, _flags, nonce = struct.unpack("!2sBBBQ", data)
    if magic != MAGIC or version != VERSION or opcode != OP_CHALLENGE:
        raise BinaryProtocolError("invalid_challenge")
    return int(nonce)


def protocol_key(token: str | None = None) -> bytes:
    raw = (
        str(os.getenv("ULTRON_BINARY_PROTOCOL_KEY", "") or "").strip()
        or str(token or "").strip()
        or str(os.getenv("ULTRON_LOCAL_INFER_TOKEN", "") or "").strip()
    )
    return raw.encode("utf-8")


def _mac(key: bytes, prefix: bytes, payload: bytes) -> bytes:
    if key:
        return hmac.new(key, prefix + payload, hashlib.sha256).digest()[:16]
    return hashlib.sha256(prefix + payload).digest()[:16]


def encode_frame(
    opcode: int,
    payload: bytes,
    *,
    nonce: int,
    key: bytes,
    flags: int = 0,
    sequence: int = 0,
) -> bytes:
    body = bytes(payload or b"")
    if len(body) > COMPRESS_THRESHOLD_BYTES:
        compressed = zlib.compress(body, level=3)
        if len(compressed) < len(body):
            body = compressed
            flags |= FLAG_COMPRESSED
    if len(body) > MAX_PAYLOAD_BYTES:
        raise BinaryProtocolError("payload_too_large")
    prefix = struct.pack(
        "!2sBBBQII",
        MAGIC,
        VERSION,
        int(opcode) & 0xFF,
        int(flags) & 0xFF,
        int(nonce) & 0xFFFFFFFFFFFFFFFF,
        int(sequence) & 0xFFFFFFFF,
        len(body),
    )
    tag = _mac(key, prefix, body)
    return prefix + tag + body


def decode_frame(data: bytes, *, key: bytes, expected_nonce: int | None = None) -> BinaryFrame:
    if len(data) < FRAME_HEADER.size:
        raise BinaryProtocolError("frame_too_short")
    magic, version, opcode, flags, nonce, sequence, length, tag = FRAME_HEADER.unpack(data[: FRAME_HEADER.size])
    if magic != MAGIC or version != VERSION:
        raise BinaryProtocolError("invalid_frame_magic")
    if expected_nonce is not None and int(nonce) != int(expected_nonce):
        raise BinaryProtocolError("nonce_mismatch")
    if length > MAX_PAYLOAD_BYTES:
        raise BinaryProtocolError("payload_too_large")
    payload = data[FRAME_HEADER.size :]
    if len(payload) != length:
        raise BinaryProtocolError("payload_length_mismatch")
    prefix = data[: FRAME_HEADER.size - 16]
    expected = _mac(key, prefix, payload)
    if not hmac.compare_digest(expected, tag):
        raise BinaryProtocolError("bad_frame_mac")
    if flags & FLAG_COMPRESSED:
        payload = zlib.decompress(payload)
    return BinaryFrame(opcode=opcode, flags=flags, nonce=nonce, payload=payload, sequence=sequence)


def _pack_bytes(value: Any) -> bytes:
    if value is None:
        raw = b""
    elif isinstance(value, bytes):
        raw = value
    else:
        raw = str(value).encode("utf-8")
    return struct.pack("!I", len(raw)) + raw


def _unpack_bytes(buf: memoryview, offset: int) -> tuple[bytes, int]:
    if offset + 4 > len(buf):
        raise BinaryProtocolError("truncated_length")
    size = struct.unpack_from("!I", buf, offset)[0]
    offset += 4
    if size > MAX_PAYLOAD_BYTES or offset + size > len(buf):
        raise BinaryProtocolError("truncated_value")
    return bytes(buf[offset : offset + size]), offset + size


def encode_infer_request(
    *,
    model: str,
    prompt: str,
    system: str | None = None,
    max_tokens: int = 256,
    temperature: float = 0.2,
    json_mode: bool = False,
    mode: str = "balanced",
) -> bytes:
    flags = FLAG_JSON_MODE if json_mode else 0
    temp_milli = max(0, min(2000, int(round(float(temperature or 0.0) * 1000))))
    head = struct.pack("!BIHB", VERSION, max(1, min(4096, int(max_tokens or 256))), temp_milli, flags)
    return (
        head
        + _pack_bytes(model)
        + _pack_bytes(system or "")
        + _pack_bytes(prompt)
        + _pack_bytes(mode or "balanced")
    )


def decode_infer_request(payload: bytes) -> dict[str, Any]:
    if len(payload) < 8:
        raise BinaryProtocolError("infer_request_too_short")
    version, max_tokens, temp_milli, flags = struct.unpack_from("!BIHB", payload, 0)
    if version != VERSION:
        raise BinaryProtocolError("unsupported_payload_version")
    buf = memoryview(payload)
    offset = 8
    model, offset = _unpack_bytes(buf, offset)
    system, offset = _unpack_bytes(buf, offset)
    prompt, offset = _unpack_bytes(buf, offset)
    mode, offset = _unpack_bytes(buf, offset)
    if offset != len(buf):
        raise BinaryProtocolError("trailing_request_bytes")
    return {
        "model": model.decode("utf-8", errors="replace"),
        "system": system.decode("utf-8", errors="replace"),
        "prompt": prompt.decode("utf-8", errors="replace"),
        "mode": mode.decode("utf-8", errors="replace") or "balanced",
        "max_tokens": int(max_tokens),
        "temperature": float(temp_milli) / 1000.0,
        "json_mode": bool(flags & FLAG_JSON_MODE),
    }


def encode_infer_response(*, text: str = "", error: str = "", model: str = "", status: int = 200) -> bytes:
    return (
        struct.pack("!BH", VERSION, max(0, min(65535, int(status or 0))))
        + _pack_bytes(text)
        + _pack_bytes(error)
        + _pack_bytes(model)
    )


def decode_infer_response(payload: bytes) -> dict[str, Any]:
    if len(payload) < 3:
        raise BinaryProtocolError("infer_response_too_short")
    version, status = struct.unpack_from("!BH", payload, 0)
    if version != VERSION:
        raise BinaryProtocolError("unsupported_payload_version")
    buf = memoryview(payload)
    offset = 3
    text, offset = _unpack_bytes(buf, offset)
    error, offset = _unpack_bytes(buf, offset)
    model, offset = _unpack_bytes(buf, offset)
    if offset != len(buf):
        raise BinaryProtocolError("trailing_response_bytes")
    return {
        "status": int(status),
        "text": text.decode("utf-8", errors="replace"),
        "error": error.decode("utf-8", errors="replace"),
        "model": model.decode("utf-8", errors="replace"),
    }


def encode_loop_event(
    *,
    loop_name: str,
    event: str,
    payload: str | bytes | None = None,
    kind: str = "event",
    severity: str = "info",
    ts_ms: int | None = None,
) -> bytes:
    kind_code = LOOP_KIND_CODES.get(str(kind or "event"), LOOP_KIND_CODES["event"])
    severity_code = SEVERITY_CODES.get(str(severity or "info"), SEVERITY_CODES["info"])
    stamp = int(ts_ms if ts_ms is not None else 0) & 0xFFFFFFFFFFFFFFFF
    head = struct.pack("!BQBB", VERSION, stamp, kind_code, severity_code)
    return head + _pack_bytes(loop_name or "") + _pack_bytes(event or "") + _pack_bytes(payload or b"")


def decode_loop_event(payload: bytes) -> dict[str, Any]:
    if len(payload) < 11:
        raise BinaryProtocolError("loop_event_too_short")
    version, ts_ms, kind_code, severity_code = struct.unpack_from("!BQBB", payload, 0)
    if version != VERSION:
        raise BinaryProtocolError("unsupported_payload_version")
    buf = memoryview(payload)
    offset = 11
    loop_name, offset = _unpack_bytes(buf, offset)
    event, offset = _unpack_bytes(buf, offset)
    body, offset = _unpack_bytes(buf, offset)
    if offset != len(buf):
        raise BinaryProtocolError("trailing_loop_event_bytes")
    return {
        "ts_ms": int(ts_ms),
        "kind": LOOP_KIND_NAMES.get(int(kind_code), "event"),
        "severity": SEVERITY_NAMES.get(int(severity_code), "info"),
        "loop_name": loop_name.decode("utf-8", errors="replace"),
        "event": event.decode("utf-8", errors="replace"),
        "payload": body.decode("utf-8", errors="replace"),
    }


def _read_exact(sock: socket.socket, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = int(size)
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            raise BinaryProtocolError("socket_closed")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _read_frame_socket(sock: socket.socket, *, key: bytes, expected_nonce: int) -> BinaryFrame:
    header = _read_exact(sock, FRAME_HEADER.size)
    length = FRAME_HEADER.unpack(header)[6]
    payload = _read_exact(sock, length)
    return decode_frame(header + payload, key=key, expected_nonce=expected_nonce)


def binary_endpoint_from_base(base_url: str, *, default_port: int = 8026) -> tuple[str, int]:
    explicit = str(os.getenv("ULTRON_LOCAL_INFER_BINARY_URL", "") or "").strip()
    if explicit:
        parsed = urlparse(explicit if "://" in explicit else f"tcp://{explicit}")
        return parsed.hostname or "127.0.0.1", int(parsed.port or default_port)
    parsed = urlparse(str(base_url or "http://127.0.0.1:8025"))
    return parsed.hostname or "127.0.0.1", int(os.getenv("ULTRON_LOCAL_INFER_BINARY_PORT", str(default_port)) or default_port)


def infer_via_binary_tcp(
    *,
    host: str,
    port: int,
    token: str,
    model: str,
    prompt: str,
    system: str | None,
    max_tokens: int,
    temperature: float = 0.2,
    json_mode: bool = False,
    timeout_sec: float = 45.0,
    connect_timeout_sec: float = 0.35,
) -> dict[str, Any]:
    key = protocol_key(token)
    request_payload = encode_infer_request(
        model=model,
        prompt=prompt,
        system=system,
        max_tokens=max_tokens,
        temperature=temperature,
        json_mode=json_mode,
        mode="balanced",
    )
    with socket.create_connection((host, int(port)), timeout=max(0.05, float(connect_timeout_sec))) as sock:
        sock.settimeout(max(5.0, float(timeout_sec)))
        sock.sendall(make_hello())
        nonce = parse_challenge(_read_exact(sock, 13))
        frame = encode_frame(OP_INFER_REQUEST, request_payload, nonce=nonce, key=key, flags=0, sequence=1)
        sock.sendall(frame)
        response = _read_frame_socket(sock, key=key, expected_nonce=nonce)
        if response.opcode == OP_ERROR:
            decoded_error = decode_infer_response(response.payload)
            raise BinaryProtocolError(decoded_error.get("error") or "binary_infer_error")
        if response.opcode != OP_INFER_RESPONSE:
            raise BinaryProtocolError("unexpected_response_opcode")
        decoded = decode_infer_response(response.payload)
        if int(decoded.get("status") or 0) >= 400:
            raise BinaryProtocolError(decoded.get("error") or f"binary_status_{decoded.get('status')}")
        return decoded
