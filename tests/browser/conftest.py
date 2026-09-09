"""Fixtures for the browser suite. Dev-only, opt-in, and never part of a default run.

Playwright and its browser are in the `browser` dependency group, so a normal
`uv run pytest` neither needs them nor collects these tests. See tests/browser/README.md.

The server under test is started in-process with `--no-archive --no-llm` semantics: no
archive root and no commentary worker, against a fixture log directory. That is
deliberate — the plan requires the decision brief and its how-to to work with the local
model unavailable, and these tests are the check that they do.
"""
from __future__ import annotations

import shutil
import socket
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("playwright", reason="the browser group is not installed")


import uvicorn  # noqa: E402

from civ7_advisor.api.app import create_app  # noqa: E402

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"



def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def brief_logs(tmp_path_factory) -> Path:
    """A log directory whose human is behind on culture with one logged settlement, so the
    culture decision has something to decide and a critical threat sits above it."""
    logs = tmp_path_factory.mktemp("logs")
    shutil.copytree(FIXTURES / "logs_82turns", logs, dirs_exist_ok=True)
    (logs / "CityBuildQueue.csv").write_text(
        "Game Turn, Player, City, Production Added, Current Item, Current Production, "
        "Production Needed, Overflow\n"
        "82, 0, LOC_CITY_NAME_TEST1, 20.0, UNIT_WARRIOR, 25.0, 30, 0.0\n"
    )
    return logs


@pytest.fixture(scope="session")
def server(brief_logs: Path):
    """The real app on a real port. No archive root, no commentary worker."""
    port = _free_port()
    app = create_app(brief_logs, poll_interval=60)
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    running = uvicorn.Server(config)
    thread = threading.Thread(target=running.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 20
    while not running.started:
        if time.monotonic() > deadline:
            raise AssertionError("the fixture server did not start")
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    running.should_exit = True
    thread.join(timeout=10)


@pytest.fixture(scope="session")
def crowded_logs(brief_logs: Path, tmp_path_factory) -> Path:
    """The same session with four more war declarations, so five distinct critical alerts
    exist. Built from real log rows rather than injected into the page: the point of the
    check is that the render path handles five, and a test hook in shipped code would
    prove something else."""
    logs = tmp_path_factory.mktemp("crowded")
    shutil.copytree(brief_logs, logs, dirs_exist_ok=True)
    path = logs / "AI_DiplomaticActions.csv"
    rows = path.read_text().splitlines()
    declarations = [f"81, {p}, ACTION DIPLOMACY_ACTION_DECLARE_WAR, 0, TOKENS 1"
                    for p in (1, 2, 5, 6)]
    path.write_text("\n".join(rows + declarations) + "\n")
    return logs


@pytest.fixture(scope="session")
def crowded_server(crowded_logs: Path):
    port = _free_port()
    config = uvicorn.Config(create_app(crowded_logs, poll_interval=60),
                            host="127.0.0.1", port=port, log_level="error")
    running = uvicorn.Server(config)
    thread = threading.Thread(target=running.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 20
    while not running.started:
        if time.monotonic() > deadline:
            raise AssertionError("the crowded fixture server did not start")
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    running.should_exit = True
    thread.join(timeout=10)


@pytest.fixture
def dashboard(page, server):
    """The dashboard, loaded, with its first briefing painted."""
    page.set_viewport_size({"width": 1200, "height": 842})
    page.goto(server)
    page.wait_for_selector("#brief-critical .decision")
    return page
