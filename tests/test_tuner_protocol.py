"""The wire format, checked against bytes a real game actually sent.

Every fixture in tests/fixtures/tuner/ is a capture. If a test here disagrees
with those bytes, the test is wrong about the protocol, not the capture.
"""
from pathlib import Path

import pytest

from civ_advisor.tuner.protocol import (
    TAG_COMMAND, TAG_HANDSHAKE, consume, frame, output_text, parse, parse_states,
)

FIXTURES = Path(__file__).parent / "fixtures" / "tuner"


def test_frame_length_counts_the_null_terminator():
    # 4-byte length, 4-byte tag, payload, NUL. "hi" is 2 bytes, so length is 3.
    assert frame(TAG_COMMAND, "hi") == b"\x03\x00\x00\x00\x03\x00\x00\x00hi\x00"


def test_parse_reads_back_what_frame_wrote():
    buf = frame(TAG_HANDSHAKE, "APP:x") + frame(TAG_COMMAND, "CMD:4:print(1)")
    assert parse(buf) == ((TAG_HANDSHAKE, "APP:x"), (TAG_COMMAND, "CMD:4:print(1)"))


def test_consume_returns_the_incomplete_tail_unparsed():
    whole = frame(TAG_COMMAND, "abc")
    msgs, rest = consume(whole + whole[:5])
    assert msgs == ((TAG_COMMAND, "abc"),)
    assert rest == whole[:5]


def test_consume_of_a_header_without_its_payload_yields_nothing():
    msgs, rest = consume(frame(TAG_COMMAND, "abc")[:6])
    assert msgs == ()
    assert len(rest) == 6


def test_real_handshake_names_the_application():
    msgs = parse((FIXTURES / "handshake_lsq.bin").read_bytes())
    assert "Civ6" in msgs[0][1]


def test_real_handshake_lists_states_by_name():
    msgs = parse((FIXTURES / "handshake_lsq.bin").read_bytes())
    states = parse_states(msgs[1][1])
    assert states["GameCore_Tuner"] == 4
    assert states["InGame"] == 125


def test_state_indices_are_not_positional():
    """A mod was loaded when this was captured, and it displaced the rest.

    This is the whole reason states are resolved by name. If this capture ever
    stops containing a mod, keep a capture that does.
    """
    states = parse_states(parse((FIXTURES / "handshake_lsq.bin").read_bytes())[1][1])
    assert states["AdvisorProbe"] == 2
    assert states["GameCore_Tuner"] > 2


def test_output_text_strips_the_state_prefix():
    assert output_text("O\x00GameCore_Tuner: total\t1") == "total\t1"


def test_output_text_rejects_a_payload_that_is_not_output():
    assert output_text("Civ6\x00Sid Meier's Civilization 6") is None


def test_real_maintenance_capture_decodes_to_its_values():
    msgs = parse((FIXTURES / "query_maintenance.bin").read_bytes())
    lines = [t for t in (output_text(p) for _, p in msgs) if t]
    assert "total\t1" in lines
    assert "districts\t1" in lines
    assert "gold\t152" in lines
