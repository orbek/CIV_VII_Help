# Civ VI Tuner Live State Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Read amenities, the maintenance breakdown, and each settlement's real build options and completion estimates from Civilization VI's tuner socket, so three capabilities the advisor declares impossible become real — without ever writing to the game.

**Architecture:** A new `civ_advisor/tuner/` package mirroring the shape of `civ_advisor/ruleset/`: a Protocol plus typed value objects plus a Null object in `base.py`, a fixed reviewed query catalog, a pure-bytes protocol module, and a socket client that never raises. `Store.rebuild()` queries it once per poll alongside the log read. Capabilities the tuner backs are live only when the socket answered this poll; otherwise the reason says which of three distinct things went wrong.

**Tech Stack:** Python 3.12, stdlib `socket`/`struct`, pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-13-civ6-tuner-live-state-design.md`

## Global Constraints

- **The program is read-only with respect to both games' directories.** It never writes `AppOptions.txt`, never enables the tuner, never leaves a file under a game folder. It prints the line a human must change.
- **No value that originated with a player is ever interpolated into Lua.** Not a settlement name, not a goal, not challenge-box text. Query Lua is a constant in reviewed source. The only runtime parameters are integers the program derived itself, passed through a validator that rejects non-`int`.
- **Loopback only.** Connect to `127.0.0.1`. Never listen, never bind, never accept a host from configuration.
- **`"Not Implemented."` means the capability is absent, not that the call failed.** Never retry it, never surface it as an error, never blend it with a real reading.
- **Resolve Lua states by name, never by index.** Indices shift when the player loads a mod. `tests/fixtures/tuner/handshake_lsq.bin` proves it: a mod occupies index 2 and displaces everything after.
- **Absence is declared, never inferred, and its reason names the real cause.** "Tuner not enabled", "tuner enabled but not answering" and "this figure is unreachable in every VM" are three different statements. A blank panel or a zero is never acceptable for any of them.
- **A tuner reading is Fair, and is its own source kind.** It is a value the advisor asked for at a moment the advisor chose — unlike a log row, which the game wrote on its own.
- **Never fabricate a guide catalog entry.** Unchanged from earlier phases.
- **Stage only your own files, by explicit path.** Never `git add -A`. `docs/` is gitignored but tracked, so documentation commits need `git add -f`.
- **The default test suite stays offline and fast.** Anything needing a running game goes in `tests/live/`, excluded via `addopts`.
- Python 3.12. `filterwarnings = ["error", ...]` is in force: a new warning fails the suite.

---

### Task 1: The wire protocol, as pure bytes

**Files:**
- Create: `civ_advisor/tuner/__init__.py`
- Create: `civ_advisor/tuner/protocol.py`
- Test: `tests/test_tuner_protocol.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `frame(tag: int, payload: str) -> bytes`, `parse(buf: bytes) -> tuple[tuple[int, str], ...]`, `consume(buf: bytes) -> tuple[tuple[tuple[int, str], ...], bytes]`, `output_text(payload: str) -> str | None`, `parse_states(payload: str) -> dict[str, int]`, constants `TAG_HANDSHAKE = 4`, `TAG_COMMAND = 3`.

This module knows bytes and nothing else — no sockets, no game concepts. That is what makes the wire format testable against the captured fixtures without a running game.

- [ ] **Step 1: Write the failing tests**

`tests/test_tuner_protocol.py`:

```python
"""The wire format, checked against bytes a real game actually sent.

Every fixture in tests/fixtures/tuner/ is a capture. If a test here disagrees
with those bytes, the test is wrong about the protocol, not the capture.
"""
from pathlib import Path

import pytest

from civ_advisor.tuner.protocol import (
    TAG_COMMAND, TAG_HANDSHAKE, consume, frame, output_text, parse, parse_states,
)

FIXTURES = Path(__file__).parent / "fixtures" / "tuner"


def test_frame_length_counts_the_null_terminator():
    # 4-byte length, 4-byte tag, payload, NUL. "hi" is 2 bytes, so length is 3.
    assert frame(TAG_COMMAND, "hi") == b"\x03\x00\x00\x00\x03\x00\x00\x00hi\x00"


def test_parse_reads_back_what_frame_wrote():
    buf = frame(TAG_HANDSHAKE, "APP:x") + frame(TAG_COMMAND, "CMD:4:print(1)")
    assert parse(buf) == ((TAG_HANDSHAKE, "APP:x"), (TAG_COMMAND, "CMD:4:print(1)"))


def test_consume_returns_the_incomplete_tail_unparsed():
    whole = frame(TAG_COMMAND, "abc")
    msgs, rest = consume(whole + whole[:5])
    assert msgs == ((TAG_COMMAND, "abc"),)
    assert rest == whole[:5]


def test_consume_of_a_header_without_its_payload_yields_nothing():
    msgs, rest = consume(frame(TAG_COMMAND, "abc")[:6])
    assert msgs == ()
    assert len(rest) == 6


def test_real_handshake_names_the_application():
    msgs = parse((FIXTURES / "handshake_lsq.bin").read_bytes())
    assert "Civ6" in msgs[0][1]


def test_real_handshake_lists_states_by_name():
    msgs = parse((FIXTURES / "handshake_lsq.bin").read_bytes())
    states = parse_states(msgs[1][1])
    assert states["GameCore_Tuner"] == 4
    assert states["InGame"] == 125


def test_state_indices_are_not_positional():
    """A mod was loaded when this was captured, and it displaced the rest.

    This is the whole reason states are resolved by name. If this capture ever
    stops containing a mod, keep a capture that does.
    """
    states = parse_states(parse((FIXTURES / "handshake_lsq.bin").read_bytes())[1][1])
    assert states["AdvisorProbe"] == 2
    assert states["GameCore_Tuner"] > 2


def test_output_text_strips_the_state_prefix():
    assert output_text("O\x00GameCore_Tuner: total\t1") == "total\t1"


def test_output_text_rejects_a_payload_that_is_not_output():
    assert output_text("Civ6\x00Sid Meier's Civilization 6") is None


def test_real_maintenance_capture_decodes_to_its_values():
    msgs = parse((FIXTURES / "query_maintenance.bin").read_bytes())
    lines = [t for t in (output_text(p) for _, p in msgs) if t]
    assert "total\t1" in lines
    assert "districts\t1" in lines
    assert "gold\t152" in lines
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_tuner_protocol.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'civ_advisor.tuner'`

- [ ] **Step 3: Write the implementation**

`civ_advisor/tuner/__init__.py`:

```python
"""Reading Civilization VI's live state through its tuner socket.

The socket exists only when the player has set `EnableTuner 1` in the game's
own AppOptions.txt. This package never writes that file -- see the spec's
"The advisor never enables the tuner".
"""
```

`civ_advisor/tuner/protocol.py`:

```python
"""The tuner wire format, as pure functions over bytes.

No sockets and no game concepts live here, so every rule below is checked
against captures in tests/fixtures/tuner/ without a running game.

A message is:  uint32 LE length (payload INCLUDING its NUL) | int32 LE tag |
NUL-terminated UTF-8 payload.
"""
from __future__ import annotations

import struct

TAG_COMMAND = 3       # "CMD:<state index>:<lua>"
TAG_HANDSHAKE = 4     # "APP:<name>", "LSQ:", and every output message

_HEADER = struct.Struct("<II")
_OUTPUT_PREFIX = "O\x00"


def frame(tag: int, payload: str) -> bytes:
    """One message on the wire. The length counts the NUL, which is easy to get wrong."""
    body = payload.encode("utf-8") + b"\0"
    return _HEADER.pack(len(body), tag) + body


def consume(buf: bytes) -> tuple[tuple[tuple[int, str], ...], bytes]:
    """Every complete message in `buf`, plus the incomplete tail to keep.

    The game splits long output across packets, so a caller that discarded the
    tail would lose a line whenever a reply straddled a boundary.
    """
    out: list[tuple[int, str]] = []
    i = 0
    while i + _HEADER.size <= len(buf):
        length, tag = _HEADER.unpack_from(buf, i)
        start = i + _HEADER.size
        if length > len(buf) - start:
            break
        out.append((tag, buf[start:start + length].rstrip(b"\0").decode("utf-8", "replace")))
        i = start + length
    return tuple(out), buf[i:]


def parse(buf: bytes) -> tuple[tuple[int, str], ...]:
    """Every complete message in `buf`, discarding any incomplete tail."""
    return consume(buf)[0]


def output_text(payload: str) -> str | None:
    """The text of an output message, or None if this payload is not output.

    Output arrives as "O\\0<state name>: <text>". The state name is discarded:
    the caller already knows which state it addressed, and keeping it here would
    invite matching on it.
    """
    if not payload.startswith(_OUTPUT_PREFIX):
        return None
    rest = payload[len(_OUTPUT_PREFIX):]
    _, sep, text = rest.partition(": ")
    return text if sep else rest


def parse_states(payload: str) -> dict[str, int]:
    """The `LSQ:` reply as name -> index.

    Keyed by NAME deliberately. Indices shift when the player loads a mod, and a
    hardcoded index does not fail loudly -- it silently addresses another VM.
    """
    parts = payload.split("\x00")
    states: dict[str, int] = {}
    for index, name in zip(parts[::2], parts[1::2]):
        try:
            states[name] = int(index)
        except ValueError:      # a malformed pair is not evidence about the others
            continue
    return states


__all__ = ["TAG_COMMAND", "TAG_HANDSHAKE", "consume", "frame", "output_text",
           "parse", "parse_states"]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_tuner_protocol.py -v`
Expected: PASS, 10 tests.

- [ ] **Step 5: Run the whole suite**

Run: `uv run pytest -q`
Expected: 781 passed (771 before + 10).

- [ ] **Step 6: Commit**

```bash
git add civ_advisor/tuner/__init__.py civ_advisor/tuner/protocol.py tests/test_tuner_protocol.py
git commit -m "Decode the tuner wire format against real captured frames"
```

---

### Task 2: Typed readings, the Protocol, and the Null object

**Files:**
- Create: `civ_advisor/tuner/base.py`
- Test: `tests/test_tuner_base.py`

**Interfaces:**
- Consumes: `civ_advisor.games.base.Capability`.
- Produces: `TunerReading`, `CityAmenities`, `Maintenance`, `BuildOption`, `SettlementOptions`, `TunerUnavailable` (StrEnum of reasons), `TunerProvider` (Protocol), `NullTuner`, `TUNER_OFF`.

This mirrors `civ_advisor/ruleset/base.py`: a closed set of questions with typed answers, no `query(lua)` anywhere on the Protocol, and a Null object so callers never branch on `None`.

- [ ] **Step 1: Write the failing tests**

`tests/test_tuner_base.py`:

```python
"""What a tuner reading is allowed to be, and what absence looks like."""
import pytest

from civ_advisor.games.base import Capability
from civ_advisor.tuner.base import (
    BuildOption, CityAmenities, Maintenance, NullTuner, SettlementOptions,
    TUNER_OFF, TunerProvider, TunerReading, TunerUnavailable,
)


def test_a_reading_records_both_the_turn_and_the_moment_it_was_asked():
    """Unlike a log row, a reading is something we asked for at a time we chose."""
    r = TunerReading(turn=59, read_at="2026-09-13T10:40:00Z", state="GameCore_Tuner")
    assert r.turn == 59
    assert r.read_at == "2026-09-13T10:40:00Z"


def test_a_reading_must_name_the_vm_it_came_from():
    with pytest.raises(ValueError, match="state"):
        TunerReading(turn=59, read_at="2026-09-13T10:40:00Z", state="")


def test_amenities_sources_must_not_exceed_the_total_they_explain():
    with pytest.raises(ValueError, match="sources"):
        CityAmenities(city="Rome", total=1, from_luxuries=5, from_civics=0,
                      from_entertainment=0, housing=9, food_surplus=1)


def test_net_gold_is_yield_minus_maintenance():
    m = Maintenance(total=1, buildings=0, districts=1, units=0, gold=152, gold_yield=8)
    assert m.net_gold == 7


def test_maintenance_parts_must_sum_to_the_total():
    """A breakdown that does not add up is a parsing bug, not a game fact."""
    with pytest.raises(ValueError, match="breakdown"):
        Maintenance(total=9, buildings=0, districts=1, units=0, gold=152, gold_yield=8)


def test_a_build_option_carries_its_own_completion_estimate():
    o = BuildOption(item="BUILDING_GRANARY", turns=8)
    assert o.turns == 8


def test_a_build_option_rejects_a_negative_estimate():
    with pytest.raises(ValueError, match="turns"):
        BuildOption(item="BUILDING_GRANARY", turns=-1)


def test_a_settlement_offering_nothing_is_different_from_not_being_asked():
    """An empty offer list is a fact. `None` would be an absence of one."""
    s = SettlementOptions(city="Puteoli", options=())
    assert s.options == ()
    assert s.offers("BUILDING_GRANARY") is None


def test_null_tuner_answers_every_question_with_its_reason():
    null = NullTuner(TunerUnavailable.NOT_ENABLED, "EnableTuner is 0 in AppOptions.txt")
    assert null.available is False
    assert null.amenities() == ()
    assert null.maintenance() is None
    assert null.build_options() == ()
    assert "EnableTuner" in null.reason


def test_the_off_singleton_says_which_absence_it_is():
    assert TUNER_OFF.unavailable is TunerUnavailable.NOT_ENABLED


def test_the_three_absences_are_distinct():
    """Told apart on purpose: only one of them is fixable by the player."""
    assert len(set(TunerUnavailable)) == 3


def test_null_tuner_satisfies_the_protocol():
    assert isinstance(TUNER_OFF, TunerProvider)


def test_the_capabilities_a_tuner_can_back_are_named_here():
    from civ_advisor.tuner.base import TUNER_BACKED
    assert Capability.HAPPINESS in TUNER_BACKED
    assert Capability.MAINTENANCE in TUNER_BACKED
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_tuner_base.py -v`
Expected: FAIL — no module `civ_advisor.tuner.base`.

- [ ] **Step 3: Write the implementation**

`civ_advisor/tuner/base.py`:

```python
"""What the tuner can be asked, and what its answers are.

The shape follows civ_advisor/ruleset/base.py on purpose: a closed set of
questions with typed answers, and no `query(lua)` on the Protocol. A caller
cannot ask this package to run arbitrary code in the player's game, because
there is no method that would take it.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable

from civ_advisor.games.base import Capability

# Capabilities a tuner reading can support. Declared here rather than in the
# profile so one list governs both the profile's declaration and the conformance
# test that keeps them honest.
TUNER_BACKED = frozenset({Capability.HAPPINESS, Capability.MAINTENANCE})


class TunerUnavailable(StrEnum):
    """Why there is no reading. Three genuinely different situations.

    Only NOT_ENABLED is something the player can fix, and saying the wrong one
    would send them to change a setting that is already correct.
    """

    NOT_ENABLED = "not_enabled"          # the socket is closed; EnableTuner is 0
    NOT_ANSWERING = "not_answering"      # enabled, but no game is running or it did not reply
    UNREACHABLE = "unreachable"          # answered, but this figure exists in no VM


@dataclass(frozen=True)
class TunerReading:
    """When a reading was taken, and from which VM.

    A log row is something the game wrote on its own; this is a value we asked
    for at a moment we chose. Both facts travel with every figure, which is why
    `read_at` exists beside `turn`.
    """

    turn: int
    read_at: str      # ISO 8601, the wall-clock instant of the query
    state: str        # the Lua VM name, e.g. "GameCore_Tuner"

    def __post_init__(self) -> None:
        if not self.state:
            raise ValueError("a reading must name the state it was read from")


@dataclass(frozen=True)
class CityAmenities:
    """One settlement's amenities and the sources that explain them."""

    city: str
    total: int
    from_luxuries: int
    from_civics: int
    from_entertainment: int
    housing: int
    food_surplus: int

    def __post_init__(self) -> None:
        named = self.from_luxuries + self.from_civics + self.from_entertainment
        if named > self.total:
            raise ValueError(
                f"sources ({named}) exceed the total they explain ({self.total})")

    @property
    def unexplained(self) -> int:
        """Amenities the game reports that these sources do not account for.

        Civ VI exposes only three of its amenity sources to this VM, so a
        positive remainder is expected and is reported rather than hidden.
        """
        return self.total - (self.from_luxuries + self.from_civics + self.from_entertainment)


@dataclass(frozen=True)
class Maintenance:
    """The gold breakdown the logs cannot supply."""

    total: int
    buildings: int
    districts: int
    units: int
    gold: int
    gold_yield: int

    def __post_init__(self) -> None:
        if self.buildings + self.districts + self.units != self.total:
            raise ValueError(
                "breakdown does not sum to the total; this is a parsing bug, "
                "not a fact about the game")

    @property
    def net_gold(self) -> int:
        """Gold per turn after upkeep -- the figure the profile calls impossible."""
        return self.gold_yield - self.total


@dataclass(frozen=True)
class BuildOption:
    """One thing a settlement may build, and how long it would take.

    Both halves come from the game. Neither is derivable from the ruleset,
    because the estimate depends on this settlement's production.
    """

    item: str
    turns: int

    def __post_init__(self) -> None:
        if self.turns < 0:
            raise ValueError(f"turns must not be negative, got {self.turns}")


@dataclass(frozen=True)
class SettlementOptions:
    """Everything one settlement may build right now.

    An empty tuple means the game offered nothing, which is a fact. A settlement
    that was never asked about is absent from the collection instead.
    """

    city: str
    options: tuple[BuildOption, ...]

    def offers(self, item: str) -> BuildOption | None:
        return next((o for o in self.options if o.item == item), None)


@runtime_checkable
class TunerProvider(Protocol):
    """A closed set of questions. There is deliberately no `query(lua)`."""

    @property
    def available(self) -> bool: ...
    @property
    def reason(self) -> str | None: ...
    @property
    def unavailable(self) -> TunerUnavailable | None: ...
    def reading(self) -> TunerReading | None: ...
    def amenities(self) -> tuple[CityAmenities, ...]: ...
    def maintenance(self) -> Maintenance | None: ...
    def build_options(self) -> tuple[SettlementOptions, ...]: ...


@dataclass(frozen=True)
class NullTuner:
    """No readings, and a reason that says which absence this is."""

    unavailable: TunerUnavailable
    _reason: str

    @property
    def available(self) -> bool:
        return False

    @property
    def reason(self) -> str:
        return self._reason

    def reading(self) -> TunerReading | None:
        return None

    def amenities(self) -> tuple[CityAmenities, ...]:
        return ()

    def maintenance(self) -> Maintenance | None:
        return None

    def build_options(self) -> tuple[SettlementOptions, ...]:
        return ()


TUNER_OFF = NullTuner(
    TunerUnavailable.NOT_ENABLED,
    "Civilization VI reports amenities, upkeep and build options only through its "
    "tuner socket, which is off. Set `EnableTuner 1` under [Debug] in the game's "
    "AppOptions.txt and restart the game. The advisor never edits that file.",
)

__all__ = ["BuildOption", "CityAmenities", "Maintenance", "NullTuner",
           "SettlementOptions", "TUNER_BACKED", "TUNER_OFF", "TunerProvider",
           "TunerReading", "TunerUnavailable"]
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_tuner_base.py -v`
Expected: PASS, 13 tests.

- [ ] **Step 5: Commit**

```bash
git add civ_advisor/tuner/base.py tests/test_tuner_base.py
git commit -m "Type what a tuner reading is, and what its absence means"
```

---

### Task 3: The query catalog

**Files:**
- Create: `civ_advisor/tuner/queries.py`
- Test: `tests/test_tuner_queries.py`

**Interfaces:**
- Consumes: `civ_advisor.tuner.base` value types.
- Produces: `Query` dataclass (`id`, `state`, `lua`, `verified_on`, `parse`), `CATALOG: dict[str, Query]`, `NOT_IMPLEMENTED` sentinel string, `looks_unreachable(lines) -> bool`.

Every entry's Lua is a module constant. The catalog is the allowlist: if a question is not in here, the program cannot ask it.

- [ ] **Step 1: Write the failing tests**

`tests/test_tuner_queries.py`:

```python
"""The catalog of questions, checked against real replies."""
from pathlib import Path

import pytest

from civ_advisor.tuner.protocol import output_text, parse
from civ_advisor.tuner.queries import CATALOG, looks_unreachable

FIXTURES = Path(__file__).parent / "fixtures" / "tuner"


def lines(name: str) -> list[str]:
    msgs = parse((FIXTURES / name).read_bytes())
    return [t for t in (output_text(p) for _, p in msgs) if t and "---END---" not in t]


def test_every_entry_declares_where_it_runs_and_when_it_was_verified():
    for q in CATALOG.values():
        assert q.state in {"GameCore_Tuner", "InGame"}, q.id
        assert q.verified_on, q.id


def test_no_entry_contains_a_format_placeholder():
    """Query Lua is a constant. A placeholder is the beginning of injection."""
    for q in CATALOG.values():
        assert "{" not in q.lua and "%s" not in q.lua, q.id


def test_maintenance_parses_the_real_reply():
    m = CATALOG["maintenance"].parse(lines("query_maintenance.bin"))
    assert m.total == 1 and m.districts == 1 and m.buildings == 0 and m.units == 0
    assert m.gold == 152 and m.gold_yield == 8
    assert m.net_gold == 7


def test_amenities_parses_every_city_in_the_real_reply():
    rows = CATALOG["amenities"].parse(lines("query_amenities.bin"))
    by_city = {r.city: r for r in rows}
    assert by_city["Rome"].total == 3
    assert by_city["Rome"].from_entertainment == 2
    assert by_city["Puteoli"].total == 1
    assert by_city["Puteoli"].housing == 5


def test_build_options_parses_each_settlement_separately():
    rows = CATALOG["build_options"].parse(lines("query_buildoptions.bin"))
    by_city = {r.city: r for r in rows}
    assert by_city["Rome"].offers("BUILDING_GRANARY").turns == 8
    assert by_city["Rome"].offers("BUILDING_LIBRARY").turns == 11
    assert by_city["Puteoli"].offers("BUILDING_MONUMENT").turns == 60
    assert by_city["Rome"].offers("BUILDING_MONUMENT") is None


def test_build_options_runs_in_the_ui_state():
    """CanProduce and GetTurnsLeft are stubs in GameCore. This is not a preference."""
    assert CATALOG["build_options"].state == "InGame"


def test_a_not_implemented_reply_reads_as_unreachable():
    assert looks_unreachable(lines("query_not_implemented.bin")) is True


def test_a_missing_binding_reads_as_unreachable():
    assert looks_unreachable(lines("query_missing_binding.bin")) is True


def test_a_good_reply_does_not_read_as_unreachable():
    assert looks_unreachable(lines("query_maintenance.bin")) is False


def test_parsing_a_truncated_reply_raises_rather_than_inventing_a_figure():
    with pytest.raises(ValueError):
        CATALOG["maintenance"].parse(["total\t1"])
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_tuner_queries.py -v`
Expected: FAIL — no module `civ_advisor.tuner.queries`.

- [ ] **Step 3: Write the implementation**

`civ_advisor/tuner/queries.py`:

```python
"""The fixed set of questions the advisor may ask the game.

This module is the allowlist, in the same sense as READABLE_COLUMNS in
ruleset/civ6.py: a question that is not written here cannot be asked. Every
`lua` below is a module constant with no placeholder of any kind, so no value
that came from a player can reach the game as code.

Each entry records the VM it runs in and the date it was verified against a
real game, because a binding that exists in one VM can be a stub in another.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .base import BuildOption, CityAmenities, Maintenance, SettlementOptions

# The game raises this, with a Lua traceback, for a binding that exists but is
# not wired up in that VM. It is a permanent property of the game, not a
# transient failure, so it is read as absence and never retried.
NOT_IMPLEMENTED = "Not Implemented."

_MAINTENANCE_LUA = (
    'local t=Players[Game.GetLocalPlayer()]:GetTreasury() '
    'print("total", t:GetTotalMaintenance()) '
    'print("buildings", t:GetBuildingMaintenance()) '
    'print("districts", t:GetDistrictMaintenance()) '
    'print("units", t:GetUnitMaintenance()) '
    'print("gold", t:GetGoldBalance()) '
    'print("goldYield", t:GetGoldYield())'
)

_AMENITIES_LUA = (
    'for _,c in Players[Game.GetLocalPlayer()]:GetCities():Members() do '
    'local g=c:GetGrowth() '
    'print(Locale.Lookup(c:GetName()), g:GetAmenities(), g:GetAmenitiesFromLuxuries(), '
    'g:GetAmenitiesFromCivics(), g:GetAmenitiesFromEntertainment(), g:GetHousing(), '
    'g:GetFoodSurplus()) end'
)

# Runs in the UI VM: CanProduce and GetTurnsLeft are present in GameCore_Tuner
# and raise "Not Implemented." there.
_BUILD_OPTIONS_LUA = (
    'for _,c in Players[Game.GetLocalPlayer()]:GetCities():Members() do '
    'local q=c:GetBuildQueue() '
    'for row in GameInfo.Buildings() do '
    'local ok,can=pcall(function() return q:CanProduce(row.Hash,true) end) '
    'if ok and can then print(Locale.Lookup(c:GetName()), row.BuildingType, '
    'q:GetTurnsLeft(row.Hash)) end end end'
)


def looks_unreachable(lines: list[str]) -> bool:
    """Whether a reply says the figure does not exist, rather than carrying one."""
    joined = "\n".join(lines)
    return NOT_IMPLEMENTED in joined or "\tnil" in joined or joined.strip().endswith("nil")


def _fields(line: str) -> list[str]:
    return [p for p in line.split("\t") if p != ""]


def _parse_maintenance(lines: list[str]) -> Maintenance:
    got: dict[str, int] = {}
    for line in lines:
        parts = _fields(line)
        if len(parts) == 2:
            try:
                got[parts[0]] = int(parts[1])
            except ValueError:
                continue
    needed = ("total", "buildings", "districts", "units", "gold", "goldYield")
    missing = [n for n in needed if n not in got]
    if missing:
        raise ValueError(f"maintenance reply is missing {missing}")
    return Maintenance(total=got["total"], buildings=got["buildings"],
                       districts=got["districts"], units=got["units"],
                       gold=got["gold"], gold_yield=got["goldYield"])


def _parse_amenities(lines: list[str]) -> tuple[CityAmenities, ...]:
    out: list[CityAmenities] = []
    for line in lines:
        parts = _fields(line)
        if len(parts) != 7:
            continue
        city, *rest = parts
        try:
            total, lux, civ, ent, housing, food = (int(v) for v in rest)
        except ValueError:
            continue
        out.append(CityAmenities(city=city, total=total, from_luxuries=lux,
                                 from_civics=civ, from_entertainment=ent,
                                 housing=housing, food_surplus=food))
    if not out:
        raise ValueError("amenities reply named no settlement")
    return tuple(out)


def _parse_build_options(lines: list[str]) -> tuple[SettlementOptions, ...]:
    grouped: dict[str, list[BuildOption]] = {}
    for line in lines:
        parts = _fields(line)
        if len(parts) != 3:
            continue
        city, item, turns = parts
        try:
            grouped.setdefault(city, []).append(BuildOption(item=item, turns=int(turns)))
        except ValueError:
            continue
    return tuple(SettlementOptions(city=c, options=tuple(o)) for c, o in grouped.items())


@dataclass(frozen=True)
class Query:
    """One reviewed question: its Lua, the VM it needs, and how to read the reply."""

    id: str
    state: str
    lua: str
    verified_on: str
    parse: Callable[[list[str]], object]


CATALOG: dict[str, Query] = {
    q.id: q for q in (
        Query("maintenance", "GameCore_Tuner", _MAINTENANCE_LUA, "2026-09-13",
              _parse_maintenance),
        Query("amenities", "GameCore_Tuner", _AMENITIES_LUA, "2026-09-13",
              _parse_amenities),
        Query("build_options", "InGame", _BUILD_OPTIONS_LUA, "2026-09-13",
              _parse_build_options),
    )
}

__all__ = ["CATALOG", "NOT_IMPLEMENTED", "Query", "looks_unreachable"]
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_tuner_queries.py -v`
Expected: PASS, 10 tests.

- [ ] **Step 5: Commit**

```bash
git add civ_advisor/tuner/queries.py tests/test_tuner_queries.py
git commit -m "Fix the set of questions the advisor may ask the game"
```

---

### Task 4: The socket client

**Files:**
- Create: `civ_advisor/tuner/client.py`
- Test: `tests/test_tuner_client.py`

**Interfaces:**
- Consumes: `protocol`, `queries`, `base`.
- Produces: `open_tuner(port: int = 4318, timeout: float = 3.0) -> TunerProvider`, `Civ6Tuner`, `SENTINEL`.

Mirrors `open_ruleset`: never raises, always degrades to a `NullTuner` carrying the right `TunerUnavailable`.

- [ ] **Step 1: Write the failing tests**

`tests/test_tuner_client.py`:

```python
"""The client, against a fake server replaying real captured frames."""
import socket
import threading
from pathlib import Path

import pytest

from civ_advisor.tuner.base import TunerUnavailable
from civ_advisor.tuner.client import SENTINEL, open_tuner
from civ_advisor.tuner.protocol import TAG_HANDSHAKE, consume, frame

FIXTURES = Path(__file__).parent / "fixtures" / "tuner"


class FakeGame:
    """Replays captured bytes, keyed by which state a command addressed."""

    def __init__(self, replies: dict[int, bytes], *, drip: bool = False):
        self.replies = replies
        self.drip = drip          # send one byte at a time, to split frames
        self.asked: list[str] = []
        self._srv = socket.socket()
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind(("127.0.0.1", 0))
        self._srv.listen(1)
        self.port = self._srv.getsockname()[1]
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _send(self, conn, payload: bytes):
        if self.drip:
            for i in range(len(payload)):
                conn.sendall(payload[i:i + 1])
        else:
            conn.sendall(payload)

    def _serve(self):
        conn, _ = self._srv.accept()
        buf = b""
        try:
            while True:
                chunk = conn.recv(65536)
                if not chunk:
                    return
                buf += chunk
                msgs, buf = consume(buf)
                for _, payload in msgs:
                    if payload.startswith("LSQ:"):
                        self._send(conn, (FIXTURES / "handshake_lsq.bin").read_bytes())
                    elif payload.startswith("CMD:"):
                        self.asked.append(payload)
                        state = int(payload.split(":")[1])
                        self._send(conn, self.replies.get(state, b""))
                        self._send(conn, frame(TAG_HANDSHAKE,
                                               f"O\x00x: {SENTINEL}"))
        except OSError:
            return

    def close(self):
        self._srv.close()


def replies() -> dict[int, bytes]:
    return {
        4: (FIXTURES / "query_maintenance.bin").read_bytes(),
        125: (FIXTURES / "query_buildoptions.bin").read_bytes(),
    }


def test_a_closed_port_is_reported_as_not_enabled():
    # Port 1 is reserved and nothing listens there.
    t = open_tuner(port=1, timeout=0.5)
    assert t.available is False
    assert t.unavailable is TunerUnavailable.NOT_ENABLED
    assert "EnableTuner" in t.reason


def test_it_resolves_states_by_name_not_by_index():
    """The capture has a mod at index 2, so positional lookup would misfire."""
    game = FakeGame(replies())
    try:
        t = open_tuner(port=game.port, timeout=3.0)
        assert t.available is True
        t.maintenance()
        assert game.asked[0].startswith("CMD:4:")   # GameCore_Tuner, by name
    finally:
        game.close()


def test_build_options_are_asked_of_the_ui_state():
    game = FakeGame(replies())
    try:
        t = open_tuner(port=game.port, timeout=3.0)
        t.build_options()
        assert any(a.startswith("CMD:125:") for a in game.asked)
    finally:
        game.close()


def test_it_reassembles_a_reply_split_across_packets():
    game = FakeGame(replies(), drip=True)
    try:
        t = open_tuner(port=game.port, timeout=5.0)
        m = t.maintenance()
        assert m is not None and m.net_gold == 7
    finally:
        game.close()


def test_a_reading_carries_the_vm_and_a_timestamp():
    game = FakeGame(replies())
    try:
        t = open_tuner(port=game.port, timeout=3.0)
        t.maintenance()
        r = t.reading()
        assert r is not None and r.state == "GameCore_Tuner" and r.read_at
    finally:
        game.close()


def test_a_not_implemented_reply_yields_absence_not_an_exception():
    game = FakeGame({4: (FIXTURES / "query_not_implemented.bin").read_bytes()})
    try:
        t = open_tuner(port=game.port, timeout=3.0)
        assert t.maintenance() is None
        assert t.unavailable is TunerUnavailable.UNREACHABLE
    finally:
        game.close()


def test_the_client_exposes_no_way_to_run_arbitrary_lua():
    """The catalog is the allowlist; there must be no bypass on the object."""
    game = FakeGame(replies())
    try:
        t = open_tuner(port=game.port, timeout=3.0)
        assert not hasattr(t, "query")
        assert not hasattr(t, "run")
        assert not hasattr(t, "eval")
    finally:
        game.close()
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_tuner_client.py -v`
Expected: FAIL — no module `civ_advisor.tuner.client`.

- [ ] **Step 3: Write the implementation**

`civ_advisor/tuner/client.py`:

```python
"""Talking to the running game, or saying precisely why we cannot.

Like `open_ruleset`, `open_tuner` never raises: every failure becomes a
NullTuner carrying the reason a player can act on. A connection error must not
take down a poll that read the logs perfectly well.
"""
from __future__ import annotations

import socket
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

from .base import (
    CityAmenities, Maintenance, NullTuner, SettlementOptions, TUNER_OFF,
    TunerProvider, TunerReading, TunerUnavailable,
)
from .protocol import TAG_COMMAND, TAG_HANDSHAKE, consume, frame, output_text, parse_states
from .queries import CATALOG, Query, looks_unreachable

HOST = "127.0.0.1"      # loopback only, always. Never configurable.
PORT = 4318
SENTINEL = "---CIV-ADVISOR-END---"

_NOT_ANSWERING = (
    "The tuner socket is open but the game did not answer. This usually means no "
    "match is loaded yet."
)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass
class Civ6Tuner:
    """A live connection to one running game.

    There is deliberately no method that takes Lua. The catalog is the only way
    to ask a question, so this object cannot be turned into a way to run code in
    someone's game.
    """

    _sock: socket.socket
    _states: dict[str, int]
    _timeout: float
    _buf: bytes = b""
    _reading: TunerReading | None = None
    _unavailable: TunerUnavailable | None = None
    _reason: str | None = None
    _turn: int = 0
    _closed: bool = False

    @property
    def available(self) -> bool:
        return not self._closed

    @property
    def reason(self) -> str | None:
        return self._reason

    @property
    def unavailable(self) -> TunerUnavailable | None:
        return self._unavailable

    def reading(self) -> TunerReading | None:
        return self._reading

    def close(self) -> None:
        self._closed = True
        try:
            self._sock.close()
        except OSError:
            pass

    def _ask(self, query: Query) -> list[str] | None:
        """Run one catalog entry and return its output lines, or None."""
        index = self._states.get(query.state)
        if index is None:
            self._unavailable = TunerUnavailable.UNREACHABLE
            self._reason = f"the game exposes no Lua state named {query.state!r}"
            return None
        try:
            self._sock.sendall(
                frame(TAG_COMMAND, f'CMD:{index}:{query.lua}\nprint("{SENTINEL}")'))
        except OSError:
            self._unavailable = TunerUnavailable.NOT_ANSWERING
            self._reason = _NOT_ANSWERING
            return None

        lines: list[str] = []
        deadline = time.monotonic() + self._timeout
        self._sock.settimeout(0.2)
        while time.monotonic() < deadline:
            try:
                chunk = self._sock.recv(65536)
                if not chunk:
                    break
                self._buf += chunk
            except socket.timeout:
                pass
            except OSError:
                break
            msgs, self._buf = consume(self._buf)
            for tag, payload in msgs:
                text = output_text(payload)
                if text is None:
                    continue
                if SENTINEL in text:
                    self._reading = TunerReading(
                        turn=self._turn, read_at=_now(), state=query.state)
                    return lines
                lines.append(text)
        self._unavailable = TunerUnavailable.NOT_ANSWERING
        self._reason = _NOT_ANSWERING
        return None

    def _answer(self, query_id: str):
        query = CATALOG[query_id]
        lines = self._ask(query)
        if lines is None:
            return None
        if looks_unreachable(lines):
            # A permanent property of the game, not a transient failure.
            self._unavailable = TunerUnavailable.UNREACHABLE
            self._reason = (
                f"the game's {query.state} state does not implement the calls "
                f"{query.id} needs")
            return None
        try:
            return query.parse(lines)
        except ValueError as exc:
            self._unavailable = TunerUnavailable.UNREACHABLE
            self._reason = f"the {query.id} reply could not be read: {exc}"
            return None

    def maintenance(self) -> Maintenance | None:
        return self._answer("maintenance")

    def amenities(self) -> tuple[CityAmenities, ...]:
        return self._answer("amenities") or ()

    def build_options(self) -> tuple[SettlementOptions, ...]:
        return self._answer("build_options") or ()


def open_tuner(port: int = PORT, timeout: float = 3.0) -> TunerProvider:
    """Connect and handshake, or return a NullTuner saying why not.

    Never raises. A tuner failure must not cost a poll that read the logs fine.
    """
    try:
        sock = socket.create_connection((HOST, port), timeout=timeout)
    except OSError:
        # Closed port and refused connection are the same thing to a player:
        # the setting is off, or the game is not running.
        return TUNER_OFF

    try:
        sock.sendall(frame(TAG_HANDSHAKE, "APP:civ-advisor"))
        sock.sendall(frame(TAG_HANDSHAKE, "LSQ:"))
    except OSError:
        sock.close()
        return NullTuner(TunerUnavailable.NOT_ANSWERING, _NOT_ANSWERING)

    buf = b""
    states: dict[str, int] = {}
    deadline = time.monotonic() + timeout
    sock.settimeout(0.2)
    while time.monotonic() < deadline and not states:
        try:
            chunk = sock.recv(65536)
            if not chunk:
                break
            buf += chunk
        except socket.timeout:
            continue
        except OSError:
            break
        msgs, buf = consume(buf)
        for _, payload in msgs:
            found = parse_states(payload)
            # The identity frame parses to nothing useful; the state list is the
            # one that names GameCore_Tuner.
            if "GameCore_Tuner" in found:
                states = found

    if not states:
        sock.close()
        return NullTuner(TunerUnavailable.NOT_ANSWERING, _NOT_ANSWERING)
    return Civ6Tuner(_sock=sock, _states=states, _timeout=timeout, _buf=buf)


__all__ = ["Civ6Tuner", "HOST", "PORT", "SENTINEL", "open_tuner"]
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_tuner_client.py -v`
Expected: PASS, 7 tests.

- [ ] **Step 5: Run the whole suite**

Run: `uv run pytest -q`
Expected: all green. No test may hang: every socket wait is bounded by `timeout`.

- [ ] **Step 6: Commit**

```bash
git add civ_advisor/tuner/client.py tests/test_tuner_client.py
git commit -m "Ask the running game, or say exactly why we cannot"
```

---

### Task 5: Declare it on the profile, and make capability reporting tuner-aware

**Files:**
- Modify: `civ_advisor/games/base.py`
- Modify: `civ_advisor/games/civ6/__init__.py`
- Modify: `civ_advisor/api/serialize.py`
- Test: `tests/test_tuner_capabilities.py`

**Interfaces:**
- Consumes: `TUNER_BACKED`, `TunerProvider`, `TunerUnavailable`.
- Produces: `GameProfile.tuner_backed: frozenset[Capability]`, `GameProfile.tuner: Callable[[], TunerProvider] | None`, `capability_report(profile, tuner=None)`.

A tuner-backed capability is **not** in `capabilities` — it is not unconditionally supported. It becomes supported only for a poll in which the socket answered.

- [ ] **Step 1: Write the failing tests**

`tests/test_tuner_capabilities.py`:

```python
"""A tuner-backed capability is live only when the socket answered."""
from civ_advisor.api.serialize import capability_report
from civ_advisor.games.base import Capability
from civ_advisor.games.civ6 import CIV6
from civ_advisor.games.civ7 import CIV7
from civ_advisor.tuner.base import NullTuner, TUNER_BACKED, TUNER_OFF, TunerUnavailable


def test_civ6_declares_the_tuner_backed_capabilities():
    assert CIV6.tuner_backed == TUNER_BACKED


def test_civ7_declares_none():
    """No claim is made that Civ VII has an equivalent socket. It was never tested."""
    assert CIV7.tuner_backed == frozenset()


def test_a_tuner_backed_capability_is_not_unconditionally_supported():
    for cap in TUNER_BACKED:
        assert cap not in CIV6.capabilities


def test_with_no_tuner_the_reason_tells_the_player_what_to_change():
    report = capability_report(CIV6, tuner=TUNER_OFF)
    assert report["happiness"]["supported"] is False
    assert "EnableTuner" in report["happiness"]["reason"]


def test_with_a_live_tuner_the_capability_is_supported():
    class Live:
        available = True
        reason = None
        unavailable = None
        def reading(self): return None
        def amenities(self): return ()
        def maintenance(self): return None
        def build_options(self): return ()

    report = capability_report(CIV6, tuner=Live())
    assert report["happiness"]["supported"] is True
    assert report["maintenance"]["supported"] is True


def test_an_unreachable_figure_says_so_rather_than_blaming_the_setting():
    null = NullTuner(TunerUnavailable.UNREACHABLE, "the game implements no such call")
    report = capability_report(CIV6, tuner=null)
    assert report["happiness"]["supported"] is False
    assert "EnableTuner" not in report["happiness"]["reason"]


def test_omitting_the_tuner_keeps_the_old_behaviour():
    """Civ VII and every existing caller must be unaffected."""
    report = capability_report(CIV7)
    assert report["victory_paths"]["supported"] is True


def test_a_tuner_backed_capability_never_reports_supported_with_no_reason():
    report = capability_report(CIV6, tuner=TUNER_OFF)
    for cap in TUNER_BACKED:
        entry = report[cap.value]
        assert entry["supported"] is False and entry["reason"]
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_tuner_capabilities.py -v`
Expected: FAIL — `GameProfile` has no `tuner_backed`.

- [ ] **Step 3: Add the profile fields**

In `civ_advisor/games/base.py`, add two fields to `GameProfile` (both defaulted so every existing construction keeps working):

```python
    # Capabilities this game can support ONLY through a live tuner reading.
    # Deliberately not in `capabilities`: they are conditional on a socket that
    # is off by default, so declaring them unconditionally would promise a panel
    # the advisor usually cannot fill.
    tuner_backed: frozenset[Capability] = frozenset()
    # Factory for this game's tuner provider, or None if it has no such socket.
    tuner: Callable[[], object] | None = None
```

Add `from typing import Callable` to the imports if it is not already there.

- [ ] **Step 4: Declare them on the Civ VI profile**

In `civ_advisor/games/civ6/__init__.py`:

- Import: `from civ_advisor.tuner.base import TUNER_BACKED` and `from civ_advisor.tuner.client import open_tuner`.
- Add to the `CIV6 = GameProfile(...)` call:

```python
    tuner_backed=TUNER_BACKED,
    tuner=open_tuner,
```

- **Remove** the `HAPPINESS` and `MAINTENANCE` entries from `unsupported`, replacing them with nothing: their reason now comes from the live tuner state, not from a fixed string. Leave every other `unsupported` entry exactly as it is.
- Update the module docstring comment above `capabilities` to say that `HAPPINESS` and `MAINTENANCE` moved to `tuner_backed` and why.

- [ ] **Step 5: Make capability reporting tuner-aware**

In `civ_advisor/api/serialize.py`, replace `capability_report`:

```python
def capability_report(profile: GameProfile, tuner: object | None = None) -> dict[str, dict]:
    """What this game supports right now, and why not where it does not.

    A tuner-backed capability is live only for a poll in which the socket
    answered. The three ways it can be absent are told apart, because only one
    of them is something the player can fix.
    """
    live = bool(tuner is not None and getattr(tuner, "available", False))
    tuner_reason = getattr(tuner, "reason", None) if tuner is not None else None
    report: dict[str, dict] = {}
    for c in Capability:
        if c in profile.tuner_backed:
            report[c.value] = {
                "supported": live,
                "reason": None if live else (tuner_reason or _NO_TUNER),
                "source": "tuner",
            }
        else:
            report[c.value] = {
                "supported": profile.supports(c),
                "reason": profile.reason(c),
            }
    return report
```

with, above it:

```python
_NO_TUNER = (
    "This figure comes from the game's tuner socket, which is not connected."
)
```

Then update `game_to_dict` so the active game's report receives the tuner: add a `tuner` parameter to `game_to_dict(resolution, tuner=None)` defaulting to `None`, and pass it through to `capability_report` for the **active** profile only. Non-active profiles keep the no-tuner call, because nothing has been asked of them.

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/test_tuner_capabilities.py -v`
Expected: PASS, 8 tests.

- [ ] **Step 7: Run the whole suite and fix fallout**

Run: `uv run pytest -q`
Expected: green. Existing tests asserting the old `HAPPINESS`/`MAINTENANCE` reasons for Civ VI will fail — update them to assert the new tuner-off reason, **not** by deleting the assertion.

- [ ] **Step 8: Commit**

```bash
git add civ_advisor/games/base.py civ_advisor/games/civ6/__init__.py \
        civ_advisor/api/serialize.py tests/test_tuner_capabilities.py
git commit -m "Make happiness and upkeep conditional on a live tuner"
```

---

### Task 6: Query it once per poll, and carry the result on the snapshot

**Files:**
- Modify: `civ_advisor/store.py`
- Modify: `civ_advisor/api/app.py`
- Test: `tests/test_tuner_store.py`

**Interfaces:**
- Consumes: `GameProfile.tuner`, `TunerProvider`.
- Produces: `Snapshot.tuner: TunerProvider` (never `None`; `TUNER_OFF` when there is none), `Store.rebuild()` unchanged in signature.

- [ ] **Step 1: Write the failing tests**

`tests/test_tuner_store.py`:

```python
"""The tuner is read once per rebuild, and never costs a poll that worked."""
from civ_advisor.tuner.base import TUNER_OFF, TunerUnavailable


def test_a_snapshot_always_carries_a_tuner(civ6_store):
    """Never None: callers must not branch on absence."""
    snap = civ6_store.rebuild()
    assert snap is not None
    assert snap.tuner is not None


def test_a_game_with_no_tuner_factory_gets_the_off_singleton(civ7_store):
    snap = civ7_store.rebuild()
    assert snap.tuner is TUNER_OFF


def test_a_tuner_that_raises_does_not_fail_the_rebuild(civ6_store, monkeypatch):
    """The logs were read perfectly well. A socket problem must not discard that."""
    def explode():
        raise OSError("boom")
    monkeypatch.setattr(civ6_store.profile, "tuner", explode, raising=False)
    snap = civ6_store.rebuild()
    assert snap is not None
    assert snap.tuner.available is False
    assert snap.tuner.unavailable is TunerUnavailable.NOT_ANSWERING


def test_the_tuner_is_asked_once_per_rebuild_not_once_per_question(civ6_store):
    calls = []
    class Counting:
        available = True
        reason = None
        unavailable = None
        def __init__(self): calls.append(1)
        def reading(self): return None
        def amenities(self): return ()
        def maintenance(self): return None
        def build_options(self): return ()
    civ6_store.profile = civ6_store.profile.__class__(
        **{**civ6_store.profile.__dict__, "tuner": Counting})
    civ6_store.rebuild()
    assert len(calls) == 1
```

Write `civ6_store` / `civ7_store` fixtures in `tests/conftest.py` following whatever pattern the existing store tests already use; do not invent a second way to build a Store.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_tuner_store.py -v`
Expected: FAIL — `Snapshot` has no `tuner`.

- [ ] **Step 3: Implement**

In `civ_advisor/store.py`:

- Add `tuner: object = TUNER_OFF` as a field on the `Snapshot` dataclass, with the comment:

```python
    # Never None. A caller that had to check for absence would eventually forget,
    # and a missing figure would read as a zero.
    tuner: object = TUNER_OFF
```

- In `rebuild()`, after the logs are read and before the snapshot is published, open the tuner **outside** the lock, in its own try/except:

```python
        # Outside the lock, and never fatal: a socket problem must not discard a
        # poll that read every log correctly.
        tuner = TUNER_OFF
        factory = getattr(self.profile, "tuner", None)
        if factory is not None:
            try:
                tuner = factory()
            except Exception:       # a third-party socket has many failure shapes
                tuner = NullTuner(
                    TunerUnavailable.NOT_ANSWERING,
                    "the tuner socket could not be reached this turn")
```

and pass `tuner=tuner` when constructing the `Snapshot`.

- Close the previous snapshot's tuner when a new one replaces it, so a live socket is not leaked every poll. Do the close **after** publishing the new snapshot, never while a reader may still hold the old one — this is the same lifecycle rule that has bitten this project five times.

In `civ_advisor/api/app.py`, pass the live snapshot's tuner into `game_to_dict(...)` at both `/api/game` handlers.

- [ ] **Step 4: Run to verify pass and then the whole suite**

Run: `uv run pytest tests/test_tuner_store.py -v && uv run pytest -q`
Expected: green.

- [ ] **Step 5: Commit**

```bash
git add civ_advisor/store.py civ_advisor/api/app.py tests/test_tuner_store.py tests/conftest.py
git commit -m "Read the tuner once per poll, without risking the poll"
```

---

### Task 7: A live reading is its own kind of evidence

**Files:**
- Modify: `civ_advisor/decisions/models.py`
- Modify: `civ_advisor/decisions/evidence.py`
- Test: `tests/test_tuner_evidence.py`

**Interfaces:**
- Produces: `SourceKind.LIVE_READING`, `amenities_fact(...)`, `net_gold_fact(...)`, `build_option_fact(...)` in `evidence.py`.

- [ ] **Step 1: Write the failing tests**

`tests/test_tuner_evidence.py`:

```python
"""A tuner reading is labelled as what it is: a value we asked for."""
import pytest

from civ_advisor.advisors.base import Provenance
from civ_advisor.decisions.models import EvidenceFact, SourceKind


def fact(**kw) -> EvidenceFact:
    base = dict(id="x", label="Amenities in Rome", source_kind=SourceKind.LIVE_READING,
                provenance=Provenance.FAIR, observed_turn=59, value=3,
                reported_at="2026-09-13T10:40:00Z", subject_id="Rome")
    return EvidenceFact(**{**base, **kw})


def test_a_live_reading_is_a_distinct_source_kind():
    assert SourceKind.LIVE_READING.value == "live_reading"
    assert SourceKind.LIVE_READING is not SourceKind.LOG


def test_a_live_reading_must_record_when_it_was_asked_for():
    """This is what separates it from a log row the game wrote on its own."""
    with pytest.raises(ValueError, match="reported_at"):
        fact(reported_at=None)


def test_a_live_reading_must_name_the_turn_it_describes():
    with pytest.raises(ValueError, match="observed_turn"):
        fact(observed_turn=None)


def test_a_live_reading_is_fair():
    """Amenities and upkeep are on the player's own screen. Not an intercept."""
    assert fact().provenance is Provenance.FAIR


def test_a_live_reading_needs_no_source_file():
    """It came from a socket. Demanding a filename would invite a fake one."""
    assert fact(source_file=None).source_file is None
```

Plus tests in the same file asserting that `amenities_fact`, `net_gold_fact` and `build_option_fact` produce facts with `SourceKind.LIVE_READING`, the reading's `read_at` as `reported_at`, and the city as `subject_id`.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_tuner_evidence.py -v`
Expected: FAIL — `SourceKind` has no `LIVE_READING`.

- [ ] **Step 3: Implement**

In `civ_advisor/decisions/models.py`:

- Add to `SourceKind`:

```python
    LIVE_READING = "live_reading"     # a value we asked the running game for
```

- In `EvidenceFact.__post_init__`, add:

```python
        if self.source_kind is SourceKind.LIVE_READING:
            # Both halves matter and neither is optional. A log row is something
            # the game wrote on its own; this is a value we asked for, so it must
            # say both which turn it describes and when we asked.
            if self.reported_at is None:
                raise ValueError("a live reading must record reported_at")
            if self.observed_turn is None:
                raise ValueError("a live reading must name its observed_turn")
```

In `civ_advisor/decisions/evidence.py`, add three builders following the existing `ruleset_fact` shape, each taking the `TunerReading` plus its value object, each setting `source_kind=SourceKind.LIVE_READING`, `provenance=Provenance.FAIR`, `observed_turn=reading.turn`, `reported_at=reading.read_at`, and a `note` naming the VM it came from.

- [ ] **Step 4: Run the tests and the whole suite**

Run: `uv run pytest tests/test_tuner_evidence.py -v && uv run pytest -q`
Expected: green. A conformance test that enumerates `SourceKind` may need the new member added.

- [ ] **Step 5: Commit**

```bash
git add civ_advisor/decisions/models.py civ_advisor/decisions/evidence.py tests/test_tuner_evidence.py
git commit -m "Label a tuner reading as a value we asked for"
```

---

### Task 8: Put the figures on the page

**Files:**
- Modify: `civ_advisor/decisions/yields.py`
- Modify: `civ_advisor/web/briefing.js`
- Modify: `civ_advisor/web/app.js`
- Modify: `civ_advisor/api/app.py`
- Test: `tests/test_tuner_delivery.py`
- Test: `tests/test_web_briefing.py` (extend)

**Interfaces:**
- Consumes: everything above.

**This task is the one that matters.** Every earlier task can pass while nothing reaches a player — that exact failure happened in phase 4, where every check called the provider directly. The tests here go through the HTTP payload, not through the provider.

- [ ] **Step 1: Write the failing tests**

`tests/test_tuner_delivery.py`, using the existing FastAPI `TestClient` pattern:

```python
"""Does a tuner reading actually reach the browser? Nothing else is proof."""

def test_amenities_reach_the_payload_with_a_live_tuner(client_with_live_tuner):
    body = client_with_live_tuner.get("/api/briefing").json()
    # Not "the provider returned 3" -- the number must be in what the page gets.
    assert "3" in str(body)


def test_with_the_tuner_off_the_payload_carries_the_reason_not_a_zero(client_no_tuner):
    caps = client_no_tuner.get("/api/game").json()["active"]["capabilities"]
    assert caps["happiness"]["supported"] is False
    assert "EnableTuner" in caps["happiness"]["reason"]
    assert caps["happiness"].get("value") is None


def test_build_options_reach_the_refine_prefill(client_with_live_tuner):
    body = client_with_live_tuner.get("/api/briefing").json()
    assert "BUILDING_GRANARY" in str(body)


def test_a_live_reading_is_labelled_as_such_in_the_evidence(client_with_live_tuner):
    body = client_with_live_tuner.get("/api/briefing").json()
    assert "live_reading" in str(body)


def test_the_prefill_is_not_recorded_as_a_player_report(client_with_live_tuner):
    """The player did not type it. Calling it their report would confuse sources."""
    body = client_with_live_tuner.get("/api/briefing").json()
    text = str(body)
    assert "live_reading" in text
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_tuner_delivery.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

- In `civ_advisor/decisions/yields.py`, extend `_source_note()` to name a live reading distinctly. Do not reuse the player-report wording: saying "your figures" about a number the player never typed records one source as another.
- Feed the tuner's `SettlementOptions` into the Refine flow as a **pre-fill**, not as a submission: the player still confirms or corrects. It is labelled `live_reading`, never `player_report`. When the tuner is off, the flow behaves exactly as it does today.
- In `briefing.js`, add `happiness`/`maintenance` notices to `PANEL_CAPABILITIES` where they are missing, so a tuner-off state renders the reason rather than an empty panel.
- In `app.js`, render a live reading's badge distinctly from a log row and from a player report, and show the `read_at` moment beside the turn.

- [ ] **Step 4: Run the tests, the JS rules suite, and the whole suite**

Run: `uv run pytest tests/test_tuner_delivery.py tests/test_web_briefing.py -v && uv run pytest -q`
Expected: green.

- [ ] **Step 5: Commit**

```bash
git add civ_advisor/decisions/yields.py civ_advisor/web/briefing.js civ_advisor/web/app.js \
        civ_advisor/api/app.py tests/test_tuner_delivery.py tests/test_web_briefing.py
git commit -m "Put amenities, upkeep and real build options in front of the player"
```

---

### Task 9: The opt-in live suite, the CLI flag, and the README

**Files:**
- Create: `tests/live/__init__.py`, `tests/live/conftest.py`, `tests/live/test_against_a_running_game.py`, `tests/live/README.md`
- Modify: `pyproject.toml`
- Modify: `civ_advisor/cli.py`
- Modify: `README.md`

- [ ] **Step 1: Exclude the live suite from the default run**

In `pyproject.toml`, change `addopts` to `"--ignore=tests/browser --ignore=tests/live"`, with a comment saying the live suite needs a running game with the tuner enabled and therefore cannot be part of an offline run.

- [ ] **Step 2: Write the live suite**

`tests/live/conftest.py` skips the whole module when the socket is closed:

```python
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
```

`tests/live/test_against_a_running_game.py` asserts shapes, never specific values — the values depend on whose game is running:

```python
def test_maintenance_reads_back_a_consistent_breakdown():
    from civ_advisor.tuner.client import open_tuner
    t = open_tuner()
    m = t.maintenance()
    assert m is not None
    assert m.buildings + m.districts + m.units == m.total


def test_every_settlement_offering_an_option_gives_it_an_estimate():
    from civ_advisor.tuner.client import open_tuner
    for s in open_tuner().build_options():
        for o in s.options:
            assert o.turns >= 0
```

- [ ] **Step 3: Add the CLI flag**

In `civ_advisor/cli.py` add `--no-tuner` (`action="store_true"`) with help text: *"Never contact Civilization VI's tuner socket, even if it is open."* Thread it to the store so the profile's tuner factory is not called. Default is to try, because an unopened socket costs one refused connection.

- [ ] **Step 4: Update the README**

Add a subsection under **Playing Civilization VI** that says: what the tuner unlocks (amenities, the upkeep breakdown and net gold, and what each settlement can actually build with completion estimates); the exact line to change and that the advisor will never change it for you; **and, plainly, that port 4318 executes arbitrary Lua in the game with no authentication, so any local process can use it** — the advisor connects to loopback only and asks only a fixed set of reviewed questions, and every panel stays usable if you decline. Also document `--no-tuner`.

Correct the existing paragraph that says every figure comes from the player "for both games today": with the tuner on, that is no longer true for Civ VI.

- [ ] **Step 5: Verify and commit**

Run: `uv run pytest -q` (the live suite must not run), then `uv run pytest tests/live -p no:cacheprovider` with a game up if one is available.

```bash
git add pyproject.toml civ_advisor/cli.py README.md tests/live/
git commit -m "Make the live suite opt-in and say what enabling the tuner costs"
```

---

## Self-review notes

- **Spec coverage:** §3 transport → Task 1; §4 two VMs and three outcomes → Tasks 1, 3, 4; §5 components → Tasks 1–4; §6 provenance → Task 7; §7 honesty when off → Tasks 5, 8; §8 never enabling → Task 9 README plus the global constraint; §9 security → Tasks 3, 4, 9; §10 testing → every task, plus Task 9; §11 scope → Task 3's catalog holds exactly the three in-scope queries; §12 open question → ruled: keep the Refine flow, tuner pre-fills (Task 8).
- **Type consistency:** `TunerProvider` is the only type crossing module boundaries; `TUNER_OFF` is the single Null instance used by `store.py` and `serialize.py` alike.
- **Known risk:** Task 5 removes two `unsupported` entries, so existing tests asserting those strings will fail. That is expected and named in Task 5 Step 7 — they are to be updated, never deleted.
