import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent))


def test_binary_protocol_roundtrip_request_response():
    from ultronpro import binary_protocol

    key = b"secret"
    nonce = 123456
    payload = binary_protocol.encode_infer_request(
        model="local",
        system="sistema",
        prompt="Gere resposta em PT-BR",
        max_tokens=128,
        temperature=0.2,
        json_mode=True,
    )
    frame = binary_protocol.encode_frame(
        binary_protocol.OP_INFER_REQUEST,
        payload,
        nonce=nonce,
        key=key,
        sequence=1,
    )
    decoded_frame = binary_protocol.decode_frame(frame, key=key, expected_nonce=nonce)
    decoded = binary_protocol.decode_infer_request(decoded_frame.payload)

    assert decoded_frame.opcode == binary_protocol.OP_INFER_REQUEST
    assert decoded["prompt"] == "Gere resposta em PT-BR"
    assert decoded["system"] == "sistema"
    assert decoded["max_tokens"] == 128
    assert decoded["json_mode"] is True

    response_payload = binary_protocol.encode_infer_response(text="ok", status=200, model="local")
    response_frame = binary_protocol.encode_frame(
        binary_protocol.OP_INFER_RESPONSE,
        response_payload,
        nonce=nonce,
        key=key,
        sequence=2,
    )
    response = binary_protocol.decode_infer_response(
        binary_protocol.decode_frame(response_frame, key=key, expected_nonce=nonce).payload
    )
    assert response["text"] == "ok"
    assert response["status"] == 200


def test_binary_protocol_rejects_tampering_and_replay_nonce():
    from ultronpro import binary_protocol

    key = b"secret"
    payload = binary_protocol.encode_infer_request(
        model="local",
        prompt="teste",
        max_tokens=64,
    )
    frame = bytearray(
        binary_protocol.encode_frame(
            binary_protocol.OP_INFER_REQUEST,
            payload,
            nonce=111,
            key=key,
            sequence=1,
        )
    )
    frame[-1] ^= 0x01
    try:
        binary_protocol.decode_frame(bytes(frame), key=key, expected_nonce=111)
        raise AssertionError("tampered frame should fail")
    except binary_protocol.BinaryProtocolError as exc:
        assert "mac" in str(exc)

    clean = binary_protocol.encode_frame(
        binary_protocol.OP_INFER_REQUEST,
        payload,
        nonce=111,
        key=key,
        sequence=1,
    )
    try:
        binary_protocol.decode_frame(clean, key=key, expected_nonce=222)
        raise AssertionError("replayed nonce should fail")
    except binary_protocol.BinaryProtocolError as exc:
        assert "nonce" in str(exc)

