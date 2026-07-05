"""Chrome native messaging framing: 4-byte little-endian length prefix + UTF-8 JSON."""

import json
import struct


def _read_exact(stream, size):
    """Read exactly size bytes, looping over short reads. Short result means EOF."""
    chunks = []
    remaining = size
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def read_frame(stream):
    """Read one framed payload from a binary stream.

    Returns the payload bytes, or None on clean EOF at a frame boundary.
    Raises EOFError if the stream ends inside a frame.
    """
    header = _read_exact(stream, 4)
    if not header:
        return None
    if len(header) < 4:
        raise EOFError("stream ended inside a frame header")
    (length,) = struct.unpack("<I", header)
    payload = _read_exact(stream, length)
    if len(payload) < length:
        raise EOFError("stream ended inside a frame payload")
    return payload


def write_frame(stream, payload):
    """Write one framed payload to a binary stream and flush."""
    stream.write(struct.pack("<I", len(payload)))
    stream.write(payload)
    stream.flush()


def read_message(stream):
    """Read one JSON message. Returns the decoded value, or None on clean EOF."""
    payload = read_frame(stream)
    if payload is None:
        return None
    return json.loads(payload.decode("utf-8"))


def write_message(stream, obj):
    """JSON-encode obj and write it as one frame."""
    write_frame(stream, json.dumps(obj, ensure_ascii=False).encode("utf-8"))
