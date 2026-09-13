"""The client, against a fake server replaying real captured frames."""
import socket
import threading
from pathlib import Path

import pytest

from civ_advisor.tuner.base import TunerUnavailable
from civ_advisor.tuner.client import SENTINEL, open_tuner
from civ_advisor.tuner.protocol import TAG_HANDSHAKE, consume, frame

FIXTURES = Path(__file__).parent / "fixtures" / "tuner"


class FakeGame:
    """Replays captured bytes, keyed by which state a command addressed."""

    def __init__(self, replies: dict[int, bytes], *, drip: bool = False):
        self.replies = replies
        self.drip = drip          # send one byte at a time, to split frames
        self.asked: list[str] = []
        self._srv = socket.socket()
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind(("127.0.0.1", 0))
        self._srv.listen(1)
        self.port = self._srv.getsockname()[1]
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _send(self, conn, payload: bytes):
        if self.drip:
            for i in range(len(payload)):
                conn.sendall(payload[i:i + 1])
        else:
            conn.sendall(payload)

    def _serve(self):
        conn, _ = self._srv.accept()
        buf = b""
        try:
            while True:
                chunk = conn.recv(65536)
                if not chunk:
                    return
                buf += chunk
                msgs, buf = consume(buf)
                for _, payload in msgs:
                    if payload.startswith("LSQ:"):
                        self._send(conn, (FIXTURES / "handshake_lsq.bin").read_bytes())
                    elif payload.startswith("CMD:"):
                        self.asked.append(payload)
                        state = int(payload.split(":")[1])
                        self._send(conn, self.replies.get(state, b""))
                        self._send(conn, frame(TAG_HANDSHAKE,
                                               f"O\x00x: {SENTINEL}"))
        except OSError:
            return

    def close(self):
        self._srv.close()


def replies() -> dict[int, bytes]:
    return {
        4: (FIXTURES / "query_maintenance.bin").read_bytes(),
        125: (FIXTURES / "query_buildoptions.bin").read_bytes(),
    }


def test_a_closed_port_is_reported_as_not_enabled():
    # Port 1 is reserved and nothing listens there.
    t = open_tuner(port=1, timeout=0.5)
    assert t.available is False
    assert t.unavailable is TunerUnavailable.NOT_ENABLED
    assert "EnableTuner" in t.reason


def test_it_resolves_states_by_name_not_by_index():
    """The capture has a mod at index 2, so positional lookup would misfire."""
    game = FakeGame(replies())
    try:
        t = open_tuner(port=game.port, timeout=3.0)
        assert t.available is True
        t.maintenance()
        assert game.asked[0].startswith("CMD:4:")   # GameCore_Tuner, by name
    finally:
        game.close()


def test_build_options_are_asked_of_the_ui_state():
    game = FakeGame(replies())
    try:
        t = open_tuner(port=game.port, timeout=3.0)
        t.build_options()
        assert any(a.startswith("CMD:125:") for a in game.asked)
    finally:
        game.close()


def test_it_reassembles_a_reply_split_across_packets():
    game = FakeGame(replies(), drip=True)
    try:
        t = open_tuner(port=game.port, timeout=5.0)
        m = t.maintenance()
        assert m is not None and m.net_gold == 7
    finally:
        game.close()


def test_a_reading_carries_the_vm_and_a_timestamp():
    game = FakeGame(replies())
    try:
        t = open_tuner(port=game.port, timeout=3.0)
        t.maintenance()
        r = t.reading()
        assert r is not None and r.state == "GameCore_Tuner" and r.read_at
    finally:
        game.close()


def test_a_not_implemented_reply_yields_absence_not_an_exception():
    game = FakeGame({4: (FIXTURES / "query_not_implemented.bin").read_bytes()})
    try:
        t = open_tuner(port=game.port, timeout=3.0)
        assert t.maintenance() is None
        assert t.unavailable is TunerUnavailable.UNREACHABLE
    finally:
        game.close()


def test_the_client_exposes_no_way_to_run_arbitrary_lua():
    """The catalog is the allowlist; there must be no bypass on the object."""
    game = FakeGame(replies())
    try:
        t = open_tuner(port=game.port, timeout=3.0)
        assert not hasattr(t, "query")
        assert not hasattr(t, "run")
        assert not hasattr(t, "eval")
    finally:
        game.close()
