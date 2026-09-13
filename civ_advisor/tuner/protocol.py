"""The tuner wire format, as pure functions over bytes.

No sockets and no game concepts live here, so every rule below is checked
against captures in tests/fixtures/tuner/ without a running game.

A message is:  uint32 LE length (payload INCLUDING its NUL) | int32 LE tag |
NUL-terminated UTF-8 payload.
"""
from __future__ import annotations

import struct

TAG_COMMAND = 3       # "CMD:<state index>:<lua>"
TAG_HANDSHAKE = 4     # "APP:<name>", "LSQ:", and every output message

_HEADER = struct.Struct("<II")
_OUTPUT_PREFIX = "O\x00"


def frame(tag: int, payload: str) -> bytes:
    """One message on the wire. The length counts the NUL, which is easy to get wrong."""
    body = payload.encode("utf-8") + b"\0"
    return _HEADER.pack(len(body), tag) + body


def consume(buf: bytes) -> tuple[tuple[tuple[int, str], ...], bytes]:
    """Every complete message in `buf`, plus the incomplete tail to keep.

    The game splits long output across packets, so a caller that discarded the
    tail would lose a line whenever a reply straddled a boundary.
    """
    out: list[tuple[int, str]] = []
    i = 0
    while i + _HEADER.size <= len(buf):
        length, tag = _HEADER.unpack_from(buf, i)
        start = i + _HEADER.size
        if length > len(buf) - start:
            break
        out.append((tag, buf[start:start + length].rstrip(b"\0").decode("utf-8", "replace")))
        i = start + length
    return tuple(out), buf[i:]


def parse(buf: bytes) -> tuple[tuple[int, str], ...]:
    """Every complete message in `buf`, discarding any incomplete tail."""
    return consume(buf)[0]


def output_text(payload: str) -> str | None:
    """The text of an output message, or None if this payload is not output.

    Output arrives as "O\\0<state name>: <text>". The state name is discarded:
    the caller already knows which state it addressed, and keeping it here would
    invite matching on it.
    """
    if not payload.startswith(_OUTPUT_PREFIX):
        return None
    rest = payload[len(_OUTPUT_PREFIX):]
    _, sep, text = rest.partition(": ")
    return text if sep else rest


def parse_states(payload: str) -> dict[str, int]:
    """The `LSQ:` reply as name -> index.

    Keyed by NAME deliberately. Indices shift when the player loads a mod, and a
    hardcoded index does not fail loudly -- it silently addresses another VM.
    """
    parts = payload.split("\x00")
    states: dict[str, int] = {}
    for index, name in zip(parts[::2], parts[1::2]):
        try:
            states[name] = int(index)
        except ValueError:      # a malformed pair is not evidence about the others
            continue
    return states


__all__ = ["TAG_COMMAND", "TAG_HANDSHAKE", "consume", "frame", "output_text",
           "parse", "parse_states"]
