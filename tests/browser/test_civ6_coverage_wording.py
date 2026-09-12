"""Whole-phase review, IMPORTANT 4 and 5: a coverage notice must name the real file (or
the real behaviour) for whichever game is actually active, not hardcode Civ VII's."""
import shutil
import socket
import threading
import time
from pathlib import Path

import pytest
import uvicorn

from civ_advisor.api.app import create_app
from civ_advisor.games.civ6 import CIV6

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _free_port() -> int:
    """Not shared from conftest.py -- tests/browser is not a package, so a relative
    import fails under pytest's rootdir-based collection. Trivial enough to repeat."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _run(app) -> str:
    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 20
    while not server.started:
        if time.monotonic() > deadline:
            raise AssertionError("the fixture server did not start")
        time.sleep(0.05)
    return f"http://127.0.0.1:{port}", server, thread


@pytest.fixture(scope="module")
def civ6_no_build_queue_server(tmp_path_factory):
    """A real Civ VI capture with City_BuildQueue.csv removed, so the production
    domain is genuinely unavailable rather than merely empty -- the case that must
    name Civ VI's own file, not Civ VII's CityBuildQueue.csv."""
    logs = tmp_path_factory.mktemp("civ6_no_queue") / "civ6"
    shutil.copytree(FIXTURES / "logs_civ6", logs)
    (logs / "City_BuildQueue.csv").unlink()
    app = create_app(logs, poll_interval=60, profile=CIV6)
    url, server, thread = _run(app)
    yield url
    server.should_exit = True
    thread.join(timeout=10)


@pytest.fixture(scope="module")
def civ6_no_stats_server(tmp_path_factory):
    """A real Civ VI capture with Player_Stats.csv removed, so the empire domain is
    unavailable -- the case that must not claim Civ VII's log-wipe-on-launch behaviour,
    which Civ VI does not have."""
    logs = tmp_path_factory.mktemp("civ6_no_stats") / "civ6"
    shutil.copytree(FIXTURES / "logs_civ6", logs)
    (logs / "Player_Stats.csv").unlink()
    app = create_app(logs, poll_interval=60, profile=CIV6)
    url, server, thread = _run(app)
    yield url
    server.should_exit = True
    thread.join(timeout=10)


def test_an_unreadable_civ6_build_queue_names_civ6_s_own_file(page, civ6_no_build_queue_server):
    page.goto(civ6_no_build_queue_server)
    page.locator('[data-tab="economy"]').click()
    page.wait_for_selector("#production-table .empty")
    text = page.text_content("#production-table")
    assert "CityBuildQueue.csv" not in text     # Civ VII's filename must never appear
    assert "City_BuildQueue.csv" in text        # Civ VI's own file, named correctly


def test_an_unavailable_civ6_empire_domain_does_not_claim_a_civ7_only_behaviour(
    page, civ6_no_stats_server
):
    page.goto(civ6_no_stats_server)
    page.wait_for_selector("#wipe:not(:empty)")
    text = page.text_content("#wipe")
    assert "Civ VII" not in text               # never claim Civ VII's mechanism for Civ VI
    assert "Civ VI" in text
