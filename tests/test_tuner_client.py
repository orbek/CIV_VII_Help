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
    """Replays captured bytes, keyed by which state a command addressed.

    An uncaught Lua error aborts the chunk before the sentinel this module's
    caller appends ever runs -- observed against the real game. `abort_states`
    models exactly that: for those states, the fake sends the reply but never
    follows it with the sentinel frame, the same way a real aborted chunk
    would never reach its own trailing `print(SENTINEL)`.
    """

    def __init__(self, replies: dict[int, bytes], *, drip: bool = False,
                 abort_states: frozenset[int] = frozenset()):
        self.replies = replies
        self.drip = drip          # send one byte at a time, to split frames
        self.abort_states = abort_states
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
                        if state not in self.abort_states:
                            self._send(conn, frame(TAG_HANDSHAKE,
                                                   f"O\x00x: {SENTINEL}"))
        except OSError:
            return

    def close(self):
        self._srv.close()


def aborted_reply(text: str) -> bytes:
    """One output frame carrying an error line, and nothing after it.

    Models what the real game sends when an un-`pcall`'d call fails: the
    chunk stops dead, so this is the entire reply -- no sentinel follows.
    """
    return frame(TAG_HANDSHAKE, f"O\x00x: {text}")


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
        # `_ask` itself must reject anything that is not a known catalog id --
        # otherwise it is an arbitrary-Lua primitive with an underscore on it.
        with pytest.raises(KeyError):
            t._ask("not-a-query")
    finally:
        game.close()


def test_an_aborted_chunk_is_reported_as_unreachable_not_as_a_dead_game():
    """The sentinel never prints when Lua raises. That must not read as 'no game'."""
    game = FakeGame({4: aborted_reply("ERR:Runtime Error: function expected instead of nil")},
                     abort_states=frozenset({4}))
    try:
        t = open_tuner(port=game.port, timeout=3.0)
        assert t.maintenance() is None
        assert t.unavailable is TunerUnavailable.UNREACHABLE
        assert "running" not in (t.reason or "")
    finally:
        game.close()


def test_an_aborted_chunk_does_not_burn_the_whole_timeout():
    """Detection is by content, not by waiting."""
    import time

    game = FakeGame({4: aborted_reply("ERR:Runtime Error: function expected instead of nil")},
                     abort_states=frozenset({4}))
    try:
        t = open_tuner(port=game.port, timeout=5.0)
        start = time.monotonic()
        t.maintenance()
        assert time.monotonic() - start < 2.0
    finally:
        game.close()


def test_a_failure_does_not_leak_into_the_next_call_on_the_same_instance():
    game = FakeGame({4: aborted_reply("ERR:Runtime Error: boom"),
                      125: (FIXTURES / "query_buildoptions.bin").read_bytes()},
                     abort_states=frozenset({4}))
    try:
        t = open_tuner(port=game.port, timeout=3.0)
        assert t.maintenance() is None
        assert t.unavailable is TunerUnavailable.UNREACHABLE
        t.build_options()
        assert t.unavailable is None
        assert t.reason is None
    finally:
        game.close()


def test_an_out_of_range_port_does_not_raise():
    t = open_tuner(port=99999, timeout=0.5)
    assert t.available is False
    assert t.unavailable is TunerUnavailable.NOT_ENABLED
