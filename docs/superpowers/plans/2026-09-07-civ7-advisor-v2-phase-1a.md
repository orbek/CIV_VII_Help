# Civ VII Advisor v2 — Phase 1a (Wider State) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire five more Civ VII logs into the advisor — production queues, realized combat, gossip, diplomatic actions and deals — so the dashboard gains a production advisor, an honest combat record, peace detection, an Intel feed, and an archiver that stops the game's launch-time log wipe from losing games.

**Architecture:** Same layering as v1: `ingest/` (new readers in `production.py`, `events.py`, `textlogs.py`) → `state/` (`GameState` gains five collections, a leader-name resolver and `peace_turns`) → `advisors/` (new `production.py` and `intel.py`; `threat.py` gains a combat record and peace awareness) → `store.py` (archiver hook) → `api/` (`/api/intel`, server-side oracle gating for the new surfaces) → `web/` (Intel tab, production section). Per-file error isolation means each new log degrades exactly one feature.

**Tech Stack:** Python 3.12, `uv`, FastAPI, uvicorn; pytest + httpx. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-07-civ7-advisor-v2-design.md` — §2 (corrections), §3.1 (the five files and their hazards), §3 provenance rule, §4.1 (advisors), §5 (architecture), §6 (errors, wipe, archiver), §7 (testing). The v1 spec `2026-09-07-civ7-turn-advisor-design.md` still governs everything this plan does not touch.

## Global Constraints

- Python `>=3.12`; run everything through `uv run …`. Runtime deps are exactly `fastapi` and `uvicorn`; dev deps `pytest` and `httpx`. **No new dependencies in this phase.**
- **Read-only with respect to Civ VII's directories.** v2 writes to exactly one place of its own: the archive root (default `~/.civ7-advisor/archive/`), and only via `civ7_advisor/archive.py`. Nothing under the Civ VII tree is ever created, modified, renamed or deleted. Never modify `tests/fixtures/logs_82turns/`.
- Layering: `ingest/*` import nothing from `state`/`advisors`/`api`; `state/*` may import `ingest`; `advisors/*` import only `civ7_advisor.state.models`, `civ7_advisor.advisors.*` siblings and stdlib; `api/` is the only HTTP-aware layer; `archive.py` and `store.py` sit above all of them.
- Provenance rule for event logs (spec §3): an event the human took part in — a combat they fought, a deal they signed, a diplomatic action they initiated or received — is `FAIR`; the same event between two rivals is `ORACLE`; gossip is `FAIR` regardless of parties; a rival's production queue is `ORACLE`, the human's own is `FAIR`.
- Every `Insight` has a stable `id`, non-empty `title`/`recommendation`/`why`, and a `provenance`. Every tunable is a module-level UPPER_CASE constant with a one-line comment.
- Player 0 is the human (`GameState.HUMAN`); `complete_through_turn = latest_turn - 1`.
- **The v2 fixture does not exist yet.** The live logs were wiped when the game relaunched (spec §2). Tasks 1–10 use synthetic rows built from the exact sample lines captured before the wipe; Task 11 snapshots the new fixture from the running game once it has ≥ 40 turns and pins every "⚠ verify" shape. Tasks 1–10 must not assume any fixture-derived number for the five new files.
- Existing tests that assert "every file in `state.files` is ok" against the v1 fixture must be narrowed to the seven v1 files (Task 1 does this), because the v1 fixture will legitimately lack the five new logs.
- Commit after every task with the message given in the task. If git complains about identity: `git -c user.name="Carlos Barbosa" -c user.email="cbarbosa@harvardmaint.com" commit -m "..."`.

---

## File structure

```
civ7_advisor/
  ingest/
    production.py      NEW  BuildQueueRow, read_build_queue           (Task 1)
    events.py          NEW  CombatRow/Combatant, GossipRow, DiplomacySummaryRow + readers (Tasks 2–3)
    textlogs.py        NEW  DealItem, read_deals — the non-CSV DiplomacyDeals.log (Task 4)
    load.py            MOD  five READERS entries + RawLogs fields       (Tasks 1–4)
  state/
    names.py           NEW  NameResolver: leader name / civ → player id (Task 5)
    models.py          MOD  GameState gains build_queues, combats, gossip, diplomacy_events,
                            deals, peace_turns, names; peace_between()  (Task 5)
    build.py           MOD  carry the new rows; fold peace deals; build the resolver (Task 5)
  advisors/
    production.py      NEW  queues(), rival_military_share(), advise()  (Task 6)
    threat.py          MOD  RivalThreat gains combat + peace fields; combat_record + peace insights (Task 7)
    intel.py           NEW  IntelEvent, feed()                          (Task 8)
    checklist.py       MOD  ADVISOR_ORDER["production"]                 (Task 6)
    __init__.py        MOD  ADVISORS += production                      (Task 6)
  archive.py           NEW  game_key(), archive_logs()                  (Task 9)
  store.py             MOD  archive hook                                (Task 9)
  cli.py               MOD  --no-archive, --archive-dir, `archive list` (Task 9)
  api/
    serialize.py       MOD  production block; intel serialization       (Task 10)
    app.py             MOD  /api/intel, ?oracle= gating, archive_root   (Tasks 9–10)
  web/
    index.html         MOD  Intel tab, production sections, wipe copy   (Task 10)
    app.js             MOD  intel fetch/render, production tables, peace cell (Task 10)
    style.css          MOD  intel rows                                  (Task 10)
README.md              MOD  Intel, production, archiver                 (Task 10)
tests/
  factories.py         MOD  builders for the five new row types         (Task 5)
  test_ingest_production.py  NEW (Task 1)     test_ingest_events.py  NEW (Tasks 2–3)
  test_ingest_textlogs.py    NEW (Task 4)     test_names.py          NEW (Task 5)
  test_state.py MOD (Task 5)  test_production_advisor.py NEW (Task 6)  test_threat.py MOD (Task 7)
  test_intel.py NEW (Task 8)  test_archive.py NEW (Task 9)  test_store.py MOD (Task 9)
  test_cli.py MOD (Task 9)    test_api.py MOD (Task 10)     test_checklist.py MOD (Task 6)
  test_ingest_load.py MOD (Task 1)
  fixtures/logs_v2/          NEW snapshot + FACTS.md                     (Task 11)
  test_fixture_v2.py         NEW fixture-pinned tests                    (Task 11)
```

---

### Task 1: `CityBuildQueue.csv` reader, wired into `load_logs`

**Files:**
- Create: `civ7_advisor/ingest/production.py`
- Modify: `civ7_advisor/ingest/load.py:10-25` (imports), `:39-48` (RawLogs), `:52-60` (READERS)
- Modify: `tests/test_ingest_load.py` (narrow the all-ok assertion), `tests/test_state.py::test_raw_rows_are_carried_through` (same)
- Test: `tests/test_ingest_production.py`

**Interfaces:**
- Consumes: `csvfile.read_table`, `expect_header`, `latest_game_segment`, `LogFormatError` (v1).
- Produces: `BuildQueueRow(turn: int, player: int, city: str, added: float, item: str, current: float, needed: float, overflow: float)` frozen, with property `turns_to_complete -> int | None`; `read_build_queue(path) -> list[BuildQueueRow]`; `RawLogs.build_queue: list[BuildQueueRow]`; `"CityBuildQueue.csv"` in `LOG_FILES`; test module constant `V1_FILES` (the seven v1 names) in `tests/test_ingest_load.py`.

- [ ] **Step 1: Write the failing tests**

`tests/test_ingest_production.py`:
```python
from pathlib import Path

import pytest

from civ7_advisor.ingest.csvfile import LogFormatError
from civ7_advisor.ingest.production import BuildQueueRow, read_build_queue

HEADER = "Game Turn, Player, City, Production Added, Current Item, Current Production, Production Needed, Overflow\n"
# Captured from the live game on 2026-09-07 (turn 82, the human's capital building a Brickyard).
LIVE_ROW = "82, 0, LOC_CITY_NAME_MAURYA1, 15.0, BUILDING_BRICKYARD, 47.5, 55, 0.0\n"


def _write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "CityBuildQueue.csv"
    p.write_text(HEADER + body)
    return p


def test_reads_the_live_row_verbatim(tmp_path: Path):
    rows = read_build_queue(_write(tmp_path, LIVE_ROW))
    assert rows == [BuildQueueRow(82, 0, "LOC_CITY_NAME_MAURYA1", 15.0, "BUILDING_BRICKYARD", 47.5, 55.0, 0.0)]


@pytest.mark.parametrize(
    "added,current,needed,expected",
    [(15.0, 47.5, 55.0, 1), (15.0, 40.0, 55.0, 1), (15.0, 39.9, 55.0, 2), (15.0, 55.0, 55.0, 0),
     (15.0, 60.0, 55.0, 0), (0.0, 10.0, 55.0, None)],
)
def test_turns_to_complete_rounds_up_and_handles_stalls(added, current, needed, expected):
    row = BuildQueueRow(1, 0, "LOC_CITY_NAME_X", added, "BUILDING_BRICKYARD", current, needed, 0.0)
    assert row.turns_to_complete == expected


def test_idle_city_has_no_completion_estimate():
    row = BuildQueueRow(1, 0, "LOC_CITY_NAME_X", 12.0, "", 0.0, 0.0, 0.0)
    assert row.turns_to_complete is None


def test_header_mismatch_raises(tmp_path: Path):
    p = tmp_path / "CityBuildQueue.csv"
    p.write_text("Game Turn, Player, City\n1, 0, X\n")
    with pytest.raises(LogFormatError, match="unexpected header"):
        read_build_queue(p)


def test_only_latest_game_is_returned(tmp_path: Path):
    body = ("1, 0, LOC_CITY_NAME_A, 5.0, UNIT_WARRIOR, 0.0, 30, 0.0\n"
            "2, 0, LOC_CITY_NAME_A, 5.0, UNIT_WARRIOR, 5.0, 30, 0.0\n"
            "1, 0, LOC_CITY_NAME_B, 6.0, UNIT_SCOUT, 0.0, 20, 0.0\n")
    rows = read_build_queue(_write(tmp_path, body))
    assert [r.city for r in rows] == ["LOC_CITY_NAME_B"]
```

Amend `tests/test_ingest_load.py` — add the module constant and narrow the two assertions:
```python
# The seven logs v1 shipped with; the v1 fixture has exactly these, so every newer log is
# legitimately "file not found" there.
V1_FILES = ["Player_Stats.csv", "Player_Treasury.csv", "Player_Happiness.csv", "AI_Victories.csv",
            "AI_DiplomaticActions.csv", "AI_Targets.csv", "Historian.csv"]
```
and in `test_load_logs_fixture_all_ok` replace `assert all(fs.ok for fs in raw.files.values())` with:
```python
    assert all(raw.files[name].ok for name in V1_FILES)
    assert set(V1_FILES) <= set(LOG_FILES)
    for name in set(LOG_FILES) - set(V1_FILES):
        assert raw.files[name].error == "file not found", name
```
Amend `tests/test_state.py::test_raw_rows_are_carried_through`: replace `assert set(fixture_state.files) and all(f.ok for f in fixture_state.files.values())` with
```python
    from tests.test_ingest_load import V1_FILES
    assert all(fixture_state.files[name].ok for name in V1_FILES)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_ingest_production.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'civ7_advisor.ingest.production'`.

- [ ] **Step 3: Write the reader**

`civ7_advisor/ingest/production.py`:
```python
"""Reader for CityBuildQueue.csv: what every player is producing, and how long it will take."""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from .csvfile import expect_header, latest_game_segment, read_table

BUILD_QUEUE_HEADER = [
    "Game Turn", "Player", "City", "Production Added", "Current Item",
    "Current Production", "Production Needed", "Overflow",
]


@dataclass(frozen=True)
class BuildQueueRow:
    turn: int
    player: int
    city: str        # LOC_CITY_NAME_* key exactly as logged
    added: float     # production added this turn
    item: str        # BUILDING_*, UNIT_*, ...; "" when the city is idle
    current: float
    needed: float
    overflow: float

    @property
    def turns_to_complete(self) -> int | None:
        """Whole turns until `needed` is reached at the current rate.

        None when the city is idle or adds no production (a stall we must not divide by).
        """
        if not self.item or self.added <= 0:
            return None
        remaining = self.needed - self.current
        return 0 if remaining <= 0 else math.ceil(remaining / self.added)


def read_build_queue(path: Path) -> list[BuildQueueRow]:
    table = read_table(path)
    expect_header(table, BUILD_QUEUE_HEADER)
    return [
        BuildQueueRow(int(r[0]), int(r[1]), r[2], float(r[3]), r[4], float(r[5]), float(r[6]), float(r[7]))
        for r in latest_game_segment(table.rows, turn_col=0)
    ]
```

- [ ] **Step 4: Wire it into `load_logs`**

In `civ7_advisor/ingest/load.py`: add `from .production import BuildQueueRow, read_build_queue` after the `.readers` import block; add `build_queue: list[BuildQueueRow] = field(default_factory=list)` to `RawLogs` immediately after `historian`; append `("CityBuildQueue.csv", "build_queue", read_build_queue),` to `READERS` after the Historian entry. Update the `load_logs` docstring's "all seven logs" to "every log in READERS".

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_ingest_production.py tests/test_ingest_load.py tests/test_state.py -q`
Expected: all pass (`test_load_logs_fixture_all_ok` now reports `CityBuildQueue.csv` as "file not found" on the v1 fixture, by design). Then `uv run pytest -q` — all pass, zero warnings.

- [ ] **Step 6: Commit**

```bash
git add civ7_advisor/ingest/production.py civ7_advisor/ingest/load.py tests/test_ingest_production.py tests/test_ingest_load.py tests/test_state.py
git commit -m "Add CityBuildQueue reader and narrow v1-fixture file assertions"
```

---

### Task 2: `CombatLog.csv` reader

**Files:**
- Create: `civ7_advisor/ingest/events.py`
- Modify: `civ7_advisor/ingest/load.py` (import, `RawLogs.combat`, READERS entry)
- Test: `tests/test_ingest_events.py`

**Interfaces:**
- Produces: `Combatant(unit_id: int | None, kind: str)` frozen; `CombatRow(turn, source_type, x, y, att_player, def_player, combat_type, attacker: Combatant, defender: Combatant, att_str, def_str, att_str_mod, def_str_mod, att_dmg, def_dmg, destroyed: str | None, heal_amount: int, att_health_raw: str, def_health_raw: str)` frozen, with methods `involves(player) -> bool`, `loser() -> int | None` (the player whose combatant `Destroyed` names; None when nothing died), `parties() -> frozenset[int]`; `read_combat_log(path)`; `RawLogs.combat`; `"CombatLog.csv"` in `LOG_FILES`.
- **Semantics deliberately NOT interpreted here:** whether `AttDmg` is damage dealt or taken, and the order inside `(a)b` health cells, could not be pinned from the single captured row. The reader stores those as raw ints/strings under the log's own names. Only `Destroyed` (unambiguous) drives win/loss. Task 11 pins the rest.

- [ ] **Step 1: Write the failing tests**

`tests/test_ingest_events.py`:
```python
from pathlib import Path

import pytest

from civ7_advisor.ingest.csvfile import LogFormatError
from civ7_advisor.ingest.events import Combatant, CombatRow, read_combat_log

COMBAT_HEADER = ("Turn, SourceType, Location, AttPlayer, DefPlayer, CombatType, Attacker, Defender, AttStr, DefStr, "
                 "AttStrMod, DefStrMod, AttDmg, DefDmg, Destroyed, HealAmount, attHealth, defHealth\n")
# Captured live 2026-09-07: the human's Warrior attacking Rizal's city centre and dying. Note the
# file uses NO space after commas, unlike every other Civ VII log.
LIVE_COMBAT = ("82,Unit vs Location,(63)(30),0,4,Melee,(14)UNIT_WARRIOR,(-1)LOC_DISTRICT_CITY_CENTER_NAME,"
               "20,30,-5,0,34,12,Attacker,0,(0)100,(8)100\n")


def _write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "CombatLog.csv"
    p.write_text(COMBAT_HEADER + body)
    return p


def test_reads_the_live_row_including_parenthesised_fields(tmp_path: Path):
    [row] = read_combat_log(_write(tmp_path, LIVE_COMBAT))
    assert (row.turn, row.source_type, row.x, row.y) == (82, "Unit vs Location", 63, 30)
    assert (row.att_player, row.def_player, row.combat_type) == (0, 4, "Melee")
    assert row.attacker == Combatant(14, "UNIT_WARRIOR")
    assert row.defender == Combatant(None, "LOC_DISTRICT_CITY_CENTER_NAME")
    assert (row.att_str, row.def_str, row.att_str_mod, row.def_str_mod) == (20, 30, -5, 0)
    assert (row.att_dmg, row.def_dmg, row.destroyed, row.heal_amount) == (34, 12, "Attacker", 0)
    assert (row.att_health_raw, row.def_health_raw) == ("(0)100", "(8)100")


def test_parties_involves_and_loser():
    row = read_combat_log_row_for_test()
    assert row.parties() == frozenset({0, 4})
    assert row.involves(0) and row.involves(4) and not row.involves(1)
    assert row.loser() == 0  # the attacker (player 0) was destroyed


def read_combat_log_row_for_test() -> CombatRow:
    return CombatRow(82, "Unit vs Location", 63, 30, 0, 4, "Melee", Combatant(14, "UNIT_WARRIOR"),
                     Combatant(None, "LOC_DISTRICT_CITY_CENTER_NAME"), 20, 30, -5, 0, 34, 12, "Attacker",
                     0, "(0)100", "(8)100")


@pytest.mark.parametrize("destroyed,expected", [("Defender", 4), ("", None)])
def test_loser_follows_the_destroyed_column(destroyed, expected):
    base = read_combat_log_row_for_test()
    row = CombatRow(**{**base.__dict__, "destroyed": destroyed or None})
    assert row.loser() == expected


def test_empty_destroyed_becomes_none(tmp_path: Path):
    body = LIVE_COMBAT.replace(",Attacker,", ",,")
    [row] = read_combat_log(_write(tmp_path, body))
    assert row.destroyed is None


def test_header_mismatch_raises(tmp_path: Path):
    p = tmp_path / "CombatLog.csv"
    p.write_text("Turn,Attacker\n1,x\n")
    with pytest.raises(LogFormatError, match="unexpected header"):
        read_combat_log(p)


def test_malformed_location_raises_log_format_error(tmp_path: Path):
    body = LIVE_COMBAT.replace("(63)(30)", "63:30")
    with pytest.raises(LogFormatError, match="Location"):
        read_combat_log(_write(tmp_path, body))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_ingest_events.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'civ7_advisor.ingest.events'`.

- [ ] **Step 3: Write the reader**

`civ7_advisor/ingest/events.py`:
```python
"""Readers for the event logs: combat, gossip and diplomatic actions.

These logs record things that happened between players. Whether an event is FAIR or ORACLE
is decided later (advisors/intel.py) by who took part; the readers only parse.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .csvfile import LogFormatError, expect_header, latest_game_segment, read_table

# --- CombatLog.csv ----------------------------------------------------------
# The one Civ VII log written without a space after each comma; read_table strips cells,
# so the same reader path handles it.

COMBAT_HEADER = [
    "Turn", "SourceType", "Location", "AttPlayer", "DefPlayer", "CombatType", "Attacker",
    "Defender", "AttStr", "DefStr", "AttStrMod", "DefStrMod", "AttDmg", "DefDmg", "Destroyed",
    "HealAmount", "attHealth", "defHealth",
]
_LOCATION = re.compile(r"^\((-?\d+)\)\((-?\d+)\)$")   # (63)(30)
_COMBATANT = re.compile(r"^\((-?\d+)\)(.+)$")        # (14)UNIT_WARRIOR or (-1)LOC_DISTRICT_...


@dataclass(frozen=True)
class Combatant:
    unit_id: int | None   # None for a district or plot, which the log tags (-1)
    kind: str             # UNIT_WARRIOR, LOC_DISTRICT_CITY_CENTER_NAME, ...


@dataclass(frozen=True)
class CombatRow:
    turn: int
    source_type: str      # e.g. "Unit vs Location"
    x: int
    y: int
    att_player: int
    def_player: int
    combat_type: str      # e.g. "Melee"
    attacker: Combatant
    defender: Combatant
    att_str: int
    def_str: int
    att_str_mod: int
    def_str_mod: int
    att_dmg: int          # raw; whether this is damage dealt or taken is pinned by the fixture task
    def_dmg: int          # raw; see above
    destroyed: str | None  # "Attacker" | "Defender" | None — the only field win/loss reads
    heal_amount: int
    att_health_raw: str   # "(a)b" exactly as logged; order of the two numbers pinned later
    def_health_raw: str

    def parties(self) -> frozenset[int]:
        return frozenset({self.att_player, self.def_player})

    def involves(self, player: int) -> bool:
        return player in self.parties()

    def loser(self) -> int | None:
        """The player whose combatant `Destroyed` names; None when nothing died."""
        if self.destroyed == "Attacker":
            return self.att_player
        if self.destroyed == "Defender":
            return self.def_player
        return None


def _combatant(cell: str, path: Path) -> Combatant:
    m = _COMBATANT.match(cell)
    if not m:
        raise LogFormatError(f"{path.name}: unexpected combatant cell {cell!r}")
    unit_id = int(m.group(1))
    return Combatant(None if unit_id < 0 else unit_id, m.group(2))


def read_combat_log(path: Path) -> list[CombatRow]:
    table = read_table(path)
    expect_header(table, COMBAT_HEADER)
    out: list[CombatRow] = []
    for r in latest_game_segment(table.rows, turn_col=0):
        loc = _LOCATION.match(r[2])
        if not loc:
            raise LogFormatError(f"{path.name}: unexpected Location cell {r[2]!r}")
        out.append(CombatRow(
            int(r[0]), r[1], int(loc.group(1)), int(loc.group(2)), int(r[3]), int(r[4]), r[5],
            _combatant(r[6], path), _combatant(r[7], path),
            int(r[8]), int(r[9]), int(r[10]), int(r[11]), int(r[12]), int(r[13]),
            r[14] or None, int(r[15]), r[16], r[17],
        ))
    return out
```

- [ ] **Step 4: Wire it into `load_logs`**

In `civ7_advisor/ingest/load.py`: add `from .events import CombatRow, read_combat_log`; add `combat: list[CombatRow] = field(default_factory=list)` to `RawLogs` after `build_queue`; append `("CombatLog.csv", "combat", read_combat_log),` to `READERS`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_ingest_events.py tests/test_ingest_load.py -q` then `uv run pytest -q`.
Expected: all pass, zero warnings.

- [ ] **Step 6: Commit**

```bash
git add civ7_advisor/ingest/events.py civ7_advisor/ingest/load.py tests/test_ingest_events.py
git commit -m "Add CombatLog reader with Destroyed-only win/loss semantics"
```

---

### Task 3: `Game_Gossip.csv` and `DiplomacySummary.csv` readers

**Files:**
- Modify: `civ7_advisor/ingest/events.py` (append two sections)
- Modify: `civ7_advisor/ingest/load.py` (imports, `RawLogs.gossip`, `RawLogs.diplomacy_summary`, two READERS entries)
- Modify: `tests/test_ingest_events.py` (append)

**Interfaces:**
- Produces: `GossipRow(turn: int, leader: str, civilization: str, x: int, y: int, type: str, detail: str | None)` frozen — `leader` is the **leader's display name as logged** (e.g. `Alexander`), not an id; `read_gossip(path)`; `DiplomacySummaryRow(turn: int, initiator: int, recipient: int, action: str, details: str, extra: tuple[str, ...])` frozen with `parties() -> frozenset[int]` and `involves(player) -> bool`; `read_diplomacy_summary(path)`; `RawLogs.gossip`, `RawLogs.diplomacy_summary`; `"Game_Gossip.csv"`, `"DiplomacySummary.csv"` in `LOG_FILES`.
- **Both files are ragged (spec §3.1, ⚠ verify).** Gossip: 6 header names, 6 or 7 data columns — the 7th is a free-text detail (`Warrior`). DiplomacySummary: 7 header names (`… Mayhem, Visibility`) but the captured row has 6 values, so which trailing column is missing cannot be known from one row. The reader keeps everything after `Details` as the raw tuple `extra` and names nothing; Task 11 assigns `mayhem`/`visibility` once the distribution is known. Provenance for diplomacy uses the party rule only.

- [ ] **Step 1: Append the failing tests**

Append to `tests/test_ingest_events.py` (extend the import line to `from civ7_advisor.ingest.events import Combatant, CombatRow, DiplomacySummaryRow, GossipRow, read_combat_log, read_diplomacy_summary, read_gossip`):
```python
GOSSIP_HEADER = "Game Turn, Player, Civilization, Plot X, Plot Y, Type\n"
# Captured live 2026-09-07. `Player` is a leader NAME; the row has one more column than the header.
LIVE_GOSSIP = "82, Alexander, Maurya, 63, 31, GOSSIP_UNIT_DESTROYED, Warrior\n"


def test_gossip_reads_the_live_row_with_its_trailing_detail(tmp_path: Path):
    p = tmp_path / "Game_Gossip.csv"
    p.write_text(GOSSIP_HEADER + LIVE_GOSSIP)
    assert read_gossip(p) == [GossipRow(82, "Alexander", "Maurya", 63, 31, "GOSSIP_UNIT_DESTROYED", "Warrior")]


def test_gossip_accepts_six_columns_with_no_detail(tmp_path: Path):
    p = tmp_path / "Game_Gossip.csv"
    p.write_text(GOSSIP_HEADER + "5, Confucius, Han, 40, 12, GOSSIP_CITY_FOUNDED\n")
    [row] = read_gossip(p)
    assert (row.leader, row.civilization, row.type, row.detail) == ("Confucius", "Han", "GOSSIP_CITY_FOUNDED", None)


def test_gossip_rejects_other_widths(tmp_path: Path):
    p = tmp_path / "Game_Gossip.csv"
    p.write_text(GOSSIP_HEADER + "5, Confucius, Han, 40\n")
    with pytest.raises(LogFormatError, match="6 or 7 columns"):
        read_gossip(p)


DIPLO_HEADER = "Game Turn, Initiator, Recipient, Action, Details, Mayhem, Visibility\n"
# Captured live 2026-09-07: seven header names, six values. The trailing cells are kept raw.
LIVE_DIPLO = ("82, 0, 7, Diplomacy Action Enter Stage, "
              "Cultural Exchange Entering Stage DIPLOMACY_CULTURAL_EXCHANGE_COMPLETE,  426.0\n")


def test_diplomacy_summary_keeps_trailing_cells_raw(tmp_path: Path):
    p = tmp_path / "DiplomacySummary.csv"
    p.write_text(DIPLO_HEADER + LIVE_DIPLO)
    [row] = read_diplomacy_summary(p)
    assert (row.turn, row.initiator, row.recipient) == (82, 0, 7)
    assert row.action == "Diplomacy Action Enter Stage"
    assert row.details == "Cultural Exchange Entering Stage DIPLOMACY_CULTURAL_EXCHANGE_COMPLETE"
    assert row.extra == ("426.0",)
    assert row.parties() == frozenset({0, 7}) and row.involves(0) and not row.involves(3)


def test_diplomacy_summary_seven_values_also_parse(tmp_path: Path):
    p = tmp_path / "DiplomacySummary.csv"
    p.write_text(DIPLO_HEADER + "10, 4, 1, Denounce, Denounced publicly, 12.5, VISIBLE\n")
    [row] = read_diplomacy_summary(p)
    assert row.extra == ("12.5", "VISIBLE")


def test_diplomacy_summary_needs_at_least_the_five_named_cells(tmp_path: Path):
    p = tmp_path / "DiplomacySummary.csv"
    p.write_text(DIPLO_HEADER + "10, 4, 1, Denounce\n")
    with pytest.raises(LogFormatError, match="at least 5 columns"):
        read_diplomacy_summary(p)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_ingest_events.py -q`
Expected: FAIL with `ImportError: cannot import name 'DiplomacySummaryRow'`.

- [ ] **Step 3: Append the readers**

Append to `civ7_advisor/ingest/events.py`:
```python
# --- Game_Gossip.csv --------------------------------------------------------
# Ragged: 6 header names, 6 or 7 data columns (the 7th is a free-text detail). `Player`
# holds the leader's display NAME, not an id — state/names.py resolves it.

GOSSIP_HEADER = ["Game Turn", "Player", "Civilization", "Plot X", "Plot Y", "Type"]


@dataclass(frozen=True)
class GossipRow:
    turn: int
    leader: str          # display name as logged, e.g. "Alexander"; resolve via NameResolver
    civilization: str    # e.g. "Maurya"
    x: int               # may be negative when the gossip has no plot
    y: int
    type: str            # GOSSIP_UNIT_DESTROYED, GOSSIP_CITY_FOUNDED, ...
    detail: str | None   # the optional 7th column, e.g. "Warrior"


def read_gossip(path: Path) -> list[GossipRow]:
    table = read_table(path)
    expect_header(table, GOSSIP_HEADER)
    out: list[GossipRow] = []
    for r in latest_game_segment(table.rows, turn_col=0):
        if len(r) not in (6, 7):
            raise LogFormatError(
                f"{path.name}: expected 6 or 7 columns but a row has {len(r)} (row starts {r[:2]})"
            )
        detail = r[6] if len(r) == 7 and r[6] else None
        out.append(GossipRow(int(r[0]), r[1], r[2], int(r[3]), int(r[4]), r[5], detail))
    return out


# --- DiplomacySummary.csv ---------------------------------------------------
# Seven header names, but the captured live row carried six values, so it is not known
# whether `Mayhem` or `Visibility` is the one missing. Everything after `Details` is kept
# raw in `extra`; the fixture task names those cells once the distribution is known.

DIPLOMACY_SUMMARY_HEADER = ["Game Turn", "Initiator", "Recipient", "Action", "Details", "Mayhem", "Visibility"]


@dataclass(frozen=True)
class DiplomacySummaryRow:
    turn: int
    initiator: int
    recipient: int
    action: str
    details: str
    extra: tuple[str, ...]   # the cells after Details, unnamed until Task 11 pins them

    def parties(self) -> frozenset[int]:
        return frozenset({self.initiator, self.recipient})

    def involves(self, player: int) -> bool:
        return player in self.parties()


def read_diplomacy_summary(path: Path) -> list[DiplomacySummaryRow]:
    table = read_table(path)
    expect_header(table, DIPLOMACY_SUMMARY_HEADER)
    out: list[DiplomacySummaryRow] = []
    for r in latest_game_segment(table.rows, turn_col=0):
        if len(r) < 5:
            raise LogFormatError(
                f"{path.name}: expected at least 5 columns but a row has {len(r)} (row starts {r[:2]})"
            )
        out.append(DiplomacySummaryRow(int(r[0]), int(r[1]), int(r[2]), r[3], r[4], tuple(r[5:])))
    return out
```

- [ ] **Step 4: Wire both into `load_logs`**

In `civ7_advisor/ingest/load.py`: extend the events import to `from .events import CombatRow, DiplomacySummaryRow, GossipRow, read_combat_log, read_diplomacy_summary, read_gossip`; add to `RawLogs` after `combat`: `gossip: list[GossipRow] = field(default_factory=list)` and `diplomacy_summary: list[DiplomacySummaryRow] = field(default_factory=list)`; append to `READERS`: `("Game_Gossip.csv", "gossip", read_gossip),` and `("DiplomacySummary.csv", "diplomacy_summary", read_diplomacy_summary),`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_ingest_events.py tests/test_ingest_load.py -q` then `uv run pytest -q`. Expected: all pass, zero warnings.

- [ ] **Step 6: Commit**

```bash
git add civ7_advisor/ingest/events.py civ7_advisor/ingest/load.py tests/test_ingest_events.py
git commit -m "Add Gossip and DiplomacySummary readers, tolerant of their ragged widths"
```

---

### Task 4: `DiplomacyDeals.log` line parser

**Files:**
- Create: `civ7_advisor/ingest/textlogs.py`
- Modify: `civ7_advisor/ingest/load.py` (import, `RawLogs.deals`, READERS entry)
- Test: `tests/test_ingest_textlogs.py`

**Interfaces:**
- Produces: `DealItem(turn: int, item_id: int, from_player: int, to_player: int, kind: str, amount: int, duration: int)` frozen with `is_peace -> bool` and `parties() -> frozenset[int]`; `read_deals(path) -> list[DealItem]`; `RawLogs.deals`; `"DiplomacyDeals.log"` in `LOG_FILES`.
- Format (captured live): a block header `Turn 79, Incoming for player 4 and 7` followed by item lines `, Item ID 2, from player 7, to player 4, type Peace, subType -751445167 (), value type , amount 0, duration 1`. Lines matching neither pattern are ignored. A block header whose turn is lower than the previous block's starts a new game: everything collected so far is discarded (the same rule as `latest_game_segment`).

- [ ] **Step 1: Write the failing tests**

`tests/test_ingest_textlogs.py`:
```python
from pathlib import Path

from civ7_advisor.ingest.textlogs import DealItem, read_deals

# Captured live 2026-09-07 (verbatim lines).
LIVE_DEALS = (
    "Turn 79, Incoming for player 4 and 7\n"
    ", Item ID 2, from player 7, to player 4, type Peace, subType -751445167 (), value type , amount 0, duration 1\n"
    ", Item ID 3, from player 7, to player 4, type Influence Large Lump (100), subType -858063716 (), value type , amount 100, duration 0\n"
)


def test_reads_items_under_their_block_turn(tmp_path: Path):
    p = tmp_path / "DiplomacyDeals.log"
    p.write_text(LIVE_DEALS)
    assert read_deals(p) == [
        DealItem(79, 2, 7, 4, "Peace", 0, 1),
        DealItem(79, 3, 7, 4, "Influence Large Lump (100)", 100, 0),
    ]


def test_is_peace_and_parties():
    peace = DealItem(79, 2, 7, 4, "Peace", 0, 1)
    gold = DealItem(79, 3, 7, 4, "Influence Large Lump (100)", 100, 0)
    assert peace.is_peace and not gold.is_peace
    assert peace.parties() == frozenset({4, 7})


def test_unknown_lines_are_ignored_and_items_before_a_header_are_dropped(tmp_path: Path):
    p = tmp_path / "DiplomacyDeals.log"
    p.write_text(
        ", Item ID 9, from player 1, to player 0, type Peace, subType 1 (), value type , amount 0, duration 1\n"
        "Some engine chatter that is not a deal\n"
        + LIVE_DEALS
    )
    assert [d.item_id for d in read_deals(p)] == [2, 3]


def test_a_turn_going_backwards_starts_a_new_game(tmp_path: Path):
    p = tmp_path / "DiplomacyDeals.log"
    p.write_text(
        LIVE_DEALS
        + "Turn 3, Incoming for player 0 and 1\n"
        + ", Item ID 1, from player 1, to player 0, type Open Borders, subType 5 (), value type , amount 0, duration 30\n"
    )
    assert read_deals(p) == [DealItem(3, 1, 1, 0, "Open Borders", 0, 30)]


def test_empty_file_gives_no_deals(tmp_path: Path):
    p = tmp_path / "DiplomacyDeals.log"
    p.write_text("")
    assert read_deals(p) == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_ingest_textlogs.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'civ7_advisor.ingest.textlogs'`.

- [ ] **Step 3: Write the parser**

`civ7_advisor/ingest/textlogs.py`:
```python
"""Parsers for the Civ VII logs that are not CSV. Phase 1a: DiplomacyDeals.log."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_BLOCK = re.compile(r"^Turn (\d+), Incoming for player (\d+) and (\d+)")
_ITEM = re.compile(
    r"^, Item ID (\d+), from player (\d+), to player (\d+), type ([^,]+), subType [^,]*, "
    r"value type [^,]*, amount (-?\d+), duration (-?\d+)"
)


@dataclass(frozen=True)
class DealItem:
    turn: int
    item_id: int
    from_player: int
    to_player: int
    kind: str        # "Peace", "Influence Large Lump (100)", "Open Borders", ...
    amount: int
    duration: int

    @property
    def is_peace(self) -> bool:
        return self.kind == "Peace"

    def parties(self) -> frozenset[int]:
        return frozenset({self.from_player, self.to_player})


def read_deals(path: Path) -> list[DealItem]:
    """Items grouped under `Turn N, Incoming …` headers. Unknown lines are skipped; a header
    whose turn is lower than the previous one means a new game, and earlier items are dropped."""
    out: list[DealItem] = []
    turn: int | None = None
    with path.open(encoding="utf-8-sig", errors="replace") as fh:
        for line in fh:
            line = line.rstrip("\n")
            block = _BLOCK.match(line)
            if block:
                new_turn = int(block.group(1))
                if turn is not None and new_turn < turn:
                    out.clear()
                turn = new_turn
                continue
            item = _ITEM.match(line)
            if item and turn is not None:
                out.append(DealItem(turn, int(item.group(1)), int(item.group(2)), int(item.group(3)),
                                    item.group(4).strip(), int(item.group(5)), int(item.group(6))))
    return out
```

- [ ] **Step 4: Wire it into `load_logs`**

In `civ7_advisor/ingest/load.py`: add `from .textlogs import DealItem, read_deals`; add `deals: list[DealItem] = field(default_factory=list)` to `RawLogs` after `diplomacy_summary`; append `("DiplomacyDeals.log", "deals", read_deals),` to `READERS`. The `latest_turn` in `FileStatus` works unchanged (`DealItem.turn` exists).

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_ingest_textlogs.py tests/test_ingest_load.py -q` then `uv run pytest -q`. Expected: all pass, zero warnings.

- [ ] **Step 6: Commit**

```bash
git add civ7_advisor/ingest/textlogs.py civ7_advisor/ingest/load.py tests/test_ingest_textlogs.py
git commit -m "Add DiplomacyDeals line parser with peace detection"
```

---

### Task 5: State — carry the new rows, resolve leader names, fold peace deals; test factories

**Files:**
- Create: `civ7_advisor/state/names.py`
- Modify: `civ7_advisor/state/models.py` (imports; `GameState` fields; `peace_between`), `civ7_advisor/state/build.py` (carry-through, fold, resolver)
- Modify: `tests/factories.py` (builders for the five new row types)
- Test: `tests/test_names.py`, `tests/test_state.py` (append)

**Interfaces:**
- Consumes: `BuildQueueRow`, `CombatRow`, `GossipRow`, `DiplomacySummaryRow`, `DealItem`, `RawLogs` fields from Tasks 1–4; `display_name`, `INDEPENDENT_KEY` from `state/build.py`.
- Produces: `NameResolver.build(rival_names: dict[int, str], human_city_keys: list[str]) -> NameResolver`, `NameResolver.player_for(leader: str, civilization: str | None = None) -> int | None`, `NameResolver.normalize(s) -> str`, attribute `human_civ: str | None`; `GameState.build_queues`, `.combats`, `.gossip`, `.diplomacy_events`, `.deals` (lists), `.peace_turns: dict[frozenset[int], int]`, `.names: NameResolver | None`, method `peace_between(a: int, b: int) -> int | None`; factories `build_queue_row(turn, player, city="LOC_CITY_NAME_TEST1", item="BUILDING_BRICKYARD", added=10.0, current=0.0, needed=50.0)`, `combat(turn, att_player, def_player, destroyed=None, att_kind="UNIT_WARRIOR", def_kind="UNIT_SPEARMAN", x=10, y=10)`, `gossip_row(turn, leader, civilization, type="GOSSIP_UNIT_DESTROYED", x=10, y=10, detail=None)`, `diplo_event(turn, initiator, recipient, action="Denounce", details="", extra=())`, `deal(turn, from_player, to_player, kind="Peace")`.

- [ ] **Step 1: Write the failing tests**

`tests/test_names.py`:
```python
from civ7_advisor.state.names import NameResolver


def _resolver() -> NameResolver:
    return NameResolver.build(
        rival_names={1: "Ibn Battuta", 4: "José Rizal", 7: "Catherine"},
        human_city_keys=["LOC_CITY_NAME_MAURYA1", "LOC_CITY_NAME_MAURYA2"],
    )


def test_rival_leaders_resolve_with_or_without_accents():
    r = _resolver()
    assert r.player_for("José Rizal") == 4
    assert r.player_for("Jose Rizal") == 4
    assert r.player_for("IBN BATTUTA") == 1


def test_human_is_recognised_by_civilization_from_their_city_keys():
    r = _resolver()
    assert r.human_civ == "maurya"
    assert r.player_for("Alexander", "Maurya") == 0
    assert r.player_for("Alexander") is None  # a bare unknown leader is never guessed


def test_unknown_stays_unknown():
    assert _resolver().player_for("Napoleon", "France") is None


def test_no_human_cities_means_no_human_civ():
    r = NameResolver.build(rival_names={}, human_city_keys=[])
    assert r.human_civ is None and r.player_for("Alexander", "Maurya") is None


def test_normalize_strips_marks_case_and_spacing():
    assert NameResolver.normalize("  Trưng   Trắc ") == "trung trac"
```

Append to `tests/test_state.py`:
```python
def test_new_rows_are_carried_and_peace_is_folded():
    from civ7_advisor.ingest.load import RawLogs
    from civ7_advisor.ingest.readers import StatsRow
    from tests.factories import build_queue_row, combat, deal, diplo_event, gossip_row

    def stats(turn, player):
        return StatsRow(turn, player, 1, 0, 3, 0, 1, 2, 1, 2, 0, 5, 1, 10.0, 1, 1, 1, 1, 1, 1, 0)

    raw = RawLogs(
        stats=[stats(1, 0), stats(1, 4), stats(2, 0), stats(2, 4), stats(3, 0)],
        build_queue=[build_queue_row(2, 0)],
        combat=[combat(2, 0, 4, destroyed="Attacker")],
        gossip=[gossip_row(2, "Alexander", "Maurya")],
        diplomacy_summary=[diplo_event(2, 0, 4)],
        deals=[deal(1, 4, 0, "Peace"), deal(2, 4, 0, "Peace"), deal(2, 1, 7, "Peace"), deal(2, 4, 0, "Open Borders")],
    )
    s = build_state(raw)
    assert len(s.build_queues) == 1 and len(s.combats) == 1 and len(s.gossip) == 1
    assert len(s.diplomacy_events) == 1 and len(s.deals) == 4
    assert s.peace_turns == {frozenset({0, 4}): 2, frozenset({1, 7}): 2}
    assert s.peace_between(0, 4) == 2 and s.peace_between(4, 0) == 2 and s.peace_between(0, 7) is None
    assert s.names is not None and s.names.player_for("Alexander", "Maurya") == 0


def test_empty_state_has_empty_collections_and_no_resolver():
    s = build_state(RawLogs())
    assert s.build_queues == [] and s.combats == [] and s.deals == [] and s.peace_turns == {}
    assert s.names is None and s.peace_between(0, 1) is None
```

Add to `tests/factories.py` (imports: `from civ7_advisor.ingest.production import BuildQueueRow`, `from civ7_advisor.ingest.events import Combatant, CombatRow, DiplomacySummaryRow, GossipRow`, `from civ7_advisor.ingest.textlogs import DealItem`):
```python
def build_queue_row(turn: int, player: int, city: str = "LOC_CITY_NAME_TEST1", item: str = "BUILDING_BRICKYARD",
                    added: float = 10.0, current: float = 0.0, needed: float = 50.0) -> BuildQueueRow:
    return BuildQueueRow(turn, player, city, added, item, current, needed, 0.0)


def combat(turn: int, att_player: int, def_player: int, destroyed: str | None = None,
           att_kind: str = "UNIT_WARRIOR", def_kind: str = "UNIT_SPEARMAN", x: int = 10, y: int = 10) -> CombatRow:
    return CombatRow(turn, "Unit vs Unit", x, y, att_player, def_player, "Melee",
                     Combatant(100, att_kind), Combatant(200, def_kind),
                     20, 20, 0, 0, 30, 30, destroyed, 0, "(70)100", "(70)100")


def gossip_row(turn: int, leader: str, civilization: str, type: str = "GOSSIP_UNIT_DESTROYED",
               x: int = 10, y: int = 10, detail: str | None = None) -> GossipRow:
    return GossipRow(turn, leader, civilization, x, y, type, detail)


def diplo_event(turn: int, initiator: int, recipient: int, action: str = "Denounce",
                details: str = "", extra: tuple[str, ...] = ()) -> DiplomacySummaryRow:
    return DiplomacySummaryRow(turn, initiator, recipient, action, details, extra)


def deal(turn: int, from_player: int, to_player: int, kind: str = "Peace") -> DealItem:
    return DealItem(turn, 1, from_player, to_player, kind, 0, 1)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_names.py tests/test_state.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'civ7_advisor.state.names'` (and, for the state tests, `TypeError` on unknown `RawLogs`/`GameState` fields until Steps 3–4 land).

- [ ] **Step 3: Write the resolver**

`civ7_advisor/state/names.py`:
```python
"""Resolve the leader names some logs use (Gossip) to player ids.

Rivals are known from AI_Victories owner keys. The human never appears there, but their
civilization does appear in their own city keys (LOC_CITY_NAME_MAURYA1 -> "maurya"), so a
gossip row whose Civilization matches is the human. Anything else stays unresolved — an id
is never guessed.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass

HUMAN = 0
_CITY_KEY = re.compile(r"^LOC_CITY_NAME_([A-Z_]+?)\d*$")


@dataclass(frozen=True)
class NameResolver:
    by_leader: dict[str, int]    # normalized display name -> player id
    human_civ: str | None        # normalized civilization name of player 0

    @staticmethod
    def normalize(s: str) -> str:
        decomposed = unicodedata.normalize("NFKD", s)
        stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
        return " ".join(stripped.casefold().split())

    @classmethod
    def build(cls, rival_names: dict[int, str], human_city_keys: list[str]) -> "NameResolver":
        by_leader = {cls.normalize(name): pid for pid, name in rival_names.items()}
        prefixes = Counter()
        for key in human_city_keys:
            m = _CITY_KEY.match(key)
            if m:
                prefixes[cls.normalize(m.group(1).replace("_", " "))] += 1
        human_civ = prefixes.most_common(1)[0][0] if prefixes else None
        return cls(by_leader=by_leader, human_civ=human_civ)

    def player_for(self, leader: str, civilization: str | None = None) -> int | None:
        pid = self.by_leader.get(self.normalize(leader))
        if pid is not None:
            return pid
        if civilization is not None and self.human_civ is not None:
            if self.normalize(civilization) == self.human_civ:
                return HUMAN
        return None
```

- [ ] **Step 4: Extend the models and the builder**

In `civ7_advisor/state/models.py`: add imports
```python
from civ7_advisor.ingest.events import CombatRow, DiplomacySummaryRow, GossipRow
from civ7_advisor.ingest.production import BuildQueueRow
from civ7_advisor.ingest.textlogs import DealItem

from .names import NameResolver
```
and add to `GameState` after `files`:
```python
    build_queues: list[BuildQueueRow] = field(default_factory=list)
    combats: list[CombatRow] = field(default_factory=list)
    gossip: list[GossipRow] = field(default_factory=list)
    diplomacy_events: list[DiplomacySummaryRow] = field(default_factory=list)
    deals: list[DealItem] = field(default_factory=list)
    peace_turns: dict[frozenset[int], int] = field(default_factory=dict)  # pair -> latest Peace deal turn
    names: NameResolver | None = None
```
and the method, after `series`:
```python
    def peace_between(self, a: int, b: int) -> int | None:
        """Turn of the most recent Peace deal between two players, if any."""
        return self.peace_turns.get(frozenset({a, b}))
```
Add the five new names to `__all__`.

In `civ7_advisor/state/build.py`: import `NameResolver` from `.names`; after the strategies fold and the existing three `state.intents/targets/events` lines, add:
```python
    state.build_queues = list(raw.build_queue)
    state.combats = list(raw.combat)
    state.gossip = list(raw.gossip)
    state.diplomacy_events = list(raw.diplomacy_summary)
    state.deals = list(raw.deals)
    for d in raw.deals:
        if d.is_peace:
            pair = d.parties()
            state.peace_turns[pair] = max(state.peace_turns.get(pair, 0), d.turn)
    state.names = NameResolver.build(
        rival_names={p.id: p.name for p in state.players.values() if p.kind is PlayerKind.RIVAL},
        human_city_keys=[q.city for q in raw.build_queue if q.player == GameState.HUMAN],
    )
```
(The early `if not raw.stats: return state` keeps the empty state's collections empty and `names` None.)

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_names.py tests/test_state.py -q` then `uv run pytest -q`. Expected: all pass, zero warnings.

- [ ] **Step 6: Commit**

```bash
git add civ7_advisor/state/names.py civ7_advisor/state/models.py civ7_advisor/state/build.py tests/factories.py tests/test_names.py tests/test_state.py
git commit -m "Carry production, combat, gossip, diplomacy and deals into GameState; resolve leader names; fold peace"
```

---

### Task 6: Production advisor, `humanize()` helper, advisor registry

**Files:**
- Create: `civ7_advisor/advisors/production.py`
- Modify: `civ7_advisor/advisors/base.py` (add `humanize`), `civ7_advisor/advisors/checklist.py:6` (`ADVISOR_ORDER`), `civ7_advisor/advisors/__init__.py` (`ADVISORS`, `__all__`)
- Modify: `tests/test_checklist.py::test_every_advisor_is_registered_in_both_lists_and_stamps_its_own_name` (subset semantics)
- Test: `tests/test_production_advisor.py`

**Interfaces:**
- Consumes: `GameState.build_queues`, `.rivals()`, `.latest_turn`, `.complete_through_turn`; `economy.comparison(state)`, `economy.BEHIND_RATIO`, `economy.YIELDS`.
- Produces: `base.humanize(key: str) -> str` (`LOC_DISTRICT_CITY_CENTER_NAME` → `City Center`, `UNIT_WARRIOR` → `Warrior`, `GOSSIP_UNIT_DESTROYED` → `Unit Destroyed`); in `production.py`: constants `RIVAL_MILITARY_SHARE = 0.5`, `CIVILIAN_UNITS`, `CIVILIAN_PREFIXES`, `ITEM_YIELDS`; `is_military(item: str) -> bool`; `CityQueue(player, city, item, added, current, needed, turns_to_complete, turn)` frozen; `queues(state) -> dict[int, list[CityQueue]]`; `rival_military_share(state) -> dict[int, float]`; `advise(state)` emitting `production.own_queue` INFO/FAIR, `production.mismatch` ADVISE/FAIR, `production.rival_military.{r}` WARN/ORACLE. `ADVISOR_ORDER["production"] == 3`; `production` in `ADVISORS`.
- Decision recorded: the human's queue uses rows up to `latest_turn` (their live turn — the row is written when they act), rivals' up to `complete_through_turn`. `ITEM_YIELDS` is **unverified game knowledge** (phase 3 checks it); an item missing from it suppresses `production.mismatch` rather than guessing.

- [ ] **Step 1: Write the failing tests**

`tests/test_production_advisor.py`:
```python
import pytest

from civ7_advisor.advisors import ADVISORS, production
from civ7_advisor.advisors.base import Provenance, Severity, humanize
from civ7_advisor.advisors.checklist import ADVISOR_ORDER
from tests.factories import build_queue_row, game_state


def ids(insights):
    return {i.id: i for i in insights}


def test_humanize_strips_game_key_decoration():
    assert humanize("LOC_DISTRICT_CITY_CENTER_NAME") == "City Center"
    assert humanize("UNIT_WARRIOR") == "Warrior"
    assert humanize("BUILDING_BRICKYARD") == "Brickyard"
    assert humanize("GOSSIP_UNIT_DESTROYED") == "Unit Destroyed"
    assert humanize("") == ""


@pytest.mark.parametrize("item,expected", [
    ("UNIT_WARRIOR", True), ("UNIT_ARMY_COMMANDER", True), ("UNIT_SCOUT", False),
    ("UNIT_SETTLER", False), ("UNIT_GREAT_MERCHANT", False), ("BUILDING_BRICKYARD", False), ("", False),
])
def test_is_military(item, expected):
    assert production.is_military(item) is expected


def test_queues_use_the_human_live_turn_but_rivals_complete_turn():
    s = game_state(turn=20)  # latest 21, complete 20
    s.build_queues = [
        build_queue_row(20, 0, "LOC_CITY_NAME_A", item="BUILDING_GRANARY"),
        build_queue_row(21, 0, "LOC_CITY_NAME_A", item="BUILDING_BRICKYARD", added=15.0, current=47.5, needed=55.0),
        build_queue_row(20, 1, "LOC_CITY_NAME_B", item="UNIT_WARRIOR"),
        build_queue_row(21, 1, "LOC_CITY_NAME_B", item="UNIT_ARCHER"),
    ]
    q = production.queues(s)
    assert [c.item for c in q[0]] == ["BUILDING_BRICKYARD"] and q[0][0].turns_to_complete == 1
    assert [c.item for c in q[1]] == ["UNIT_WARRIOR"]


def test_own_queue_insight_lists_every_city_and_is_fair():
    s = game_state(turn=20)
    s.build_queues = [
        build_queue_row(21, 0, "LOC_CITY_NAME_A", item="BUILDING_BRICKYARD", added=15.0, current=47.5, needed=55.0),
        build_queue_row(21, 0, "LOC_CITY_NAME_B", item="", added=8.0),
    ]
    i = ids(production.advise(s))["production.own_queue"]
    assert i.severity is Severity.INFO and i.provenance is Provenance.FAIR and i.advisor == "production"
    assert "A: Brickyard in 1 turn" in i.why and "B: idle" in i.why


@pytest.mark.parametrize("item,fires", [("BUILDING_BRICKYARD", True), ("BUILDING_GRANARY", False), ("BUILDING_ZIGGURAT", False)])
def test_mismatch_fires_only_when_every_item_is_known_and_none_serves_the_worst_gap(item, fires):
    s = game_state(turn=20, human_stats={"food": 8.0})  # food 8 vs rival 20 -> worst gap
    s.build_queues = [build_queue_row(21, 0, "LOC_CITY_NAME_A", item=item)]
    got = ids(production.advise(s))
    assert ("production.mismatch" in got) is fires
    if fires:
        assert got["production.mismatch"].provenance is Provenance.FAIR
        assert "food" in got["production.mismatch"].title and "Brickyard" in got["production.mismatch"].why


def test_mismatch_silent_when_nothing_is_behind():
    s = game_state(turn=20)
    s.build_queues = [build_queue_row(21, 0, "LOC_CITY_NAME_A", item="BUILDING_BRICKYARD")]
    assert "production.mismatch" not in ids(production.advise(s))


@pytest.mark.parametrize("items,fires", [
    (["UNIT_WARRIOR", "BUILDING_GRANARY"], True),            # 1/2 = 0.5, at the threshold
    (["UNIT_WARRIOR", "BUILDING_GRANARY", "BUILDING_X"], False),  # 1/3
    (["UNIT_SCOUT", "UNIT_SETTLER"], False),                 # civilians never count
])
def test_rival_military_share_threshold(items, fires):
    s = game_state(turn=20)
    s.build_queues = [build_queue_row(20, 1, f"LOC_CITY_NAME_R{n}", item=it) for n, it in enumerate(items)]
    got = ids(production.advise(s))
    assert ("production.rival_military.1" in got) is fires
    if fires:
        i = got["production.rival_military.1"]
        assert i.severity is Severity.WARN and i.provenance is Provenance.ORACLE and "1 of Rival One's 2 cities" in i.why


def test_no_queues_means_no_insights():
    assert production.advise(game_state(turn=20)) == []


def test_production_is_registered():
    assert production in ADVISORS and ADVISOR_ORDER["production"] == 3
```

Amend `tests/test_checklist.py::test_every_advisor_is_registered_in_both_lists_and_stamps_its_own_name`: change the last assertion to subset semantics, because an advisor may legitimately be silent on the v1 fixture (production has no `CityBuildQueue` there):
```python
        assert emitted <= {name}, f"{name}.advise() stamps {emitted}"  # silent on this fixture is allowed
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_production_advisor.py -q`
Expected: FAIL with `ImportError: cannot import name 'production'`.

- [ ] **Step 3: Add `humanize` to `base.py`**

Append to `civ7_advisor/advisors/base.py`:
```python
_KEY_PREFIXES = ("LOC_", "GOSSIP_", "DISTRICT_", "UNIT_", "BUILDING_", "IMPROVEMENT_", "WONDER_")


def humanize(key: str) -> str:
    """Turn a game key into words: LOC_DISTRICT_CITY_CENTER_NAME -> 'City Center'."""
    s = key
    stripped = True
    while stripped:
        stripped = False
        for prefix in _KEY_PREFIXES:
            if s.startswith(prefix):
                s = s[len(prefix):]
                stripped = True
    return s.removesuffix("_NAME").replace("_", " ").title()
```

- [ ] **Step 4: Write the advisor**

`civ7_advisor/advisors/production.py`:
```python
"""What everyone is building, how soon, and whether your queue matches your worst gap."""
from __future__ import annotations

from dataclasses import dataclass

from civ7_advisor.state.models import GameState

from . import economy
from .base import Insight, Provenance, Severity, humanize

RIVAL_MILITARY_SHARE = 0.5  # share of a rival's cities building military at/above which we warn
CIVILIAN_UNITS = {"UNIT_SETTLER", "UNIT_MIGRANT", "UNIT_FOUNDER", "UNIT_SCOUT", "UNIT_MERCHANT"}
CIVILIAN_PREFIXES = ("UNIT_GREAT_",)
# Which economy yield an item mainly serves. UNVERIFIED against current game rules (phase 3
# checks it); an item that is not listed suppresses the mismatch insight rather than guessing.
ITEM_YIELDS: dict[str, str] = {
    "BUILDING_BRICKYARD": "production", "BUILDING_SAWPIT": "production",
    "BUILDING_GRANARY": "food", "BUILDING_FISHING_QUAY": "food",
    "BUILDING_LIBRARY": "science", "BUILDING_ACADEMY": "science",
    "BUILDING_MONUMENT": "culture", "BUILDING_AMPHITHEATER": "culture",
    "BUILDING_MARKET": "gold", "BUILDING_BANK": "gold",
}


def is_military(item: str) -> bool:
    return item.startswith("UNIT_") and item not in CIVILIAN_UNITS and not item.startswith(CIVILIAN_PREFIXES)


@dataclass(frozen=True)
class CityQueue:
    player: int
    city: str
    item: str
    added: float
    current: float
    needed: float
    turns_to_complete: int | None
    turn: int


def queues(state: GameState) -> dict[int, list[CityQueue]]:
    """Latest logged queue row per (player, city).

    The human's row is written when they act, so their live queue is the row at latest_turn;
    rivals are read at complete_through_turn like every other AI-side fact.
    """
    latest: dict[tuple[int, str], object] = {}
    for q in state.build_queues:
        cutoff = state.latest_turn if q.player == state.HUMAN else state.complete_through_turn
        if q.turn > cutoff:
            continue
        key = (q.player, q.city)
        if key not in latest or q.turn > latest[key].turn:  # type: ignore[attr-defined]
            latest[key] = q
    out: dict[int, list[CityQueue]] = {}
    for (pid, city), q in sorted(latest.items()):
        out.setdefault(pid, []).append(
            CityQueue(pid, city, q.item, q.added, q.current, q.needed, q.turns_to_complete, q.turn)  # type: ignore[attr-defined]
        )
    return out


def rival_military_share(state: GameState) -> dict[int, float]:
    qs = queues(state)
    return {
        r.id: sum(is_military(c.item) for c in qs[r.id]) / len(qs[r.id])
        for r in state.rivals() if qs.get(r.id)
    }


def _city(city_key: str) -> str:
    return city_key.removeprefix("LOC_CITY_NAME_").replace("_", " ").title()


def _queue_phrase(c: CityQueue) -> str:
    if not c.item:
        return f"{_city(c.city)}: idle"
    if c.turns_to_complete is None:
        return f"{_city(c.city)}: {humanize(c.item)} (stalled)"
    n = c.turns_to_complete
    return f"{_city(c.city)}: {humanize(c.item)} in {n} turn{'s' if n != 1 else ''}"


def advise(state: GameState) -> list[Insight]:
    t = state.complete_through_turn
    out: list[Insight] = []
    qs = queues(state)
    human = qs.get(state.HUMAN, [])

    if human:
        out.append(Insight(
            id="production.own_queue", advisor="production", severity=Severity.INFO, provenance=Provenance.FAIR,
            title="What your cities are building",
            recommendation="Check each queue against the gap the Economy tab flags; an idle city is the first thing to fix.",
            why="; ".join(_queue_phrase(c) for c in human) + ".", turn=t, subject_player=state.HUMAN,
        ))
        behind = sorted((c for c in economy.comparison(state) if c.ratio < economy.BEHIND_RATIO), key=lambda c: c.ratio)
        building = [c for c in human if c.item]
        served = [ITEM_YIELDS.get(c.item) for c in building]
        if behind and building and all(served) and behind[0].stat not in served:
            worst = behind[0]
            out.append(Insight(
                id="production.mismatch", advisor="production", severity=Severity.ADVISE, provenance=Provenance.FAIR,
                title=f"Nothing in your queues addresses {worst.label}",
                recommendation=f"Your worst gap is {worst.label} ({worst.ratio:.0%} of the rival median). "
                               f"{economy.YIELDS[worst.stat][1]}",
                why=f"Turn {t}: you are building {', '.join(humanize(c.item) for c in building)}, which serve "
                    f"{', '.join(sorted(set(served)))}, not {worst.label}.",
                turn=t, subject_player=state.HUMAN,
            ))

    shares = rival_military_share(state)
    for r in state.rivals():
        share = shares.get(r.id)
        if share is None or share < RIVAL_MILITARY_SHARE:
            continue
        cities = qs[r.id]
        mil = [c for c in cities if is_military(c.item)]
        out.append(Insight(
            id=f"production.rival_military.{r.id}", advisor="production", severity=Severity.WARN,
            provenance=Provenance.ORACLE, title=f"{r.name} is building an army",
            recommendation="Treat this as the earliest warning you get — the units are built before the AI "
                           "decides to declare. Match the build, or shore up the shared border now.",
            why=f"Turn {t}: {len(mil)} of {r.name}'s {len(cities)} cities are producing military units "
                f"({', '.join(humanize(c.item) for c in mil)}).",
            turn=t, subject_player=r.id,
        ))
    return out
```

- [ ] **Step 5: Register it**

`civ7_advisor/advisors/checklist.py:6` → `ADVISOR_ORDER = {"threat": 0, "victory": 1, "economy": 2, "production": 3}`.
`civ7_advisor/advisors/__init__.py`: import `production` alongside the others, `ADVISORS = (threat, victory, economy, production)`, add `"production"` to `__all__`.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_production_advisor.py tests/test_checklist.py -q` then `uv run pytest -q`. Expected: all pass, zero warnings. (`test_fixture_end_to_end` in `tests/test_e2e.py` asserts the advisor set equals `{"threat","victory","economy"}` on the v1 fixture — production is silent there, so that assertion still holds; if it does not, the production advisor is emitting without queue data, which is a bug.)

- [ ] **Step 7: Commit**

```bash
git add civ7_advisor/advisors/production.py civ7_advisor/advisors/base.py civ7_advisor/advisors/checklist.py civ7_advisor/advisors/__init__.py tests/test_production_advisor.py tests/test_checklist.py
git commit -m "Add production advisor: own queue, worst-gap mismatch, rival military build-up"
```

---

### Task 7: Threat advisor — combat record and peace detection

**Files:**
- Modify: `civ7_advisor/advisors/threat.py:22-38` (RivalThreat), `:48-98` (`_summarize_rival`), `:125-210` (`advise`)
- Modify: `docs/superpowers/specs/2026-09-07-civ7-advisor-v2-design.md` §4.1 (one bullet, see Step 5)
- Test: `tests/test_threat.py` (append)

**Interfaces:**
- Consumes: `GameState.combats` (`CombatRow.parties()`, `.loser()`, `.attacker/.defender.kind`, `.x/.y`), `GameState.peace_between(a, b)`, `humanize` from `.base`.
- Produces: `RivalThreat` gains `peace_since: int | None`, `fights: int`, `fights_won: int`, `fights_lost: int`, `latest_combat: tuple[int, int, int, str, str] | None` (turn, x, y, your unit kind, their unit kind). `at_war_since` becomes `None` when a Peace deal between the human and that rival is dated **at or after** the declaration. New insights `threat.peace.{r}` INFO/FAIR and `threat.combat_record.{r}` WARN/FAIR (INFO when not losing). All existing `RivalThreat` fields, ids and provenances unchanged.
- **Ruling:** damage figures (`att_dmg`, `def_dmg`, health) are **not** quoted — their direction is unpinned until Task 11. The combat record reports counts, the latest fight's turn/tile, and the two unit kinds.

- [ ] **Step 1: Append the failing tests**

Append to `tests/test_threat.py` (extend the factories import to include `combat, deal`):
```python
def test_peace_at_or_after_the_declaration_clears_war_and_is_fair():
    s = game_state(turn=20)
    s.intents = [executed_war(15, 1)]
    s.peace_turns = {frozenset({0, 1}): 17}
    got = ids(threat.advise(s))
    assert "threat.at_war.1" not in got
    peace = got["threat.peace.1"]
    assert peace.severity is Severity.INFO and peace.provenance is Provenance.FAIR and "turn 17" in peace.why


def test_peace_on_the_declaration_turn_also_clears():
    s = game_state(turn=20)
    s.intents = [executed_war(15, 1)]
    s.peace_turns = {frozenset({0, 1}): 15}
    assert "threat.at_war.1" not in ids(threat.advise(s))


def test_peace_before_the_declaration_does_not_clear_and_is_not_announced():
    s = game_state(turn=20)
    s.intents = [executed_war(15, 1)]
    s.peace_turns = {frozenset({0, 1}): 12}
    got = ids(threat.advise(s))
    assert "threat.at_war.1" in got and "threat.peace.1" not in got


def test_peace_with_a_third_party_is_ignored():
    s = game_state(turn=20, rivals={1: "A", 2: "B"})
    s.intents = [executed_war(15, 1)]
    s.peace_turns = {frozenset({1, 2}): 17}
    assert "threat.at_war.1" in ids(threat.advise(s))


def test_combat_record_counts_only_by_destroyed_side():
    s = game_state(turn=20)
    s.combats = [
        combat(18, 0, 1, destroyed="Attacker"),   # your attacker died
        combat(19, 1, 0, destroyed="Attacker"),   # their attacker died
        combat(20, 0, 1, destroyed=None),         # nobody died
        combat(9, 0, 1, destroyed="Attacker"),    # outside RECENT_TURNS
    ]
    i = ids(threat.advise(s))["threat.combat_record.1"]
    assert i.severity is Severity.INFO and i.provenance is Provenance.FAIR
    assert "3 fights" in i.why and "you lost 1" in i.why and "they lost 1" in i.why and "holding" in i.title


def test_combat_record_warns_when_you_are_losing_and_orients_units_to_you():
    s = game_state(turn=20)
    s.combats = [
        combat(18, 0, 1, destroyed="Attacker"),
        combat(20, 1, 0, destroyed="Defender", att_kind="UNIT_SPEARMAN", def_kind="UNIT_WARRIOR", x=62, y=32),
    ]
    i = ids(threat.advise(s))["threat.combat_record.1"]
    assert i.severity is Severity.WARN and "losing" in i.title
    assert "you lost 2" in i.why and "turn 20 at (62,32), your Warrior against their Spearman" in i.why


def test_combat_record_ignores_fights_with_third_parties():
    s = game_state(turn=20, rivals={1: "A", 2: "B"})
    s.combats = [combat(20, 2, 1, destroyed="Attacker"), combat(20, 0, 2, destroyed="Attacker")]
    got = ids(threat.advise(s))
    assert "threat.combat_record.1" not in got and "threat.combat_record.2" in got


def test_summary_carries_the_new_fields_on_the_v1_fixture(fixture_state):
    by_player = {r.player: r for r in threat.summarize(fixture_state)}
    assert all(r.fights == 0 and r.latest_combat is None and r.peace_since is None for r in by_player.values())
    assert by_player[4].at_war_since == 80  # no deals in the v1 fixture, so the war stands
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_threat.py -q`
Expected: the new tests FAIL (`KeyError: 'threat.peace.1'`, `KeyError: 'threat.combat_record.1'`, `AttributeError: 'RivalThreat' object has no attribute 'fights'`); the existing ones still pass.

- [ ] **Step 3: Extend `RivalThreat` and `_summarize_rival`**

In `civ7_advisor/advisors/threat.py`: import `humanize` from `.base`. Append to `RivalThreat` after `target_box`:
```python
    peace_since: int | None        # Peace deal with the human dated at/after the last declaration
    fights: int                    # CombatLog rows between the two within RECENT_TURNS
    fights_won: int                # ... in which the rival's combatant was destroyed
    fights_lost: int               # ... in which the human's combatant was destroyed
    latest_combat: tuple[int, int, int, str, str] | None  # (turn, x, y, your unit kind, their unit kind)
```
In `_summarize_rival`, directly after `at_war_since = max(...)` (line 59) add:
```python
    peace = state.peace_between(state.HUMAN, rival.id)
    peace_since = None
    if at_war_since is not None and peace is not None and peace >= at_war_since:
        peace_since, at_war_since = peace, None
```
After the Historian `fights`/`latest` block (line 75) add:
```python
    combats = [
        c for c in state.combats
        if c.turn in window and c.parties() == frozenset({state.HUMAN, rival.id})
    ]
    latest_combat = None
    newest = max(combats, key=lambda c: c.turn, default=None)
    if newest is not None:
        mine, theirs = ((newest.attacker, newest.defender) if newest.att_player == state.HUMAN
                        else (newest.defender, newest.attacker))
        latest_combat = (newest.turn, newest.x, newest.y, mine.kind, theirs.kind)
```
and pass the new fields in the `return RivalThreat(...)`:
```python
        peace_since=peace_since, fights=len(combats),
        fights_won=sum(c.loser() == rival.id for c in combats),
        fights_lost=sum(c.loser() == state.HUMAN for c in combats),
        latest_combat=latest_combat,
```

- [ ] **Step 4: Emit the two insights**

In `advise`, after the `at_war`/`war_intent` `if/elif` block (after line 154) add:
```python
        if r.peace_since is not None:
            out.append(Insight(
                id=f"threat.peace.{r.player}", severity=Severity.INFO, provenance=Provenance.FAIR,
                title=f"Peace with {r.name}",
                recommendation="Use the breathing room: heal, re-garrison, and decide whether the border "
                               "needs walls before the next declaration.",
                why=f"A Peace deal between you and {r.name} was recorded on turn {r.peace_since}, "
                    f"after the war declaration.",
                **common,
            ))

        if r.fights:
            turn, x, y, mine, theirs = r.latest_combat
            losing = r.fights_lost > r.fights_won
            state_word = "losing" if losing else "winning" if r.fights_won > r.fights_lost else "holding"
            out.append(Insight(
                id=f"threat.combat_record.{r.player}",
                severity=Severity.WARN if losing else Severity.INFO, provenance=Provenance.FAIR,
                title=f"You are {state_word} the fighting with {r.name}",
                recommendation=("Stop trading units one for one: pull back to heal, fortify on defensible "
                                "terrain, and bring ranged support before re-engaging." if losing else
                                "Keep the pressure but do not overextend; a unit lost to a counter-attack "
                                "costs more than it just won."),
                why=f"Last {RECENT_TURNS} turns: {r.fights} fights with {r.name} — you lost {r.fights_lost} "
                    f"units, they lost {r.fights_won}. Latest: turn {turn} at ({x},{y}), your "
                    f"{humanize(mine)} against their {humanize(theirs)}.",
                **common,
            ))
```

- [ ] **Step 5: Align the spec bullet**

In `docs/superpowers/specs/2026-09-07-civ7-advisor-v2-design.md` §4.1, replace the `threat.combat_record.{r}` bullet with:
```
- `threat.combat_record.{r}` WARN/FAIR when you are losing, INFO otherwise —
  the after-action read from `CombatLog` within `RECENT_TURNS`: fights, your
  losses, their losses, and the latest fight's turn, tile and unit kinds
  ("your Warrior against their Spearman at (62,32)"). Damage figures are not
  quoted until the fixture task pins the log's damage-direction semantics.
  Complements, and does not replace, the Historian-based kill count.
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_threat.py -q` then `uv run pytest -q`. Expected: all pass, zero warnings.

- [ ] **Step 7: Commit**

```bash
git add civ7_advisor/advisors/threat.py tests/test_threat.py docs/superpowers/specs/2026-09-07-civ7-advisor-v2-design.md
git commit -m "Threat advisor: combat record from CombatLog and peace detection from deals"
```

---

### Task 8: Intel feed

**Files:**
- Create: `civ7_advisor/advisors/intel.py`
- Test: `tests/test_intel.py`

**Interfaces:**
- Consumes: `GameState.gossip`, `.diplomacy_events`, `.combats`, `.deals`, `.names`, `.players`; `humanize`, `Provenance` from `.base`.
- Produces: `IntelEvent(turn: int, kind: str, provenance: Provenance, text: str, players: tuple[int, ...], x: int | None, y: int | None, source: str)` frozen; `feed(state) -> list[IntelEvent]` newest first, then combat < deal < diplomacy < gossip, then text. `intel` is **not** an advisor (no `advise`, not in `ADVISORS`).

- [ ] **Step 1: Write the failing tests**

`tests/test_intel.py`:
```python
from civ7_advisor.advisors import intel
from civ7_advisor.advisors.base import Provenance
from civ7_advisor.state.models import GameState
from civ7_advisor.state.names import NameResolver
from tests.factories import combat, deal, diplo_event, game_state, gossip_row


def _state():
    s = game_state(turn=20, rivals={1: "Ibn Battuta", 4: "José Rizal"})
    s.names = NameResolver.build({1: "Ibn Battuta", 4: "José Rizal"}, ["LOC_CITY_NAME_MAURYA1"])
    return s


def test_gossip_is_fair_and_resolves_names():
    s = _state()
    s.gossip = [gossip_row(20, "Alexander", "Maurya", "GOSSIP_UNIT_DESTROYED", 63, 31, "Warrior"),
                gossip_row(19, "Jose Rizal", "Maya", "GOSSIP_CITY_FOUNDED", -1, -1)]
    a, b = intel.feed(s)
    assert (a.kind, a.provenance, a.players, a.x, a.y) == ("gossip", Provenance.FAIR, (0,), 63, 31)
    assert a.text == "You: Unit Destroyed — Warrior"
    assert (b.players, b.x, b.y) == ((4,), None, None) and b.text.startswith("José Rizal: City Founded")


def test_unresolved_gossip_keeps_the_logged_name():
    s = _state()
    s.gossip = [gossip_row(20, "Napoleon", "France")]
    [e] = intel.feed(s)
    assert e.players == () and e.text.startswith("Napoleon (France):")


def test_diplomacy_combat_and_deals_follow_the_party_rule():
    s = _state()
    s.diplomacy_events = [diplo_event(20, 0, 1, "Denounce"), diplo_event(20, 1, 4, "Denounce")]
    s.combats = [combat(20, 0, 4, destroyed="Attacker"), combat(20, 1, 4, destroyed="Defender")]
    s.deals = [deal(20, 4, 0, "Peace"), deal(20, 1, 4, "Open Borders")]
    by_text = {e.text: e for e in intel.feed(s)}
    assert by_text["You → Ibn Battuta: Denounce"].provenance is Provenance.FAIR
    assert by_text["Ibn Battuta → José Rizal: Denounce"].provenance is Provenance.ORACLE
    assert by_text["Your Warrior attacked José Rizal's Spearman — Warrior destroyed"].provenance is Provenance.FAIR
    assert by_text["Ibn Battuta's Warrior attacked José Rizal's Spearman — Spearman destroyed"].provenance is Provenance.ORACLE
    assert by_text["José Rizal → You: Peace"].provenance is Provenance.FAIR
    assert by_text["Ibn Battuta → José Rizal: Open Borders"].provenance is Provenance.ORACLE


def test_feed_is_newest_first_then_combat_deal_diplomacy_gossip():
    s = _state()
    s.gossip = [gossip_row(20, "Alexander", "Maurya")]
    s.deals = [deal(20, 4, 0)]
    s.combats = [combat(19, 0, 4), combat(20, 0, 4)]
    s.diplomacy_events = [diplo_event(20, 0, 1)]
    kinds = [(e.turn, e.kind) for e in intel.feed(s)]
    assert kinds == [(20, "combat"), (20, "deal"), (20, "diplomacy"), (20, "gossip"), (19, "combat")]


def test_empty_state_has_an_empty_feed():
    assert intel.feed(GameState()) == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_intel.py -q`
Expected: FAIL with `ImportError: cannot import name 'intel'`.

- [ ] **Step 3: Write the feed**

`civ7_advisor/advisors/intel.py`:
```python
"""One chronological feed of what happened — gossip, diplomacy, combat, deals — each labelled.

Not an advisor: it emits no Insights. It gives fair mode real substance, because gossip and the
diplomacy the human took part in are things the game itself showed the player.
"""
from __future__ import annotations

from dataclasses import dataclass

from civ7_advisor.state.models import GameState

from .base import Provenance, humanize

KIND_ORDER = {"combat": 0, "deal": 1, "diplomacy": 2, "gossip": 3}


@dataclass(frozen=True)
class IntelEvent:
    turn: int
    kind: str                 # combat | deal | diplomacy | gossip
    provenance: Provenance
    text: str
    players: tuple[int, ...]  # resolved ids involved; empty when a gossip name could not be resolved
    x: int | None
    y: int | None
    source: str               # the log file the event came from


def _name(state: GameState, pid: int) -> str:
    if pid == state.HUMAN:
        return "You"
    player = state.players.get(pid)
    return player.name if player else f"Player {pid}"


def _poss(state: GameState, pid: int) -> str:
    """Possessive form: 'your' for the human, "<Name>'s" otherwise (capitalised by the caller if first)."""
    return "your" if pid == state.HUMAN else f"{_name(state, pid)}'s"


def _party(state: GameState, *players: int) -> Provenance:
    return Provenance.FAIR if state.HUMAN in players else Provenance.ORACLE


def feed(state: GameState) -> list[IntelEvent]:
    events: list[IntelEvent] = []
    for g in state.gossip:
        pid = state.names.player_for(g.leader, g.civilization) if state.names else None
        who = _name(state, pid) if pid is not None else f"{g.leader} ({g.civilization})"
        text = f"{who}: {humanize(g.type)}" + (f" — {g.detail}" if g.detail else "")
        events.append(IntelEvent(g.turn, "gossip", Provenance.FAIR, text, (pid,) if pid is not None else (),
                                 g.x if g.x >= 0 else None, g.y if g.y >= 0 else None, "Game_Gossip.csv"))
    for d in state.diplomacy_events:
        text = f"{_name(state, d.initiator)} → {_name(state, d.recipient)}: {d.action}"
        if d.details:
            text += f" — {d.details}"
        events.append(IntelEvent(d.turn, "diplomacy", _party(state, d.initiator, d.recipient), text,
                                 (d.initiator, d.recipient), None, None, "DiplomacySummary.csv"))
    for c in state.combats:
        outcome = {"Attacker": f"{humanize(c.attacker.kind)} destroyed",
                   "Defender": f"{humanize(c.defender.kind)} destroyed"}.get(c.destroyed, "no unit destroyed")
        text = (f"{_poss(state, c.att_player)} {humanize(c.attacker.kind)} attacked "
                f"{_poss(state, c.def_player)} {humanize(c.defender.kind)} — {outcome}")
        text = text[0].upper() + text[1:]
        events.append(IntelEvent(c.turn, "combat", _party(state, c.att_player, c.def_player), text,
                                 (c.att_player, c.def_player), c.x, c.y, "CombatLog.csv"))
    for d in state.deals:
        text = f"{_name(state, d.from_player)} → {_name(state, d.to_player)}: {d.kind}"
        events.append(IntelEvent(d.turn, "deal", _party(state, d.from_player, d.to_player), text,
                                 (d.from_player, d.to_player), None, None, "DiplomacyDeals.log"))
    return sorted(events, key=lambda e: (-e.turn, KIND_ORDER[e.kind], e.text))
```
Also add `intel` to the imports and `__all__` in `civ7_advisor/advisors/__init__.py` — but **not** to `ADVISORS` (it has no `advise`).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_intel.py tests/test_checklist.py -q` then `uv run pytest -q`. Expected: all pass, zero warnings.

- [ ] **Step 5: Commit**

```bash
git add civ7_advisor/advisors/intel.py civ7_advisor/advisors/__init__.py tests/test_intel.py
git commit -m "Add the Intel feed: gossip, diplomacy, combat and deals with per-event provenance"
```

---

### Task 9: Archiver — mirror the logs before the game deletes them

**Files:**
- Create: `civ7_advisor/archive.py`
- Modify: `civ7_advisor/store.py` (constructor, archive hook), `civ7_advisor/api/app.py:23-24` (`archive_root` parameter), `civ7_advisor/cli.py` (flags, `archive list`)
- Test: `tests/test_archive.py`, `tests/test_store.py` (append), `tests/test_cli.py` (append)

**Interfaces:**
- Consumes: `RawLogs` (its `stats`, `victories`, `build_queue`), `LOG_FILES`, `INDEPENDENT_KEY` from `state/build.py`.
- Produces: `archive.DEFAULT_ARCHIVE_ROOT = Path.home() / ".civ7-advisor" / "archive"`, `archive.MANIFEST = "archived.json"`, `archive.game_key(raw: RawLogs) -> str | None`, `archive.archive_logs(logs_dir: Path, dest: Path, names: Iterable[str]) -> list[str]` (names copied); `Store(logs_dir, archive_root: Path | None = None)`; `create_app(logs_dir, poll_interval=1.0, archive_root: Path | None = None)`; CLI flags `--no-archive`, `--archive-dir PATH`, and subcommand `civ7-advisor archive list [--archive-dir PATH]`.
- **Why the layout is `<root>/<game-key>/<session>/`:** the game deletes its logs on launch and regenerates them *from the loaded save's current turn*, so after a relaunch the new files cover a later turn range than the archived ones. One session directory per log-directory lifetime means a newer, shorter file never overwrites an older, longer one. `game_key` is a hash of the leader line-up, the human's civilization and the player-id set — stable across relaunches of the same save, which the turn range is not.
- **Guarantees:** writes only under `dest`; refuses a `dest` inside `logs_dir`; never opens a source for writing (`shutil.copy2`); a failure inside the archiver is logged and never breaks a rebuild.

- [ ] **Step 1: Write the failing tests**

`tests/test_archive.py`:
```python
import shutil
from pathlib import Path

import pytest

from civ7_advisor.archive import MANIFEST, archive_logs, game_key
from civ7_advisor.ingest.load import LOG_FILES, RawLogs, load_logs
from civ7_advisor.ingest.production import BuildQueueRow
from civ7_advisor.ingest.readers import StatsRow, VictoryRow


def _stats(turn, player):
    return StatsRow(turn, player, 1, 0, 3, 0, 1, 2, 1, 2, 0, 5, 1, 10.0, 1, 1, 1, 1, 1, 1, 0)


def _raw(leaders=("LOC_LEADER_CONFUCIUS_NAME", "LOC_LEADER_CATHERINE_NAME"), turns=(1, 2), civ="MAURYA"):
    return RawLogs(
        stats=[_stats(t, p) for t in turns for p in (0, 1, 2)],
        victories=[VictoryRow(turns[0], i + 1, key, "SCIENCE", "Following", 50) for i, key in enumerate(leaders)],
        build_queue=[BuildQueueRow(turns[0], 0, f"LOC_CITY_NAME_{civ}1", 5.0, "UNIT_WARRIOR", 0.0, 30.0, 0.0)],
    )


def test_game_key_is_stable_across_turn_ranges_and_none_without_stats():
    assert game_key(RawLogs()) is None
    assert game_key(_raw(turns=(1, 2))) == game_key(_raw(turns=(40, 50)))  # a relaunch resumes mid-game


def test_game_key_changes_with_the_leader_lineup_or_human_civ():
    base = game_key(_raw())
    assert game_key(_raw(leaders=("LOC_LEADER_CONFUCIUS_NAME", "LOC_LEADER_NAPOLEON_NAME"))) != base
    assert game_key(_raw(civ="HAN")) != base


def test_archive_logs_copies_only_existing_listed_files_and_is_idempotent(tmp_path: Path, fixture_dir: Path):
    dest = tmp_path / "root" / "game" / "session"
    before = {n: (fixture_dir / n).stat() for n in LOG_FILES if (fixture_dir / n).exists()}
    copied = archive_logs(fixture_dir, dest, LOG_FILES)
    assert sorted(copied) == sorted(before)                      # the seven v1 files; missing ones skipped
    assert (dest / MANIFEST).is_file()
    assert archive_logs(fixture_dir, dest, LOG_FILES) == []      # nothing changed -> nothing copied
    after = {n: (fixture_dir / n).stat() for n in before}
    assert all((before[n].st_mtime_ns, before[n].st_size) == (after[n].st_mtime_ns, after[n].st_size) for n in before)
    assert not set(p.name for p in fixture_dir.iterdir()) - set(before) - {"README.md"}  # source dir untouched


def test_archive_logs_recopies_a_changed_file(tmp_path: Path, fixture_dir: Path):
    src = tmp_path / "logs"
    shutil.copytree(fixture_dir, src)
    dest = tmp_path / "root" / "g" / "s"
    archive_logs(src, dest, LOG_FILES)
    with (src / "Historian.csv").open("a") as fh:
        fh.write("UNIT_KILLED, AGE_ANTIQUITY, 83, 1, 1, 0, 4, Warrior, NO_CONSTRUCTIBLE\n")
    assert archive_logs(src, dest, LOG_FILES) == ["Historian.csv"]
    assert (dest / "Historian.csv").read_text().endswith("NO_CONSTRUCTIBLE\n")


def test_archive_logs_refuses_a_destination_inside_the_logs_dir(tmp_path: Path):
    with pytest.raises(ValueError, match="inside"):
        archive_logs(tmp_path, tmp_path / "archive", LOG_FILES)
```

Append to `tests/test_store.py`:
```python
def test_store_archives_under_game_and_session_and_starts_a_new_session_after_a_wipe(tmp_path, fixture_dir):
    import shutil
    from civ7_advisor.ingest.load import LOG_FILES
    logs = tmp_path / "logs"
    shutil.copytree(fixture_dir, logs)
    root = tmp_path / "archive"
    store = Store(logs, archive_root=root)
    store.rebuild()
    games = list(root.iterdir())
    assert len(games) == 1
    sessions = sorted(games[0].iterdir())
    assert len(sessions) == 1 and (sessions[0] / "Player_Stats.csv").is_file()
    for name in LOG_FILES:                       # the game relaunches: every log vanishes
        (logs / name).unlink(missing_ok=True)
    store.rebuild()
    shutil.copytree(fixture_dir, logs, dirs_exist_ok=True)  # ... and a save is loaded again
    store.rebuild()
    assert len(sorted(games[0].iterdir())) == 2


def test_store_without_archive_root_writes_nothing(tmp_path, fixture_dir):
    root = tmp_path / "archive"
    Store(fixture_dir).rebuild()
    assert not root.exists()


def test_archiver_failure_does_not_break_rebuild(tmp_path, fixture_dir, monkeypatch):
    import civ7_advisor.store as store_mod
    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(store_mod, "archive_logs", boom)
    state = Store(fixture_dir, archive_root=tmp_path / "archive").rebuild()
    assert state.latest_turn == 82
```

Append to `tests/test_cli.py`:
```python
def test_archive_flags_reach_create_app(fixture_dir, monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(cli.uvicorn, "run", lambda app, host, port, log_level: None)
    monkeypatch.setattr(cli, "create_app", lambda logs_dir, poll, archive_root=None: seen.update(root=archive_root) or object.__new__(type("A", (), {"title": "x"})))
    cli.main(["--logs-dir", str(fixture_dir), "--no-archive"])
    assert seen["root"] is None
    cli.main(["--logs-dir", str(fixture_dir), "--archive-dir", str(tmp_path / "arc")])
    assert seen["root"] == tmp_path / "arc"


def test_archive_list_prints_sessions(tmp_path, capsys):
    from civ7_advisor.archive import MANIFEST
    session = tmp_path / "arc" / "abc123def456" / "20260907T171100"
    session.mkdir(parents=True)
    (session / MANIFEST).write_text('{"updated": "2026-09-07T17:11:00", "files": ["Player_Stats.csv"]}')
    assert cli.main(["archive", "list", "--archive-dir", str(tmp_path / "arc")]) == 0
    out = capsys.readouterr().out
    assert "abc123def456" in out and "20260907T171100" in out and "1 file" in out


def test_archive_list_with_no_archive_is_quiet(tmp_path, capsys):
    assert cli.main(["archive", "list", "--archive-dir", str(tmp_path / "none")]) == 0
    assert "No archive" in capsys.readouterr().out
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_archive.py tests/test_store.py tests/test_cli.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'civ7_advisor.archive'` and `TypeError: Store.__init__() got an unexpected keyword argument 'archive_root'`.

- [ ] **Step 3: Write the archiver**

`civ7_advisor/archive.py`:
```python
"""Mirror the game's logs into a directory of our own.

Civ VII deletes its entire Logs/ directory on every launch and regenerates it from the loaded
save's current turn, so without this a game's history is lost the moment the game restarts.
This module is the ONLY place the advisor writes to disk, and it writes only under `dest`.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import time
from pathlib import Path
from typing import Iterable

from civ7_advisor.ingest.load import RawLogs
from civ7_advisor.state.build import INDEPENDENT_KEY

DEFAULT_ARCHIVE_ROOT = Path.home() / ".civ7-advisor" / "archive"
MANIFEST = "archived.json"


def game_key(raw: RawLogs) -> str | None:
    """A stable id for a game: the rival leader line-up, the human's civilization and the
    player-id set. Unlike a turn range, this survives a relaunch of the same save."""
    if not raw.stats:
        return None
    leaders = sorted({r.owner_key for r in raw.victories if r.owner_key != INDEPENDENT_KEY})
    civs = sorted({q.city.removeprefix("LOC_CITY_NAME_").rstrip("0123456789")
                   for q in raw.build_queue if q.player == 0})
    players = sorted({r.player for r in raw.stats})
    blob = json.dumps([leaders, civs[:1], players])
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:12]


def archive_logs(logs_dir: Path, dest: Path, names: Iterable[str]) -> list[str]:
    """Copy each named log into `dest`, skipping files that are unchanged (same size and
    mtime) since the last copy. Returns the names copied. Never touches `logs_dir`."""
    logs_dir, dest = logs_dir.resolve(), dest.resolve()
    if dest == logs_dir or logs_dir in dest.parents:
        raise ValueError(f"archive destination {dest} is inside the logs directory {logs_dir}")
    dest.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    for name in names:
        src, dst = logs_dir / name, dest / name
        if not src.is_file():
            continue
        s = src.stat()
        if dst.exists():
            d = dst.stat()
            if (d.st_size, d.st_mtime_ns) == (s.st_size, s.st_mtime_ns):
                continue
        shutil.copy2(src, dst)  # copy2 preserves mtime, which is what makes the skip above work
        copied.append(name)
    manifest = {"updated": time.strftime("%Y-%m-%dT%H:%M:%S"), "logs_dir": str(logs_dir),
                "files": sorted(p.name for p in dest.iterdir() if p.name != MANIFEST)}
    (dest / MANIFEST).write_text(json.dumps(manifest, indent=2))
    return copied
```

- [ ] **Step 4: Hook it into `Store` and `create_app`**

Rewrite `civ7_advisor/store.py` as:
```python
"""Owns the current GameState and ranked insights; rebuilds, archives, and fans out change events."""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from pathlib import Path

from civ7_advisor.advisors import Insight, run_all
from civ7_advisor.archive import archive_logs, game_key
from civ7_advisor.ingest.load import LOG_FILES, load_logs
from civ7_advisor.state.build import build_state
from civ7_advisor.state.models import GameState

log = logging.getLogger(__name__)


class Store:
    def __init__(self, logs_dir: Path, archive_root: Path | None = None) -> None:
        self.logs_dir = logs_dir
        self.archive_root = archive_root
        self.state: GameState | None = None
        self.insights: list[Insight] = []
        self._lock = threading.Lock()
        self._subscribers: set[asyncio.Queue] = set()
        self._session: str | None = None  # one archive session per life of the logs directory

    def rebuild(self) -> GameState:
        """Re-read every log, archive it, and recompute advice. Safe to call from a worker thread."""
        raw = load_logs(self.logs_dir)
        state = build_state(raw)
        insights = run_all(state)
        with self._lock:
            self.state, self.insights = state, insights
        self._archive(raw)
        return state

    def _archive(self, raw) -> None:
        if self.archive_root is None:
            return
        if not raw.stats:            # the directory was wiped (game relaunch): next data is a new session
            self._session = None
            return
        try:
            key = game_key(raw)
            if self._session is None:
                self._session = time.strftime("%Y%m%dT%H%M%S")
            archive_logs(self.logs_dir, self.archive_root / key / self._session, LOG_FILES)
        except Exception:            # archiving must never cost the player their advice
            log.exception("archiving failed; continuing without it")

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
In `civ7_advisor/api/app.py`, change the factory signature and construction to `def create_app(logs_dir: Path, poll_interval: float = 1.0, archive_root: Path | None = None) -> FastAPI:` and `store = Store(logs_dir, archive_root)`.

- [ ] **Step 5: Extend the CLI**

Rewrite `civ7_advisor/cli.py`'s `main` (keep `DEFAULT_LOGS_DIR`):
```python
import json
from civ7_advisor.archive import DEFAULT_ARCHIVE_ROOT, MANIFEST


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["archive"]:
        return _archive_command(argv[1:])

    parser = argparse.ArgumentParser(
        prog="civ7-advisor",
        description="Second-screen turn advisor for Civilization VII. Reads the game's own log "
                    "files; never writes to them. Archives them under ~/.civ7-advisor because the "
                    "game deletes its logs on launch.",
    )
    parser.add_argument("--logs-dir", type=Path, default=DEFAULT_LOGS_DIR,
                        help=f"Civ VII Logs directory (default: {DEFAULT_LOGS_DIR})")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--poll-interval", type=float, default=1.0,
                        help="seconds between checks of the log files (default 1.0)")
    parser.add_argument("--archive-dir", type=Path, default=DEFAULT_ARCHIVE_ROOT,
                        help=f"where to mirror the logs (default: {DEFAULT_ARCHIVE_ROOT})")
    parser.add_argument("--no-archive", action="store_true", help="do not mirror the logs anywhere")
    args = parser.parse_args(argv)

    if not args.logs_dir.is_dir():
        print(
            f"Civ VII log directory not found: {args.logs_dir}\n"
            f"Start the game once so it creates the folder, or pass --logs-dir <path>.",
            file=sys.stderr,
        )
        return 2

    archive_root = None if args.no_archive else args.archive_dir
    app = create_app(args.logs_dir, args.poll_interval, archive_root=archive_root)
    where = f"archiving to {archive_root}" if archive_root else "archiving off"
    print(f"Civ VII Advisor -> http://{args.host}:{args.port}  (reading {args.logs_dir}; {where})")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


def _archive_command(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="civ7-advisor archive")
    parser.add_argument("action", choices=["list"])
    parser.add_argument("--archive-dir", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    args = parser.parse_args(argv)
    root = args.archive_dir
    if not root.is_dir():
        print(f"No archive at {root}")
        return 0
    for game in sorted(p for p in root.iterdir() if p.is_dir()):
        for session in sorted(p for p in game.iterdir() if p.is_dir()):
            manifest = session / MANIFEST
            files, updated = [], "?"
            if manifest.is_file():
                data = json.loads(manifest.read_text())
                files, updated = data.get("files", []), data.get("updated", "?")
            n = len(files)
            print(f"{game.name}  {session.name}  {n} file{'s' if n != 1 else ''}  updated {updated}")
    return 0
```
Keep the existing `test_server_is_started_with_parsed_options` green: its fake `create_app` must accept the new keyword — update that test's lambda to `lambda logs_dir, poll, archive_root=None: ...` if it does not already.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_archive.py tests/test_store.py tests/test_cli.py tests/test_api.py -q` then `uv run pytest -q`. Expected: all pass, zero warnings. Then a manual check: `uv run civ7-advisor --logs-dir tests/fixtures/logs_82turns --archive-dir /tmp/civ7-arc-check` for a few seconds, Ctrl-C, then `uv run civ7-advisor archive list --archive-dir /tmp/civ7-arc-check` prints one session with 7 files; `rm -rf /tmp/civ7-arc-check`. Confirm the fixture directory's file mtimes are unchanged.

- [ ] **Step 7: Commit**

```bash
git add civ7_advisor/archive.py civ7_advisor/store.py civ7_advisor/api/app.py civ7_advisor/cli.py tests/test_archive.py tests/test_store.py tests/test_cli.py
git commit -m "Archive the logs per game and session, because Civ VII deletes them on launch"
```

---

### Task 10: API and dashboard — Intel tab, production, peace, wipe copy

**Files:**
- Modify: `civ7_advisor/api/serialize.py`, `civ7_advisor/api/app.py` (`/api/intel`, `?oracle=` on `/api/state`)
- Modify: `civ7_advisor/web/index.html`, `civ7_advisor/web/app.js`, `civ7_advisor/web/style.css`, `README.md`
- Modify: `tests/test_api.py` (append)

**Interfaces:**
- Consumes: `production.queues`, `production.rival_military_share`, `intel.feed`, `IntelEvent`, `RivalThreat.peace_since`.
- Produces: `serialize.state_to_dict(state, oracle: bool = True)` adds `"production": {"human": [CityQueue dicts], "rivals": [ {"player", "name", "military_share", "cities": [CityQueue dicts]} ] | None}` (`rivals` is `None` when `oracle` is false); `serialize.intel_to_dict(e) -> dict` (provenance as value); `serialize.INTEL_LIMIT = 300`; `GET /api/state?oracle=0|1`, `GET /api/intel?oracle=0|1` (503 before the first rebuild; with `oracle=0` only FAIR events). Page: a fifth tab `data-tab="intel"` labelled "Intel"; sections `#intel-feed`, `#production-table`, `#rival-production-table`; `<p id="wipe">` copy shown when every log is unreadable.
- **Gating decision:** the two new surfaces are gated **server-side** by `?oracle=` and pinned by Python tests; the existing threats/victory column gating stays client-side and pinned as before. `app.js` passes `state.showOracle` on every fetch and the toggle triggers a refetch.

- [ ] **Step 1: Append the failing tests**

Append to `tests/test_api.py`:
```python
def test_state_has_a_production_block_gated_by_the_oracle_flag(client):
    body = client.get("/api/state").json()
    assert body["production"] == {"human": [], "rivals": []}      # the v1 fixture has no CityBuildQueue.csv
    body = client.get("/api/state?oracle=0").json()
    assert body["production"]["rivals"] is None and body["production"]["human"] == []


def _v2_dir(tmp_path: Path, fixture_dir: Path) -> Path:
    import shutil
    d = tmp_path / "logs"
    shutil.copytree(fixture_dir, d)
    (d / "Game_Gossip.csv").write_text(
        "Game Turn, Player, Civilization, Plot X, Plot Y, Type\n"
        "81, Alexander, Maurya, 63, 31, GOSSIP_UNIT_DESTROYED, Warrior\n")
    (d / "CombatLog.csv").write_text(
        "Turn, SourceType, Location, AttPlayer, DefPlayer, CombatType, Attacker, Defender, AttStr, DefStr, "
        "AttStrMod, DefStrMod, AttDmg, DefDmg, Destroyed, HealAmount, attHealth, defHealth\n"
        "81,Unit vs Unit,(63)(30),0,4,Melee,(14)UNIT_WARRIOR,(15)UNIT_SPEARMAN,20,30,0,0,34,12,Attacker,0,(0)100,(88)100\n"
        "81,Unit vs Unit,(10)(10),1,2,Melee,(16)UNIT_WARRIOR,(17)UNIT_WARRIOR,20,20,0,0,30,30,,0,(70)100,(70)100\n")
    (d / "DiplomacyDeals.log").write_text(
        "Turn 80, Incoming for player 4 and 0\n"
        ", Item ID 1, from player 4, to player 0, type Peace, subType 1 (), value type , amount 0, duration 1\n")
    (d / "CityBuildQueue.csv").write_text(
        "Game Turn, Player, City, Production Added, Current Item, Current Production, Production Needed, Overflow\n"
        "82, 0, LOC_CITY_NAME_MAURYA1, 15.0, BUILDING_BRICKYARD, 47.5, 55, 0.0\n"
        "81, 4, LOC_CITY_NAME_MAYA1, 12.0, UNIT_WARRIOR, 0.0, 30, 0.0\n")
    return d


def test_intel_endpoint_filters_oracle_events_server_side(tmp_path: Path, fixture_dir: Path):
    with TestClient(create_app(_v2_dir(tmp_path, fixture_dir), poll_interval=60)) as c:
        events = c.get("/api/intel").json()
        kinds = {(e["kind"], e["provenance"]) for e in events}
        assert ("gossip", "fair") in kinds and ("combat", "fair") in kinds
        assert ("combat", "oracle") in kinds and ("deal", "fair") in kinds
        fair_only = c.get("/api/intel?oracle=0").json()
        assert fair_only and all(e["provenance"] == "fair" for e in fair_only)
        assert [e["turn"] for e in events] == sorted((e["turn"] for e in events), reverse=True)
        state = c.get("/api/state").json()
        assert state["production"]["human"][0]["item"] == "BUILDING_BRICKYARD"
        assert state["production"]["rivals"][0]["name"] == "José Rizal"
        assert state["production"]["rivals"][0]["military_share"] == 1.0
        rizal = next(t for t in state["threats"] if t["player"] == 4)
        assert rizal["at_war_since"] is None and rizal["peace_since"] == 80   # the deal cancelled the war


def test_intel_is_503_before_first_rebuild(fixture_dir: Path):
    assert TestClient(create_app(fixture_dir)).get("/api/intel").status_code == 503


def test_page_has_intel_tab_production_sections_and_wipe_copy(client):
    page = client.get("/").text
    for needle in ('data-tab="intel"', 'id="intel-feed"', 'id="production-table"', 'id="rival-production-table"', 'id="wipe"'):
        assert needle in page, needle
    js = client.get("/static/app.js").text
    assert "/api/intel?oracle=" in js and "/api/state?oracle=" in js
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_api.py -q`
Expected: the new tests FAIL (`KeyError: 'production'`, 404 on `/api/intel`, missing `data-tab="intel"`); the existing ones pass.

- [ ] **Step 3: Serialize the new surfaces**

In `civ7_advisor/api/serialize.py`: change the advisors import to `from civ7_advisor.advisors import Insight, economy, intel, production, threat, victory`; add
```python
INTEL_LIMIT = 300  # newest events returned by /api/intel


def intel_to_dict(e) -> dict:
    d = asdict(e)
    d["provenance"] = e.provenance.value
    return d


def _production(state: GameState, oracle: bool) -> dict:
    qs = production.queues(state)
    human = [asdict(c) for c in qs.get(state.HUMAN, [])]
    if not oracle:
        return {"human": human, "rivals": None}
    shares = production.rival_military_share(state)
    rivals = [
        {"player": r.id, "name": r.name, "military_share": shares.get(r.id),
         "cities": [asdict(c) for c in qs.get(r.id, [])]}
        for r in state.rivals() if qs.get(r.id)
    ]
    return {"human": human, "rivals": rivals}
```
change the signature to `def state_to_dict(state: GameState, oracle: bool = True) -> dict:` and add `"production": _production(state, oracle),` to the returned dict after `"economy"`.

In `civ7_advisor/api/app.py`: import `intel` from `civ7_advisor.advisors` and `intel_to_dict, INTEL_LIMIT` from `.serialize`; change `api_state` to
```python
    @app.get("/api/state")
    def api_state(oracle: int = 1) -> dict:
        if store.state is None:
            raise HTTPException(status_code=503, detail="state not loaded yet")
        return state_to_dict(store.state, oracle=bool(oracle))
```
and add after `api_insights`:
```python
    @app.get("/api/intel")
    def api_intel(oracle: int = 1) -> list[dict]:
        if store.state is None:
            raise HTTPException(status_code=503, detail="state not loaded yet")
        events = intel.feed(store.state)
        if not oracle:
            events = [e for e in events if e.provenance is Provenance.FAIR]
        return [intel_to_dict(e) for e in events[:INTEL_LIMIT]]
```
(import `Provenance` from `civ7_advisor.advisors`).

- [ ] **Step 4: Extend the page**

`civ7_advisor/web/index.html`: after the Economy tab button add
`<button role="tab" id="tab-intel" data-tab="intel" aria-controls="intel" aria-selected="false" tabindex="-1">Intel</button>`;
after `<div class="files" id="files"></div>` add
`<p class="file-warn" id="wipe" hidden>Civ VII clears its logs when it starts — advice resumes once a game is loaded.</p>`;
in the Economy section, before `<h2 class="section-head">Advice</h2>`, add
```html
    <h2 class="section-head">Your production</h2>
    <div id="production-table"></div>
    <h2 class="section-head" id="rival-production-head">Rival production</h2>
    <div id="rival-production-table"></div>
```
and after the Economy section add
```html
  <section class="tab" id="intel" role="tabpanel" aria-labelledby="tab-intel" tabindex="0">
    <h2 class="section-head">What happened</h2>
    <div id="intel-feed"></div>
  </section>
```

`civ7_advisor/web/app.js` — make these changes, keeping everything else as it is:
1. Add `intel: []` to the `state` object, and `const INTEL_ORACLE_OFF = "Oracle off — fights, deals and diplomacy between rivals are hidden.";` beside `ORACLE_OFF`.
2. The oracle checkbox handler calls `refresh()` instead of `render()` (the server now gates by flag).
3. `refresh()` fetches three URLs with the flag:
```js
  async function refresh() {
    const o = state.showOracle ? 1 : 0;
    const [s, i, n] = await Promise.all([
      fetch(`/api/state?oracle=${o}`), fetch("/api/insights"), fetch(`/api/intel?oracle=${o}`),
    ]);
    if (!s.ok || !i.ok || !n.ok) return;
    state.data = await s.json();
    state.insights = await i.json();
    state.intel = await n.json();
    render();
  }
```
4. In `THREATS_ORACLE_COLUMNS`, the "War declared" cell becomes
`cell: (t) => t.at_war_since !== null ? \`turn ${t.at_war_since}\` : t.peace_since !== null ? \`peace turn ${t.peace_since}\` : dim()` (label unchanged, so the column pin holds).
5. `renderFiles(d)` additionally sets `$("#wipe").hidden = !Object.values(d.files).every((f) => !f.ok);`.
6. In `render()`, after the economy table, add the production tables and the intel feed:
```js
    const turnsCell = (c) => c.item === "" ? dim("idle") : c.turns_to_complete === null ? dim("stalled") : c.turns_to_complete;
    const cityName = (key) => key.replace(/^LOC_CITY_NAME_/, "").replace(/_/g, " ");
    const itemName = (key) => key.replace(/^(BUILDING|UNIT|IMPROVEMENT|WONDER)_/, "").replace(/_/g, " ").toLowerCase()
      .replace(/\b\w/g, (ch) => ch.toUpperCase());
    const prod = d.production;
    $("#production-table").replaceChildren(prod.human.length
      ? table([{ label: "City" }, { label: "Building" }, { label: "Turns left", num: true }],
              prod.human.map((c) => [cityName(c.city), c.item ? itemName(c.item) : dim("nothing"), turnsCell(c)]))
      : el("p", "empty", d.files["CityBuildQueue.csv"] && d.files["CityBuildQueue.csv"].ok
          ? "No cities yet." : "No production data — CityBuildQueue.csv is not readable yet."));
    $("#rival-production-head").hidden = prod.rivals === null;
    $("#rival-production-table").replaceChildren(prod.rivals === null ? withheld()
      : table([{ label: "Rival" }, { label: "Cities building military", num: true }, { label: "Share", num: true }],
              prod.rivals.map((r) => [r.name, r.cities.filter((c) => /^UNIT_/.test(c.item)).length,
                                      `${Math.round((r.military_share || 0) * 100)}%`])));

    const feed = el("div", "intel");
    if (!state.intel.length) feed.append(el("p", "empty", seen ? "No events yet." : INTEL_ORACLE_OFF));
    state.intel.forEach((e) => {
      const row = el("div", `intel-row prov-${e.provenance}`);
      row.append(el("span", "intel-turn", String(e.turn)), el("span", "intel-kind", e.kind), el("span", "intel-text", e.text));
      if (e.provenance === "oracle") row.append(el("span", "tag", "intercept"));
      feed.append(row);
    });
    $("#intel-feed").replaceChildren(feed, ...(seen ? [] : [el("p", "oracle-off", INTEL_ORACLE_OFF)]));
```
(The client-side military test above only decides how many cities to count for display; the share itself comes from the server.)

`civ7_advisor/web/style.css` — append, using the existing tokens (`--rule`, `--muted`, `--vellum`) and the same monospace stack the tables' `.num` cells use:
```css
.intel-row { display: grid; grid-template-columns: 3.5rem 6.5rem 1fr auto; gap: .75rem; align-items: baseline;
  padding: .45rem 0; border-bottom: 1px solid var(--rule); }
.intel-turn { font-family: ui-monospace, "SF Mono", Menlo, monospace; font-variant-numeric: tabular-nums; color: var(--muted); }
.intel-kind { color: var(--muted); }
.intel-row.prov-oracle .intel-text { color: var(--vellum); }
@media (max-width: 40rem) { .intel-row { grid-template-columns: 3rem 1fr; } .intel-kind { display: none; } }
```

`README.md`: add an **Intel** paragraph under "Fair vs Oracle" (the fifth tab lists gossip, diplomacy, fights and deals newest first; events between you and a rival are Fair, events between two rivals are Oracle); a **Production** sentence in the run section (the Economy tab now shows what each of your cities is building and, with Oracle on, what rivals are building); and a new section:
```
## The game deletes its logs

Civ VII empties its `Logs/` folder every time it starts and rewrites it from
the turn your save is on. The advisor therefore mirrors the logs it reads to
`~/.civ7-advisor/archive/<game>/<session>/` on every rebuild. Turn it off with
`--no-archive`, point it elsewhere with `--archive-dir PATH`, and list what is
kept with `civ7-advisor archive list`. Nothing is ever written under the
game's own folders.
```

- [ ] **Step 5: Run the tests, then look at the page**

Run: `uv run pytest tests/test_api.py -q` then `uv run pytest -q`. Expected: all pass, zero warnings.
Then start the server on a directory built like `_v2_dir` (copy the v1 fixture to a temp folder and add the four synthetic files from the test above), open it in the browser at 1440×900, and confirm: the Intel tab lists the gossip, both fights and the peace deal newest first with `intercept` on the rival-vs-rival fight; with Oracle off that fight vanishes and the withheld line appears; the Economy tab shows "Maurya1 — Brickyard — 1" under Your production and Rizal at 100% under Rival production (hidden with Oracle off); the threats table's War declared cell for Rizal reads `peace turn 80`; and an empty logs directory shows the `#wipe` sentence. Stop the server.

- [ ] **Step 6: Commit**

```bash
git add civ7_advisor/api/serialize.py civ7_advisor/api/app.py civ7_advisor/web/index.html civ7_advisor/web/app.js civ7_advisor/web/style.css README.md tests/test_api.py
git commit -m "Add the Intel tab, production tables, peace-aware war column and wipe copy"
```

---

### Task 11: Snapshot the v2 fixture and pin the unverified shapes — **gated on play**

**Files:**
- Create: `tests/fixtures/logs_v2/` (12 files), `tests/fixtures/logs_v2/FACTS.md`, `tests/test_fixture_v2.py`
- Modify: `tests/conftest.py` (`fixture_v2_dir`, `fixture_v2_state`), possibly `civ7_advisor/ingest/events.py` (only if a pinned shape contradicts a reader — see Step 4)

**Gate:** this task can only run once the live game has produced enough log. Check first:
```bash
L="$HOME/Library/Application Support/Civilization VII/Logs"
tail -1 "$L/Player_Stats.csv" | cut -d, -f1          # want >= 40
tail -n +2 "$L/CombatLog.csv" | wc -l                # want >= 1
grep -c "Item ID" "$L/DiplomacyDeals.log"            # want >= 1
```
If any condition fails, **report `BLOCKED` with the three numbers** and stop — this is "not yet", not a defect. The controller moves on and returns to this task later. Never relaunch the game to force it: relaunching deletes the logs.

- [ ] **Step 1: Snapshot (read-only copy)**

```bash
mkdir -p tests/fixtures/logs_v2
for f in Player_Stats.csv Player_Treasury.csv Player_Happiness.csv AI_Victories.csv AI_DiplomaticActions.csv AI_Targets.csv Historian.csv \
         CityBuildQueue.csv CombatLog.csv Game_Gossip.csv DiplomacySummary.csv DiplomacyDeals.log; do
  cp "$HOME/Library/Application Support/Civilization VII/Logs/$f" tests/fixtures/logs_v2/
done
```

- [ ] **Step 2: Record the facts the readers could not pin**

Write `tests/fixtures/logs_v2/FACTS.md` from these commands (paste the outputs verbatim under each heading):
```bash
cd tests/fixtures/logs_v2
echo "## Turn range"; head -2 Player_Stats.csv | tail -1 | cut -d, -f1; tail -1 Player_Stats.csv | cut -d, -f1
echo "## Human civ (player 0 city keys)"; awk -F', *' '$2==0{print $3}' CityBuildQueue.csv | sort -u
echo "## Gossip column-count distribution"; awk -F', *' 'NR>1{print NF}' Game_Gossip.csv | sort | uniq -c
echo "## Gossip types"; awk -F', *' 'NR>1{print $6}' Game_Gossip.csv | sort | uniq -c | sort -rn
echo "## DiplomacySummary column-count distribution and trailing-cell values"
awk -F', *' 'NR>1{print NF}' DiplomacySummary.csv | sort | uniq -c
awk -F', *' 'NR>1{for(i=6;i<=NF;i++) print i": "$i}' DiplomacySummary.csv | sort | uniq -c | sort -rn | head -20
echo "## CombatLog value sets"; for c in 2 6 15; do awk -F, -v c=$c 'NR>1{print $c}' CombatLog.csv | sort | uniq -c; echo; done
echo "## CombatLog health cells for destroyed combatants (to infer (a)b order)"
awk -F, 'NR>1 && $15=="Attacker"{print "att", $17, "dmg", $13, $14}' CombatLog.csv | head -5
awk -F, 'NR>1 && $15=="Defender"{print "def", $18, "dmg", $13, $14}' CombatLog.csv | head -5
echo "## Deal kinds"; grep -o "type [^,]*" DiplomacyDeals.log | sort | uniq -c
echo "## CityBuildQueue idle vocabulary (Current Item values that are not BUILDING_/UNIT_/IMPROVEMENT_/WONDER_)"
awk -F', *' 'NR>1 && $5 !~ /^(BUILDING|UNIT|IMPROVEMENT|WONDER)_/{print "["$5"]"}' CityBuildQueue.csv | sort | uniq -c
```
Under each heading, add one line stating what it settles: e.g. "Gossip is always 7 columns" or "6 and 7 both occur"; "DiplomacySummary is always 6 values: the missing column is X"; "In a destroyed attacker, attHealth reads (0)100, so the order is (after)before"; "Idle cities log `NONE`" (or whatever is observed).

- [ ] **Step 3: Pin with tests**

Append to `tests/conftest.py`:
```python
FIXTURE_V2_DIR = Path(__file__).parent / "fixtures" / "logs_v2"


@pytest.fixture(scope="session")
def fixture_v2_dir() -> Path:
    if not FIXTURE_V2_DIR.is_dir():
        pytest.skip("v2 fixture not snapshotted yet (see plan Task 11)")
    return FIXTURE_V2_DIR


@pytest.fixture(scope="session")
def fixture_v2_state(fixture_v2_dir: Path):
    return build_state(load_logs(fixture_v2_dir))
```
`tests/test_fixture_v2.py`:
```python
from civ7_advisor.advisors import intel, production, run_all, threat
from civ7_advisor.ingest.load import LOG_FILES, load_logs


def test_every_log_in_the_v2_fixture_parses(fixture_v2_dir):
    raw = load_logs(fixture_v2_dir)
    assert all(raw.files[n].ok for n in LOG_FILES), {n: f.error for n, f in raw.files.items() if not f.ok}
    assert raw.build_queue and raw.combat and raw.gossip and raw.diplomacy_summary and raw.deals


def test_feed_production_and_advice_are_populated(fixture_v2_state):
    assert intel.feed(fixture_v2_state)
    assert fixture_v2_state.HUMAN in production.queues(fixture_v2_state)
    insights = run_all(fixture_v2_state)
    assert insights and all(i.title.strip() and i.recommendation.strip() and i.why.strip() for i in insights)


def test_peace_and_war_are_never_asserted_together(fixture_v2_state):
    for r in threat.summarize(fixture_v2_state):
        assert not (r.at_war_since is not None and r.peace_since is not None)


def test_human_gossip_resolves_to_player_zero(fixture_v2_state):
    names = fixture_v2_state.names
    assert names is not None and names.human_civ is not None
    human_rows = [g for g in fixture_v2_state.gossip if names.player_for(g.leader, g.civilization) == 0]
    assert human_rows, "no gossip about the human resolved — check FACTS.md civ prefix vs Gossip Civilization"
```
Add pinning assertions that match FACTS.md — for example, if gossip is always 7 columns, `assert all(g.detail is not None for g in read_gossip(fixture_v2_dir / "Game_Gossip.csv"))`; if DiplomacySummary always has six values, `assert {len(r.extra) for r in read_diplomacy_summary(...)} == {1}`. Write each as a separate small test named after the fact it pins.

- [ ] **Step 4: Reconcile the readers with what was pinned — only if contradicted**

If FACTS.md shows a shape the readers reject (a third Gossip width, a DiplomacySummary row with fewer than five cells, a CombatLog `Location` in another format), widen the reader minimally and add the failing row as a synthetic test. If FACTS.md settles the `DiplomacySummary` trailing cells, **do not** rename `extra` in this task — record the finding in FACTS.md under "Follow-ups" for a bounded task. Same for the CombatLog damage direction and idle-item vocabulary.

- [ ] **Step 5: Run everything**

Run: `uv run pytest -q`. Expected: all pass including the new fixture tests, zero warnings. Start the dashboard on the new fixture (`uv run civ7-advisor --logs-dir tests/fixtures/logs_v2 --no-archive`) and confirm the Intel tab and production tables show real data. Stop it.

- [ ] **Step 6: Commit**

```bash
git add tests/fixtures/logs_v2 tests/test_fixture_v2.py tests/conftest.py
git commit -m "Snapshot the v2 fixture from a live session and pin the unverified log shapes"
```

---

## Self-review

**Spec coverage (v2 §, phase 1a scope):** §2 corrections → Task 9 (wipe → archiver), Task 7 (peace), Task 1 (production exists), Task 2 note (CombatLog is historical). §3.1 five files → Tasks 1–4; every ⚠ verify item is either tolerated by a reader (Gossip 6/7, DiplomacySummary ≥5 + `extra`) or pinned in Task 11. §3 provenance rule → Tasks 6, 7, 8, 10. §3 name resolver → Task 5. §4.1 `production.*` → Task 6; `threat.combat_record` (amended wording) and peace → Task 7; `intel.feed` → Task 8; Intel tab → Task 10. §5 architecture → file structure above; `ADVISORS`/`ADVISOR_ORDER` pin → Task 6. §6.2 wipe copy → Task 10; §6.3 archiver → Task 9; §6.1 isolation unchanged. §7 fixture → Task 11; synthetic hazard tests → Tasks 1–4; oracle gating of new surfaces → Task 10 (server-side, Python-pinned). Not in 1a by design: 1b tactical files, LLM, research.

**Placeholder scan:** no TBD/TODO. Task 11's "write each as a separate small test" is conditional on facts that do not exist yet; the two example assertions show the exact form.

**Type consistency:** `RawLogs.build_queue/combat/gossip/diplomacy_summary/deals` ↔ `build_state` ↔ `GameState.build_queues/combats/gossip/diplomacy_events/deals` (Tasks 1–5, used by 6–10); `CombatRow.parties()/loser()/involves()` (Task 2) used in Tasks 7–8; `DealItem.is_peace/parties()` (Task 4) used in Task 5; `NameResolver.build(rival_names, human_city_keys)`/`player_for(leader, civilization)` (Task 5) used in Tasks 8, 11; `production.queues/rival_military_share/is_military/CityQueue` (Task 6) used in Task 10; `RivalThreat.peace_since/fights/fights_won/fights_lost/latest_combat` (Task 7) used in Task 10 and 11; `archive.game_key(raw)/archive_logs(logs_dir, dest, names)/MANIFEST/DEFAULT_ARCHIVE_ROOT` (Task 9) used by `Store`/CLI; `Store(logs_dir, archive_root=None)` ↔ `create_app(logs_dir, poll_interval=1.0, archive_root=None)` ↔ CLI (Task 9); `state_to_dict(state, oracle=True)`/`intel_to_dict`/`INTEL_LIMIT` (Task 10). `humanize` (Task 6) used in Tasks 7–8.

**Known plan-level rulings (for the executor's ledger):** damage figures are not quoted until Task 11 pins their direction; the human's queue reads `latest_turn`, rivals' `complete_through_turn`; `ITEM_YIELDS` is unverified and suppresses rather than guesses; `intel` is not an advisor; new-surface oracle gating is server-side; the archive session key resets when the state goes empty.
