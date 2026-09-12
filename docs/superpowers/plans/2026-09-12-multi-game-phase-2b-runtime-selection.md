# Multi-Game Advisor — Phase 2b: Runtime Selection and Per-Game Storage — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the game a **runtime property** rather than a startup constant. The
advisor detects which game is being played from the games' own declared logs,
the player can override that from the header, a game switch is a new sitting
that carries nothing across, storage is namespaced per game, and a game's
absent capabilities say *why* they are absent instead of silently vanishing.

**Architecture:** Two new modules under `civ_advisor/games/` — `detect.py`
(stat the declared gameplay logs of every registered profile; answer which game
is freshest, or that it cannot tell) and `selection.py` (a `GameSelector` that
combines a session pin with detection and reports which won and whether they
disagree). `Store` gains an **idle** state and a `switch_to()` that increments
the epoch, so one long-lived `Store` spans every switch while nothing computed
under the previous game survives one. `create_app` grows a supervisor task
alongside the existing file-change watcher: the supervisor re-resolves the
selection every poll, and on a change it swaps the store, restarts the watcher,
and publishes a `game_changed` event. The archive root and the player-context
store move under `~/.civ-advisor/<game>/`, and every context entry records the
game it was made in so an acknowledgement cannot cross the boundary even when
the player points both games at one file. The dashboard header gains a game
control (Auto plus every registered game) and renders the capability matrix, so
a panel a game cannot fill states the reason.

**Tech Stack:** Python 3.12, dataclasses, `StrEnum`, asyncio, pytest,
FastAPI/uvicorn, vanilla JS. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-12-multi-game-advisor-design.md` —
this plan implements §8 and §8.1, with the §11 phase-2b obligations
(`--logs-dir` implies explicit `--game`; `profile` required at three layers).

## Global Constraints

- **TDD.** Failing test first, minimal implementation, verify, commit. Every
  step contains real code. A step that says "add appropriate handling" is a
  defect in this plan — stop and report it.
- **Civ VII's behaviour does not change except where this plan says it does.**
  There are exactly three deliberate changes, each justified where it occurs:
  1. `--logs-dir` now requires `--game` (spec §8, §11). Task 1.
  2. `--game` defaults to `auto` rather than `civ7`. Task 6.
  3. The default archive root and context path move under `~/.civ-advisor/civ7/`.
     Nothing is moved or deleted on the user's disk; Task 5 says exactly what
     happens to existing data.
- **No pre-existing assertion may be edited** unless this plan names the test
  and argues the change. Adding an argument to a call is not editing an
  assertion. Two tests have assertions edited by this plan, both named:
  `tests/test_civ6_advisors.py::test_the_api_reports_which_capabilities_are_unavailable`
  (Task 8) and nothing else. `tests/test_cli.py::test_missing_logs_dir_exits_2_with_a_helpful_message`
  is discussed at length in Task 1 and its assertions are **kept**.
- **Read-only with respect to both games' directories.** Detection stats files;
  it never opens or writes them.
- Python `>=3.12`. No new runtime dependencies. `filterwarnings = ["error", ...]`
  is set: a new `DeprecationWarning` fails the suite.
- The browser suite under `tests/browser/` is opt-in (`addopts =
  "--ignore=tests/browser"`). Task 9 adds one browser test; it runs with
  `uv sync --group browser && uv run playwright install chromium && uv run
  pytest tests/browser -p playwright.pytest_plugin` and is **not** part of the
  green-suite count any other step compares against.
- **Terminology hazard.** The archive path is already
  `<root>/<game_key>/<session>/` where `game_key` means *the save's seeds*.
  "Game" in this plan means the **title** (Civ VI / Civ VII). The new layout is
  `~/.civ-advisor/<title>/archive/<save-key>/<session>/`. Do not collapse the
  two.


## Three adjudicated decisions

Raised by the plan's author and settled before execution.

**1. `civ-advisor` defaults to `auto`; `civ7-advisor` defaults to `civ7`.
Approved, with that split.** The author's argument is right — once two
games are registered, a `civ7` default makes detection invisible and puts a
Civ VI player in front of an empty dashboard, which is the opposite of what
runtime selection is for. The objection is also right: it changes what a
bare invocation does for someone who has only ever advised on Civ VII.

Both are satisfied by using the entry point that already exists. Phase 1
retained `civ7-advisor` as an alias of `civ-advisor`; make that alias
default to `--game civ7` and the new `civ-advisor` name default to
`--game auto`. Anyone whose muscle memory or notes say `civ7-advisor` gets
exactly what they got before, and nobody has to be told about a change they
did not ask for. `--game` still overrides either.

The header must then say which game is in force and whether it was
detected or pinned, every time. A default that picks for you is only
acceptable while it is loud about having picked.

**2. `test_missing_logs_dir_exits_2_with_a_helpful_message` keeps its
assertions. Approved — the author was right to push back.** I had asked
for the assertion to change. It should not: that test is about the
missing-directory message, which this phase does not alter. Only its argv
gains `--game civ7`, and the new "`--logs-dir` requires `--game`" refusal
gets its own sibling test. Editing the original would have weakened a check
to make room for a new behaviour, when the two are simply different cases.

**3. `Store(logs_dir=None, profile=None)` as an idle state. Approved.**
Spec §11 says make `profile` required; this is required-but-nullable, so a
forgotten argument still raises `TypeError` while `None` remains a
meaningful value. That is the correct reading rather than a looser one:
§8.1 makes "I cannot tell which game is being played" a first-class answer,
and a type that cannot represent it would force a provisional profile at
cold start — which is exactly the guess this project refuses to make.

---

### Task 1: `--logs-dir` requires `--game`, and `profile` becomes required

Spec §11 makes both binding for this phase. They land together because both are
about the same failure: running one game's readers against the other's
directory and producing silently empty advice instead of an error.

**Files:**
- Modify: `civ_advisor/cli.py` (the coupling check)
- Modify: `civ_advisor/ingest/load.py`, `civ_advisor/store.py`,
  `civ_advisor/api/app.py` (drop the `= CIV7` defaults)
- Modify: every call site that relied on the default — 9 `load_logs`, 15
  `Store`, ~25 `create_app` (listed in Step 4)
- Test: `tests/test_cli.py`, `tests/test_ingest_load.py`

**Interfaces:**
- Consumes: `GameProfile`, `get_profile`, `CIV7`, `CIV6` from phases 1 and 2a.
- Produces:
  - `load_logs(logs_dir: Path, profile: GameProfile) -> RawLogs` — `profile` positional-or-keyword, **no default**.
  - `Store(logs_dir, archive_root=None, ..., *, profile: GameProfile | None)` — keyword-only, **no default**, and nullable from Task 4 onwards. In this task it is required and non-None.
  - `create_app(logs_dir, poll_interval=1.0, ..., *, profile: GameProfile)` — keyword-only, no default.

**On the pre-existing test.** `tests/test_cli.py::test_missing_logs_dir_exits_2_with_a_helpful_message`
calls `cli.main(["--logs-dir", str(tmp_path / "nope")])` and asserts the exit
code is 2 and that the message contains `"not found"`, `"--logs-dir"` and the
path. Under the new rule that invocation would exit 2 for a *different* reason
and print a *different* message, so every one of those assertions would become
a coincidence.

**Its assertions do not change.** What changes is its argv: it gains
`"--game", "civ7"`. That is legitimate rather than convenient because the test
is about *what the advisor says when a named log directory is missing*, and it
still tests exactly that — the directory is still named, still missing, and the
message is still the one under test. Naming the game is now part of naming a
directory, so the test naming a directory must name a game. Editing the
assertion instead would have weakened a check on a message that is not changing.
The new refusal gets its **own** test (Step 1), so both behaviours stay pinned.

Two other tests pass `--logs-dir` without `--game`
(`test_server_is_started_with_parsed_options`, `test_archive_flags_reach_create_app`).
Both gain `"--game", "civ7"` in argv; neither has an assertion touched.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli.py`:

```python
def test_logs_dir_without_game_is_refused(tmp_path, capsys):
    """A logs directory belongs to one game, and the advisor cannot tell which from the
    path. Guessing would run Civ VII's readers over a Civ VI directory: every file would
    report "file not found" and the player would get empty advice instead of an error."""
    rc = cli.main(["--logs-dir", str(tmp_path)])
    err = capsys.readouterr().err
    assert rc == 2
    assert "--logs-dir" in err and "--game" in err
    assert "civ6" in err and "civ7" in err       # name the choices, do not just refuse


def test_logs_dir_with_an_explicit_game_is_accepted(fixture_dir, monkeypatch):
    monkeypatch.setattr(cli.uvicorn, "run", lambda *a, **k: None)
    assert cli.main(["--logs-dir", str(fixture_dir), "--game", "civ7", "--no-archive",
                     "--no-llm", "--no-context-file"]) == 0
```

Append to `tests/test_ingest_load.py`:

```python
def test_load_logs_requires_a_profile(fixture_dir):
    """Phase 1's default existed so one game's call sites need not change. With two games
    registered a forgotten argument silently advises on the wrong one, so it must raise."""
    with pytest.raises(TypeError):
        load_logs(fixture_dir)
```

`tests/test_ingest_load.py` must import `pytest`; add it if absent.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_cli.py tests/test_ingest_load.py -q 2>&1 | tail -5
```

Expected: `test_logs_dir_without_game_is_refused` fails (rc 0 or a different
message), `test_load_logs_requires_a_profile` fails (no `TypeError` raised).

- [ ] **Step 3: Couple the two flags in `civ_advisor/cli.py`**

`--game`'s `default="civ7"` becomes `default=None` so the CLI can tell "the
user chose civ7" from "the user chose nothing". (Task 6 replaces the `None`
branch with `auto`; until then `None` means `civ7`, preserving today's
behaviour.) Directly after `args = parser.parse_args(argv)`:

```python
    if args.logs_dir is not None and args.game is None:
        print(
            "--logs-dir needs --game: a log directory belongs to one game and the path "
            "does not say which.\n"
            f"Pass one of: {', '.join(profile_ids())}.",
            file=sys.stderr,
        )
        return 2
    game = args.game or "civ7"
    try:
        profile = get_profile(game)
    except UnknownGame as exc:
        print(str(exc), file=sys.stderr)
        return 2
```

and change the argument declaration to:

```python
    parser.add_argument("--game", default=None,
                        help=f"which game to advise on: {', '.join(profile_ids())} "
                             "(default: civ7; required with --logs-dir)")
```

- [ ] **Step 4: Remove the three `= CIV7` defaults and fix every call site**

`civ_advisor/ingest/load.py`:

```python
def load_logs(logs_dir: Path, profile: GameProfile) -> RawLogs:
```

and delete the now-unused `from civ_advisor.games.civ7 import CIV7` import.

`civ_advisor/store.py`: change `*, profile: GameProfile = CIV7` to
`*, profile: GameProfile`, and delete the `CIV7` import.

`civ_advisor/api/app.py`: change `*, profile: GameProfile = CIV7` to
`*, profile: GameProfile`, and delete the `CIV7` import.

Then fix the call sites. Each is choosing Civ VII explicitly, which is the
point of the change:

```bash
# 1. load_logs(x) -> load_logs(x, profile=CIV7), skipping calls that already pass one.
grep -rn 'load_logs(' --include='*.py' tests scripts | grep -v profile
# 2. Store(...) and create_app(...) with no profile= keyword.
grep -rn 'Store(' --include='*.py' tests | grep -v 'ContextStore' | grep -v profile
grep -rn 'create_app(' --include='*.py' tests | grep -v profile
```

Edit each by hand or with a reviewed `sed`; do **not** blanket-replace, because
`ContextStore(` and `PersistentContextStore(` also match `Store(`. Every edited
file needs `from civ_advisor.games.civ7 import CIV7` at the top. The affected
files are `tests/conftest.py`, `tests/test_fixture_v2.py`,
`tests/test_ingest_load.py`, `tests/test_store.py`, `tests/test_api.py`,
`tests/browser/conftest.py` and `scripts/calibrate_advisor.py`.

`scripts/calibrate_advisor.py` reads archived Civ VII logs, so it passes
`profile=CIV7`; a per-game calibration is phase 3's problem, not this one.

- [ ] **Step 5: Add `--game civ7` to the three CLI tests that pass `--logs-dir`**

In `tests/test_cli.py`, insert `"--game", "civ7",` into the argv lists of
`test_missing_logs_dir_exits_2_with_a_helpful_message`,
`test_server_is_started_with_parsed_options` and
`test_archive_flags_reach_create_app`. Change nothing else in those tests — in
particular, no `assert` line in any of them may be modified.

- [ ] **Step 6: Run the full suite**

```bash
uv run pytest -q 2>&1 | tail -3
```

Expected: 537 + 3 = 540 passed, zero failures. A `TypeError: load_logs()
missing 1 required positional argument` in any test means a call site was
missed in Step 4.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "Require an explicit game wherever one could be guessed wrong

--logs-dir now needs --game, and profile is required by load_logs, Store and
create_app. A forgotten profile used to mean Civ VII's readers over a Civ VI
directory: empty advice rather than an error."
```

---

### Task 2: Detect the game from its own declared logs

**Files:**
- Create: `civ_advisor/games/detect.py`
- Test: `tests/test_detect.py`

**Interfaces:**
- Consumes: `GameProfile` (`log_files`, `default_logs_dir`), `registry.profile_ids`/`get_profile`.
- Produces:
  - `civ_advisor.games.detect.RECENCY_WINDOW_S: float = 600.0`
  - `Candidate(game_id: str, logs_dir: Path, present: bool, newest: float | None, age: float | None)`, frozen.
  - `Detection(game_id: str | None, reason: str, candidates: tuple[Candidate, ...], at: float)`, frozen.
  - Reason constants `DETECTED`, `NO_LOGS_DIR`, `ALL_STALE`, `AMBIGUOUS`.
  - `newest_declared_log(logs_dir: Path, profile: GameProfile) -> float | None`
  - `detect(profiles: Iterable[GameProfile], *, logs_dirs: Mapping[str, Path] | None = None, now: float | None = None, window: float = RECENCY_WINDOW_S) -> Detection`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_detect.py`:

```python
import os
import time
from pathlib import Path

from civ_advisor.games.base import GameProfile, LogReader, simple
from civ_advisor.games.detect import (
    ALL_STALE, AMBIGUOUS, DETECTED, NO_LOGS_DIR, detect, newest_declared_log,
)


def _profile(game_id: str, logs_dir: Path, *files: str) -> GameProfile:
    return GameProfile(
        id=game_id, display_name=game_id.upper(), default_logs_dir=logs_dir,
        readers=tuple(LogReader(f, "stats", simple(lambda p: [])) for f in files),
        knowledge_package="civ_advisor.knowledge.civ7",
    )


def _write(path: Path, age_s: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x")
    when = time.time() - age_s
    os.utime(path, (when, when))


def test_the_freshest_declared_log_decides(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    _write(a / "Player_Stats.csv", 300)
    _write(b / "Player_Stats.csv", 10)
    found = detect([_profile("ga", a, "Player_Stats.csv"), _profile("gb", b, "Player_Stats.csv")])
    assert (found.game_id, found.reason) == ("gb", DETECTED)


def test_an_undeclared_file_cannot_make_a_game_look_live(tmp_path):
    """Both engines rewrite noise logs at launch. Only declared gameplay logs count, or
    starting Civ VI at the menu would drag the dashboard away from a live Civ VII game."""
    a, b = tmp_path / "a", tmp_path / "b"
    _write(a / "Player_Stats.csv", 300)
    _write(b / "Player_Stats.csv", 3000)
    _write(b / "VFXSystem.log", 1)          # not declared by gb
    found = detect([_profile("ga", a, "Player_Stats.csv"), _profile("gb", b, "Player_Stats.csv")])
    assert found.game_id == "ga"


def test_a_game_whose_logs_directory_is_absent_is_not_a_candidate(tmp_path):
    a = tmp_path / "a"
    _write(a / "Player_Stats.csv", 5)
    found = detect([_profile("ga", a, "Player_Stats.csv"),
                    _profile("gb", tmp_path / "missing", "Player_Stats.csv")])
    assert found.game_id == "ga"
    absent = next(c for c in found.candidates if c.game_id == "gb")
    assert absent.present is False and absent.newest is None


def test_no_candidate_at_all_says_so_rather_than_naming_one(tmp_path):
    found = detect([_profile("ga", tmp_path / "x", "Player_Stats.csv")])
    assert found.game_id is None and found.reason == NO_LOGS_DIR


def test_nothing_recent_is_cannot_tell_not_least_stale(tmp_path):
    """The point of the window. Two games last played on different days are not a
    question about which is running now; naming one would attach the whole dashboard to
    a game nobody is playing."""
    a, b = tmp_path / "a", tmp_path / "b"
    _write(a / "Player_Stats.csv", 86400)
    _write(b / "Player_Stats.csv", 7200)
    found = detect([_profile("ga", a, "Player_Stats.csv"), _profile("gb", b, "Player_Stats.csv")],
                   window=600)
    assert found.game_id is None and found.reason == ALL_STALE
    assert {c.game_id for c in found.candidates} == {"ga", "gb"}   # still reported, with ages


def test_an_exact_tie_is_cannot_tell(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    _write(a / "Player_Stats.csv", 5)
    _write(b / "Player_Stats.csv", 5)
    stamp = os.stat(a / "Player_Stats.csv").st_mtime
    os.utime(b / "Player_Stats.csv", (stamp, stamp))
    found = detect([_profile("ga", a, "Player_Stats.csv"), _profile("gb", b, "Player_Stats.csv")])
    assert found.game_id is None and found.reason == AMBIGUOUS


def test_an_overridden_logs_dir_is_the_one_stat_ed(tmp_path):
    """--logs-dir moves where a game's logs are. Detection must look there, or it would
    report a disagreement with the pin purely because it looked in the wrong place."""
    real, elsewhere = tmp_path / "real", tmp_path / "elsewhere"
    _write(real / "Player_Stats.csv", 9000)
    _write(elsewhere / "Player_Stats.csv", 2)
    found = detect([_profile("ga", real, "Player_Stats.csv")], logs_dirs={"ga": elsewhere})
    assert found.game_id == "ga"


def test_newest_declared_log_ignores_a_missing_file(tmp_path):
    _write(tmp_path / "Player_Stats.csv", 5)
    profile = _profile("ga", tmp_path, "Player_Stats.csv", "Never_Written.csv")
    assert newest_declared_log(tmp_path, profile) is not None
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_detect.py -q 2>&1 | tail -3
```

Expected: collection error, `ModuleNotFoundError: No module named 'civ_advisor.games.detect'`.

- [ ] **Step 3: Write `civ_advisor/games/detect.py`**

```python
"""Which game is being played, decided from the games' own gameplay logs.

Only files a profile DECLARES are stat'ed. Both engines rewrite engine and
diagnostic logs when they launch, so an undeclared file is exactly the thing
that could make a main-menu process look like a game in progress.

Nothing here opens a file: every answer comes from stat(), and both games'
directories stay read-only.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

from .base import GameProfile

RECENCY_WINDOW_S = 600.0   # 10 minutes: long enough to survive a slow turn, short
                           # enough that yesterday's session is not mistaken for now

DETECTED = "detected"          # one game is freshest and inside the window
NO_LOGS_DIR = "no_logs_dir"    # no registered game has a logs directory with declared logs
ALL_STALE = "all_stale"        # candidates exist, none written inside the window
AMBIGUOUS = "ambiguous"        # two candidates share the freshest timestamp exactly


@dataclass(frozen=True)
class Candidate:
    """One game's freshest declared gameplay log, or the absence of one."""

    game_id: str
    logs_dir: Path
    present: bool          # the logs directory exists
    newest: float | None   # mtime of the freshest declared log; None when there is none
    age: float | None      # seconds since `newest`, at the moment of the scan


@dataclass(frozen=True)
class Detection:
    """What the scan concluded, and everything it saw.

    `game_id` is None when the honest answer is that it cannot tell. `candidates`
    ships regardless so the header can say WHY — "Civ VI last wrote 4 hours ago"
    is a usable statement; a blank one is not.
    """

    game_id: str | None
    reason: str
    candidates: tuple[Candidate, ...]
    at: float

    def candidate(self, game_id: str) -> Candidate | None:
        return next((c for c in self.candidates if c.game_id == game_id), None)


def newest_declared_log(logs_dir: Path, profile: GameProfile) -> float | None:
    """The newest mtime among the files this profile declares, or None if none exist."""
    newest: float | None = None
    for name in profile.log_files:
        try:
            mtime = (logs_dir / name).stat().st_mtime
        except OSError:          # missing, or unreadable: not evidence of play either way
            continue
        if newest is None or mtime > newest:
            newest = mtime
    return newest


def detect(profiles: Iterable[GameProfile], *, logs_dirs: Mapping[str, Path] | None = None,
           now: float | None = None, window: float = RECENCY_WINDOW_S) -> Detection:
    """Which game is being played, from one stat() sweep of every declared log."""
    at = time.time() if now is None else now
    overrides = logs_dirs or {}
    candidates: list[Candidate] = []
    for profile in profiles:
        logs_dir = overrides.get(profile.id, profile.default_logs_dir)
        present = logs_dir.is_dir()
        newest = newest_declared_log(logs_dir, profile) if present else None
        candidates.append(Candidate(
            game_id=profile.id, logs_dir=logs_dir, present=present, newest=newest,
            age=None if newest is None else at - newest,
        ))
    found = tuple(sorted(candidates, key=lambda c: c.game_id))
    live = [c for c in found if c.newest is not None]
    if not live:
        return Detection(None, NO_LOGS_DIR, found, at)
    fresh = [c for c in live if c.age is not None and c.age <= window]
    if not fresh:
        # Deliberately NOT "the least stale". Picking one here would attach a whole
        # dashboard to a game nobody is playing, on evidence that says nothing.
        return Detection(None, ALL_STALE, found, at)
    best = max(c.newest for c in fresh if c.newest is not None)
    winners = [c for c in fresh if c.newest == best]
    if len(winners) > 1:
        return Detection(None, AMBIGUOUS, found, at)
    return Detection(winners[0].game_id, DETECTED, found, at)


__all__ = ["ALL_STALE", "AMBIGUOUS", "Candidate", "DETECTED", "Detection", "NO_LOGS_DIR",
           "RECENCY_WINDOW_S", "detect", "newest_declared_log"]
```

- [ ] **Step 4: Run the tests**

```bash
uv run pytest tests/test_detect.py -q 2>&1 | tail -3
```

Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add civ_advisor/games/detect.py tests/test_detect.py
git commit -m "Detect the running game from its declared gameplay logs

Only declared files count, so an engine log rewritten at launch cannot look
like a game in progress. Nothing recent enough is reported as 'cannot tell'
rather than resolved to the least stale candidate."
```

---

### Task 3: `GameSelector` — the pin wins over detection, visibly

**Files:**
- Create: `civ_advisor/games/selection.py`
- Test: `tests/test_selection.py`

**Interfaces:**
- Consumes: `detect`, `Detection`, `Candidate` (Task 2); `get_profile`, `profile_ids`, `UnknownGame`.
- Produces:
  - `AUTO = "auto"`, `PINNED = "pinned"`
  - `Resolution(profile: GameProfile | None, logs_dir: Path | None, mode: str, pinned_id: str | None, detected_id: str | None, detection_reason: str, disagrees: bool, candidates: tuple[Candidate, ...])`, frozen.
  - `GameSelector(pinned: str | None = None, logs_dirs: Mapping[str, Path] | None = None, window: float = RECENCY_WINDOW_S, clock: Callable[[], float] = time.time)`
  - `GameSelector.pin(game_id: str) -> None`, `.unpin() -> None`, `.mode -> str`, `.resolve() -> Resolution`, `.logs_dir_for(profile) -> Path`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_selection.py`:

```python
import os
import time
from pathlib import Path

import pytest

from civ_advisor.games.civ6 import CIV6
from civ_advisor.games.civ7 import CIV7
from civ_advisor.games.detect import ALL_STALE, DETECTED
from civ_advisor.games.registry import UnknownGame
from civ_advisor.games.selection import AUTO, PINNED, GameSelector


def _live(logs_dir: Path, name: str, age_s: float = 2) -> None:
    logs_dir.mkdir(parents=True, exist_ok=True)
    (logs_dir / name).write_text("x")
    when = time.time() - age_s
    os.utime(logs_dir / name, (when, when))


@pytest.fixture
def dirs(tmp_path):
    return {"civ7": tmp_path / "civ7", "civ6": tmp_path / "civ6"}


def test_auto_follows_detection(dirs):
    _live(dirs["civ6"], "Player_Stats.csv")
    resolved = GameSelector(logs_dirs=dirs).resolve()
    assert resolved.mode == AUTO
    assert resolved.profile is CIV6 and resolved.detected_id == "civ6"
    assert resolved.disagrees is False


def test_a_pin_wins_over_detection_and_says_that_it_disagrees(dirs):
    _live(dirs["civ6"], "Player_Stats.csv")
    resolved = GameSelector(pinned="civ7", logs_dirs=dirs).resolve()
    assert resolved.mode == PINNED
    assert resolved.profile is CIV7
    assert resolved.detected_id == "civ6"
    assert resolved.disagrees is True


def test_a_pin_that_agrees_does_not_claim_a_disagreement(dirs):
    _live(dirs["civ6"], "Player_Stats.csv")
    resolved = GameSelector(pinned="civ6", logs_dirs=dirs).resolve()
    assert resolved.detected_id == "civ6" and resolved.disagrees is False


def test_a_pin_with_no_detection_is_not_a_disagreement(dirs):
    """Detection saying "I cannot tell" does not contradict the pin. Reporting it as a
    disagreement would train the player to ignore a warning that means something."""
    resolved = GameSelector(pinned="civ7", logs_dirs=dirs).resolve()
    assert resolved.detection_reason in {"no_logs_dir", ALL_STALE}
    assert resolved.detected_id is None and resolved.disagrees is False
    assert resolved.profile is CIV7      # a pin still resolves with nothing on disk


def test_auto_with_nothing_recent_resolves_to_no_game(dirs):
    resolved = GameSelector(logs_dirs=dirs).resolve()
    assert resolved.profile is None and resolved.logs_dir is None
    assert resolved.mode == AUTO


def test_pinning_and_unpinning_switch_the_mode(dirs):
    _live(dirs["civ6"], "Player_Stats.csv")
    selector = GameSelector(logs_dirs=dirs)
    assert selector.mode == AUTO
    selector.pin("civ7")
    assert selector.mode == PINNED and selector.resolve().profile is CIV7
    selector.unpin()
    assert selector.mode == AUTO and selector.resolve().profile is CIV6


def test_pinning_an_unknown_game_is_refused(dirs):
    selector = GameSelector(logs_dirs=dirs)
    with pytest.raises(UnknownGame):
        selector.pin("civ5")
    assert selector.mode == AUTO      # the refused pin left no trace


def test_an_overridden_logs_dir_reaches_the_resolution(dirs, tmp_path):
    elsewhere = tmp_path / "elsewhere"
    _live(elsewhere, "Player_Stats.csv")
    resolved = GameSelector(pinned="civ7", logs_dirs={"civ7": elsewhere}).resolve()
    assert resolved.logs_dir == elsewhere
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_selection.py -q 2>&1 | tail -3
```

Expected: `ModuleNotFoundError: No module named 'civ_advisor.games.selection'`.

- [ ] **Step 3: Write `civ_advisor/games/selection.py`**

```python
"""Which game the advisor is advising on, and how that was decided.

Two mechanisms settle it and their precedence is fixed: an explicit choice wins
over detection, always, and the resolution says so. A pin silently overridden by
detection -- or detection silently overridden by a stale pin -- would make the
advisor's own provenance claims unreliable, which is the one thing it may not be.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

from .base import GameProfile
from .detect import RECENCY_WINDOW_S, Candidate, detect
from .registry import get_profile, profile_ids

AUTO = "auto"
PINNED = "pinned"


@dataclass(frozen=True)
class Resolution:
    """The active game, plus everything needed to explain the choice in one line.

    `profile` is None only in AUTO mode when detection could not tell. That is a
    real state, not an error: the advisor has no game to advise on and must say so.
    """

    profile: GameProfile | None
    logs_dir: Path | None
    mode: str                  # AUTO | PINNED
    pinned_id: str | None
    detected_id: str | None
    detection_reason: str
    disagrees: bool            # pinned, and detection names a DIFFERENT game
    candidates: tuple[Candidate, ...]

    @property
    def game_id(self) -> str | None:
        return None if self.profile is None else self.profile.id


class GameSelector:
    """Holds the session's pin and re-runs detection on demand."""

    def __init__(self, pinned: str | None = None,
                 logs_dirs: Mapping[str, Path] | None = None,
                 window: float = RECENCY_WINDOW_S,
                 clock: Callable[[], float] = time.time) -> None:
        self._logs_dirs = dict(logs_dirs or {})
        self._window = window
        self._clock = clock
        self._pinned: str | None = None
        if pinned is not None:
            self.pin(pinned)

    @property
    def mode(self) -> str:
        return PINNED if self._pinned is not None else AUTO

    @property
    def pinned_id(self) -> str | None:
        return self._pinned

    def pin(self, game_id: str) -> None:
        """Pin the session to one game. Raises UnknownGame, leaving the pin untouched."""
        get_profile(game_id)       # validate before mutating; a refused pin leaves no trace
        self._pinned = game_id

    def unpin(self) -> None:
        self._pinned = None

    def logs_dir_for(self, profile: GameProfile) -> Path:
        return self._logs_dirs.get(profile.id, profile.default_logs_dir)

    def resolve(self) -> Resolution:
        found = detect((get_profile(g) for g in profile_ids()),
                       logs_dirs=self._logs_dirs, now=self._clock(), window=self._window)
        if self._pinned is not None:
            profile = get_profile(self._pinned)
            return Resolution(
                profile=profile, logs_dir=self.logs_dir_for(profile), mode=PINNED,
                pinned_id=self._pinned, detected_id=found.game_id,
                detection_reason=found.reason,
                # "cannot tell" does not contradict a pin. Only a NAMED other game does.
                disagrees=found.game_id is not None and found.game_id != self._pinned,
                candidates=found.candidates,
            )
        profile = None if found.game_id is None else get_profile(found.game_id)
        return Resolution(
            profile=profile,
            logs_dir=None if profile is None else self.logs_dir_for(profile),
            mode=AUTO, pinned_id=None, detected_id=found.game_id,
            detection_reason=found.reason, disagrees=False, candidates=found.candidates,
        )


__all__ = ["AUTO", "PINNED", "GameSelector", "Resolution"]
```

- [ ] **Step 4: Run the tests**

```bash
uv run pytest tests/test_selection.py -q 2>&1 | tail -3
```

Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add civ_advisor/games/selection.py tests/test_selection.py
git commit -m "Add the game selector: a pin always wins over detection, visibly

Detection reporting 'cannot tell' is not a disagreement with a pin; only a
named other game is. A warning that fires when nothing is wrong is a warning
the player learns to ignore."
```

---

### Task 4: A game switch is a new sitting

`Store` currently fixes `logs_dir` and `profile` for its lifetime. It gains two
things: an **idle** state (no game selected — the honest answer when detection
cannot tell and nothing is pinned) and `switch_to()`, which forces a new epoch.

**Files:**
- Modify: `civ_advisor/store.py`
- Test: `tests/test_store.py` (appended)

**Interfaces:**
- Consumes: `GameProfile`.
- Produces:
  - `Store(logs_dir: Path | None, archive_root=None, ..., *, profile: GameProfile | None)` — still **required**, now nullable. Required-but-nullable satisfies spec §11: a caller that forgets gets a `TypeError`, and a caller that means "no game yet" must say so.
  - `Store.switch_to(profile: GameProfile, logs_dir: Path) -> None`
  - `Store.active: bool`
  - `Store.rebuild() -> Snapshot | None` — `None` while idle.
  - `Snapshot.game_id: str` — which game produced this snapshot.
  - `store.GAME_SWITCHED = "game_switched"`, a new epoch reason.
  - `SCHEMA_VERSION` stays `1`: `game_id` is an added field, and
    `tests/test_api.py:264` pins the value.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_store.py` (the file already imports `Store`; add
`from civ_advisor.games.civ6 import CIV6` and
`from civ_advisor.store import GAME_SWITCHED`):

```python
def test_a_snapshot_records_which_game_produced_it(fixture_dir):
    captured = Store(fixture_dir, profile=CIV7).rebuild()
    assert captured.game_id == "civ7"


def test_switching_games_starts_a_new_sitting(fixture_dir, civ6_dir):
    """Spec 8.1: nothing computed under the previous game may survive the switch. The
    session id is what acknowledgements are filed under, so it must change."""
    store = Store(fixture_dir, profile=CIV7)
    first = store.rebuild()
    store.switch_to(CIV6, civ6_dir)
    second = store.rebuild()

    assert second.game_id == "civ6"
    assert second.epoch == first.epoch + 1
    assert second.epoch_reason == GAME_SWITCHED
    assert second.session != first.session
    assert second.revision > first.revision      # revision stays monotonic across a switch


def test_a_switch_does_not_inherit_the_previous_game_s_save_key(fixture_dir, civ6_dir):
    store = Store(fixture_dir, profile=CIV7)
    first = store.rebuild()
    store.switch_to(CIV6, civ6_dir)
    second = store.rebuild()
    assert first.game_key is not None
    assert second.game_key != first.game_key


def test_switching_back_does_not_resume_the_earlier_sitting(fixture_dir, civ6_dir):
    """Returning to Civ VII is a third sitting, not the first one continued: the logs
    were rewritten while we were not watching them."""
    store = Store(fixture_dir, profile=CIV7)
    first = store.rebuild()
    store.switch_to(CIV6, civ6_dir)
    store.rebuild()
    store.switch_to(CIV7, fixture_dir)
    third = store.rebuild()
    assert third.session != first.session and third.epoch == first.epoch + 2


def test_an_idle_store_has_no_snapshot_and_does_not_invent_one():
    """Auto mode with nothing recent on disk. 'I cannot tell which game is running' is a
    supported answer; a snapshot built from no logs would be an assertion."""
    store = Store(None, profile=None)
    assert store.active is False
    assert store.rebuild() is None
    assert store.snapshot is None


def test_activating_an_idle_store_is_the_first_load_not_a_switch(civ6_dir):
    store = Store(None, profile=None)
    store.switch_to(CIV6, civ6_dir)
    captured = store.rebuild()
    assert captured is not None
    assert captured.epoch == 1 and captured.epoch_reason == "first_load"
```

`civ6_dir` is the phase-2a fixture in `tests/conftest.py`; confirm the fixture
name with `grep -n 'def civ6_dir' tests/conftest.py` before relying on it.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_store.py -q 2>&1 | tail -5
```

Expected: `ImportError: cannot import name 'GAME_SWITCHED'`.

- [ ] **Step 3: Add the switch to `civ_advisor/store.py`**

Add the reason constant beside the others:

```python
GAME_SWITCHED = "game_switched"
```

Add `game_id` to `Snapshot`, directly below `schema_version`:

```python
    game_id: str            # which game's readers produced this; never inferred downstream
```

Change the constructor signature and body:

```python
    def __init__(self, logs_dir: Path | None, archive_root: Path | None = None,
                 commentary_worker: CommentaryWorker | None = None,
                 identity_provider: Callable[[Snapshot], dict] | None = None,
                 *, profile: GameProfile | None) -> None:
```

and below `self.profile = profile` add:

```python
        self._pending_switch = False   # a game switch forces the next snapshot to a new epoch
```

Add, after the `insights` property:

```python
    @property
    def active(self) -> bool:
        """Whether a game is selected at all. False is a real state, not a failure."""
        return self.profile is not None and self.logs_dir is not None

    def switch_to(self, profile: GameProfile, logs_dir: Path) -> None:
        """Point the store at another game.

        Everything computed under the previous game is dropped here rather than
        left to expire: the reader table, the capability matrix and the context
        namespace all change at once, so the previous snapshot is not this game's
        past in any sense. Subscribers survive -- the browser is still connected --
        but the next snapshot starts a new epoch, which is what makes the change
        tracker and the player's record treat this as another sitting.
        """
        with self._lock:
            if self.profile is not None and self.profile.id == profile.id \
                    and self.logs_dir == logs_dir:
                return
            had_game = self.profile is not None
            self.profile = profile
            self.logs_dir = logs_dir
            self.snapshot = None
            self._observed_key = None
            self._session_has_data = False
            self._pending_reason = None
            # Activating an idle store is not a switch; it is this store's first load.
            self._pending_switch = had_game
```

In `rebuild`, guard the idle case:

```python
    def rebuild(self) -> Snapshot | None:
        """Re-read every log, archive it, and recompute advice. Safe to call from a
        worker thread. Returns None while no game is selected."""
        profile, logs_dir = self.profile, self.logs_dir
        if profile is None or logs_dir is None:
            return None
        raw = load_logs(logs_dir, profile)
        state = build_state(raw)
        insights = run_all(state)
        key = game_key(logs_dir)
        with self._lock:
            snapshot = self._capture_locked(raw, state, insights, key)
            self.snapshot = snapshot
        self._archive(raw, snapshot.session)
        if self.commentary_worker is not None:
            self.commentary_worker.schedule(snapshot, revisions=self.revisions(snapshot))
        return snapshot
```

In `_capture_locked`, pass the id through to the snapshot:

```python
        assert self.profile is not None
        return Snapshot(
            schema_version=SCHEMA_VERSION,
            game_id=self.profile.id,
            session=self._session, epoch=self._epoch, epoch_reason=self._session_reason,
            ...
```

And make `_session_reason_locked` honour the pending switch, as its **first**
statement — before the `if not raw.stats` branch, so a switch into a game that
has not written a stats row yet still starts its own epoch:

```python
        if self._pending_switch:
            self._pending_switch = False
            return GAME_SWITCHED
```

Finally, `_archive` must not run while idle; its first line becomes:

```python
        if self.archive_root is None or self.logs_dir is None:
            return
```

- [ ] **Step 4: Fix the snapshot factory**

`tests/factories.py:119` builds a `Snapshot` positionally/by keyword and now
needs `game_id`. Add `game_id: str = "civ7"` to the factory's parameters and
pass it through. This is a test helper, not an assertion.

- [ ] **Step 5: Run the full suite**

```bash
uv run pytest -q 2>&1 | tail -3
```

Expected: Task 1's count **plus 6**, zero failures.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "Make a game switch a new sitting

Switching changes the logs directory, reader table, capability matrix and
context namespace at once, so the epoch increments for the same reason a
reload does: the past being compared against is not this game's past. A store
with no game selected is idle rather than guessing."
```

---

### Task 5: Namespace the archive and the player's notes per game

**Files:**
- Modify: `civ_advisor/archive.py` (`DEFAULT_ARCHIVE_ROOT`, `LEGACY_ARCHIVE_ROOT`, `archive_root_for`)
- Modify: `civ_advisor/context_store.py` (`DEFAULT_STORE_ROOT`, `store_path_for`, `LEGACY_STORE_PATH`)
- Modify: `civ_advisor/cli.py` (defaults, the legacy notice, `archive list`)
- Test: `tests/test_archive.py`, `tests/test_context_store.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: `GameProfile`.
- Produces:
  - `archive.DEFAULT_ROOT = Path.home() / ".civ-advisor"`
  - `archive.LEGACY_ARCHIVE_ROOT = Path.home() / ".civ7-advisor" / "archive"`
  - `archive.archive_root_for(game_id: str, base: Path = DEFAULT_ROOT) -> Path` → `<base>/<game_id>/archive`
  - `context_store.store_path_for(game_id: str, base: Path = DEFAULT_ROOT) -> Path` → `<base>/<game_id>/player-context.json`
  - `context_store.LEGACY_STORE_PATH = Path.home() / ".civ7-advisor" / "player-context.json"`
  - `DEFAULT_ARCHIVE_ROOT` and `DEFAULT_STORE_PATH` are **kept as aliases of the
    legacy paths**, because `tests/test_archive.py` and `tests/test_context_store.py`
    import them and they still name something real: where a pre-2b install put
    its data.

**What happens to existing data, stated plainly.** A user upgrading has
`~/.civ7-advisor/archive/<save-key>/<session>/` and
`~/.civ7-advisor/player-context.json`. After this task the defaults are
`~/.civ-advisor/civ7/archive/...` and `~/.civ-advisor/civ7/player-context.json`.

- **Nothing is moved, copied or deleted.** Moving a user's files without asking
  is not acceptable, and neither is doing it silently on their behalf.
- **Nothing is silently orphaned either.** Three things prevent that:
  1. `civ-advisor archive list` walks the legacy root as well as the new one and
     labels those rows `civ7 (pre-2b)`, so the old archives remain visible from
     the tool that exists to see them.
  2. On startup, if a legacy path exists and the corresponding new path does
     not, the CLI prints one line naming the old location and the exact `mv`
     that would adopt it. It does not run it.
  3. `--archive-dir` and `--context-file` still accept the old paths verbatim,
     so a user who wants continuity has a one-flag answer today.

This is the only honest option: the archive is keyed by save seeds and the
context file holds acknowledgements, and neither can be *proved* to be Civ
VII's rather than something the user put there. Assuming is the failure mode
this project exists to avoid.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_archive.py`:

```python
def test_the_archive_root_is_namespaced_per_game(tmp_path):
    from civ_advisor.archive import archive_root_for

    assert archive_root_for("civ6", base=tmp_path) == tmp_path / "civ6" / "archive"
    assert archive_root_for("civ7", base=tmp_path) != archive_root_for("civ6", base=tmp_path)


def test_the_legacy_archive_root_is_still_named(tmp_path):
    """A user's existing archives are not orphaned by being renamed out of the code."""
    from civ_advisor.archive import LEGACY_ARCHIVE_ROOT

    assert LEGACY_ARCHIVE_ROOT.name == "archive"
    assert LEGACY_ARCHIVE_ROOT.parent.name == ".civ7-advisor"
```

Append to `tests/test_context_store.py`:

```python
def test_the_context_path_is_namespaced_per_game(tmp_path):
    from civ_advisor.context_store import store_path_for

    assert store_path_for("civ7", base=tmp_path) == tmp_path / "civ7" / "player-context.json"
    assert store_path_for("civ6", base=tmp_path) != store_path_for("civ7", base=tmp_path)
```

Append to `tests/test_cli.py`:

```python
def test_archive_list_shows_pre_2b_archives_under_a_label(tmp_path, capsys, monkeypatch):
    """An existing archive must stay visible from the tool that exists to see it."""
    import civ_advisor.cli as cli

    legacy = tmp_path / ".civ7-advisor" / "archive" / "seeds-1-2" / "20260101T000000-1-abc"
    legacy.mkdir(parents=True)
    (legacy / "archived.json").write_text('{"files": ["Player_Stats.csv"], "updated": "x"}')
    monkeypatch.setattr(cli, "LEGACY_ARCHIVE_ROOT", tmp_path / ".civ7-advisor" / "archive")

    assert cli.main(["archive", "list", "--archive-dir", str(tmp_path / ".civ-advisor")]) == 0
    out = capsys.readouterr().out
    assert "pre-2b" in out and "seeds-1-2" in out
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_archive.py tests/test_context_store.py tests/test_cli.py -q 2>&1 | tail -5
```

Expected: `ImportError: cannot import name 'archive_root_for'`.

- [ ] **Step 3: Add the per-game roots**

In `civ_advisor/archive.py`, replace the `DEFAULT_ARCHIVE_ROOT` line with:

```python
DEFAULT_ROOT = Path.home() / ".civ-advisor"      # our own directory, never the game's
# Where a pre-2b install kept everything. Still named, and still readable: the tooling
# lists it, and --archive-dir accepts it. Nothing here moves a user's files.
LEGACY_ARCHIVE_ROOT = Path.home() / ".civ7-advisor" / "archive"
DEFAULT_ARCHIVE_ROOT = LEGACY_ARCHIVE_ROOT       # retained: existing imports and tests


def archive_root_for(game_id: str, base: Path = DEFAULT_ROOT) -> Path:
    """Where this game's logs are mirrored. `game_id` is the TITLE (civ6/civ7); the
    save-seeds key is a directory deeper, under this root."""
    return base / game_id / "archive"
```

In `civ_advisor/context_store.py`, beside `DEFAULT_STORE_PATH`:

```python
from civ_advisor.archive import DEFAULT_ROOT

LEGACY_STORE_PATH = Path.home() / ".civ7-advisor" / "player-context.json"
DEFAULT_STORE_PATH = LEGACY_STORE_PATH           # retained: existing imports and tests


def store_path_for(game_id: str, base: Path = DEFAULT_ROOT) -> Path:
    """Where this game's goals, acknowledgements and watchlist live. Per game: an
    acknowledgement made in Civ VII is not an acknowledgement in Civ VI."""
    return base / game_id / "player-context.json"
```

Check for an import cycle first: `context_store` must not already be imported
by `archive`. It is not (`archive.py` imports only stdlib), so this direction is
safe.

Add both new names to each module's `__all__`.

- [ ] **Step 4: Point the CLI at the new roots and keep the old ones visible**

In `civ_advisor/cli.py`:

```python
from civ_advisor.archive import DEFAULT_ROOT, LEGACY_ARCHIVE_ROOT, MANIFEST, archive_root_for
from civ_advisor.context_store import (
    LEGACY_STORE_PATH, PersistentContextStore, store_path_for,
)
```

`--archive-dir` and `--context-file` default to `None`; the chosen profile
fills them in after parsing:

```python
    parser.add_argument("--archive-dir", type=Path, default=None,
                        help=f"where to mirror the logs (default: {DEFAULT_ROOT}/<game>/archive)")
    parser.add_argument("--context-file", type=Path, default=None,
                        help="where to keep your goals and acknowledgements "
                             f"(default: {DEFAULT_ROOT}/<game>/player-context.json)")
```

and after the profile is known (Task 6 replaces `profile` here with the
selector's initial resolution; the shape is the same):

```python
    archive_root = None if args.no_archive else (
        args.archive_dir or archive_root_for(profile.id))
    store_path = (Path(tempfile.mkdtemp(prefix="civ-context-")) / "player-context.json"
                  if args.no_context_file else
                  (args.context_file or store_path_for(profile.id)))
    _report_legacy_data(archive_root, store_path)
```

Task 7 moves this behind the selector, because with `--game auto` there is no
`profile.id` yet; the shape and the call to `_report_legacy_data` are unchanged.

```python
```

with, at module level:

```python
def _report_legacy_data(archive_root: Path | None, store_path: Path | None) -> None:
    """Say where a pre-2b install's data is, once, and how to adopt it.

    Storage is now per game, so the old single-rooted directory is not read by default.
    Printing this is the alternative to two unacceptable options: moving a user's files
    without asking, or leaving them where nothing mentions them again.
    """
    for legacy, current, what, flag in (
        (LEGACY_ARCHIVE_ROOT, archive_root, "archived logs", "--archive-dir"),
        (LEGACY_STORE_PATH, store_path, "goals and acknowledgements", "--context-file"),
    ):
        if current is None or not legacy.exists() or current.exists():
            continue
        print(f"note: your earlier {what} are still at {legacy}. Storage is now per game.\n"
              f"      To adopt them:  mv {legacy} {current}\n"
              f"      Or keep using them where they are with {flag} {legacy}",
              file=sys.stderr)
```

- [ ] **Step 5: Make `archive list` walk both roots**

Replace the body of `_archive_command` after `args = parser.parse_args(argv)`:

```python
    roots: list[tuple[Path, str]] = []
    base = args.archive_dir or DEFAULT_ROOT
    for game in sorted(profile_ids()):
        root = archive_root_for(game, base=base)
        if root.is_dir():
            roots.append((root, game))
    if LEGACY_ARCHIVE_ROOT.is_dir():
        roots.append((LEGACY_ARCHIVE_ROOT, "civ7 (pre-2b)"))
    if not roots:
        print(f"No archive at {base}")
        return 0
    for root, label in roots:
        for key in sorted(p for p in root.iterdir() if p.is_dir()):
            for session in sorted(p for p in key.iterdir() if p.is_dir()):
                manifest = session / MANIFEST
                files, updated = [], "?"
                if manifest.is_file():
                    data = json.loads(manifest.read_text())
                    files, updated = data.get("files", []), data.get("updated", "?")
                n = len(files)
                print(f"{label}  {key.name}  {session.name}  "
                      f"{n} file{'s' if n != 1 else ''}  updated {updated}")
    return 0
```

`--archive-dir` here now means the **base** (`~/.civ-advisor`), not one game's
archive directory. `_archive_command`'s parser needs `LEGACY_ARCHIVE_ROOT`
readable as a module attribute for the test's `monkeypatch.setattr` to bite, so
reference it as `LEGACY_ARCHIVE_ROOT` imported at module level (as above) and
read it inside the function — which the code does.

- [ ] **Step 6: Run the full suite**

```bash
uv run pytest -q 2>&1 | tail -3
```

Expected: Task 4's count **plus 4**, zero failures.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "Namespace archives and player notes per game

Storage moves to ~/.civ-advisor/<game>/. Nothing on a user's disk is moved or
deleted: the old root is still listed by 'archive list', still accepted by
--archive-dir and --context-file, and named on startup with the mv that would
adopt it."
```

---

### Task 6: An acknowledgement cannot cross games

Per-game paths are not sufficient on their own: `--context-file` can point two
games at one file, and the pre-2b file has no game recorded at all. The entry
itself must carry the game.

**Files:**
- Modify: `civ_advisor/context_store.py` (`Entry.game`, `adopt`, serialization)
- Modify: `civ_advisor/api/app.py` (pass the game to `adopt` and `record`)
- Test: `tests/test_context_store.py`

**Interfaces:**
- Consumes: `Snapshot.game_id` (Task 4).
- Produces:
  - `Entry.game: str = ""` — `""` means "recorded before games were distinguished".
  - `PersistentContextStore.adopt(session, epoch, game_key, epoch_reason="", *, game: str = "")`
  - `PersistentContextStore.record(..., game: str = "")`
  - An entry whose `game` differs from the adopted game is neither applied nor offered for association.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_context_store.py`:

```python
def test_an_entry_records_the_game_it_was_made_in(tmp_path):
    store = PersistentContextStore(path=tmp_path / "notes.json")
    store.load()
    store.adopt("s1", 1, None, game="civ7")
    entry = store.record(kind="acknowledged", subject="x", turn=10, game="civ7")
    assert entry.game == "civ7"
    raw = json.loads((tmp_path / "notes.json").read_text())
    assert raw["entries"][0]["game"] == "civ7"


def test_another_game_s_entries_are_neither_applied_nor_offered(tmp_path):
    """Spec 8.1: offering an acknowledgement across the boundary would repeat exactly
    the mistake the reload logic exists to prevent."""
    store = PersistentContextStore(path=tmp_path / "notes.json")
    store.load()
    store.adopt("s1", 1, None, game="civ7")
    store.record(kind="acknowledged", subject="x", turn=10, game="civ7")

    store.adopt("s2", 2, None, game="civ6")
    assert store.of_kind("acknowledged") == []
    assert all(a.session != "s1" for a in store.pending)


def test_the_same_game_in_another_sitting_is_still_offered(tmp_path):
    """The reload flow is unchanged WITHIN a game; only the cross-game case is closed."""
    store = PersistentContextStore(path=tmp_path / "notes.json")
    store.load()
    store.adopt("s1", 1, None, game="civ7")
    store.record(kind="acknowledged", subject="x", turn=10, game="civ7")

    store.adopt("s2", 2, None, game="civ7")
    assert [a.session for a in store.pending] == ["s1"]


def test_an_entry_from_before_namespacing_is_offered_not_applied(tmp_path):
    """A pre-2b file records no game. It cannot be attributed, so it is shown to the
    player to accept rather than silently treated as this game's."""
    (tmp_path / "notes.json").write_text(json.dumps({
        "schema_version": SCHEMA_VERSION, "revision": 1,
        "entries": [{"id": "e1", "kind": "acknowledged", "subject": "x", "turn": 3,
                     "session": "old", "epoch": 1, "text": "", "fingerprint": "",
                     "game_key": None, "recorded_at": "2026-01-01T00:00:00"}]}))
    store = PersistentContextStore(path=tmp_path / "notes.json")
    store.load()
    store.adopt("s1", 1, None, game="civ7")
    assert store.of_kind("acknowledged") == []
    assert [a.session for a in store.pending] == ["old"]
```

Match the on-disk entry shape to the file's real serializer before writing this
test — read `PersistentContextStore._serialize`/`_entry_from` and copy the keys
exactly.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_context_store.py -q 2>&1 | tail -5
```

Expected: `TypeError: adopt() got an unexpected keyword argument 'game'`.

- [ ] **Step 3: Add `game` to `Entry` and filter on it**

Add the field to `Entry` with a default so existing construction sites and old
files still work:

```python
    game: str = ""       # "" means recorded before games were distinguished
```

Serialize it alongside the other fields, and read it with
`raw.get("game", "")` so a pre-2b file loads rather than being quarantined —
being *unattributable* is the point, not being unreadable.

In `adopt`, add the keyword and widen the "mine" test from `(session, epoch)`
to `(game, session, epoch)`:

```python
    def adopt(self, session: str, epoch: int, game_key: str | None,
              epoch_reason: str = "", *, game: str = "") -> None:
        with self._lock:
            if (self.game, self.session, self.epoch) == (game, session, epoch):
                return
            held = getattr(self, "_loaded", ())
            self.game, self.session, self.epoch, self.game_key = game, session, epoch, game_key
            def mine_p(e: Entry) -> bool:
                return e.game == game and e.session == session and e.epoch == epoch
            mine = {e.id: e for e in list(held) + list(self.entries.values()) if mine_p(e)}
            others = [e for e in list(held) + list(self.entries.values()) if not mine_p(e)]
            self.entries = mine
```

Then, where `groups` is built from `others`, exclude entries belonging to a
**different named** game — they are not this game's, and offering them would be
the cross-game leak:

```python
            for entry in others:
                if entry.game and entry.game != game:
                    continue   # another game's record. Not ours to apply, not ours to offer.
                groups.setdefault((entry.session, entry.epoch), []).append(entry)
```

An entry with `game == ""` falls through to `groups` and is offered — which is
the honest treatment of a record whose game is unknown.

Initialise `self.game = ""` in `__init__` (or as a dataclass field, matching the
class's existing style), and add `game` to `record(...)` so a new entry is
stamped with the adopted game by default:

```python
    def record(self, kind: str, subject: str, turn: int, text: str = "",
               fingerprint: str = "", game: str = "") -> Entry:
        ...
        entry = Entry(..., game=game or self.game, ...)
```

- [ ] **Step 4: Pass the game from the API**

In `civ_advisor/api/app.py`, every `record.adopt(captured.session, captured.epoch,
captured.game_key, captured.epoch_reason)` call gains `game=captured.game_id`
(there are three: in `brief_for`, `api_record`, `api_write_record`), and the
`record.record(...)` call in `api_write_record` gains `game=captured.game_id`.

- [ ] **Step 5: Run the full suite**

```bash
uv run pytest -q 2>&1 | tail -3
```

Expected: Task 5's count **plus 4**, zero failures.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "Record which game each note was made in

Per-game files are not enough: --context-file can point two games at one file,
and a pre-2b file names no game at all. Another game's acknowledgement is now
neither applied nor offered; an unattributable one is offered, never assumed."
```

---

### Task 7: Wire selection into the app — `/api/game`, the supervisor, and `--game auto`

**Files:**
- Modify: `civ_advisor/api/app.py` (selector, supervisor task, endpoints, store swap)
- Modify: `civ_advisor/api/serialize.py` (`game_to_dict`, `status_to_dict`)
- Modify: `civ_advisor/cli.py` (`--game auto`, pass the selector through)
- Test: `tests/test_api.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: `GameSelector`, `Resolution` (Task 3); `Store.switch_to`, `Store.active` (Task 4); `archive_root_for`, `store_path_for` (Task 5).
- Produces:
  - `create_app(logs_dir: Path | None, ..., *, profile: GameProfile | None = ..., selector: GameSelector | None = None, storage_base: Path | None = None)`. When `selector` is None the app behaves exactly as today: one fixed profile, no detection, no supervisor. Every existing test therefore keeps working unchanged.
  - `serialize.game_to_dict(resolution: Resolution) -> dict`
  - `GET /api/game`, `POST /api/game` (`{"game": "civ6"}` or `{"game": "auto"}`)
  - `status["game"]` inside `/api/status` and `/api/briefing`.
  - SSE event `{"type": "game_changed", "game": "<id>", "session": ..., "epoch": ...}`.
  - `civ-advisor --game auto`, and `auto` as the default.

**Why `--game` defaults to `auto`.** This is the second deliberate Civ VII
behaviour change. With two games registered, a default of `civ7` makes
detection invisible to anyone who does not read the flag list, and leaves a Civ
VI player staring at an empty Civ VII dashboard — the exact failure the phase
exists to remove. `--game civ7` still pins, and a pinned run behaves precisely
as it does today. `--logs-dir` still requires an explicit game (Task 1), so the
`auto` default never applies to an overridden directory.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_api.py`:

```python
def _selector(tmp_path, civ7_dir, civ6_dir, pinned=None):
    from civ_advisor.games.selection import GameSelector
    return GameSelector(pinned=pinned, logs_dirs={"civ7": civ7_dir, "civ6": civ6_dir})


def test_api_game_reports_the_mode_and_what_detection_thinks(fixture_dir, civ6_dir, tmp_path):
    from civ_advisor.games.selection import GameSelector

    selector = GameSelector(pinned="civ7", logs_dirs={"civ7": fixture_dir, "civ6": civ6_dir})
    with TestClient(create_app(fixture_dir, poll_interval=60, profile=CIV7,
                               selector=selector, storage_base=tmp_path)) as c:
        body = c.get("/api/game").json()
    assert body["mode"] == "pinned" and body["active"]["id"] == "civ7"
    assert [g["id"] for g in body["games"]] == ["civ6", "civ7"]
    assert body["active"]["display_name"] == "Civilization VII"


def test_posting_a_game_pins_it_and_switches_the_store(fixture_dir, civ6_dir, tmp_path):
    from civ_advisor.games.selection import GameSelector

    selector = GameSelector(logs_dirs={"civ7": fixture_dir, "civ6": civ6_dir})
    with TestClient(create_app(fixture_dir, poll_interval=60, profile=CIV7,
                               selector=selector, storage_base=tmp_path)) as c:
        before = c.get("/api/status").json()
        assert c.post("/api/game", json={"game": "civ6"}).status_code == 200
        after = c.get("/api/status").json()
    assert before["game"]["active"]["id"] == "civ7"
    assert after["game"]["active"]["id"] == "civ6"
    assert after["game"]["mode"] == "pinned"
    assert after["epoch"] == before["epoch"] + 1       # a switch is a new sitting
    assert after["session"] != before["session"]


def test_posting_auto_returns_to_detection(fixture_dir, civ6_dir, tmp_path):
    from civ_advisor.games.selection import GameSelector

    selector = GameSelector(pinned="civ7", logs_dirs={"civ7": fixture_dir, "civ6": civ6_dir})
    with TestClient(create_app(fixture_dir, poll_interval=60, profile=CIV7,
                               selector=selector, storage_base=tmp_path)) as c:
        assert c.post("/api/game", json={"game": "auto"}).status_code == 200
        assert c.get("/api/game").json()["mode"] == "auto"


def test_posting_an_unknown_game_is_refused_without_changing_anything(fixture_dir, tmp_path):
    from civ_advisor.games.selection import GameSelector

    selector = GameSelector(pinned="civ7", logs_dirs={"civ7": fixture_dir})
    with TestClient(create_app(fixture_dir, poll_interval=60, profile=CIV7,
                               selector=selector, storage_base=tmp_path)) as c:
        assert c.post("/api/game", json={"game": "civ5"}).status_code == 422
        assert c.get("/api/game").json()["active"]["id"] == "civ7"


def test_status_carries_the_game_when_no_selector_is_configured(fixture_dir):
    """A fixed-profile app still says which game it is advising on."""
    with TestClient(create_app(fixture_dir, poll_interval=60, profile=CIV7)) as c:
        body = c.get("/api/status").json()
    assert body["game"]["active"]["id"] == "civ7" and body["game"]["mode"] == "pinned"


def test_an_idle_app_explains_itself_rather_than_erroring_blankly(tmp_path):
    """Auto mode, nothing recent on disk: the briefing is unavailable, and /api/game
    still answers so the header can say why and offer the control."""
    from civ_advisor.games.selection import GameSelector

    empty = {"civ7": tmp_path / "no7", "civ6": tmp_path / "no6"}
    selector = GameSelector(logs_dirs=empty)
    with TestClient(create_app(None, poll_interval=60, profile=None,
                               selector=selector, storage_base=tmp_path)) as c:
        assert c.get("/api/briefing").status_code == 503
        body = c.get("/api/game").json()
    assert body["active"] is None
    assert body["detection"]["reason"] in {"no_logs_dir", "all_stale"}
    assert body["mode"] == "auto"
```

Append to `tests/test_cli.py`:

```python
def test_game_auto_starts_in_detection(monkeypatch):
    import civ_advisor.cli as cli

    seen = {}

    def fake_create_app(logs_dir, poll_interval, **kwargs):
        seen.update(kwargs)
        return object()

    monkeypatch.setattr(cli, "create_app", fake_create_app)
    monkeypatch.setattr(cli.uvicorn, "run", lambda *a, **k: None)
    monkeypatch.setattr(Path, "is_dir", lambda self: True)

    assert cli.main(["--game", "auto", "--no-llm", "--no-context-file", "--no-archive"]) == 0
    assert seen["selector"].mode == "auto"


def test_game_civ6_starts_pinned(monkeypatch):
    import civ_advisor.cli as cli

    seen = {}
    monkeypatch.setattr(cli, "create_app", lambda l, p, **k: seen.update(k) or object())
    monkeypatch.setattr(cli.uvicorn, "run", lambda *a, **k: None)
    monkeypatch.setattr(Path, "is_dir", lambda self: True)

    assert cli.main(["--game", "civ6", "--no-llm", "--no-context-file", "--no-archive"]) == 0
    assert seen["selector"].mode == "pinned" and seen["selector"].pinned_id == "civ6"
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_api.py tests/test_cli.py -q 2>&1 | tail -5
```

Expected: `TypeError: create_app() got an unexpected keyword argument 'selector'`.

- [ ] **Step 3: Serialize the selection**

In `civ_advisor/api/serialize.py`:

```python
def game_to_dict(resolution: Resolution) -> dict:
    """Which game is being advised on, how that was decided, and what else is on offer.

    `mode` and `disagrees` are not decoration: a pinned choice that detection contradicts
    is the one case where the dashboard's numbers come from a game the player may not be
    looking at, and the header has to say so rather than leave it to be discovered.
    """
    from civ_advisor.games.registry import get_profile, profile_ids

    def described(profile) -> dict:
        return {"id": profile.id, "display_name": profile.display_name,
                "capabilities": capability_report(profile)}

    active = resolution.profile
    return {
        "mode": resolution.mode,
        "pinned": resolution.pinned_id,
        "active": None if active is None else dict(
            described(active), logs_dir=str(resolution.logs_dir)),
        "disagrees": resolution.disagrees,
        "detection": {
            "game": resolution.detected_id,
            "reason": resolution.detection_reason,
            "candidates": [
                {"id": c.game_id, "logs_dir": str(c.logs_dir), "present": c.present,
                 "age": None if c.age is None else round(c.age, 1)}
                for c in resolution.candidates
            ],
        },
        "games": [described(get_profile(g)) for g in profile_ids()],
    }
```

and in `status_to_dict`, add a `game` parameter (defaulted so existing callers
and `tests/factories.py` keep working) and include it:

```python
def status_to_dict(snapshot: Snapshot, oracle: bool, game: dict | None = None) -> dict:
    return {
        "schema_version": snapshot.schema_version,
        "game_id": snapshot.game_id,
        "game": game,
        ...
```

`briefing_to_dict` gains the same `game: dict | None = None` parameter and
forwards it to `status_to_dict`.

- [ ] **Step 4: Give `create_app` a selector and a supervisor**

In `civ_advisor/api/app.py`, replace the signature:

```python
def create_app(logs_dir: Path | None, poll_interval: float = 1.0,
               archive_root: Path | None = None,
               commentary_worker: CommentaryWorker | None = None,
               player_store: PersistentContextStore | None = None,
               *, profile: GameProfile | None,
               selector: GameSelector | None = None,
               storage_base: Path | None = None,
               archiving: bool = True) -> FastAPI:
```

`archiving` is separate from `archive_root` on purpose: "no root was supplied,
derive one per game" and "the player said --no-archive" are different
instructions, and conflating them is how a `--no-archive` run ends up writing to
a user's home directory.

Immediately after, normalise the selection. A `selector` of None means "one
fixed game, no detection" — which is what every existing test wants, and what
keeps this change additive:

```python
    if selector is None:
        if profile is None or logs_dir is None:
            raise ValueError("create_app needs either a profile and a logs_dir, or a selector")
        selector = GameSelector(pinned=profile.id, logs_dirs={profile.id: logs_dir})
        supervise_selection = False
    else:
        supervise_selection = True
    base = storage_base if storage_base is not None else DEFAULT_ROOT
```

Storage follows the active game. When the caller supplied an explicit
`archive_root` or `player_store`, those are honoured for every game (an
explicit path is the player's instruction, and Task 6 keeps the notes
separated inside it):

```python
    def archive_for(active: GameProfile) -> Path | None:
        if not archiving:
            return None
        return archive_root if archive_root is not None else archive_root_for(active.id, base=base)

    record = player_store if player_store is not None else PersistentContextStore()
    record.load()
    fixed_record = player_store is not None
```

Replace the `store = Store(...)` line and the lifespan with:

```python
    store = Store(logs_dir, None if profile is None else archive_for(profile),
                  commentary_worker=commentary_worker,
                  identity_provider=identity_provider, profile=profile)
    resolution = selector.resolve()

    def activate(new: Resolution) -> bool:
        """Point everything at `new`'s game. Returns whether anything changed."""
        nonlocal resolution, record
        resolution = new
        active = new.profile
        if active is None or new.logs_dir is None:
            return False
        store.archive_root = archive_for(active)   # set before the early return: the
        # fixed-profile path activates the game it was already constructed with
        if store.profile is not None and store.profile.id == active.id \
                and store.logs_dir == new.logs_dir:
            return False
        if not fixed_record:
            record = PersistentContextStore(path=store_path_for(active.id, base=base))
            record.load()
        history.forget()          # "since last turn" has no meaning across a game switch
        store.switch_to(active, new.logs_dir)
        return True

    activate(resolution)
```

`record` is reassigned, so every closure that uses it must read the enclosing
variable rather than capture a value — they already do (`record.adopt(...)`),
so only `nonlocal record` above is needed.

`History` needs a `forget()`. Add it to `civ_advisor/decisions/changes.py`:

```python
    def forget(self) -> None:
        """Drop every recorded turn. A game switch, not a reload: the entries are another
        game's turns and `previous()` must not be able to reach them even by accident."""
        self.entries.clear()
```

Its session+epoch filter already isolates them; clearing is belt and braces and
keeps the bounded list from carrying a dead game's turns for the rest of the run.

The lifespan becomes a watcher plus a supervisor:

```python
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        loop = asyncio.get_running_loop()
        watcher: asyncio.Task | None = None

        def on_change() -> None:  # runs in a worker thread
            captured = store.rebuild()
            if captured is None:
                return
            loop.call_soon_threadsafe(store.publish, {
                "type": "state_changed", "turn": captured.analysis_turn,
                "latest_turn": captured.latest_turn, "revision": captured.revision,
                "session": captured.session, "epoch": captured.epoch,
                "game": captured.game_id,
            })

        async def start_watching() -> asyncio.Task | None:
            if not store.active:
                return None
            assert store.logs_dir is not None and store.profile is not None
            initial = poll_snapshot(store.logs_dir, store.profile.log_files)
            await asyncio.to_thread(store.rebuild)
            return asyncio.create_task(watch(store.logs_dir, store.profile.log_files,
                                             on_change, poll_interval, initial))

        async def supervise() -> None:
            """Re-resolve the selection every poll and swap games when it changes.

            Never ends on an exception: it is not awaited, so an escape would freeze the
            advisor on one game for the rest of the session with nothing on screen saying
            so. CancelledError is a BaseException, so shutdown still works.
            """
            nonlocal watcher
            while True:
                await asyncio.sleep(poll_interval)
                try:
                    new = await asyncio.to_thread(selector.resolve)
                    if not activate(new):
                        continue
                    if watcher is not None:
                        watcher.cancel()
                    watcher = await start_watching()
                    captured = store.snapshot
                    store.publish({
                        "type": "game_changed", "game": store.profile.id,
                        "session": None if captured is None else captured.session,
                        "epoch": None if captured is None else captured.epoch,
                    })
                except Exception:
                    log.exception("game selection failed; keeping the current game")

        watcher = await start_watching()
        supervisor = asyncio.create_task(supervise()) if supervise_selection else None
        try:
            yield
        finally:
            if watcher is not None:
                watcher.cancel()
            if supervisor is not None:
                supervisor.cancel()
            if store.commentary_worker is not None:
                store.commentary_worker.close()
```

`app.py` has no module logger; add `log = logging.getLogger(__name__)` and the
`logging` import at the top.

`current()` gains the idle case:

```python
    def current() -> Snapshot:
        captured = store.snapshot
        if captured is None or captured.state is None:
            if not store.active:
                raise HTTPException(
                    status_code=503,
                    detail="cannot tell which game is running; pick one from the header")
            raise HTTPException(status_code=503, detail="state not loaded yet")
        return captured
```

The two endpoints:

```python
    @app.get("/api/game")
    def api_game() -> dict:
        return game_to_dict(selector.resolve() if supervise_selection else resolution)

    @app.post("/api/game", response_model=None)
    def api_set_game(body: dict = Body(...)) -> dict:
        """Pin the session to one game, or return to detection.

        The override wins immediately rather than at the next poll: the player has just
        told the advisor which game they are looking at, and a dashboard that keeps
        showing the other one for a second is a dashboard that was wrong on purpose.
        """
        choice = str(body.get("game", ""))
        try:
            if choice == AUTO:
                selector.unpin()
            else:
                selector.pin(choice)
        except UnknownGame as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if activate(selector.resolve()):
            store.rebuild()
        return game_to_dict(resolution)
```

Finally, thread the game dict into the two responses that carry status:

```python
    def game_now() -> dict:
        return game_to_dict(resolution)

    @app.get("/api/status")
    def api_status(oracle: int = 1) -> dict:
        return status_to_dict(current(), bool(oracle), game=game_now())
```

and in `api_briefing`, pass `game=game_now()` to `briefing_to_dict`.

Add the imports: `Resolution`, `GameSelector`, `AUTO` from
`civ_advisor.games.selection`; `UnknownGame` from `civ_advisor.games.registry`;
`archive_root_for`, `DEFAULT_ROOT` from `civ_advisor.archive`;
`store_path_for` from `civ_advisor.context_store`; `game_to_dict` from
`.serialize`.

- [ ] **Step 5: Add `auto` to the CLI**

In `civ_advisor/cli.py`, replace the profile resolution from Task 1 Step 3:

```python
    game = args.game or AUTO
    logs_dirs: dict[str, Path] = {}
    if game == AUTO:
        profile = None
        logs_dir = None
    else:
        try:
            profile = get_profile(game)
        except UnknownGame as exc:
            print(str(exc), file=sys.stderr)
            return 2
        logs_dir = args.logs_dir or profile.default_logs_dir
        if not logs_dir.is_dir():
            print(f"{profile.display_name} log directory not found: {logs_dir}\n"
                  "Start the game once so it creates the folder, or pass --logs-dir <path>.",
                  file=sys.stderr)
            return 2
        logs_dirs[profile.id] = logs_dir
    selector = GameSelector(pinned=None if game == AUTO else game, logs_dirs=logs_dirs)
```

and update the `--game` help:

```python
    parser.add_argument("--game", default=None, choices=[*profile_ids(), AUTO],
                        help="which game to advise on, or 'auto' to detect it each poll "
                             "(default: auto; required with --logs-dir)")
```

The storage defaults from Task 5 Step 4 move behind the same branch — with
`auto` there is no game yet, so pass `storage_base` and let `create_app` derive
the per-game paths when it activates one:

`--context-file` and `--no-context-file` both mean "one file, whatever the
game", so they build the store here; with neither, `create_app` derives the
per-game path as the active game changes.

```python
    fixed_notes = args.no_context_file or args.context_file is not None
    store_path = (Path(tempfile.mkdtemp(prefix="civ-context-")) / "player-context.json"
                  if args.no_context_file else args.context_file)
    app = create_app(logs_dir, args.poll_interval,
                     archive_root=args.archive_dir,
                     archiving=not args.no_archive,
                     commentary_worker=worker,
                     player_store=PersistentContextStore(path=store_path) if fixed_notes else None,
                     profile=profile, selector=selector,
                     storage_base=DEFAULT_ROOT)
    # Task 5's notice, now against whichever game is pinned; with --game auto there is
    # no game yet and nothing is claimed about where a user's old data belongs.
    if profile is not None:
        _report_legacy_data(
            None if args.no_archive else (args.archive_dir or archive_root_for(profile.id)),
            store_path or store_path_for(profile.id))
```

Banner:

```python
    which = "detecting the game each poll" if profile is None else \
        f"{profile.display_name}, reading {logs_dir}"
    print(f"Civ Advisor -> http://{args.host}:{args.port}  ({which}; {where}; {llm}; {notes})")
```

`--archive-dir`, when given, is one directory for every game, matching
`--context-file`. `--no-archive` reaches `create_app` as `archiving=False`
rather than as `archive_root=None` — see Step 4 for why the two are kept apart.

`notes` in the banner is now `"notes off"`, the explicit path, or
`"notes under <DEFAULT_ROOT>/<game>"` when `create_app` derives it.

- [ ] **Step 6: Run the full suite**

```bash
uv run pytest -q 2>&1 | tail -3
```

Expected: Task 6's count **plus 8**, zero failures. Every existing
`create_app(...)` call in `tests/test_api.py` passes no selector and must behave
exactly as before — a failure there means the `selector is None` branch is not
equivalent to the old code path.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "Make the game a runtime property

The app re-resolves the selection every poll, swaps the store and the watcher
when it changes, and publishes game_changed. An override applies immediately
rather than at the next poll. With no selector configured the app behaves
exactly as before: one game, no detection."
```

---

### Task 8: Coverage and capabilities that are honest about a second game

Two defects surface as soon as Civ VI reaches the UI. `store.DOMAINS` is Civ
VII's file list, so a Civ VI game reports eleven domains "unavailable" — an
alarm about files that game never writes. And `capability_report` says *whether*
a capability is supported but not *why not*, so the UI can only omit a panel,
which is indistinguishable from the panel being quiet.

This task also settles **the question phase 2a deferred**: how to surface "N
build-queue rows could not be attributed to a player".

**Decision, and the reasoning.** It does **not** become an `Insight`. Phase 2a
was right that `Insight.provenance` is a two-value FAIR/ORACLE contract about
*how trustworthy a source is*, and a row count is not a claim about source
trust. But it does not stay out either, because silently dropping a quarter of
a build queue is exactly the kind of quiet incompleteness this project refuses.
It belongs on `DomainCoverage`, which already exists to say how well a
domain's files covered the turn, and which already distinguishes "empty" from
"stale" from "unavailable". It gains one field, `unattributed: int | None`, and
the header renders it as a sentence: *"Settlement build queues: 12 of 807 rows
could not be attributed to a player — they are excluded, not assigned to you."*
`None` means the domain does not have the concept, which is the Civ VII case.

**Files:**
- Modify: `civ_advisor/games/base.py` (`unsupported` reasons on `GameProfile`)
- Modify: `civ_advisor/games/civ6/__init__.py`, `civ7/__init__.py` (the reasons)
- Modify: `civ_advisor/store.py` (`DOMAINS` filtered by the profile; `unattributed`)
- Modify: `civ_advisor/api/serialize.py` (`capability_report` shape)
- Modify: `civ_advisor/web/briefing.js` (`coverageLines`)
- Test: `tests/test_store.py`, `tests/test_profile_conformance.py`, `tests/test_civ6_advisors.py`, `tests/test_web_briefing.py`

**Interfaces:**
- Produces:
  - `GameProfile.unsupported: tuple[tuple[Capability, str], ...] = ()` and `GameProfile.reason(capability) -> str | None`.
  - `capability_report(profile) -> dict[str, dict]` — `{"happiness": {"supported": False, "reason": "Civ VI writes no amenities log..."}}`. **This changes the shape**, and with it three assertions in `tests/test_civ6_advisors.py::test_the_api_reports_which_capabilities_are_unavailable`. Legitimate: that test is phase 2a's own, the function has no other consumer yet, and a bare `False` is precisely the "silently vanishing" outcome this task exists to prevent.
  - `DomainCoverage.unattributed: int | None`
  - `Store._coverage` skips a domain none of whose files the profile declares.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_store.py`:

```python
def test_a_domain_this_game_never_writes_is_not_reported_as_broken(civ6_dir):
    """Civ VI has no Player_Happiness.csv. Reporting it 'unavailable' would be an alarm
    about a file that does not exist by design -- exactly the distinction spec 9 draws."""
    captured = Store(civ6_dir, profile=CIV6).rebuild()
    names = {c.name for c in captured.coverage}
    assert "happiness" not in names and "treasury" not in names
    assert "empire" in names and "production" in names


def test_civ7_coverage_is_unchanged(fixture_dir):
    captured = Store(fixture_dir, profile=CIV7).rebuild()
    assert len(captured.coverage) == len(DOMAINS)


def test_unattributed_build_queue_rows_are_counted_not_hidden(civ6_dir):
    """Civ VI's City_BuildQueue.csv has no Player column; a row whose city has no owner
    in the join is attributed to nobody. The count must be visible, because a silently
    shorter queue reads as a quieter game."""
    captured = Store(civ6_dir, profile=CIV6).rebuild()
    production = captured.domain("production")
    assert production is not None and production.unattributed is not None
    assert production.unattributed >= 0


def test_civ7_reports_no_attribution_gap_concept(fixture_dir):
    captured = Store(fixture_dir, profile=CIV7).rebuild()
    assert captured.domain("production").unattributed is None
```

Append to `tests/test_profile_conformance.py` (it already parametrizes over
`profile_ids()`; reuse that import rather than adding a second one):

```python
@pytest.mark.parametrize("game_id", profile_ids())
def test_every_unsupported_capability_carries_a_reason(game_id):
    """A capability that is merely absent from the set tells the player nothing. The
    profile is the source of truth for WHY, and this is what stops the two drifting."""
    from civ_advisor.games.base import Capability
    from civ_advisor.games.registry import get_profile

    profile = get_profile(game_id)
    for capability in Capability:
        if profile.supports(capability):
            assert profile.reason(capability) is None, \
                f"{game_id} declares {capability.value} supported AND gives a reason it is not"
        else:
            assert profile.reason(capability), \
                f"{game_id} does not support {capability.value} and does not say why"
```

Replace the three assertions in
`tests/test_civ6_advisors.py::test_the_api_reports_which_capabilities_are_unavailable`:

```python
    report = capability_report(CIV6)
    assert report["victory_paths"]["supported"] is False
    assert "victory" in report["victory_paths"]["reason"].lower()
    assert report["happiness"]["supported"] is False and report["happiness"]["reason"]
    assert report["faith"] == {"supported": True, "reason": None}
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_store.py tests/test_profile_conformance.py tests/test_civ6_advisors.py -q 2>&1 | tail -5
```

Expected: `AttributeError: 'GameProfile' object has no attribute 'reason'`.

- [ ] **Step 3: Let a profile say why it cannot**

In `civ_advisor/games/base.py`, add to `GameProfile`:

```python
    unsupported: tuple[tuple[Capability, str], ...] = ()

    def reason(self, capability: Capability) -> str | None:
        """Why this game cannot support `capability`, or None when it can.

        Required for every capability the profile does not declare: "not available" with
        no reason is indistinguishable from a panel that happens to be empty, and the
        two mean opposite things to a player deciding what to do this turn.
        """
        if self.supports(capability):
            return None
        return next((why for cap, why in self.unsupported if cap is capability), None)
```

In `civ_advisor/games/civ6/__init__.py`, add to `CIV6`:

```python
    unsupported=(
        (Capability.VICTORY_PATHS,
         "Civ VI's AI_Victories.csv records era and posture strategies "
         "(STRATEGY_DARKAGE, STRATEGY_EARLY_EXPLORATION), not which victory a rival is "
         "pursuing. Reading them as victory paths would assert a pursuit the log does "
         "not state."),
        (Capability.HAPPINESS,
         "Civ VI writes no amenities log. DynamicEmpires.csv supplies the golden-age "
         "flag; the happiness numbers have no substitute."),
        (Capability.MAINTENANCE,
         "Civ VI logs a gold balance but no maintenance breakdown, so net gold per turn "
         "cannot be computed."),
        (Capability.PEACE_DEALS,
         "Civ VI has no DiplomacyDeals.log, so a signed peace treaty is not observable "
         "and a war alert cannot be cleared by one."),
        (Capability.COMBAT_ODDS,
         "Civ VI's AI_Operation_Eval.csv has no Odds column, so the AI's own combat odds "
         "-- the basis of bounded combat prediction -- do not exist."),
        (Capability.SETTLEMENT_CAP, "Civ VI has no settlement cap."),
        (Capability.URBAN_RURAL_SPLIT, "Civ VI does not split population urban/rural."),
        (Capability.TOURISM,
         "Tourism is in Player_Stats_2.csv, for which this build has no reader yet."),
        (Capability.DIPLOMATIC_FAVOR,
         "Diplomatic favor is in Player_Stats_2.csv, for which this build has no reader yet."),
    ),
```

In `civ_advisor/games/civ7/__init__.py`, add the two Civ VII does not support:

```python
    unsupported=(
        (Capability.FAITH, "Civ VII has no Faith yield."),
        (Capability.CIVICS, "Civ VII tracks Legacy Paths rather than a civics count."),
        (Capability.TOURISM, "Civ VII's Player_Stats.csv has no Tourism column."),
        (Capability.DIPLOMATIC_FAVOR,
         "Civ VII's Player_Stats.csv has no Diplomatic Favor column."),
    ),
```

Check `CIV7.capabilities` before writing this: the conformance test requires a
reason for **exactly** the capabilities it does not declare, so read the set at
`civ_advisor/games/civ7/__init__.py:58-64` and cover its complement.

- [ ] **Step 4: Make coverage follow the profile**

In `civ_advisor/store.py`, add the field to `DomainCoverage` (after `errors`,
with a default so nothing else needs changing):

```python
    unattributed: int | None = None
```

Give `DOMAINS` a seventh element: an optional counter, `None` for every domain
that has no such concept.

```python
def _unattributed_queue_rows(state: GameState) -> int:
    """Build-queue rows with no owner. Civ VI recovers ownership by joining City name
    against AI_CityBuild.csv (spec 3.2); a city absent from the join is attributed to
    nobody rather than defaulted to the human."""
    return sum(1 for row in state.build_queue if row.player is None)
```

`GameState`'s field name for the queue rows differs from `RawLogs`'; confirm it
with `grep -n 'build_queue' civ_advisor/state/models.py` and use the real one.
If the canonical state discards unowned rows before this point, count them in
`build_state` instead and carry the number on `GameState`; do not infer it from
a row-count difference, which would silently absorb a parse failure too.

Then filter by what the profile declares, in `_coverage`:

```python
def _coverage(state: GameState, analysis_turn: int,
              declared: frozenset[str]) -> tuple[DomainCoverage, ...]:
    out = []
    for name, label, required, turn_scoped, names, counter in DOMAINS:
        names = tuple(n for n in names if n in declared)
        if not names:
            # This game declares none of the domain's files. Absent by design is not
            # missing, and reporting it would be an alarm about a file that cannot exist.
            continue
        ...
        out.append(DomainCoverage(..., unattributed=None if counter is None else counter(state)))
```

and in `_capture_locked`:

```python
            coverage=_coverage(state, state.complete_through_turn,
                               frozenset(self.profile.log_files)),
```

- [ ] **Step 5: Reshape `capability_report` and render the new lines**

In `civ_advisor/api/serialize.py`:

```python
def capability_report(profile: GameProfile) -> dict[str, dict]:
    """Every capability this build models, whether this game supports it, and why not.

    Exhaustive on purpose, and the reason ships with the answer: the UI must be able to
    say "Civ VI's logs do not record which victory a rival is pursuing" rather than
    quietly rendering one panel fewer, which is indistinguishable from a quiet game.
    """
    return {
        c.value: {"supported": profile.supports(c), "reason": profile.reason(c)}
        for c in Capability
    }
```

In `civ_advisor/web/briefing.js`, add one branch to `coverageLines`, before the
`status === "ok"` early return so an otherwise-healthy domain still reports it:

```js
    (coverage || []).forEach(function (c) {
      if (c.unattributed) {
        lines.push({
          cls: "file-note",
          text: c.label + ": " + c.unattributed + " row"
            + (c.unattributed === 1 ? "" : "s") + " could not be attributed to a player"
            + " — they are excluded, not assigned to you",
        });
      }
      if (c.status === "ok") return;
      ...
```

Add a test to `tests/test_web_briefing.py`:

```python
def test_unattributed_rows_are_reported_even_when_the_domain_is_healthy():
    lines = run_js(
        'return B.coverageLines([{name: "production", label: "Settlement build queues",'
        ' status: "ok", required: false, files: ["City_BuildQueue.csv"], missing: [],'
        ' rows: 807, errors: [], unattributed: 12}]);'
    )
    assert len(lines) == 1
    assert "12 rows could not be attributed" in lines[0]["text"]
    assert "not assigned to you" in lines[0]["text"]
```

- [ ] **Step 6: Run the full suite**

```bash
uv run pytest -q 2>&1 | tail -3
```

Expected: Task 7's count **plus 7** (4 store, 2 from the parametrized conformance test, 1 browser-logic), zero failures. The three rewritten `capability_report` assertions add no test.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "Say why a capability is absent, and count what could not be attributed

A domain a game never writes is no longer reported as broken, every
unsupported capability carries the reason it is unsupported, and Civ VI's
unattributable build-queue rows are counted on the coverage record rather than
forced into Insight.provenance, which is a source-trust contract and not a
data-completeness one."
```

---

### Task 9: The header control

**Files:**
- Modify: `civ_advisor/web/index.html` (the control)
- Modify: `civ_advisor/web/app.js` (`renderGame`, the change handler, `game_changed`)
- Modify: `civ_advisor/web/style.css`
- Test: `tests/browser/test_game_control.py` (new, opt-in)

**Interfaces:**
- Consumes: `status.game` (Task 7), `capability_report` (Task 8).
- Produces: `#game-select`, `#game-mode` in the masthead.

- [ ] **Step 1: Add the control to `index.html`**

Inside `header.masthead > .wrap`, directly above `<p class="status-line">`:

```html
    <p class="game-line">
      <label class="game-switch" for="game-select">Game
        <select id="game-select">
          <option value="auto">Auto — detect from the logs</option>
        </select>
      </label>
      <span class="game-mode" id="game-mode"></span>
    </p>
```

The per-game options are appended by `renderGame` from `status.game.games`, so
a third profile would appear without an HTML change.

- [ ] **Step 2: Render and drive it in `app.js`**

Add to the `state` object: `game: null, gameBusy: false`. In `refresh()`, after
`state.status = status;`, add `state.game = status.game;`.

```js
  /* Which game, and how that was decided. The mode is stated in words rather than left
     to be inferred from which option is selected: a pinned choice that detection
     contradicts is the one case where the numbers on screen may come from a game the
     player is not looking at, and they have to be told rather than left to find out. */
  const DETECTION_WORDS = {
    detected: (g) => `detection says ${g}`,
    all_stale: () => "nothing written recently — detection cannot tell",
    no_logs_dir: () => "no game's log folder found — detection cannot tell",
    ambiguous: () => "two games wrote at the same moment — detection cannot tell",
  };

  function renderGame() {
    const game = state.game;
    const select = $("#game-select");
    const mode = $("#game-mode");
    if (!game) { mode.textContent = ""; return; }
    const names = {};
    game.games.forEach((g) => { names[g.id] = g.display_name; });
    const wanted = ["auto"].concat(game.games.map((g) => g.id)).join("|");
    if (select.dataset.built !== wanted) {
      select.replaceChildren(...[el("option", null, "Auto — detect from the logs")]
        .concat(game.games.map((g) => el("option", null, g.display_name))));
      select.children[0].value = "auto";
      game.games.forEach((g, i) => { select.children[i + 1].value = g.id; });
      select.dataset.built = wanted;
    }
    select.value = game.mode === "pinned" ? game.pinned : "auto";
    select.disabled = state.gameBusy;

    const detected = game.detection.game ? names[game.detection.game] : null;
    const said = DETECTION_WORDS[game.detection.reason] || (() => game.detection.reason);
    if (game.mode === "pinned" && game.disagrees) {
      mode.textContent = `pinned to ${names[game.pinned]} — ${said(detected)}`;
      mode.className = "game-mode game-disagrees";
    } else if (game.mode === "pinned") {
      mode.textContent = `pinned to ${names[game.pinned]}`;
      mode.className = "game-mode";
    } else if (game.active) {
      mode.textContent = `following detection — ${names[game.active.id]}`;
      mode.className = "game-mode";
    } else {
      mode.textContent = `${said(detected)} — pick a game to start`;
      mode.className = "game-mode game-disagrees";
    }
  }

  $("#game-select").addEventListener("change", async (e) => {
    const chosen = e.target.value;
    state.gameBusy = true;
    renderGame();
    try {
      const response = await fetch("/api/game", {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ game: chosen }),
      });
      if (response.ok) state.game = await response.json();
    } catch (_) { /* the refresh below reports the real state either way */ }
    state.gameBusy = false;
    /* Everything on screen was computed under the previous game. Clear it before the
       new brief lands rather than leaving one game's advice under another's name. */
    state.data = null; state.insights = []; state.intel = []; state.decisions = null;
    state.changes = null; state.tactical = null; state.commentary = null;
    render();
    refresh();
  });
```

Call `renderGame()` from `paint()` — both in the early-return branch and the
main one, beside `renderStatus()`.

Handle the server-pushed switch in the SSE handler, beside `state_changed`:

```js
      if (event.type === "game_changed") {
        state.data = null; state.insights = []; state.intel = []; state.decisions = null;
        state.changes = null; state.tactical = null; state.commentary = null;
        render();
      }
```

Find the existing `state_changed` handler with `grep -n 'state_changed'
civ_advisor/web/app.js` and add the branch alongside it, in the same style.

- [ ] **Step 3: Style it**

In `civ_advisor/web/style.css`, beside the existing `.status-line` rules:

```css
.game-line { display: flex; align-items: baseline; gap: .6rem; flex-wrap: wrap; margin: .3rem 0; }
.game-switch { font-size: .85rem; opacity: .85; }
.game-switch select { margin-left: .35rem; font: inherit; }
.game-mode { font-size: .8rem; opacity: .7; }
.game-disagrees { opacity: 1; font-weight: 600; }
```

Reuse the palette variables the file already defines for `.file-warn` rather
than introducing a colour; `grep -n 'file-warn' civ_advisor/web/style.css` for
the existing rule and match it.

- [ ] **Step 4: Add one browser test**

Create `tests/browser/test_game_control.py`, following the fixtures in
`tests/browser/conftest.py`:

```python
def test_the_header_names_the_game_and_the_mode(page, brief_server):
    page.goto(brief_server)
    page.wait_for_selector("#game-mode:not(:empty)")
    assert "Civilization VII" in page.text_content("#game-mode")
    assert page.input_value("#game-select") == "civ7"
```

It runs only with the opt-in suite:

```bash
uv sync --group browser && uv run playwright install chromium
uv run pytest tests/browser -p playwright.pytest_plugin
```

The `brief_server` fixture passes no selector today; it will need
`profile=CIV7` from Task 1. Check `tests/browser/conftest.py` for the real
fixture name before writing the test.

- [ ] **Step 5: Verify by hand**

```bash
uv run civ-advisor --game auto --no-llm --no-context-file --no-archive
```

Expected: the header shows the Game control; with neither game recently played
it says detection cannot tell and offers the list. Picking a game repaints the
whole dashboard rather than leaving the previous game's cards under the new
name.

- [ ] **Step 6: Run the full suite and commit**

```bash
uv run pytest -q 2>&1 | tail -3
```

Expected: Task 8's count unchanged (the browser test is excluded by `addopts`).

```bash
git add -A
git commit -m "Put the game control in the header

The header says which mode is in force, and when pinned, whether detection
disagrees. Switching clears the dashboard before the new brief lands rather
than leaving one game's advice under another's name."
```

---

### Task 10: Panels that a game cannot fill say why

`capability_report` reaches the browser in `status.game.active.capabilities`
(Task 8). Nothing renders it yet. A Civ VI game must show fewer panels, and
each absent one must state its reason.

**Files:**
- Modify: `civ_advisor/web/briefing.js` (`capabilityNotices`)
- Modify: `civ_advisor/web/app.js` (render the notices; suppress the panels)
- Test: `tests/test_web_briefing.py`

**Interfaces:**
- Consumes: `status.game.active.capabilities`.
- Produces: `Civ7Briefing.capabilityNotices(capabilities, panel) -> [{capability, reason}]`, and a `PANEL_CAPABILITIES` map naming which capabilities each tab depends on.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_web_briefing.py`:

```python
def test_an_unsupported_panel_is_explained_rather_than_omitted():
    """An empty panel and an unsupported panel mean opposite things. The player has to be
    able to tell 'no rival is chasing a victory' from 'this game does not record it'."""
    lines = run_js(
        'return B.capabilityNotices({victory_paths: {supported: false,'
        ' reason: "Civ VI records era strategies, not victory paths."},'
        ' happiness: {supported: true, reason: null}}, "victory");'
    )
    assert len(lines) == 1
    assert lines[0]["reason"] == "Civ VI records era strategies, not victory paths."


def test_a_supported_panel_gets_no_notice():
    lines = run_js(
        'return B.capabilityNotices({victory_paths: {supported: true, reason: null}},'
        ' "victory");'
    )
    assert lines == []


def test_a_panel_with_no_declared_capabilities_is_never_suppressed():
    """Threats and Intel run off signals both games have. A panel not in the map must
    render normally rather than silently disappearing on an unknown game."""
    assert run_js('return B.capabilityNotices({}, "intel");') == []
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
uv run pytest tests/test_web_briefing.py -q 2>&1 | tail -3
```

Expected: `TypeError: B.capabilityNotices is not a function`.

- [ ] **Step 3: Implement `capabilityNotices` in `briefing.js`**

```js
  /* Which capabilities each panel needs to be meaningful. A panel missing from this map
     depends on nothing game-specific and always renders: silence must be earned by a
     declaration, never by a lookup failing. */
  var PANEL_CAPABILITIES = {
    victory: ["victory_paths"],
    economy: ["maintenance", "happiness"],
  };

  function capabilityNotices(capabilities, panel) {
    var needed = PANEL_CAPABILITIES[panel] || [];
    var out = [];
    needed.forEach(function (name) {
      var held = (capabilities || {})[name];
      if (!held || held.supported) return;
      out.push({ capability: name, reason: held.reason || "not available in this game" });
    });
    return out;
  }
```

Export both from the module's `api` object beside `coverageLines`.

- [ ] **Step 4: Render the notices in `app.js`**

Add a helper and call it at the top of each panel's render function:

```js
  /* An unsupported panel keeps its tab and states its reason. Removing the tab would
     make the dashboard's shape depend on the game in a way the player cannot ask about;
     an empty panel would read as "nothing is happening", which is a different claim. */
  function capabilityBlock(panel) {
    const caps = state.game && state.game.active ? state.game.active.capabilities : null;
    const notices = B.capabilityNotices(caps, panel);
    if (!notices.length) return null;
    const box = el("div", "cap-absent");
    box.append(el("p", "cap-absent-head", "Not available in this game"));
    notices.forEach((n) => box.append(el("p", "cap-absent-why", n.reason)));
    return box;
  }
```

In the victory/strategy and economy render functions, start with:

```js
    const absent = capabilityBlock("victory");   // "economy" in the economy renderer
    if (absent) { $("#victory").replaceChildren(absent); return; }
```

Use the real container selectors; find them with
`grep -n 'id="victory"\|id="economy"' civ_advisor/web/index.html`.

Style, beside the `.file-note` rules:

```css
.cap-absent { padding: .9rem 1rem; border-left: 3px solid currentColor; opacity: .8; }
.cap-absent-head { font-weight: 600; margin: 0 0 .3rem; }
.cap-absent-why { margin: .2rem 0; font-size: .9rem; }
```

- [ ] **Step 5: Verify by hand against a real Civ VI directory**

```bash
uv run civ-advisor --game civ6 --no-llm --no-context-file --no-archive
```

Expected: the Strategy tab says Civ VI's `AI_Victories.csv` records era
strategies rather than victory paths; the Economy tab names the missing
maintenance breakdown and amenities. Neither tab is missing, and neither is
blank.

- [ ] **Step 6: Run the full suite and commit**

```bash
uv run pytest -q 2>&1 | tail -3
```

Expected: Task 9's count **plus 3**, zero failures.

```bash
git add -A
git commit -m "Explain the panels this game's logs cannot fill

An empty panel and an unsupported panel mean opposite things. Each keeps its
tab and states the reason from the profile's own declaration."
```

---

### Task 11: Record what phase 2b established

**Files:**
- Modify: `README.md`
- Modify: `docs/architecture/log-capability-matrix.md`
- Modify: `docs/superpowers/specs/2026-09-12-multi-game-advisor-design.md` (status line)

- [ ] **Step 1: Update the README**

Replace the Options paragraph:

```markdown
Options: `--game auto|civ6|civ7` (default `auto`: the advisor detects which game
is being played from the games' own logs each poll, and you can override it from
the header at any time), `--logs-dir PATH` (requires `--game`, because a log
directory belongs to one game and the path does not say which), `--port`,
`--host`, `--poll-interval`, `--llm-model MODEL`, `--llm-timeout SECONDS`,
`--no-llm`, `--context-file PATH`, and `--no-context-file`.
```

Replace the archive paragraph's path with
`~/.civ-advisor/<game>/archive/<save-key>/<session>/`, and add:

```markdown
Storage is per game: Civilization VI and Civilization VII keep separate archives
and separate goals, acknowledgements and watchlists. An acknowledgement made in
one game is never offered in the other.

**Upgrading from an earlier version?** Your existing archive and notes are still
at `~/.civ7-advisor/`. Nothing has been moved or deleted. `civ-advisor archive
list` still shows them, labelled `pre-2b`, and the advisor prints the one-line
`mv` that would adopt them the first time it starts without them.
```

Add to the "what the header tells you" list: which game is being advised on,
whether that was pinned or detected, and — when pinned — whether detection
currently disagrees.

- [ ] **Step 2: Give the capability matrix its Civ VI column**

In `docs/architecture/log-capability-matrix.md`, replace the phase-1 header
note with a Civ VI column, sourced from `CIV6.unsupported` so the document and
the code cannot drift: victory-path pursuit, amenities, maintenance and net
gold, peace deals, combat odds, settlement cap and the urban/rural split are
unavailable, each with the reason the profile gives. Faith and civics are
available in Civ VI and not in Civ VII.

- [ ] **Step 3: Mark the phase in the spec**

```markdown
**Status:** Phases 1, 2a and 2b implemented on `feature/multi-game-advisor`; phases 3–4 not yet planned
```

- [ ] **Step 4: Confirm the suite is green one last time**

```bash
uv run pytest -q 2>&1 | tail -3
```

Expected: 537 + 51 = 588 passed, zero failures — 3 from Task 1, 8 from Task 2,
8 from Task 3, 6 from Task 4, 4 from Task 5, 4 from Task 6, 8 from Task 7, 7
from Task 8 and 3 from Task 10. Task 9's browser test is excluded by `addopts`,
and Task 8 rewrote an existing test rather than adding one. Treat the count as a
check that nothing was deleted, not as a target to hit: if it differs, find out
which test changed and why before continuing.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "Record phase 2b of the multi-game work as landed"
```

---

## Done when

- `uv run pytest` is green, with every pre-existing assertion intact except the
  three in `tests/test_civ6_advisors.py::test_the_api_reports_which_capabilities_are_unavailable`,
  which Task 8 rewrites for a stated reason.
- `uv run civ-advisor` (no flags) starts in detection, and the header says which
  game it found or that it cannot tell.
- Starting Civilization VI while the advisor is running switches the dashboard
  to Civ VI within one poll, with a new session id, an empty "since last turn",
  and no acknowledgement carried across.
- Choosing Civilization VII from the header pins it, and the header says
  detection disagrees while Civ VI is the one writing logs.
- `uv run civ-advisor --logs-dir /tmp/x` exits 2 naming `--game` and both games.
- `~/.civ7-advisor/` is untouched by every path above, and
  `civ-advisor archive list` still shows what is in it.
- No file under `civ_advisor/advisors/` or `civ_advisor/decisions/` is modified
  by this phase except `changes.py`'s new `History.forget()`. Anything more
  means the seam is in the wrong place — stop and report it.
