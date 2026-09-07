# Civ VII Turn Advisor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A local web dashboard that reads Civilization VII's own log files each turn and shows rival standings, threats, the legacy-path race, an economy comparison and a ranked, evidence-backed action checklist — with hidden-information ("Oracle") advice labeled and hideable.

**Architecture:** One Python process. `ingest/` parses seven CSV logs into typed rows (per-file error isolation, positional column map for the ragged `Player_Stats.csv`), `state/` merges them into a `GameState` for the current game, `advisors/` are pure functions `GameState → list[Insight]` that also expose summaries for the UI tables, `store.py` rebuilds on file change and fans out SSE events, `api/` is FastAPI, `web/` is a static vanilla-JS page. Dependencies point strictly downward.

**Tech Stack:** Python 3.12, `uv`, FastAPI, uvicorn, pytest, httpx (test client). No JS toolchain.

**Spec:** `docs/superpowers/specs/2026-09-07-civ7-turn-advisor-design.md` — read it first; every task below cites it.

## Global Constraints

- Python `>=3.12`; run everything through `uv run …`. Runtime deps are exactly `fastapi` and `uvicorn`; dev deps `pytest` and `httpx`. Do not add others.
- The program is **read-only** with respect to Civ VII: never write, rename or delete anything under the logs directory.
- Layering: `advisors/*` import only `civ7_advisor.state.models` (and their own package); `ingest/*` import nothing from `state`, `advisors`, `api`; `api/*` is the only place that knows HTTP.
- Player `0` is the human (`GameState.HUMAN`). `complete_through_turn = latest_turn - 1`.
- Every tunable threshold is a module-level UPPER_CASE constant at the top of its advisor module, with a one-line comment.
- Every `Insight` has non-empty `title`, `recommendation` and `why`, and a `provenance` of `FAIR` or `ORACLE` as defined in spec §3.3.
- `Player_Stats.csv` is parsed **by position** (spec §2.1 hazard 1); any row without exactly 25 columns raises `LogFormatError`.
- Tests use the fixture at `tests/fixtures/logs_82turns/` (already in the repo; do not regenerate it). Fixture facts used in assertions: latest turn 82, complete turn 81; player 3 (Napoleon) last seen turn 59; players 1–7 are rivals; independents ≥ 8.
- Commit after every task with the message given in the task.

---

## File structure

```
pyproject.toml
README.md
civ7_advisor/
  __init__.py            version string
  cli.py                 argparse entry point `civ7-advisor`
  store.py               Store: rebuild + SSE fan-out
  ingest/
    __init__.py
    csvfile.py           read_table, latest_game_segment, expect_header, LogFormatError
    columns.py           pinned positional map for Player_Stats.csv
    readers.py           7 readers + their frozen row dataclasses
    load.py              load_logs(dir) -> RawLogs, FileStatus, LOG_FILES
    poller.py            snapshot(), watch()
  state/
    __init__.py
    models.py            Player, PlayerTurn, StrategyStatus, GameState
    build.py             build_state(RawLogs) -> GameState, LEADER_NAMES
  advisors/
    __init__.py          run_all()
    base.py              Insight, Severity, Provenance
    checklist.py         rank()
    threat.py            summarize(), advise()
    victory.py           leaderboards(), committed_paths(), advise()
    economy.py           comparison(), advise()
  api/
    __init__.py
    serialize.py         insight_to_dict, state_to_dict
    app.py               create_app()
  web/
    index.html  style.css  app.js
tests/
  __init__.py  conftest.py  factories.py
  fixtures/logs_82turns/*.csv   (present)
  test_scaffold.py test_ingest_stats.py test_ingest_readers.py test_ingest_load.py
  test_state.py test_checklist.py test_threat.py test_victory.py test_economy.py
  test_e2e.py test_poller.py test_store.py test_api.py test_cli.py
```

---

### Task 1: Project scaffold

**Files:**
- Create: `pyproject.toml`, `civ7_advisor/__init__.py`, `tests/__init__.py`, `tests/conftest.py`, `tests/test_scaffold.py`
- Existing: `.gitignore`, `tests/fixtures/logs_82turns/` (7 CSVs), `docs/`

**Interfaces:**
- Produces: `tests.conftest.FIXTURE_DIR: Path` and pytest fixture `fixture_dir` used by every later test.

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "civ7-advisor"
version = "0.1.0"
description = "Second-screen turn advisor for Civilization VII, driven by the game's own log files"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn>=0.30",
]

[project.scripts]
civ7-advisor = "civ7_advisor.cli:main"

[dependency-groups]
dev = [
    "pytest>=8",
    "httpx>=0.27",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["civ7_advisor"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
```

- [ ] **Step 2: Write the package and test scaffolding**

`civ7_advisor/__init__.py`:
```python
"""Second-screen turn advisor for Civilization VII, driven by the game's own log files."""

__version__ = "0.1.0"
```

`tests/__init__.py`: empty file.

`tests/conftest.py`:
```python
from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "logs_82turns"


@pytest.fixture(scope="session")
def fixture_dir() -> Path:
    return FIXTURE_DIR
```

`tests/test_scaffold.py`:
```python
import civ7_advisor


def test_package_has_version():
    assert civ7_advisor.__version__ == "0.1.0"


def test_fixture_has_all_seven_logs(fixture_dir):
    names = sorted(p.name for p in fixture_dir.glob("*.csv"))
    assert names == [
        "AI_DiplomaticActions.csv",
        "AI_Targets.csv",
        "AI_Victories.csv",
        "Historian.csv",
        "Player_Happiness.csv",
        "Player_Stats.csv",
        "Player_Treasury.csv",
    ]
```

- [ ] **Step 3: Install and run**

Run: `uv sync && uv run pytest -q`
Expected: `2 passed`. `uv.lock` and `.venv/` are created (`.venv/` is git-ignored).

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock civ7_advisor/__init__.py tests/__init__.py tests/conftest.py tests/test_scaffold.py tests/fixtures docs/superpowers
git commit -m "Scaffold civ7-advisor package with fixture logs from a live game"
```

---

### Task 2: CSV core and the `Player_Stats.csv` reader

**Files:**
- Create: `civ7_advisor/ingest/__init__.py`, `civ7_advisor/ingest/csvfile.py`, `civ7_advisor/ingest/columns.py`, `civ7_advisor/ingest/readers.py`
- Test: `tests/test_ingest_stats.py`

**Interfaces:**
- Produces: `csvfile.read_table(path) -> RawTable(path, header: list[str], rows: list[list[str]])`, `csvfile.latest_game_segment(rows, turn_col) -> list[list[str]]`, `csvfile.expect_header(table, expected: list[str]) -> None`, `csvfile.LogFormatError(ValueError)`; `readers.StatsRow` (frozen dataclass, 21 fields listed below) and `readers.read_player_stats(path) -> list[StatsRow]`.

- [ ] **Step 1: Write the failing tests**

`tests/test_ingest_stats.py`:
```python
from pathlib import Path

import pytest

from civ7_advisor.ingest.csvfile import LogFormatError, latest_game_segment, read_table
from civ7_advisor.ingest.readers import read_player_stats


def test_read_table_strips_cells_and_skips_blank_lines(tmp_path: Path):
    p = tmp_path / "t.csv"
    p.write_text("A, B\n1,  2.0\n\n3, 4\n")
    table = read_table(p)
    assert table.header == ["A", "B"]
    assert table.rows == [["1", "2.0"], ["3", "4"]]


def test_read_table_empty_file_raises(tmp_path: Path):
    p = tmp_path / "t.csv"
    p.write_text("")
    with pytest.raises(LogFormatError):
        read_table(p)


def test_latest_game_segment_keeps_rows_after_last_turn_drop():
    rows = [["1", "a"], ["2", "a"], ["3", "a"], ["1", "b"], ["2", "b"]]
    assert latest_game_segment(rows, turn_col=0) == [["1", "b"], ["2", "b"]]


def test_latest_game_segment_single_game_is_unchanged():
    rows = [["1", "a"], ["1", "b"], ["2", "a"]]
    assert latest_game_segment(rows, turn_col=0) == rows


def test_player_stats_fixture_row_count(fixture_dir: Path):
    rows = read_player_stats(fixture_dir / "Player_Stats.csv")
    assert len(rows) == 2523


def test_player_stats_last_row_matches_verified_values(fixture_dir: Path):
    last = read_player_stats(fixture_dir / "Player_Stats.csv")[-1]
    assert (last.turn, last.player) == (82, 0)
    assert (last.cities, last.towns, last.settlement_cap, last.settlements_over_cap) == (1, 1, 4, 0)
    assert (last.urban_pop, last.rural_pop, last.techs) == (6, 12, 9)
    assert (last.land_units, last.naval_units) == (4, 0)
    assert (last.tiles_owned, last.tiles_improved) == (47, 12)
    assert last.gold_balance == 136.0  # cross-checked against Player_Treasury "Gold Balance"
    assert last.science == 15.0
    assert last.culture == 14.0
    assert last.gold == 23.0  # cross-checked against Player_Treasury "Gold Yield"
    assert last.production == 24.0
    assert last.food == 24.0
    assert last.happiness == 20.0  # cross-checked against Player_Happiness "Per Turn Happiness"
    assert last.diplomacy == 10.0


def test_player_stats_wrong_column_count_raises(tmp_path: Path, fixture_dir: Path):
    header = (fixture_dir / "Player_Stats.csv").read_text().splitlines()[0]
    bad = tmp_path / "Player_Stats.csv"
    bad.write_text(header + "\n" + ", ".join(["1"] * 24) + "\n")
    with pytest.raises(LogFormatError, match="expected 25 columns"):
        read_player_stats(bad)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_ingest_stats.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'civ7_advisor.ingest'`.

- [ ] **Step 3: Write the implementation**

`civ7_advisor/ingest/__init__.py`:
```python
"""Readers for Civ VII's per-turn log files. Pure functions: path in, typed rows out."""
```

`civ7_advisor/ingest/csvfile.py`:
```python
"""Low-level CSV access shared by every reader."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


class LogFormatError(ValueError):
    """A log file does not have the shape this reader was pinned against."""


@dataclass(frozen=True)
class RawTable:
    path: Path
    header: list[str]
    rows: list[list[str]]  # data rows; every cell stripped of surrounding whitespace


def read_table(path: Path) -> RawTable:
    """Read a Civ VII CSV: header on row 0, cells stripped, blank lines skipped."""
    with path.open(newline="", encoding="utf-8", errors="replace") as fh:
        reader = csv.reader(fh, skipinitialspace=True)
        rows = [
            [cell.strip() for cell in row]
            for row in reader
            if any(cell.strip() for cell in row)
        ]
    if not rows:
        raise LogFormatError(f"{path.name}: file is empty")
    return RawTable(path=path, header=rows[0], rows=rows[1:])


def latest_game_segment(rows: list[list[str]], turn_col: int) -> list[list[str]]:
    """Keep only the rows from the most recent game.

    Civ VII appends to the same log across games and never truncates it, so
    the turn column climbs, drops back when a new game starts, and climbs
    again. The newest game is everything after the last drop.
    """
    start = 0
    prev: int | None = None
    for index, row in enumerate(rows):
        try:
            turn = int(row[turn_col])
        except (IndexError, ValueError):
            continue
        if prev is not None and turn < prev:
            start = index
        prev = turn
    return rows[start:]


def expect_header(table: RawTable, expected: list[str]) -> None:
    if table.header != expected:
        raise LogFormatError(
            f"{table.path.name}: unexpected header {table.header!r}; "
            f"this version of civ7-advisor expects {expected!r}"
        )
```

`civ7_advisor/ingest/columns.py`:
```python
"""Pinned positional layout of Player_Stats.csv.

The header of this file is ragged: it names 22 columns but rows carry 25.
`TILES:`, `BALANCE:`, `YIELDS:` and `BY TYPE:` are group labels, not columns.
The positions below were verified against a live game (turn 82, player 0):
gold_balance matched Player_Treasury "Gold Balance" (136.0), gold matched its
"Gold Yield" (23.0), and happiness matched Player_Happiness "Per Turn
Happiness" (20). Columns 21-24 are an unlabeled by-type breakdown and are
ignored.
"""

PLAYER_STATS_COLUMN_COUNT = 25

PLAYER_STATS_INT_COLUMNS = {
    "turn": 0,
    "player": 1,
    "cities": 2,
    "towns": 3,
    "settlement_cap": 4,
    "settlements_over_cap": 5,
    "urban_pop": 6,
    "rural_pop": 7,
    "techs": 8,
    "land_units": 9,
    "naval_units": 10,
    "tiles_owned": 11,
    "tiles_improved": 12,
}

PLAYER_STATS_FLOAT_COLUMNS = {
    "gold_balance": 13,
    "science": 14,
    "culture": 15,
    "gold": 16,
    "production": 17,
    "food": 18,
    "happiness": 19,
    "diplomacy": 20,
}
```

`civ7_advisor/ingest/readers.py` (first part; later tasks append to this file):
```python
"""One reader per Civ VII log file. Each is pure: path in, typed rows out.

Every reader returns rows for the most recent game only (see
csvfile.latest_game_segment) and raises LogFormatError when the file does
not match the shape it was pinned against.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .columns import (
    PLAYER_STATS_COLUMN_COUNT,
    PLAYER_STATS_FLOAT_COLUMNS,
    PLAYER_STATS_INT_COLUMNS,
)
from .csvfile import LogFormatError, expect_header, latest_game_segment, read_table


# --- Player_Stats.csv ------------------------------------------------------


@dataclass(frozen=True)
class StatsRow:
    turn: int
    player: int
    cities: int
    towns: int
    settlement_cap: int
    settlements_over_cap: int
    urban_pop: int
    rural_pop: int
    techs: int
    land_units: int
    naval_units: int
    tiles_owned: int
    tiles_improved: int
    gold_balance: float
    science: float
    culture: float
    gold: float
    production: float
    food: float
    happiness: float
    diplomacy: float


def read_player_stats(path: Path) -> list[StatsRow]:
    table = read_table(path)
    out: list[StatsRow] = []
    for row in latest_game_segment(table.rows, turn_col=0):
        if len(row) != PLAYER_STATS_COLUMN_COUNT:
            raise LogFormatError(
                f"{path.name}: expected {PLAYER_STATS_COLUMN_COUNT} columns but a row has "
                f"{len(row)} (row starts {row[:2]}). The game may have changed its log "
                f"format; update civ7_advisor/ingest/columns.py."
            )
        values = {name: int(row[i]) for name, i in PLAYER_STATS_INT_COLUMNS.items()}
        values |= {name: float(row[i]) for name, i in PLAYER_STATS_FLOAT_COLUMNS.items()}
        out.append(StatsRow(**values))
    return out
```

(`Enum` and `expect_header` are imported now because Tasks 3–4 append code to this file that uses them.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_ingest_stats.py -q`
Expected: `7 passed`.

- [ ] **Step 5: Commit**

```bash
git add civ7_advisor/ingest tests/test_ingest_stats.py
git commit -m "Add CSV core and positional Player_Stats reader"
```

---

### Task 3: Readers for treasury, happiness and AI victories

**Files:**
- Modify: `civ7_advisor/ingest/readers.py` (append)
- Test: `tests/test_ingest_readers.py`

**Interfaces:**
- Produces: `TreasuryRow(turn, player, gold_balance, unit_maintenance, building_maintenance, total_maintenance, gold_yield)`, `read_treasury(path)`; `HappinessRow(turn, player, golden_age: bool, threshold, total, per_turn, bonus)`, `read_happiness(path)`; `VictoryRow(turn, player, owner_key, strategy, status, weight)`, `canonical_strategy(raw) -> str`, `read_victories(path)`.

- [ ] **Step 1: Write the failing tests**

`tests/test_ingest_readers.py`:
```python
from pathlib import Path

import pytest

from civ7_advisor.ingest.csvfile import LogFormatError
from civ7_advisor.ingest.readers import (
    HappinessRow,
    TreasuryRow,
    VictoryRow,
    canonical_strategy,
    read_happiness,
    read_treasury,
    read_victories,
)


def test_treasury_fixture(fixture_dir: Path):
    rows = read_treasury(fixture_dir / "Player_Treasury.csv")
    assert len(rows) == 2523
    assert rows[-1] == TreasuryRow(
        turn=82, player=0, gold_balance=136.0, unit_maintenance=2,
        building_maintenance=2, total_maintenance=4, gold_yield=23.0,
    )


def test_treasury_header_mismatch_raises(tmp_path: Path):
    p = tmp_path / "Player_Treasury.csv"
    p.write_text("Turn, Player, Something Else\n1, 0, 3\n")
    with pytest.raises(LogFormatError, match="unexpected header"):
        read_treasury(p)


def test_happiness_fixture_covers_only_major_players(fixture_dir: Path):
    rows = read_happiness(fixture_dir / "Player_Happiness.csv")
    assert len(rows) == 646
    assert {r.player for r in rows} == set(range(8))
    assert rows[-1] == HappinessRow(
        turn=82, player=0, golden_age=False, threshold=1532, total=1058, per_turn=20, bonus=0,
    )
    assert any(r.golden_age for r in rows)  # the fixture has 102 "Yes" rows


def test_canonical_strategy_takes_last_segment():
    assert canonical_strategy("CD_VICTORY_STRATEGY_SCIENCE") == "SCIENCE"
    assert canonical_strategy("TRIUMPH_STRATEGY_ALLAGES_ESPIONAGE") == "ESPIONAGE"


def test_victories_fixture_is_event_based_with_canonical_strategies(fixture_dir: Path):
    rows = read_victories(fixture_dir / "AI_Victories.csv")
    assert len(rows) == 77
    assert rows[0] == VictoryRow(
        turn=1, player=1, owner_key="LOC_LEADER_IBN_BATTUTA_NAME",
        strategy="MILITARY", status="Following", weight=39,
    )
    assert {r.strategy for r in rows} == {"MILITARY", "SCIENCE", "CULTURAL", "ECONOMIC", "ESPIONAGE"}
    assert {r.status for r in rows} == {"Following", "Stopped", "Forbidden"}
    assert rows[-1] == VictoryRow(
        turn=80, player=1, owner_key="LOC_LEADER_IBN_BATTUTA_NAME",
        strategy="CULTURAL", status="Stopped", weight=0,
    )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_ingest_readers.py -q`
Expected: FAIL with `ImportError: cannot import name 'HappinessRow'`.

- [ ] **Step 3: Append the readers**

Append to `civ7_advisor/ingest/readers.py`:
```python
# --- Player_Treasury.csv ---------------------------------------------------

TREASURY_HEADER = [
    "Turn", "Player", "Gold Balance", "Unit Maintenance",
    "Building Maintenance", "Total Maintenance", "Gold Yield",
]


@dataclass(frozen=True)
class TreasuryRow:
    turn: int
    player: int
    gold_balance: float
    unit_maintenance: int
    building_maintenance: int
    total_maintenance: int
    gold_yield: float


def read_treasury(path: Path) -> list[TreasuryRow]:
    table = read_table(path)
    expect_header(table, TREASURY_HEADER)
    return [
        TreasuryRow(int(r[0]), int(r[1]), float(r[2]), int(r[3]), int(r[4]), int(r[5]), float(r[6]))
        for r in latest_game_segment(table.rows, turn_col=0)
    ]


# --- Player_Happiness.csv (majors only) ------------------------------------

HAPPINESS_HEADER = [
    "Game Turn", "Player", "Golden Age", "Threshold",
    "Total Happiness", "Per Turn Happiness", "Happiness Bonus",
]


@dataclass(frozen=True)
class HappinessRow:
    turn: int
    player: int
    golden_age: bool
    threshold: int
    total: int
    per_turn: int
    bonus: int


def read_happiness(path: Path) -> list[HappinessRow]:
    table = read_table(path)
    expect_header(table, HAPPINESS_HEADER)
    return [
        HappinessRow(int(r[0]), int(r[1]), r[2] == "Yes", int(r[3]), int(r[4]), int(r[5]), int(r[6]))
        for r in latest_game_segment(table.rows, turn_col=0)
    ]


# --- AI_Victories.csv (event-based) ----------------------------------------

VICTORIES_HEADER = ["Game Turn", "Player", "Owner", "Strategy", "Status", "Percentage"]


@dataclass(frozen=True)
class VictoryRow:
    turn: int
    player: int
    owner_key: str   # e.g. LOC_LEADER_CONFUCIUS_NAME
    strategy: str    # canonical: SCIENCE, CULTURAL, MILITARY, ECONOMIC, ESPIONAGE
    status: str      # Following | Stopped | Forbidden
    weight: int      # the AI's priority weight for this strategy (NOT progress)


def canonical_strategy(raw: str) -> str:
    """CD_VICTORY_STRATEGY_SCIENCE -> SCIENCE; TRIUMPH_STRATEGY_ALLAGES_ESPIONAGE -> ESPIONAGE."""
    return raw.rsplit("_", 1)[-1]


def read_victories(path: Path) -> list[VictoryRow]:
    table = read_table(path)
    expect_header(table, VICTORIES_HEADER)
    return [
        VictoryRow(int(r[0]), int(r[1]), r[2], canonical_strategy(r[3]), r[4], int(r[5]))
        for r in latest_game_segment(table.rows, turn_col=0)
    ]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_ingest_readers.py -q`
Expected: `5 passed`.

- [ ] **Step 5: Commit**

```bash
git add civ7_advisor/ingest/readers.py tests/test_ingest_readers.py
git commit -m "Add treasury, happiness and AI victory readers"
```

---

### Task 4: Readers for diplomacy, targets and historian

**Files:**
- Modify: `civ7_advisor/ingest/readers.py` (append)
- Modify: `tests/test_ingest_readers.py` (append)

**Interfaces:**
- Produces: `IntentKind(Enum)` with `SCORED`, `EXECUTED`; `DiplomacyRow(turn, actor, action, target: int | None, kind: IntentKind, score: float | None)`, `canonical_action(raw) -> tuple[str, IntentKind]`, `read_diplomacy(path)`; `TargetRow(turn, player, target_type, owner, target_id, x, y)`, `read_targets(path)`; `HistorianRow(type, age, turn, x, y, player, opponent: int | None, unit: str | None, constructible: str | None)`, `read_historian(path)`.

- [ ] **Step 1: Append the failing tests**

Append to `tests/test_ingest_readers.py` (and extend the import block to include `DiplomacyRow, HistorianRow, IntentKind, TargetRow, canonical_action, read_diplomacy, read_historian, read_targets`):
```python
def test_canonical_action_handles_all_three_shapes():
    assert canonical_action("DIPLOMACY_ACTION_OPEN_BORDERS") == ("OPEN_BORDERS", IntentKind.SCORED)
    assert canonical_action("LOC_DIPLOMACY_ACTION_DECLARE_WAR_NAME") == ("DECLARE_WAR", IntentKind.SCORED)
    assert canonical_action("ACTION DIPLOMACY_ACTION_DECLARE_WAR") == ("DECLARE_WAR", IntentKind.EXECUTED)


def test_diplomacy_fixture(fixture_dir: Path):
    rows = read_diplomacy(fixture_dir / "AI_DiplomaticActions.csv")
    assert len(rows) == 2422
    assert sum(r.kind is IntentKind.EXECUTED for r in rows) == 117
    assert all(not r.action.startswith(("LOC_", "DIPLOMACY_ACTION_", "ACTION ")) for r in rows)
    assert DiplomacyRow(80, 4, "DECLARE_WAR", 0, IntentKind.EXECUTED, None) in rows
    assert DiplomacyRow(81, 1, "DECLARE_WAR", None, IntentKind.EXECUTED, None) in rows  # raw target -1
    assert DiplomacyRow(81, 7, "DECLARE_WAR", 1, IntentKind.SCORED, 31.109) in rows


def test_targets_fixture(fixture_dir: Path):
    rows = read_targets(fixture_dir / "AI_Targets.csv")
    assert len(rows) == 47025
    assert rows[0] == TargetRow(1, 1, "TARGET_NEUTRAL_CITY", 63, 2687015, 73, 13)
    assert rows[-1] == TargetRow(82, 0, "TARGET_NEUTRAL_CITY", 63, 262147, 51, 47)


def test_historian_fixture(fixture_dir: Path):
    rows = read_historian(fixture_dir / "Historian.csv")
    assert len(rows) == 190
    assert rows[0] == HistorianRow("DISCOVERY_TRIGGERED", "AGE_ANTIQUITY", 3, 73, 13, 1, None, None, "Ruin")
    assert rows[-1] == HistorianRow("UNIT_KILLED", "AGE_ANTIQUITY", 81, 53, 12, 7, 22, "Hoplite", None)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_ingest_readers.py -q`
Expected: FAIL with `ImportError: cannot import name 'DiplomacyRow'`.

- [ ] **Step 3: Append the readers**

Append to `civ7_advisor/ingest/readers.py`:
```python
# --- AI_DiplomaticActions.csv (three row shapes) ---------------------------

DIPLOMACY_HEADER = ["Game Turn", "Player", "Diplomatic Action", "Target", "Score"]


class IntentKind(Enum):
    SCORED = "scored"      # the AI evaluated this action and gave it a score
    EXECUTED = "executed"  # the AI actually performed it ("ACTION ..., TOKENS n")


@dataclass(frozen=True)
class DiplomacyRow:
    turn: int
    actor: int
    action: str          # canonical, e.g. DECLARE_WAR, OPEN_BORDERS
    target: int | None   # None when the log says -1
    kind: IntentKind
    score: float | None  # None for EXECUTED rows


def canonical_action(raw: str) -> tuple[str, IntentKind]:
    """Normalize the three shapes of the 'Diplomatic Action' column.

    'DIPLOMACY_ACTION_OPEN_BORDERS'         -> ('OPEN_BORDERS', SCORED)
    'LOC_DIPLOMACY_ACTION_DECLARE_WAR_NAME' -> ('DECLARE_WAR', SCORED)
    'ACTION DIPLOMACY_ACTION_DECLARE_WAR'   -> ('DECLARE_WAR', EXECUTED)
    """
    kind = IntentKind.SCORED
    name = raw
    if name.startswith("ACTION "):
        kind = IntentKind.EXECUTED
        name = name[len("ACTION "):]
    name = name.removeprefix("LOC_").removesuffix("_NAME").removeprefix("DIPLOMACY_ACTION_")
    return name, kind


def _player_or_none(cell: str) -> int | None:
    value = int(cell)
    return None if value < 0 else value


def read_diplomacy(path: Path) -> list[DiplomacyRow]:
    table = read_table(path)
    expect_header(table, DIPLOMACY_HEADER)
    out: list[DiplomacyRow] = []
    for r in latest_game_segment(table.rows, turn_col=0):
        action, kind = canonical_action(r[2])
        score = None if kind is IntentKind.EXECUTED else float(r[4])
        out.append(DiplomacyRow(int(r[0]), int(r[1]), action, _player_or_none(r[3]), kind, score))
    return out


# --- AI_Targets.csv --------------------------------------------------------

TARGETS_HEADER = [
    "Game Turn", "Player", "Target Type", "Unit Type", "Target Owner", "Target ID", "Location",
]


@dataclass(frozen=True)
class TargetRow:
    turn: int
    player: int        # the AI doing the targeting
    target_type: str   # e.g. TARGET_ENEMY_CITY, TARGET_HIGH_PRIORITY_UNIT
    owner: int         # player who owns the targeted plot or unit
    target_id: int
    x: int
    y: int


def read_targets(path: Path) -> list[TargetRow]:
    table = read_table(path)
    expect_header(table, TARGETS_HEADER)
    out: list[TargetRow] = []
    for r in latest_game_segment(table.rows, turn_col=0):
        x, y = r[6].split(":")
        out.append(TargetRow(int(r[0]), int(r[1]), r[2], int(r[4]), int(r[5]), int(x), int(y)))
    return out


# --- Historian.csv ---------------------------------------------------------

HISTORIAN_HEADER = ["Type", "Age", "Turn", "X", "Y", "Player", "Opponent", "Unit", "Constructible"]


@dataclass(frozen=True)
class HistorianRow:
    type: str                  # UNIT_KILLED, SHIP_SUNK, DISCOVERY_TRIGGERED, ...
    age: str
    turn: int
    x: int
    y: int
    player: int                # for kills: the owner of the unit that died
    opponent: int | None       # for kills: the killer; None when the log says -1
    unit: str | None           # None for NO_UNIT
    constructible: str | None  # None for NO_CONSTRUCTIBLE


def read_historian(path: Path) -> list[HistorianRow]:
    table = read_table(path)
    expect_header(table, HISTORIAN_HEADER)
    return [
        HistorianRow(
            r[0], r[1], int(r[2]), int(r[3]), int(r[4]), int(r[5]), _player_or_none(r[6]),
            None if r[7] == "NO_UNIT" else r[7],
            None if r[8] == "NO_CONSTRUCTIBLE" else r[8],
        )
        for r in latest_game_segment(table.rows, turn_col=2)
    ]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_ingest_readers.py -q`
Expected: `9 passed`.

- [ ] **Step 5: Commit**

```bash
git add civ7_advisor/ingest/readers.py tests/test_ingest_readers.py
git commit -m "Add diplomacy, targets and historian readers"
```

---

### Task 5: `load_logs` with per-file error isolation

**Files:**
- Create: `civ7_advisor/ingest/load.py`
- Test: `tests/test_ingest_load.py`

**Interfaces:**
- Produces: `FileStatus(name, ok, rows, latest_turn: int | None, error: str | None = None)` (frozen), `RawLogs` (mutable dataclass with list fields `stats, treasury, happiness, victories, diplomacy, targets, historian` and `files: dict[str, FileStatus]`), `LOG_FILES: list[str]` (the seven file names), `load_logs(logs_dir: Path) -> RawLogs`.

- [ ] **Step 1: Write the failing tests**

`tests/test_ingest_load.py`:
```python
import shutil
from pathlib import Path

from civ7_advisor.ingest.load import LOG_FILES, load_logs


def test_load_logs_fixture_all_ok(fixture_dir: Path):
    raw = load_logs(fixture_dir)
    assert set(raw.files) == set(LOG_FILES)
    assert all(fs.ok for fs in raw.files.values())
    assert raw.files["Player_Stats.csv"].rows == 2523
    assert raw.files["Player_Stats.csv"].latest_turn == 82
    assert raw.files["AI_Victories.csv"].latest_turn == 80
    assert len(raw.targets) == 47025


def test_load_logs_isolates_a_broken_file(tmp_path: Path, fixture_dir: Path):
    for name in LOG_FILES:
        shutil.copy(fixture_dir / name, tmp_path / name)
    (tmp_path / "Player_Treasury.csv").write_text("Turn, Player, Broken\n1, 0, x\n")
    raw = load_logs(tmp_path)
    assert raw.files["Player_Treasury.csv"].ok is False
    assert "unexpected header" in raw.files["Player_Treasury.csv"].error
    assert raw.treasury == []
    assert raw.files["Player_Stats.csv"].ok is True
    assert len(raw.stats) == 2523


def test_load_logs_reports_missing_files(tmp_path: Path):
    raw = load_logs(tmp_path)
    assert all(fs.ok is False and fs.error == "file not found" for fs in raw.files.values())
    assert raw.stats == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_ingest_load.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'civ7_advisor.ingest.load'`.

- [ ] **Step 3: Write the implementation**

`civ7_advisor/ingest/load.py`:
```python
"""Load every log file the advisor uses, isolating failures per file."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .csvfile import LogFormatError
from .readers import (
    DiplomacyRow,
    HappinessRow,
    HistorianRow,
    StatsRow,
    TargetRow,
    TreasuryRow,
    VictoryRow,
    read_diplomacy,
    read_happiness,
    read_historian,
    read_player_stats,
    read_targets,
    read_treasury,
    read_victories,
)

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class FileStatus:
    name: str
    ok: bool
    rows: int
    latest_turn: int | None
    error: str | None = None


@dataclass
class RawLogs:
    stats: list[StatsRow] = field(default_factory=list)
    treasury: list[TreasuryRow] = field(default_factory=list)
    happiness: list[HappinessRow] = field(default_factory=list)
    victories: list[VictoryRow] = field(default_factory=list)
    diplomacy: list[DiplomacyRow] = field(default_factory=list)
    targets: list[TargetRow] = field(default_factory=list)
    historian: list[HistorianRow] = field(default_factory=list)
    files: dict[str, FileStatus] = field(default_factory=dict)


# (file name, RawLogs attribute, reader)
READERS: list[tuple[str, str, Callable[[Path], list]]] = [
    ("Player_Stats.csv", "stats", read_player_stats),
    ("Player_Treasury.csv", "treasury", read_treasury),
    ("Player_Happiness.csv", "happiness", read_happiness),
    ("AI_Victories.csv", "victories", read_victories),
    ("AI_DiplomaticActions.csv", "diplomacy", read_diplomacy),
    ("AI_Targets.csv", "targets", read_targets),
    ("Historian.csv", "historian", read_historian),
]
LOG_FILES = [name for name, _, _ in READERS]


def load_logs(logs_dir: Path) -> RawLogs:
    """Read all seven logs. A file that fails to parse is dropped for this load
    (its FileStatus says why) while every other file still contributes."""
    raw = RawLogs()
    for name, attr, reader in READERS:
        path = logs_dir / name
        try:
            rows = reader(path)
        except FileNotFoundError:
            raw.files[name] = FileStatus(name, False, 0, None, "file not found")
            continue
        except (LogFormatError, ValueError, IndexError) as exc:
            log.warning("%s: dropping file for this rebuild: %s", name, exc)
            raw.files[name] = FileStatus(name, False, 0, None, str(exc))
            continue
        setattr(raw, attr, rows)
        raw.files[name] = FileStatus(
            name, True, len(rows), max((r.turn for r in rows), default=None)
        )
    return raw
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_ingest_load.py -q`
Expected: `3 passed`.

- [ ] **Step 5: Commit**

```bash
git add civ7_advisor/ingest/load.py tests/test_ingest_load.py
git commit -m "Add load_logs with per-file error isolation"
```

---

### Task 6: State models and `build_state`

**Files:**
- Create: `civ7_advisor/state/__init__.py`, `civ7_advisor/state/models.py`, `civ7_advisor/state/build.py`
- Modify: `tests/conftest.py` (add `fixture_state`)
- Test: `tests/test_state.py`

**Interfaces:**
- Consumes: `RawLogs`, `FileStatus` from `ingest.load`; row types from `ingest.readers`.
- Produces (all in `state.models`): `PlayerKind(Enum)` `HUMAN|RIVAL|INDEPENDENT`; `Player(id, name, kind, alive, last_seen_turn)`; `PlayerTurn` (21 stats fields identical in name to `StatsRow` + optional `unit_maintenance, building_maintenance, total_maintenance, golden_age, happiness_threshold, happiness_total`; properties `settlements`, `military_units`, `net_gold`, `celebration_progress`); `StrategyStatus(player, strategy, status, weight, since_turn)` with property `following`; `GameState` with fields `players, latest_turn, complete_through_turn, turns, strategies, intents, targets, events, files`, class attr `HUMAN = 0`, methods `human()`, `rivals(alive_only=True)`, `majors()`, `at(player, turn=None)`, `series(player, attr, n)`; re-exports `IntentKind`, `FileStatus`, and aliases `DiplomaticIntent`, `Target`, `HistorianEvent`. In `state.build`: `build_state(raw) -> GameState`, `LEADER_NAMES`, `display_name(key)`.

- [ ] **Step 1: Add the shared fixture and write the failing tests**

Append to `tests/conftest.py`:
```python
from civ7_advisor.ingest.load import load_logs  # noqa: E402
from civ7_advisor.state.build import build_state  # noqa: E402


@pytest.fixture(scope="session")
def fixture_state(fixture_dir: Path):
    """GameState built from the live-game fixture: latest turn 82, complete turn 81."""
    return build_state(load_logs(fixture_dir))
```

`tests/test_state.py`:
```python
import pytest

from civ7_advisor.ingest.load import RawLogs
from civ7_advisor.state.build import build_state, display_name
from civ7_advisor.state.models import PlayerKind, StrategyStatus


def test_turn_bookkeeping(fixture_state):
    assert fixture_state.latest_turn == 82
    assert fixture_state.complete_through_turn == 81


def test_player_classification(fixture_state):
    s = fixture_state
    assert s.human().kind is PlayerKind.HUMAN and s.human().alive
    assert [p.id for p in s.rivals()] == [1, 2, 4, 5, 6, 7]
    assert [p.id for p in s.rivals(alive_only=False)] == [1, 2, 3, 4, 5, 6, 7]
    napoleon = s.players[3]
    assert (napoleon.name, napoleon.kind, napoleon.alive, napoleon.last_seen_turn) == (
        "Napoleon", PlayerKind.RIVAL, False, 59,
    )
    assert s.players[4].name == "José Rizal"
    assert s.players[7].name == "Catherine"
    assert s.players[9].kind is PlayerKind.INDEPENDENT
    assert [p.id for p in s.majors()] == [0, 1, 2, 4, 5, 6, 7]


def test_player_turn_merges_treasury_and_happiness(fixture_state):
    pt = fixture_state.at(0)  # defaults to the complete turn, 81
    assert pt.turn == 81
    assert pt.land_units == 5 and pt.science == 15.0
    assert (pt.unit_maintenance, pt.building_maintenance, pt.total_maintenance) == (2, 2, 4)
    assert pt.net_gold == 19.0  # gold 23.0 - maintenance 4
    assert (pt.happiness_total, pt.happiness_threshold, pt.golden_age) == (1038, 1532, False)
    assert pt.celebration_progress == pytest.approx(1038 / 1532)
    assert pt.settlements == 2 and pt.military_units == 5


def test_independent_has_treasury_but_no_happiness(fixture_state):
    pt = fixture_state.at(9)
    assert pt is not None and pt.total_maintenance is not None  # treasury covers all players
    assert pt.happiness_threshold is None and pt.celebration_progress is None


def test_strategies_fold_to_current_status(fixture_state):
    st = fixture_state.strategies
    assert st[4]["CULTURAL"] == StrategyStatus(4, "CULTURAL", "Following", 100, since_turn=74)
    assert st[1]["CULTURAL"].status == "Stopped" and st[1]["CULTURAL"].since_turn == 80
    assert st[7]["SCIENCE"].weight == 100 and st[7]["SCIENCE"].following
    assert 0 not in st  # the human has no AI strategy rows


def test_series_reads_backwards_from_complete_turn(fixture_state):
    assert fixture_state.series(0, "land_units", 3) == [7.0, 6.0, 5.0]  # turns 79, 80, 81
    assert fixture_state.series(3, "land_units", 3) == []  # Napoleon is gone


def test_raw_rows_are_carried_through(fixture_state):
    assert len(fixture_state.intents) == 2422
    assert len(fixture_state.targets) == 47025
    assert len(fixture_state.events) == 190
    assert set(fixture_state.files) and all(f.ok for f in fixture_state.files.values())


def test_empty_logs_give_empty_state():
    state = build_state(RawLogs())
    assert state.latest_turn == 0 and state.players == {} and state.human() is None
    assert state.rivals() == [] and state.majors() == [] and state.at(0) is None


def test_display_name_fallback():
    assert display_name("LOC_LEADER_CONFUCIUS_NAME") == "Confucius"
    assert display_name("LOC_LEADER_SOME_NEW_LEADER_NAME") == "Some New Leader"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_state.py -q`
Expected: FAIL at collection with `ModuleNotFoundError: No module named 'civ7_advisor.state'`.

- [ ] **Step 3: Write the models**

`civ7_advisor/state/__init__.py`:
```python
"""Typed snapshot of the current game, built from raw log rows."""
```

`civ7_advisor/state/models.py`:
```python
"""Typed snapshot of the current game. Advisors import only this module."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import ClassVar

from civ7_advisor.ingest.load import FileStatus
from civ7_advisor.ingest.readers import DiplomacyRow, HistorianRow, IntentKind, TargetRow

# Row types advisors need, re-exported under domain names.
DiplomaticIntent = DiplomacyRow
Target = TargetRow
HistorianEvent = HistorianRow

__all__ = [
    "DiplomaticIntent", "FileStatus", "GameState", "HistorianEvent", "IntentKind",
    "Player", "PlayerKind", "PlayerTurn", "StrategyStatus", "Target",
]


class PlayerKind(Enum):
    HUMAN = "human"
    RIVAL = "rival"
    INDEPENDENT = "independent"


@dataclass(frozen=True)
class Player:
    id: int
    name: str
    kind: PlayerKind
    alive: bool
    last_seen_turn: int


@dataclass(frozen=True)
class PlayerTurn:
    """One player's per-turn stats, with treasury and happiness rows merged in when present."""

    turn: int
    player: int
    cities: int
    towns: int
    settlement_cap: int
    settlements_over_cap: int
    urban_pop: int
    rural_pop: int
    techs: int
    land_units: int
    naval_units: int
    tiles_owned: int
    tiles_improved: int
    gold_balance: float
    science: float
    culture: float
    gold: float
    production: float
    food: float
    happiness: float
    diplomacy: float
    unit_maintenance: int | None = None
    building_maintenance: int | None = None
    total_maintenance: int | None = None
    golden_age: bool | None = None
    happiness_threshold: int | None = None
    happiness_total: int | None = None

    @property
    def settlements(self) -> int:
        return self.cities + self.towns

    @property
    def military_units(self) -> int:
        return self.land_units + self.naval_units

    @property
    def net_gold(self) -> float | None:
        if self.total_maintenance is None:
            return None
        return self.gold - self.total_maintenance

    @property
    def celebration_progress(self) -> float | None:
        if not self.happiness_threshold or self.happiness_total is None:
            return None
        return self.happiness_total / self.happiness_threshold


@dataclass(frozen=True)
class StrategyStatus:
    player: int
    strategy: str   # SCIENCE, CULTURAL, MILITARY, ECONOMIC, ESPIONAGE
    status: str     # Following | Stopped | Forbidden
    weight: int     # the AI's priority weight, not progress
    since_turn: int

    @property
    def following(self) -> bool:
        return self.status == "Following"


@dataclass
class GameState:
    players: dict[int, Player] = field(default_factory=dict)
    latest_turn: int = 0
    complete_through_turn: int = 0
    turns: dict[int, dict[int, PlayerTurn]] = field(default_factory=dict)  # turn -> player -> stats
    strategies: dict[int, dict[str, StrategyStatus]] = field(default_factory=dict)  # player -> path
    intents: list[DiplomaticIntent] = field(default_factory=list)
    targets: list[Target] = field(default_factory=list)
    events: list[HistorianEvent] = field(default_factory=list)
    files: dict[str, FileStatus] = field(default_factory=dict)

    HUMAN: ClassVar[int] = 0

    def human(self) -> Player | None:
        return self.players.get(self.HUMAN)

    def rivals(self, alive_only: bool = True) -> list[Player]:
        return [
            p for p in sorted(self.players.values(), key=lambda p: p.id)
            if p.kind is PlayerKind.RIVAL and (p.alive or not alive_only)
        ]

    def majors(self) -> list[Player]:
        """The human plus every living rival, human first."""
        human = self.human()
        return ([human] if human else []) + self.rivals()

    def at(self, player: int, turn: int | None = None) -> PlayerTurn | None:
        t = self.complete_through_turn if turn is None else turn
        return self.turns.get(t, {}).get(player)

    def series(self, player: int, attr: str, n: int) -> list[float]:
        """`attr` over the last n complete turns, oldest first; turns without a row are skipped."""
        t = self.complete_through_turn
        out: list[float] = []
        for turn in range(t - n + 1, t + 1):
            pt = self.turns.get(turn, {}).get(player)
            if pt is not None:
                out.append(float(getattr(pt, attr)))
        return out
```

- [ ] **Step 4: Write the builder**

`civ7_advisor/state/build.py`:
```python
"""Turn raw log rows into a GameState for the current game."""
from __future__ import annotations

from dataclasses import asdict

from civ7_advisor.ingest.load import RawLogs

from .models import GameState, Player, PlayerKind, PlayerTurn, StrategyStatus

INDEPENDENT_KEY = "LOC_CIVILIZATION_INDEPENDENT_NAME"

LEADER_NAMES = {
    "LOC_LEADER_IBN_BATTUTA_NAME": "Ibn Battuta",
    "LOC_LEADER_HARRIET_TUBMAN_NAME": "Harriet Tubman",
    "LOC_LEADER_NAPOLEON_NAME": "Napoleon",
    "LOC_LEADER_JOSE_RIZAL_NAME": "José Rizal",
    "LOC_LEADER_TRUNG_TRAC_NAME": "Trưng Trắc",
    "LOC_LEADER_CONFUCIUS_NAME": "Confucius",
    "LOC_LEADER_CATHERINE_NAME": "Catherine",
    "LOC_LEADER_ADA_LOVELACE_NAME": "Ada Lovelace",
    "LOC_LEADER_AMINA_NAME": "Amina",
    "LOC_LEADER_ASHOKA_NAME": "Ashoka",
    "LOC_LEADER_AUGUSTUS_NAME": "Augustus",
    "LOC_LEADER_BENJAMIN_FRANKLIN_NAME": "Benjamin Franklin",
    "LOC_LEADER_CHARLEMAGNE_NAME": "Charlemagne",
    "LOC_LEADER_FRIEDRICH_NAME": "Friedrich",
    "LOC_LEADER_GENGHIS_KHAN_NAME": "Genghis Khan",
    "LOC_LEADER_HATSHEPSUT_NAME": "Hatshepsut",
    "LOC_LEADER_HIMIKO_NAME": "Himiko",
    "LOC_LEADER_ISABELLA_NAME": "Isabella",
    "LOC_LEADER_LAFAYETTE_NAME": "Lafayette",
    "LOC_LEADER_MACHIAVELLI_NAME": "Machiavelli",
    "LOC_LEADER_PACHACUTI_NAME": "Pachacuti",
    "LOC_LEADER_SIMON_BOLIVAR_NAME": "Simón Bolívar",
    "LOC_LEADER_TECUMSEH_NAME": "Tecumseh",
    "LOC_LEADER_XERXES_NAME": "Xerxes",
}


def display_name(key: str) -> str:
    """Map a LOC_LEADER_*_NAME key to a display name; unknown keys are title-cased."""
    if key in LEADER_NAMES:
        return LEADER_NAMES[key]
    core = key.removeprefix("LOC_LEADER_").removeprefix("LOC_").removesuffix("_NAME")
    return core.replace("_", " ").title()


def build_state(raw: RawLogs) -> GameState:
    state = GameState(files=dict(raw.files))
    if not raw.stats:
        return state

    state.latest_turn = max(r.turn for r in raw.stats)
    state.complete_through_turn = max(state.latest_turn - 1, 0)

    # Per-turn stats, with treasury and happiness merged on (turn, player).
    treasury = {(r.turn, r.player): r for r in raw.treasury}
    happiness = {(r.turn, r.player): r for r in raw.happiness}
    for s in raw.stats:
        extra: dict = {}
        tr = treasury.get((s.turn, s.player))
        if tr is not None:
            extra |= dict(
                unit_maintenance=tr.unit_maintenance,
                building_maintenance=tr.building_maintenance,
                total_maintenance=tr.total_maintenance,
            )
        hp = happiness.get((s.turn, s.player))
        if hp is not None:
            extra |= dict(golden_age=hp.golden_age, happiness_threshold=hp.threshold, happiness_total=hp.total)
        state.turns.setdefault(s.turn, {})[s.player] = PlayerTurn(**asdict(s), **extra)

    # Players: 0 is human; a LOC_LEADER owner key or a happiness row marks a rival;
    # everyone else is an independent people.
    owner_keys = {r.player: r.owner_key for r in raw.victories}
    happiness_players = {r.player for r in raw.happiness}
    last_seen: dict[int, int] = {}
    for s in raw.stats:
        last_seen[s.player] = max(last_seen.get(s.player, 0), s.turn)
    for pid, seen in sorted(last_seen.items()):
        key = owner_keys.get(pid)
        has_leader_key = key is not None and key != INDEPENDENT_KEY
        if pid == GameState.HUMAN:
            kind, name = PlayerKind.HUMAN, "You"
        elif has_leader_key or pid in happiness_players:
            kind = PlayerKind.RIVAL
            name = display_name(key) if has_leader_key else f"Player {pid}"
        else:
            kind, name = PlayerKind.INDEPENDENT, f"Independent {pid}"
        state.players[pid] = Player(
            id=pid, name=name, kind=kind,
            alive=seen >= state.complete_through_turn, last_seen_turn=seen,
        )

    # Strategies are change events; fold them in turn order to the current status.
    for v in sorted(raw.victories, key=lambda r: r.turn):
        state.strategies.setdefault(v.player, {})[v.strategy] = StrategyStatus(
            v.player, v.strategy, v.status, v.weight, since_turn=v.turn,
        )

    state.intents = list(raw.diplomacy)
    state.targets = list(raw.targets)
    state.events = list(raw.historian)
    return state
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_state.py -q`
Expected: `9 passed`.

- [ ] **Step 6: Commit**

```bash
git add civ7_advisor/state tests/conftest.py tests/test_state.py
git commit -m "Add GameState models and build_state"
```

---

### Task 7: Advisor base types, checklist ranking, and test factories

**Files:**
- Create: `civ7_advisor/advisors/__init__.py` (placeholder docstring only — `run_all` arrives in Task 11), `civ7_advisor/advisors/base.py`, `civ7_advisor/advisors/checklist.py`, `tests/factories.py`
- Test: `tests/test_checklist.py`

**Interfaces:**
- Produces: `base.Provenance(Enum)` `FAIR="fair"`, `ORACLE="oracle"`; `base.Severity(IntEnum)` `INFO=0, ADVISE=1, WARN=2, CRITICAL=3`; `base.Insight(id, advisor, severity, provenance, title, recommendation, why, turn, subject_player=None)` frozen; `checklist.rank(insights) -> list[Insight]`; test helpers in `tests/factories.py`: `insight(...)`, `player_turn(turn, player, **overrides)`, `game_state(turn=10, rivals=None, human_stats=None, rival_stats=None, history_turns=1)`, `scored_war(turn, actor, target=0, score=202.0)`, `executed_war(turn, actor, target=0)`, `kill(turn, victim, killer, unit="Warrior", x=10, y=10)`, `city_target(turn, player, owner=0, x=10, y=10, target_type="TARGET_ENEMY_CITY")`, `strategy(player, path, weight, status="Following", since=1)`.

- [ ] **Step 1: Write the factories and the failing tests**

`tests/factories.py`:
```python
"""Small builders for hand-made GameStates in advisor tests."""
from __future__ import annotations

from civ7_advisor.advisors.base import Insight, Provenance, Severity
from civ7_advisor.ingest.readers import DiplomacyRow, HistorianRow, IntentKind, TargetRow
from civ7_advisor.state.models import GameState, Player, PlayerKind, PlayerTurn, StrategyStatus


def insight(
    id: str = "x", advisor: str = "threat", severity: Severity = Severity.INFO,
    provenance: Provenance = Provenance.FAIR, turn: int = 10, **kw,
) -> Insight:
    return Insight(
        id=id, advisor=advisor, severity=severity, provenance=provenance,
        title=kw.get("title", id), recommendation=kw.get("recommendation", "do it"),
        why=kw.get("why", "because"), turn=turn, subject_player=kw.get("subject_player"),
    )


def player_turn(turn: int, player: int, **overrides) -> PlayerTurn:
    base = dict(
        turn=turn, player=player, cities=1, towns=1, settlement_cap=4, settlements_over_cap=0,
        urban_pop=5, rural_pop=10, techs=8, land_units=5, naval_units=0, tiles_owned=40,
        tiles_improved=10, gold_balance=100.0, science=20.0, culture=20.0, gold=20.0,
        production=20.0, food=20.0, happiness=10.0, diplomacy=5.0,
    )
    base.update(overrides)
    return PlayerTurn(**base)


def game_state(
    turn: int = 10,
    rivals: dict[int, str] | None = None,
    human_stats: dict | None = None,
    rival_stats: dict[int, dict] | None = None,
    history_turns: int = 1,
) -> GameState:
    """A game whose complete turn is `turn` (latest is turn + 1).

    Every rival and the human get identical default stats (see player_turn) unless
    overridden. `history_turns` copies of those stats are written for the turns
    ending at `turn`, so GameState.series() has data.
    """
    rivals = {1: "Rival One"} if rivals is None else rivals
    state = GameState(latest_turn=turn + 1, complete_through_turn=turn)
    state.players[0] = Player(0, "You", PlayerKind.HUMAN, True, turn + 1)
    for pid, name in rivals.items():
        state.players[pid] = Player(pid, name, PlayerKind.RIVAL, True, turn)
    for t in range(turn - history_turns + 1, turn + 1):
        state.turns[t] = {0: player_turn(t, 0, **(human_stats or {}))}
        for pid in rivals:
            state.turns[t][pid] = player_turn(t, pid, **((rival_stats or {}).get(pid, {})))
    return state


def scored_war(turn: int, actor: int, target: int | None = 0, score: float = 202.0) -> DiplomacyRow:
    return DiplomacyRow(turn, actor, "DECLARE_WAR", target, IntentKind.SCORED, score)


def executed_war(turn: int, actor: int, target: int | None = 0) -> DiplomacyRow:
    return DiplomacyRow(turn, actor, "DECLARE_WAR", target, IntentKind.EXECUTED, None)


def kill(turn: int, victim: int, killer: int, unit: str = "Warrior", x: int = 10, y: int = 10) -> HistorianRow:
    return HistorianRow("UNIT_KILLED", "AGE_ANTIQUITY", turn, x, y, victim, killer, unit, None)


def city_target(
    turn: int, player: int, owner: int = 0, x: int = 10, y: int = 10,
    target_type: str = "TARGET_ENEMY_CITY",
) -> TargetRow:
    return TargetRow(turn, player, target_type, owner, 1, x, y)


def strategy(player: int, path: str, weight: int, status: str = "Following", since: int = 1) -> StrategyStatus:
    return StrategyStatus(player, path, status, weight, since)
```

`tests/test_checklist.py`:
```python
from dataclasses import FrozenInstanceError

import pytest

from civ7_advisor.advisors.base import Provenance, Severity
from civ7_advisor.advisors.checklist import rank
from tests.factories import insight


def test_rank_orders_by_severity_then_turn_then_advisor_then_id():
    items = [
        insight("economy.a", "economy", Severity.WARN, turn=10),
        insight("threat.b", "threat", Severity.WARN, turn=10),
        insight("victory.c", "victory", Severity.CRITICAL, turn=9),
        insight("threat.a", "threat", Severity.WARN, turn=10),
        insight("threat.z", "threat", Severity.INFO, turn=10),
        insight("threat.old", "threat", Severity.WARN, turn=9),
    ]
    assert [i.id for i in rank(items)] == [
        "victory.c", "threat.a", "threat.b", "economy.a", "threat.old", "threat.z",
    ]


def test_rank_dedupes_by_id_keeping_the_more_severe():
    items = [insight("threat.x", severity=Severity.INFO), insight("threat.x", severity=Severity.WARN)]
    ranked = rank(items)
    assert len(ranked) == 1 and ranked[0].severity is Severity.WARN


def test_severity_is_ordered_and_insight_is_frozen():
    assert Severity.INFO < Severity.ADVISE < Severity.WARN < Severity.CRITICAL
    i = insight("a", provenance=Provenance.ORACLE)
    assert i.provenance is Provenance.ORACLE
    with pytest.raises(FrozenInstanceError):
        i.title = "x"  # type: ignore[misc]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_checklist.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'civ7_advisor.advisors'`.

- [ ] **Step 3: Write the implementation**

`civ7_advisor/advisors/__init__.py` (placeholder; replaced in Task 11):
```python
"""Advisors turn a GameState into Insights. Each module exposes advise(state)."""
```

`civ7_advisor/advisors/base.py`:
```python
"""Shared vocabulary for advisors."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, IntEnum


class Provenance(Enum):
    FAIR = "fair"      # derivable from what the player can see in-game
    ORACLE = "oracle"  # uses AI-internal data the game hides


class Severity(IntEnum):
    INFO = 0
    ADVISE = 1
    WARN = 2
    CRITICAL = 3


@dataclass(frozen=True)
class Insight:
    id: str             # stable key, e.g. "threat.war_intent.1"
    advisor: str        # "threat" | "victory" | "economy"
    severity: Severity
    provenance: Provenance
    title: str
    recommendation: str
    why: str            # the evidence, in plain language, with the numbers
    turn: int           # complete_through_turn it was computed on
    subject_player: int | None = None
```

`civ7_advisor/advisors/checklist.py`:
```python
"""Merge advisor output into one ranked, de-duplicated to-do list."""
from __future__ import annotations

from .base import Insight

ADVISOR_ORDER = {"threat": 0, "victory": 1, "economy": 2}


def rank(insights: list[Insight]) -> list[Insight]:
    """Most severe first, then most recent, then threat > victory > economy, then id.
    Duplicate ids keep the first (i.e. most severe) occurrence."""
    ordered = sorted(
        insights,
        key=lambda i: (-int(i.severity), -i.turn, ADVISOR_ORDER.get(i.advisor, 99), i.id),
    )
    seen: set[str] = set()
    out: list[Insight] = []
    for insight in ordered:
        if insight.id in seen:
            continue
        seen.add(insight.id)
        out.append(insight)
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_checklist.py -q`
Expected: `3 passed`.

- [ ] **Step 5: Commit**

```bash
git add civ7_advisor/advisors tests/factories.py tests/test_checklist.py
git commit -m "Add Insight vocabulary, checklist ranking and test factories"
```

---

### Task 8: Threat advisor

**Files:**
- Create: `civ7_advisor/advisors/threat.py`
- Test: `tests/test_threat.py`

**Interfaces:**
- Consumes: `GameState`, `IntentKind` from `state.models`; `Insight, Severity, Provenance` from `.base`.
- Produces: constants `WAR_INTENT_WARN=100.0, WAR_INTENT_WATCH=50.0, RECENT_TURNS=10, MILITARY_RATIO_ADVISE=1.5, ARMY_GROWTH_TURNS=10, ARMY_GROWTH_DELTA=3`; `RivalThreat` dataclass with fields `player, name, land_units, human_land_units, military_ratio, war_score, war_score_since, at_war_since, kills, losses, latest_fight: tuple[int,int,int] | None, target_turn, city_tiles_targeted, units_targeted, target_box: tuple[int,int,int,int] | None`; `summarize(state) -> list[RivalThreat]`; `advise(state) -> list[Insight]` emitting ids `threat.at_war.{r}`, `threat.war_intent.{r}`, `threat.active_front.{r}`, `threat.targeting.{r}`, `threat.military_gap.{r}`, `threat.army_growth.{r}`.

- [ ] **Step 1: Write the failing tests**

`tests/test_threat.py`:
```python
from dataclasses import replace

import pytest

from civ7_advisor.advisors import threat
from civ7_advisor.advisors.base import Provenance, Severity
from tests.factories import city_target, executed_war, game_state, kill, scored_war


def ids(insights):
    return {i.id: i for i in insights}


def test_executed_war_is_critical_oracle_and_suppresses_intent():
    s = game_state(turn=20)
    s.intents = [scored_war(20, 1, score=204.0), executed_war(18, 1)]
    got = ids(threat.advise(s))
    assert got["threat.at_war.1"].severity is Severity.CRITICAL
    assert got["threat.at_war.1"].provenance is Provenance.ORACLE
    assert "turn 18" in got["threat.at_war.1"].why
    assert "threat.war_intent.1" not in got


def test_executed_war_outside_window_is_ignored():
    s = game_state(turn=40)
    s.intents = [executed_war(30, 1)]  # RECENT_TURNS = 10 -> window is 31..40
    assert "threat.at_war.1" not in ids(threat.advise(s))


def test_executed_war_with_unknown_target_is_not_attributed():
    s = game_state(turn=20)
    s.intents = [executed_war(20, 1, target=None)]
    assert "threat.at_war.1" not in ids(threat.advise(s))


@pytest.mark.parametrize(
    "score,expected",
    [(49.0, None), (50.0, Severity.INFO), (99.9, Severity.INFO), (100.0, Severity.WARN), (202.0, Severity.WARN)],
)
def test_war_intent_thresholds(score, expected):
    s = game_state(turn=20)
    s.intents = [scored_war(20, 1, score=score)]
    got = ids(threat.advise(s))
    if expected is None:
        assert "threat.war_intent.1" not in got
    else:
        assert got["threat.war_intent.1"].severity is expected
        assert got["threat.war_intent.1"].provenance is Provenance.ORACLE


def test_war_intent_reports_start_of_current_run():
    s = game_state(turn=20)
    s.intents = [
        scored_war(15, 1, score=25.0), scored_war(16, 1, score=150.0),
        scored_war(17, 1, score=160.0), scored_war(20, 1, score=202.0),
    ]
    why = ids(threat.advise(s))["threat.war_intent.1"].why
    assert "since turn 16" in why and "held for 5 turns" in why


def test_stale_war_score_is_dropped():
    s = game_state(turn=20)
    s.intents = [scored_war(17, 1, score=202.0)]  # last logged 3 turns ago
    assert "threat.war_intent.1" not in ids(threat.advise(s))


def test_war_intent_against_someone_else_is_ignored():
    s = game_state(turn=20, rivals={1: "A", 2: "B"})
    s.intents = [scored_war(20, 1, target=2, score=202.0)]
    assert not any(i.id.startswith("threat.war") for i in threat.advise(s))


def test_active_front_counts_kills_and_losses_fairly():
    s = game_state(turn=20)
    s.events = [
        kill(15, victim=1, killer=0),
        kill(18, victim=0, killer=1),
        kill(20, victim=0, killer=1, unit="Slinger", x=7, y=9),
        kill(5, victim=0, killer=1),  # outside the window
    ]
    i = ids(threat.advise(s))["threat.active_front.1"]
    assert i.severity is Severity.WARN and i.provenance is Provenance.FAIR
    assert "3 unit kills" in i.why and "you lost 2" in i.why and "turn 20 at (7,9)" in i.why


def test_city_targeting_is_warn_and_units_only_is_advise():
    s = game_state(turn=20)
    s.targets = [
        city_target(20, 1, x=3, y=4),
        city_target(20, 1, x=5, y=6),
        city_target(20, 1, x=4, y=4, target_type="TARGET_HIGH_PRIORITY_UNIT"),
    ]
    i = ids(threat.advise(s))["threat.targeting.1"]
    assert i.severity is Severity.WARN and i.provenance is Provenance.ORACLE
    assert "2 of your city tiles and 1 of your units" in i.why and "x 3-5, y 4-6" in i.why
    s.targets = [city_target(20, 1, target_type="TARGET_LOW_PRIORITY_UNIT")]
    assert ids(threat.advise(s))["threat.targeting.1"].severity is Severity.ADVISE


def test_targeting_uses_previous_turn_when_ai_lags_but_not_older():
    s = game_state(turn=20)
    s.targets = [city_target(19, 1)]
    assert "On turn 19" in ids(threat.advise(s))["threat.targeting.1"].why
    s.targets = [city_target(17, 1)]
    assert "threat.targeting.1" not in ids(threat.advise(s))


@pytest.mark.parametrize("rival_units,expected", [(7, False), (8, True), (12, True)])  # human has 5
def test_military_gap_threshold(rival_units, expected):
    s = game_state(turn=20, rival_stats={1: {"land_units": rival_units}})
    assert ("threat.military_gap.1" in ids(threat.advise(s))) is expected


def test_army_growth_compares_deltas():
    s = game_state(turn=20, history_turns=10)
    s.turns[20][1] = replace(s.turns[20][1], land_units=8)  # rival 5 -> 8, human 5 -> 5
    i = ids(threat.advise(s))["threat.army_growth.1"]
    assert i.severity is Severity.INFO and i.provenance is Provenance.FAIR
    assert "from 5 to 8" in i.why
    s.turns[20][1] = replace(s.turns[20][1], land_units=7)  # +2 is below ARMY_GROWTH_DELTA
    assert "threat.army_growth.1" not in ids(threat.advise(s))


def test_no_human_row_means_no_threats():
    s = game_state(turn=20)
    del s.turns[20][0]
    assert threat.advise(s) == [] and threat.summarize(s) == []


def test_fixture_threats_at_turn_81(fixture_state):
    got = ids(threat.advise(fixture_state))
    assert got["threat.at_war.4"].severity is Severity.CRITICAL and "turn 80" in got["threat.at_war.4"].why
    front = got["threat.active_front.4"]
    assert front.provenance is Provenance.FAIR
    assert "6 unit kills" in front.why and "you lost 3" in front.why and "turn 81 at (62,32)" in front.why
    intent = got["threat.war_intent.1"]
    assert intent.severity is Severity.WARN and "since turn 72" in intent.why and "held for 10 turns" in intent.why
    assert "19 of your city tiles" in got["threat.targeting.4"].why
    assert "9 of your city tiles" in got["threat.targeting.1"].why
    assert got["threat.military_gap.1"].why.endswith("has 11 land units to your 5.")
    assert not any(i.subject_player == 7 and i.id.startswith("threat.war") for i in got.values())
    assert not any(i.subject_player == 3 for i in got.values())  # Napoleon is dead


def test_fixture_summary_numbers(fixture_state):
    by_player = {r.player: r for r in threat.summarize(fixture_state)}
    assert set(by_player) == {1, 2, 4, 5, 6, 7}
    assert by_player[4].at_war_since == 80 and by_player[4].kills == 6 and by_player[4].losses == 3
    assert by_player[4].latest_fight == (81, 62, 32)
    assert by_player[4].city_tiles_targeted == 19 and by_player[4].units_targeted == 5
    assert by_player[1].war_score == 202.0 and by_player[1].war_score_since == 72
    assert by_player[1].at_war_since is None and by_player[1].military_ratio == pytest.approx(2.2)
    assert by_player[7].war_score is None and by_player[7].kills == 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_threat.py -q`
Expected: FAIL with `ImportError: cannot import name 'threat'`.

- [ ] **Step 3: Write the implementation**

`civ7_advisor/advisors/threat.py`:
```python
"""Who is coming for you, and how much time you have."""
from __future__ import annotations

from dataclasses import dataclass

from civ7_advisor.state.models import GameState, IntentKind, Player

from .base import Insight, Provenance, Severity

WAR_INTENT_WARN = 100.0      # AI DECLARE_WAR score at/above which we warn; committed AIs sit near 200
WAR_INTENT_WATCH = 50.0      # at/above this (but below WARN) we mention it as INFO
RECENT_TURNS = 10            # window in which executed actions and kills count as "recent"
MILITARY_RATIO_ADVISE = 1.5  # rival land units / human land units at/above which we advise
ARMY_GROWTH_TURNS = 10       # window over which army growth is compared
ARMY_GROWTH_DELTA = 3        # rival must have gained this many more land units than the human

KILL_EVENTS = ("UNIT_KILLED", "SHIP_SUNK")
CITY_TARGET = "TARGET_ENEMY_CITY"
UNIT_TARGET_SUFFIX = "_PRIORITY_UNIT"


@dataclass(frozen=True)
class RivalThreat:
    player: int
    name: str
    land_units: int
    human_land_units: int
    military_ratio: float
    war_score: float | None        # latest SCORED DECLARE_WAR against the human, if logged this/last turn
    war_score_since: int | None    # first turn of the current unbroken run at/above WAR_INTENT_WATCH
    at_war_since: int | None       # most recent EXECUTED DECLARE_WAR on the human within RECENT_TURNS
    kills: int                     # kills between the two within RECENT_TURNS
    losses: int                    # ... of which were the human's units
    latest_fight: tuple[int, int, int] | None  # (turn, x, y)
    target_turn: int | None        # turn the targeting rows below come from
    city_tiles_targeted: int
    units_targeted: int
    target_box: tuple[int, int, int, int] | None  # (min_x, max_x, min_y, max_y)


def summarize(state: GameState) -> list[RivalThreat]:
    human_turn = state.at(state.HUMAN)
    if human_turn is None:
        return []
    return [_summarize_rival(state, rival, human_turn.land_units) for rival in state.rivals()]


def _summarize_rival(state: GameState, rival: Player, human_land: int) -> RivalThreat:
    t = state.complete_through_turn
    window = range(t - RECENT_TURNS + 1, t + 1)
    rt = state.at(rival.id, t)
    land = rt.land_units if rt else 0

    war_rows = [
        i for i in state.intents
        if i.action == "DECLARE_WAR" and i.actor == rival.id and i.target == state.HUMAN
    ]
    executed = [i for i in war_rows if i.kind is IntentKind.EXECUTED and i.turn in window]
    at_war_since = max((i.turn for i in executed), default=None)

    scored = sorted((i for i in war_rows if i.kind is IntentKind.SCORED and i.turn <= t), key=lambda i: i.turn)
    war_score = war_since = None
    if scored and scored[-1].turn >= t - 1:  # the AI logs lag the human by up to one turn
        war_score = scored[-1].score
        if war_score is not None and war_score >= WAR_INTENT_WATCH:
            for i in reversed(scored):
                if i.score is None or i.score < WAR_INTENT_WATCH:
                    break
                war_since = i.turn

    fights = [
        e for e in state.events
        if e.type in KILL_EVENTS and e.turn in window and {e.player, e.opponent} == {state.HUMAN, rival.id}
    ]
    latest = max(fights, key=lambda e: e.turn, default=None)

    rows = [g for g in state.targets if g.player == rival.id and g.owner == state.HUMAN and g.turn <= t]
    target_turn = max((g.turn for g in rows), default=None)
    if target_turn is not None and target_turn < t - 1:
        target_turn = None
    rows = [g for g in rows if g.turn == target_turn]
    cities = [g for g in rows if g.target_type == CITY_TARGET]
    units = [g for g in rows if g.target_type.endswith(UNIT_TARGET_SUFFIX)]
    box = None
    if cities or units:
        xs = [g.x for g in cities + units]
        ys = [g.y for g in cities + units]
        box = (min(xs), max(xs), min(ys), max(ys))

    return RivalThreat(
        player=rival.id, name=rival.name, land_units=land, human_land_units=human_land,
        military_ratio=land / max(human_land, 1), war_score=war_score, war_score_since=war_since,
        at_war_since=at_war_since, kills=len(fights),
        losses=sum(e.player == state.HUMAN for e in fights),
        latest_fight=(latest.turn, latest.x, latest.y) if latest else None,
        target_turn=target_turn if (cities or units) else None,
        city_tiles_targeted=len(cities), units_targeted=len(units), target_box=box,
    )


def _army_growth(state: GameState, rival_id: int) -> tuple[list[float], list[float]] | None:
    rs = state.series(rival_id, "land_units", ARMY_GROWTH_TURNS)
    hs = state.series(state.HUMAN, "land_units", ARMY_GROWTH_TURNS)
    if len(rs) < 2 or len(hs) < 2:
        return None
    return rs, hs


def advise(state: GameState) -> list[Insight]:
    t = state.complete_through_turn
    out: list[Insight] = []
    for r in summarize(state):
        common = dict(advisor="threat", turn=t, subject_player=r.player)

        if r.at_war_since is not None:
            out.append(Insight(
                id=f"threat.at_war.{r.player}", severity=Severity.CRITICAL, provenance=Provenance.ORACLE,
                title=f"{r.name} has declared war on you",
                recommendation="Garrison border settlements, pull exposed units back to defensible "
                               "terrain, and switch production to military until the front stabilises.",
                why=f"{r.name}'s AI executed DECLARE_WAR against you on turn {r.at_war_since}.",
                **common,
            ))
        elif r.war_score is not None and r.war_score >= WAR_INTENT_WATCH:
            held = t - (r.war_score_since or t) + 1
            out.append(Insight(
                id=f"threat.war_intent.{r.player}",
                severity=Severity.WARN if r.war_score >= WAR_INTENT_WARN else Severity.INFO,
                provenance=Provenance.ORACLE,
                title=f"{r.name} is weighing war against you",
                recommendation="Build units now, not when the declaration comes: walls in the border "
                               "settlement, a commander, and enough melee to hold. A delegation or "
                               "improved relations can buy turns.",
                why=f"{r.name}'s AI scores declaring war on you at {r.war_score:.0f} "
                    f"(warn threshold {WAR_INTENT_WARN:.0f}), held for {held} "
                    f"turn{'s' if held != 1 else ''} since turn {r.war_score_since}.",
                **common,
            ))

        if r.kills:
            turn, x, y = r.latest_fight
            out.append(Insight(
                id=f"threat.active_front.{r.player}", severity=Severity.WARN, provenance=Provenance.FAIR,
                title=f"Active fighting with {r.name}",
                recommendation="Concentrate force at the front, heal inside friendly territory, and "
                               "stop feeding units in one at a time.",
                why=f"{r.kills} unit kills between you and {r.name} in the last {RECENT_TURNS} turns; "
                    f"you lost {r.losses}. Latest fight: turn {turn} at ({x},{y}).",
                **common,
            ))

        if r.city_tiles_targeted or r.units_targeted:
            parts = []
            if r.city_tiles_targeted:
                parts.append(f"{r.city_tiles_targeted} of your city tiles")
            if r.units_targeted:
                parts.append(f"{r.units_targeted} of your units")
            x0, x1, y0, y1 = r.target_box
            out.append(Insight(
                id=f"threat.targeting.{r.player}",
                severity=Severity.WARN if r.city_tiles_targeted else Severity.ADVISE,
                provenance=Provenance.ORACLE,
                title=f"{r.name}'s AI is targeting your {'cities' if r.city_tiles_targeted else 'units'}",
                recommendation=f"Fortify and garrison around x {x0}-{x1}, y {y0}-{y1}; keep ranged "
                               "units inside the settlement and a melee unit on the approach.",
                why=f"On turn {r.target_turn} {r.name}'s AI listed {' and '.join(parts)} as targets, "
                    f"spanning x {x0}-{x1}, y {y0}-{y1}.",
                **common,
            ))

        if r.military_ratio >= MILITARY_RATIO_ADVISE:
            out.append(Insight(
                id=f"threat.military_gap.{r.player}", severity=Severity.ADVISE, provenance=Provenance.FAIR,
                title=f"{r.name} out-muscles you {r.military_ratio:.1f}x",
                recommendation="Close the gap before it is tested: queue military units in your "
                               "highest-production settlement and keep a commander near the shared border.",
                why=f"Turn {t}: {r.name} has {r.land_units} land units to your {r.human_land_units}.",
                **common,
            ))

        growth = _army_growth(state, r.player)
        if growth is not None:
            rs, hs = growth
            if (rs[-1] - rs[0]) - (hs[-1] - hs[0]) >= ARMY_GROWTH_DELTA:
                out.append(Insight(
                    id=f"threat.army_growth.{r.player}", severity=Severity.INFO, provenance=Provenance.FAIR,
                    title=f"{r.name} is arming faster than you",
                    recommendation="Match the build-up or make sure your defences don't depend on parity.",
                    why=f"Over the last {len(rs)} turns {r.name} went from {rs[0]:.0f} to {rs[-1]:.0f} "
                        f"land units while you went from {hs[0]:.0f} to {hs[-1]:.0f}.",
                    **common,
                ))
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_threat.py -q`
Expected: `19 passed`.

- [ ] **Step 5: Commit**

```bash
git add civ7_advisor/advisors/threat.py tests/test_threat.py
git commit -m "Add threat advisor: war intent, executed war, fronts, targeting, military gap"
```

---

### Task 9: Victory advisor

**Files:**
- Create: `civ7_advisor/advisors/victory.py`
- Test: `tests/test_victory.py`

**Interfaces:**
- Produces: constants `STRATEGY_COMMITTED = 75`, `LEAD_MARGIN = 1.25`, `PATH_STATS: dict[str, tuple[str, str]]` (SCIENCE→science, CULTURAL→culture, ECONOMIC→gold, MILITARY→military_units); `leaderboards(state) -> dict[str, list[tuple[Player, float]]]`; `committed_paths(state) -> dict[tuple[int, str], StrategyStatus]`; `advise(state)` emitting `victory.pursuing.{r}.{path}`, `victory.leader.{path}`, `victory.you_lead.{path}`.

- [ ] **Step 1: Write the failing tests**

`tests/test_victory.py`:
```python
import pytest

from civ7_advisor.advisors import victory
from civ7_advisor.advisors.base import Provenance, Severity
from tests.factories import game_state, strategy


def ids(insights):
    return {i.id: i for i in insights}


def test_committed_strategy_is_info_oracle():
    s = game_state(turn=20)
    s.strategies = {1: {"SCIENCE": strategy(1, "SCIENCE", 77, since=12)}}
    i = ids(victory.advise(s))["victory.pursuing.1.SCIENCE"]
    assert i.severity is Severity.INFO and i.provenance is Provenance.ORACLE
    assert "weight 77 since turn 12" in i.why and i.subject_player == 1


@pytest.mark.parametrize(
    "weight,status,expected",
    [(74, "Following", False), (75, "Following", True), (100, "Stopped", False), (100, "Forbidden", False)],
)
def test_commitment_threshold_and_status(weight, status, expected):
    s = game_state(turn=20)
    s.strategies = {1: {"CULTURAL": strategy(1, "CULTURAL", weight, status=status)}}
    assert ("victory.pursuing.1.CULTURAL" in ids(victory.advise(s))) is expected


def test_espionage_is_not_a_legacy_path():
    s = game_state(turn=20)
    s.strategies = {1: {"ESPIONAGE": strategy(1, "ESPIONAGE", 100)}}
    assert not any(i.id.startswith("victory.pursuing") for i in victory.advise(s))


def test_leader_pulling_away_is_advise_fair_by_default():
    s = game_state(turn=20, rivals={1: "A", 2: "B"}, rival_stats={1: {"science": 50.0}, 2: {"science": 39.0}})
    i = ids(victory.advise(s))["victory.leader.SCIENCE"]
    assert i.severity is Severity.ADVISE and i.provenance is Provenance.FAIR and i.subject_player == 1
    assert "A 50.0 vs runner-up B 39.0 (1.28x)" in i.why


def test_leader_below_margin_is_silent():
    s = game_state(turn=20, rivals={1: "A", 2: "B"}, rival_stats={1: {"science": 48.0}, 2: {"science": 39.0}})
    assert "victory.leader.SCIENCE" not in ids(victory.advise(s))


def test_committed_leader_escalates_to_warn_oracle():
    s = game_state(turn=20, rivals={1: "A", 2: "B"}, rival_stats={1: {"culture": 60.0}})
    s.strategies = {1: {"CULTURAL": strategy(1, "CULTURAL", 100)}}
    i = ids(victory.advise(s))["victory.leader.CULTURAL"]
    assert i.severity is Severity.WARN and i.provenance is Provenance.ORACLE and "committed" in i.why


def test_human_strict_lead_is_info_fair_and_ties_are_silent():
    s = game_state(turn=20, human_stats={"gold": 90.0})
    got = ids(victory.advise(s))
    i = got["victory.you_lead.ECONOMIC"]
    assert i.provenance is Provenance.FAIR and "you 90.0" in i.why
    assert "victory.you_lead.MILITARY" not in got  # 5 vs 5 is a tie, not a lead


def test_fixture_victory_at_turn_81(fixture_state):
    got = ids(victory.advise(fixture_state))
    pursuing = sorted(k for k in got if k.startswith("victory.pursuing"))
    assert pursuing == [
        "victory.pursuing.1.SCIENCE", "victory.pursuing.2.MILITARY", "victory.pursuing.4.CULTURAL",
        "victory.pursuing.4.SCIENCE", "victory.pursuing.5.MILITARY", "victory.pursuing.7.SCIENCE",
    ]
    assert "weight 100 since turn 74" in got["victory.pursuing.4.CULTURAL"].why
    econ = got["victory.leader.ECONOMIC"]
    assert econ.subject_player == 2 and econ.severity is Severity.ADVISE and econ.provenance is Provenance.FAIR
    assert "Harriet Tubman 72.5 vs runner-up Ibn Battuta 30.0" in econ.why
    assert not any(k in got for k in ("victory.leader.SCIENCE", "victory.leader.CULTURAL", "victory.leader.MILITARY"))
    assert not any(k.startswith("victory.you_lead") for k in got)


def test_fixture_leaderboards(fixture_state):
    boards = victory.leaderboards(fixture_state)
    assert set(boards) == {"SCIENCE", "CULTURAL", "ECONOMIC", "MILITARY"}
    assert [p.id for p, _ in boards["SCIENCE"]] == [4, 7, 5, 1, 6, 2, 0]
    assert boards["ECONOMIC"][0][1] == 72.5
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_victory.py -q`
Expected: FAIL with `ImportError: cannot import name 'victory'`.

- [ ] **Step 3: Write the implementation**

`civ7_advisor/advisors/victory.py`:
```python
"""Who is pursuing which legacy path, and who is actually ahead on it."""
from __future__ import annotations

from civ7_advisor.state.models import GameState, Player, StrategyStatus

from .base import Insight, Provenance, Severity

STRATEGY_COMMITTED = 75  # AI strategy weight at/above which we call the AI "committed"
LEAD_MARGIN = 1.25       # leader must beat the runner-up by this factor to be "pulling away"

# legacy path -> (PlayerTurn attribute that proxies progress, human-readable label)
PATH_STATS: dict[str, tuple[str, str]] = {
    "SCIENCE": ("science", "science yield"),
    "CULTURAL": ("culture", "culture yield"),
    "ECONOMIC": ("gold", "gold yield"),
    "MILITARY": ("military_units", "military units"),
}


def leaderboards(state: GameState) -> dict[str, list[tuple[Player, float]]]:
    """Per path, alive majors (human included) ordered best-first by the proxy stat."""
    t = state.complete_through_turn
    boards: dict[str, list[tuple[Player, float]]] = {}
    for path, (attr, _) in PATH_STATS.items():
        rows = [
            (p, float(getattr(state.at(p.id, t), attr)))
            for p in state.majors() if state.at(p.id, t) is not None
        ]
        boards[path] = sorted(rows, key=lambda pv: pv[1], reverse=True)
    return boards


def committed_paths(state: GameState) -> dict[tuple[int, str], StrategyStatus]:
    """(rival id, path) -> status for every legacy path a rival's AI is committed to."""
    out: dict[tuple[int, str], StrategyStatus] = {}
    for rival in state.rivals():
        for path, st in state.strategies.get(rival.id, {}).items():
            if path in PATH_STATS and st.following and st.weight >= STRATEGY_COMMITTED:
                out[(rival.id, path)] = st
    return out


def advise(state: GameState) -> list[Insight]:
    t = state.complete_through_turn
    out: list[Insight] = []
    committed = committed_paths(state)

    for (pid, path), st in sorted(committed.items()):
        rival = state.players[pid]
        label = PATH_STATS[path][1]
        out.append(Insight(
            id=f"victory.pursuing.{pid}.{path}", advisor="victory",
            severity=Severity.INFO, provenance=Provenance.ORACLE,
            title=f"{rival.name} is committed to the {path.title()} legacy path",
            recommendation=f"Expect {rival.name} to pour effort into {label}. Decide now whether you "
                           f"race them on it or deny them (trade, war, or out-building them).",
            why=f"{rival.name}'s AI has followed its {path} strategy at weight {st.weight} since "
                f"turn {st.since_turn} (committed threshold {STRATEGY_COMMITTED}).",
            turn=t, subject_player=pid,
        ))

    for path, board in leaderboards(state).items():
        if len(board) < 2:
            continue
        (leader, lv), (second, sv) = board[0], board[1]
        _, label = PATH_STATS[path]
        if leader.id == state.HUMAN:
            if lv > sv:
                out.append(Insight(
                    id=f"victory.you_lead.{path}", advisor="victory",
                    severity=Severity.INFO, provenance=Provenance.FAIR,
                    title=f"You lead the field in {label}",
                    recommendation=f"Protect the lead: keep {label} growing and watch {second.name}, who is second.",
                    why=f"Turn {t}: you {lv:.1f} vs {second.name} {sv:.1f}.",
                    turn=t, subject_player=state.HUMAN,
                ))
            continue
        if lv > 0 and lv >= LEAD_MARGIN * sv:
            st = committed.get((leader.id, path))
            ratio = f" ({lv / sv:.2f}x)" if sv else ""
            why = f"Turn {t}: {leader.name} {lv:.1f} vs runner-up {second.name} {sv:.1f}{ratio}."
            if st:
                why += f" Their AI is also committed to the {path} path (weight {st.weight})."
            out.append(Insight(
                id=f"victory.leader.{path}", advisor="victory",
                severity=Severity.WARN if st else Severity.ADVISE,
                provenance=Provenance.ORACLE if st else Provenance.FAIR,
                title=f"{leader.name} is pulling away in {label}",
                recommendation=f"Either contest {label} directly or make sure your own path finishes first; "
                               f"consider slowing {leader.name} with diplomacy or denial.",
                why=why, turn=t, subject_player=leader.id,
            ))
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_victory.py -q`
Expected: `12 passed`.

- [ ] **Step 5: Commit**

```bash
git add civ7_advisor/advisors/victory.py tests/test_victory.py
git commit -m "Add victory advisor: committed strategies and path leaderboards"
```

---

### Task 10: Economy advisor

**Files:**
- Create: `civ7_advisor/advisors/economy.py`
- Test: `tests/test_economy.py`

**Interfaces:**
- Produces: constants `BEHIND_RATIO = 0.75`, `FAR_BEHIND_RATIO = 0.5`, `CELEBRATION_NEAR = 0.9`, `YIELDS: dict[str, tuple[str, str]]`; `YieldComparison(stat, label, human, rival_median, leader_name, leader_value, ratio)`; `comparison(state) -> list[YieldComparison]`; `advise(state)` emitting `economy.behind.{stat}`, `economy.settlement_slack`, `economy.over_cap`, `economy.negative_gold`, `economy.celebration`, `economy.rival_celebration.{r}`.

- [ ] **Step 1: Write the failing tests**

`tests/test_economy.py`:
```python
import pytest

from civ7_advisor.advisors import economy
from civ7_advisor.advisors.base import Provenance, Severity
from tests.factories import game_state


def ids(insights):
    return {i.id: i for i in insights}


def test_worst_stat_is_warn_when_far_behind_and_others_are_info():
    s = game_state(
        turn=20, rivals={1: "A", 2: "B", 3: "C"},
        human_stats={"food": 8.0, "science": 14.0, "culture": 30.0},
        rival_stats={1: {"food": 20.0, "science": 20.0}, 2: {"food": 24.0}, 3: {"food": 40.0}},
    )
    got = ids(economy.advise(s))
    food = got["economy.behind.food"]  # 8 / median 24 = 0.33
    assert food.severity is Severity.WARN and food.provenance is Provenance.FAIR
    assert "8.0 vs rival median 24.0 (33%)" in food.why and "leader C at 40.0" in food.why
    assert got["economy.behind.science"].severity is Severity.INFO  # 14 / 20 = 0.70
    assert "economy.behind.culture" not in got  # 30 / 20 is ahead


def test_worst_stat_is_advise_when_moderately_behind():
    s = game_state(turn=20, human_stats={"gold": 14.0})  # 14 / 20 = 0.70
    assert ids(economy.advise(s))["economy.behind.gold"].severity is Severity.ADVISE


@pytest.mark.parametrize("value,flagged", [(14.9, True), (15.0, False)])  # threshold is 0.75 * 20
def test_behind_threshold(value, flagged):
    s = game_state(turn=20, human_stats={"production": value})
    assert ("economy.behind.production" in ids(economy.advise(s))) is flagged


def test_settlement_slack_and_over_cap():
    s = game_state(turn=20, human_stats={"cities": 1, "towns": 1, "settlement_cap": 4})
    assert "2 of 4 settlement slots unused" in ids(economy.advise(s))["economy.settlement_slack"].why
    s = game_state(turn=20, human_stats={"cities": 2, "towns": 3, "settlement_cap": 4, "settlements_over_cap": 1})
    got = ids(economy.advise(s))
    assert "economy.settlement_slack" not in got and got["economy.over_cap"].severity is Severity.WARN


def test_negative_gold_needs_treasury_data():
    s = game_state(turn=20, human_stats={"gold": 10.0, "total_maintenance": 14})
    assert "= -4.0 per turn" in ids(economy.advise(s))["economy.negative_gold"].why
    s = game_state(turn=20, human_stats={"gold": 10.0})  # no maintenance row -> unknown, stay silent
    assert "economy.negative_gold" not in ids(economy.advise(s))


def test_celebration_thresholds_and_provenance():
    s = game_state(
        turn=20, human_stats={"happiness_total": 900, "happiness_threshold": 1000},
        rival_stats={1: {"happiness_total": 899, "happiness_threshold": 1000}},
    )
    got = ids(economy.advise(s))
    assert got["economy.celebration"].provenance is Provenance.FAIR
    assert "economy.rival_celebration.1" not in got
    s = game_state(turn=20, rival_stats={1: {"happiness_total": 950, "happiness_threshold": 1000}})
    assert ids(economy.advise(s))["economy.rival_celebration.1"].provenance is Provenance.ORACLE


def test_no_rivals_means_no_comparison_but_own_checks_still_run():
    s = game_state(turn=20, rivals={}, human_stats={"settlement_cap": 5})
    got = ids(economy.advise(s))
    assert not any(k.startswith("economy.behind") for k in got) and "economy.settlement_slack" in got
    assert economy.comparison(s) == []


def test_fixture_economy_at_turn_81(fixture_state):
    got = ids(economy.advise(fixture_state))
    food = got["economy.behind.food"]
    assert food.severity is Severity.WARN and "24.0 vs rival median 59.0 (41%)" in food.why
    assert got["economy.behind.culture"].severity is Severity.INFO
    assert got["economy.behind.science"].severity is Severity.INFO
    assert "economy.behind.gold" not in got and "economy.behind.production" not in got
    assert "2 of 4 settlement slots unused" in got["economy.settlement_slack"].why
    assert "economy.negative_gold" not in got  # 23.0 - 4 = +19
    assert "economy.celebration" not in got    # 1038 / 1532 = 68%
    catherine = got["economy.rival_celebration.7"]
    assert catherine.provenance is Provenance.ORACLE and "(93%)" in catherine.why
    assert [k for k in got if k.startswith("economy.rival_celebration")] == ["economy.rival_celebration.7"]


def test_fixture_comparison_table(fixture_state):
    by_stat = {c.stat: c for c in economy.comparison(fixture_state)}
    assert set(by_stat) == {"science", "culture", "gold", "production", "food"}
    assert by_stat["food"].rival_median == 59.0 and by_stat["food"].leader_name == "Ibn Battuta"
    assert by_stat["gold"].leader_name == "Harriet Tubman" and by_stat["gold"].leader_value == 72.5
    assert by_stat["science"].ratio == pytest.approx(15.0 / 31.8)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_economy.py -q`
Expected: FAIL with `ImportError: cannot import name 'economy'`.

- [ ] **Step 3: Write the implementation**

`civ7_advisor/advisors/economy.py`:
```python
"""How your economy compares to the field, and which lever to pull."""
from __future__ import annotations

import statistics
from dataclasses import dataclass

from civ7_advisor.state.models import GameState

from .base import Insight, Provenance, Severity

BEHIND_RATIO = 0.75     # human / rival median below this is flagged
FAR_BEHIND_RATIO = 0.5  # below this the worst stat is WARN instead of ADVISE
CELEBRATION_NEAR = 0.9  # happiness total / threshold at/above which a celebration is "imminent"

# PlayerTurn attribute -> (label, the Civ VII lever to pull)
YIELDS: dict[str, tuple[str, str]] = {
    "science": ("science", "Build science buildings (Library, then Academy) and work tiles with science "
                           "adjacency; a Research Collaboration with a friendly leader helps too."),
    "culture": ("culture", "Build culture buildings (Monument, Amphitheater), pick a wonder you can "
                           "finish, and use Cultural Exchange with a friendly leader."),
    "gold": ("gold", "Add trade routes to distant partners, build gold buildings (Market, then Bank), "
                     "and trim unit maintenance."),
    "production": ("production", "Work mines and quarries, build production buildings (Brickyard, "
                                 "Saw Pit), and specialise a town for production."),
    "food": ("food", "Grow towns on farmland and fishing tiles, use a Farming Town specialisation, "
                     "and build Granaries."),
}


@dataclass(frozen=True)
class YieldComparison:
    stat: str
    label: str
    human: float
    rival_median: float
    leader_name: str
    leader_value: float
    ratio: float  # human / rival median


def comparison(state: GameState) -> list[YieldComparison]:
    t = state.complete_through_turn
    human = state.at(state.HUMAN, t)
    rivals = [(r, state.at(r.id, t)) for r in state.rivals()]
    rivals = [(r, pt) for r, pt in rivals if pt is not None]
    if human is None or not rivals:
        return []
    out: list[YieldComparison] = []
    for attr, (label, _) in YIELDS.items():
        median = statistics.median(getattr(pt, attr) for _, pt in rivals)
        if median <= 0:
            continue
        leader, leader_value = max(((r, getattr(pt, attr)) for r, pt in rivals), key=lambda x: x[1])
        value = getattr(human, attr)
        out.append(YieldComparison(attr, label, value, median, leader.name, leader_value, value / median))
    return out


def advise(state: GameState) -> list[Insight]:
    t = state.complete_through_turn
    human = state.at(state.HUMAN, t)
    if human is None:
        return []
    out: list[Insight] = []
    common = dict(advisor="economy", turn=t)

    behind = sorted((c for c in comparison(state) if c.ratio < BEHIND_RATIO), key=lambda c: c.ratio)
    for index, c in enumerate(behind):
        if index == 0:
            severity = Severity.WARN if c.ratio < FAR_BEHIND_RATIO else Severity.ADVISE
        else:
            severity = Severity.INFO
        out.append(Insight(
            id=f"economy.behind.{c.stat}", severity=severity, provenance=Provenance.FAIR,
            title=f"Your {c.label} is {'far ' if c.ratio < FAR_BEHIND_RATIO else ''}behind the field",
            recommendation=YIELDS[c.stat][1],
            why=f"Turn {t}: your {c.label} {c.human:.1f} vs rival median {c.rival_median:.1f} "
                f"({c.ratio:.0%}); leader {c.leader_name} at {c.leader_value:.1f}.",
            subject_player=state.HUMAN, **common,
        ))

    slack = human.settlement_cap - human.settlements
    if slack >= 1:
        out.append(Insight(
            id="economy.settlement_slack", severity=Severity.ADVISE, provenance=Provenance.FAIR,
            title="You have room to expand",
            recommendation="Queue a Settler and found a town on food or resource tiles; every settlement "
                           "is more yields and more legacy progress.",
            why=f"Turn {t}: {slack} of {human.settlement_cap} settlement slots unused "
                f"({human.settlements} settlements).",
            subject_player=state.HUMAN, **common,
        ))
    if human.settlements_over_cap > 0:
        out.append(Insight(
            id="economy.over_cap", severity=Severity.WARN, provenance=Provenance.FAIR,
            title="You are over your settlement cap",
            recommendation="Raise the cap (civics, wonders, leader attributes) or stop settling; each "
                           "settlement over the cap costs happiness everywhere.",
            why=f"Turn {t}: {human.settlements_over_cap} settlement(s) over a cap of {human.settlement_cap}.",
            subject_player=state.HUMAN, **common,
        ))
    if human.net_gold is not None and human.net_gold < 0:
        out.append(Insight(
            id="economy.negative_gold", severity=Severity.WARN, provenance=Provenance.FAIR,
            title="You are losing gold every turn",
            recommendation="Disband idle units, delay buildings with maintenance, and add a trade route "
                           "or a gold building.",
            why=f"Turn {t}: gold yield {human.gold:.1f} minus maintenance {human.total_maintenance} "
                f"= {human.net_gold:+.1f} per turn (balance {human.gold_balance:.0f}).",
            subject_player=state.HUMAN, **common,
        ))

    progress = human.celebration_progress
    if progress is not None and progress >= CELEBRATION_NEAR:
        out.append(Insight(
            id="economy.celebration", severity=Severity.INFO, provenance=Provenance.FAIR,
            title="A celebration is imminent",
            recommendation="Line up what you want boosted (production, culture, gold) so the celebration "
                           "bonus lands on something that matters.",
            why=f"Turn {t}: happiness {human.happiness_total} of {human.happiness_threshold} ({progress:.0%}).",
            subject_player=state.HUMAN, **common,
        ))
    for rival in state.rivals():
        pt = state.at(rival.id, t)
        rp = pt.celebration_progress if pt else None
        if rp is not None and rp >= CELEBRATION_NEAR:
            out.append(Insight(
                id=f"economy.rival_celebration.{rival.id}", severity=Severity.INFO, provenance=Provenance.ORACLE,
                title=f"{rival.name} is about to celebrate",
                recommendation=f"Expect a temporary surge from {rival.name}; don't read their next few "
                               f"turns as their baseline.",
                why=f"Turn {t}: {rival.name}'s happiness {pt.happiness_total} of {pt.happiness_threshold} ({rp:.0%}).",
                subject_player=rival.id, **common,
            ))
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_economy.py -q`
Expected: `10 passed`.

- [ ] **Step 5: Commit**

```bash
git add civ7_advisor/advisors/economy.py tests/test_economy.py
git commit -m "Add economy advisor: yield gaps, settlement cap, gold, celebrations"
```

---

### Task 11: `run_all` and the end-to-end fixture test

**Files:**
- Modify: `civ7_advisor/advisors/__init__.py` (replace placeholder)
- Test: `tests/test_e2e.py`

**Interfaces:**
- Produces: `advisors.run_all(state) -> list[Insight]` (ranked); `advisors.ADVISORS` tuple; re-exports `Insight, Provenance, Severity`.

- [ ] **Step 1: Write the failing tests**

`tests/test_e2e.py`:
```python
from civ7_advisor.advisors import Provenance, Severity, run_all
from civ7_advisor.state.models import GameState


def test_fixture_end_to_end(fixture_state):
    insights = run_all(fixture_state)
    assert insights, "the live game should produce advice"
    assert insights[0].id == "threat.at_war.4" and insights[0].severity is Severity.CRITICAL
    ids_ = [i.id for i in insights]
    assert len(ids_) == len(set(ids_))
    severities = [int(i.severity) for i in insights]
    assert severities == sorted(severities, reverse=True)
    assert all(i.title.strip() and i.recommendation.strip() and i.why.strip() for i in insights)
    assert all(i.turn == 81 for i in insights)
    assert {i.advisor for i in insights} == {"threat", "victory", "economy"}
    assert {"threat.war_intent.1", "economy.behind.food", "victory.pursuing.4.CULTURAL"} <= set(ids_)


def test_fair_view_alone_still_flags_the_real_problems(fixture_state):
    insights = run_all(fixture_state)
    fair = {i.id for i in insights if i.provenance is Provenance.FAIR}
    oracle = {i.id for i in insights if i.provenance is Provenance.ORACLE}
    assert fair and oracle
    assert {"threat.active_front.4", "threat.military_gap.1", "economy.behind.food"} <= fair
    assert {"threat.at_war.4", "threat.war_intent.1", "threat.targeting.4"} <= oracle


def test_empty_state_yields_no_insights():
    assert run_all(GameState()) == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_e2e.py -q`
Expected: FAIL with `ImportError: cannot import name 'run_all'`.

- [ ] **Step 3: Write the implementation**

Replace `civ7_advisor/advisors/__init__.py` with:
```python
"""Advisors turn a GameState into ranked Insights. Each module exposes advise(state)."""
from __future__ import annotations

from civ7_advisor.state.models import GameState

from . import checklist, economy, threat, victory
from .base import Insight, Provenance, Severity

ADVISORS = (threat, victory, economy)

__all__ = ["ADVISORS", "Insight", "Provenance", "Severity", "economy", "run_all", "threat", "victory"]


def run_all(state: GameState) -> list[Insight]:
    insights: list[Insight] = []
    for module in ADVISORS:
        insights.extend(module.advise(state))
    return checklist.rank(insights)
```

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest -q`
Expected: all tests pass (`67 passed`).

- [ ] **Step 5: Commit**

```bash
git add civ7_advisor/advisors/__init__.py tests/test_e2e.py
git commit -m "Add run_all and end-to-end fixture test"
```

---

### Task 12: Poller and Store

**Files:**
- Create: `civ7_advisor/ingest/poller.py`, `civ7_advisor/store.py`
- Test: `tests/test_poller.py`, `tests/test_store.py`

**Interfaces:**
- Produces: `poller.snapshot(logs_dir, names) -> dict[str, tuple[int, int] | None]`; `async poller.watch(logs_dir, names, on_change, interval=1.0, initial=None)` — calls `on_change()` in a worker thread once the snapshot has changed **and then stayed unchanged for one interval** (so half-written files are not parsed); `Store(logs_dir)` with `state: GameState | None`, `insights: list[Insight]`, `rebuild() -> GameState`, `subscribe() -> asyncio.Queue`, `unsubscribe(q)`, `publish(event: dict)`.

- [ ] **Step 1: Write the failing tests**

`tests/test_poller.py`:
```python
import asyncio
from pathlib import Path

from civ7_advisor.ingest.poller import snapshot, watch


def test_snapshot_reports_missing_files_as_none(tmp_path: Path):
    (tmp_path / "a.csv").write_text("1\n")
    snap = snapshot(tmp_path, ["a.csv", "b.csv"])
    assert snap["b.csv"] is None
    assert snap["a.csv"][1] == 2  # size in bytes


def test_watch_fires_once_after_a_quiet_interval(tmp_path: Path):
    f = tmp_path / "a.csv"
    f.write_text("1\n")
    calls: list[int] = []

    async def scenario():
        task = asyncio.create_task(watch(tmp_path, ["a.csv"], lambda: calls.append(1), interval=0.02))
        await asyncio.sleep(0.1)
        assert calls == []  # nothing changed
        f.write_text("1\n2\n")
        await asyncio.sleep(0.15)
        assert calls == [1]  # changed, then quiet -> exactly one rebuild
        task.cancel()

    asyncio.run(scenario())


def test_watch_waits_while_files_keep_changing(tmp_path: Path):
    f = tmp_path / "a.csv"
    f.write_text("1\n")
    calls: list[int] = []

    async def scenario():
        task = asyncio.create_task(watch(tmp_path, ["a.csv"], lambda: calls.append(1), interval=0.03))
        for i in range(5):  # keep writing faster than the interval
            f.write_text("1\n" * (i + 2))
            await asyncio.sleep(0.01)
        assert calls == []
        await asyncio.sleep(0.12)
        assert calls == [1]
        task.cancel()

    asyncio.run(scenario())
```

`tests/test_store.py`:
```python
import asyncio
from pathlib import Path

from civ7_advisor.store import Store


def test_rebuild_loads_fixture_and_ranks_insights(fixture_dir: Path):
    store = Store(fixture_dir)
    assert store.state is None and store.insights == []
    state = store.rebuild()
    assert state.latest_turn == 82 and store.state is state
    assert store.insights[0].id == "threat.at_war.4"


def test_publish_reaches_subscribers_and_unsubscribe_stops_it():
    async def scenario():
        store = Store(Path("."))
        q = store.subscribe()
        store.publish({"type": "state_changed", "turn": 5})
        assert await asyncio.wait_for(q.get(), 1) == {"type": "state_changed", "turn": 5}
        store.unsubscribe(q)
        store.publish({"type": "state_changed", "turn": 6})
        assert q.empty()

    asyncio.run(scenario())
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_poller.py tests/test_store.py -q`
Expected: FAIL with `ModuleNotFoundError` for `civ7_advisor.ingest.poller` / `civ7_advisor.store`.

- [ ] **Step 3: Write the implementation**

`civ7_advisor/ingest/poller.py`:
```python
"""Detect changes to the log files by polling their mtime and size.

Polling was chosen over a filesystem watcher: seven stat() calls a second are
free, it needs no extra dependency, and it avoids cross-thread debouncing.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Callable, Iterable

Snapshot = dict[str, tuple[int, int] | None]


def snapshot(logs_dir: Path, names: Iterable[str]) -> Snapshot:
    out: Snapshot = {}
    for name in names:
        try:
            st = (logs_dir / name).stat()
            out[name] = (st.st_mtime_ns, st.st_size)
        except FileNotFoundError:
            out[name] = None
    return out


async def watch(
    logs_dir: Path,
    names: list[str],
    on_change: Callable[[], None],
    interval: float = 1.0,
    initial: Snapshot | None = None,
) -> None:
    """Call `on_change` (in a worker thread) after the files change and then stay
    unchanged for one full interval — Civ VII writes its logs over a few hundred
    milliseconds, and we want the finished files, not the half-written ones.

    Runs until cancelled. `initial` is the snapshot the caller has already
    processed, so startup does not trigger a redundant rebuild.
    """
    last = snapshot(logs_dir, names) if initial is None else initial
    pending: Snapshot | None = None
    while True:
        await asyncio.sleep(interval)
        current = snapshot(logs_dir, names)
        if current == last:
            pending = None
            continue
        if pending is not None and current == pending:
            last = current
            pending = None
            await asyncio.to_thread(on_change)
        else:
            pending = current
```

`civ7_advisor/store.py`:
```python
"""Owns the current GameState and ranked insights; rebuilds and fans out change events."""
from __future__ import annotations

import asyncio
import threading
from pathlib import Path

from civ7_advisor.advisors import Insight, run_all
from civ7_advisor.ingest.load import load_logs
from civ7_advisor.state.build import build_state
from civ7_advisor.state.models import GameState


class Store:
    def __init__(self, logs_dir: Path) -> None:
        self.logs_dir = logs_dir
        self.state: GameState | None = None
        self.insights: list[Insight] = []
        self._lock = threading.Lock()
        self._subscribers: set[asyncio.Queue] = set()

    def rebuild(self) -> GameState:
        """Re-read every log and recompute advice. Safe to call from a worker thread."""
        state = build_state(load_logs(self.logs_dir))
        insights = run_all(state)
        with self._lock:
            self.state, self.insights = state, insights
        return state

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    def publish(self, event: dict) -> None:
        """Deliver an event to every subscriber. Call on the event-loop thread."""
        for q in list(self._subscribers):
            q.put_nowait(event)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_poller.py tests/test_store.py -q`
Expected: `5 passed`.

- [ ] **Step 5: Commit**

```bash
git add civ7_advisor/ingest/poller.py civ7_advisor/store.py tests/test_poller.py tests/test_store.py
git commit -m "Add quiet-period log poller and Store with SSE fan-out"
```

---

### Task 13: FastAPI application

**Files:**
- Create: `civ7_advisor/api/__init__.py`, `civ7_advisor/api/serialize.py`, `civ7_advisor/api/app.py`, `civ7_advisor/web/index.html` (placeholder — Task 14 replaces it)
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: `Store`, `poller.snapshot/watch`, `load.LOG_FILES`, `threat.summarize`, `victory.leaderboards`, `economy.comparison`.
- Produces: `serialize.insight_to_dict(i) -> dict` (severity as name, provenance as value), `serialize.state_to_dict(state) -> dict` with keys `latest_turn, complete_through_turn, in_progress, human, standings, ranks, threats, leaderboards, economy, files`; `app.create_app(logs_dir: Path, poll_interval: float = 1.0) -> FastAPI`; `app.WEB_DIR`.

- [ ] **Step 1: Write the failing tests**

`tests/test_api.py`:
```python
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from civ7_advisor.api.app import create_app


@pytest.fixture(scope="module")
def client(fixture_dir: Path):
    with TestClient(create_app(fixture_dir, poll_interval=60)) as c:
        yield c


def test_state_endpoint(client):
    r = client.get("/api/state")
    assert r.status_code == 200
    body = r.json()
    assert body["latest_turn"] == 82 and body["complete_through_turn"] == 81 and body["in_progress"] is True
    assert [s["id"] for s in body["standings"]] == [0, 1, 2, 3, 4, 5, 6, 7]
    napoleon = body["standings"][3]
    assert napoleon["alive"] is False and napoleon["stats"] is None
    assert body["ranks"]["science"] == [7, 7]
    assert body["ranks"]["gold"] == [4, 7]
    assert body["ranks"]["military_units"] == [6, 7]
    assert body["standings"][0]["stats"]["net_gold"] == 19.0
    assert {t["player"] for t in body["threats"]} == {1, 2, 4, 5, 6, 7}
    assert body["leaderboards"]["ECONOMIC"][0]["name"] == "Harriet Tubman"
    assert {c["stat"] for c in body["economy"]} == {"science", "culture", "gold", "production", "food"}
    assert all(f["ok"] for f in body["files"].values())
    strategies = {s["strategy"]: s for s in body["standings"][4]["strategies"]}  # player 4
    assert strategies["CULTURAL"]["weight"] == 100 and strategies["CULTURAL"]["following"] is True


def test_insights_endpoint(client):
    body = client.get("/api/insights").json()
    assert body[0]["id"] == "threat.at_war.4"
    assert body[0]["severity"] == "CRITICAL" and body[0]["provenance"] == "oracle"
    assert all(i["why"] for i in body)


def test_index_and_static(client):
    assert "Civ VII Advisor" in client.get("/").text
    assert client.get("/static/index.html").status_code == 200


def test_state_is_503_before_first_rebuild(fixture_dir: Path):
    app = create_app(fixture_dir)  # no lifespan entered -> never rebuilt
    assert TestClient(app).get("/api/state").status_code == 503
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_api.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'civ7_advisor.api'`.

- [ ] **Step 3: Write the implementation**

`civ7_advisor/api/__init__.py`:
```python
"""HTTP layer: JSON state, ranked insights, SSE change events, static dashboard."""
```

`civ7_advisor/web/index.html` (placeholder so `/static` can mount; replaced in Task 14):
```html
<!doctype html><title>Civ VII Advisor</title><p>Dashboard coming in Task 14.</p>
```

`civ7_advisor/api/serialize.py`:
```python
"""JSON shapes for the API. Enums become names/values; dataclasses become dicts."""
from __future__ import annotations

from dataclasses import asdict

from civ7_advisor.advisors import Insight, economy, threat, victory
from civ7_advisor.state.models import GameState, PlayerKind, PlayerTurn

RANK_STATS = ["science", "culture", "production", "gold", "military_units"]


def insight_to_dict(i: Insight) -> dict:
    d = asdict(i)
    d["severity"] = i.severity.name
    d["provenance"] = i.provenance.value
    return d


def _ranks(state: GameState) -> dict[str, list[int]]:
    """Human's rank (1 = best) and field size among alive majors, per stat."""
    t = state.complete_through_turn
    rows = [(p.id, state.at(p.id, t)) for p in state.majors()]
    rows = [(pid, pt) for pid, pt in rows if pt is not None]
    out: dict[str, list[int]] = {}
    for stat in RANK_STATS:
        ordered = sorted(rows, key=lambda r: getattr(r[1], stat), reverse=True)
        position = next((i for i, (pid, _) in enumerate(ordered) if pid == state.HUMAN), None)
        if position is not None:
            out[stat] = [position + 1, len(ordered)]
    return out


def _player_turn_dict(pt: PlayerTurn | None) -> dict | None:
    if pt is None:
        return None
    d = asdict(pt)
    d["settlements"] = pt.settlements
    d["military_units"] = pt.military_units
    d["net_gold"] = pt.net_gold
    d["celebration_progress"] = pt.celebration_progress
    return d


def state_to_dict(state: GameState) -> dict:
    t = state.complete_through_turn
    standings = []
    for p in sorted(state.players.values(), key=lambda p: p.id):
        if p.kind is PlayerKind.INDEPENDENT:
            continue
        standings.append({
            "id": p.id, "name": p.name, "kind": p.kind.value, "alive": p.alive,
            "last_seen_turn": p.last_seen_turn, "stats": _player_turn_dict(state.at(p.id, t)),
            "strategies": [
                asdict(s) | {"following": s.following} for s in state.strategies.get(p.id, {}).values()
            ],
        })
    return {
        "latest_turn": state.latest_turn,
        "complete_through_turn": t,
        "in_progress": state.latest_turn > t,
        "human": state.HUMAN,
        "standings": standings,
        "ranks": _ranks(state),
        "threats": [asdict(r) for r in threat.summarize(state)],
        "leaderboards": {
            path: [{"id": p.id, "name": p.name, "value": v} for p, v in board]
            for path, board in victory.leaderboards(state).items()
        },
        "economy": [asdict(c) for c in economy.comparison(state)],
        "files": {name: asdict(fs) for name, fs in state.files.items()},
    }
```

`civ7_advisor/api/app.py`:
```python
"""FastAPI application factory."""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from civ7_advisor.ingest.load import LOG_FILES
from civ7_advisor.ingest.poller import snapshot, watch
from civ7_advisor.store import Store

from .serialize import insight_to_dict, state_to_dict

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
KEEPALIVE_SECONDS = 15


def create_app(logs_dir: Path, poll_interval: float = 1.0) -> FastAPI:
    store = Store(logs_dir)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        loop = asyncio.get_running_loop()
        initial = snapshot(logs_dir, LOG_FILES)
        await asyncio.to_thread(store.rebuild)

        def on_change() -> None:  # runs in a worker thread
            state = store.rebuild()
            loop.call_soon_threadsafe(
                store.publish, {"type": "state_changed", "turn": state.latest_turn}
            )

        task = asyncio.create_task(watch(logs_dir, LOG_FILES, on_change, poll_interval, initial))
        try:
            yield
        finally:
            task.cancel()

    app = FastAPI(title="Civ VII Advisor", lifespan=lifespan)
    app.state.store = store

    @app.get("/api/state")
    def api_state() -> dict:
        if store.state is None:
            raise HTTPException(status_code=503, detail="state not loaded yet")
        return state_to_dict(store.state)

    @app.get("/api/insights")
    def api_insights() -> list[dict]:
        return [insight_to_dict(i) for i in store.insights]

    @app.get("/events")
    async def events() -> StreamingResponse:
        return StreamingResponse(
            _event_stream(store), media_type="text/event-stream",
            headers={"Cache-Control": "no-cache"},
        )

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
    return app


async def _event_stream(store: Store):
    queue = store.subscribe()
    try:
        yield "retry: 2000\n\n"
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=KEEPALIVE_SECONDS)
                yield f"data: {json.dumps(event)}\n\n"
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
    finally:
        store.unsubscribe(queue)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_api.py -q`
Expected: `4 passed`.

- [ ] **Step 5: Commit**

```bash
git add civ7_advisor/api civ7_advisor/web/index.html tests/test_api.py
git commit -m "Add FastAPI app: state and insights JSON, SSE events, static mount"
```

---

### Task 14: Dashboard page

**Files:**
- Modify: `civ7_advisor/web/index.html` (replace placeholder)
- Create: `civ7_advisor/web/style.css`, `civ7_advisor/web/app.js`
- Modify: `tests/test_api.py` (extend `test_index_and_static`)

**Interfaces:**
- Consumes: `/api/state`, `/api/insights`, `/events` exactly as produced in Task 13 (field names: `threats[].war_score`, `war_score_since`, `at_war_since`, `kills`, `losses`, `city_tiles_targeted`, `units_targeted`, `military_ratio`, `land_units`; `standings[].strategies[]` with `strategy, status, weight, following`; `economy[]` with `label, human, rival_median, ratio, leader_name, leader_value`; `ranks` as `{stat: [rank, count]}`).

- [ ] **Step 1: Extend the failing test**

Replace `test_index_and_static` in `tests/test_api.py` with:
```python
def test_index_and_static(client):
    page = client.get("/").text
    assert "<title>Civ VII Advisor</title>" in page and 'id="oracle"' in page
    for tab in ("checklist", "threats", "victory", "economy"):
        assert f'data-tab="{tab}"' in page
    js = client.get("/static/app.js")
    assert js.status_code == 200 and "EventSource" in js.text and "/api/insights" in js.text
    assert client.get("/static/style.css").status_code == 200
```

Run: `uv run pytest tests/test_api.py::test_index_and_static -q`
Expected: FAIL (`id="oracle"` not in the placeholder page).

- [ ] **Step 2: Write the page**

`civ7_advisor/web/index.html`:
```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Civ VII Advisor</title>
<link rel="stylesheet" href="/static/style.css">
</head>
<body>
<header class="bar">
  <div class="turn"><span id="turn">Turn —</span><span id="progress" class="badge hidden"></span></div>
  <div id="ranks" class="ranks"></div>
  <div id="top" class="top"></div>
  <label class="toggle" title="Show advice that uses AI-internal data the game hides from you">
    <input type="checkbox" id="oracle" checked> Oracle
  </label>
  <div id="files" class="files"></div>
</header>
<nav class="tabs">
  <button data-tab="checklist" class="active">Checklist</button>
  <button data-tab="threats">Threats</button>
  <button data-tab="victory">Victory</button>
  <button data-tab="economy">Economy</button>
</nav>
<main>
  <section id="checklist" class="tab active"></section>
  <section id="threats" class="tab"><div id="threats-table"></div><div id="threats-cards"></div></section>
  <section id="victory" class="tab"><div id="victory-table"></div><div id="victory-cards"></div></section>
  <section id="economy" class="tab"><div id="economy-table"></div><div id="economy-cards"></div></section>
</main>
<script src="/static/app.js"></script>
</body>
</html>
```

`civ7_advisor/web/style.css`:
```css
:root {
  --bg: #14161c; --panel: #1d2028; --line: #2c303b; --text: #e6e6e6; --muted: #9aa0ad;
  --info: #5b8def; --advise: #4fb286; --warn: #e0a72f; --critical: #e5533d; --oracle: #b07cf0;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text);
  font: 14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
.bar { display: flex; flex-wrap: wrap; gap: 12px; align-items: center; padding: 10px 16px;
  background: var(--panel); border-bottom: 1px solid var(--line); position: sticky; top: 0; z-index: 2; }
.turn { font-size: 20px; font-weight: 600; display: flex; gap: 8px; align-items: center; }
.badge { font-size: 11px; padding: 2px 6px; border-radius: 10px; background: var(--line); color: var(--muted); }
.badge.oracle { background: var(--oracle); color: #fff; }
.hidden { display: none; }
.chip { font-size: 12px; padding: 2px 8px; border-radius: 10px; background: var(--line);
  color: var(--muted); margin-right: 6px; white-space: nowrap; }
.chip.warn { background: var(--warn); color: #000; }
.top { flex: 1; min-width: 200px; font-weight: 600; }
.top-critical { color: var(--critical); } .top-warn { color: var(--warn); }
.top-advise { color: var(--advise); } .top-info { color: var(--info); }
.toggle { color: var(--muted); display: flex; gap: 6px; align-items: center; cursor: pointer; }
.tabs { display: flex; gap: 4px; padding: 8px 16px 0; border-bottom: 1px solid var(--line); }
.tabs button { background: none; border: 1px solid transparent; border-bottom: none; color: var(--muted);
  padding: 8px 14px; cursor: pointer; border-radius: 6px 6px 0 0; font: inherit; }
.tabs button.active { color: var(--text); background: var(--panel); border-color: var(--line); }
main { padding: 16px; }
.tab { display: none; } .tab.active { display: block; }
.cards { display: grid; gap: 10px; }
.card { background: var(--panel); border: 1px solid var(--line); border-left: 4px solid var(--info);
  border-radius: 6px; padding: 10px 14px; }
.card.sev-advise { border-left-color: var(--advise); }
.card.sev-warn { border-left-color: var(--warn); }
.card.sev-critical { border-left-color: var(--critical); }
.card.prov-oracle { border-style: dashed; border-left-style: solid; }
.card-head { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.sev { font-size: 11px; font-weight: 700; letter-spacing: .04em; color: var(--muted); }
.title { font-weight: 600; }
.rec { margin: 6px 0 4px; }
.why { margin: 0; color: var(--muted); font-size: 13px; }
.empty { color: var(--muted); }
.table-wrap { overflow-x: auto; margin-bottom: 14px; }
table { border-collapse: collapse; width: 100%; background: var(--panel); }
th, td { text-align: left; padding: 6px 10px; border-bottom: 1px solid var(--line); white-space: nowrap; }
th { color: var(--muted); font-weight: 600; font-size: 12px; }
```

`civ7_advisor/web/app.js`:
```js
(() => {
  const $ = (sel) => document.querySelector(sel);
  const el = (tag, cls, text) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  };
  const fmt = (v, digits = 1) => (v === null || v === undefined) ? "—" : Number(v).toFixed(digits);

  const state = { data: null, insights: [], showOracle: true };
  try { state.showOracle = localStorage.getItem("civ7.oracle") !== "off"; } catch (_) { /* private mode */ }
  $("#oracle").checked = state.showOracle;
  $("#oracle").addEventListener("change", (e) => {
    state.showOracle = e.target.checked;
    try { localStorage.setItem("civ7.oracle", state.showOracle ? "on" : "off"); } catch (_) { /* ignore */ }
    render();
  });

  document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => {
    document.querySelectorAll(".tabs button, .tab").forEach((x) => x.classList.remove("active"));
    b.classList.add("active");
    $("#" + b.dataset.tab).classList.add("active");
  }));

  async function refresh() {
    const [s, i] = await Promise.all([fetch("/api/state"), fetch("/api/insights")]);
    if (!s.ok || !i.ok) return;
    state.data = await s.json();
    state.insights = await i.json();
    render();
  }

  const visible = () => state.insights.filter((x) => state.showOracle || x.provenance !== "oracle");

  function card(ins) {
    const c = el("article", `card sev-${ins.severity.toLowerCase()} prov-${ins.provenance}`);
    const head = el("div", "card-head");
    head.append(el("span", "sev", ins.severity), el("span", "title", ins.title));
    if (ins.provenance === "oracle") head.append(el("span", "badge oracle", "Oracle"));
    c.append(head, el("p", "rec", ins.recommendation), el("p", "why", "Why: " + ins.why));
    return c;
  }
  function cards(list) {
    const wrap = el("div", "cards");
    if (!list.length) wrap.append(el("p", "empty", "Nothing to report."));
    list.forEach((i) => wrap.append(card(i)));
    return wrap;
  }
  function table(headers, rows) {
    const t = el("table");
    const head = el("tr");
    headers.forEach((h) => head.append(el("th", null, h)));
    t.append(head);
    rows.forEach((r) => { const tr = el("tr"); r.forEach((c) => tr.append(el("td", null, String(c)))); t.append(tr); });
    const wrap = el("div", "table-wrap");
    wrap.append(t);
    return wrap;
  }

  function render() {
    const d = state.data;
    if (!d) return;
    $("#turn").textContent = `Turn ${d.complete_through_turn}`;
    const progress = $("#progress");
    progress.classList.toggle("hidden", !d.in_progress);
    progress.textContent = `turn ${d.latest_turn} in progress`;
    $("#ranks").replaceChildren(...Object.entries(d.ranks).map(([k, [r, n]]) =>
      el("span", "chip", `${k.replace("_", " ")} #${r}/${n}`)));
    const ins = visible();
    $("#top").replaceChildren(ins.length
      ? el("span", `top-${ins[0].severity.toLowerCase()}`, `${ins[0].severity}: ${ins[0].title}`)
      : el("span", null, "All quiet"));
    $("#files").replaceChildren(...Object.values(d.files).filter((f) => !f.ok)
      .map((f) => el("span", "chip warn", `${f.name}: ${f.error}`)));

    $("#checklist").replaceChildren(cards(ins));
    const byAdvisor = (a) => ins.filter((i) => i.advisor === a);

    $("#threats-table").replaceChildren(table(
      ["Rival", "Land units", "vs you", "War score", "At war", "Kills / your losses", "Targeting"],
      d.threats.map((t) => [
        t.name, t.land_units, `${fmt(t.military_ratio)}x`,
        t.war_score === null ? "—" : `${fmt(t.war_score, 0)} since t${t.war_score_since}`,
        t.at_war_since === null ? "no" : `since t${t.at_war_since}`,
        `${t.kills} / ${t.losses}`,
        (t.city_tiles_targeted || t.units_targeted) ? `${t.city_tiles_targeted} city tiles, ${t.units_targeted} units` : "—",
      ])));
    $("#threats-cards").replaceChildren(cards(byAdvisor("threat")));

    const paths = ["SCIENCE", "CULTURAL", "MILITARY", "ECONOMIC"];
    const strategyRows = d.standings.filter((s) => s.kind === "rival" && s.alive).map((s) => [
      s.name, ...paths.map((p) => {
        const st = s.strategies.find((x) => x.strategy === p);
        return st ? `${st.status}${st.following ? " " + st.weight : ""}` : "—";
      }),
    ]);
    const boards = Object.entries(d.leaderboards).map(([p, b]) => [p, b.map((x) => `${x.name} ${fmt(x.value)}`).join("  ›  ")]);
    $("#victory-table").replaceChildren(
      table(["Rival", "Science", "Cultural", "Military", "Economic"], strategyRows),
      table(["Path", "Leaderboard (best first)"], boards));
    $("#victory-cards").replaceChildren(cards(byAdvisor("victory")));

    $("#economy-table").replaceChildren(table(
      ["Yield", "You", "Rival median", "You / median", "Leader"],
      d.economy.map((c) => [c.label, fmt(c.human), fmt(c.rival_median), `${Math.round(c.ratio * 100)}%`, `${c.leader_name} ${fmt(c.leader_value)}`])));
    $("#economy-cards").replaceChildren(cards(byAdvisor("economy")));
  }

  function connect() {
    const es = new EventSource("/events");
    es.onmessage = () => refresh();
    es.onerror = () => { es.close(); setTimeout(connect, 2000); };
  }

  refresh();
  connect();
})();
```

- [ ] **Step 3: Run the API tests**

Run: `uv run pytest tests/test_api.py -q`
Expected: `4 passed`.

- [ ] **Step 4: Manual check against the fixture**

Run (in a terminal, leave it running):
```bash
uv run uvicorn --factory --port 8765 "civ7_advisor.api.app:create_app" --reload
```
That fails because `create_app` needs `logs_dir`; instead run:
```bash
uv run python -c "import uvicorn, pathlib; from civ7_advisor.api.app import create_app; uvicorn.run(create_app(pathlib.Path('tests/fixtures/logs_82turns')), port=8765)"
```
Open `http://127.0.0.1:8765`. Verify: header reads "Turn 81" with a "turn 82 in progress" badge and five rank chips (science #7/7 …); the top line is "CRITICAL: José Rizal has declared war on you"; the Checklist tab shows dashed "Oracle" cards; unticking **Oracle** removes them and the top line becomes the active-front WARN; Threats table shows Rizal at war since t80 and Ibn Battuta at 202 since t72; Economy table shows food 41%. Then append a line to `tests/fixtures/logs_82turns/Player_Stats.csv` in another shell, wait ~2 s, and confirm the page updates without a reload; **revert that edit** (`git checkout tests/fixtures/logs_82turns/Player_Stats.csv`). Stop the server.

- [ ] **Step 5: Commit**

```bash
git add civ7_advisor/web tests/test_api.py
git commit -m "Add dashboard page with four tabs, Oracle toggle and live SSE refresh"
```

---

### Task 15: CLI entry point and README

**Files:**
- Create: `civ7_advisor/cli.py`, `README.md`
- Test: `tests/test_cli.py`

**Interfaces:**
- Produces: `cli.DEFAULT_LOGS_DIR: Path`, `cli.main(argv: list[str] | None = None) -> int` (exit 2 when the logs dir is missing; otherwise runs uvicorn and returns 0).

- [ ] **Step 1: Write the failing tests**

`tests/test_cli.py`:
```python
from pathlib import Path

from civ7_advisor import cli


def test_default_logs_dir_is_the_macos_civ_vii_logs_folder():
    assert cli.DEFAULT_LOGS_DIR == Path.home() / "Library/Application Support/Civilization VII/Logs"


def test_missing_logs_dir_exits_2_with_a_helpful_message(tmp_path: Path, capsys):
    rc = cli.main(["--logs-dir", str(tmp_path / "nope")])
    err = capsys.readouterr().err
    assert rc == 2
    assert "not found" in err and "--logs-dir" in err and str(tmp_path / "nope") in err


def test_server_is_started_with_parsed_options(fixture_dir: Path, monkeypatch):
    calls = {}

    def fake_run(app, host, port, log_level):
        calls.update(app=app, host=host, port=port, log_level=log_level)

    monkeypatch.setattr(cli.uvicorn, "run", fake_run)
    rc = cli.main(["--logs-dir", str(fixture_dir), "--port", "9000", "--host", "0.0.0.0"])
    assert rc == 0
    assert calls["port"] == 9000 and calls["host"] == "0.0.0.0"
    assert calls["app"].title == "Civ VII Advisor"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_cli.py -q`
Expected: FAIL with `ImportError: cannot import name 'cli'`.

- [ ] **Step 3: Write the implementation**

`civ7_advisor/cli.py`:
```python
"""`civ7-advisor` command: start the dashboard server."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import uvicorn

from civ7_advisor.api.app import create_app

DEFAULT_LOGS_DIR = Path.home() / "Library/Application Support/Civilization VII/Logs"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="civ7-advisor",
        description="Second-screen turn advisor for Civilization VII. Reads the game's own log "
                    "files; never writes to them.",
    )
    parser.add_argument("--logs-dir", type=Path, default=DEFAULT_LOGS_DIR,
                        help=f"Civ VII Logs directory (default: {DEFAULT_LOGS_DIR})")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--poll-interval", type=float, default=1.0,
                        help="seconds between checks of the log files (default 1.0)")
    args = parser.parse_args(argv)

    if not args.logs_dir.is_dir():
        print(
            f"Civ VII log directory not found: {args.logs_dir}\n"
            f"Start the game once so it creates the folder, or pass --logs-dir <path>.",
            file=sys.stderr,
        )
        return 2

    app = create_app(args.logs_dir, args.poll_interval)
    print(f"Civ VII Advisor -> http://{args.host}:{args.port}  (reading {args.logs_dir})")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

`README.md`:
```markdown
# Civ VII Turn Advisor

A second-screen dashboard for single-player Civilization VII. It tails the
game's own log files (`~/Library/Application Support/Civilization VII/Logs`)
and, every turn, shows where each rival stands, who is a threat and why, who
is pursuing and leading each legacy path, how your economy compares, and a
ranked checklist of things to do — each with the evidence behind it.

It never writes to the game. Everything runs locally and offline.

## Run

    uv sync
    uv run civ7-advisor

Open http://127.0.0.1:8765 on your second screen and play. The page updates
by itself about a second after the game finishes writing a turn.

Options: `--logs-dir PATH` (if your logs live elsewhere), `--port`, `--host`,
`--poll-interval`.

## Fair vs Oracle

Advice built only from things you could see in-game is **Fair**. Advice that
uses the AI's internal logs — its war-intent scores, its target lists, the
legacy path it has committed to — is **Oracle**, drawn with a dashed border
and a badge. Untick **Oracle** in the header to see whether the fair evidence
alone would have told you the same thing. That comparison is the point: it
shows you where your read of the game was right and where it wasn't.

## Tuning

Every threshold is a named constant at the top of its advisor module:
`civ7_advisor/advisors/threat.py`, `victory.py`, `economy.py`. Change a
number, restart, done.

## Tests

    uv run pytest

The test fixture in `tests/fixtures/logs_82turns/` is a snapshot of a real
82-turn game, so the whole pipeline is exercised against genuine Civ VII
output. Try the dashboard against it without the game running:

    uv run civ7-advisor --logs-dir tests/fixtures/logs_82turns

## Design

See `docs/superpowers/specs/2026-09-07-civ7-turn-advisor-design.md`.
```

- [ ] **Step 4: Run the whole suite and the real command**

Run: `uv run pytest -q`
Expected: all tests pass (`79 passed`).

Run: `uv run civ7-advisor --logs-dir tests/fixtures/logs_82turns`
Expected: prints `Civ VII Advisor -> http://127.0.0.1:8765  (reading tests/fixtures/logs_82turns)`; the page loads as in Task 14. Ctrl-C to stop. If Civ VII is installed, also run plain `uv run civ7-advisor` and confirm it reads the live logs directory.

- [ ] **Step 5: Commit**

```bash
git add civ7_advisor/cli.py README.md tests/test_cli.py
git commit -m "Add civ7-advisor CLI entry point and README"
```

---

## Self-review notes

- **Spec coverage:** §2 files → Tasks 2–5; §2.1 hazards 1 (Task 2), 2–3 (Task 6), 4–5 (Task 4), 6 (Task 6), 7 (Task 2), 8 (Task 6 joins by turn), 9 (Task 6 `display_name`); §3.1 → Tasks 2–5, 12; §3.2 → Task 6; §3.3 → Tasks 7–11; §3.4 → Tasks 12–13; §3.5 → Task 14; §4 error handling → Task 5 (per-file isolation), Task 13 (503), Task 15 (exit 2), Task 14 (file chips, SSE reconnect); §5 tests → every task; §7 tooling → Tasks 1, 15.
- **Type consistency:** `DiplomacyRow.actor` (not `player`) is used in `threat.py`; `RivalThreat` field names match what `app.js` reads; `PlayerTurn` field names equal `StatsRow` field names so `PlayerTurn(**asdict(stats_row), **extra)` works; `Insight` keyword names are identical across all three advisors.
- **Test counts** stated after Tasks 11 and 15 assume every earlier task's tests are present; if a count differs by one or two because of parametrization, the "all pass" condition is what matters.
