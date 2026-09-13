"""Talking to the running game, or saying precisely why we cannot.

Like `open_ruleset`, `open_tuner` never raises: every failure becomes a
NullTuner carrying the reason a player can act on. A connection error must not
take down a poll that read the logs perfectly well.
"""
from __future__ import annotations

import socket
import time
from dataclasses import dataclass
from datetime import UTC, datetime

from .base import (
    CityAmenities, Maintenance, NullTuner, SettlementOptions, TUNER_OFF,
    TunerProvider, TunerReading, TunerUnavailable,
)
from .protocol import TAG_COMMAND, TAG_HANDSHAKE, consume, frame, output_text, parse_states
from .queries import CATALOG, Query, looks_unreachable

HOST = "127.0.0.1"      # loopback only, always. Never configurable.
PORT = 4318
SENTINEL = "---CIV-ADVISOR-END---"

_NOT_ANSWERING = (
    "The tuner socket is open but the game did not answer. This usually means no "
    "match is loaded yet."
)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass
class Civ6Tuner:
    """A live connection to one running game.

    There is deliberately no method that takes Lua. The catalog is the only way
    to ask a question, so this object cannot be turned into a way to run code in
    someone's game.
    """

    _sock: socket.socket
    _states: dict[str, int]
    _timeout: float
    _buf: bytes = b""
    _reading: TunerReading | None = None
    _unavailable: TunerUnavailable | None = None
    _reason: str | None = None
    _turn: int = 0
    _closed: bool = False

    @property
    def available(self) -> bool:
        return not self._closed

    @property
    def reason(self) -> str | None:
        return self._reason

    @property
    def unavailable(self) -> TunerUnavailable | None:
        return self._unavailable

    def reading(self) -> TunerReading | None:
        return self._reading

    def close(self) -> None:
        self._closed = True
        try:
            self._sock.close()
        except OSError:
            pass

    def _ask(self, query: Query) -> list[str] | None:
        """Run one catalog entry and return its output lines, or None."""
        index = self._states.get(query.state)
        if index is None:
            self._unavailable = TunerUnavailable.UNREACHABLE
            self._reason = f"the game exposes no Lua state named {query.state!r}"
            return None
        try:
            self._sock.sendall(
                frame(TAG_COMMAND, f'CMD:{index}:{query.lua}\nprint("{SENTINEL}")'))
        except OSError:
            self._unavailable = TunerUnavailable.NOT_ANSWERING
            self._reason = _NOT_ANSWERING
            return None

        lines: list[str] = []
        deadline = time.monotonic() + self._timeout
        self._sock.settimeout(0.2)
        while time.monotonic() < deadline:
            try:
                chunk = self._sock.recv(65536)
                if not chunk:
                    break
                self._buf += chunk
            except socket.timeout:
                pass
            except OSError:
                break
            msgs, self._buf = consume(self._buf)
            for tag, payload in msgs:
                text = output_text(payload)
                if text is None:
                    continue
                if SENTINEL in text:
                    self._reading = TunerReading(
                        turn=self._turn, read_at=_now(), state=query.state)
                    return lines
                lines.append(text)
        self._unavailable = TunerUnavailable.NOT_ANSWERING
        self._reason = _NOT_ANSWERING
        return None

    def _answer(self, query_id: str):
        query = CATALOG[query_id]
        lines = self._ask(query)
        if lines is None:
            return None
        if looks_unreachable(lines):
            # A permanent property of the game, not a transient failure.
            self._unavailable = TunerUnavailable.UNREACHABLE
            self._reason = (
                f"the game's {query.state} state does not implement the calls "
                f"{query.id} needs")
            return None
        try:
            return query.parse(lines)
        except ValueError as exc:
            self._unavailable = TunerUnavailable.UNREACHABLE
            self._reason = f"the {query.id} reply could not be read: {exc}"
            return None

    def maintenance(self) -> Maintenance | None:
        return self._answer("maintenance")

    def amenities(self) -> tuple[CityAmenities, ...]:
        return self._answer("amenities") or ()

    def build_options(self) -> tuple[SettlementOptions, ...]:
        return self._answer("build_options") or ()


def open_tuner(port: int = PORT, timeout: float = 3.0) -> TunerProvider:
    """Connect and handshake, or return a NullTuner saying why not.

    Never raises. A tuner failure must not cost a poll that read the logs fine.
    """
    try:
        sock = socket.create_connection((HOST, port), timeout=timeout)
    except OSError:
        # Closed port and refused connection are the same thing to a player:
        # the setting is off, or the game is not running.
        return TUNER_OFF

    try:
        sock.sendall(frame(TAG_HANDSHAKE, "APP:civ-advisor"))
        sock.sendall(frame(TAG_HANDSHAKE, "LSQ:"))
    except OSError:
        sock.close()
        return NullTuner(TunerUnavailable.NOT_ANSWERING, _NOT_ANSWERING)

    buf = b""
    states: dict[str, int] = {}
    deadline = time.monotonic() + timeout
    sock.settimeout(0.2)
    while time.monotonic() < deadline and not states:
        try:
            chunk = sock.recv(65536)
            if not chunk:
                break
            buf += chunk
        except socket.timeout:
            continue
        except OSError:
            break
        msgs, buf = consume(buf)
        for _, payload in msgs:
            found = parse_states(payload)
            # The identity frame parses to nothing useful; the state list is the
            # one that names GameCore_Tuner.
            if "GameCore_Tuner" in found:
                states = found

    if not states:
        sock.close()
        return NullTuner(TunerUnavailable.NOT_ANSWERING, _NOT_ANSWERING)
    return Civ6Tuner(_sock=sock, _states=states, _timeout=timeout, _buf=buf)


__all__ = ["Civ6Tuner", "HOST", "PORT", "SENTINEL", "open_tuner"]
