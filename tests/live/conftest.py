"""Fixtures for the live suite. Opt-in, and never part of a default run.

These tests talk to a real, running Civilization VI with `EnableTuner 1` set (see
tests/live/README.md). A normal `uv run pytest` neither starts a game nor collects
these tests -- `addopts` in pyproject.toml ignores this directory, because the default
run must stay offline. Whoever runs this suite by hand may have any game state loaded,
so every test here asserts a shape, never a specific value.
"""
from __future__ import annotations

import socket

import pytest


def _tuner_is_up() -> bool:
    try:
        socket.create_connection(("127.0.0.1", 4318), timeout=0.5).close()
        return True
    except OSError:
        return False


@pytest.fixture(scope="session", autouse=True)
def require_tuner():
    if not _tuner_is_up():
        pytest.skip("needs a running Civ VI with EnableTuner 1", allow_module_level=True)


@pytest.fixture
def tuner():
    """One connection per test, always closed.

    `open_tuner` holds a real socket against the player's game. Each test used to call
    it and drop the result, leaking a connection per test into whatever the game does
    with abandoned tuner clients. `close` is looked up rather than assumed: on any
    failure `open_tuner` returns a NullTuner, which has no socket to close.
    """
    from civ_advisor.tuner.client import open_tuner

    provider = open_tuner()
    try:
        yield provider
    finally:
        close = getattr(provider, "close", None)
        if callable(close):
            close()
