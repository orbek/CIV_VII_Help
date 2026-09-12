"""The header's game control: which title is in force, and how that was decided."""
import shutil
import socket
import threading
import time
from pathlib import Path

import pytest
import uvicorn

from civ_advisor.api.app import create_app
from civ_advisor.games.civ7 import CIV7
from civ_advisor.games.selection import GameSelector

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _free_port() -> int:
    """Not shared from conftest.py -- tests/browser is not a package, so a relative
    import fails under pytest's rootdir-based collection. Trivial enough to repeat."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_the_header_names_the_game_and_the_mode(page, server):
    page.goto(server)
    page.wait_for_selector("#game-mode:not(:empty)")
    assert "Civilization VII" in page.text_content("#game-mode")
    assert page.input_value("#game-select") == "civ7"


@pytest.fixture(scope="module")
def selector_server(tmp_path_factory):
    """A selectable server: civ7's own fixture logs, plus a civ6 directory that does
    not exist at all -- so pinning civ6 exercises the "logs folder was not found" case
    carried in from Task 7's review (spec 8.1: the pin is honoured, not refused, but
    the header must say why the dashboard is then empty)."""
    logs = tmp_path_factory.mktemp("logs") / "civ7"
    shutil.copytree(FIXTURES / "logs_82turns", logs)
    absent_civ6 = tmp_path_factory.mktemp("nowhere") / "civ6"   # never created
    storage = tmp_path_factory.mktemp("storage")

    selector = GameSelector(pinned="civ7", logs_dirs={"civ7": logs, "civ6": absent_civ6})
    port = _free_port()
    app = create_app(logs, poll_interval=60, profile=CIV7,
                     selector=selector, storage_base=storage)
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    running = uvicorn.Server(config)
    thread = threading.Thread(target=running.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 20
    while not running.started:
        if time.monotonic() > deadline:
            raise AssertionError("the selector fixture server did not start")
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    running.should_exit = True
    thread.join(timeout=10)


def test_pinning_an_absent_logs_directory_says_so_in_the_header(page, selector_server):
    """CARRIED IN FROM TASK 7's REVIEW: an honoured pin whose directory does not exist
    must not look identical to "installed but never played" -- the remedies are
    opposite (install/launch the game, versus play a turn)."""
    page.goto(selector_server)
    page.wait_for_selector("#game-mode:not(:empty)")
    page.select_option("#game-select", "civ6")
    page.wait_for_selector("#game-mode:has-text('logs folder was not found')")
    text = page.text_content("#game-mode")
    assert "install or launch the game" in text
    assert page.input_value("#game-select") == "civ6"


@pytest.fixture(scope="module")
def unplayed_server(tmp_path_factory):
    """Civ VI's directory exists (the game is installed) but is empty (never played) --
    the OTHER half of the same distinction: same visible emptiness, opposite remedy."""
    logs = tmp_path_factory.mktemp("logs") / "civ7"
    shutil.copytree(FIXTURES / "logs_82turns", logs)
    installed_civ6 = tmp_path_factory.mktemp("installed") / "civ6"
    installed_civ6.mkdir()   # exists, but nothing has ever been written into it
    storage = tmp_path_factory.mktemp("storage")

    selector = GameSelector(pinned="civ7", logs_dirs={"civ7": logs, "civ6": installed_civ6})
    port = _free_port()
    app = create_app(logs, poll_interval=60, profile=CIV7,
                     selector=selector, storage_base=storage)
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    running = uvicorn.Server(config)
    thread = threading.Thread(target=running.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 20
    while not running.started:
        if time.monotonic() > deadline:
            raise AssertionError("the unplayed fixture server did not start")
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    running.should_exit = True
    thread.join(timeout=10)


def test_pinning_an_installed_but_unplayed_game_says_so_in_the_header(page, unplayed_server):
    """CARRIED IN FROM TASK 7's REVIEW, the other half: the folder is there, so this
    must NOT say "not found" -- it must say no log has been written yet."""
    page.goto(unplayed_server)
    page.wait_for_selector("#game-mode:not(:empty)")
    page.select_option("#game-select", "civ6")
    page.wait_for_selector("#game-mode:has-text('no log has been written')")
    text = page.text_content("#game-mode")
    assert "play a turn" in text
    assert "not found" not in text
