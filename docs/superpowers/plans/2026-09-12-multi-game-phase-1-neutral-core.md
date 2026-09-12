# Multi-Game Advisor — Phase 1: Neutral Core — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename the package to `civ_advisor` and put every Civilization
VII-specific detail behind a `GameProfile`, so that phase 2 can add a
Civilization VI profile without touching the advisor layer.

**Architecture:** A `GameProfile` value object names a game and carries the
one thing phase 1 moves behind it — the table of log files and the reader
for each. `ingest.load_logs`, `Store`, `create_app` and the guide catalog
gain a `profile` parameter. Downstream of `build_state` nothing changes.
The registry lives in `civ_advisor/games/`; each game gets a subpackage.

**Tech Stack:** Python 3.12, dataclasses, `importlib.resources`, pytest,
FastAPI/uvicorn. No new dependencies.

**Deliberately not in this phase:** spec §4 describes `GameProfile` as also
carrying a capability declaration and an identity strategy. Both exist to
serve a second game, and neither has a consumer until one exists, so phase 1
leaves them off rather than shipping unused fields whose shape would be
guesswork. Phase 2 adds them alongside the code that reads them.

**Spec:** `docs/superpowers/specs/2026-09-12-multi-game-advisor-design.md`
(this plan implements §11 phase 1; see §4 for the target architecture).

## Global Constraints

- **Zero behaviour change.** The 36 existing test files are the acceptance
  criterion for this phase. A task that requires editing an existing
  assertion about advisor output has gone out of scope — stop and say so.
- **Read-only with respect to both games' directories.** Nothing in this
  phase writes anywhere except the existing archive root.
- Python `>=3.12`. No new runtime dependencies.
- `filterwarnings = ["error", ...]` is set in `pyproject.toml`; a new
  `DeprecationWarning` fails the suite. This is deliberate.
- `profile` is a **keyword argument defaulting to the `civ7` profile**
  throughout phase 1. This is what keeps the ~40 existing call sites
  unchanged. Phase 2 removes the default once a second game exists, so
  callers must choose. Do not remove it in this phase.
- The package rename is `civ7_advisor` → `civ_advisor`. The **console
  script `civ7-advisor` is retained as an alias** alongside the new
  `civ-advisor`; the README's commands must keep working.
- `DEFAULT_ARCHIVE_ROOT` stays `~/.civ7-advisor/archive` in this phase.
  Renaming it would orphan the user's existing archives; spec §8 handles
  namespacing in phase 2.

---

### Task 1: Rename the package to `civ_advisor`

Pure mechanical rename. There is no new test: **the existing suite is the
test**, and it must pass unchanged both before and after.

**Files:**
- Rename: `civ7_advisor/` → `civ_advisor/` (all 20 modules beneath it)
- Modify: every `.py` file containing `civ7_advisor` (63 files: 20 under
  the package, 36 test files, 2 scripts, plus `tests/browser/conftest.py`)
- Modify: `pyproject.toml` (project name, script entry points, wheel
  packages)
- Modify: `README.md` (the one `civ7_advisor/knowledge/guides.json` path)

**Interfaces:**
- Consumes: nothing.
- Produces: the module path `civ_advisor.*` for every later task. Console
  entry points `civ-advisor` and `civ7-advisor`, both
  `civ_advisor.cli:main`.

- [ ] **Step 1: Record the green baseline**

```bash
uv run pytest -q 2>&1 | tail -3
```

Expected: all tests pass. Write the exact pass count down — Task 1 Step 6
compares against it. If the suite is red before you start, stop and report
that; do not rename on top of a broken suite.

- [ ] **Step 2: Rename the directory, preserving history**

```bash
git mv civ7_advisor civ_advisor
```

- [ ] **Step 3: Rewrite every module reference**

`civ7_advisor` is never a substring of another identifier in this repo, so
a plain literal replacement is safe. Do **not** let this touch the string
`civ7-advisor` (hyphen) — that is the console script and the archive
directory, and both keep their names.

```bash
grep -rl 'civ7_advisor' --include='*.py' . | grep -v '\.venv' \
  | xargs sed -i '' 's/civ7_advisor/civ_advisor/g'
sed -i '' 's/civ7_advisor/civ_advisor/g' README.md
grep -rn 'civ7_advisor' --include='*.py' --include='*.md' . | grep -v '\.venv'
```

Expected from the final `grep`: no output.

- [ ] **Step 4: Update `pyproject.toml`**

Replace the `[project.scripts]` and `[tool.hatch.build.targets.wheel]`
blocks, and the project name:

```toml
[project]
name = "civ-advisor"
version = "0.1.0"
description = "Second-screen turn advisor for Civilization VI and VII, driven by the games' own log files"

[project.scripts]
civ-advisor = "civ_advisor.cli:main"
# Retained so existing commands and the README keep working.
civ7-advisor = "civ_advisor.cli:main"

[tool.hatch.build.targets.wheel]
packages = ["civ_advisor"]
```

- [ ] **Step 5: Update the package docstring**

In `civ_advisor/__init__.py`, replace the first line:

```python
"""Second-screen turn advisor for Civilization VI and VII, driven by the games' own log files."""
```

- [ ] **Step 6: Re-sync and run the full suite**

```bash
uv sync
uv run pytest -q 2>&1 | tail -3
```

Expected: the **same pass count** as Step 1, zero failures. A different
count means a test file was missed by the rename.

- [ ] **Step 7: Verify the console scripts both resolve**

```bash
uv run civ-advisor --help | head -3
uv run civ7-advisor --help | head -3
```

Expected: both print the same usage line. Neither starts a server
(`--help` exits first).

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "Rename civ7_advisor to civ_advisor

The package is about to serve two games. No behaviour changes; the
civ7-advisor console script is retained as an alias."
```

---

### Task 2: `GameProfile`, `LogReader`, and the registry

**Files:**
- Create: `civ_advisor/games/__init__.py`
- Create: `civ_advisor/games/base.py`
- Create: `civ_advisor/games/registry.py`
- Test: `tests/test_games.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `civ_advisor.games.base.LogReader(filename: str, attr: str, read: Callable[[Path], list])`, a frozen dataclass.
  - `civ_advisor.games.base.GameProfile(id: str, display_name: str, default_logs_dir: Path, readers: tuple[LogReader, ...], knowledge_package: str)`, a frozen dataclass with a `log_files: tuple[str, ...]` property.
  - `civ_advisor.games.registry.UnknownGame(KeyError)`.
  - `civ_advisor.games.registry.register(profile: GameProfile) -> None`.
  - `civ_advisor.games.registry.get_profile(game_id: str) -> GameProfile`.
  - `civ_advisor.games.registry.profile_ids() -> tuple[str, ...]`, sorted.

**Why three modules rather than one:** `civ_advisor/games/civ7/` (Task 3)
must import `GameProfile` to build itself, while
`civ_advisor/games/__init__.py` must import `civ7` to register it. Putting
the dataclasses in `base.py` and the registry in `registry.py` — neither
of which imports any game — breaks that cycle.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_games.py`:

```python
from pathlib import Path

import pytest

from civ_advisor.games.base import GameProfile, LogReader
from civ_advisor.games.registry import UnknownGame, get_profile, profile_ids, register


def _reader(name: str) -> LogReader:
    return LogReader(filename=name, attr="stats", read=lambda path: [])


def test_log_files_lists_every_declared_reader_in_order():
    profile = GameProfile(
        id="testgame", display_name="Test Game", default_logs_dir=Path("/tmp/logs"),
        readers=(_reader("B.csv"), _reader("A.csv")),
        knowledge_package="civ_advisor.knowledge",
    )
    assert profile.log_files == ("B.csv", "A.csv")


def test_profiles_are_frozen():
    profile = GameProfile(
        id="testgame", display_name="Test Game", default_logs_dir=Path("/tmp/logs"),
        readers=(), knowledge_package="civ_advisor.knowledge",
    )
    with pytest.raises(AttributeError):
        profile.id = "other"


def test_register_then_get_round_trips():
    profile = GameProfile(
        id="registerme", display_name="Register Me", default_logs_dir=Path("/tmp/logs"),
        readers=(), knowledge_package="civ_advisor.knowledge",
    )
    register(profile)
    assert get_profile("registerme") is profile
    assert "registerme" in profile_ids()


def test_registering_the_same_id_twice_is_refused():
    """A second registration would silently shadow the first, and which one won
    would depend on import order."""
    profile = GameProfile(
        id="dupe", display_name="Dupe", default_logs_dir=Path("/tmp/logs"),
        readers=(), knowledge_package="civ_advisor.knowledge",
    )
    register(profile)
    with pytest.raises(ValueError, match="dupe"):
        register(profile)


def test_unknown_game_names_the_games_that_do_exist():
    """The error is what a user sees after a typo in --game, so it must list the
    valid ids rather than only repeating the bad one."""
    register(GameProfile(
        id="listed", display_name="Listed", default_logs_dir=Path("/tmp/logs"),
        readers=(), knowledge_package="civ_advisor.knowledge",
    ))
    with pytest.raises(UnknownGame) as exc:
        get_profile("civ5")
    assert "civ5" in str(exc.value)
    assert "listed" in str(exc.value)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_games.py -v`
Expected: collection error, `ModuleNotFoundError: No module named 'civ_advisor.games'`.

- [ ] **Step 3: Write `civ_advisor/games/base.py`**

```python
"""What distinguishes one game from another. Imports no game: see games/__init__.py."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class LogReader:
    """One log file and the function that turns it into typed rows.

    `attr` is the RawLogs field the rows are stored on, so two games can feed the
    same canonical field from differently-named files.
    """

    filename: str
    attr: str
    read: Callable[[Path], list]


@dataclass(frozen=True)
class GameProfile:
    """Everything about a game that the rest of the advisor must not hard-code."""

    id: str                             # "civ6" | "civ7"; matches --game and the archive path
    display_name: str                   # "Civilization VII"
    default_logs_dir: Path
    readers: tuple[LogReader, ...]
    knowledge_package: str              # importable package holding this game's guides.json

    @property
    def log_files(self) -> tuple[str, ...]:
        """Declared file names, in reader order. This is what the poller watches, so a
        file this game never writes is simply never declared and never reported."""
        return tuple(r.filename for r in self.readers)
```

- [ ] **Step 4: Write `civ_advisor/games/registry.py`**

```python
"""The set of games this build can advise on."""
from __future__ import annotations

from .base import GameProfile


class UnknownGame(KeyError):
    """Asked for a game this build does not have a profile for."""

    def __str__(self) -> str:  # KeyError's repr would quote the message
        return self.args[0]


_PROFILES: dict[str, GameProfile] = {}


def register(profile: GameProfile) -> None:
    """Add a profile. Refuses a duplicate id: a silent overwrite would make the
    active profile depend on import order."""
    if profile.id in _PROFILES:
        raise ValueError(f"a profile for {profile.id!r} is already registered")
    _PROFILES[profile.id] = profile


def get_profile(game_id: str) -> GameProfile:
    if game_id not in _PROFILES:
        known = ", ".join(sorted(_PROFILES)) or "none"
        raise UnknownGame(f"unknown game {game_id!r}; this build knows: {known}")
    return _PROFILES[game_id]


def profile_ids() -> tuple[str, ...]:
    return tuple(sorted(_PROFILES))
```

- [ ] **Step 5: Write `civ_advisor/games/__init__.py`**

Importing `civ_advisor.games` must be enough to make every game available.
The game imports go at the **bottom**, after the re-exports, because
`games.civ7` imports `games.base`.

```python
"""Per-game profiles. Importing this package registers every game this build supports."""
from __future__ import annotations

from .base import GameProfile, LogReader
from .registry import UnknownGame, get_profile, profile_ids, register

__all__ = [
    "GameProfile", "LogReader", "UnknownGame", "get_profile", "profile_ids", "register",
]

# Task 3 appends the line that imports and registers civ7 here, at the bottom:
# each game package imports .base, so importing one from the top of this module
# would be circular.
```

Note that this file deliberately does **not** import `civ7` yet. Python
imports a parent package before its submodules, so
`from civ_advisor.games.base import ...` executes this `__init__` first —
a `from . import civ7` line here before Task 3 creates that package would
fail the whole test module, not just one test.

- [ ] **Step 6: Run the tests**

```bash
uv run pytest tests/test_games.py -v
```

Expected: 5 passed.

- [ ] **Step 7: Commit**

```bash
git add civ_advisor/games tests/test_games.py
git commit -m "Add GameProfile and the game registry

A duplicate id is refused rather than overwritten: which profile won would
otherwise depend on import order."
```

---

### Task 3: The `civ7` profile owns the reader table; `load_logs` takes a profile

**Files:**
- Create: `civ_advisor/games/civ7/__init__.py`
- Modify: `civ_advisor/ingest/load.py` (delete the `READERS` / `LOG_FILES`
  constants at lines 84–107; add the `profile` parameter to `load_logs`)
- Test: `tests/test_games.py` (the two tests left red in Task 2),
  `tests/test_ingest_load.py` (one new test)

**Interfaces:**
- Consumes: `GameProfile`, `LogReader`, `register` from Task 2.
- Produces:
  - `civ_advisor.games.civ7.CIV7`, a `GameProfile` with `id="civ7"` and 21 readers.
  - `civ_advisor.ingest.load.load_logs(logs_dir: Path, profile: GameProfile = CIV7) -> RawLogs`.
  - `civ_advisor.ingest.load.LOG_FILES` is **removed**; callers use `profile.log_files`.

**Import direction, which is load-bearing:** `games/civ7/` imports the
reader functions from `civ_advisor.ingest.readers`, `.events`,
`.production`, `.textlogs` and `.tactical`. `civ_advisor/ingest/__init__.py`
imports nothing, so this does not pull in `ingest.load`, and
`ingest/load.py` may therefore import `games.civ7` for its default. Do not
add imports to `civ_advisor/ingest/__init__.py`; that would create a cycle.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ingest_load.py`:

```python
def test_load_logs_reads_only_the_files_the_profile_declares(tmp_path, fixture_dir):
    """A profile that declares one file must not read, or report on, the other
    twenty sitting next to it. This is what lets Civ VI declare a different set."""
    from civ_advisor.games.base import GameProfile, LogReader
    from civ_advisor.ingest.readers import read_player_stats

    only_stats = GameProfile(
        id="civ7-statsonly", display_name="Stats Only", default_logs_dir=tmp_path,
        readers=(LogReader("Player_Stats.csv", "stats", read_player_stats),),
        knowledge_package="civ_advisor.knowledge",
    )
    raw = load_logs(fixture_dir, profile=only_stats)

    assert list(raw.files) == ["Player_Stats.csv"]
    assert raw.stats
    assert raw.combat == []
```

And append to `tests/test_games.py`, adding this import at the **top** of the
file so that importing the package — and therefore registering every game —
happens once, at collection:

```python
import civ_advisor.games  # noqa: F401  (imported for its registration side effect)
```

```python
def test_importing_the_games_package_registers_civ7():
    """Importing civ_advisor.games must be enough; nothing should have to import
    the civ7 subpackage by hand."""
    assert "civ7" in profile_ids()


def test_civ7_profile_declares_every_reader_the_advisor_had():
    from civ_advisor.games.civ7 import CIV7

    assert CIV7.id == "civ7"
    assert CIV7.display_name == "Civilization VII"
    assert CIV7.default_logs_dir.name == "Logs"
    assert len(CIV7.readers) == 21
    assert "Player_Stats.csv" in CIV7.log_files
    assert "GameCore.log" in CIV7.log_files


def test_civ7_declares_no_file_twice():
    """Two readers on one file would double-count its rows."""
    from civ_advisor.games.civ7 import CIV7

    assert len(set(CIV7.log_files)) == len(CIV7.log_files)


def test_every_civ7_reader_targets_a_real_rawlogs_field():
    """A typo in `attr` would silently drop a whole log: setattr would create a new
    attribute that nothing reads."""
    from dataclasses import fields

    from civ_advisor.games.civ7 import CIV7
    from civ_advisor.ingest.load import RawLogs

    known = {f.name for f in fields(RawLogs)}
    assert {r.attr for r in CIV7.readers} <= known
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_games.py tests/test_ingest_load.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'civ_advisor.games.civ7'`.

- [ ] **Step 3: Write `civ_advisor/games/civ7/__init__.py`**

This is the table currently at `civ_advisor/ingest/load.py:84–107`, moved
verbatim and wrapped in `LogReader`s. The order is unchanged.

```python
"""Civilization VII: where its logs live and how each one is read."""
from __future__ import annotations

from pathlib import Path

from civ_advisor.ingest.events import read_combat_log, read_diplomacy_summary, read_gossip
from civ_advisor.ingest.production import read_build_queue
from civ_advisor.ingest.readers import (
    read_diplomacy, read_happiness, read_historian, read_player_stats, read_targets,
    read_treasury, read_victories,
)
from civ_advisor.ingest.tactical import (
    read_combat_planning, read_commander_promotions, read_mayhem, read_operation_evals,
    read_operations, read_tactical, read_unit_efficiency, read_unit_operations,
)
from civ_advisor.ingest.textlogs import read_deals, read_player_identities

from ..base import GameProfile, LogReader
from ..registry import register

DEFAULT_LOGS_DIR = Path.home() / "Library/Application Support/Civilization VII/Logs"

READERS: tuple[LogReader, ...] = (
    LogReader("Player_Stats.csv", "stats", read_player_stats),
    LogReader("Player_Treasury.csv", "treasury", read_treasury),
    LogReader("Player_Happiness.csv", "happiness", read_happiness),
    LogReader("AI_Victories.csv", "victories", read_victories),
    LogReader("AI_DiplomaticActions.csv", "diplomacy", read_diplomacy),
    LogReader("AI_Targets.csv", "targets", read_targets),
    LogReader("Historian.csv", "historian", read_historian),
    LogReader("CityBuildQueue.csv", "build_queue", read_build_queue),
    LogReader("CombatLog.csv", "combat", read_combat_log),
    LogReader("Game_Gossip.csv", "gossip", read_gossip),
    LogReader("DiplomacySummary.csv", "diplomacy_summary", read_diplomacy_summary),
    LogReader("DiplomacyDeals.log", "deals", read_deals),
    LogReader("UnitOperations.log", "unit_operations", read_unit_operations),
    LogReader("AI_Tactical.csv", "tactical", read_tactical),
    LogReader("AI_Operation.csv", "operations", read_operations),
    LogReader("AI_CombatPlanning.csv", "combat_orders", read_combat_planning),
    LogReader("AI_Operation_Eval.csv", "operation_evals", read_operation_evals),
    LogReader("AI_UnitEfficiency.csv", "unit_efficiency", read_unit_efficiency),
    LogReader("AI_MayhemTracker.csv", "mayhem", read_mayhem),
    LogReader("AI_Commander_Promotions.csv", "commander_promotions", read_commander_promotions),
    LogReader("GameCore.log", "player_identities", read_player_identities),
)

CIV7 = GameProfile(
    id="civ7",
    display_name="Civilization VII",
    default_logs_dir=DEFAULT_LOGS_DIR,
    readers=READERS,
    knowledge_package="civ_advisor.knowledge",
)

register(CIV7)
```

`knowledge_package` points at the current location; Task 5 moves it to
`civ_advisor.knowledge.civ7`.

Then add the registration import to the **bottom** of
`civ_advisor/games/__init__.py`, below the `__all__` block:

```python
# Imported for the side effect of registering. Must come last: each game package
# imports .base, so importing one from the top of this module would be circular.
from . import civ7  # noqa: E402,F401
```

- [ ] **Step 4: Rewrite `load_logs` in `civ_advisor/ingest/load.py`**

Delete the `READERS` list and the `LOG_FILES` constant (lines 84–107), and
delete the now-unused reader imports at the top of the file — `RawLogs`
still needs the **row types**, so keep every `from .readers import
DiplomacyRow, ...` name and drop only the `read_*` functions. Replace
`load_logs` with:

```python
def load_logs(logs_dir: Path, profile: GameProfile = CIV7) -> RawLogs:
    """Read every log `profile` declares. A file that fails to parse is dropped for
    this load (its FileStatus says why) while every other file still contributes.

    A file the profile does not declare is not read and not reported: absent by
    design is not the same as missing, and only the profile knows which is which.
    """
    raw = RawLogs()
    for reader in profile.readers:
        path = logs_dir / reader.filename
        try:
            rows = reader.read(path)
        except OSError as exc:
            error = "file not found" if isinstance(exc, FileNotFoundError) else str(exc)
            raw.files[reader.filename] = FileStatus(reader.filename, False, 0, None, error)
            continue
        except (LogFormatError, ValueError, IndexError) as exc:
            log.warning("%s: dropping file for this rebuild: %s", reader.filename, exc)
            raw.files[reader.filename] = FileStatus(reader.filename, False, 0, None, str(exc))
            continue
        setattr(raw, reader.attr, rows)
        raw.files[reader.filename] = FileStatus(
            reader.filename, True, len(rows), max((r.turn for r in rows), default=None)
        )
    return raw
```

Add at the top of the file, after the existing `from .csvfile import LogFormatError`:

```python
from civ_advisor.games.base import GameProfile
from civ_advisor.games.civ7 import CIV7
```

- [ ] **Step 5: Point the two `LOG_FILES` consumers at the profile**

In `civ_advisor/api/app.py`, replace the import on line 26:

```python
from civ_advisor.games.civ7 import CIV7
```

and inside `create_app`, replace `LOG_FILES` at lines 85 and 96 with
`CIV7.log_files`. Task 4 replaces `CIV7` here with the passed-in profile;
this step only keeps the module importable.

- [ ] **Step 6: Run the full suite**

```bash
uv run pytest -q 2>&1 | tail -3
```

Expected: the Task 1 Step 1 pass count (486), **plus 10** — 5 from Task 2,
4 more in `test_games.py`, and 1 in `test_ingest_load.py`. Zero failures.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "Move Civ VII's log table into a game profile

load_logs now reads what the profile declares rather than a module
constant, so a file one game never writes is absent by design rather than
reported as missing."
```

---

### Task 4: Thread the profile through `Store`, `create_app`, and `--game`

**Files:**
- Modify: `civ_advisor/store.py:156-200` (constructor, `rebuild`)
- Modify: `civ_advisor/api/app.py:54-96` (`create_app` signature, poller)
- Modify: `civ_advisor/cli.py` (`--game`, default logs dir from the profile)
- Modify: `README.md` (the Options paragraph)
- Test: `tests/test_cli.py`, `tests/test_store.py` (new tests appended)

**Interfaces:**
- Consumes: `GameProfile`, `get_profile`, `profile_ids`, `UnknownGame`,
  `CIV7` from Tasks 2–3.
- Produces:
  - `Store(logs_dir, archive_root=None, *, profile: GameProfile = CIV7, ...)` — `profile` is keyword-only so the existing positional `archive_root` calls in `tests/test_store.py` keep working.
  - `create_app(logs_dir, poll_interval=1.0, archive_root=None, *, profile: GameProfile = CIV7, ...)`.
  - `civ-advisor --game <id>`, defaulting to `civ7`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_store.py`:

```python
def test_store_watches_and_reads_only_the_profile_s_files(fixture_dir, tmp_path):
    """The profile reaches the reader table, not just the constructor."""
    from civ_advisor.games.base import GameProfile, LogReader
    from civ_advisor.ingest.readers import read_player_stats
    from civ_advisor.store import Store

    only_stats = GameProfile(
        id="store-statsonly", display_name="Stats Only", default_logs_dir=tmp_path,
        readers=(LogReader("Player_Stats.csv", "stats", read_player_stats),),
        knowledge_package="civ_advisor.knowledge",
    )
    snapshot = Store(fixture_dir, profile=only_stats).rebuild()

    assert list(snapshot.state.files) == ["Player_Stats.csv"]
```

Append to `tests/test_cli.py`:

```python
def test_game_flag_selects_the_profile_and_its_default_logs_dir(monkeypatch, capsys):
    """--game picks both the readers and where to look, so a user who names the
    game does not also have to know the path."""
    import civ_advisor.cli as cli

    seen = {}

    def fake_create_app(logs_dir, poll_interval, **kwargs):
        seen["logs_dir"] = logs_dir
        seen["profile"] = kwargs["profile"]
        return object()

    monkeypatch.setattr(cli, "create_app", fake_create_app)
    monkeypatch.setattr(cli.uvicorn, "run", lambda *a, **k: None)
    # The profile's real default_logs_dir only exists if the game is installed, and
    # the test is about which path is chosen, not whether it is present. main() makes
    # exactly one is_dir() call before create_app, and monkeypatch undoes this after.
    monkeypatch.setattr(Path, "is_dir", lambda self: True)

    assert cli.main(["--game", "civ7", "--no-llm", "--no-context-file"]) == 0
    assert seen["profile"].id == "civ7"
    assert seen["logs_dir"] == seen["profile"].default_logs_dir


def test_unknown_game_is_refused_with_the_known_ids(capsys):
    """A typo must not fall back to a default and silently advise on the wrong game."""
    import civ_advisor.cli as cli

    assert cli.main(["--game", "civ5"]) == 2
    assert "civ7" in capsys.readouterr().err
```

`tests/test_cli.py` already imports `Path`; confirm before relying on it.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_store.py tests/test_cli.py -v`
Expected: FAIL — `Store() got an unexpected keyword argument 'profile'`, and
`unrecognized arguments: --game`.

- [ ] **Step 3: Add the profile to `Store`**

In `civ_advisor/store.py`, add the import:

```python
from civ_advisor.games.base import GameProfile
from civ_advisor.games.civ7 import CIV7
```

Replace the constructor signature at lines 155-157 with this — `profile` is
keyword-only so that the existing positional `Store(logs, archive_root=root)`
calls in `tests/test_store.py` are untouched:

```python
    def __init__(self, logs_dir: Path, archive_root: Path | None = None,
                 commentary_worker: CommentaryWorker | None = None,
                 identity_provider: Callable[[Snapshot], dict] | None = None,
                 *, profile: GameProfile = CIV7) -> None:
```

Then add one line to the body, directly below `self.logs_dir = logs_dir`
(line 164):

```python
        self.profile = profile
```

Change nothing else in the body. At line 193, pass it through:

```python
        raw = load_logs(self.logs_dir, self.profile)
```

- [ ] **Step 4: Add the profile to `create_app`**

In `civ_advisor/api/app.py`, replace the signature at lines 54-56 with:

```python
def create_app(logs_dir: Path, poll_interval: float = 1.0, archive_root: Path | None = None,
               commentary_worker: CommentaryWorker | None = None,
               player_store: PersistentContextStore | None = None,
               *, profile: GameProfile = CIV7) -> FastAPI:
```

Add `profile=profile` to the `Store(...)` call at line 79, and replace the
two `CIV7.log_files` uses from Task 3 Step 5 with `profile.log_files`:

```python
        initial = poll_snapshot(logs_dir, profile.log_files)
        ...
        task = asyncio.create_task(watch(logs_dir, profile.log_files, on_change, poll_interval, initial))
```

`watch` and `snapshot` take an `Iterable[str]`, so a tuple is fine; no
change is needed in `civ_advisor/ingest/poller.py`.

- [ ] **Step 5: Add `--game` to the CLI**

In `civ_advisor/cli.py`, the logs directory now defaults to the **chosen
profile's** directory, which cannot be known until the arguments are parsed
— so `--logs-dir`'s `default` becomes `None` and is filled in afterwards.

`tests/test_cli.py::test_default_logs_dir_is_the_macos_civ_vii_logs_folder`
asserts on the module constant `cli.DEFAULT_LOGS_DIR`. That test must not be
edited, so **keep the constant**, sourced from the profile rather than
spelled out a second time:

```python
from civ_advisor.games.civ7 import CIV7
from civ_advisor.games.registry import UnknownGame, get_profile, profile_ids

DEFAULT_LOGS_DIR = CIV7.default_logs_dir  # retained: the path Civ VII users know
```

```python
    parser.add_argument("--game", default="civ7",
                        help=f"which game to advise on: {', '.join(profile_ids())} (default: civ7)")
    parser.add_argument("--logs-dir", type=Path, default=None,
                        help="log directory to read (default: the chosen game's own)")
```

After `args = parser.parse_args(argv)`:

```python
    try:
        profile = get_profile(args.game)
    except UnknownGame as exc:
        print(str(exc), file=sys.stderr)
        return 2
    logs_dir = args.logs_dir or profile.default_logs_dir

    if not logs_dir.is_dir():
        print(
            f"{profile.display_name} log directory not found: {logs_dir}\n"
            f"Start the game once so it creates the folder, or pass --logs-dir <path>.",
            file=sys.stderr,
        )
        return 2
```

Replace the remaining uses of `args.logs_dir` in `main` with `logs_dir`,
pass `profile=profile` to `create_app`, and change the startup banner:

```python
    print(f"{profile.display_name} Advisor -> http://{args.host}:{args.port}  "
          f"(reading {logs_dir}; {where}; {llm}; {notes})")
```

- [ ] **Step 6: Run the full suite**

```bash
uv run pytest -q 2>&1 | tail -3
```

Expected: Task 3's count **plus 3**, zero failures.

- [ ] **Step 7: Update the README's Options paragraph**

In `README.md`, replace the `Options:` sentence with:

```markdown
Options: `--game civ7` (the only game this build advises on so far),
`--logs-dir PATH` (if your logs live elsewhere), `--port`, `--host`,
`--poll-interval`, `--llm-model MODEL`, `--llm-timeout SECONDS`, `--no-llm`,
`--context-file PATH`, and `--no-context-file`.
```

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "Select the game profile from --game

The logs directory now defaults to the chosen game's own, so naming the
game is enough. An unknown --game is refused rather than falling back to a
default and advising on the wrong game."
```

---

### Task 5: Split the guide catalog per game

**Files:**
- Create: `civ_advisor/knowledge/civ7/__init__.py`
- Rename: `civ_advisor/knowledge/guides.json` → `civ_advisor/knowledge/civ7/guides.json`
- Modify: `civ_advisor/knowledge/catalog.py:195-205` (`load_catalog`)
- Modify: `civ_advisor/games/civ7/__init__.py` (`knowledge_package`)
- Modify: `scripts/check_guides.py` (`--game`)
- Modify: `README.md` (the `guides.json` path)
- Test: `tests/test_guide_catalog.py` (one new test)

**Interfaces:**
- Consumes: `CIV7.knowledge_package` from Task 3.
- Produces: `load_catalog(raw: str | None = None, package: str = "civ_advisor.knowledge.civ7") -> Catalog`. The `raw` parameter stays first and positional, so the ~12 existing `load_catalog(json.dumps(...))` call sites are untouched.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_guide_catalog.py`:

```python
def test_catalog_is_loaded_from_the_package_the_profile_names():
    """The guides a game gets must follow from its profile, not from a constant,
    or a second game would silently be handed Civ VII's catalog."""
    from civ_advisor.games.civ7 import CIV7

    catalog = load_catalog(package=CIV7.knowledge_package)

    assert catalog.entries
    assert {e.game for e in catalog.entries} == {"civ7"}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_guide_catalog.py -v -k package`
Expected: FAIL — `load_catalog() got an unexpected keyword argument 'package'`.

- [ ] **Step 3: Move the catalog into a per-game package**

```bash
mkdir -p civ_advisor/knowledge/civ7
git mv civ_advisor/knowledge/guides.json civ_advisor/knowledge/civ7/guides.json
```

Create `civ_advisor/knowledge/civ7/__init__.py`:

```python
"""Reviewed guides for Civilization VII. Data only; see ../catalog.py for the loader."""
```

- [ ] **Step 4: Give `load_catalog` a package parameter**

In `civ_advisor/knowledge/catalog.py`, add the default beside
`CATALOG_FILE` near line 25:

```python
CATALOG_FILE = "guides.json"
DEFAULT_CATALOG_PACKAGE = "civ_advisor.knowledge.civ7"
```

and change `load_catalog` at line 195:

```python
def load_catalog(raw: str | None = None, package: str = DEFAULT_CATALOG_PACKAGE) -> Catalog:
    if raw is None:
        raw = resources.files(package).joinpath(CATALOG_FILE).read_text(encoding="utf-8")
```

Leave the rest of the function untouched, including the `row["game"] !=
"civ7"` check at line 159 — that check is per-entry data validation and
phase 2 replaces it with a per-profile one. Do not generalise it now.

- [ ] **Step 5: Point the civ7 profile at its own package**

In `civ_advisor/games/civ7/__init__.py`, change:

```python
    knowledge_package="civ_advisor.knowledge.civ7",
```

- [ ] **Step 6: Add `--game` to the link auditor**

In `scripts/check_guides.py`, add the argument to its parser and pass the
profile's package through:

```python
    parser.add_argument("--game", default="civ7", help="which game's catalog to audit")
```

and replace line 86:

```python
    catalog = load_catalog(package=get_profile(args.game).knowledge_package)
```

with `from civ_advisor.games.registry import get_profile` added to the
imports at line 29.

- [ ] **Step 7: Confirm the packaged data still ships**

`[tool.hatch.build.targets.wheel] packages = ["civ_advisor"]` includes
subpackage data already, but the move is exactly the kind of thing that
breaks an installed wheel while passing in a source checkout. Verify:

```bash
uv run python -c "
from importlib import resources
print(len(resources.files('civ_advisor.knowledge.civ7').joinpath('guides.json').read_text()))
"
```

Expected: a positive byte count, no `FileNotFoundError`.

- [ ] **Step 8: Update the README's guides path**

In `README.md`, change `civ_advisor/knowledge/guides.json` to
`civ_advisor/knowledge/civ7/guides.json`, and change the audit command to:

```markdown
    uv run python scripts/check_guides.py --game civ7
```

- [ ] **Step 9: Run the full suite**

```bash
uv run pytest -q 2>&1 | tail -3
```

Expected: Task 4's count **plus 1**, zero failures.

- [ ] **Step 10: Commit**

```bash
git add -A
git commit -m "Give each game its own guide catalog

The catalog a game gets now follows from its profile, so phase 2 can add
Civ VI's guides without touching the loader."
```

---

### Task 6: Record what phase 1 established

**Files:**
- Modify: `docs/architecture/log-capability-matrix.md`
- Modify: `docs/superpowers/specs/2026-09-12-multi-game-advisor-design.md` (status line)

**Interfaces:**
- Consumes: everything above.
- Produces: nothing consumed by later tasks.

- [ ] **Step 1: Head the capability matrix with its scope**

`docs/architecture/log-capability-matrix.md` currently describes Civ VII
implicitly. Phase 2 adds a Civ VI column, so the document must first say
which game it is about. Add immediately below its title:

```markdown
**Game:** Civilization VII. Civilization VI has a different log set and a
different set of things it cannot know; see
[the multi-game design](../superpowers/specs/2026-09-12-multi-game-advisor-design.md)
§3, and this document gains a Civ VI column in phase 2.
```

- [ ] **Step 2: Mark phase 1 done in the spec**

Change the spec's status line to:

```markdown
**Status:** Phase 1 (neutral core) implemented on `feature/multi-game-advisor`; phases 2–4 not yet planned
```

- [ ] **Step 3: Confirm the whole suite is green one last time**

```bash
uv run pytest -q 2>&1 | tail -3
```

Expected: zero failures. Compare the pass count against Task 1 Step 1:
it must be **higher by exactly 14** — 5 from Task 2, 6 from Task 3, 3 from
Task 4, 1 from Task 5 — and no pre-existing test may have been deleted or
had an assertion changed.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "Record phase 1 of the multi-game work as landed"
```

---

## Done when

- `uv run pytest` is green, with every pre-existing test unmodified.
- `uv run civ-advisor --game civ7` and `uv run civ7-advisor` both start and
  serve the dashboard exactly as before.
- `grep -rn civ7_advisor --include='*.py' .` returns nothing.
- No file under `civ_advisor/advisors/` or `civ_advisor/decisions/` was
  modified by this phase. If one was, the seam is in the wrong place —
  stop and report it before continuing to phase 2.
