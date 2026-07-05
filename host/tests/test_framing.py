import io

import pytest

from signer_host import framing


def test_round_trip():
    buf = io.BytesIO()
    framing.write_message(buf, {"id": "1", "result": {"ok": True}})
    buf.seek(0)
    assert framing.read_message(buf) == {"id": "1", "result": {"ok": True}}


def test_multi_message_stream():
    buf = io.BytesIO()
    messages = [{"id": str(i), "n": i} for i in range(3)]
    for message in messages:
        framing.write_message(buf, message)
    buf.seek(0)
    assert [framing.read_message(buf) for _ in range(3)] == messages
    assert framing.read_message(buf) is None


def test_unicode_round_trip():
    buf = io.BytesIO()
    message = {"id": "x", "subject": "CN=जॉन डो, O=दिल्ली", "note": "签名 ✒️"}
    framing.write_message(buf, message)
    buf.seek(0)
    assert framing.read_message(buf) == message


def test_length_prefix_is_little_endian_byte_count():
    buf = io.BytesIO()
    payload = "héllo".encode("utf-8")
    framing.write_frame(buf, payload)
    raw = buf.getvalue()
    assert raw[:4] == len(payload).to_bytes(4, "little")
    assert raw[4:] == payload


def test_clean_eof_returns_none():
    assert framing.read_frame(io.BytesIO(b"")) is None
    assert framing.read_message(io.BytesIO(b"")) is None


def test_truncated_header_raises():
    with pytest.raises(EOFError):
        framing.read_frame(io.BytesIO(b"\x05\x00"))


def test_truncated_payload_raises():
    with pytest.raises(EOFError):
        framing.read_frame(io.BytesIO(b"\x05\x00\x00\x00ab"))
