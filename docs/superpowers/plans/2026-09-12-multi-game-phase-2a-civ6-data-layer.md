# Multi-Game Advisor — Phase 2a: The Civ VI Data Layer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a `civ6` GameProfile that turns Civilization VI's logs into
the same canonical `GameState` the advisors already consume, with every
signal Civ VI cannot supply declared unavailable rather than defaulted.

**Architecture:** Civ VI declares its own reader table behind the
`GameProfile` seam phase 1 built. Five of Civ VII's readers are reused
unchanged; five get Civ VI variants that map into the *same* row
dataclasses; ten Civ VII files have no Civ VI counterpart and are simply
not declared. Canonical fields a game cannot fill become `T | None`, and
each profile declares which capabilities it supports so an advisor asking
for a missing signal gets "unavailable", never `0.0`.

**Tech Stack:** Python 3.12, dataclasses, pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-12-multi-game-advisor-design.md`
(this plan implements §11 phase 2a; §3, §5 and §6 are the binding detail).

## Global Constraints

- **Civ VII's behaviour must not change.** The suite stands at **501
  passing**; every pre-existing test must still pass with its assertions
  untouched. If a task seems to require editing a Civ VII assertion, stop
  and report BLOCKED.
- **Read-only** with respect to both games' directories.
- Python `>=3.12`. No new runtime dependencies.
- `filterwarnings = ["error", ...]`; a new warning fails the suite.
- **Absence is declared, never inferred.** A canonical field a game cannot
  supply is `None` AND the profile declares the capability unsupported.
  Returning `0.0`, `""` or an empty list in place of an unavailable signal
  is the single defect this phase exists to prevent: the project's whole
  premise is that it never asserts what its data cannot support.
- **Civ VI does NOT declare an `AI_Victories` reader.** Its file exists but
  holds era/posture strategies (`STRATEGY_DARKAGE`,
  `STRATEGY_EARLY_EXPLORATION`), not victory paths. `VictoryRow.strategy`
  is contractually one of SCIENCE/CULTURAL/MILITARY/ECONOMIC/ESPIONAGE.
  Feeding VI's values in would make the victory advisor assert a rival is
  pursuing a victory on the strength of a row that says nothing of the
  kind. Victory-path advice is declared unsupported for Civ VI.
- All Civ VI facts in this plan were verified on 2026-09-12 against a real
  turn-53 capture. Where a step states a number, it was measured.

## Fixture

Tasks 3 onward need Civ VI logs. A 25-file, turn-53 capture is at:
`/private/tmp/claude-501/-Users-carlosbarbosa-Documents-GitHub-CIV-VII-Help/2c5c83ca-a788-43f0-b812-b0937b548bec/scratchpad/civ6-fixture-raw`
Task 3 Step 1 copies a trimmed version into `tests/fixtures/logs_civ6/`.
If that path is gone, the source logs persist at
`~/Library/Application Support/Sid Meier's Civilization VI/Firaxis Games/Sid Meier's Civilization VI/Logs`
(Civ VI appends rather than truncating).

---

### Task 1: Canonical fields become optional, and profiles declare capabilities

**Files:**
- Modify: `civ_advisor/ingest/readers.py` (`StatsRow`, `VictoryRow`)
- Modify: `civ_advisor/state/models.py` (`PlayerTurn`, `StrategyStatus`)
- Modify: `civ_advisor/games/base.py` (`GameProfile.capabilities`)
- Test: `tests/test_games.py`, `tests/test_state.py`

**Interfaces:**
- Consumes: `GameProfile` from phase 1.
- Produces:
  - `civ_advisor.games.base.Capability` — a `StrEnum` with members
    `VICTORY_PATHS`, `HAPPINESS`, `MAINTENANCE`, `PEACE_DEALS`,
    `COMBAT_ODDS`, `SETTLEMENT_CAP`, `URBAN_RURAL_SPLIT`, `FAITH`,
    `CIVICS`, `TOURISM`, `DIPLOMATIC_FAVOR`.
  - `GameProfile.capabilities: frozenset[Capability]`, and
    `GameProfile.supports(c: Capability) -> bool`.
  - `StatsRow` fields `towns`, `settlement_cap`, `settlements_over_cap`,
    `urban_pop`, `rural_pop`, `happiness`, `diplomacy` become `| None`;
    new optional fields `civics`, `faith_balance`, `faith`, `corps`,
    `armies`.
  - `StrategyStatus.weight` becomes `int | None`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_games.py`:

```python
def test_a_profile_declares_what_it_supports():
    from civ_advisor.games.base import Capability, GameProfile

    profile = GameProfile(
        id="capgame", display_name="Cap Game", default_logs_dir=Path("/tmp/logs"),
        readers=(), knowledge_package="civ_advisor.knowledge",
        capabilities=frozenset({Capability.HAPPINESS}),
    )
    assert profile.supports(Capability.HAPPINESS)
    assert not profile.supports(Capability.VICTORY_PATHS)


def test_civ7_supports_everything_it_did_before():
    """Phase 1 changed no behaviour, so civ7 must declare every capability;
    a missing one here would silently switch off a working Civ VII panel."""
    from civ_advisor.games.base import Capability
    from civ_advisor.games.civ7 import CIV7

    assert set(CIV7.capabilities) == set(Capability)
```

Append to `tests/test_state.py`:

```python
def test_optional_stats_fields_default_to_none_not_zero():
    """A game that cannot supply happiness must yield None. 0.0 would read as
    'this civ is miserable' rather than 'this game has no such concept'."""
    from civ_advisor.state.models import PlayerTurn

    pt = PlayerTurn(turn=1, player=0, cities=1, techs=2, land_units=1,
                    naval_units=0, tiles_owned=5, tiles_improved=1,
                    gold_balance=10.0, science=1.0, culture=1.0, gold=2.0,
                    production=3.0, food=4.0)
    assert pt.happiness is None
    assert pt.towns is None
    assert pt.settlement_cap is None
    assert pt.diplomacy is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_games.py tests/test_state.py -v -k "declares or optional or supports"`
Expected: FAIL — `GameProfile.__init__() got an unexpected keyword argument 'capabilities'`, and `PlayerTurn` requiring `happiness`.

- [ ] **Step 3: Add `Capability` and the profile field**

In `civ_advisor/games/base.py`, above `LogReader`:

```python
from enum import StrEnum


class Capability(StrEnum):
    """A signal or panel a game may or may not be able to support.

    Declared per profile rather than inferred from data: a log that is merely
    empty this turn is not the same as a game that has no such concept, and
    only the profile knows which is which.
    """

    VICTORY_PATHS = "victory_paths"
    HAPPINESS = "happiness"
    MAINTENANCE = "maintenance"
    PEACE_DEALS = "peace_deals"
    COMBAT_ODDS = "combat_odds"
    SETTLEMENT_CAP = "settlement_cap"
    URBAN_RURAL_SPLIT = "urban_rural_split"
    FAITH = "faith"
    CIVICS = "civics"
    TOURISM = "tourism"
    DIPLOMATIC_FAVOR = "diplomatic_favor"
```

Add to `GameProfile`, after `knowledge_package`:

```python
    capabilities: frozenset[Capability] = frozenset()

    def supports(self, capability: Capability) -> bool:
        return capability in self.capabilities
```

- [ ] **Step 4: Make the optional fields optional**

In `civ_advisor/ingest/readers.py`, change `StatsRow` so that `towns`,
`settlement_cap`, `settlements_over_cap`, `urban_pop`, `rural_pop`,
`happiness` and `diplomacy` are typed `| None` with default `None`, and add
`civics: int | None = None`, `faith_balance: float | None = None`,
`faith: float | None = None`, `corps: int | None = None`,
`armies: int | None = None`.

**Do not add a `civilization` field.** An earlier draft of this plan carried
Civ VI's row key on `StatsRow` for `build_state` to resolve. That breaks the
pre-existing `tests/test_state.py::test_player_turn_covers_every_stats_field`,
which asserts every `StatsRow` field is also a `PlayerTurn` field — a real
guard against a stats field being silently dropped before it reaches the
state. Task 4's reader resolves player ids itself instead (see there).

Every field with a default must follow the
fields without one — reorder so the required Civ VII/VI-common fields
(`turn`, `player`, `cities`, `techs`, `land_units`, `naval_units`,
`tiles_owned`, `tiles_improved`, `gold_balance`, `science`, `culture`,
`gold`, `production`, `food`) come first.

`civ_advisor/ingest/readers.py`'s `read_player_stats` builds `StatsRow(**values)`
from `columns.py`, so it keeps supplying every Civ VII field by name and is
otherwise untouched.

Mirror the same field changes on `PlayerTurn` in `civ_advisor/state/models.py`,
and change `StrategyStatus.weight` to `int | None`.

- [ ] **Step 5: Declare civ7's capabilities**

In `civ_advisor/games/civ7/__init__.py`, add to the `CIV7` profile:

```python
    capabilities=frozenset(Capability),   # Civ VII supports every capability this build models
```

importing `Capability` from `..base`.

- [ ] **Step 6: Run the full suite**

```bash
uv run pytest -q 2>&1 | tail -3
```

Expected: **504 passed** (501 + 3 new), zero failures. A failure here means
a Civ VII field was made optional that its own reader relies on positionally.

- [ ] **Step 7: Commit**

```bash
git add civ_advisor/games/base.py civ_advisor/games/civ7/__init__.py \
        civ_advisor/ingest/readers.py civ_advisor/state/models.py \
        tests/test_games.py tests/test_state.py
git commit -m "Let a profile declare what its game cannot support

A signal one game lacks is now declared unavailable rather than arriving
as a zero that reads like a measurement."
```

---

### Task 2: Widen `LogReader.read` so a reader can join across files

**Files:**
- Modify: `civ_advisor/games/base.py` (`LogReader.read` signature, `simple` helper)
- Modify: `civ_advisor/games/civ7/__init__.py` (wrap its 21 readers)
- Modify: `civ_advisor/ingest/load.py` (pass the directory)
- Test: `tests/test_ingest_load.py`

**Interfaces:**
- Produces:
  - `LogReader.read: Callable[[Path, Path], list]` — called as
    `read(logs_dir, path)`.
  - `civ_advisor.games.base.simple(fn: Callable[[Path], list]) -> Callable[[Path, Path], list]`,
    adapting a single-path reader so declaring one stays a one-liner.

**Why:** spec §3.2 requires Civ VI's build-queue reader to join
`City_BuildQueue.csv` against `AI_CityBuild.csv`, and a reader that reaches
for a sibling file behind `load_logs`'s back would report a header change in
the joined file as a fault against the wrong file.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ingest_load.py`:

```python
def test_a_reader_receives_the_logs_directory_so_it_can_join_across_files(tmp_path):
    """Civ VI's build queue has no owner column; ownership lives in a sibling
    file. The reader must be handed the directory, not just its own path."""
    from civ_advisor.games.base import GameProfile, LogReader

    (tmp_path / "Player_Stats.csv").write_text("Game Turn, Player\n1, 0\n")
    (tmp_path / "Sibling.csv").write_text("anything\n")
    seen = {}

    def reader(logs_dir, path):
        seen["logs_dir"] = logs_dir
        seen["path"] = path
        seen["sibling_visible"] = (logs_dir / "Sibling.csv").is_file()
        return []

    profile = GameProfile(
        id="joingame", display_name="Join Game", default_logs_dir=tmp_path,
        readers=(LogReader("Player_Stats.csv", "stats", reader),),
        knowledge_package="civ_advisor.knowledge",
    )
    load_logs(tmp_path, profile=profile)

    assert seen["logs_dir"] == tmp_path
    assert seen["path"] == tmp_path / "Player_Stats.csv"
    assert seen["sibling_visible"] is True
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_ingest_load.py -v -k join`
Expected: FAIL — `TypeError: reader() missing 1 required positional argument`.

- [ ] **Step 3: Widen the signature and add the adapter**

In `civ_advisor/games/base.py`:

```python
def simple(fn: Callable[[Path], list]) -> Callable[[Path, Path], list]:
    """Adapt a reader that needs only its own file to the two-argument form."""

    def read(logs_dir: Path, path: Path) -> list:
        return fn(path)

    return read
```

and change `LogReader.read`'s annotation to `Callable[[Path, Path], list]`.

- [ ] **Step 4: Call it with the directory**

In `civ_advisor/ingest/load.py`, change the call to
`rows = reader.read(logs_dir, path)`.

- [ ] **Step 5: Wrap civ7's readers**

In `civ_advisor/games/civ7/__init__.py`, import `simple` from `..base` and
wrap every one of the 21 reader functions: `LogReader("Player_Stats.csv",
"stats", simple(read_player_stats))`, and so on for all 21. Change nothing
else about the table — same files, same attrs, same order.

- [ ] **Step 6: Run the full suite**

```bash
uv run pytest -q 2>&1 | tail -3
```

Expected: **505 passed** (504 + 1), zero failures.

- [ ] **Step 7: Commit**

```bash
git add civ_advisor/games/base.py civ_advisor/games/civ7/__init__.py \
        civ_advisor/ingest/load.py tests/test_ingest_load.py
git commit -m "Hand readers the logs directory, not only their own file

Civ VI's build queue records no owner; ownership lives in a sibling file,
and a reader that reached for it privately would misattribute a header
change to the wrong file."
```

---

### Task 3: The civ6 profile skeleton and the five shared readers

**Files:**
- Create: `civ_advisor/games/civ6/__init__.py`
- Create: `tests/fixtures/logs_civ6/` (trimmed capture)
- Modify: `civ_advisor/games/__init__.py` (register civ6)
- Modify: `tests/conftest.py` (a `civ6_dir` fixture)
- Test: `tests/test_civ6_ingest.py` (new)

**Interfaces:**
- Produces: `civ_advisor.games.civ6.CIV6`, a registered `GameProfile`;
  `civ6_dir` pytest fixture.

- [ ] **Step 1: Install the fixture**

```bash
SRC="/private/tmp/claude-501/-Users-carlosbarbosa-Documents-GitHub-CIV-VII-Help/2c5c83ca-a788-43f0-b812-b0937b548bec/scratchpad/civ6-fixture-raw"
mkdir -p tests/fixtures/logs_civ6
cp "$SRC"/*.csv "$SRC"/*.log tests/fixtures/logs_civ6/
ls -la tests/fixtures/logs_civ6 | head -30
du -sh tests/fixtures/logs_civ6
```

If `$SRC` no longer exists, copy from the live Civ VI Logs directory named
in this plan's Fixture section instead. Then trim the two largest files to
keep the repo small — keep every row of every other file:

```bash
for f in AI_Research.csv AI_GovtPolicies.csv; do
  head -400 "tests/fixtures/logs_civ6/$f" > "tests/fixtures/logs_civ6/$f.tmp" && \
  mv "tests/fixtures/logs_civ6/$f.tmp" "tests/fixtures/logs_civ6/$f"
done
du -sh tests/fixtures/logs_civ6
```

Add a `tests/fixtures/logs_civ6/README.md` saying: captured 2026-09-12 from
a real Civ VI game at turn 53, Julius Caesar of Rome, 6 majors (players
0-5), 9 city-states (6-14), Free Cities at 62, Barbarians at 63;
`AI_Research.csv` and `AI_GovtPolicies.csv` truncated to 400 lines for size.

- [ ] **Step 2: Write the failing test**

Create `tests/test_civ6_ingest.py`:

```python
from civ_advisor.games.base import Capability
from civ_advisor.games.civ6 import CIV6
from civ_advisor.ingest.load import load_logs


def test_civ6_is_registered_by_importing_the_games_package():
    import civ_advisor.games  # noqa: F401
    from civ_advisor.games.registry import get_profile, profile_ids

    assert "civ6" in profile_ids()
    assert get_profile("civ6") is CIV6


def test_civ6_declares_only_what_its_logs_can_support():
    """Civ VI's AI_Victories holds era strategies, not victory paths (spec
    §3.2), and it logs no amenities, maintenance or deals."""
    assert not CIV6.supports(Capability.VICTORY_PATHS)
    assert not CIV6.supports(Capability.HAPPINESS)
    assert not CIV6.supports(Capability.MAINTENANCE)
    assert not CIV6.supports(Capability.PEACE_DEALS)
    assert not CIV6.supports(Capability.COMBAT_ODDS)
    assert CIV6.supports(Capability.FAITH)
    assert CIV6.supports(Capability.CIVICS)


def test_civ6_does_not_declare_ai_victories():
    """Declaring it would populate GameState.strategies with era postures the
    victory advisor would report as victory pursuit."""
    assert "AI_Victories.csv" not in CIV6.log_files


def test_the_shared_readers_parse_the_civ6_capture(civ6_dir):
    raw = load_logs(civ6_dir, profile=CIV6)
    for name in ("DiplomacySummary.csv", "AI_Tactical.csv", "AI_Operation.csv",
                 "AI_MayhemTracker.csv", "AI_UnitEfficiency.csv", "GameCore.log"):
        status = raw.files[name]
        assert status.ok, f"{name}: {status.error}"
        assert status.rows > 0, f"{name} parsed but is empty"


def test_civ6_identities_come_from_the_shared_gamecore_reader(civ6_dir):
    """Verified against the capture: 6 majors, human at 0, Free Cities at 62."""
    raw = load_logs(civ6_dir, profile=CIV6)
    by_player = {r.player: r for r in raw.player_identities}

    assert by_player[0].civilization == "CIVILIZATION_ROME"
    assert by_player[0].leader == "LEADER_JULIUS_CAESAR"
    assert by_player[0].slot_status == "Human"
    assert by_player[1].civilization == "CIVILIZATION_SCOTLAND"
    majors = [r for r in raw.player_identities
              if r.level == "CIVILIZATION_LEVEL_FULL_CIV"]
    assert len(majors) == 6
    assert by_player[62].level == "CIVILIZATION_LEVEL_FREE_CITIES"
```

Add to `tests/conftest.py`:

```python
FIXTURE_CIV6_DIR = Path(__file__).parent / "fixtures" / "logs_civ6"


@pytest.fixture(scope="session")
def civ6_dir() -> Path:
    if not FIXTURE_CIV6_DIR.is_dir():
        pytest.skip("civ6 fixture not installed")
    return FIXTURE_CIV6_DIR
```

- [ ] **Step 3: Run it to verify it fails**

Run: `uv run pytest tests/test_civ6_ingest.py -v`
Expected: collection error — `No module named 'civ_advisor.games.civ6'`.

- [ ] **Step 4: Write the civ6 profile**

Create `civ_advisor/games/civ6/__init__.py`:

```python
"""Civilization VI: where its logs live and how each one is read.

Civ VI writes its gameplay logs with no configuration: no mod, no FireTuner,
no AppOptions change. What it does NOT write is as important as what it does
-- see the profile's capability set and spec §3.5.
"""
from __future__ import annotations

from pathlib import Path

from civ_advisor.ingest.events import read_diplomacy_summary
from civ_advisor.ingest.tactical import (
    read_mayhem, read_operations, read_tactical, read_unit_efficiency,
)
from civ_advisor.ingest.textlogs import read_player_identities

from ..base import Capability, GameProfile, LogReader, simple
from ..registry import register

DEFAULT_LOGS_DIR = (
    Path.home()
    / "Library/Application Support/Sid Meier's Civilization VI"
    / "Firaxis Games/Sid Meier's Civilization VI/Logs"
)

READERS: tuple[LogReader, ...] = (
    # Shared with Civ VII, byte-identical headers (spec §3.1).
    LogReader("DiplomacySummary.csv", "diplomacy_summary", simple(read_diplomacy_summary)),
    LogReader("AI_Tactical.csv", "tactical", simple(read_tactical)),
    LogReader("AI_Operation.csv", "operations", simple(read_operations)),
    LogReader("AI_MayhemTracker.csv", "mayhem", simple(read_mayhem)),
    LogReader("AI_UnitEfficiency.csv", "unit_efficiency", simple(read_unit_efficiency)),
    LogReader("GameCore.log", "player_identities", simple(read_player_identities)),
    # Tasks 4 and 5 add the Civ VI variant readers here.
)

CIV6 = GameProfile(
    id="civ6",
    display_name="Civilization VI",
    default_logs_dir=DEFAULT_LOGS_DIR,
    readers=READERS,
    knowledge_package="civ_advisor.knowledge.civ6",
    # What Civ VI's logs cannot support, and therefore what this build must
    # not claim for it. AI_Victories exists but records era strategies, not
    # victory paths (spec §3.2); there is no amenities, maintenance, deal or
    # combat-odds log at all (spec §3.5).
    capabilities=frozenset({
        Capability.FAITH,
        Capability.CIVICS,
        Capability.TOURISM,
        Capability.DIPLOMATIC_FAVOR,
    }),
)

register(CIV6)
```

`knowledge_package` points at a package Task 8 creates; nothing loads it
until then.

- [ ] **Step 5: Register it**

In `civ_advisor/games/__init__.py`, add below the civ7 import:

```python
from . import civ6  # noqa: E402,F401
```

- [ ] **Step 6: Run the suite**

```bash
uv run pytest tests/test_civ6_ingest.py -v && uv run pytest -q 2>&1 | tail -3
```

Expected: 5 new tests pass; full suite **510 passed** (505 + 5).

- [ ] **Step 7: Commit**

```bash
git add civ_advisor/games/civ6 civ_advisor/games/__init__.py \
        tests/fixtures/logs_civ6 tests/conftest.py tests/test_civ6_ingest.py
git commit -m "Add a Civ VI profile carrying the readers it can share

Six of Civ VII's readers parse Civ VI's logs unchanged, identity among
them. The profile declares up front what Civ VI cannot support."
```

---

### Task 4: Civ VI variant readers — `Player_Stats`, `Player_Stats_2`, `UnitOperations`

**Files:**
- Create: `civ_advisor/games/civ6/columns.py`
- Create: `civ_advisor/games/civ6/readers.py`
- Modify: `civ_advisor/games/civ6/__init__.py` (declare them)
- Test: `tests/test_civ6_ingest.py`

**Interfaces:**
- Produces, in `civ_advisor.games.civ6.readers`:
  - `read_player_stats_civ6(logs_dir: Path, path: Path) -> list[StatsRow]`
  - `read_unit_operations_civ6(logs_dir: Path, path: Path) -> list[UnitOperationRow]`

**Measured facts this task depends on** (turn-53 capture, 2026-09-12):
`Player_Stats.csv` has exactly 20 header fields and every row has 20.
`Faith` appears at index 13 (balance) and index 17 (yield) — the reader must
be positional. `Player_Stats_2.csv` has 12 fields. `UnitOperations.log` in the committed
fixture has 396 rows of 5 fields and 3 rows of 2 fields at lines 2-4, the
latter reading `Unit operation handler <hex>, is disabled`. (Task 3 trimmed
this file to 400 lines; the untrimmed capture had 6533 data rows.)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_civ6_ingest.py`:

```python
def test_player_stats_reads_both_faith_columns_by_position(civ6_dir):
    """`Faith` is the header name at index 13 (balance) AND index 17 (yield).
    A name-keyed reader silently keeps one and drops the other."""
    from civ_advisor.games.civ6.readers import read_player_stats_civ6

    rows = read_player_stats_civ6(civ6_dir, civ6_dir / "Player_Stats.csv")
    rome = [r for r in rows if r.turn == 53 and r.player == 0]
    assert len(rome) == 1
    row = rome[0]
    assert row.cities == 2
    assert row.techs == 5
    assert row.civics == 5
    assert row.gold_balance == 98.0
    assert row.gold == 11.0
    assert row.production == 13.0
    assert row.food == 9.0
    assert row.faith_balance == 0.0
    assert row.faith == 0.0


def test_player_stats_leaves_civ7_only_fields_unavailable(civ6_dir):
    """Civ VI logs no towns, settlement cap, urban/rural split, amenities or
    diplomacy yield. These must be None, never 0."""
    from civ_advisor.games.civ6.readers import read_player_stats_civ6

    row = read_player_stats_civ6(civ6_dir, civ6_dir / "Player_Stats.csv")[0]
    assert row.towns is None
    assert row.settlement_cap is None
    assert row.urban_pop is None
    assert row.rural_pop is None
    assert row.happiness is None
    assert row.diplomacy is None


def test_unit_operations_skips_engine_diagnostics_but_not_real_rows(civ6_dir):
    """Civ VI interleaves 'Unit operation handler <hex>, is disabled' lines
    among the data -- at lines 2-4, before any data row.

    Counts are for the COMMITTED fixture, which Task 3 trimmed to 400 lines:
    396 data rows and 3 diagnostics, turns 1-7. (The untrimmed capture had
    6533 data rows through turn 52.) The trim deliberately kept the
    diagnostics, which are the whole point of this test."""
    from civ_advisor.games.civ6.readers import read_unit_operations_civ6

    rows = read_unit_operations_civ6(civ6_dir, civ6_dir / "UnitOperations.log")
    assert len(rows) == 396
    assert max(r.turn for r in rows) == 7


def test_unit_operations_still_raises_on_an_unrecognised_short_row(tmp_path):
    """Skipping every short row would turn a malformed log into quiet data
    loss. Only the known diagnostic shape may be skipped."""
    import pytest

    from civ_advisor.games.civ6.readers import read_unit_operations_civ6
    from civ_advisor.ingest.csvfile import LogFormatError

    path = tmp_path / "UnitOperations.log"
    path.write_text(
        "Game Turn, Mode, Player, Unit, Operation\n"
        "001, Adding, 0, UNIT_WARRIOR (1), UNITOPERATION_MOVE_TO (2)\n"
        "002, Adding\n"
    )
    with pytest.raises((LogFormatError, ValueError, IndexError)):
        read_unit_operations_civ6(tmp_path, path)
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_civ6_ingest.py -v -k "faith or unavailable or unit_operations"`
Expected: FAIL — `No module named 'civ_advisor.games.civ6.readers'`.

- [ ] **Step 3: Write the positional column map**

Create `civ_advisor/games/civ6/columns.py`:

```python
"""Pinned positional layout of Civ VI's Player_Stats.csv.

Addressed by position, not by header name, because `Faith` is the name of
BOTH column 13 (the treasury balance) and column 17 (the per-turn yield). A
dict keyed on the header keeps one and discards the other, and which one
survives depends on iteration order.

Verified 2026-09-12 against a turn-53 capture: header and every row carry
exactly 20 fields.
"""

PLAYER_STATS_COLUMN_COUNT = 20

# Column 1 is the civilization string, not a player id; see spec §5.
PLAYER_STATS_CIV_COLUMN = 1

PLAYER_STATS_INT_COLUMNS = {
    "turn": 0,
    "cities": 2,
    "techs": 4,
    "civics": 5,
    "land_units": 6,
    "corps": 7,
    "armies": 8,
    "naval_units": 9,
    "tiles_owned": 10,
    "tiles_improved": 11,
}

PLAYER_STATS_FLOAT_COLUMNS = {
    "gold_balance": 12,
    "faith_balance": 13,
    "science": 14,
    "culture": 15,
    "gold": 16,
    "faith": 17,
    "production": 18,
    "food": 19,
}
```

- [ ] **Step 4: Write the readers**

Create `civ_advisor/games/civ6/readers.py`:

```python
"""Readers for the Civ VI logs whose columns differ from Civ VII's.

Each maps into the SAME row dataclass Civ VII's reader produces, leaving
every field Civ VI cannot supply as None. See spec §3.2.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

log = logging.getLogger(__name__)

from civ_advisor.ingest.csvfile import LogFormatError, latest_game_segment, read_table
from civ_advisor.ingest.readers import StatsRow
from civ_advisor.ingest.tactical import UnitOperationRow, _unit
from civ_advisor.ingest.textlogs import read_player_identities

from .columns import (
    PLAYER_STATS_CIV_COLUMN,
    PLAYER_STATS_COLUMN_COUNT,
    PLAYER_STATS_FLOAT_COLUMNS,
    PLAYER_STATS_INT_COLUMNS,
)

IDENTITY_FILE = "GameCore.log"


def _player_by_civilization(logs_dir: Path) -> dict[str, int]:
    """civilization string -> player id, from GameCore.log (spec §5).

    A civilization fielded by two players maps to NEITHER: its rows cannot be
    attributed, and guessing one would misfile every observation about that
    rival. Missing or unreadable file returns {}, so rows go unattributed
    rather than wrongly attributed.
    """
    path = logs_dir / IDENTITY_FILE
    if not path.is_file():
        return {}
    try:
        identities = read_player_identities(path)
    except (LogFormatError, ValueError, IndexError, OSError):
        return {}
    counts: dict[str, int] = {}
    for row in identities:
        counts[row.civilization] = counts.get(row.civilization, 0) + 1
    return {r.civilization: r.player for r in identities if counts[r.civilization] == 1}


def read_player_stats_civ6(logs_dir: Path, path: Path) -> list[StatsRow]:
    players = _player_by_civilization(logs_dir)
    table = read_table(path)
    out: list[StatsRow] = []
    for row in latest_game_segment(table.rows, turn_col=0):
        if len(row) != PLAYER_STATS_COLUMN_COUNT:
            raise LogFormatError(
                f"{path.name}: expected {PLAYER_STATS_COLUMN_COUNT} columns but a row "
                f"has {len(row)} (row starts {row[:2]}). The game may have changed its "
                f"log format; update civ_advisor/games/civ6/columns.py."
            )
        values: dict = {name: int(row[i]) for name, i in PLAYER_STATS_INT_COLUMNS.items()}
        values |= {name: float(row[i]) for name, i in PLAYER_STATS_FLOAT_COLUMNS.items()}
        player = players.get(row[PLAYER_STATS_CIV_COLUMN])
        if player is None:
            # Unattributable: cannot be filed under a player at all. Dropped
            # rather than filed under player 0, which would put a rival's
            # figures on the player's own dashboard.
            log.warning("%s: no player for civilization %r; dropping its rows",
                        path.name, row[PLAYER_STATS_CIV_COLUMN])
            continue
        # Every Civ VII-only field is left at its None default, not zeroed.
        out.append(StatsRow(player=player, **values))
    return out


# Civ VI interleaves handler diagnostics among the data rows, e.g.
# "Unit operation handler a92585ad, is disabled". Only this exact shape is
# skipped; any other malformed row still raises, because silently dropping
# short rows would turn a broken log into quiet data loss.
_DIAGNOSTIC = re.compile(r"^Unit operation handler [0-9a-f]+$")


def read_unit_operations_civ6(logs_dir: Path, path: Path) -> list[UnitOperationRow]:
    table = read_table(path)
    out: list[UnitOperationRow] = []
    for row in table.rows:
        if len(row) == 2 and _DIAGNOSTIC.match(row[0]):
            continue
        if len(row) != 5:
            raise LogFormatError(
                f"{path.name}: expected 5 columns but a row has {len(row)}: {row!r}"
            )
        unit_type, unit_id = _unit(row[3])
        out.append(UnitOperationRow(int(row[0]), row[1], int(row[2]), unit_type, unit_id, row[4]))
    return out
```

If `_unit` is private in `civ_advisor/ingest/tactical.py`, import it anyway
rather than duplicating the parsing — two copies of the same
`UNIT_X (12345)` parser would drift. If it does not exist under that name,
find the helper `read_unit_operations` uses and import that.

- [ ] **Step 5: Declare the readers**

In `civ_advisor/games/civ6/__init__.py`, add to `READERS` (after the shared
block, replacing the "Tasks 4 and 5" comment):

```python
    LogReader("Player_Stats.csv", "stats", read_player_stats_civ6),
    LogReader("UnitOperations.log", "unit_operations", read_unit_operations_civ6),
```

**`Player_Stats_2.csv` is deliberately NOT declared here.** `CIV6` declares
TOURISM and DIPLOMATIC_FAVOR, which live in that file, and Task 8's
conformance test asserts a profile declaring them must read it. There is no
canonical `RawLogs` field for those yet, so wiring it now would mean
inventing one before anything consumes it. Task 8 closes this: either
`Player_Stats_2.csv` gains a reader and a canonical field, or those two
capabilities come off `CIV6` until one exists. Whichever Task 8 chooses, the
conformance test is what forces the choice rather than letting the
declaration and the readers drift apart silently.

importing both from `.readers`. Note these are NOT wrapped in `simple` —
they already take the two-argument form.

- [ ] **Step 6: Run the suite**

```bash
uv run pytest tests/test_civ6_ingest.py -v && uv run pytest -q 2>&1 | tail -3
```

Expected: full suite **514 passed** (510 + 4).

- [ ] **Step 7: Commit**

```bash
git add civ_advisor/games/civ6 tests/test_civ6_ingest.py
git commit -m "Read Civ VI's player stats and unit operations

Player_Stats is addressed positionally: Faith is the name of two different
columns. UnitOperations skips the engine's handler diagnostics by their
exact shape and still raises on anything else malformed."
```

---

### Task 5: Civ VI variant readers — the build queue's cross-file ownership join

**Files:**
- Modify: `civ_advisor/games/civ6/readers.py`
- Modify: `civ_advisor/games/civ6/__init__.py`
- Test: `tests/test_civ6_ingest.py`

**Interfaces:**
- Produces `read_build_queue_civ6(logs_dir: Path, path: Path) -> list[BuildQueueRow]`.

**Measured facts:** `City_BuildQueue.csv` has header
`Game Turn, City, Production Added, Current Item, Current Production, Production Needed, Overflow`
and no player column. `AI_CityBuild.csv` has `Game Turn, Player, City, ...`
and supplies ownership, but only for 202 of the 807 (turn, city) pairs —
25%. Every queue city is resolvable at some turn; none changed owner in the
capture. `AI_CityBuild`'s City column sometimes holds the sentinel
`PURCHASE` instead of a city name.

- [ ] **Step 1: Write the failing tests**

```python
def test_build_queue_attributes_cities_via_the_sibling_file(civ6_dir):
    """City_BuildQueue has no Player column; ownership comes from
    AI_CityBuild. Rome is the human's city in this capture."""
    from civ_advisor.games.civ6.readers import read_build_queue_civ6

    rows = read_build_queue_civ6(civ6_dir, civ6_dir / "City_BuildQueue.csv")
    rome = [r for r in rows if r.city == "LOC_CITY_NAME_ROME"]
    assert rome
    assert {r.player for r in rome} == {0}


def test_build_queue_carries_ownership_forward_rather_than_requiring_same_turn(civ6_dir):
    """AI_CityBuild logs only 25% of (turn, city) pairs. Requiring a same-turn
    match would discard three quarters of the queue."""
    from civ_advisor.games.civ6.readers import read_build_queue_civ6

    rows = read_build_queue_civ6(civ6_dir, civ6_dir / "City_BuildQueue.csv")
    attributed = [r for r in rows if r.player is not None and r.player >= 0]
    assert len(attributed) > len(rows) * 0.9


def test_build_queue_ignores_the_purchase_sentinel(civ6_dir):
    """AI_CityBuild's City column sometimes reads PURCHASE. Treating it as a
    city name would invent a city and attribute real queues to it."""
    from civ_advisor.games.civ6.readers import read_build_queue_civ6

    rows = read_build_queue_civ6(civ6_dir, civ6_dir / "City_BuildQueue.csv")
    assert all(r.city != "PURCHASE" for r in rows)


def test_a_queue_row_with_no_owner_anywhere_is_not_attributed_to_the_human(tmp_path):
    """Defaulting an unknown owner to player 0 would put a rival's production
    on the player's own Economy tab."""
    from civ_advisor.games.civ6.readers import read_build_queue_civ6

    (tmp_path / "City_BuildQueue.csv").write_text(
        "Game Turn, City, Production Added, Current Item, Current Production, "
        "Production Needed, Overflow\n"
        "5, LOC_CITY_NAME_NOWHERE, 6.0, UNIT_BUILDER, 6.0, 50, 0.0\n"
    )
    (tmp_path / "AI_CityBuild.csv").write_text(
        "Game Turn, Player, City, Food Adv., Prod. Adv., Construct, Order Source\n"
    )
    rows = read_build_queue_civ6(tmp_path, tmp_path / "City_BuildQueue.csv")
    assert len(rows) == 1
    assert rows[0].player is None
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_civ6_ingest.py -v -k build_queue`
Expected: FAIL — `cannot import name 'read_build_queue_civ6'`.

- [ ] **Step 3: Make `BuildQueueRow.player` optional**

In `civ_advisor/ingest/production.py`, change `BuildQueueRow.player` to
`int | None`. Civ VII always supplies it; Civ VI cannot always. Move it
after the fields without defaults if you give it one, or keep it required
and pass `None` explicitly — either is fine, but Civ VII's reader must keep
passing a real id.

- [ ] **Step 4: Write the reader**

Append to `civ_advisor/games/civ6/readers.py`:

```python
from civ_advisor.ingest.production import BuildQueueRow

OWNERSHIP_FILE = "AI_CityBuild.csv"
# AI_CityBuild's City column carries this instead of a city name on some rows.
PURCHASE_SENTINEL = "PURCHASE"


def _ownership_by_turn(logs_dir: Path) -> dict[str, list[tuple[int, int]]]:
    """city -> [(turn, player), ...] ascending, from AI_CityBuild.csv.

    Missing or unreadable: returns {}, so every queue row is reported
    unattributed rather than attributed wrongly.
    """
    path = logs_dir / OWNERSHIP_FILE
    if not path.is_file():
        return {}
    try:
        table = read_table(path)
    except (LogFormatError, ValueError, IndexError):
        return {}
    seen: dict[str, list[tuple[int, int]]] = {}
    for row in table.rows:
        if len(row) < 3:
            continue
        city = row[2].strip()
        if not city or city == PURCHASE_SENTINEL:
            continue
        try:
            turn, player = int(row[0]), int(row[1])
        except ValueError:
            continue
        seen.setdefault(city, []).append((turn, player))
    for entries in seen.values():
        entries.sort()
    return seen


def _owner_at(entries: list[tuple[int, int]], turn: int) -> int | None:
    """The most recent owner observed at or before `turn`.

    Carried forward rather than matched exactly: AI_CityBuild logs only about
    a quarter of (turn, city) pairs. Carrying forward is also what makes a
    capture read correctly -- ownership changes at the turn the file next
    reports a different player, and earlier rows keep the previous owner.
    """
    owner = None
    for entry_turn, player in entries:
        if entry_turn > turn:
            break
        owner = player
    return owner


def read_build_queue_civ6(logs_dir: Path, path: Path) -> list[BuildQueueRow]:
    ownership = _ownership_by_turn(logs_dir)
    table = read_table(path)
    out: list[BuildQueueRow] = []
    for row in latest_game_segment(table.rows, turn_col=0):
        if len(row) != 7:
            raise LogFormatError(
                f"{path.name}: expected 7 columns but a row has {len(row)}: {row!r}"
            )
        turn, city = int(row[0]), row[1]
        out.append(BuildQueueRow(
            turn=turn,
            player=_owner_at(ownership.get(city, []), turn),
            city=city,
            added=float(row[2]),
            item=row[3],
            current=float(row[4]),
            needed=float(row[5]),
            overflow=float(row[6]),
        ))
    return out
```

- [ ] **Step 5: Declare it**

Add to `civ_advisor/games/civ6/__init__.py`'s `READERS`:

```python
    LogReader("City_BuildQueue.csv", "build_queue", read_build_queue_civ6),
```

- [ ] **Step 6: Run the suite**

```bash
uv run pytest tests/test_civ6_ingest.py -v && uv run pytest -q 2>&1 | tail -3
```

Expected: full suite **518 passed** (514 + 4).

- [ ] **Step 7: Commit**

```bash
git add civ_advisor/games/civ6 civ_advisor/ingest/production.py tests/test_civ6_ingest.py
git commit -m "Attribute Civ VI's build queue from its sibling ownership log

City_BuildQueue records no owner. Ownership is carried forward from
AI_CityBuild, which logs only a quarter of the pairs; a row with no owner
anywhere stays unattributed rather than defaulting to the human."
```

---

### Task 6: Resolve Civ VI player ids and build the state

**Files:**
- Modify: `civ_advisor/state/build.py`
- Modify: `civ_advisor/games/civ6/__init__.py` (if a hook is needed)
- Test: `tests/test_civ6_state.py` (new)

**Interfaces:**
- Produces: `build_state(raw, profile)` resolving `UNRESOLVED_PLAYER` stats
  rows to real ids via the identity map, and classifying players by level.

**Measured facts:** identities give 17 players; majors (`FULL_CIV`) are
0-5 with the human at 0; city-states (`CITY_STATE`) are 6-14; Free Cities
(`FREE_CITIES`) is 62; Barbarians (`TRIBE`) is 63.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_civ6_state.py`:

```python
from civ_advisor.games.civ6 import CIV6
from civ_advisor.ingest.load import load_logs
from civ_advisor.state.build import build_state
from civ_advisor.state.models import PlayerKind


def _state(civ6_dir):
    return build_state(load_logs(civ6_dir, profile=CIV6), profile=CIV6)


def test_stats_rows_arrive_under_real_player_ids(civ6_dir):
    state = _state(civ6_dir)
    human = state.at(0, turn=53)
    assert human is not None
    assert human.cities == 2
    assert human.gold_balance == 98.0


def test_players_are_classified_by_their_logged_level_not_by_id_range(civ6_dir):
    state = _state(civ6_dir)
    assert state.players[0].kind is PlayerKind.HUMAN
    assert state.players[1].kind is PlayerKind.RIVAL
    assert state.players[6].kind is PlayerKind.INDEPENDENT   # city-state
    assert state.players[62].kind is PlayerKind.INDEPENDENT  # Free Cities
    assert len(state.rivals()) == 5


def test_rivals_are_named_from_their_leader(civ6_dir):
    state = _state(civ6_dir)
    assert state.players[1].name == "Robert The Bruce"


def test_no_victory_strategies_are_claimed_for_civ6(civ6_dir):
    """Civ VI's AI_Victories is not declared, so nothing may populate this."""
    state = _state(civ6_dir)
    assert state.strategies == {}


def test_unavailable_signals_are_none_not_zero(civ6_dir):
    state = _state(civ6_dir)
    human = state.at(0, turn=53)
    assert human.happiness is None
    assert human.total_maintenance is None
    assert human.net_gold is None
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_civ6_state.py -v`
Expected: FAIL — `build_state() got an unexpected keyword argument 'profile'`.

- [ ] **Step 3: Give `build_state` the profile and resolve ids**

In `civ_advisor/state/build.py`:

- Change the signature to `build_state(raw: RawLogs, profile: GameProfile | None = None) -> GameState`.
  The default keeps Civ VII's ~10 existing call sites working; do not remove it.
- **No id resolution is needed here.** Task 4's reader already emits real
  player ids, so `build_state` receives Civ VI stats rows in exactly the shape
  it receives Civ VII's. This task's work is classification only.
- Classify players from `PlayerIdentityRow.level` when identities exist:
  `CIVILIZATION_LEVEL_FULL_CIV` with `slot_status == "Human"` is
  `PlayerKind.HUMAN`, other `FULL_CIV` are `RIVAL`, `CITY_STATE` and
  `FREE_CITIES` are `INDEPENDENT`, and `TRIBE` (barbarians) is excluded from
  `state.players` entirely. Keep the existing Civ VII classification path
  intact for states built without identities.

Leave Civ VII's naming (`display_name`, `_identity_name`) as the source of
rival names; `LEADER_ROBERT_THE_BRUCE` title-cases to "Robert The Bruce"
through the existing fallback.

- [ ] **Step 4: Run the suite**

```bash
uv run pytest tests/test_civ6_state.py -v && uv run pytest -q 2>&1 | tail -3
```

Expected: full suite **523 passed** (518 + 5).

- [ ] **Step 5: Commit**

```bash
git add civ_advisor/state/build.py civ_advisor/games/civ6 tests/test_civ6_state.py
git commit -m "Resolve Civ VI player ids and classify by logged level

Civ VI keys its stats by civilization; identities supply the map. A
civilization fielded by two players resolves to neither, and an
unresolvable row is dropped rather than filed under the human."
```

---

### Task 7: Advisors must report unavailable, not zero

**Files:**
- Modify: `civ_advisor/advisors/*.py` as the tests require
- Modify: `civ_advisor/api/serialize.py` (surface capabilities)
- Test: `tests/test_civ6_advisors.py` (new)

**Interfaces:**
- Produces: every advisor runs against a Civ VI state without raising, and
  a capability the profile does not declare surfaces as unavailable.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_civ6_advisors.py`:

```python
from civ_advisor.advisors import run_all
from civ_advisor.games.base import Capability
from civ_advisor.games.civ6 import CIV6
from civ_advisor.ingest.load import load_logs
from civ_advisor.state.build import build_state


def test_every_advisor_runs_against_a_civ6_state_without_raising(civ6_dir):
    """The point of the canonical state: advisors are game-agnostic."""
    state = build_state(load_logs(civ6_dir, profile=CIV6), profile=CIV6)
    insights = run_all(state)
    assert isinstance(insights, list)


def test_no_insight_asserts_a_signal_civ6_cannot_supply(civ6_dir):
    """An advisor that reads happiness or maintenance from a Civ VI state
    would be reporting a number the game never logged."""
    state = build_state(load_logs(civ6_dir, profile=CIV6), profile=CIV6)
    text = " ".join(
        f"{getattr(i, 'title', '')} {getattr(i, 'detail', '')}" for i in run_all(state)
    ).lower()
    for banned in ("happiness", "amenit", "maintenance", "celebration"):
        assert banned not in text, f"a Civ VI insight mentions {banned!r}"


def test_the_api_reports_which_capabilities_are_unavailable(civ6_dir):
    from civ_advisor.api.serialize import capability_report

    report = capability_report(CIV6)
    assert report[Capability.VICTORY_PATHS.value] is False
    assert report[Capability.HAPPINESS.value] is False
    assert report[Capability.FAITH.value] is True
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_civ6_advisors.py -v`
Expected: FAIL — advisors raising `TypeError` on `None` arithmetic, and
`cannot import name 'capability_report'`.

- [ ] **Step 3: Add the capability report**

In `civ_advisor/api/serialize.py`, add to the imports:

```python
from civ_advisor.games.base import Capability, GameProfile
```

then add:

```python
def capability_report(profile: GameProfile) -> dict[str, bool]:
    """Every capability this build models, and whether this game supports it.

    Exhaustive on purpose: the UI must be able to say "this game does not
    support X" rather than simply omitting X, which would be indistinguishable
    from X being quiet.
    """
    return {c.value: profile.supports(c) for c in Capability}
```

- [ ] **Step 4: Make each advisor `None`-safe**

Run the failing test, and for each advisor that raises or emits an insight
about an unavailable signal, guard it. The rule: an advisor that needs a
value which is `None` emits NOTHING for that check — it must not emit an
insight saying the value is zero, low, or unknown. Whether the capability is
absent is the profile's business to report, not each advisor's.

Do not change any threshold, wording or ordering that Civ VII's tests pin.
If making an advisor `None`-safe would change Civ VII output, stop and
report BLOCKED.

- [ ] **Step 5: Run the suite**

```bash
uv run pytest -q 2>&1 | tail -3
```

Expected: **526 passed** (523 + 3), zero failures. Every pre-existing Civ VII
test must still pass unmodified.

- [ ] **Step 6: Commit**

```bash
git add civ_advisor/advisors civ_advisor/api/serialize.py tests/test_civ6_advisors.py
git commit -m "Keep advisors silent about signals a game cannot supply

An advisor whose input is unavailable emits nothing; whether a capability
exists at all is the profile's to report, not each advisor's to guess."
```

---

### Task 8: Civ VI guides package, conformance tests, and the capability matrix

**Files:**
- Create: `civ_advisor/knowledge/civ6/__init__.py`, `civ_advisor/knowledge/civ6/guides.json`
- Modify: `civ_advisor/knowledge/catalog.py` (unpin the civ7 check)
- Modify: `docs/architecture/log-capability-matrix.md`
- Test: `tests/test_profile_conformance.py` (new)

- [ ] **Step 1: Write the conformance tests**

Create `tests/test_profile_conformance.py`:

```python
import dataclasses

import pytest

from civ_advisor.games import profile_ids
from civ_advisor.games.registry import get_profile
from civ_advisor.ingest.load import RawLogs

PROFILES = [get_profile(i) for i in profile_ids()]


@pytest.mark.parametrize("profile", PROFILES, ids=lambda p: p.id)
def test_every_reader_targets_a_real_rawlogs_field(profile):
    known = {f.name for f in dataclasses.fields(RawLogs)}
    assert {r.attr for r in profile.readers} <= known


@pytest.mark.parametrize("profile", PROFILES, ids=lambda p: p.id)
def test_no_profile_declares_a_file_twice(profile):
    assert len(set(profile.log_files)) == len(profile.log_files)


@pytest.mark.parametrize("profile", PROFILES, ids=lambda p: p.id)
def test_every_profile_has_a_loadable_guide_catalog(profile):
    from civ_advisor.knowledge.catalog import load_catalog

    catalog = load_catalog(package=profile.knowledge_package)
    assert {e.game for e in catalog.entries} <= {profile.id}


@pytest.mark.parametrize("profile", PROFILES, ids=lambda p: p.id)
def test_every_declared_capability_is_backed_by_a_declared_reader(profile):
    """Stops the capability declaration and the reader table drifting apart:
    a profile claiming FAITH with no reader that can produce it would promise
    a panel it cannot fill."""
    from civ_advisor.games.base import Capability

    if profile.supports(Capability.VICTORY_PATHS):
        assert "AI_Victories.csv" in profile.log_files
    if profile.supports(Capability.MAINTENANCE):
        assert "Player_Treasury.csv" in profile.log_files
    if profile.supports(Capability.HAPPINESS):
        assert "Player_Happiness.csv" in profile.log_files
    if profile.supports(Capability.PEACE_DEALS):
        assert "DiplomacyDeals.log" in profile.log_files
    # The other direction, which is the one that actually bites: a capability
    # declared with no reader able to produce it promises a panel that cannot
    # be filled. Civ VI declares FAITH/CIVICS from Player_Stats and
    # TOURISM/DIPLOMATIC_FAVOR from Player_Stats_2.
    stats_backed = {Capability.FAITH, Capability.CIVICS}
    stats2_backed = {Capability.TOURISM, Capability.DIPLOMATIC_FAVOR}
    if stats_backed & set(profile.capabilities):
        assert "Player_Stats.csv" in profile.log_files
    if stats2_backed & set(profile.capabilities):
        assert "Player_Stats_2.csv" in profile.log_files
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_profile_conformance.py -v`
Expected: FAIL for civ6 — `ModuleNotFoundError: civ_advisor.knowledge.civ6`.

- [ ] **Step 3: Create the Civ VI guides package**

```bash
mkdir -p civ_advisor/knowledge/civ6
```

`civ_advisor/knowledge/civ6/__init__.py`:

```python
"""Reviewed guides for Civilization VI. Data only; see ../catalog.py."""
```

`civ_advisor/knowledge/civ6/guides.json` — an empty but valid catalog. Copy
the `schema_version`, `catalog_revision`, `note` and `review_statuses` keys
from `civ_advisor/knowledge/civ7/guides.json`, set `"entries": []`, and set
the note to say no Civ VI guide has been reviewed yet, so no Civ VI
recommendation may carry a how-to. An empty reviewed catalog is honest; a
copy of Civ VII's would attach Civ VII navigation to Civ VI screens.

- [ ] **Step 4: Unpin the catalog's game check**

In `civ_advisor/knowledge/catalog.py`, `load_catalog` gains
`game: str | None = None` as its THIRD parameter (after `raw` and `package`,
so existing positional callers are unaffected), and the check at line ~160
becomes: reject an entry whose `game` differs from the expected one, where
the expected one is `game` if given, else `"civ7"` for backward
compatibility. Also make `ALLOWED_HOSTS`'s civ7 markers apply only when the
expected game is civ7; a civ6 catalog with no entries exercises none of it,
so keep this change minimal and do not invent civ6 host markers now.

Then pass it through: `load_catalog(package=profile.knowledge_package, game=profile.id)`
wherever a profile is available.

- [ ] **Step 5: Give the capability matrix a Civ VI column**

In `docs/architecture/log-capability-matrix.md`, replace the "Game:
Civilization VII" header note added in phase 1 with a short section stating
what Civ VI can and cannot support, drawn from `CIV6.capabilities`:
unavailable are victory paths, amenities/happiness, maintenance and net
gold, peace deals, combat odds, settlement cap and the urban/rural split;
available and new are faith, civics, tourism and diplomatic favor. Say for
each unavailable one WHY — which log does not exist, or which log exists but
records a different concept (AI_Victories).

- [ ] **Step 6: Run the full suite**

```bash
uv run pytest -q 2>&1 | tail -3
```

Expected: **534 passed** (526 + 8 parametrized conformance tests), zero
failures.

- [ ] **Step 7: Commit**

```bash
git add civ_advisor/knowledge docs/architecture/log-capability-matrix.md \
        tests/test_profile_conformance.py
git commit -m "Hold each profile to what it declares

A conformance test per game checks its readers, its catalog and that a
declared capability has a reader behind it. Civ VI ships an empty reviewed
catalog: no Civ VI guide has been reviewed, and Civ VII's navigation does
not describe Civ VI's screens."
```

---

## Done when

- `uv run pytest` is green at **534**, with every pre-existing Civ VII test
  unmodified.
- `uv run civ-advisor --game civ6` starts and serves a dashboard built from
  the real Civ VI log directory.
- No advisor emits an insight mentioning happiness, amenities, maintenance
  or a victory path for a Civ VI game.
- `CIV6.capabilities` and the reader table agree, enforced by the
  conformance test rather than by review.
