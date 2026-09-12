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
import urllib.parse
from pathlib import Path

import pytest

pytest.importorskip("playwright", reason="the browser group is not installed")


import uvicorn  # noqa: E402

from civ_advisor.api.app import create_app  # noqa: E402
from civ_advisor.context_store import PersistentContextStore  # noqa: E402
from civ_advisor.games.civ7 import CIV7  # noqa: E402

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"



def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


CULTURE_COLUMN = 15   # "Culture" in Player_Stats.csv, zero-based


@pytest.fixture(scope="session")
def brief_logs(tmp_path_factory) -> Path:
    """A session where culture is the worst gap, with one logged settlement.

    Several yields trail the field here and the brief folds same-settlement gaps into the
    worst one, so the pilot's card only exists when culture is that gap. The override row
    goes immediately after the row it replaces: a turn number that moves backwards reads
    as a new game and would drop everything before it.
    """
    logs = tmp_path_factory.mktemp("logs")
    shutil.copytree(FIXTURES / "logs_82turns", logs, dirs_exist_ok=True)
    (logs / "CityBuildQueue.csv").write_text(
        "Game Turn, Player, City, Production Added, Current Item, Current Production, "
        "Production Needed, Overflow\n"
        "82, 0, LOC_CITY_NAME_TEST1, 20.0, UNIT_WARRIOR, 25.0, 30, 0.0\n"
    )
    stats = logs / "Player_Stats.csv"
    rows = stats.read_text().splitlines()
    index = next(i for i, r in enumerate(rows)
                 if [c.strip() for c in r.split(",")[:2]] == ["81", "0"])
    cells = rows[index].split(",")
    cells[CULTURE_COLUMN] = " 1.0"
    rows.insert(index + 1, ",".join(cells))
    stats.write_text("\n".join(rows) + "\n")
    return logs


@pytest.fixture(scope="session")
def notes_path(tmp_path_factory) -> Path:
    """A throwaway player record. Never the developer's own file."""
    return tmp_path_factory.mktemp("notes") / "player-context.json"


@pytest.fixture(scope="session")
def server(brief_logs: Path, notes_path: Path):
    """The real app on a real port. No archive root, no commentary worker."""
    port = _free_port()
    app = create_app(brief_logs, poll_interval=60,
                     player_store=PersistentContextStore(path=notes_path), profile=CIV7)
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
    config = uvicorn.Config(create_app(crowded_logs, poll_interval=60, profile=CIV7),
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


@pytest.fixture(scope="session")
def frontier_logs(brief_logs: Path, tmp_path_factory) -> Path:
    """Two city areas far apart, contacts near each, two sharing a tile, and one exposed
    unit of the player's own well away from both.

    Written as real log rows so the whole pipeline runs — the point of the checks is that
    the render path handles two frontiers, not that a stub can be drawn.
    """
    logs = tmp_path_factory.mktemp("frontier")
    shutil.copytree(brief_logs, logs, dirs_exist_ok=True)

    targets = ["Game Turn, Player, Target Type, Unit Type, Target Owner, Target ID, Location"]
    for x, y in ((10, 10), (11, 10), (10, 11), (12, 11)):
        targets.append(f"81, 1, TARGET_ENEMY_CITY, not implemented, 0, 1, {x}:{y}")
    for x, y in ((70, 40), (71, 40), (70, 41)):
        targets.append(f"81, 2, TARGET_ENEMY_CITY, not implemented, 0, 2, {x}:{y}")
    targets.append("81, 1, TARGET_HIGH_PRIORITY_UNIT, not implemented, 0, 900, 40:25")
    (logs / "AI_Targets.csv").write_text("\n".join(targets) + "\n")

    contacts = ["Game Turn, Player, Category, Target Type, Target Info, Unit Info, Extra"]
    plan = [(1, 5001, "UNIT_SPEARMAN", 12, 12), (1, 5002, "UNIT_ARCHER", 13, 12),
            (1, 5003, "UNIT_ARCHER", 13, 12), (2, 5004, "UNIT_IMMORTAL", 72, 41),
            (2, 5005, "UNIT_SPEARMAN", 73, 42), (2, 5006, "UNIT_ARCHER", 74, 43),
            (1, 5007, "UNIT_SCOUT", 41, 26)]
    for player, unit, kind, x, y in plan:
        contacts.append(f"81, {player}, Attack Units, , , {kind} ({unit}), Move To {x} {y}")
    (logs / "AI_Tactical.csv").write_text("\n".join(contacts) + "\n")

    (logs / "UnitOperations.log").write_text(
        "Game Turn, Mode, Player, Unit, Operation\n"
        "081, Adding, 0, UNIT_SCOUT (900), UNITOPERATION_ALERT (1)\n")
    return logs


@pytest.fixture(scope="session")
def frontier_server(frontier_logs: Path):
    port = _free_port()
    config = uvicorn.Config(create_app(frontier_logs, poll_interval=60, profile=CIV7),
                            host="127.0.0.1", port=port, log_level="error")
    running = uvicorn.Server(config)
    thread = threading.Thread(target=running.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 20
    while not running.started:
        if time.monotonic() > deadline:
            raise AssertionError("the frontier fixture server did not start")
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    running.should_exit = True
    thread.join(timeout=10)


@pytest.fixture
def frontier(page, frontier_server):
    """The Intel tab of the two-frontier session."""
    page.set_viewport_size({"width": 1200, "height": 842})
    page.goto(frontier_server)
    page.wait_for_selector("#brief-critical .decision, #brief-cards .decision")
    page.locator('[data-tab="intel"]').click()
    page.wait_for_selector(".view-picker button")
    return page


def _clear_record(base_url: str) -> None:
    """Empty the player record between tests.

    It is deliberately durable and server-side now, and the fixture server is shared, so
    without this one test's acknowledgement would hide the decision every later test
    works on.
    """
    import json
    import urllib.request

    with urllib.request.urlopen(f"{base_url}/api/record") as response:
        record = json.load(response)
    for entry in record["entries"]:
        request = urllib.request.Request(
            f"{base_url}/api/record/{urllib.parse.quote(entry['id'], safe='')}",
            method="DELETE")
        with urllib.request.urlopen(request):
            pass


@pytest.fixture
def dashboard(page, server):
    """The dashboard, loaded, with its first briefing painted and an empty record."""
    _clear_record(server)
    page.set_viewport_size({"width": 1200, "height": 842})
    page.goto(server)
    page.wait_for_selector("#brief-critical .decision")
    page.wait_for_selector('.decision[data-decision*="culture"]')
    return page
