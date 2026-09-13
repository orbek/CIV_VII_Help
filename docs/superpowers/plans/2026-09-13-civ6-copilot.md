# Civ VI Copilot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A conversation box beside the briefing that answers anything the player asks from the installed ruleset, the logs and the live tuner reading — every number in its prose traceable to a cited fact or the prose rejected — and, only if a write spike proves it works, one reviewed operation the player confirms individually, off by default and journaled.

**Architecture:** A new `civ_advisor/copilot/` package: `grounding.py` (the number rule, one function, shared with `llm/questions.py`), `catalog.py` (the fixed allowlist of named questions the model may ask, resolving to `EvidenceFact`s through the existing builders or to a declared `Absence`), `conversation.py` (two-phase generation: select questions, then compose; deterministic fallback; per-sitting transcript), `worker.py` (one background thread), and — contingent on Task 1 — `actions.py` and `journal.py` for proposals and the record of what was sent. The tuner package gains `commands.py`, the write-side allowlist mirroring `queries.py`, and an `ActingTuner` that is the only object with a `perform` method. `ruleset/civ6.py`'s `READABLE_COLUMNS` grows by the tables the spec lists, each verified against the installed file.

**Tech Stack:** Python 3.12, stdlib `re`/`decimal`/`json`/`os.fsync`, pytest, node for the briefing rules. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-13-civ6-copilot-design.md`

## Global Constraints

- **Task 1 runs first and its result gates Tasks 10–12.** Nothing about acting is implemented until `docs/research/2026-09-13-civ6-tuner-write-spike.md` exists and names an outcome A–F from spec §6. Tasks 10–12 each open by stating which outcome they assume; if the recorded outcome is B, C or F, Tasks 10–12 are **not performed** and Task 9's proposal card renders with no confirm button.
- **The program is read-only with respect to both games' directories.** It never writes `AppOptions.txt`, never leaves a file under a game folder, never touches a save. Acting sends a command into a running game over a socket the player opened; it writes no file of the game's. The journal lives under `~/.civ-advisor/<game>/`.
- **The model never writes SQL and never writes Lua.** It names a catalog question or a catalog operation and supplies parameter values. Every parameter is validated against a set the program computed (`YIELD_STATS`, this snapshot's city names, `RULE_PARAMETERS`) or a regex for a bound SQL value. No player text is ever a parameter.
- **Every number in generated prose must appear in a cited fact** — `value`, `observed_turn`, or a numeral in `note` — or the prose is rejected and the deterministic answer is shown. Spec §4.3 is the definition; `copilot/grounding.py:check` is the implementation; `questions.validate` and `conversation.validate_answer` both call it. A figure only the player reported is attributed as theirs (rule 6); a number the player just typed is never a citation, may be repeated only as their claim, and a cited figure is stated beside it rather than dropped (rule 7).
- **Provenance is never blended.** Five `SourceKind`s exist; this plan adds none and every fact it produces uses the existing builders.
- **Absence is declared, never inferred, and names the real cause.** An `Absence` carries a kind the page branches on; a tuner absence carries the `TunerUnavailable` enum; a ruleset absence carries the provider's reason; a `not_logged` absence carries the profile's own `unsupported` text. An absence is ESTABLISHED from its source, never read off the shape of a failure: a refused connection does not mean the tuner is off (spec §4.6), and where the source cannot be consulted the absence says so rather than picking the likeliest story.
- **A figure is never attached to a turn it did not come from.** Conversation history is context, not evidence: the current answer cites facts resolved from the current snapshot. A proposal built on turn N is not sent into turn N+1.
- **Acting is off by default, per run.** `--allow-actions` enables it; without it no `ActingTuner` is constructed and `POST /api/copilot/act` is 403. The flag refuses a non-loopback `--host`.
- **Every action is journaled before it is sent.** An unwritable journal makes the outcome `not_sent`.
- **Loopback only.** Tuner and HTTP alike.
- **Civ VI's guide catalog stays empty.** No task here adds an entry to `knowledge/civ6/guides.json`.
- **Stage only your own files, by explicit path.** Never `git add -A`. `docs/` is gitignored but tracked: documentation commits use `git add -f`.
- **The default test suite stays offline and fast.** Anything needing a running game goes in `tests/live/`. The acting live test additionally requires `CIV_ADVISOR_LIVE_ACT=1`.
- Python 3.12. `filterwarnings = ["error", ...]` is in force.
- **No default-suite test may depend on whether port 4318 is listening.** Two shipped tests do — `tests/test_api.py::test_a_capability_gap_coexists_with_the_real_data_it_does_not_gate` and `tests/test_tuner_store.py::test_a_game_that_has_a_socket_is_still_told_the_socket_is_off` — and fail with `NOT_ANSWERING` where they expect `NOT_ENABLED` whenever a Civ VI with the tuner on is open (measured 2026-09-13: exactly these two, on the current tree). Commit `1e78a2f` isolated both with `tests/conftest.py:unreachable_tuner`, which points the profile's tuner at port 1; Task 2 must keep that isolation honest by giving the helper an `AppOptions.txt` saying `EnableTuner 0`, or a refusal on port 1 becomes `UNESTABLISHED` and the store test fails again. Never fix such a test by skipping when a socket is found.

---

### Task 1: The write-capability spike, on a throwaway save

**Files:**
- Create: `scripts/spike_tuner_write.py`
- Create: `docs/research/2026-09-13-civ6-tuner-write-spike.md`
- Create (captures): `tests/fixtures/tuner/write_probe_bindings.bin`, `tests/fixtures/tuner/write_set_production.bin`, `tests/fixtures/tuner/write_readback.bin`, `tests/fixtures/tuner/write_revert.bin`, `tests/fixtures/tuner/query_buildoptions_ids.bin`
- Modify: `tests/fixtures/tuner/README.md`

**Interfaces:**
- Consumes: `civ_advisor.tuner.protocol` (`frame`, `consume`, `output_text`, `parse_states`, `TAG_COMMAND`, `TAG_HANDSHAKE`).
- Produces: a findings document naming one outcome A–F, and the raw captures Tasks 7 and 10 parse.

This script is the ONE place outside the package that sends Lua it composed itself, and it is never imported by `civ_advisor`. It exists to answer a question, not to become a feature: after it runs, the answer lives in the findings document and the captures, and the script is kept only so the experiment is repeatable when the game is patched.

Preconditions, all done by a human:

1. Start Civilization VI with `[Debug] EnableTuner 1`. Load a match you do not care about, **or** save the current match under a new name first (in-game: Save Game, a fresh slot) so that whatever happens, the save you play is untouched. The script will ask you to type the word `throwaway` before it sends anything.
2. Note which city you will experiment on and what it is building now, from the game's own city screen. You will compare against that.
3. Quit the advisor if it is running: two clients on the socket at once is one more variable than this experiment needs.

- [ ] **Step 1: Record what the installed game's UI does, before sending anything**

Read, do not modify, `Civ6.app/Contents/Assets/Base/Assets/UI/Panels/ProductionPanel.lua` under the Steam install (`~/Library/Application Support/Steam/steamapps/common/Sid Meier's Civilization VI/`). Copy into the findings document, verbatim with line numbers: `BuildBuilding` (lines 334–370 on the 2026-09-13 install) and `GetBuildInsertMode` (around lines 2880–2900), and the read-back at line 1894 (`buildQueue:GetCurrentProductionTypeHash()`). These are the bindings the game's own UI uses; the spike tries the same ones.

- [ ] **Step 2: Write the spike script**

`scripts/spike_tuner_write.py`:

```python
"""One reversible write through the tuner, on a throwaway save. Run by hand.

This is an EXPERIMENT, not a feature, and the only code in this repository that
sends Lua it composed itself. `civ_advisor` never imports it. It exists to answer
spec 2026-09-13-civ6-copilot-design.md section 6: does CityManager.RequestOperation
work when the chunk arrives over the tuner socket, does the game validate it, and
what does a refused request do. Every frame the game sends back is saved, so the
answer is a capture and not a memory.

Usage:
    uv run python scripts/spike_tuner_write.py --city 0 --item BUILDING_GRANARY

It will not send the write until you type the word `throwaway`.
"""
from __future__ import annotations

import argparse
import socket
import sys
import time
from pathlib import Path

from civ_advisor.tuner.protocol import (
    TAG_COMMAND, TAG_HANDSHAKE, consume, frame, output_text, parse_states,
)

HOST, PORT = "127.0.0.1", 4318
SENTINEL = "---SPIKE-END---"
FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "tuner"

# Read this poll's cities, their ids, and every building each may build, with the
# hash the operation needs. This is the query Task 7 promotes into the catalog as
# `build_options_ids`; its reply here becomes that task's fixture.
LUA_OPTIONS_IDS = (
    'print("turn", Game.GetCurrentGameTurn()) '
    'for _,c in Players[Game.GetLocalPlayer()]:GetCities():Members() do '
    'local q=c:GetBuildQueue() '
    'for row in GameInfo.Buildings() do '
    'local ok,can=pcall(function() return q:CanProduce(row.Hash,true) end) '
    'if ok and can then print(c:GetID(), Locale.Lookup(c:GetName()), row.BuildingType, '
    'row.Hash, tostring(row.RequiresPlacement), q:GetTurnsLeft(row.Hash)) end end end'
)

# Which of the bindings the write needs exist in InGame, and in which of the three
# states the read spike taught: absent (nil), stubbed ("Not Implemented."), working.
LUA_PROBE_BINDINGS = (
    'print("CityManager", type(CityManager)) '
    'print("RequestOperation", type(CityManager and CityManager.RequestOperation)) '
    'print("CanStartOperation", type(CityManager and CityManager.CanStartOperation)) '
    'print("BUILD", tostring(CityOperationTypes and CityOperationTypes.BUILD)) '
    'print("PARAM_BUILDING_TYPE", tostring(CityOperationTypes and CityOperationTypes.PARAM_BUILDING_TYPE)) '
    'print("PARAM_INSERT_MODE", tostring(CityOperationTypes and CityOperationTypes.PARAM_INSERT_MODE)) '
    'print("VALUE_EXCLUSIVE", tostring(CityOperationTypes and CityOperationTypes.VALUE_EXCLUSIVE)) '
    'print("VALUE_REPLACE_AT", tostring(CityOperationTypes and CityOperationTypes.VALUE_REPLACE_AT)) '
    'print("VALUE_APPEND", tostring(CityOperationTypes and CityOperationTypes.VALUE_APPEND)) '
    'local c=Players[Game.GetLocalPlayer()]:GetCities():FindID(CITYID) '
    'print("FindID", tostring(c~=nil)) '
    'if c then local q=c:GetBuildQueue() '
    'print("GetCurrentProductionTypeHash", type(q.GetCurrentProductionTypeHash)) '
    'local ok,v=pcall(function() return q:GetCurrentProductionTypeHash() end) '
    'print("current", tostring(ok), tostring(v)) '
    'print("GetPreviousProductionTypeHash", type(q.GetPreviousProductionTypeHash)) '
    'print("GetProductionProgress", type(q.GetProductionProgress)) end'
)

# The write. Same shape as ProductionPanel.lua:BuildBuilding, with the guard the
# UI does not need because its buttons only exist for legal items.
LUA_SET_PRODUCTION = (
    'local ok,err=pcall(function() '
    'local c=Players[Game.GetLocalPlayer()]:GetCities():FindID(CITYID) '
    'if c==nil then print("REJECTED", "no city with id", CITYID) return end '
    'local q=c:GetBuildQueue() '
    'print("before", q:GetCurrentProductionTypeHash()) '
    'local t={} '
    't[CityOperationTypes.PARAM_BUILDING_TYPE]=ITEMHASH '
    't[CityOperationTypes.PARAM_INSERT_MODE]=CityOperationTypes.VALUE_EXCLUSIVE '
    'if CityManager.CanStartOperation~=nil then '
    'local can=CityManager.CanStartOperation(c, CityOperationTypes.BUILD, t) '
    'print("canStart", tostring(can)) '
    'if not can then print("REJECTED", "CanStartOperation returned false") return end end '
    'CityManager.RequestOperation(c, CityOperationTypes.BUILD, t) '
    'print("requested") '
    'print("after", q:GetCurrentProductionTypeHash()) end) '
    'if not ok then print("PROBEERR", tostring(err)) end'
)

LUA_READBACK = (
    'local c=Players[Game.GetLocalPlayer()]:GetCities():FindID(CITYID) '
    'local q=c:GetBuildQueue() '
    'print("turn", Game.GetCurrentGameTurn()) '
    'print("current", q:GetCurrentProductionTypeHash()) '
    'for row in GameInfo.Buildings() do if row.Hash==q:GetCurrentProductionTypeHash() '
    'then print("currentType", row.BuildingType) end end'
)


def bind(lua: str, city_id: int, item_hash: int | None = None) -> str:
    """The spike's own parameter binding: integer literals only, checked here."""
    if type(city_id) is not int or city_id < 0:
        raise SystemExit(f"city id must be a non-negative int, got {city_id!r}")
    out = lua.replace("CITYID", str(city_id))
    if "ITEMHASH" in out:
        if type(item_hash) is not int:
            raise SystemExit(f"item hash must be an int, got {item_hash!r}")
        out = out.replace("ITEMHASH", str(item_hash))
    return out


def connect() -> tuple[socket.socket, dict[str, int]]:
    sock = socket.create_connection((HOST, PORT), timeout=5.0)
    sock.sendall(frame(TAG_HANDSHAKE, "APP:civ-advisor-spike"))
    sock.sendall(frame(TAG_HANDSHAKE, "LSQ:"))
    buf, states = b"", {}
    deadline = time.monotonic() + 5.0
    sock.settimeout(0.2)
    while time.monotonic() < deadline and not states:
        try:
            buf += sock.recv(65536)
        except socket.timeout:
            continue
        msgs, buf = consume(buf)
        for _, payload in msgs:
            found = parse_states(payload)
            if "InGame" in found:
                states = found
    if not states:
        raise SystemExit("the socket answered but named no InGame state; is a match loaded?")
    return sock, states


def run(sock: socket.socket, index: int, lua: str, capture: Path) -> list[str]:
    """Send one chunk, collect to the sentinel, save EVERY raw byte the game sent."""
    sock.sendall(frame(TAG_COMMAND, f'CMD:{index}:{lua}\nprint("{SENTINEL}")'))
    raw, buf, lines = b"", b"", []
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        try:
            chunk = sock.recv(65536)
        except socket.timeout:
            continue
        raw += chunk
        buf += chunk
        msgs, buf = consume(buf)
        done = False
        for _, payload in msgs:
            text = output_text(payload)
            if text is None:
                continue
            if SENTINEL in text:
                done = True
                break
            lines.append(text)
        if done:
            break
    capture.write_bytes(raw)
    for line in lines:
        print("   ", line)
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--city", type=int, required=True, help="city id, from the options listing")
    parser.add_argument("--item", required=True, help="BuildingType to set, e.g. BUILDING_GRANARY")
    args = parser.parse_args()

    sock, states = connect()
    ingame = states["InGame"]
    print(f"InGame is state {ingame} this session (never hardcode it)")

    print("\n1. What each city may build, with ids and hashes:")
    options = run(sock, ingame, LUA_OPTIONS_IDS, FIXTURES / "query_buildoptions_ids.bin")
    rows = [line.split("\t") for line in options if line.count("\t") == 5]
    match = [r for r in rows if int(r[0]) == args.city and r[2] == args.item]
    if not match:
        print(f"\nthe game did not offer {args.item} to city {args.city}; nothing sent")
        return 2
    item_hash = int(match[0][3])
    if match[0][4] == "true":
        print(f"\n{args.item} needs a plot (RequiresPlacement); this spike only sets a "
              "building that does not. Pick another.")
        return 2

    print("\n2. Which bindings exist in InGame:")
    run(sock, ingame, bind(LUA_PROBE_BINDINGS, args.city),
        FIXTURES / "write_probe_bindings.bin")

    print("\nThis will now send a command that CHANGES a city's production in the loaded "
          "game. Only continue on a save you would not mind losing.")
    if input("Type the word throwaway to continue: ").strip() != "throwaway":
        print("nothing sent")
        return 1

    print(f"\n3. Setting city {args.city} to {args.item} ({item_hash}):")
    before = run(sock, ingame, bind(LUA_SET_PRODUCTION, args.city, item_hash),
                 FIXTURES / "write_set_production.bin")
    previous = next((int(l.split("\t")[1]) for l in before
                     if l.startswith("before\t") and l.split("\t")[1].lstrip("-").isdigit()), None)

    print("\n4. Reading the queue back. Compare with the game's own city screen NOW:")
    run(sock, ingame, bind(LUA_READBACK, args.city), FIXTURES / "write_readback.bin")
    input("Look at the city screen. Press Enter when you have noted what it shows: ")

    if previous is None:
        print("\n5. The game named no previous item, so nothing can be set back. Reload the save.")
        return 0
    print(f"\n5. Setting it back to hash {previous}:")
    run(sock, ingame, bind(LUA_SET_PRODUCTION, args.city, previous),
        FIXTURES / "write_revert.bin")
    run(sock, ingame, bind(LUA_READBACK, args.city), FIXTURES / "write_readback.bin")
    print("\nCompare with the city screen again, then write the findings document.")
    sock.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Run it, on the throwaway save**

Run: `uv run python scripts/spike_tuner_write.py --city <id> --item <BUILDING_...>`

Pick the city id and item from step 1's listing (it prints before asking anything). Prefer a building the city is *not* already building and that shows a turn estimate. Watch the game's own city screen at steps 4 and 5.

- [ ] **Step 4: Write the findings document**

`docs/research/2026-09-13-civ6-tuner-write-spike.md`, with these sections and nothing invented in any of them:

```markdown
# Writing through the tuner: one reversible operation, <date>, turn <n>, <city>

## Outcome: <A|B|C|D|E|F> — <spec §6 row title>

## What the game's own UI does (ProductionPanel.lua, read-only)
<verbatim lines 334–370, GetBuildInsertMode, line 1894, with line numbers>

## Bindings in InGame
| Binding | absent / stubbed / working | Evidence line |
| CityManager.RequestOperation | | |
| CityManager.CanStartOperation | | |
| CityOperationTypes.VALUE_EXCLUSIVE / VALUE_REPLACE_AT / VALUE_APPEND | | |
| Cities():FindID | | |
| BuildQueue:GetCurrentProductionTypeHash | | |
| BuildQueue:GetPreviousProductionTypeHash | | |
| BuildQueue:GetProductionProgress | | |

## The write
- before: <hash / type>
- canStart: <true/false/not present>
- game reply lines, verbatim:
- after (same chunk): <hash>
- read-back (next chunk): <hash / type>
- the city screen showed: <what you saw>

## The revert
<same shape>

## Progress on the displaced item
<kept / lost / not measurable, and how you know>

## What this means for the design
<which acting tasks proceed, quoting spec §6's row>
```

- [ ] **Step 5: Document the captures**

Add a row per new `.bin` to `tests/fixtures/tuner/README.md`, in the existing table, saying what each holds and — for `write_set_production.bin` — which outcome it is evidence of. Captures are never edited to make a test pass.

- [ ] **Step 6: Commit**

```bash
git add scripts/spike_tuner_write.py tests/fixtures/tuner/
git add -f docs/research/2026-09-13-civ6-tuner-write-spike.md
git commit -m "Try one reversible write through the tuner, and record what the game did"
```

**Decision gate.** Read the outcome. Outcomes A, D and E: Tasks 10–12 are performed, each adjusted as its opening paragraph says. Outcomes B, C and F: Tasks 10–12 are skipped, Task 9 renders the proposal card without a confirm button, and Task 12's README section is written in the past tense about what was tried.

---

### Task 2: Establish whether the tuner is enabled, instead of inferring it from a refusal

**Files:**
- Create: `civ_advisor/tuner/options.py`
- Modify: `civ_advisor/tuner/base.py`
- Modify: `civ_advisor/tuner/client.py`
- Modify: `civ_advisor/games/civ6/__init__.py`
- Modify: `civ_advisor/web/briefing.js`, `README.md`
- Test: `tests/test_tuner_options.py`, `tests/test_tuner_base.py` (extend), `tests/test_tuner_client.py` (extend)

**Interfaces:**
- Consumes: `TunerUnavailable`, `NullTuner`, `open_tuner`.
- Produces: `TunerFlag` (StrEnum: `ON`, `OFF`, `UNREADABLE`), `read_enable_tuner(path) -> tuple[TunerFlag, str]`, `DEFAULT_APP_OPTIONS`, `TunerUnavailable.UNESTABLISHED`, `open_tuner(port, timeout, app_options=None)`, `GameProfile`-free: the Civ VI profile's `tuner` factory passes its own `DEFAULT_APP_OPTIONS`.

Spec §4.6. Small, independent of the spike, and the copilot's own subject: a refused connection is one observation, and the file that configures the tuner is an authoritative source the program was not reading. Reading it is permitted — the read-only rule forbids WRITING under the game's directories; the logs and the ruleset database are already read from inside them.

- [ ] **Step 1: Write the failing tests**

`tests/test_tuner_options.py`:

```python
"""Whether the tuner is enabled is READ from AppOptions.txt, never inferred from a
refused connection. Confirmed live on 2026-09-13: with EnableTuner 1 set, connections
are still refused while the game sits at the main menu."""
from pathlib import Path

import pytest

from civ_advisor.tuner.base import TunerUnavailable
from civ_advisor.tuner.client import open_tuner
from civ_advisor.tuner.options import TunerFlag, read_enable_tuner

REAL_SHAPE = """[Video]
RenderWidth 1920

[Debug]
;Enable FireTuner.
EnableTuner {value}

;Enable the debug menu.
EnableDebugMenu 1

[Misc]
EnableTuner 1
"""


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "AppOptions.txt"
    path.write_text(text)
    return path


def test_the_flag_on_is_read_from_the_debug_section(tmp_path):
    flag, detail = read_enable_tuner(write(tmp_path, REAL_SHAPE.format(value=1)))
    assert flag is TunerFlag.ON
    assert "EnableTuner 1" in detail


def test_the_flag_off_is_read_from_the_debug_section(tmp_path):
    assert read_enable_tuner(write(tmp_path, REAL_SHAPE.format(value=0)))[0] is TunerFlag.OFF


def test_a_line_outside_debug_does_not_count(tmp_path):
    """The [Misc] copy above says 1; only [Debug] governs the tuner."""
    text = REAL_SHAPE.format(value=0)
    assert read_enable_tuner(write(tmp_path, text))[0] is TunerFlag.OFF


def test_no_line_at_all_is_off(tmp_path):
    flag, detail = read_enable_tuner(write(tmp_path, "[Debug]\nEnableDebugMenu 1\n"))
    assert flag is TunerFlag.OFF and "no EnableTuner line" in detail


def test_a_commented_out_line_is_off(tmp_path):
    assert read_enable_tuner(write(tmp_path, "[Debug]\n;EnableTuner 1\n"))[0] is TunerFlag.OFF


def test_an_absent_file_is_unreadable_and_names_the_path(tmp_path):
    flag, detail = read_enable_tuner(tmp_path / "nowhere" / "AppOptions.txt")
    assert flag is TunerFlag.UNREADABLE and "nowhere" in detail


def test_the_file_is_opened_read_only_and_left_untouched(tmp_path):
    path = write(tmp_path, REAL_SHAPE.format(value=1))
    before = (path.stat().st_mtime_ns, path.read_bytes())
    read_enable_tuner(path)
    assert (path.stat().st_mtime_ns, path.read_bytes()) == before


def test_a_refusal_with_the_flag_off_is_not_enabled_and_says_what_to_change(tmp_path):
    t = open_tuner(port=1, timeout=0.5, app_options=write(tmp_path, REAL_SHAPE.format(value=0)))
    assert t.unavailable is TunerUnavailable.NOT_ENABLED
    assert "EnableTuner 1" in t.reason


def test_a_refusal_with_the_flag_on_is_not_answering_and_never_says_to_change_it(tmp_path):
    t = open_tuner(port=1, timeout=0.5, app_options=write(tmp_path, REAL_SHAPE.format(value=1)))
    assert t.unavailable is TunerUnavailable.NOT_ANSWERING
    assert "main menu" in t.reason
    assert "Set `EnableTuner 1`" not in t.reason


def test_a_refusal_with_no_readable_file_is_unestablished(tmp_path):
    t = open_tuner(port=1, timeout=0.5, app_options=tmp_path / "missing.txt")
    assert t.unavailable is TunerUnavailable.UNESTABLISHED
    assert "could not be read" in t.reason and "missing.txt" in t.reason


def test_the_six_absences_are_distinct():
    assert len(set(TunerUnavailable)) == 6
```

In `tests/test_tuner_base.py`, change the existing distinct-count assertion from five to six and update its docstring: *Told apart on purpose: only NOT_ENABLED is fixable by the player, and it is asserted only when the file was read and says so.* In `tests/test_tuner_client.py`, `test_a_closed_port_is_reported_as_not_enabled` now passes an `app_options` file saying `0` — a bare refusal no longer asserts NOT_ENABLED.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_tuner_options.py -v`
Expected: FAIL — no module `civ_advisor.tuner.options`.

- [ ] **Step 3: Write the implementation**

`civ_advisor/tuner/options.py`:

```python
"""Read whether the tuner is enabled from the file that enables it.

A refused connection is ONE observation with at least three causes: the flag is 0; the
flag is 1 but the game is at the main menu, between screens, or not running (confirmed
live: the listener cycles at the menu and is stable in a loaded match); or the file
cannot be read to say which. Until this module existed the advisor collapsed all three
into "set EnableTuner 1", and told a player with it already set to set it.

Read-only, and permitted: the rule this program lives by forbids WRITING under either
game's directories. It reads the logs and the ruleset database from inside them already.
Only the [Debug] section is consulted; a line elsewhere does not govern the tuner.
"""
from __future__ import annotations

from enum import StrEnum
from pathlib import Path

# The parent of Civ VI's own Logs/ directory. On the machine this was verified on, line
# 73 is `[Debug]`, line 74 `;Enable FireTuner.`, line 75 `EnableTuner 1`.
DEFAULT_APP_OPTIONS = (Path.home() / "Library" / "Application Support"
                       / "Sid Meier's Civilization VI" / "Firaxis Games"
                       / "Sid Meier's Civilization VI" / "AppOptions.txt")


class TunerFlag(StrEnum):
    ON = "on"
    OFF = "off"                 # the line says 0, or there is no line in [Debug]
    UNREADABLE = "unreadable"   # absent, unreadable, or undecodable: nothing is asserted


def read_enable_tuner(path: Path) -> tuple[TunerFlag, str]:
    """The flag as the file states it, and a sentence saying what was read."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return TunerFlag.UNREADABLE, f"{path} could not be read ({exc.strerror or exc})"
    section = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(";"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            continue
        if section != "Debug":
            continue
        parts = line.split(None, 1)
        if parts[0] == "EnableTuner" and len(parts) == 2:
            value = parts[1].strip()
            if value == "1":
                return TunerFlag.ON, f"{path.name} says `EnableTuner 1` under [Debug]"
            return TunerFlag.OFF, f"{path.name} says `EnableTuner {value}` under [Debug]"
    return TunerFlag.OFF, f"{path.name} has no EnableTuner line under [Debug]"


__all__ = ["DEFAULT_APP_OPTIONS", "TunerFlag", "read_enable_tuner"]
```

In `civ_advisor/tuner/base.py`, add to `TunerUnavailable`:

```python
    UNESTABLISHED = "unestablished"    # refused, and the file that would say why could not be read
```

and update the class docstring's "Five" to "Six", adding: *UNESTABLISHED is the honest answer when a connection was refused and AppOptions.txt could not be read: asserting either NOT_ENABLED or NOT_ANSWERING there would be inferring from the refusal alone, which is the defect that made this member necessary.* Add two more constants beside `TUNER_OFF`:

```python
TUNER_NOT_ANSWERING_ENABLED = NullTuner(
    TunerUnavailable.NOT_ANSWERING,
    "The tuner is enabled (AppOptions.txt says `EnableTuner 1`) but the game is not "
    "answering on its socket. It may be at the main menu, between screens, or not "
    "running; the listener only answers reliably inside a loaded match. Nothing needs "
    "changing in the file.",
)


def tuner_unestablished(detail: str) -> NullTuner:
    return NullTuner(
        TunerUnavailable.UNESTABLISHED,
        "The tuner socket refused the connection, and whether the tuner is enabled could "
        f"not be established: {detail}. Either the flag is off or the game is not "
        "answering; the advisor does not know which and will not guess.",
    )
```

In `civ_advisor/tuner/client.py`, `open_tuner` gains `app_options: Path | None = None`, and the refusal branch becomes:

```python
    except (OSError, OverflowError, TypeError, ValueError):
        # Refused is ONE observation. Which of three things it means is read from the
        # file that enables the tuner, never inferred -- with the flag on, the game
        # refuses connections at the main menu, and telling that player to set a flag
        # they have set is the false reason this branch used to give.
        if app_options is None:
            return tuner_unestablished("no AppOptions.txt path was supplied for this game")
        flag, detail = read_enable_tuner(app_options)
        if flag is TunerFlag.ON:
            return TUNER_NOT_ANSWERING_ENABLED
        if flag is TunerFlag.OFF:
            return TUNER_OFF
        return tuner_unestablished(detail)
```

In `tests/conftest.py`, `unreachable_tuner` (landed in `1e78a2f`) must now also pass `app_options=` a temporary file saying `[Debug]\nEnableTuner 0\n` — write it once under `tempfile.mkdtemp()` at import — so a refusal on port 1 is ESTABLISHED as off and the two tests it isolates keep asserting `NOT_ENABLED` for the right reason. Add a sibling `unreachable_tuner_enabled(profile)` with a file saying `1`, for the `NOT_ANSWERING` case.

In `civ_advisor/games/civ6/__init__.py`, the profile's factory becomes `tuner=lambda: open_tuner(app_options=DEFAULT_APP_OPTIONS)` (a named function `_open_civ6_tuner` rather than a lambda, with a docstring saying the path is the game's own default directory and is NOT derived from `--logs-dir`, which points at logs and says nothing about where the game is). `TUNER_OFF` keeps its text: it is now asserted only when the file says 0.

In `civ_advisor/web/briefing.js`, wherever `unavailable` is mapped to a notice (the tuner-off cases in `tunerEconomy` and `capabilityNotices`), add the `unestablished` cause with the reason text passed through, and make sure `not_answering` no longer renders any "set EnableTuner" hint of its own — the server's reason is the sentence to show.

In `README.md`, under the tuner subsection, change *Each of the five ways a tuner figure can be missing* to six, adding: *the socket refused the connection and `AppOptions.txt` could not be read to say whether the tuner is on*; and say that with `EnableTuner 1` set the game still refuses connections while at the main menu, so *enabled but not answering* is the message to expect until a match is loaded.

- [ ] **Step 4: Run to verify pass, then the whole suite**

Run: `uv run pytest tests/test_tuner_options.py tests/test_tuner_base.py tests/test_tuner_client.py tests/test_tuner_store.py tests/test_tuner_capabilities.py -v && uv run pytest -q`
Expected: PASS, 11 option tests. Tests that asserted a bare refusal is `NOT_ENABLED` must now supply a file saying `0` (asserting the established case) — or assert `UNESTABLISHED` when they mean "no file" — never be deleted. On this machine, with a game at the menu and `EnableTuner 1`, the store tests that failed with `NOT_ANSWERING` where they expected `NOT_ENABLED` are the defect itself; after this task they pass a file and stop depending on port 4318's state.

- [ ] **Step 5: Commit**

```bash
git add civ_advisor/tuner/options.py civ_advisor/tuner/base.py civ_advisor/tuner/client.py \
        civ_advisor/games/civ6/__init__.py civ_advisor/web/briefing.js README.md \
        tests/test_tuner_options.py tests/test_tuner_base.py tests/test_tuner_client.py
git commit -m "Read whether the tuner is enabled instead of inferring it from a refused connection"
```

---

### Task 3: A single refused connection is not evidence — retry, bounded, before reading the file

**Files:**
- Modify: `civ_advisor/tuner/client.py`
- Test: `tests/test_tuner_client.py` (extend)

**Interfaces:**
- Consumes: Task 2's `open_tuner(port, timeout, app_options)`.
- Produces: `CONNECT_ATTEMPTS = 3`, `CONNECT_RETRY_SECONDS = 0.25`, `open_tuner(..., attempts=CONNECT_ATTEMPTS, retry_seconds=CONNECT_RETRY_SECONDS)`.

Measured on 2026-09-13: 8 of 8 connections succeeded against a stable loaded match; during menu and load transitions the listener cycles and a connection is refused, and a reconnect 0.2 s later succeeded. So one refusal says nothing, and a bounded retry — under a second in total, because the poll runs every second — separates a cycling listener from a closed one before the file is consulted.

- [ ] **Step 1: Write the failing tests**

Extend `tests/test_tuner_client.py`:

```python
def test_a_refusal_is_retried_a_bounded_number_of_times_before_being_believed(monkeypatch):
    import civ_advisor.tuner.client as client_mod
    calls = []

    def refusing(address, timeout):
        calls.append(address)
        raise ConnectionRefusedError

    monkeypatch.setattr(client_mod.socket, "create_connection", refusing)
    monkeypatch.setattr(client_mod.time, "sleep", lambda s: None)
    client_mod.open_tuner(port=1, timeout=0.5)
    assert len(calls) == client_mod.CONNECT_ATTEMPTS


def test_a_listener_that_answers_on_the_second_try_is_a_live_tuner(monkeypatch):
    """The menu-transition case: refused once, then up."""
    game = FakeGame(replies())
    try:
        import civ_advisor.tuner.client as client_mod
        real = client_mod.socket.create_connection
        state = {"n": 0}

        def flaky(address, timeout):
            state["n"] += 1
            if state["n"] == 1:
                raise ConnectionRefusedError
            return real(address, timeout=timeout)

        monkeypatch.setattr(client_mod.socket, "create_connection", flaky)
        t = client_mod.open_tuner(port=game.port, timeout=3.0, retry_seconds=0)
        assert t.available is True
        t.close()
    finally:
        game.close()


def test_the_retry_budget_stays_under_one_poll():
    from civ_advisor.tuner.client import CONNECT_ATTEMPTS, CONNECT_RETRY_SECONDS
    assert (CONNECT_ATTEMPTS - 1) * CONNECT_RETRY_SECONDS < 1.0
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_tuner_client.py -v -k "retried or second_try or budget"`
Expected: FAIL — `CONNECT_ATTEMPTS` does not exist; the refusing fake is called once.

- [ ] **Step 3: Implement**

In `civ_advisor/tuner/client.py`:

```python
# A refused connection is ONE observation. Measured 2026-09-13: 8/8 connections succeed
# against a loaded match, and the listener cycles at the main menu and during loads, so
# a refusal is retried -- bounded to well under the one-second poll -- before anything
# is concluded from it. What IS concluded afterwards comes from AppOptions.txt (Task 2),
# not from the refusals.
CONNECT_ATTEMPTS = 3
CONNECT_RETRY_SECONDS = 0.25
```

and in `open_tuner`, replace the single `create_connection` with:

```python
    sock = None
    for attempt in range(attempts):
        try:
            sock = socket.create_connection((HOST, port), timeout=timeout)
            break
        except (OSError, OverflowError, TypeError, ValueError):
            if attempt + 1 < attempts:
                time.sleep(retry_seconds)
    if sock is None:
        # Every attempt was refused. Which of three things that means is READ from the
        # file that enables the tuner (Task 2); the refusals themselves decide nothing.
        if app_options is None:
            return tuner_unestablished("no AppOptions.txt path was supplied for this game")
        flag, detail = read_enable_tuner(app_options)
        if flag is TunerFlag.ON:
            return TUNER_NOT_ANSWERING_ENABLED
        if flag is TunerFlag.OFF:
            return TUNER_OFF
        return tuner_unestablished(detail)
```

with the signature `open_tuner(port: int = PORT, timeout: float = 3.0, app_options: Path | None = None, *, attempts: int = CONNECT_ATTEMPTS, retry_seconds: float = CONNECT_RETRY_SECONDS)`. `TUNER_NOT_ANSWERING_ENABLED`'s sentence (Task 2) already names the main menu; add *"after three attempts"* so the player knows it was not one unlucky moment.

- [ ] **Step 4: Run to verify pass, then the whole suite**

Run: `uv run pytest tests/test_tuner_client.py -v && uv run pytest -q`
Expected: PASS, 3 new tests. `test_a_closed_port_is_reported_as_not_enabled` still completes quickly: three refusals to port 1 with 0.25 s between them is half a second.

- [ ] **Step 5: Commit**

```bash
git add civ_advisor/tuner/client.py tests/test_tuner_client.py
git commit -m "Retry a refused tuner connection briefly before concluding anything from it"
```

---

### Task 4: The number rule

**Files:**
- Create: `civ_advisor/copilot/__init__.py`
- Create: `civ_advisor/copilot/grounding.py`
- Modify: `civ_advisor/llm/questions.py`
- Test: `tests/test_copilot_grounding.py`
- Test: `tests/test_questions.py` (extend)

**Interfaces:**
- Consumes: nothing from the package.
- Produces: `numerals_in(text: str, *, strip_ids: Iterable[str] = ()) -> tuple[Numeral, ...]`, `admitted(facts: Iterable[Mapping]) -> tuple[Admitted, ...]`, `check(text, cited_ids, facts) -> Grounding`, `Grounding(ok: bool, ungrounded: tuple[str, ...])`, `NUMBER_WORDS`.

Pure functions over strings and dicts, so the rule is testable table-by-table and shared by every generation path. `facts` are the payload dicts the prompt already carries (`id`, `value`, `unit`, `observed_turn`, `note`), so this sits between the model and the screen without a new data shape.

- [ ] **Step 1: Write the failing tests**

`tests/test_copilot_grounding.py`:

```python
"""Spec section 4.3: every number in generated prose must appear in a cited fact."""
import pytest

from civ_advisor.copilot.grounding import check, numerals_in

FACTS = [
    {"id": "gold.net.59", "value": 7, "unit": "per turn", "observed_turn": 59,
     "note": "Reserve is 152 gold."},
    {"id": "comparison.culture.59", "value": 0.44, "unit": "ratio", "observed_turn": 59,
     "note": "Your 4.4 against a rival median of 10.0."},
    {"id": "tuner.amenities.Rome.60", "value": 3, "unit": "amenities", "observed_turn": 60,
     "note": "Luxuries 1, civics 0, entertainment 2; unexplained 0."},
    {"id": "identity.human", "value": "CIVILIZATION_ROME / LEADER_TRAJAN", "unit": None,
     "observed_turn": None, "note": None},
    {"id": "gold.balance.59", "value": -12.5, "unit": "gold", "observed_turn": 59, "note": None},
]


def cited(*ids):
    return tuple(ids)


def test_digits_are_numerals_and_words_from_two_up_are_too():
    got = [n.text for n in numerals_in("You make 7 gold; three cities; twenty turns; one option.")]
    assert got == ["7", "three", "twenty"]


def test_the_word_one_is_not_a_numeral():
    """A pronoun in most sentences: rejecting it would reject grammar, not claims."""
    assert numerals_in("One of them is the one to build.") == ()


def test_cited_ids_are_stripped_before_scanning():
    got = numerals_in("Net gold is 7 [gold.net.59].", strip_ids=["gold.net.59"])
    assert [n.text for n in got] == ["7"]


def test_a_value_in_a_cited_fact_is_grounded():
    assert check("Your net gold is 7 per turn.", cited("gold.net.59"), FACTS).ok


def test_a_number_the_cited_facts_do_not_carry_is_rejected_and_named():
    got = check("Your net gold is 9 per turn.", cited("gold.net.59"), FACTS)
    assert not got.ok
    assert got.ungrounded == ("9",)


def test_a_number_in_an_uncited_fact_does_not_help():
    got = check("Rome has 3 amenities.", cited("gold.net.59"), FACTS)
    assert not got.ok and got.ungrounded == ("3",)


def test_the_observed_turn_of_a_cited_fact_is_grounded():
    assert check("On turn 59 you netted 7.", cited("gold.net.59"), FACTS).ok


def test_numerals_in_a_cited_note_are_grounded():
    """Notes are written by the deterministic layer from the data."""
    assert check("Your reserve is 152 gold.", cited("gold.net.59"), FACTS).ok


def test_a_ratio_may_be_written_as_a_percentage():
    assert check("You are at 44% of the median.", cited("comparison.culture.59"), FACTS).ok
    assert check("You are at 0.44 of the median.", cited("comparison.culture.59"), FACTS).ok


def test_rounding_to_the_written_precision_matches():
    assert check("Roughly 0.4 of the median.", cited("comparison.culture.59"), FACTS).ok
    assert not check("Roughly 0.45 of the median.", cited("comparison.culture.59"), FACTS).ok


def test_a_non_ratio_is_not_a_percentage():
    got = check("Amenities are at 300%.", cited("tuner.amenities.Rome.60"), FACTS)
    assert not got.ok


def test_thousands_separators_are_stripped():
    facts = FACTS + [{"id": "x", "value": 1250, "unit": "gold", "observed_turn": 59, "note": None}]
    assert check("You hold 1,250 gold.", cited("x"), facts).ok


def test_a_negative_matches_only_a_negative():
    assert check("Balance is -12.5.", cited("gold.balance.59"), FACTS).ok
    assert not check("Balance is 12.5.", cited("gold.balance.59"), FACTS).ok


def test_number_words_are_checked_like_digits():
    assert check("You have three amenities in Rome.", cited("tuner.amenities.Rome.60"), FACTS).ok
    assert not check("You have four amenities in Rome.", cited("tuner.amenities.Rome.60"), FACTS).ok


def test_an_answer_citing_nothing_may_contain_no_numbers():
    assert check("The advisor cannot see that.", (), FACTS).ok
    assert not check("It is usually about 10 turns.", (), FACTS).ok


def test_a_string_value_is_not_a_number_source():
    got = check("Trajan has 1 capital.", cited("identity.human"), FACTS)
    assert not got.ok and got.ungrounded == ("1",)


def test_a_player_reported_figure_is_admitted_when_attributed():
    facts = FACTS + [{"id": "report.turns", "kind": "player_report", "value": 8, "unit": "turns",
                      "observed_turn": 59, "note": None}]
    assert check("The 8 turns you reported on turn 59 make this the quicker option.",
                 cited("report.turns"), facts).ok


def test_a_player_reported_figure_stated_as_the_games_is_rejected():
    facts = FACTS + [{"id": "report.turns", "kind": "player_report", "value": 8, "unit": "turns",
                      "observed_turn": 59, "note": None}]
    got = check("The Granary takes 8 turns here.", cited("report.turns"), facts)
    assert not got.ok and got.unattributed == ("8",)


def test_a_figure_the_game_also_states_needs_no_attribution():
    # Grounded by a log fact as well as a report: the game did say it.
    facts = FACTS + [{"id": "report.net", "kind": "player_report", "value": 7, "unit": "per turn",
                      "observed_turn": 59, "note": None}]
    assert check("Your net gold is 7 per turn.", cited("gold.net.59", "report.net"), facts).ok


def test_a_number_the_player_just_typed_is_not_a_citation():
    """Spec 4.3 rule 7: typed into the box, it is neither dated nor stored."""
    got = check("The Granary takes 8 turns.", cited("gold.net.59"), FACTS,
                player_text="should I take the 8-turn Granary?")
    assert not got.ok and got.ungrounded == ("8",)


def test_a_typed_number_may_be_repeated_as_the_players_claim():
    facts = FACTS + [{"id": "tuner.build_option.Rome.BUILDING_GRANARY.49", "kind": "live_reading",
                      "value": 4, "unit": "turns", "observed_turn": 49, "note": None}]
    text = ("You mention 8 turns; the tuner read 4 for the Granary in Rome on turn 49. "
            "Both are reported here and neither has been corrected to the other.")
    assert check(text, cited("tuner.build_option.Rome.BUILDING_GRANARY.49"), facts,
                 player_text="should I take the 8-turn Granary?").ok


def test_a_typed_number_repeated_without_the_claim_phrase_is_rejected():
    got = check("So 8 turns it is, then, and that settles the question here.", (), FACTS,
                player_text="8 turns for the Granary")
    assert not got.ok and got.ungrounded == ("8",)


def test_a_typed_number_repeated_while_the_cited_figure_goes_unstated_is_rejected():
    """The disagreement must be NAMED: the player's 8 beside the game's 4, never 8 alone."""
    facts = FACTS + [{"id": "tuner.build_option.Rome.BUILDING_GRANARY.49", "kind": "live_reading",
                      "value": 4, "unit": "turns", "observed_turn": 49, "note": None}]
    got = check("You mention 8 turns, which is quick enough to be worth taking now.",
                cited("tuner.build_option.Rome.BUILDING_GRANARY.49"), facts,
                player_text="should I take the 8-turn Granary?")
    assert not got.ok and got.unreconciled == ("8",)


def test_every_ungrounded_numeral_is_reported_once_in_order():
    got = check("First 9, then 9 again, then 11.", cited("gold.net.59"), FACTS)
    assert got.ungrounded == ("9", "11")
```

Extend `tests/test_questions.py` with two tests using its existing `request()` helper and `FAIR_FACT` (value 0.44, turn 81):

```python
def test_a_generated_answer_with_an_ungrounded_number_is_rejected():
    data = {"text": "You trail the field at 0.44 and should expect about 12 turns to close it.",
            "evidence_ids": ["comparison.culture.81"], "action_ids": [], "guide_ids": [],
            "unknowns": []}
    with pytest.raises(ValueError, match="12"):
        questions.validate(request(), data)


def test_a_generated_answer_whose_numbers_are_all_cited_passes():
    data = {"text": "You trail the field at 0.44 of the median on turn 81, which is why this "
                    "is the call to weigh now.",
            "evidence_ids": ["comparison.culture.81"], "action_ids": [], "guide_ids": [],
            "unknowns": []}
    assert questions.validate(request(), data).text.startswith("You trail")
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_copilot_grounding.py tests/test_questions.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'civ_advisor.copilot'`.

- [ ] **Step 3: Write the implementation**

`civ_advisor/copilot/__init__.py`:

```python
"""A conversation grounded in the same evidence as the briefing.

The model chooses NAMED questions from a fixed catalog and writes prose around the
facts they return. It never writes SQL or Lua, and every number in its prose must
appear in a fact it cited (grounding.py) or the prose is not shown.
"""
```

`civ_advisor/copilot/grounding.py`:

```python
"""The number rule, spec section 4.3, as one pure function.

Every number in generated prose must be a number that appears in a fact the answer
cited: the fact's value, its observed turn, or a numeral in its note (notes are written
by the deterministic layer from the data). Nothing else is admitted -- not the player's
message, not an earlier exchange, not arithmetic the model did itself. A figure a
player might want derived is a resolver's job, as a DERIVED fact citing its inputs.

Deliberately NOT here: any check that a number is attached to the right noun. "Rome has
3 amenities" passes if a cited fact has value 3 even when that fact is Puteoli's. The
evidence drawer under the answer shows each cited fact with its subject; that is where a
player catches it, and why generated prose stays labelled interpretation.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Iterable, Mapping

# `one` is absent on purpose: it is a pronoun in most English sentences ("one of",
# "one settlement"), and treating it as a numeral rejects grammar rather than claims.
NUMBER_WORDS: dict[str, int] = {
    "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
    "eighty": 80, "ninety": 90, "hundred": 100, "thousand": 1000,
}

_DIGITS = re.compile(r"-?\d[\d,]*(?:\.\d+)?%?")
_WORDS = re.compile(r"\b(" + "|".join(sorted(NUMBER_WORDS, key=len, reverse=True)) + r")\b",
                    re.IGNORECASE)


@dataclass(frozen=True)
class Numeral:
    """One number as written, with what it would have to match."""

    text: str
    value: Decimal
    places: int          # decimal places written; a number word has none
    percent: bool


# How prose must own up to a figure the PLAYER supplied. A player report is citable --
# it is dated, labelled and stored -- but the game did not say it, and the sentence
# must not read as though it did. Lower-cased comparison; the phrases are fixed.
ATTRIBUTION = ("you reported", "your report", "you told the advisor", "you entered", "you recorded")

# How prose may repeat a number the player JUST TYPED. Kept apart from ATTRIBUTION on
# purpose: a report is a dated observation the advisor holds; this is an unverified
# assertion made a moment ago in conversation, and the words must say which it is.
CLAIM = ("you mention", "you mentioned", "you say", "you wrote", "your message")


@dataclass(frozen=True)
class Grounding:
    ok: bool
    ungrounded: tuple[str, ...] = ()     # numerals no cited fact carries, once, in order
    unattributed: tuple[str, ...] = ()   # numerals grounded ONLY by a player report, unattributed
    unreconciled: tuple[str, ...] = ()   # the player's typed numerals repeated while every cited figure goes unstated

    def describe(self) -> str:
        if self.ok:
            return ""
        parts = []
        if self.ungrounded:
            parts.append(f"the answer contains {', '.join(self.ungrounded)}, which no cited "
                         "fact carries")
        if self.unattributed:
            parts.append(f"the answer states {', '.join(self.unattributed)} as though the game "
                         "said it, when only your own report does; it must say you reported it")
        if self.unreconciled:
            parts.append(f"the answer repeats your {', '.join(self.unreconciled)} without "
                         "stating the figure the evidence holds; a disagreement is named, "
                         "never resolved by dropping one side")
        return "; ".join(parts) + " -- a number the evidence does not state is not shown"


def numerals_in(text: str, *, strip_ids: Iterable[str] = ()) -> tuple[Numeral, ...]:
    """Every numeral in `text`, after the citations the answer is allowed to make are
    removed -- an id like `comparison.culture.81` carries a turn number that is not a
    claim about anything."""
    for fact_id in strip_ids:
        text = text.replace(f"[{fact_id}]", " ").replace(fact_id, " ")
    found: list[tuple[int, Numeral]] = []
    for m in _DIGITS.finditer(text):
        raw = m.group(0)
        percent = raw.endswith("%")
        body = raw.rstrip("%").replace(",", "")
        try:
            value = Decimal(body)
        except InvalidOperation:
            continue
        places = len(body.split(".")[1]) if "." in body else 0
        found.append((m.start(), Numeral(raw, value, places, percent)))
    for m in _WORDS.finditer(text):
        word = m.group(1).lower()
        found.append((m.start(), Numeral(m.group(1), Decimal(NUMBER_WORDS[word]), 0, False)))
    return tuple(n for _, n in sorted(found, key=lambda pair: pair[0]))


@dataclass(frozen=True)
class Admitted:
    value: Decimal
    ratio: bool      # may also be written as a percentage
    player: bool = False   # carried by a player_report fact


def _decimal(value) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    return None      # a string value is a name, not a number source


def admitted(facts: Iterable[Mapping]) -> tuple[Admitted, ...]:
    """Every number the cited facts carry: value, observed turn, numerals in the note."""
    out: list[Admitted] = []
    for fact in facts:
        ratio = fact.get("unit") == "ratio"
        player = fact.get("kind") == "player_report"
        value = _decimal(fact.get("value"))
        if value is not None:
            out.append(Admitted(value, ratio, player))
        turn = _decimal(fact.get("observed_turn"))
        if turn is not None:
            out.append(Admitted(turn, False, player))
        for n in numerals_in(str(fact.get("note") or "")):
            out.append(Admitted(n.value, False, player))
    return tuple(out)


def _matches(numeral: Numeral, candidate: Admitted) -> bool:
    quant = Decimal(1).scaleb(-numeral.places)
    if numeral.percent:
        if not candidate.ratio:
            return False
        return numeral.value == (candidate.value * 100).quantize(quant)
    if numeral.value == candidate.value.quantize(quant):
        return True
    # A ratio written as its plain value, e.g. "0.44 of the median".
    return False


def check(text: str, cited_ids: Iterable[str], facts: Iterable[Mapping],
          player_text: str = "") -> Grounding:
    """Spec section 4.3. `facts` is the full payload list; only those whose id is in
    `cited_ids` may ground a number. `player_text` is what the player typed: its numbers
    are never citations (rule 7), may be repeated only as the player's claim, and when
    the answer cites a numeric fact at all, at least one cited value must appear in the
    prose beside the claim -- the disagreement is named, never resolved by omission."""
    cited = set(cited_ids)
    pool = admitted(f for f in facts if f.get("id") in cited)
    typed = {n.value for n in numerals_in(player_text)}
    lowered = text.lower()
    attributed = any(phrase in lowered for phrase in ATTRIBUTION)
    claimed = any(phrase in lowered for phrase in CLAIM)
    ungrounded: list[str] = []
    unattributed: list[str] = []
    unreconciled: list[str] = []
    numerals = numerals_in(text, strip_ids=cited)
    states_a_cited_value = any(
        _matches(n, c) for n in numerals for c in pool if not c.player)
    pool_has_values = any(not c.player for c in pool)
    for numeral in numerals:
        matches = [c for c in pool if _matches(numeral, c)]
        if matches:
            if all(c.player for c in matches) and not attributed:
                # Only the player's own report carries this number. Spec 4.3 rule 6: the
                # prose must say so, or it is stating the player's figure as the game's.
                if numeral.text not in unattributed:
                    unattributed.append(numeral.text)
            continue
        if numeral.value in typed and claimed:
            # The player's own typed figure, repeated as their claim. Allowed -- but
            # not while a cited figure it might disagree with goes unstated.
            if pool_has_values and not states_a_cited_value and numeral.text not in unreconciled:
                unreconciled.append(numeral.text)
            continue
        if numeral.text not in ungrounded:
            ungrounded.append(numeral.text)
    return Grounding(ok=not ungrounded and not unattributed and not unreconciled,
                     ungrounded=tuple(ungrounded), unattributed=tuple(unattributed),
                     unreconciled=tuple(unreconciled))


__all__ = ["ATTRIBUTION", "CLAIM", "Admitted", "Grounding", "NUMBER_WORDS", "Numeral",
           "admitted", "check", "numerals_in"]
```

In `civ_advisor/llm/questions.py`, add `from civ_advisor.copilot import grounding` and, in `validate`, after the URL check and before constructing `Answer`:

```python
    grounded = grounding.check(text, evidence, request.payload["evidence"],
                               player_text=request.player_text)
    if not grounded.ok:
        # Spec 2026-09-13-civ6-copilot-design section 4.3. This is the check on
        # CONTENT the structural checks above are not: a number the cited evidence
        # does not carry is a claim the advisor cannot stand behind.
        raise ValueError(grounded.describe())
```

Update the module docstring's list of three guarantees to four, adding: "**Every number is a cited number.** A numeral in the prose that no cited fact carries — as value, turn or note — rejects the answer (`copilot/grounding.py`)."

- [ ] **Step 4: Run to verify pass, then the whole suite**

Run: `uv run pytest tests/test_copilot_grounding.py tests/test_questions.py -v && uv run pytest -q`
Expected: PASS, 25 grounding tests; the two new question tests pass; existing `test_questions.py` cases still pass (their fixtures' numbers — 0.44, 81 — are all in `FAIR_FACT`). Any existing test whose generated text carried an uncited number must be updated to cite a fact that carries it, never by weakening the check.

- [ ] **Step 5: Commit**

```bash
git add civ_advisor/copilot/__init__.py civ_advisor/copilot/grounding.py \
        civ_advisor/llm/questions.py tests/test_copilot_grounding.py tests/test_questions.py
git commit -m "Reject generated prose whose numbers no cited fact carries"
```

---

### Task 5: The question catalog, and absence with its cause

**Files:**
- Create: `civ_advisor/copilot/catalog.py`
- Modify: `civ_advisor/decisions/evidence.py` (one builder: `analysis_turn_fact`)
- Test: `tests/test_copilot_catalog.py`

**Interfaces:**
- Consumes: `DecisionContext`, the `evidence.py` builders, `GameProfile.reason`, `TunerSnapshot`, `RulesetProvider`.
- Produces: `Unanswerable` (StrEnum), `Absence`, `ParamKind`, `Param`, `Question`, `Resolution`, `CATALOG: dict[str, Question]`, `choices(context) -> dict[ParamKind, tuple[str, ...]]`, `ask(context, question_id, params) -> Resolution`, `TYPE_KEY`.

This task holds the log-backed questions and the machinery. Ruleset questions arrive in Task 6 and tuner questions in Task 7, each by adding entries to `CATALOG` and nothing else.

- [ ] **Step 1: Write the failing tests**

`tests/test_copilot_catalog.py`:

```python
"""The catalog is the allowlist: a question not written here cannot be asked, a
parameter outside its set never reaches a resolver, and every absence names its cause."""
import re

import pytest

from civ_advisor.copilot.catalog import (
    CATALOG, TYPE_KEY, Absence, ParamKind, Unanswerable, ask, choices,
)
from civ_advisor.decisions.context import build_context
from civ_advisor.decisions.models import SourceKind
from civ_advisor.games.civ7 import CIV7


@pytest.fixture
def civ7_context(civ7_store):
    return build_context(civ7_store.rebuild())


@pytest.fixture
def civ6_context(civ6_store):
    return build_context(civ6_store.rebuild())


def test_every_question_declares_its_parameters_and_a_verified_date():
    for q in CATALOG.values():
        assert q.verified_on, q.id
        assert q.description, q.id
        for p in q.params:
            assert isinstance(p.kind, ParamKind), (q.id, p.name)


def test_question_ids_are_dotted_lowercase():
    for qid in CATALOG:
        assert re.fullmatch(r"[a-z_]+(\.[a-z_]+)+", qid), qid


def test_an_unknown_question_is_an_absence_not_an_error(civ7_context):
    got = ask(civ7_context, "empire.everything", {})
    assert got.facts == ()
    assert got.absence is not None
    assert got.absence.kind is Unanswerable.NOT_IN_CATALOG


def test_a_parameter_outside_its_set_never_reaches_the_resolver(civ7_context):
    got = ask(civ7_context, "empire.comparison", {"stat": "faith'; DROP TABLE x"})
    assert got.absence is not None
    assert got.absence.kind is Unanswerable.BAD_PARAMETER
    assert "faith" in got.absence.detail


def test_choices_come_from_this_snapshot(civ7_context):
    got = choices(civ7_context)
    assert got[ParamKind.STAT] == ("culture", "science", "gold", "production", "food")
    assert all(isinstance(c, str) and c for c in got[ParamKind.CITY])


def test_type_key_regex_admits_game_keys_and_nothing_else():
    assert TYPE_KEY.fullmatch("BUILDING_LIBRARY")
    assert TYPE_KEY.fullmatch("TECH_WRITING")
    assert not TYPE_KEY.fullmatch("building_library")
    assert not TYPE_KEY.fullmatch("BUILDING LIBRARY")
    assert not TYPE_KEY.fullmatch("X")


def test_the_analysis_turn_is_a_log_fact(civ7_context):
    got = ask(civ7_context, "turn.analysis", {})
    (fact,) = got.facts
    assert fact.source_kind is SourceKind.LOG
    assert fact.value == civ7_context.analysis_turn
    assert fact.source_file == "Player_Stats.csv"


def test_a_comparison_resolves_to_derived_facts_citing_their_inputs(civ7_context):
    got = ask(civ7_context, "empire.comparison", {"stat": "culture"})
    assert got.absence is None
    kinds = {f.source_kind for f in got.facts}
    assert SourceKind.DERIVED in kinds and SourceKind.RULE in kinds and SourceKind.LOG in kinds


def test_a_capability_this_game_does_not_log_is_absent_with_the_profiles_own_reason(civ6_context):
    """Civ VI writes no happiness log; the reason is the profile's, not a generic one."""
    got = ask(civ6_context, "empire.happiness", {})
    assert got.facts == ()
    assert got.absence.kind is Unanswerable.TUNER_ABSENT   # Civ VI backs it by tuner
    assert got.absence.cause in {"not_enabled", "not_answering", "unreachable",
                                 "no_socket", "not_asked"}


def test_an_oracle_question_in_fair_mode_is_hidden_not_missing(civ7_store):
    context = build_context(civ7_store.rebuild(), oracle=False)
    got = ask(context, "defense.objectives", {})
    assert got.facts == ()
    assert got.absence.kind is Unanswerable.ORACLE_HIDDEN


def test_the_brief_resolves_to_the_facts_the_cards_cite(civ7_context):
    got = ask(civ7_context, "decisions.brief", {})
    assert got.absence is None
    assert all(f.id in civ7_context.ledger.facts for f in got.facts)


def test_player_reports_are_their_own_kind(civ7_context):
    got = ask(civ7_context, "player.reports", {})
    assert all(f.source_kind is SourceKind.PLAYER_REPORT for f in got.facts)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_copilot_catalog.py -v`
Expected: FAIL — no module `civ_advisor.copilot.catalog`.

- [ ] **Step 3: Add the one new builder**

In `civ_advisor/decisions/evidence.py`, after `human_identity_fact`:

```python
def analysis_turn_fact(ledger: EvidenceLedger, state: GameState) -> EvidenceFact:
    """The turn the logs are complete through, as a citable fact.

    Exists so a generated answer may say "turn 59" and be grounded: spec section 4.3
    admits a number only from a cited fact, and the frame of the whole answer is a
    number. LOG, not DERIVED: it is the newest turn Player_Stats.csv has a complete
    row for, read off that file.
    """
    turn = state.complete_through_turn
    return ledger.add(EvidenceFact(
        id=f"turn.analysis.{turn}", label="The turn the logs are complete through",
        source_kind=SourceKind.LOG, provenance=Provenance.FAIR, observed_turn=turn,
        value=turn, unit="turn", source_file=STATS_FILE, record_key=(STATS_FILE, turn),
        note=("The logs are complete through this turn. A live tuner reading may be one "
              "turn ahead of it; that is normal and is reported beside each reading."),
    ))
```

Add it to `build_ledger` after `human_identity_fact(ledger, state)`, and to `__all__` if one exists.

- [ ] **Step 4: Write the catalog**

`civ_advisor/copilot/catalog.py`:

```python
"""The fixed set of questions the copilot may ask, and how each is answered.

An allowlist in exactly the sense of tuner/queries.py and ruleset/civ6.py's
READABLE_COLUMNS: a question not written here cannot be asked. The model names an
entry and supplies parameter values; every parameter has a kind, and the kind decides
what may reach the resolver -- a member of a fixed set, a name this snapshot actually
contains, or a bound SQL value matching TYPE_KEY. No player text is ever a parameter.

Every resolver produces EvidenceFacts through the builders decisions/evidence.py already
has, so a fact the conversation cites is the same fact -- same id, kind, turn, note -- a
decision card would show. An unanswerable question resolves to an Absence carrying a
kind the page branches on and the REAL cause: the profile's own reason for a log this
game does not write, the tuner's own enum, the ruleset provider's own sentence.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Callable

from civ_advisor.advisors.base import Provenance
from civ_advisor.decisions import evidence
from civ_advisor.decisions.context import DecisionContext
from civ_advisor.decisions.models import EvidenceFact
from civ_advisor.games.base import Capability
from civ_advisor.games.registry import get_profile

TYPE_KEY = re.compile(r"[A-Z][A-Z0-9_]{2,63}")


class Unanswerable(StrEnum):
    NOT_LOGGED = "not_logged"                  # this game writes no log that could answer it
    TUNER_ABSENT = "tuner_absent"              # a live reading was needed; `cause` says why none
    RULESET_UNAVAILABLE = "ruleset_unavailable"
    NO_SUCH_ROW = "no_such_row"                # the ruleset has no row for that key
    ORACLE_HIDDEN = "oracle_hidden"            # it exists, and Oracle is off
    BAD_PARAMETER = "bad_parameter"            # a value outside the parameter's set
    NOT_IN_CATALOG = "not_in_catalog"


@dataclass(frozen=True)
class Absence:
    question: str
    kind: Unanswerable
    detail: str
    cause: str | None = None     # a TunerUnavailable value, for TUNER_ABSENT

    def describe(self) -> str:
        return f"{self.question}: {self.detail}"


class ParamKind(StrEnum):
    STAT = "stat"                      # one of YIELD_STATS
    CITY = "city"                      # a settlement name in this snapshot or reading
    TYPE_KEY = "type_key"              # a game type key, bound as a SQL value
    PARAMETER_NAME = "parameter_name"  # one of RULE_PARAMETERS (Task 6)


@dataclass(frozen=True)
class Param:
    name: str
    kind: ParamKind
    description: str


@dataclass(frozen=True)
class Resolution:
    facts: tuple[EvidenceFact, ...] = ()
    absence: Absence | None = None


Resolver = Callable[[DecisionContext, dict[str, str]], Resolution]


@dataclass(frozen=True)
class Question:
    id: str
    description: str          # what the model reads to choose it
    resolve: Resolver
    params: tuple[Param, ...] = ()
    verified_on: str = ""
    oracle: bool = False      # answered only with Oracle on


def _city_names(context: DecisionContext) -> tuple[str, ...]:
    names: list[str] = []
    for s in context.settlements:
        for n in (s.name, s.city):
            if n and n not in names:
                names.append(n)
    tuner = context.tuner
    if tuner.available:
        for a in tuner.amenities:
            if a.city not in names:
                names.append(a.city)
        for so in tuner.build_options:
            if so.city not in names:
                names.append(so.city)
    return tuple(names)


def choices(context: DecisionContext) -> dict[ParamKind, tuple[str, ...]]:
    """The valid values for each enumerable parameter kind, from THIS snapshot."""
    from civ_advisor.ruleset.civ6 import RULE_PARAMETERS  # Task 6; empty set until then
    return {
        ParamKind.STAT: evidence.YIELD_STATS,
        ParamKind.CITY: _city_names(context),
        ParamKind.PARAMETER_NAME: tuple(sorted(RULE_PARAMETERS)),
    }


def _validate(context: DecisionContext, question: Question,
              params: dict[str, str]) -> Absence | None:
    valid = choices(context)
    for p in question.params:
        value = params.get(p.name)
        if not isinstance(value, str) or not value:
            return Absence(question.id, Unanswerable.BAD_PARAMETER,
                           f"{p.name} was not supplied")
        if p.kind is ParamKind.TYPE_KEY:
            if not TYPE_KEY.fullmatch(value):
                return Absence(question.id, Unanswerable.BAD_PARAMETER,
                               f"{value!r} is not a game type key")
        elif value not in valid[p.kind]:
            return Absence(question.id, Unanswerable.BAD_PARAMETER,
                           f"{value!r} is not one of the {p.kind.value} values this turn")
    return None


def ask(context: DecisionContext, question_id: str, params: dict[str, str]) -> Resolution:
    """Resolve one question, or say precisely why it cannot be. Never raises for a
    bad id or a bad parameter: those are the model's mistakes, reported as absences."""
    question = CATALOG.get(question_id)
    if question is None:
        return Resolution(absence=Absence(question_id, Unanswerable.NOT_IN_CATALOG,
                                          "no catalog question covers this"))
    bad = _validate(context, question, params)
    if bad is not None:
        return Resolution(absence=bad)
    if question.oracle and context.evidence_mode != "oracle":
        return Resolution(absence=Absence(
            question.id, Unanswerable.ORACLE_HIDDEN,
            "this reads the AI's own logs, and Oracle is off"))
    return question.resolve(context, params)


# ---- log-backed resolvers ------------------------------------------------------------

def _not_logged(context: DecisionContext, question_id: str,
                capability: Capability) -> Resolution:
    """The absence for a capability this game's profile does not declare -- with the
    profile's own words, and with the tuner's own cause when the tuner could back it."""
    profile = get_profile(context_game(context))
    if capability in profile.tuner_backed:
        tuner = context.tuner
        return Resolution(absence=Absence(
            question_id, Unanswerable.TUNER_ABSENT,
            tuner.reason or "the tuner supplied no reading this poll",
            cause=None if tuner.unavailable is None else tuner.unavailable.value))
    return Resolution(absence=Absence(
        question_id, Unanswerable.NOT_LOGGED,
        profile.reason(capability) or f"{profile.display_name} does not record this"))


def context_game(context: DecisionContext) -> str:
    """The game id this context was built for. `DecisionContext` does not carry it
    directly; the catalog it loaded does, and every game has its own."""
    return context.catalog.game


def _turn(context: DecisionContext, params: dict[str, str]) -> Resolution:
    return Resolution(facts=(evidence.analysis_turn_fact(context.ledger, context.state),))


def _yields(context: DecisionContext, params: dict[str, str]) -> Resolution:
    facts = tuple(f for f in (evidence.yield_fact(context.ledger, context.state,
                                                  context.state.HUMAN, stat)
                              for stat in evidence.YIELD_STATS) if f is not None)
    if not facts:
        return Resolution(absence=Absence("empire.yields", Unanswerable.NOT_LOGGED,
                                          "Player_Stats.csv has no row for you this turn"))
    return Resolution(facts=facts)


def _comparison(context: DecisionContext, params: dict[str, str]) -> Resolution:
    fact = evidence.yield_comparison_fact(context.ledger, context.state, params["stat"])
    if fact is None:
        return Resolution(absence=Absence("empire.comparison", Unanswerable.NOT_LOGGED,
                                          f"no rival row to compare {params['stat']} against"))
    return Resolution(facts=(fact,) + context.ledger.resolve(fact.contributing))


def _net_gold(context: DecisionContext, params: dict[str, str]) -> Resolution:
    fact = evidence.net_gold_fact(context.ledger, context.state)
    if fact is None:
        return _not_logged(context, "empire.net_gold", Capability.MAINTENANCE)
    return Resolution(facts=(fact,) + context.ledger.resolve(fact.contributing))


def _happiness(context: DecisionContext, params: dict[str, str]) -> Resolution:
    fact = evidence.happiness_fact(context.ledger, context.state)
    if fact is None:
        return _not_logged(context, "empire.happiness", Capability.HAPPINESS)
    return Resolution(facts=(fact,))


def _queues(context: DecisionContext, params: dict[str, str]) -> Resolution:
    facts = evidence.queue_facts(context.ledger, context.state)
    if not facts:
        return Resolution(absence=Absence("settlements.queues", Unanswerable.NOT_LOGGED,
                                          "no settlement of yours has a logged build queue"))
    return Resolution(facts=facts)


def _coverage(context: DecisionContext, params: dict[str, str]) -> Resolution:
    fact = evidence.settlement_coverage_fact(context.ledger, context.state)
    return Resolution(facts=(fact,) + context.ledger.resolve(fact.contributing))


def _rival_yields(context: DecisionContext, params: dict[str, str]) -> Resolution:
    facts = []
    for rival in context.state.rivals():
        for stat in evidence.YIELD_STATS:
            f = evidence.yield_fact(context.ledger, context.state, rival.id, stat)
            if f is not None:
                facts.append(f)
    if not facts:
        return Resolution(absence=Absence("rivals.yields", Unanswerable.NOT_LOGGED,
                                          "no rival has a stats row this turn"))
    return Resolution(facts=tuple(facts))


def _defense(context: DecisionContext, params: dict[str, str]) -> Resolution:
    facts = context.defense_facts or evidence.defense_facts(context.ledger, context.state)
    return Resolution(facts=tuple(f for f in facts if f.provenance is Provenance.ORACLE))


def _brief(context: DecisionContext, params: dict[str, str]) -> Resolution:
    from civ_advisor.decisions import decide_all
    ids: list[str] = []
    for card in decide_all(context):
        ids.extend(card.evidence_ids)
        for candidate in card.candidates:
            ids.extend(candidate.evidence_ids)
    unique = tuple(dict.fromkeys(ids))
    if not unique:
        return Resolution(absence=Absence("decisions.brief", Unanswerable.NOT_LOGGED,
                                          "the brief holds no decision this turn"))
    return Resolution(facts=context.ledger.resolve(unique))


def _reports(context: DecisionContext, params: dict[str, str]) -> Resolution:
    return Resolution(facts=tuple(r.fact() for r in context.player.reports))


CATALOG: dict[str, Question] = {
    q.id: q for q in (
        Question("turn.analysis", "The turn the logs are complete through.", _turn,
                 verified_on="2026-09-13"),
        Question("empire.yields", "Your culture, science, gold, production and food per turn.",
                 _yields, verified_on="2026-09-13"),
        Question("empire.comparison", "One of your yields against the rival median, with the "
                 "advisor's threshold.", _comparison,
                 params=(Param("stat", ParamKind.STAT, "which yield"),), verified_on="2026-09-13"),
        Question("empire.net_gold", "Gold per turn after upkeep, from the logs.", _net_gold,
                 verified_on="2026-09-13"),
        Question("empire.happiness", "Empire happiness against the celebration threshold.",
                 _happiness, verified_on="2026-09-13"),
        Question("settlements.queues", "What each of your settlements is building, from the log.",
                 _queues, verified_on="2026-09-13"),
        Question("settlements.coverage", "How many settlements the queue log covers.",
                 _coverage, verified_on="2026-09-13"),
        Question("rivals.yields", "Every rival's yields per turn.", _rival_yields,
                 verified_on="2026-09-13"),
        Question("defense.objectives", "Recorded AI attack objectives against your tiles "
                 "(Oracle).", _defense, verified_on="2026-09-13", oracle=True),
        Question("decisions.brief", "The evidence behind every decision in this turn's brief.",
                 _brief, verified_on="2026-09-13"),
        Question("player.reports", "Figures you have told the advisor this sitting.", _reports,
                 verified_on="2026-09-13"),
    )
}

__all__ = ["Absence", "CATALOG", "Param", "ParamKind", "Question", "Resolution", "TYPE_KEY",
           "Unanswerable", "ask", "choices", "context_game"]
```

`Catalog.game`: `load_catalog(..., game=...)` in `civ_advisor/knowledge/catalog.py` receives the game id. If `Catalog` does not already keep it as an attribute, add `game: str = "civ7"` to the `Catalog` dataclass and set it in `load_catalog`; the default keeps every existing construction working.

Until Task 6 lands, add to `civ_advisor/ruleset/civ6.py`: `RULE_PARAMETERS: frozenset[str] = frozenset()` with the comment `# Filled by the copilot plan's Task 6; empty means no GlobalParameters row may be read.`

- [ ] **Step 5: Run to verify pass, then the whole suite**

Run: `uv run pytest tests/test_copilot_catalog.py -v && uv run pytest -q`
Expected: PASS, 12 tests. `build_ledger` now adds one more fact, so any existing test asserting an exact ledger size must be updated by one — the fact is `turn.analysis.<n>` and the assertion should name it.

- [ ] **Step 6: Commit**

```bash
git add civ_advisor/copilot/catalog.py civ_advisor/decisions/evidence.py \
        civ_advisor/ruleset/civ6.py civ_advisor/knowledge/catalog.py tests/test_copilot_catalog.py
git commit -m "Fix the set of questions the copilot may ask, and name why one cannot be answered"
```

---

### Task 6: Grow the ruleset allowlist, table by table, and ask it

**Files:**
- Modify: `civ_advisor/ruleset/base.py`
- Modify: `civ_advisor/ruleset/civ6.py`
- Modify: `civ_advisor/copilot/catalog.py`
- Modify: `tests/ruleset_fixture.py`
- Test: `tests/test_ruleset_growth.py`

**Interfaces:**
- Consumes: `Civ6Ruleset._select`, `_figure_maker`, `_read_verified`.
- Produces: `READABLE_COLUMNS` extended per spec §4.2; `RULE_PARAMETERS: frozenset[str]`; `ImprovementFacts`, `PolicyFacts`, `GovernmentFacts`, `ResourceFacts`; `RulesetProvider.parameter/improvement/policy/government/resource`; extra fields on `BuildingFacts`, `DistrictFacts`, `UnitFacts`; catalog questions `ruleset.*`; `Resolution.notes`.

Every table and column below was read from the installed `DebugGameplay.sqlite` on 2026-09-13 with `sqlite3 -readonly`. The stand-in fixture copies those names and a handful of real rows, and a second test opens the real file when it is present, so a patch that renames a column fails here first.

- [ ] **Step 1: Write the failing tests**

`tests/test_ruleset_growth.py`:

```python
"""The allowlist grew by the tables spec section 4.2 names -- and only those."""
import sqlite3
from pathlib import Path

import pytest

from civ_advisor.copilot.catalog import Unanswerable, ask
from civ_advisor.decisions.context import build_context
from civ_advisor.decisions.models import SourceKind
from civ_advisor.ruleset.base import RulesetMention
from civ_advisor.ruleset.civ6 import (
    DEFAULT_DATABASE, READABLE_COLUMNS, RULE_PARAMETERS, Civ6Ruleset, open_ruleset,
)
from tests.ruleset_fixture import build_fixture


@pytest.fixture
def ruleset(tmp_path: Path):
    path = build_fixture(tmp_path / "DebugGameplay.sqlite")
    provider = Civ6Ruleset.open(path)
    yield provider
    provider.close()


def test_the_new_tables_are_in_the_allowlist_with_exactly_these_columns():
    assert READABLE_COLUMNS["GlobalParameters"] == frozenset({"Name", "Value"})
    assert READABLE_COLUMNS["Government_SlotCounts"] == frozenset(
        {"GovernmentType", "GovernmentSlotType", "NumSlots"})
    assert {"Housing", "Entertainment", "CitizenSlots", "IsWonder", "RequiresPlacement"} \
        <= READABLE_COLUMNS["Buildings"]
    assert {"BaseMoves", "Range", "Domain", "PromotionClass"} <= READABLE_COLUMNS["Units"]


def test_effect_tables_are_still_refused():
    for table in ("Modifiers", "ModifierArguments", "PolicyModifiers", "GovernmentModifiers"):
        assert table not in READABLE_COLUMNS


def test_a_parameter_is_read_only_from_the_fixed_name_set(ruleset):
    assert "CITY_AMENITIES_FOR_FREE" in RULE_PARAMETERS
    fig = ruleset.parameter("CITY_AMENITIES_FOR_FREE")
    assert fig is not None and fig.value == 0
    assert fig.table == "GlobalParameters" and fig.column == "Value"
    assert ruleset.parameter("SOMETHING_ELSE") is None


def test_a_government_states_its_slot_counts_as_figures(ruleset):
    facts = ruleset.government("GOVERNMENT_CLASSICAL_REPUBLIC")
    slots = {f.row_key[1]: f.value for f in facts.slots}
    assert slots == {"SLOT_DIPLOMATIC": 1, "SLOT_ECONOMIC": 2, "SLOT_WILDCARD": 1}


def test_a_policy_states_its_slot_and_civic_and_mentions_its_unquantified_effect(ruleset):
    facts = ruleset.policy("POLICY_URBAN_PLANNING")
    assert facts.slot.value == "SLOT_ECONOMIC"
    assert facts.prereq_civic.value == "CIVIC_CODE_OF_LAWS"
    assert any(isinstance(m, RulesetMention) for m in facts.mentions)


def test_a_luxury_resource_states_its_amenity_figure(ruleset):
    facts = ruleset.resource("RESOURCE_SILK")
    assert facts.resource_class.value == "RESOURCECLASS_LUXURY"
    assert facts.happiness.value == 4


def test_a_strategic_resource_states_zero_not_absence(ruleset):
    assert ruleset.resource("RESOURCE_IRON").happiness.value == 0


def test_an_improvement_states_housing_and_yields(ruleset):
    facts = ruleset.improvement("IMPROVEMENT_FARM")
    assert facts.housing.value == 1
    assert {(f.row_key[1], f.value) for f in facts.yields} == {("YIELD_FOOD", 1), ("YIELD_PRODUCTION", 0)}


def test_a_building_now_states_housing_and_placement(ruleset):
    facts = ruleset.building("BUILDING_GRANARY")
    assert facts.housing.value == 2
    assert facts.requires_placement.value == 0


def test_a_unit_now_states_moves_and_range(ruleset):
    facts = ruleset.unit("UNIT_ARCHER")
    assert facts.moves.value == 2 and facts.range.value == 2


def test_ruleset_questions_resolve_to_installed_ruleset_facts(civ6_store, tmp_path):
    from civ_advisor.ruleset.civ6 import clear_cache
    path = build_fixture(tmp_path / "DebugGameplay.sqlite")
    context = build_context(civ6_store.rebuild(), ruleset=open_ruleset(path))
    try:
        got = ask(context, "ruleset.building", {"item": "BUILDING_GRANARY"})
        assert got.absence is None
        assert all(f.source_kind is SourceKind.INSTALLED_RULESET for f in got.facts)
        assert any(f.value == 2 and "Housing" in f.record_key for f in got.facts)
        got = ask(context, "ruleset.building", {"item": "BUILDING_NOT_A_THING"})
        assert got.absence.kind is Unanswerable.NO_SUCH_ROW
        got = ask(context, "ruleset.parameter", {"name": "CITY_AMENITIES_FOR_FREE"})
        assert got.facts[0].value == 0
    finally:
        clear_cache()


def test_civ7_has_no_ruleset_and_says_so(civ7_store):
    context = build_context(civ7_store.rebuild())
    got = ask(context, "ruleset.building", {"item": "BUILDING_GRANARY"})
    assert got.absence.kind is Unanswerable.RULESET_UNAVAILABLE
    assert "no queryable ruleset" in got.absence.detail


@pytest.mark.skipif(not DEFAULT_DATABASE.is_file(), reason="no installed Civ VI ruleset here")
def test_every_allowlisted_column_exists_in_the_real_installed_file():
    """Read-only. A patch that renames a column must fail a developer's run, not a player's."""
    conn = sqlite3.connect(f"file:{DEFAULT_DATABASE.as_posix()}?mode=ro", uri=True)
    try:
        for table, columns in READABLE_COLUMNS.items():
            present = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
            assert present, f"{table} is not in the installed ruleset"
            assert columns <= present, (table, sorted(columns - present))
        names = {row[0] for row in conn.execute("SELECT Name FROM GlobalParameters")}
        assert RULE_PARAMETERS <= names, sorted(RULE_PARAMETERS - names)
    finally:
        conn.close()
```

`tests/ruleset_fixture.py` must expose `build_fixture(path) -> Path`; if the module names its builder differently today, add `build_fixture` as an alias rather than renaming what other tests use.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_ruleset_growth.py -v`
Expected: FAIL — `ImportError: cannot import name 'RULE_PARAMETERS'` or missing `parameter`.

- [ ] **Step 3: Extend the fixture**

Append to `SCHEMA` in `tests/ruleset_fixture.py`:

```sql
CREATE TABLE GlobalParameters (Name TEXT NOT NULL PRIMARY KEY, Value TEXT);
CREATE TABLE Improvements (
    ImprovementType TEXT NOT NULL PRIMARY KEY, Name TEXT, PrereqTech TEXT, PrereqCivic TEXT,
    Housing INTEGER);
CREATE TABLE Improvement_YieldChanges (
    ImprovementType TEXT NOT NULL, YieldType TEXT NOT NULL, YieldChange INTEGER,
    PRIMARY KEY (ImprovementType, YieldType));
CREATE TABLE Policies (
    PolicyType TEXT NOT NULL PRIMARY KEY, Name TEXT, GovernmentSlotType TEXT, PrereqCivic TEXT);
CREATE TABLE Governments (
    GovernmentType TEXT NOT NULL PRIMARY KEY, Name TEXT, PrereqCivic TEXT, Tier INTEGER);
CREATE TABLE Government_SlotCounts (
    GovernmentType TEXT NOT NULL, GovernmentSlotType TEXT NOT NULL, NumSlots INTEGER,
    PRIMARY KEY (GovernmentType, GovernmentSlotType));
CREATE TABLE Resources (
    ResourceType TEXT NOT NULL PRIMARY KEY, Name TEXT, ResourceClassType TEXT,
    Happiness INTEGER, PrereqTech TEXT, PrereqCivic TEXT);
CREATE TABLE Resource_YieldChanges (
    ResourceType TEXT NOT NULL, YieldType TEXT NOT NULL, YieldChange INTEGER,
    PRIMARY KEY (ResourceType, YieldType));
CREATE TABLE Terrain_YieldChanges (
    TerrainType TEXT NOT NULL, YieldType TEXT NOT NULL, YieldChange INTEGER,
    PRIMARY KEY (TerrainType, YieldType));
CREATE TABLE Feature_YieldChanges (
    FeatureType TEXT NOT NULL, YieldType TEXT NOT NULL, YieldChange INTEGER,
    PRIMARY KEY (FeatureType, YieldType));
```

Add columns to the existing `CREATE TABLE Buildings` (`Entertainment INTEGER, CitizenSlots INTEGER, RequiresPlacement BOOLEAN`), `Districts` (`Housing INTEGER, Entertainment INTEGER, CitizenSlots INTEGER, Maintenance INTEGER`) and `Units` (`BaseMoves INTEGER, Range INTEGER, Domain TEXT, PromotionClass TEXT`), extending the existing rows with the real values (Library: Entertainment 0, CitizenSlots NULL, RequiresPlacement 0; Warrior: moves 2, range 0, `DOMAIN_LAND`, `PROMOTION_CLASS_MELEE`). Add rows, all read from the real file on 2026-09-13:

```python
    "GlobalParameters": [("CITY_AMENITIES_FOR_FREE", "0"), ("CITY_GROWTH_THRESHOLD", "15"),
                         ("CITY_MIN_RANGE", "3"), ("TRADE_ROUTE_BASE_RANGE", "15")],
    "Improvements": [("IMPROVEMENT_FARM", "LOC_IMPROVEMENT_FARM_NAME", "", "", 1)],
    "Improvement_YieldChanges": [("IMPROVEMENT_FARM", "YIELD_FOOD", 1),
                                 ("IMPROVEMENT_FARM", "YIELD_PRODUCTION", 0)],
    "Policies": [("POLICY_URBAN_PLANNING", "LOC_POLICY_URBAN_PLANNING_NAME",
                  "SLOT_ECONOMIC", "CIVIC_CODE_OF_LAWS")],
    "Governments": [("GOVERNMENT_CLASSICAL_REPUBLIC", "LOC_GOVERNMENT_CLASSICAL_REPUBLIC_NAME",
                     "CIVIC_POLITICAL_PHILOSOPHY", 1)],
    "Government_SlotCounts": [("GOVERNMENT_CLASSICAL_REPUBLIC", "SLOT_DIPLOMATIC", 1),
                              ("GOVERNMENT_CLASSICAL_REPUBLIC", "SLOT_ECONOMIC", 2),
                              ("GOVERNMENT_CLASSICAL_REPUBLIC", "SLOT_WILDCARD", 1)],
    "Resources": [("RESOURCE_SILK", "LOC_RESOURCE_SILK_NAME", "RESOURCECLASS_LUXURY", 4, "", ""),
                  ("RESOURCE_IRON", "LOC_RESOURCE_IRON_NAME", "RESOURCECLASS_STRATEGIC", 0,
                   "TECH_BRONZE_WORKING", "")],
```

plus `("BUILDING_GRANARY", "LOC_BUILDING_GRANARY_NAME", 65, 0, "DISTRICT_CITY_CENTER", "TECH_POTTERY", "", 2, 0, 0, None, 0)` in `Buildings` (Granary: Cost 65, Maintenance 0, Housing 2, IsWonder 0, Entertainment 0, CitizenSlots NULL, RequiresPlacement 0) and `("UNIT_ARCHER", "LOC_UNIT_ARCHER_NAME", 60, 1, 15, 25, "TECH_ARCHERY", "", "", 2, 2, "DOMAIN_LAND", "PROMOTION_CLASS_RANGED")` in `Units`. If a value here disagrees with the real file when the real-file test runs, the real file wins: change the fixture, never the assertion's source.

- [ ] **Step 4: Extend the value types**

In `civ_advisor/ruleset/base.py`:

- `BuildingFacts` gains `housing`, `entertainment`, `citizen_slots`, `is_wonder`, `requires_placement: RulesetFigure | None = None` and includes them in `figures`.
- `DistrictFacts` gains `housing`, `entertainment`, `citizen_slots`, `maintenance`.
- `UnitFacts` gains `moves`, `range`, `domain`, `promotion_class`.
- New dataclasses, each with a `figures` property in the same shape:

```python
@dataclass(frozen=True)
class ImprovementFacts:
    improvement: str
    prereq_tech: RulesetFigure | None = None
    prereq_civic: RulesetFigure | None = None
    housing: RulesetFigure | None = None
    yields: tuple[RulesetFigure, ...] = ()

    @property
    def figures(self) -> tuple[RulesetFigure, ...]:
        return tuple(f for f in (self.prereq_tech, self.prereq_civic, self.housing)
                     if f is not None) + self.yields


@dataclass(frozen=True)
class PolicyFacts:
    """Which slot a policy fills and what unlocks it. What it DOES is a modifier the
    ruleset does not quantify, so it is a mention and never a figure -- ADR-002."""
    policy: str
    slot: RulesetFigure | None = None
    prereq_civic: RulesetFigure | None = None
    mentions: tuple[RulesetMention, ...] = ()

    @property
    def figures(self) -> tuple[RulesetFigure, ...]:
        return tuple(f for f in (self.slot, self.prereq_civic) if f is not None)


@dataclass(frozen=True)
class GovernmentFacts:
    government: str
    prereq_civic: RulesetFigure | None = None
    tier: RulesetFigure | None = None
    slots: tuple[RulesetFigure, ...] = ()     # one per Government_SlotCounts row

    @property
    def figures(self) -> tuple[RulesetFigure, ...]:
        return tuple(f for f in (self.prereq_civic, self.tier) if f is not None) + self.slots


@dataclass(frozen=True)
class ResourceFacts:
    resource: str
    resource_class: RulesetFigure | None = None
    happiness: RulesetFigure | None = None     # a stated 0 is a figure, not absence
    prereq_tech: RulesetFigure | None = None
    prereq_civic: RulesetFigure | None = None
    yields: tuple[RulesetFigure, ...] = ()

    @property
    def figures(self) -> tuple[RulesetFigure, ...]:
        return tuple(f for f in (self.resource_class, self.happiness, self.prereq_tech,
                                 self.prereq_civic) if f is not None) + self.yields
```

- `RulesetProvider` gains `parameter(name) -> RulesetFigure | None`, `improvement(type)`, `policy(type)`, `government(type)`, `resource(type)`; `NullRuleset` returns `None` from each. Add the new names to `__all__`.

- [ ] **Step 5: Extend the provider**

In `civ_advisor/ruleset/civ6.py`:

```python
# GlobalParameters rows the copilot may quote, by name. Read by NAME from a fixed set,
# never by a name the model produced: adding one means reading its row from the
# installed file and writing it here. Every entry below was read on 2026-09-13.
RULE_PARAMETERS: frozenset[str] = frozenset({
    "CITY_AMENITIES_FOR_FREE",          # 0
    "CITY_GROWTH_THRESHOLD",            # 15
    "CITY_GROWTH_EXPONENT",             # 1.5
    "CITY_GROWTH_MULTIPLIER",           # 8
    "CITY_MIN_RANGE",                   # 3
    "CITY_POPULATION_COAST",            # 3
    "CITY_POPULATION_NO_WATER",         # 2
    "CITY_POPULATION_RIVER_LAKE",       # 5
    "CITY_POPULATION_AQUEDUCT_BOOST",   # 2
    "TRADE_ROUTE_BASE_RANGE",           # 15
    "WAR_WEARINESS_PER_UNIT_KILLED",    # 3
    "WAR_WEARINESS_PER_COMBAT_IN_FOREIGN_LANDS",   # 2
    "WAR_WEARINESS_PER_COMBAT_IN_ALLIED_LANDS",    # 1
})
```

Extend `READABLE_COLUMNS`:

```python
    "Buildings": frozenset({"BuildingType", "Cost", "Maintenance", "PrereqDistrict",
                            "PrereqTech", "PrereqCivic", "Housing", "Entertainment",
                            "CitizenSlots", "IsWonder", "RequiresPlacement"}),
    "Districts": frozenset({"DistrictType", "Cost", "PrereqTech", "PrereqCivic", "Housing",
                            "Entertainment", "CitizenSlots", "Maintenance"}),
    "Units": frozenset({"UnitType", "Cost", "Maintenance", "Combat", "RangedCombat",
                        "PrereqTech", "PrereqCivic", "StrategicResource", "BaseMoves",
                        "Range", "Domain", "PromotionClass"}),
    "GlobalParameters": frozenset({"Name", "Value"}),
    "Improvements": frozenset({"ImprovementType", "PrereqTech", "PrereqCivic", "Housing"}),
    "Improvement_YieldChanges": frozenset({"ImprovementType", "YieldType", "YieldChange"}),
    "Policies": frozenset({"PolicyType", "GovernmentSlotType", "PrereqCivic"}),
    "Governments": frozenset({"GovernmentType", "PrereqCivic", "Tier"}),
    "Government_SlotCounts": frozenset({"GovernmentType", "GovernmentSlotType", "NumSlots"}),
    "Resources": frozenset({"ResourceType", "ResourceClassType", "Happiness", "PrereqTech",
                            "PrereqCivic"}),
    "Resource_YieldChanges": frozenset({"ResourceType", "YieldType", "YieldChange"}),
    "Terrain_YieldChanges": frozenset({"TerrainType", "YieldType", "YieldChange"}),
    "Feature_YieldChanges": frozenset({"FeatureType", "YieldType", "YieldChange"}),
```

Add a shared yield-rows helper and the lookups, each through `_read_verified`:

```python
    def _yield_figures(self, table: str, key_column: str, subject: str,
                       label: str) -> tuple[RulesetFigure, ...]:
        try:
            rows = self._select(table, ("YieldType", "YieldChange"), {key_column: subject})
        except sqlite3.OperationalError:
            return ()
        return tuple(
            RulesetFigure(subject=subject, label=f"{label} {_yield_label(y['YieldType'])} yield",
                          value=y["YieldChange"], unit="per turn", table=table,
                          column="YieldChange", row_key=(subject, y["YieldType"]),
                          identity=self._identity)
            for y in rows)

    def parameter(self, name: str) -> RulesetFigure | None:
        if name not in RULE_PARAMETERS:
            return None     # not a gap in the file: a name outside the fixed set
        return self._read_verified("parameter", name, lambda: self._read_parameter(name))

    def _read_parameter(self, name: str) -> RulesetFigure | None:
        try:
            rows = self._select("GlobalParameters", ("Value",), {"Name": name})
        except sqlite3.OperationalError:
            return None
        if not rows or _absent(rows[0]["Value"]):
            return None
        raw = rows[0]["Value"]
        try:
            value: float | int | str = int(raw)
        except (TypeError, ValueError):
            try:
                value = float(raw)
            except (TypeError, ValueError):
                value = str(raw)
        return RulesetFigure(subject=name, label=f"Game rule {name}", value=value, unit=None,
                             table="GlobalParameters", column="Value", row_key=(name,),
                             identity=self._identity)

    def improvement(self, improvement_type: str) -> ImprovementFacts | None:
        return self._read_verified("improvement", improvement_type,
                                   lambda: self._read_improvement(improvement_type))

    def _read_improvement(self, improvement_type: str) -> ImprovementFacts | None:
        try:
            rows = self._select("Improvements", ("PrereqTech", "PrereqCivic", "Housing"),
                                {"ImprovementType": improvement_type})
        except sqlite3.OperationalError:
            return None
        if not rows:
            return None
        name = _title(improvement_type)
        make = self._figure_maker("Improvements", improvement_type, (improvement_type,), rows[0])
        return ImprovementFacts(
            improvement=improvement_type,
            prereq_tech=make("PrereqTech", f"{name} requires technology", None),
            prereq_civic=make("PrereqCivic", f"{name} requires civic", None),
            housing=make("Housing", f"{name} housing", "housing"),
            yields=self._yield_figures("Improvement_YieldChanges", "ImprovementType",
                                       improvement_type, name))

    def policy(self, policy_type: str) -> PolicyFacts | None:
        return self._read_verified("policy", policy_type, lambda: self._read_policy(policy_type))

    def _read_policy(self, policy_type: str) -> PolicyFacts | None:
        try:
            rows = self._select("Policies", ("GovernmentSlotType", "PrereqCivic"),
                                {"PolicyType": policy_type})
        except sqlite3.OperationalError:
            return None
        if not rows:
            return None
        name = _title(policy_type)
        make = self._figure_maker("Policies", policy_type, (policy_type,), rows[0])
        return PolicyFacts(
            policy=policy_type,
            slot=make("GovernmentSlotType", f"{name} fills slot", None),
            prereq_civic=make("PrereqCivic", f"{name} requires civic", None),
            mentions=(RulesetMention(
                subject=policy_type, label=f"{name} has an effect",
                detail=("The ruleset records which slot it fills and what unlocks it. What "
                        "it does is a modifier chain whose magnitude no row states.")),))

    def government(self, government_type: str) -> GovernmentFacts | None:
        return self._read_verified("government", government_type,
                                   lambda: self._read_government(government_type))

    def _read_government(self, government_type: str) -> GovernmentFacts | None:
        try:
            rows = self._select("Governments", ("PrereqCivic", "Tier"),
                                {"GovernmentType": government_type})
            slot_rows = self._select("Government_SlotCounts", ("GovernmentSlotType", "NumSlots"),
                                     {"GovernmentType": government_type})
        except sqlite3.OperationalError:
            return None
        if not rows:
            return None
        name = _title(government_type)
        make = self._figure_maker("Governments", government_type, (government_type,), rows[0])
        slots = tuple(
            RulesetFigure(subject=government_type,
                          label=f"{name} {_yield_label(s['GovernmentSlotType'].removeprefix('SLOT_'))} slots",
                          value=s["NumSlots"], unit="slots", table="Government_SlotCounts",
                          column="NumSlots", row_key=(government_type, s["GovernmentSlotType"]),
                          identity=self._identity)
            for s in slot_rows)
        return GovernmentFacts(
            government=government_type,
            prereq_civic=make("PrereqCivic", f"{name} requires civic", None),
            tier=make("Tier", f"{name} tier", None), slots=slots)

    def resource(self, resource_type: str) -> ResourceFacts | None:
        return self._read_verified("resource", resource_type,
                                   lambda: self._read_resource(resource_type))

    def _read_resource(self, resource_type: str) -> ResourceFacts | None:
        try:
            rows = self._select("Resources", ("ResourceClassType", "Happiness", "PrereqTech",
                                              "PrereqCivic"), {"ResourceType": resource_type})
        except sqlite3.OperationalError:
            return None
        if not rows:
            return None
        name = _title(resource_type)
        make = self._figure_maker("Resources", resource_type, (resource_type,), rows[0])
        return ResourceFacts(
            resource=resource_type,
            resource_class=make("ResourceClassType", f"{name} resource class", None),
            happiness=make("Happiness", f"{name} amenities when improved", "amenities"),
            prereq_tech=make("PrereqTech", f"{name} requires technology", None),
            prereq_civic=make("PrereqCivic", f"{name} requires civic", None),
            yields=self._yield_figures("Resource_YieldChanges", "ResourceType", resource_type,
                                       name))
```

Extend `_read_building`, `_read_district` and `_read_unit` to select and `make(...)` the new columns (`Housing` → `f"{name} housing"`, unit `"housing"`; `Entertainment` → unit `"amenities"`; `CitizenSlots` → unit `"slots"`; `IsWonder` and `RequiresPlacement` → unit `None`; `BaseMoves` → unit `"moves"`; `Range` → unit `"tiles"`, with `zero_is_absent=False` deliberately, because a melee unit's range 0 is a stated fact the way its RangedCombat 0 is not — say so in a comment; `Domain`, `PromotionClass` → unit `None`). `REQUIRED_TABLES = READABLE_COLUMNS` already makes `_schema_complaint` check every new column.

- [ ] **Step 6: Add the ruleset questions to the catalog**

In `civ_advisor/copilot/catalog.py`, add `notes: tuple[str, ...] = ()` to `Resolution` (deterministic sentences the model may read that are not facts — a `RulesetMention.as_unknown()` has no number in it, by construction), then:

```python
def _ruleset(question_id: str, lookup: str, param: str, *, id_prefix: str) -> Resolver:
    def resolve(context: DecisionContext, params: dict[str, str]) -> Resolution:
        provider = context.ruleset
        if not provider.available:
            return Resolution(absence=Absence(
                question_id, Unanswerable.RULESET_UNAVAILABLE,
                provider.reason or "no installed ruleset is readable"))
        facts = getattr(provider, lookup)(params[param])
        if facts is None:
            return Resolution(absence=Absence(
                question_id, Unanswerable.NO_SUCH_ROW,
                f"the installed ruleset has no {lookup} row for {params[param]}"))
        figures = (facts,) if not hasattr(facts, "figures") else facts.figures
        notes = tuple(m.as_unknown() for m in getattr(facts, "mentions", ()))
        notes += tuple(c.describe() for c in getattr(facts, "counts", ()))
        return Resolution(facts=tuple(evidence.ruleset_fact(context.ledger, f) for f in figures),
                          notes=notes)
    return resolve
```

and entries, each `verified_on="2026-09-13"`:

```python
        Question("ruleset.building", "A building's cost, upkeep, prerequisites, flat yields, "
                 "housing, entertainment and whether it needs a plot, from your installed ruleset.",
                 _ruleset("ruleset.building", "building", "item", id_prefix="ruleset"),
                 params=(Param("item", ParamKind.TYPE_KEY, "e.g. BUILDING_LIBRARY"),)),
        Question("ruleset.district", "A district's cost, prerequisites, housing and upkeep.",
                 _ruleset("ruleset.district", "district", "item", id_prefix="ruleset"),
                 params=(Param("item", ParamKind.TYPE_KEY, "e.g. DISTRICT_CAMPUS"),)),
        Question("ruleset.unit", "A unit's cost, upkeep, strength, moves, range and prerequisites.",
                 _ruleset("ruleset.unit", "unit", "item", id_prefix="ruleset"),
                 params=(Param("item", ParamKind.TYPE_KEY, "e.g. UNIT_ARCHER"),)),
        Question("ruleset.technology", "A technology's cost, era, prerequisites and eurekas.",
                 _ruleset("ruleset.technology", "technology", "item", id_prefix="ruleset"),
                 params=(Param("item", ParamKind.TYPE_KEY, "e.g. TECH_WRITING"),)),
        Question("ruleset.civic", "A civic's cost, era, prerequisites and inspirations.",
                 _ruleset("ruleset.civic", "civic", "item", id_prefix="ruleset"),
                 params=(Param("item", ParamKind.TYPE_KEY, "e.g. CIVIC_CODE_OF_LAWS"),)),
        Question("ruleset.improvement", "A tile improvement's prerequisites, housing and yields.",
                 _ruleset("ruleset.improvement", "improvement", "item", id_prefix="ruleset"),
                 params=(Param("item", ParamKind.TYPE_KEY, "e.g. IMPROVEMENT_FARM"),)),
        Question("ruleset.policy", "Which slot a policy card fills and what unlocks it. Its "
                 "effect is not quantified by the ruleset.",
                 _ruleset("ruleset.policy", "policy", "item", id_prefix="ruleset"),
                 params=(Param("item", ParamKind.TYPE_KEY, "e.g. POLICY_URBAN_PLANNING"),)),
        Question("ruleset.government", "A government's slot counts, tier and unlocking civic.",
                 _ruleset("ruleset.government", "government", "item", id_prefix="ruleset"),
                 params=(Param("item", ParamKind.TYPE_KEY, "e.g. GOVERNMENT_CLASSICAL_REPUBLIC"),)),
        Question("ruleset.resource", "A resource's class, amenities and prerequisites.",
                 _ruleset("ruleset.resource", "resource", "item", id_prefix="ruleset"),
                 params=(Param("item", ParamKind.TYPE_KEY, "e.g. RESOURCE_SILK"),)),
        Question("ruleset.parameter", "One of the game's global rule constants, by name.",
                 _ruleset("ruleset.parameter", "parameter", "name", id_prefix="ruleset"),
                 params=(Param("name", ParamKind.PARAMETER_NAME, "one of the fixed names"),)),
```

Remove the placeholder `RULE_PARAMETERS = frozenset()` Task 5 left, and the local import inside `choices` becomes a module-level `from civ_advisor.ruleset.civ6 import RULE_PARAMETERS`.

- [ ] **Step 7: Run to verify pass, then the whole suite**

Run: `uv run pytest tests/test_ruleset_growth.py tests/test_ruleset_civ6.py tests/test_ruleset_contracts.py -v && uv run pytest -q`
Expected: PASS, 15 growth tests (14 on a machine without the installed file). Existing ruleset tests that build the fixture keep passing because the added columns default to NULL and `_absent` treats NULL as "no figure".

- [ ] **Step 8: Commit**

```bash
git add civ_advisor/ruleset/base.py civ_advisor/ruleset/civ6.py civ_advisor/copilot/catalog.py \
        tests/ruleset_fixture.py tests/test_ruleset_growth.py
git commit -m "Read rule constants, improvements, policies, governments and resources from the installed ruleset"
```

---

### Task 7: Ask the tuner through the catalog, and read city ids and item hashes

**Files:**
- Modify: `civ_advisor/tuner/base.py`
- Modify: `civ_advisor/tuner/queries.py`
- Modify: `civ_advisor/tuner/client.py`
- Modify: `civ_advisor/copilot/catalog.py`
- Modify: `civ_advisor/api/serialize.py`
- Test: `tests/test_tuner_queries.py` (extend), `tests/test_copilot_tuner_questions.py`

**Interfaces:**
- Consumes: `tests/fixtures/tuner/query_buildoptions_ids.bin` from Task 1.
- Produces: `BuildOptionId`, `SettlementOptionIds`, `TunerProvider.build_option_ids()`, `TunerSnapshot.build_option_ids`, catalog `build_options_ids`, questions `settlement.amenities`, `settlement.build_options`, `empire.upkeep`.

`build_options` is left exactly as it is, with its fixture. `build_option_ids` is a second query that carries what acting needs — the city's id and each item's hash — and whether an item needs a plot. Kept separate so the existing parser and capture stay untouched. It is asked **only on a run started with `--allow-actions`**: a normal advisory run has no use for a city id or a hash, and its poll costs one query fewer. The catalog `city` parameter is validated against names, which `amenities` and `build_options` already carry.

- [ ] **Step 1: Write the failing tests**

Extend `tests/test_tuner_queries.py`:

```python
def test_build_option_ids_carry_the_city_id_the_hash_and_placement():
    rows = CATALOG["build_options_ids"].parse(lines("query_buildoptions_ids.bin"))
    by_city = {r.city: r for r in rows}
    first = next(iter(by_city.values()))
    assert isinstance(first.city_id, int)
    for o in first.options:
        assert isinstance(o.item_hash, int) and o.item.startswith("BUILDING_")
        assert o.requires_placement in (True, False)
        assert o.turns >= 0


def test_build_option_ids_runs_in_the_ui_state():
    assert CATALOG["build_options_ids"].state == "InGame"


def test_build_option_ids_lua_is_a_constant():
    assert "{" not in CATALOG["build_options_ids"].lua and "%s" not in CATALOG["build_options_ids"].lua
```

`tests/test_copilot_tuner_questions.py`:

```python
"""Live questions resolve to live readings, and their absence names the tuner's own cause."""
from civ_advisor.copilot.catalog import Unanswerable, ask
from civ_advisor.decisions.context import build_context
from civ_advisor.decisions.models import SourceKind
from civ_advisor.tuner.base import (
    BuildOption, CityAmenities, Maintenance, SettlementOptions, TunerReading, TunerSnapshot,
)

READING = TunerReading(turn=53, read_at="2026-09-13T10:40:00Z", state="GameCore_Tuner")
LIVE = TunerSnapshot(
    available=True,
    amenities=(CityAmenities(city="Rome", total=3, from_luxuries=1, from_civics=0,
                             from_entertainment=2, housing=9, food_surplus=1),),
    maintenance=Maintenance(total=1, buildings=0, districts=1, units=0, gold=152, gold_yield=8),
    build_options=(SettlementOptions(city="Rome", options=(BuildOption("BUILDING_GRANARY", 8),)),),
    readings=(("amenities", READING), ("maintenance", READING),
              ("build_options", TunerReading(turn=53, read_at="2026-09-13T10:40:01Z",
                                             state="InGame"))),
)


def test_amenities_resolve_to_a_live_reading_for_that_city(civ6_store):
    context = build_context(civ6_store.rebuild(), tuner=LIVE)
    got = ask(context, "settlement.amenities", {"city": "Rome"})
    (fact,) = got.facts
    assert fact.source_kind is SourceKind.LIVE_READING
    assert fact.value == 3 and fact.observed_turn == 53 and fact.reported_at


def test_a_city_the_reading_did_not_name_is_a_bad_parameter(civ6_store):
    context = build_context(civ6_store.rebuild(), tuner=LIVE)
    got = ask(context, "settlement.amenities", {"city": "Carthage"})
    assert got.absence.kind is Unanswerable.BAD_PARAMETER


def test_upkeep_resolves_to_the_live_net_gold(civ6_store):
    context = build_context(civ6_store.rebuild(), tuner=LIVE)
    got = ask(context, "empire.upkeep", {})
    assert any(f.value == 7 and f.source_kind is SourceKind.LIVE_READING for f in got.facts)


def test_build_options_resolve_per_option_with_turns(civ6_store):
    context = build_context(civ6_store.rebuild(), tuner=LIVE)
    got = ask(context, "settlement.build_options", {"city": "Rome"})
    assert [(f.subject_id, f.value, f.unit) for f in got.facts] == [("Rome", 8, "turns")]


def test_with_the_tuner_off_the_absence_carries_the_tuners_own_cause(civ6_store):
    context = build_context(civ6_store.rebuild())
    got = ask(context, "empire.upkeep", {})
    assert got.absence.kind is Unanswerable.TUNER_ABSENT
    assert got.absence.cause in {"not_enabled", "not_answering", "no_socket", "not_asked",
                                 "unreachable"}
    assert got.absence.detail


def test_civ7_has_no_socket_and_says_so(civ7_store):
    context = build_context(civ7_store.rebuild(), tuner=civ7_store.snapshot.tuner)
    got = ask(context, "empire.upkeep", {})
    assert got.absence.kind is Unanswerable.TUNER_ABSENT
    assert got.absence.cause == "no_socket"
    assert "EnableTuner" not in got.absence.detail
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_tuner_queries.py tests/test_copilot_tuner_questions.py -v`
Expected: FAIL — `KeyError: 'build_options_ids'`, then missing questions.

- [ ] **Step 3: Types and the query**

In `civ_advisor/tuner/base.py`:

```python
@dataclass(frozen=True)
class BuildOptionId:
    """One offered building with the integers an operation would need.

    `item_hash` is the game's own hash for the type, as `GameInfo.Buildings()` reports
    it. It is the ONLY form in which an item ever reaches a command: a name is for the
    player and the model, a hash is what the game asked for. `requires_placement` is
    read from the same row, so an item that needs a plot is known before anyone proposes
    it.
    """

    item: str
    item_hash: int
    requires_placement: bool
    turns: int

    def __post_init__(self) -> None:
        if type(self.item_hash) is not int:
            raise ValueError(f"item_hash must be an int, got {type(self.item_hash).__name__}")
        if self.turns < 0:
            raise ValueError(f"turns must not be negative, got {self.turns}")


@dataclass(frozen=True)
class SettlementOptionIds:
    city_id: int
    city: str
    options: tuple[BuildOptionId, ...]

    def offers(self, item: str) -> BuildOptionId | None:
        return next((o for o in self.options if o.item == item), None)
```

Add `def build_option_ids(self) -> tuple[SettlementOptionIds, ...]: ...` to `TunerProvider`, returning `()` on `NullTuner`; add `build_option_ids: tuple[SettlementOptionIds, ...] = ()` to `TunerSnapshot`. `capture` gains a keyword `acting: bool = False` and asks a fourth `_ask(provider, "build_options_ids", provider.build_option_ids, ())` **only when `acting` is true**, including it in `absences`, `readings` and the returned snapshot; with `acting` false the field stays `()` and no absence is recorded for it, because nothing was asked. `Store.__init__` gains `allow_actions: bool = False` (set by `create_app` from its own `allow_actions` in Task 11) and passes `acting=self.allow_actions` to `capture`. A test in `tests/test_tuner_store.py` asserts a store built without the flag never sends `build_options_ids` — by counting the fake game's `asked` commands. Export the two names.

In `civ_advisor/tuner/queries.py`:

```python
# The same walk as _BUILD_OPTIONS_LUA, carrying the integers an operation would need:
# the city's id and the row's hash. `RequiresPlacement` says whether the game's own UI
# would send this item into placement mode rather than the queue; the catalog will
# never offer such an item to set_production. Verified by the write spike, Task 1 of
# the copilot plan, whose reply is tests/fixtures/tuner/query_buildoptions_ids.bin.
_BUILD_OPTION_IDS_LUA = (
    _TURN_LUA +
    'local ok,err=pcall(function() '
    'for _,c in Players[Game.GetLocalPlayer()]:GetCities():Members() do '
    'local q=c:GetBuildQueue() '
    'for row in GameInfo.Buildings() do '
    'local ok2,can=pcall(function() return q:CanProduce(row.Hash,true) end) '
    'if ok2 and can then print(c:GetID(), Locale.Lookup(c:GetName()), row.BuildingType, '
    'row.Hash, tostring(row.RequiresPlacement), q:GetTurnsLeft(row.Hash)) end end end end) '
    'if not ok then print("PROBEERR", tostring(err)) end'
)


def _parse_build_option_ids(lines: list[str]) -> tuple[SettlementOptionIds, ...]:
    grouped: dict[tuple[int, str], list[BuildOptionId]] = {}
    for line in lines:
        parts = _fields(line)
        if len(parts) != 6:
            continue
        city_id, city, item, item_hash, placement, turns = parts
        try:
            grouped.setdefault((int(city_id), city), []).append(BuildOptionId(
                item=item, item_hash=int(item_hash),
                requires_placement=placement.lower() == "true", turns=int(turns)))
        except ValueError:
            continue
    return tuple(SettlementOptionIds(city_id=cid, city=name, options=tuple(opts))
                 for (cid, name), opts in grouped.items())
```

and the entry `Query("build_options_ids", "InGame", _BUILD_OPTION_IDS_LUA, "2026-09-13", _parse_build_option_ids)` in `CATALOG` — with `verified_on` set to the date the spike actually ran, read from the findings document. In `client.py`, `def build_option_ids(self): return self._answer("build_options_ids") or ()`.

In `civ_advisor/api/serialize.py:tuner_to_dict`, add `"build_option_ids"` (city, city_id, options with item, item_hash, requires_placement, turns), `"build_option_ids_reason"` and `"build_option_ids_read"` in the same shape as the existing three, so the page can name what a proposal will refer to.

- [ ] **Step 4: The live questions**

In `civ_advisor/copilot/catalog.py`:

```python
def _tuner_absent(question_id: str, context: DecisionContext, query_id: str) -> Resolution:
    tuner = context.tuner
    detail = tuner.absence(query_id) if tuner.available else tuner.reason
    return Resolution(absence=Absence(
        question_id, Unanswerable.TUNER_ABSENT,
        detail or "the tuner supplied no reading for this",
        cause=None if tuner.unavailable is None else tuner.unavailable.value))


def _amenities(context: DecisionContext, params: dict[str, str]) -> Resolution:
    tuner = context.tuner
    reading = tuner.reading_for("amenities") if tuner.available else None
    row = next((a for a in tuner.amenities if a.city == params["city"]), None)
    if reading is None or row is None:
        return _tuner_absent("settlement.amenities", context, "amenities")
    return Resolution(facts=(evidence.amenities_fact(context.ledger, reading, row),))


def _upkeep(context: DecisionContext, params: dict[str, str]) -> Resolution:
    tuner = context.tuner
    reading = tuner.reading_for("maintenance") if tuner.available else None
    if reading is None or tuner.maintenance is None:
        return _tuner_absent("empire.upkeep", context, "maintenance")
    return Resolution(facts=(evidence.tuner_net_gold_fact(context.ledger, reading,
                                                          tuner.maintenance),))


def _live_options(context: DecisionContext, params: dict[str, str]) -> Resolution:
    tuner = context.tuner
    reading = tuner.reading_for("build_options") if tuner.available else None
    so = next((s for s in tuner.build_options if s.city == params["city"]), None)
    if reading is None or so is None:
        return _tuner_absent("settlement.build_options", context, "build_options")
    return Resolution(facts=tuple(
        evidence.build_option_fact(context.ledger, reading, so.city, o) for o in so.options))
```

Entries:

```python
        Question("settlement.amenities", "One settlement's amenities and their sources, read "
                 "live from the game.", _amenities,
                 params=(Param("city", ParamKind.CITY, "the settlement"),), verified_on="2026-09-13"),
        Question("empire.upkeep", "Net gold after upkeep, read live from the game.", _upkeep,
                 verified_on="2026-09-13"),
        Question("settlement.build_options", "What one settlement may build right now and how "
                 "many turns each would take, read live.", _live_options,
                 params=(Param("city", ParamKind.CITY, "the settlement"),), verified_on="2026-09-13"),
```

`_city_names` in Task 5 already includes cities from `tuner.amenities` and `tuner.build_options`; add `tuner.build_option_ids` to it too.

- [ ] **Step 5: Run to verify pass, then the whole suite**

Run: `uv run pytest tests/test_tuner_queries.py tests/test_copilot_tuner_questions.py tests/test_tuner_base.py tests/test_tuner_client.py -v && uv run pytest -q`
Expected: PASS — 3 new query tests, 6 question tests, and the store test above. The `FakeGame` in `tests/test_tuner_client.py` replies to any `InGame` command with `query_buildoptions.bin`; a store built with `allow_actions=True` sends the fourth query and the fake's reply parses to `()` (3 fields, not 6), which `capture` records as an absence with the parser's reason, not as a failure. A store built without the flag sends exactly the three queries it sends today.

- [ ] **Step 6: Commit**

```bash
git add civ_advisor/tuner/base.py civ_advisor/tuner/queries.py civ_advisor/tuner/client.py \
        civ_advisor/copilot/catalog.py civ_advisor/api/serialize.py \
        tests/test_tuner_queries.py tests/test_copilot_tuner_questions.py
git commit -m "Let the copilot ask the tuner by name, and read the ids an operation would need"
```

---

### Task 8: The conversation — select, resolve, compose, validate, or fall back

**Files:**
- Create: `civ_advisor/copilot/conversation.py`
- Test: `tests/test_copilot_conversation.py`

**Interfaces:**
- Consumes: `catalog.CATALOG/choices/ask`, `grounding.check`, `questions.FENCES/SENTENCE_ENDS/MIN_ANSWER`, `DecisionContext`.
- Produces: `ASK_LIMIT`, `HISTORY_LIMIT`, `MAX_QUESTIONS`, `Exchange`, `ChatRequest`, `Selected`, `Resolved`, `ChatAnswer`, `select_prompt`, `select_schema`, `parse_selection`, `resolve`, `compose_prompt`, `compose_schema`, `validate_answer`, `fallback`, `fact_payload`, `source_phrase`, `Transcript`.

Two model calls, one deterministic step between them, and a deterministic answer that exists whether or not either call happens. The player's text reaches `select_prompt` and `compose_prompt` and nothing else.

- [ ] **Step 1: Write the failing tests**

`tests/test_copilot_conversation.py`:

```python
"""The conversation: closed vocabularies in, grounded prose or the deterministic answer out."""
import json

import pytest

from civ_advisor.copilot import conversation as conv
from civ_advisor.copilot.catalog import CATALOG, ParamKind
from civ_advisor.decisions.context import build_context


@pytest.fixture
def context(civ7_store):
    return build_context(civ7_store.rebuild())


def request(context, text="How is my culture doing?", history=()):
    return conv.ChatRequest(
        text=text, session="s1", epoch=1, snapshot_revision=3, context_revision=0,
        evidence_mode="oracle", turn=context.analysis_turn, display_name="Civilization VII",
        context=context, history=tuple(history))


def test_the_players_text_is_trimmed_to_the_limit(context):
    made = request(context, text="x" * 2000)
    assert len(made.text) == conv.ASK_LIMIT


def test_the_select_schema_enumerates_exactly_this_polls_choices(context):
    schema = conv.select_schema(request(context))
    ids = schema["properties"]["questions"]["items"]["properties"]["id"]["enum"]
    assert set(ids) == set(CATALOG)
    params = schema["properties"]["questions"]["items"]["properties"]["params"]["properties"]
    assert params["stat"]["enum"] == list(conv.catalog.choices(context)[ParamKind.STAT])
    assert params["item"]["pattern"] == conv.catalog.TYPE_KEY.pattern
    assert schema["properties"]["questions"]["maxItems"] == conv.MAX_QUESTIONS


def test_the_select_prompt_carries_the_players_words_as_a_question_not_a_fact(context):
    prompt = conv.select_prompt(request(context, text="I have 40 gold"))
    assert "I have 40 gold" in prompt
    assert "not an observation" in prompt


def test_parse_selection_keeps_only_catalog_ids_and_caps_the_count(context):
    data = {"questions": [{"id": "empire.comparison", "params": {"stat": "culture"}},
                          {"id": "empire.everything", "params": {}}] * 6, "cannot": ""}
    selected = conv.parse_selection(request(context), data)
    assert len(selected) <= conv.MAX_QUESTIONS
    assert all(s.question_id in CATALOG or s.question_id == "empire.everything" for s in selected)


def test_resolve_separates_facts_from_absences(context):
    selected = (conv.Selected("empire.comparison", {"stat": "culture"}),
                conv.Selected("empire.everything", {}),
                conv.Selected("ruleset.building", {"item": "BUILDING_LIBRARY"}))
    resolved = conv.resolve(request(context), selected)
    assert resolved.facts
    kinds = {a.kind.value for a in resolved.absences}
    assert "not_in_catalog" in kinds and "ruleset_unavailable" in kinds


def test_the_compose_schema_enumerates_only_resolved_fact_ids(context):
    resolved = conv.resolve(request(context), (conv.Selected("empire.comparison", {"stat": "culture"}),))
    schema = conv.compose_schema(request(context), resolved)
    assert set(schema["properties"]["evidence_ids"]["items"]["enum"]) == {f.id for f in resolved.facts}
    assert "proposal" not in schema["properties"]


def test_a_composed_answer_with_an_ungrounded_number_is_rejected(context):
    resolved = conv.resolve(request(context), (conv.Selected("empire.comparison", {"stat": "culture"}),))
    fact = next(f for f in resolved.facts if f.id.startswith("comparison."))
    data = {"text": "You trail the median and it will take about 12 turns to catch up.",
            "evidence_ids": [fact.id], "unknowns": []}
    with pytest.raises(ValueError, match="12"):
        conv.validate_answer(request(context), resolved, data)


def test_a_composed_answer_whose_numbers_are_cited_passes(context):
    resolved = conv.resolve(request(context), (conv.Selected("turn.analysis", {}),))
    (fact,) = resolved.facts
    data = {"text": f"The logs are complete through turn {fact.value}, so that is the turn "
                    "this answer describes.", "evidence_ids": [fact.id], "unknowns": []}
    answer = conv.validate_answer(request(context), resolved, data)
    assert answer.generated and answer.evidence_ids == (fact.id,)


def test_a_composed_answer_may_not_cite_an_id_it_was_not_given(context):
    resolved = conv.resolve(request(context), (conv.Selected("turn.analysis", {}),))
    data = {"text": "This is a long enough sentence to count as an answer here.",
            "evidence_ids": ["gold.net.9"], "unknowns": []}
    with pytest.raises(ValueError, match="not supplied"):
        conv.validate_answer(request(context), resolved, data)


def test_history_numbers_are_not_admitted(context):
    """An earlier answer said 7. This answer must cite a fact that says so now."""
    earlier = conv.Exchange(id="e1", asked_at="2026-09-13T10:00:00Z", turn=80,
                            text="net gold?", answer_text="Your net gold is 7.",
                            status="ready", question_ids=("empire.net_gold",),
                            evidence_ids=("gold.net.80",))
    made = request(context, history=[earlier])
    resolved = conv.resolve(made, (conv.Selected("turn.analysis", {}),))
    data = {"text": "As before, your net gold is 7 and that has not changed at all.",
            "evidence_ids": [resolved.facts[0].id], "unknowns": []}
    with pytest.raises(ValueError, match="7"):
        conv.validate_answer(made, resolved, data)


def test_the_fallback_names_every_fact_with_its_source_and_every_absence(context):
    selected = (conv.Selected("empire.comparison", {"stat": "culture"}),
                conv.Selected("ruleset.building", {"item": "BUILDING_LIBRARY"}))
    resolved = conv.resolve(request(context), selected)
    answer = conv.fallback(request(context), resolved)
    assert not answer.generated
    for fact in resolved.facts:
        assert fact.label in answer.text
    assert "no queryable ruleset" in answer.text
    assert "Player_Stats.csv" in answer.text


def test_the_fallback_with_nothing_resolved_says_it_cannot_see_that(context):
    answer = conv.fallback(request(context), conv.Resolved())
    assert "cannot" in answer.text.lower()
    assert conv.grounding.check(answer.text, (), []).ok


def test_the_fallback_repeats_a_typed_number_only_as_the_players_statement(context):
    answer = conv.fallback(request(context, text="is 8 turns for a Granary good?"), conv.Resolved())
    assert "You mention 8" in answer.text and "your statement" in answer.text
    assert conv.grounding.check(answer.text, (), [], player_text="is 8 turns for a Granary good?").ok


def test_source_phrases_keep_the_five_kinds_apart(context):
    resolved = conv.resolve(request(context), (conv.Selected("empire.comparison", {"stat": "culture"}),))
    phrases = {conv.source_phrase(f) for f in resolved.facts}
    assert any("advisor rule" in p for p in phrases)
    assert any("Player_Stats.csv" in p for p in phrases)
    assert any("computed from" in p for p in phrases)


def test_the_transcript_is_scoped_to_session_and_epoch():
    t = conv.Transcript()
    e = conv.Exchange(id="e1", asked_at="t", turn=1, text="q", answer_text="a", status="ready",
                      question_ids=(), evidence_ids=())
    t.record("s1", 1, e)
    assert t.history("s1", 1) == (e,)
    assert t.history("s1", 2) == ()
    assert t.history("s2", 1) == ()


def test_history_offered_to_the_model_is_capped_and_dated(context):
    exchanges = [conv.Exchange(id=f"e{i}", asked_at="t", turn=70 + i, text=f"q{i}",
                               answer_text=f"a{i}", status="ready", question_ids=(),
                               evidence_ids=()) for i in range(10)]
    prompt = conv.compose_prompt(request(context, history=exchanges), conv.Resolved())
    assert "q9" in prompt and "q0" not in prompt
    assert "turn 79" in prompt
    assert "context only" in prompt
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_copilot_conversation.py -v`
Expected: FAIL — no module `civ_advisor.copilot.conversation`.

- [ ] **Step 3: Write the implementation**

`civ_advisor/copilot/conversation.py`:

```python
"""One exchange with the copilot, in two model calls with a deterministic step between.

  select   -- the model reads the player's words and names catalog questions;
  resolve  -- the advisor answers those questions from the snapshot, ruleset and reading;
  compose  -- the model writes prose around the facts, citing ids from a closed list;
  validate -- structure, citations, and the number rule (grounding.py); or
  fallback -- the resolved facts in words, each with its source, plus every absence.

The player's text reaches two prompts and nothing else. Earlier exchanges are offered as
context, dated by game turn, and the current answer must cite facts resolved NOW: a number
from an earlier exchange is not admitted, because it came from an earlier turn.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from civ_advisor.decisions.context import DecisionContext
from civ_advisor.decisions.models import EvidenceFact, SourceKind
from civ_advisor.llm.questions import FENCES, MIN_ANSWER, SENTENCE_ENDS

from . import catalog, grounding
from .catalog import Absence, ParamKind

ASK_LIMIT = 600        # characters of the player's words that reach a prompt
HISTORY_LIMIT = 6      # earlier exchanges offered as context
MAX_QUESTIONS = 8      # catalog questions one exchange may resolve

CANNOT = ("The advisor cannot see that. It answers only from the game's logs, your "
          "installed ruleset and, when it is on, the tuner's live reading.")


@dataclass(frozen=True)
class Exchange:
    id: str
    asked_at: str
    turn: int
    text: str
    answer_text: str
    status: str
    question_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class ChatRequest:
    text: str
    session: str
    epoch: int
    snapshot_revision: int
    context_revision: int
    evidence_mode: str
    turn: int
    display_name: str
    context: DecisionContext = field(compare=False, repr=False)
    history: tuple[Exchange, ...] = ()
    acting: object | None = None     # an ActingOffer (Task 11) or None: no proposals

    def __post_init__(self) -> None:
        object.__setattr__(self, "text", (self.text or "").strip()[:ASK_LIMIT])

    @property
    def cache_key(self) -> tuple:
        import hashlib
        return (self.session, self.epoch, self.evidence_mode, self.snapshot_revision,
                self.context_revision, hashlib.sha256(self.text.encode()).hexdigest(),
                len(self.history))


@dataclass(frozen=True)
class Selected:
    question_id: str
    params: dict[str, str]


@dataclass(frozen=True)
class Resolved:
    facts: tuple[EvidenceFact, ...] = ()
    absences: tuple[Absence, ...] = ()
    notes: tuple[str, ...] = ()
    asked: tuple[Selected, ...] = ()

    @property
    def fact_ids(self) -> tuple[str, ...]:
        return tuple(f.id for f in self.facts)


@dataclass(frozen=True)
class ChatAnswer:
    text: str
    evidence_ids: tuple[str, ...]
    unknowns: tuple[str, ...]
    generated: bool
    model: str = ""
    proposal: dict | None = None     # Task 11


# ---- select ---------------------------------------------------------------------------

def _catalog_listing() -> list[dict]:
    return [{"id": q.id, "description": q.description,
             "params": [{"name": p.name, "kind": p.kind.value, "description": p.description}
                        for p in q.params]}
            for q in catalog.CATALOG.values()]


def select_prompt(request: ChatRequest) -> str:
    return (
        f"You are a {request.display_name} advisor deciding which of a FIXED list of questions "
        "to look up in order to answer the player. You do not answer yet. Choose only questions "
        "from the list, with parameters from the allowed values; if nothing in the list can "
        "answer, choose none and say so in `cannot`. The player's words are a question or an "
        "intention, not an observation about the game.\n"
        "Return JSON only, shaped: {\"questions\":[{\"id\":\"...\",\"params\":{...}}],"
        "\"cannot\":\"\"}.\n"
        f"The player wrote: {json.dumps(request.text, ensure_ascii=False)}\n"
        "Questions available this turn:\n"
        + json.dumps(_catalog_listing(), ensure_ascii=False, separators=(",", ":"))
    )


def select_schema(request: ChatRequest) -> dict:
    valid = catalog.choices(request.context)

    def enum(kind: ParamKind) -> dict:
        values = list(valid.get(kind, ()))
        return {"type": "string", "enum": values} if values else {"type": "string", "maxLength": 0}

    return {
        "type": "object",
        "properties": {
            "questions": {
                "type": "array", "maxItems": MAX_QUESTIONS,
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "enum": sorted(catalog.CATALOG)},
                        "params": {
                            "type": "object",
                            "properties": {
                                "stat": enum(ParamKind.STAT),
                                "city": enum(ParamKind.CITY),
                                "item": {"type": "string", "pattern": catalog.TYPE_KEY.pattern},
                                "name": enum(ParamKind.PARAMETER_NAME),
                            },
                            "additionalProperties": False,
                        },
                    },
                    "required": ["id", "params"], "additionalProperties": False,
                },
            },
            "cannot": {"type": "string"},
        },
        "required": ["questions", "cannot"], "additionalProperties": False,
    }


def parse_selection(request: ChatRequest, data: dict) -> tuple[Selected, ...]:
    """Every selection the model made, capped. Unknown ids and bad values are kept: `ask`
    turns each into an Absence that names the mistake, which is more use than dropping it."""
    out: list[Selected] = []
    for row in (data.get("questions") or [])[:MAX_QUESTIONS]:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            continue
        params = {k: v for k, v in (row.get("params") or {}).items()
                  if isinstance(k, str) and isinstance(v, str)}
        out.append(Selected(row["id"], params))
    return tuple(out)


# ---- resolve --------------------------------------------------------------------------

def resolve(request: ChatRequest, selected: tuple[Selected, ...]) -> Resolved:
    facts: dict[str, EvidenceFact] = {}
    absences: list[Absence] = []
    notes: list[str] = []
    for s in selected:
        got = catalog.ask(request.context, s.question_id, s.params)
        for f in got.facts:
            facts.setdefault(f.id, f)
        if got.absence is not None:
            absences.append(got.absence)
        notes.extend(n for n in got.notes if n not in notes)
    return Resolved(facts=tuple(facts.values()), absences=tuple(absences),
                    notes=tuple(notes), asked=selected)


# ---- compose --------------------------------------------------------------------------

def source_phrase(fact: EvidenceFact) -> str:
    """Where a fact came from, in words a player can check. Five kinds, never blended."""
    turn = "" if fact.observed_turn is None else f", turn {fact.observed_turn}"
    if fact.source_kind is SourceKind.LOG:
        return f"from {fact.source_file}{turn}"
    if fact.source_kind is SourceKind.LIVE_READING:
        return f"read live from the game{turn}, at {fact.reported_at}"
    if fact.source_kind is SourceKind.INSTALLED_RULESET:
        return f"from your installed ruleset ({fact.source_file})"
    if fact.source_kind is SourceKind.PLAYER_REPORT:
        return f"your own report{turn}"
    if fact.source_kind is SourceKind.RULE:
        return "an advisor rule, not an observation"
    return f"computed from {', '.join(fact.contributing)}{turn}"


def fact_payload(fact: EvidenceFact) -> dict:
    return {"id": fact.id, "label": fact.label, "kind": fact.source_kind.value,
            "provenance": fact.provenance.value, "value": fact.value, "unit": fact.unit,
            "observed_turn": fact.observed_turn, "subject": fact.subject_id,
            "note": fact.note, "source": source_phrase(fact)}


def _history_payload(request: ChatRequest) -> list[dict]:
    return [{"turn": e.turn, "player": e.text, "advisor": e.answer_text}
            for e in request.history[-HISTORY_LIMIT:]]


def compose_prompt(request: ChatRequest, resolved: Resolved) -> str:
    payload = {
        "player": request.text,
        "turn": request.turn,
        "facts": [fact_payload(f) for f in resolved.facts],
        "cannot_answer": [{"question": a.question, "why": a.detail, "kind": a.kind.value}
                          for a in resolved.absences],
        "notes": list(resolved.notes),
        "earlier": _history_payload(request),
    }
    return (
        f"You are a {request.display_name} advisor answering the player from the supplied "
        "facts and nothing else. Write quantities as digits. Every number you write must "
        "appear in a fact you cite -- its value, its turn, or its note. Do not compute, "
        "estimate or recall a figure; if a figure is not in the facts, say the advisor "
        "cannot see it. A fact whose kind is player_report is the player's own figure: when "
        "you use it, say so -- 'the 8 turns you reported on turn 59' -- never as though the "
        "game said it. A number in the player's own message is their claim, not a fact: you "
        "may repeat it only as 'you mention ...', and if a fact gives a different figure for "
        "the same thing you must state both and say they disagree, never adopt either. Where "
        "`cannot_answer` lists something, say so plainly rather than filling it. The `earlier` exchanges are context only, from earlier turns: do not "
        "repeat a number from them. Do not write a URL.\n"
        "Return JSON only, shaped: {\"text\":\"...\",\"evidence_ids\":[\"...\"],"
        "\"unknowns\":[\"...\"]}.\n"
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    )


def compose_schema(request: ChatRequest, resolved: Resolved) -> dict:
    ids = sorted(resolved.fact_ids)
    item = {"type": "string", "enum": ids} if ids else {"type": "string", "maxLength": 0}
    schema = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "minLength": 1},
            "evidence_ids": {"type": "array", "items": item, "maxItems": 16},
            "unknowns": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
        },
        "required": ["text", "evidence_ids", "unknowns"], "additionalProperties": False,
    }
    if request.acting is not None:
        # Task 11 adds the `proposal` property here; without an acting offer the grammar
        # has no such field, so a normal run's model cannot propose anything.
        schema["properties"]["proposal"] = request.acting.schema()
    return schema


def validate_answer(request: ChatRequest, resolved: Resolved, data: dict) -> ChatAnswer:
    text = data.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("the answer had no text")
    text = text.strip()
    if any(fence in text for fence in FENCES):
        raise ValueError("the answer contained a code fence, so it is not prose")
    if len(text) < MIN_ANSWER:
        raise ValueError(f"the answer was {len(text)} characters, too short to be one")
    if not text.endswith(SENTENCE_ENDS):
        raise ValueError("the answer stopped mid-sentence")
    if "http://" in text or "https://" in text:
        raise ValueError("the answer contained a URL, which only the catalog may supply")
    ids = data.get("evidence_ids", [])
    if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
        raise ValueError("evidence_ids must be a list of ids")
    invented = sorted(set(ids) - set(resolved.fact_ids))
    if invented:
        raise ValueError("evidence_ids cites ids that were not supplied: " + ", ".join(invented))
    cited = tuple(dict.fromkeys(ids))
    grounded = grounding.check(text, cited, [fact_payload(f) for f in resolved.facts],
                               player_text=request.text)
    if not grounded.ok:
        raise ValueError(grounded.describe())
    unknowns = tuple(u for u in data.get("unknowns", []) if isinstance(u, str) and u.strip())
    proposal = None
    if request.acting is not None and isinstance(data.get("proposal"), dict):
        proposal = request.acting.validate(data["proposal"], cited)     # Task 11
    return ChatAnswer(text=text, evidence_ids=cited, unknowns=unknowns, generated=True,
                      proposal=proposal)


def _value(fact: EvidenceFact) -> str:
    if fact.value is None:
        return "no value"
    unit = f" {fact.unit}" if fact.unit else ""
    return f"{fact.value}{unit}"


def fallback(request: ChatRequest, resolved: Resolved, reason: str = "") -> ChatAnswer:
    """The deterministic answer: every resolved fact in words with its source, every
    absence with its reason. Shown first, and kept when a generation fails or is rejected."""
    parts: list[str] = []
    for fact in resolved.facts:
        parts.append(f"{fact.label}: {_value(fact)} ({source_phrase(fact)}).")
    parts.extend(resolved.notes)
    typed = [n.text for n in grounding.numerals_in(request.text)]
    if typed:
        # Spec 4.3 rule 7: the player's own figure is on screen as THEIR statement, beside
        # every grounded figure above, so a disagreement is visible whether or not a model
        # writes it. It is never a fact and never quietly adopted.
        parts.append(f"You mention {', '.join(typed)}: that is your statement, not a figure "
                     "the advisor holds; the figures above are what it can establish.")
    for absence in resolved.absences:
        parts.append(f"Not available — {absence.describe()}.")
    if not parts:
        parts.append(CANNOT)
    if reason:
        parts.append(f"(The generated answer was not shown: {reason}.)")
    return ChatAnswer(text=" ".join(parts), evidence_ids=resolved.fact_ids,
                      unknowns=tuple(a.detail for a in resolved.absences), generated=False)


# ---- the transcript ---------------------------------------------------------------------

class Transcript:
    """Exchanges per (session, epoch). In memory; a reload starts a new sitting."""

    def __init__(self) -> None:
        self._by_sitting: dict[tuple[str, int], list[Exchange]] = {}

    def record(self, session: str, epoch: int, exchange: Exchange) -> None:
        self._by_sitting.setdefault((session, epoch), []).append(exchange)

    def history(self, session: str, epoch: int) -> tuple[Exchange, ...]:
        return tuple(self._by_sitting.get((session, epoch), ()))


__all__ = ["ASK_LIMIT", "CANNOT", "ChatAnswer", "ChatRequest", "Exchange", "HISTORY_LIMIT",
           "MAX_QUESTIONS", "Resolved", "Selected", "Transcript", "compose_prompt",
           "compose_schema", "fact_payload", "fallback", "parse_selection", "resolve",
           "select_prompt", "select_schema", "source_phrase", "validate_answer"]
```

- [ ] **Step 4: Run to verify pass, then the whole suite**

Run: `uv run pytest tests/test_copilot_conversation.py -v && uv run pytest -q`
Expected: PASS, 17 tests.

- [ ] **Step 5: Commit**

```bash
git add civ_advisor/copilot/conversation.py tests/test_copilot_conversation.py
git commit -m "Answer the player in two grounded steps, or with the facts themselves"
```

---

### Task 9: The worker, the endpoints, and the box on the page

**Files:**
- Create: `civ_advisor/copilot/worker.py`
- Modify: `civ_advisor/api/app.py`
- Modify: `civ_advisor/api/serialize.py`
- Modify: `civ_advisor/web/app.js`
- Modify: `civ_advisor/web/briefing.js`
- Modify: `civ_advisor/web/index.html` (a mount point on the This turn tab, if the tab is not already built entirely by app.js)
- Modify: `civ_advisor/cli.py`
- Test: `tests/test_copilot_api.py`, `tests/test_web_briefing.py` (extend)

**Interfaces:**
- Consumes: everything above; `OllamaClient`.
- Produces: `CopilotWorker.ask(request) -> tuple[str, ChatAnswer]`, `wait(request, timeout)`, `close()`; `POST /api/copilot/ask`, `POST /api/copilot/question`, `GET /api/copilot/catalog`, `GET /api/copilot/transcript`; `create_app(..., copilot_worker=None)`; `briefing.copilotLabel(status, generated)`, `briefing.copilotEvidenceLines(answer, evidence)`.

**This task is the one that matters**, for the same reason the tuner plan's Task 8 was: everything above can pass while nothing reaches a player. The tests go through the HTTP payload.

- [ ] **Step 1: Write the failing tests**

`tests/test_copilot_api.py`:

```python
"""Does a grounded answer reach the page? Only the HTTP payload is proof."""
import json

import pytest
from fastapi.testclient import TestClient

from civ_advisor.api.app import create_app
from civ_advisor.copilot.worker import CopilotWorker
from civ_advisor.games.civ7 import CIV7


class ScriptedClient:
    """Stands in for OllamaClient: answers the select call, then the compose call."""

    model = "scripted"

    def __init__(self, select: dict, compose):
        self.select, self.compose, self.prompts = select, compose, []

    def generate(self, prompt: str, *, schema: dict | None = None) -> str:
        self.prompts.append(prompt)
        if "deciding which of a FIXED list" in prompt:
            return json.dumps(self.select)
        data = self.compose(prompt) if callable(self.compose) else self.compose
        return json.dumps(data)


def app_with(fixture_dir, client=None):
    worker = None if client is None else CopilotWorker(client)
    return create_app(fixture_dir, poll_interval=60, profile=CIV7, copilot_worker=worker)


def test_the_catalog_and_this_turns_choices_reach_the_page(fixture_dir):
    with TestClient(app_with(fixture_dir)) as c:
        body = c.get("/api/copilot/catalog").json()
        ids = {q["id"] for q in body["questions"]}
        assert "empire.comparison" in ids and "ruleset.building" in ids
        assert body["choices"]["stat"] == ["culture", "science", "gold", "production", "food"]


def test_a_direct_question_returns_the_deterministic_answer_with_its_evidence(fixture_dir):
    with TestClient(app_with(fixture_dir)) as c:
        body = c.post("/api/copilot/question",
                      json={"id": "empire.comparison", "params": {"stat": "culture"}}).json()
        assert body["status"] == "fallback"
        assert body["answer"]["generated"] is False
        assert body["evidence"], "the resolved facts must travel with the answer"
        assert all(e["kind"] in {"log", "derived", "rule"} for e in body["evidence"])


def test_without_a_model_asking_free_text_says_so_and_offers_the_catalog(fixture_dir):
    with TestClient(app_with(fixture_dir)) as c:
        body = c.post("/api/copilot/ask", json={"text": "how am I doing?"}).json()
        assert body["status"] == "unsupported"
        assert "no local model" in body["answer"]["text"]


def test_a_grounded_generation_replaces_the_fallback(fixture_dir):
    def compose(prompt):
        facts = json.loads(prompt.split("\n", 2)[-1])["facts"]
        turn = next(f for f in facts if f["id"].startswith("turn.analysis"))
        return {"text": f"The logs are complete through turn {turn['value']}, and that is "
                        "the turn this answer is about.", "evidence_ids": [turn["id"]], "unknowns": []}
    client = ScriptedClient({"questions": [{"id": "turn.analysis", "params": {}}], "cannot": ""}, compose)
    with TestClient(app_with(fixture_dir, client)) as c:
        first = c.post("/api/copilot/ask", json={"text": "what turn is it?"}).json()
        assert first["status"] in {"generating", "ready"}
        assert first["answer"]["generated"] in {False, True}
        worker = c.app.state.copilot_worker
        worker.wait_all(timeout=5)
        body = c.post("/api/copilot/ask", json={"text": "what turn is it?"}).json()
        assert body["status"] == "ready"
        assert body["answer"]["generated"] is True
        assert body["answer"]["model"] == "scripted"
        assert body["questions_asked"] == [{"id": "turn.analysis", "params": {}}]


def test_an_ungrounded_generation_is_rejected_and_the_fallback_says_why(fixture_dir):
    compose = {"text": "You should expect roughly 12 more turns before anything changes here.",
               "evidence_ids": [], "unknowns": []}
    client = ScriptedClient({"questions": [{"id": "turn.analysis", "params": {}}], "cannot": ""}, compose)
    with TestClient(app_with(fixture_dir, client)) as c:
        c.post("/api/copilot/ask", json={"text": "how long?"})
        c.app.state.copilot_worker.wait_all(timeout=5)
        body = c.post("/api/copilot/ask", json={"text": "how long?"}).json()
        assert body["status"] == "rejected"
        assert body["answer"]["generated"] is False
        assert "12" in body["rejection"]


def test_the_players_text_never_reaches_a_resolver(fixture_dir):
    """The select prompt sees the words; the parameters come from the schema's enums."""
    client = ScriptedClient({"questions": [{"id": "empire.comparison",
                                            "params": {"stat": "culture"}}], "cannot": ""},
                            {"text": "x", "evidence_ids": [], "unknowns": []})
    with TestClient(app_with(fixture_dir, client)) as c:
        c.post("/api/copilot/ask", json={"text": "'; DROP TABLE Buildings; --"})
        c.app.state.copilot_worker.wait_all(timeout=5)
        body = c.post("/api/copilot/ask", json={"text": "'; DROP TABLE Buildings; --"}).json()
        assert body["questions_asked"] == [{"id": "empire.comparison", "params": {"stat": "culture"}}]


def test_the_transcript_is_scoped_to_this_sitting(fixture_dir):
    with TestClient(app_with(fixture_dir)) as c:
        c.post("/api/copilot/question", json={"id": "turn.analysis", "params": {}})
        body = c.get("/api/copilot/transcript").json()
        assert body["session"] and body["epoch"] == 1
        assert len(body["exchanges"]) == 1
        assert body["exchanges"][0]["question_ids"] == ["turn.analysis"]


def test_the_act_endpoint_is_refused_by_default(fixture_dir):
    with TestClient(app_with(fixture_dir)) as c:
        r = c.post("/api/copilot/act", json={"proposal_id": "x"})
        assert r.status_code == 403
        assert "--allow-actions" in r.json()["detail"]
```

Extend `tests/test_web_briefing.py`:

```python
def test_copilot_labels_never_call_a_fallback_generated():
    assert run_js('return B.copilotLabel("fallback", false);') == "From the evidence, not written by a model"
    assert run_js('return B.copilotLabel("ready", true);') == "Generated interpretation"
    assert run_js('return B.copilotLabel("rejected", false);').startswith("The model's answer was not shown")
    assert run_js('return B.copilotLabel("unsupported", false);') == "This cannot be answered"


def test_copilot_evidence_lines_carry_kind_turn_and_source_for_every_cited_fact():
    out = run_js("""
      return B.copilotEvidenceLines(
        {evidence_ids: ["a", "b"]},
        [{id: "a", label: "Your culture", kind: "log", value: 4, unit: "per turn",
          observed_turn: 81, source: "from Player_Stats.csv, turn 81"},
         {id: "b", label: "Rome's amenities", kind: "live_reading", value: 3, unit: "amenities",
          observed_turn: 82, source: "read live from the game, turn 82"},
         {id: "c", label: "not cited", kind: "log", value: 9}]);
    """)
    assert [l["id"] for l in out] == ["a", "b"]
    assert out[1]["badge"] == "read live" and out[0]["badge"] == "log row"
    assert "turn 82" in out[1]["text"]
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_copilot_api.py tests/test_web_briefing.py -v`
Expected: FAIL — no module `civ_advisor.copilot.worker`; `create_app` rejects `copilot_worker`.

- [ ] **Step 3: The worker**

`civ_advisor/copilot/worker.py`:

```python
"""One background thread for the conversation. Never blocks a request.

`ask` returns immediately with the deterministic answer and a status; the model's prose,
if it arrives and passes validation, replaces it on the next poll of the same request.
A rejection is recorded with its reason, so the page can say WHY the prose is missing
rather than looking as if there had never been a model.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor

from civ_advisor.llm.client import OllamaClient, OllamaError

from . import conversation as conv

log = logging.getLogger(__name__)


class CopilotWorker:
    def __init__(self, client: OllamaClient) -> None:
        self.client = client
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="civ-copilot")
        self._lock = threading.RLock()
        self._done: dict[tuple, tuple[str, conv.ChatAnswer, conv.Resolved, str]] = {}
        self._futures: dict[tuple, Future] = {}
        self._closed = False

    def ask(self, request: conv.ChatRequest) -> tuple[str, conv.ChatAnswer, conv.Resolved, str]:
        """(status, answer, resolved, rejection). Statuses: generating | ready | rejected."""
        key = request.cache_key
        with self._lock:
            held = self._done.get(key)
            if held is not None:
                return held
            if key not in self._futures and not self._closed:
                future = self._pool.submit(self._run, request)
                self._futures[key] = future
                future.add_done_callback(lambda _: self._futures.pop(key, None))
        return "generating", conv.fallback(request, conv.Resolved()), conv.Resolved(), ""

    def _run(self, request: conv.ChatRequest) -> None:
        key = request.cache_key
        resolved = conv.Resolved()
        try:
            chosen = json.loads(self.client.generate(
                conv.select_prompt(request), schema=conv.select_schema(request)))
            selected = conv.parse_selection(request, chosen)
            resolved = conv.resolve(request, selected)
            composed = json.loads(self.client.generate(
                conv.compose_prompt(request, resolved),
                schema=conv.compose_schema(request, resolved)))
            answer = conv.validate_answer(request, resolved, composed)
            result = ("ready", conv.ChatAnswer(**{**answer.__dict__, "model": self.client.model}),
                      resolved, "")
        except (OllamaError, json.JSONDecodeError, ValueError, KeyError) as exc:
            log.warning("copilot answer rejected: %s", exc)
            result = ("rejected", conv.fallback(request, resolved, str(exc)), resolved, str(exc))
        except Exception as exc:  # pragma: no cover - the optional path must never bite
            log.exception("unexpected copilot failure")
            result = ("rejected", conv.fallback(request, resolved, str(exc)), resolved, str(exc))
        with self._lock:
            self._done[key] = result

    def wait_all(self, timeout: float = 2.0) -> None:
        """Tests and the smoke check: block until every running exchange is done."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                pending = list(self._futures.values())
            if not pending:
                return
            for f in pending:
                try:
                    f.result(timeout=max(deadline - time.monotonic(), 0.01))
                except Exception:
                    pass

    def close(self) -> None:
        with self._lock:
            self._closed = True
        self._pool.shutdown(wait=False, cancel_futures=True)
```

- [ ] **Step 4: The endpoints**

In `civ_advisor/api/app.py`:

- `create_app` gains `copilot_worker: CopilotWorker | None = None` and `allow_actions: bool = False` (the flag is wired in Task 11; here it only gates the 403). Set `app.state.copilot_worker = copilot_worker`. Close it in `lifespan`'s `finally`.
- Module-level `transcript = conv.Transcript()` inside `create_app` (one per app), and a helper:

```python
    def chat_request(captured: Snapshot, oracle: bool, text: str) -> conv.ChatRequest:
        context, _ = brief_for(captured, oracle)
        return conv.ChatRequest(
            text=text, session=captured.session, epoch=captured.epoch,
            snapshot_revision=captured.revision, context_revision=context.context_revision,
            evidence_mode="oracle" if oracle else "fair", turn=captured.analysis_turn,
            display_name=get_profile(captured.game_id).display_name, context=context,
            history=transcript.history(captured.session, captured.epoch))

    def chat_response(captured, request, status, answer, resolved, rejection, asked) -> dict:
        exchange = conv.Exchange(
            id=secrets.token_hex(4), asked_at=datetime.now(UTC).isoformat(timespec="seconds"),
            turn=captured.analysis_turn, text=request.text, answer_text=answer.text,
            status=status, question_ids=tuple(a.question_id for a in asked),
            evidence_ids=answer.evidence_ids)
        if status in ("ready", "rejected", "fallback"):
            transcript.record(captured.session, captured.epoch, exchange)
        return {
            "status": status, "exchange_id": exchange.id, "turn": captured.analysis_turn,
            "evidence_mode": request.evidence_mode,
            "questions_asked": [{"id": a.question_id, "params": a.params} for a in asked],
            "answer": {"text": answer.text, "evidence_ids": list(answer.evidence_ids),
                       "unknowns": list(answer.unknowns), "generated": answer.generated,
                       "model": answer.model, "proposal": answer.proposal},
            "evidence": [conv.fact_payload(f) for f in resolved.facts],
            "absences": [{"question": a.question, "kind": a.kind.value, "detail": a.detail,
                          "cause": a.cause} for a in resolved.absences],
            "rejection": rejection,
        }
```

Endpoints:

```python
    @app.get("/api/copilot/catalog")
    def api_copilot_catalog(oracle: int = 1) -> dict:
        captured = current()
        context, _ = brief_for(captured, bool(oracle))
        return {
            "questions": [{"id": q.id, "description": q.description, "oracle": q.oracle,
                           "params": [{"name": p.name, "kind": p.kind.value,
                                       "description": p.description} for p in q.params]}
                          for q in catalog.CATALOG.values()],
            "choices": {k.value: list(v) for k, v in catalog.choices(context).items()},
            "model": None if copilot_worker is None else copilot_worker.client.model,
            "acting": allow_actions,
        }

    @app.post("/api/copilot/question", response_model=None)
    def api_copilot_question(body: dict = Body(...)):
        """One catalog question, resolved deterministically. Works with no model at all."""
        captured = current()
        request = chat_request(captured, bool(int(body.get("oracle", 1))), "")
        asked = (conv.Selected(str(body.get("id", "")),
                               {str(k): str(v) for k, v in (body.get("params") or {}).items()}),)
        resolved = conv.resolve(request, asked)
        return chat_response(captured, request, "fallback", conv.fallback(request, resolved),
                             resolved, "", asked)

    @app.post("/api/copilot/ask", response_model=None)
    def api_copilot_ask(body: dict = Body(...)):
        captured = current()
        request = chat_request(captured, bool(int(body.get("oracle", 1))), str(body.get("text") or ""))
        if not request.text:
            raise HTTPException(status_code=422, detail="nothing was asked")
        if copilot_worker is None:
            answer = conv.ChatAnswer(
                text=("There is no local model in this run, so free text cannot be read. "
                      "Pick one of the fixed questions instead; each answers from the evidence."),
                evidence_ids=(), unknowns=(), generated=False)
            return chat_response(captured, request, "unsupported", answer, conv.Resolved(), "", ())
        status, answer, resolved, rejection = copilot_worker.ask(request)
        return chat_response(captured, request, status, answer, resolved, rejection, resolved.asked)

    @app.get("/api/copilot/transcript")
    def api_copilot_transcript() -> dict:
        captured = current()
        return {"session": captured.session, "epoch": captured.epoch,
                "exchanges": [e.__dict__ | {"question_ids": list(e.question_ids),
                                            "evidence_ids": list(e.evidence_ids)}
                              for e in transcript.history(captured.session, captured.epoch)]}

    @app.post("/api/copilot/act", response_model=None)
    def api_copilot_act(body: dict = Body(...)):
        if not allow_actions:
            raise HTTPException(
                status_code=403,
                detail="this run was started without --allow-actions, so the advisor will not "
                       "send a command into the game; restart with the flag to enable acting")
        raise HTTPException(status_code=501, detail="acting is not implemented in this run")  # Task 11 replaces
```

Imports: `import secrets`, `from datetime import UTC, datetime`, `from civ_advisor.copilot import catalog, conversation as conv`.

In `civ_advisor/cli.py`, construct `CopilotWorker(OllamaClient(args.llm_model, timeout=args.llm_timeout))` beside the commentary worker (same `--no-llm` gate, same client settings) and pass `copilot_worker=` to `create_app`. `CopilotWorker` is exported from `civ_advisor/copilot/__init__.py`.

- [ ] **Step 5: The page**

In `civ_advisor/web/briefing.js`, two pure functions exported beside `PANEL_CAPABILITIES`:

```javascript
  /* What the copilot panel calls an answer. "fallback" is NOT a degraded state: it is
     the facts themselves, and it must never read as though a model wrote it. */
  function copilotLabel(status, generated) {
    if (status === "ready" && generated) return "Generated interpretation";
    if (status === "rejected") return "The model's answer was not shown; this is the evidence itself";
    if (status === "unsupported") return "This cannot be answered";
    if (status === "generating") return "From the evidence — the local model is writing an interpretation";
    return "From the evidence, not written by a model";
  }

  var KIND_BADGES = {
    log: "log row", derived: "computed", rule: "advisor rule", player_report: "your report",
    installed_ruleset: "installed ruleset", live_reading: "read live",
  };

  /* One line per CITED fact, in citation order, each with its kind badge and its source
     phrase. Uncited facts the resolver also returned are not lines: the answer did not
     rest on them. */
  function copilotEvidenceLines(answer, evidence) {
    var byId = {};
    (evidence || []).forEach(function (f) { byId[f.id] = f; });
    return (answer.evidence_ids || []).map(function (id) {
      var f = byId[id];
      if (!f) return { id: id, badge: "unresolved", text: id };
      var value = f.value === null || f.value === undefined ? "" : String(f.value);
      var unit = f.unit ? " " + f.unit : "";
      var turn = f.observed_turn === null || f.observed_turn === undefined ? "" : " (turn " + f.observed_turn + ")";
      return { id: id, badge: KIND_BADGES[f.kind] || f.kind,
               text: f.label + ": " + value + unit + turn + " — " + (f.source || "") };
    });
  }
```

and add both to the exported `api` object.

In `civ_advisor/web/app.js`, a `copilotPanel()` rendered on the **This turn** tab above the commentary block: a textarea (`maxLength` 600, `data-focus-key="copilot:ask"`), an Ask button, a row of buttons built from `/api/copilot/catalog` for questions with no parameters (and a `<select>` per enumerable parameter for the rest), the answer block using `copilotLabel`, the evidence list using `copilotEvidenceLines` with the badge rendered in the same classes the decision evidence drawer uses for the same kinds, the absences list each prefixed *Not available —*, and the transcript beneath, oldest first, each entry dated *turn N*. Poll `/api/copilot/ask` every 2500 ms while the status is `generating`, exactly as `ask()` does for questions, and refuse to paint a reply whose `turn` differs from `state.status.analysis_turn` (the same rule `acceptResponse` applies). When `catalog.model` is null, hide the textarea and show the sentence the API returns for `unsupported`. When `catalog.acting` is true, show *Acting enabled for this run* in the header beside the game label. If `index.html` needs a mount point, add `<section id="copilot"></section>` inside the This turn tab.

- [ ] **Step 6: Run to verify pass, then everything**

Run: `uv run pytest tests/test_copilot_api.py tests/test_web_briefing.py -v && uv run pytest -q`
Expected: PASS, 8 API tests and 2 briefing tests. Then, with the fixtures: `uv run civ-advisor --logs-dir tests/fixtures/logs_civ6 --game civ6 --no-archive --no-llm` and confirm the box renders, offers the catalog as buttons, and a click on *The turn the logs are complete through* shows the deterministic answer with a `log row` badge.

- [ ] **Step 7: Commit**

```bash
git add civ_advisor/copilot/worker.py civ_advisor/copilot/__init__.py civ_advisor/api/app.py \
        civ_advisor/api/serialize.py civ_advisor/web/app.js civ_advisor/web/briefing.js \
        civ_advisor/web/index.html civ_advisor/cli.py tests/test_copilot_api.py tests/test_web_briefing.py
git commit -m "Put a grounded conversation beside the briefing"
```

---

### Task 10: The operation catalog and the one object that can perform one — contingent on Task 1

**Assumes Task 1 recorded outcome A, D or E.** If it recorded B, C or F, this task is not performed. Under D, `Outcome.APPLIED` is unreachable on the turn of sending and the docstring on `classify` says so. Under E, the `CanStartOperation` guard may be absent and `set_production` is limited to hashes present in this poll's `build_option_ids` reading — which Task 11 enforces regardless.

**Files:**
- Create: `civ_advisor/tuner/commands.py`
- Modify: `civ_advisor/tuner/client.py`
- Test: `tests/test_tuner_commands.py`

**Interfaces:**
- Consumes: `tests/fixtures/tuner/write_set_production.bin`, `write_readback.bin`, `write_revert.bin` from Task 1; `protocol`, `queries.looks_unreachable`.
- Produces: `Command`, `COMMANDS`, `render(command_id, **ints) -> str`, `OutcomeKind`, `Outcome`, `classify(lines, requested_hash) -> Outcome`, `ActingTuner` with `perform(command_id, **ints) -> Outcome`, `open_acting_tuner(port, timeout) -> ActingTuner | NullTuner`.

`Civ6Tuner` is untouched and still has no method that sends anything but a catalog query. `ActingTuner` is a separate class, constructed only by `open_acting_tuner`, which only Task 11's confirm path calls, which only runs under `--allow-actions`.

- [ ] **Step 1: Write the failing tests**

`tests/test_tuner_commands.py`:

```python
"""The write-side allowlist. Lua is a constant; parameters are ints the program read
from the game; the reply is classified by reading the game back, never assumed."""
from pathlib import Path

import pytest

from civ_advisor.tuner.client import Civ6Tuner, open_tuner
from civ_advisor.tuner.commands import (
    COMMANDS, ActingTuner, OutcomeKind, classify, open_acting_tuner, render,
)
from civ_advisor.tuner.protocol import output_text, parse

from tests.test_tuner_client import FakeGame, replies

FIXTURES = Path(__file__).parent / "fixtures" / "tuner"


def lines(name: str) -> list[str]:
    msgs = parse((FIXTURES / name).read_bytes())
    return [t for t in (output_text(p) for _, p in msgs) if t and "---" not in t]


def test_every_command_body_is_a_constant_with_no_placeholder():
    for c in COMMANDS.values():
        assert "{" not in c.lua and "%s" not in c.lua and "CITYID" not in c.lua, c.id
        assert c.state == "InGame" and c.verified_on, c.id


def test_render_binds_only_ints_as_lua_integer_literals():
    lua = render("set_production", city_id=3, item_hash=-1234567890)
    assert lua.startswith("local cityId=3 local itemHash=-1234567890 ")
    assert COMMANDS["set_production"].lua in lua


@pytest.mark.parametrize("bad", ["3", 3.0, True, None, [3]])
def test_render_refuses_anything_that_is_not_an_int(bad):
    with pytest.raises(TypeError):
        render("set_production", city_id=bad, item_hash=1)


def test_render_refuses_a_missing_or_extra_parameter():
    with pytest.raises(ValueError, match="item_hash"):
        render("set_production", city_id=1)
    with pytest.raises(ValueError, match="extra"):
        render("set_production", city_id=1, item_hash=2, extra=3)


def test_render_refuses_an_unknown_command():
    with pytest.raises(KeyError):
        render("launch_nuke", city_id=1)


def test_the_recorded_success_classifies_as_applied():
    got = classify(lines("write_set_production.bin"), requested_hash=_requested())
    assert got.kind is OutcomeKind.APPLIED
    assert got.before_hash is not None and got.after_hash == _requested()


def test_a_rejected_line_classifies_as_rejected_with_the_games_words():
    got = classify(["before\t111", "canStart\tfalse", "REJECTED\tCanStartOperation returned false"],
                   requested_hash=222)
    assert got.kind is OutcomeKind.REJECTED
    assert "CanStartOperation" in got.detail


def test_a_lua_error_classifies_as_rejected():
    got = classify(["PROBEERR\tattempt to index a nil value"], requested_hash=222)
    assert got.kind is OutcomeKind.REJECTED


def test_requested_without_a_matching_readback_is_unconfirmed():
    got = classify(["before\t111", "requested", "after\t111"], requested_hash=222)
    assert got.kind is OutcomeKind.REQUESTED_UNCONFIRMED
    assert got.after_hash == 111


def test_the_read_side_client_has_no_perform():
    game = FakeGame(replies())
    try:
        t = open_tuner(port=game.port, timeout=3.0)
        assert isinstance(t, Civ6Tuner)
        assert not hasattr(t, "perform")
    finally:
        game.close()


def test_the_acting_client_performs_only_catalog_commands():
    game = FakeGame({125: (FIXTURES / "write_set_production.bin").read_bytes()})
    try:
        t = open_acting_tuner(port=game.port, timeout=3.0)
        assert isinstance(t, ActingTuner)
        out = t.perform("set_production", city_id=_city(), item_hash=_requested())
        assert out.kind is OutcomeKind.APPLIED
        sent = game.asked[-1]
        assert sent.startswith("CMD:125:local cityId=")
        with pytest.raises(KeyError):
            t.perform("anything_else", city_id=1)
        assert not hasattr(t, "run") and not hasattr(t, "query") and not hasattr(t, "eval")
    finally:
        game.close()


def _requested() -> int:
    """The hash Task 1 set, read from the capture's own `after` line."""
    for line in lines("write_set_production.bin"):
        if line.startswith("after\t"):
            return int(line.split("\t")[1])
    raise AssertionError("write_set_production.bin has no `after` line")


def _city() -> int:
    for line in lines("query_buildoptions_ids.bin"):
        parts = line.split("\t")
        if len(parts) == 6:
            return int(parts[0])
    raise AssertionError("query_buildoptions_ids.bin names no city")
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_tuner_commands.py -v`
Expected: FAIL — no module `civ_advisor.tuner.commands`.

- [ ] **Step 3: Write the implementation**

`civ_advisor/tuner/commands.py`:

```python
"""The fixed set of operations the advisor may perform in the game. The write side of
the allowlist queries.py is the read side of.

Lua here is a module constant. An operation's parameters are integers the program read
from the game itself this poll -- a city id and an item hash from `build_options_ids` --
and `render` binds them as Lua integer literals ahead of the constant body after checking
that each is exactly an int. No str, no bool, no float, no player text, ever.

Every command prints the state it read BEFORE acting and AFTER, and `classify` decides
the outcome from those lines, never from the absence of an error: the read spike showed
the game can accept a call and do nothing visible.

Which bindings this uses, and that they work over the socket, was established by the
write spike (docs/research/2026-09-13-civ6-tuner-write-spike.md). The Lua is the same
shape as the game's own ProductionPanel.lua:BuildBuilding, plus the CanStartOperation
guard the UI does not need because its buttons exist only for legal items.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from .base import NullTuner, TunerReading, TunerUnavailable
from .client import Civ6Tuner, HOST, PORT, SENTINEL, _NOT_ANSWERING
from .protocol import TAG_COMMAND, frame
from .queries import TURN_FIELD, _TURN_LUA, looks_unreachable, split_turn


@dataclass(frozen=True)
class Command:
    id: str
    state: str
    params: tuple[str, ...]      # Lua local names, bound in this order
    lua: str                     # the constant body; refers to the locals above
    verified_on: str


_SET_PRODUCTION_LUA = (
    _TURN_LUA +
    'local ok,err=pcall(function() '
    'local c=Players[Game.GetLocalPlayer()]:GetCities():FindID(cityId) '
    'if c==nil then print("REJECTED", "no city with id "..tostring(cityId)) return end '
    'local q=c:GetBuildQueue() '
    'print("before", q:GetCurrentProductionTypeHash()) '
    'local t={} '
    't[CityOperationTypes.PARAM_BUILDING_TYPE]=itemHash '
    't[CityOperationTypes.PARAM_INSERT_MODE]=CityOperationTypes.VALUE_EXCLUSIVE '
    'if CityManager.CanStartOperation~=nil then '
    'local can=CityManager.CanStartOperation(c, CityOperationTypes.BUILD, t) '
    'print("canStart", tostring(can)) '
    'if not can then print("REJECTED", "CanStartOperation returned false") return end end '
    'CityManager.RequestOperation(c, CityOperationTypes.BUILD, t) '
    'print("requested") '
    'print("after", q:GetCurrentProductionTypeHash()) end) '
    'if not ok then print("PROBEERR", tostring(err)) end'
)

COMMANDS: dict[str, Command] = {
    c.id: c for c in (
        Command("set_production", "InGame", ("cityId", "itemHash"), _SET_PRODUCTION_LUA,
                "2026-09-13"),
    )
}

# Python keyword -> Lua local. The Python side speaks snake_case ids; the Lua body reads
# the locals it was written against. One mapping, so neither side can drift alone.
_PARAM_NAMES = {"set_production": {"city_id": "cityId", "item_hash": "itemHash"}}


def render(command_id: str, **ints: int) -> str:
    """The exact chunk that would be sent. Raises rather than guessing on any mismatch."""
    command = COMMANDS[command_id]
    names = _PARAM_NAMES[command_id]
    extra = sorted(set(ints) - set(names))
    if extra:
        raise ValueError(f"{command_id} takes no parameter named {', '.join(extra)} (extra)")
    missing = sorted(set(names) - set(ints))
    if missing:
        raise ValueError(f"{command_id} needs {', '.join(missing)}")
    prefix = []
    for py_name, lua_name in names.items():
        value = ints[py_name]
        if type(value) is not int:      # bool is an int subclass; refused on purpose
            raise TypeError(f"{py_name} must be an int, got {type(value).__name__}")
        prefix.append(f"local {lua_name}={value}")
    return " ".join(prefix) + " " + command.lua


class OutcomeKind(StrEnum):
    NOT_SENT = "not_sent"
    REJECTED = "rejected"
    REQUESTED_UNCONFIRMED = "requested_unconfirmed"
    APPLIED = "applied"


@dataclass(frozen=True)
class Outcome:
    kind: OutcomeKind
    detail: str
    game_reply: tuple[str, ...] = ()
    before_hash: int | None = None
    after_hash: int | None = None
    reading: TunerReading | None = None
    lua: str = ""


def _hash_line(lines: list[str], key: str) -> int | None:
    for line in lines:
        parts = line.split("\t")
        if len(parts) == 2 and parts[0] == key:
            try:
                return int(parts[1])
            except ValueError:
                return None
    return None


def classify(lines: list[str], requested_hash: int,
             reading: TunerReading | None = None, lua: str = "") -> Outcome:
    """The outcome, from what the game printed. Order matters: a REJECTED or error line
    wins over anything else; then only a read-back naming the requested hash is APPLIED."""
    reply = tuple(lines)
    before, after = _hash_line(lines, "before"), _hash_line(lines, "after")
    rejected = next((l for l in lines if l.startswith("REJECTED")), None)
    if rejected is not None:
        return Outcome(OutcomeKind.REJECTED, rejected.split("\t", 1)[-1], reply, before, after,
                       reading, lua)
    if looks_unreachable(lines):
        return Outcome(OutcomeKind.REJECTED, "the game raised an error: " + " | ".join(
            l for l in lines if "ERR" in l or "Error" in l), reply, before, after, reading, lua)
    if "requested" not in lines:
        return Outcome(OutcomeKind.REJECTED, "the game printed no `requested` line", reply,
                       before, after, reading, lua)
    if after == requested_hash:
        return Outcome(OutcomeKind.APPLIED, "the read-back names the requested item", reply,
                       before, after, reading, lua)
    return Outcome(OutcomeKind.REQUESTED_UNCONFIRMED,
                   "the request was sent without error, but the read-back does not show the "
                   "requested item; whether it took is unknown until the next log row",
                   reply, before, after, reading, lua)


class ActingTuner(Civ6Tuner):
    """A connection that may also PERFORM a catalog command. Constructed only by
    `open_acting_tuner`, which only the confirm path under --allow-actions calls. The
    read-side `Civ6Tuner` has no `perform`; this subclass is the whole difference."""

    def perform(self, command_id: str, **ints: int) -> Outcome:
        command = COMMANDS[command_id]          # KeyError for anything not in the catalog
        lua = render(command_id, **ints)
        index = self._states.get(command.state)
        if index is None:
            return Outcome(OutcomeKind.NOT_SENT,
                           f"the game exposes no Lua state named {command.state!r}", lua=lua)
        try:
            self._sock.sendall(frame(TAG_COMMAND, f'CMD:{index}:{lua}\nprint("{SENTINEL}")'))
        except OSError:
            return Outcome(OutcomeKind.NOT_SENT, _NOT_ANSWERING, lua=lua)
        lines = self._collect()
        if lines is None:
            return Outcome(OutcomeKind.REQUESTED_UNCONFIRMED,
                           "the command was sent and the game did not answer before the timeout",
                           lua=lua)
        turn, rest = split_turn(lines)
        reading = None
        if turn is not None:
            try:
                reading = TunerReading(turn=turn, read_at=datetime.now(UTC).isoformat(
                    timespec="seconds"), state=command.state)
            except ValueError:
                reading = None
        return classify(rest, ints.get("item_hash", 0), reading, lua)

    def _collect(self) -> list[str] | None:
        """Every output line up to the sentinel, or None on timeout. Split out of `_ask`
        in client.py so both share one loop: refactor `_ask` to call this."""
        from .protocol import consume, output_text
        import socket as _socket
        lines: list[str] = []
        deadline = time.monotonic() + self._timeout
        self._sock.settimeout(0.2)
        while time.monotonic() < deadline:
            try:
                chunk = self._sock.recv(65536)
                if not chunk:
                    break
                self._buf += chunk
            except _socket.timeout:
                continue
            except OSError:
                break
            msgs, self._buf = consume(self._buf)
            for _, payload in msgs:
                text = output_text(payload)
                if text is None:
                    continue
                if SENTINEL in text:
                    return lines
                lines.append(text)
        return None


def open_acting_tuner(port: int = PORT, timeout: float = 3.0):
    """Like `open_tuner`, returning an ActingTuner. Never raises."""
    opened = __import__("civ_advisor.tuner.client", fromlist=["open_tuner"]).open_tuner(
        port=port, timeout=timeout)
    if isinstance(opened, NullTuner):
        return opened
    return ActingTuner(_sock=opened._sock, _states=opened._states, _timeout=opened._timeout,
                       _buf=opened._buf)


__all__ = ["COMMANDS", "ActingTuner", "Command", "Outcome", "OutcomeKind", "classify",
           "open_acting_tuner", "render"]
```

In `civ_advisor/tuner/client.py`, move the receive loop of `Civ6Tuner._ask` into a `_collect(self) -> list[str] | None` method with the `looks_unreachable` early return kept inside `_ask` by checking each returned line — one loop, used by both `_ask` and `perform` — and replace the `__import__` in `open_acting_tuner` with a plain `from .client import open_tuner` once the import order allows it (commands imports client; client does not import commands, so it does).

- [ ] **Step 4: Run to verify pass, then the whole suite**

Run: `uv run pytest tests/test_tuner_commands.py tests/test_tuner_client.py -v && uv run pytest -q`
Expected: PASS, 12 command tests. `test_the_client_exposes_no_way_to_run_arbitrary_lua` still passes: `Civ6Tuner` gained nothing.

- [ ] **Step 5: Commit**

```bash
git add civ_advisor/tuner/commands.py civ_advisor/tuner/client.py tests/test_tuner_commands.py
git commit -m "Fix the one operation the advisor may perform, and read the game back to say what happened"
```

---

### Task 11: Proposals, confirmation, the flag and the journal — contingent on Task 1

**Assumes Task 1 recorded outcome A, D or E** and Task 10 is merged. Under E, `ActingOffer.validate` is the only guard against an illegal item and must not be weakened.

**Files:**
- Create: `civ_advisor/copilot/journal.py`
- Create: `civ_advisor/copilot/actions.py`
- Modify: `civ_advisor/copilot/conversation.py` (the `acting` hook is already there)
- Modify: `civ_advisor/api/app.py`
- Modify: `civ_advisor/cli.py`
- Modify: `civ_advisor/web/app.js`, `civ_advisor/web/briefing.js`
- Test: `tests/test_copilot_actions.py`, `tests/test_cli.py` (extend), `tests/test_web_briefing.py` (extend)

**Interfaces:**
- Consumes: `commands.render/open_acting_tuner/OutcomeKind`, `TunerSnapshot.build_option_ids`, `conversation.ChatRequest.acting`.
- Produces: `Journal(path)`, `JournalEntry`, `ActingOffer(snapshot)`, `Proposal`, `Proposals` (registry), `PROPOSAL_TTL`, `confirm(...)`; `--allow-actions`; `POST /api/copilot/act`, `GET /api/copilot/proposals`, `GET /api/copilot/journal`.

- [ ] **Step 1: Write the failing tests**

`tests/test_copilot_actions.py`:

```python
"""Acting: off by default, one proposal one confirmation, journaled before sending,
turn-checked, and every outcome reported as what the game actually did."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from civ_advisor.api.app import create_app
from civ_advisor.copilot.actions import PROPOSAL_TTL, ActingOffer, Proposals
from civ_advisor.copilot.journal import Journal
from civ_advisor.games.civ6 import CIV6
from civ_advisor.tuner.base import (
    BuildOptionId, SettlementOptionIds, TunerReading, TunerSnapshot,
)
from tests.test_tuner_client import FakeGame

FIXTURES = Path(__file__).parent / "fixtures" / "tuner"
READING = TunerReading(turn=53, read_at="2026-09-13T10:40:00Z", state="InGame")
IDS = SettlementOptionIds(city_id=0, city="Rome", options=(
    BuildOptionId("BUILDING_GRANARY", 1234, False, 8),
    BuildOptionId("BUILDING_HANGING_GARDENS", 5678, True, 23)))
LIVE = TunerSnapshot(available=True, build_option_ids=(IDS,),
                     readings=(("build_options_ids", READING),))


def test_the_offer_enumerates_only_this_polls_cities_and_placeable_items():
    schema = ActingOffer(LIVE).schema()
    assert schema["properties"]["city"]["enum"] == ["Rome"]
    assert schema["properties"]["item"]["enum"] == ["BUILDING_GRANARY"]   # no Hanging Gardens


def test_a_proposal_binds_names_to_the_integers_the_game_gave():
    p = ActingOffer(LIVE).validate({"operation": "set_production", "city": "Rome",
                                    "item": "BUILDING_GRANARY", "because": []}, cited=())
    assert p["city_id"] == 0 and p["item_hash"] == 1234 and p["turn"] == 53
    assert p["lua"].startswith("local cityId=0 local itemHash=1234 ")


def test_a_name_outside_the_reading_is_refused_before_anything_is_rendered():
    with pytest.raises(ValueError, match="Carthage"):
        ActingOffer(LIVE).validate({"operation": "set_production", "city": "Carthage",
                                    "item": "BUILDING_GRANARY", "because": []}, cited=())


def test_an_item_needing_a_plot_is_refused():
    with pytest.raises(ValueError, match="plot"):
        ActingOffer(LIVE).validate({"operation": "set_production", "city": "Rome",
                                    "item": "BUILDING_HANGING_GARDENS", "because": []}, cited=())


def test_the_journal_appends_one_line_per_entry_and_reads_them_back(tmp_path):
    j = Journal(tmp_path / "actions.jsonl")
    j.record({"id": "a", "outcome": "not_sent"})
    j.record({"id": "b", "outcome": "applied"})
    assert [e["id"] for e in j.entries()] == ["b", "a"]
    assert (tmp_path / "actions.jsonl").read_text().count("\n") == 2


def test_an_unwritable_journal_is_reported_not_raised(tmp_path):
    j = Journal(tmp_path / "not-a-dir" / "x" / "actions.jsonl")
    (tmp_path / "not-a-dir").write_text("a file, not a directory")
    assert j.record({"id": "a"}) is False
    assert j.last_error


def test_a_proposal_can_be_confirmed_once_and_expires_with_the_turn():
    reg = Proposals()
    p = reg.add({"id": "p1", "turn": 53, "snapshot_revision": 4, "created": 0.0})
    assert reg.take("p1", turn=53, snapshot_revision=4, now=1.0) is p
    assert reg.take("p1", turn=53, snapshot_revision=4, now=1.0) is None
    p2 = reg.add({"id": "p2", "turn": 53, "snapshot_revision": 4, "created": 0.0})
    assert reg.take("p2", turn=54, snapshot_revision=4, now=1.0) is None
    p3 = reg.add({"id": "p3", "turn": 53, "snapshot_revision": 4, "created": 0.0})
    assert reg.take("p3", turn=53, snapshot_revision=4, now=PROPOSAL_TTL + 1) is None


def _acting_app(civ6_dir, tmp_path, game_port, allow=True):
    from civ_advisor.tuner.client import open_tuner
    from dataclasses import replace
    profile = replace(CIV6, tuner=lambda: open_tuner(port=game_port, timeout=3.0))
    return create_app(civ6_dir, poll_interval=60, profile=profile, allow_actions=allow,
                      journal_path=tmp_path / "actions.jsonl", acting_port=game_port)


def test_with_the_flag_off_nothing_is_ever_sent(civ6_dir, tmp_path):
    game = FakeGame({125: (FIXTURES / "query_buildoptions_ids.bin").read_bytes()})
    try:
        with TestClient(_acting_app(civ6_dir, tmp_path, game.port, allow=False)) as c:
            r = c.post("/api/copilot/act", json={"proposal_id": "x", "save_acknowledged": True})
            assert r.status_code == 403
        assert not any(a.startswith("CMD:125:local cityId=") for a in game.asked)
    finally:
        game.close()


def test_confirming_sends_journals_and_reports_the_recorded_outcome(civ6_dir, tmp_path):
    game = FakeGame({125: (FIXTURES / "query_buildoptions_ids.bin").read_bytes()
                     + (FIXTURES / "write_set_production.bin").read_bytes()})
    try:
        with TestClient(_acting_app(civ6_dir, tmp_path, game.port)) as c:
            catalog = c.get("/api/copilot/catalog").json()
            assert catalog["acting"] is True
            ids = c.get("/api/briefing").json()["tuner"]["build_option_ids"]
            city, option = ids[0]["city"], ids[0]["options"][0]
            made = c.post("/api/copilot/proposals", json={
                "operation": "set_production", "city": city, "item": option["item"],
                "because": []}).json()
            assert made["lua"].startswith("local cityId=")
            assert "cannot undo" in made["warning"]
            r = c.post("/api/copilot/act", json={"proposal_id": made["id"],
                                                 "snapshot_revision": made["snapshot_revision"],
                                                 "turn": made["turn"], "save_acknowledged": True})
            body = r.json()
            assert body["outcome"] in {"applied", "requested_unconfirmed", "rejected"}
            assert body["game_reply"]
            journal = c.get("/api/copilot/journal").json()["entries"]
            assert journal[0]["id"] == made["id"] and journal[0]["lua"] == made["lua"]
            assert journal[0]["save_acknowledged_at"]
            again = c.post("/api/copilot/act", json={"proposal_id": made["id"],
                                                     "snapshot_revision": made["snapshot_revision"],
                                                     "turn": made["turn"], "save_acknowledged": True})
            assert again.json()["outcome"] == "not_sent"
    finally:
        game.close()


def test_the_first_confirmation_of_a_sitting_needs_the_save_acknowledgement(civ6_dir, tmp_path):
    game = FakeGame({125: (FIXTURES / "query_buildoptions_ids.bin").read_bytes()})
    try:
        with TestClient(_acting_app(civ6_dir, tmp_path, game.port)) as c:
            ids = c.get("/api/briefing").json()["tuner"]["build_option_ids"]
            made = c.post("/api/copilot/proposals", json={
                "operation": "set_production", "city": ids[0]["city"],
                "item": ids[0]["options"][0]["item"], "because": []}).json()
            r = c.post("/api/copilot/act", json={"proposal_id": made["id"],
                                                 "snapshot_revision": made["snapshot_revision"],
                                                 "turn": made["turn"]})
            assert r.json()["outcome"] == "not_sent"
            assert "save" in r.json()["detail"]
    finally:
        game.close()
```

Extend `tests/test_cli.py`:

```python
def test_allow_actions_refuses_a_non_loopback_host(capsys):
    from civ_advisor.cli import main
    assert main(["--game", "civ7", "--allow-actions", "--host", "0.0.0.0", "--no-llm"]) == 2
    assert "loopback" in capsys.readouterr().err
```

Extend `tests/test_web_briefing.py`:

```python
def test_a_proposal_card_has_a_confirm_button_only_when_acting_is_on():
    assert run_js('return B.proposalControls({id: "p"}, true).confirm;') is True
    assert run_js('return B.proposalControls({id: "p"}, false).confirm;') is False
    assert "by hand" in run_js('return B.proposalControls({id: "p"}, false).note;')
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_copilot_actions.py -v`
Expected: FAIL — no module `civ_advisor.copilot.actions`.

- [ ] **Step 3: The journal**

`civ_advisor/copilot/journal.py`:

```python
"""Every command the advisor was asked to send, whether or not it was sent.

Append-only JSON lines under ~/.civ-advisor/<game>/, beside the player's notes and never
beside the game's own files. Written and fsynced BEFORE the operation goes out: the
advisor will not act where it cannot record having acted, so a write failure here turns
the outcome into `not_sent`. Never trimmed by the program.
"""
from __future__ import annotations

import json
import os
from pathlib import Path


class Journal:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.last_error: str | None = None

    def record(self, entry: dict) -> bool:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
                f.flush()
                os.fsync(f.fileno())
            self.last_error = None
            return True
        except OSError as exc:
            self.last_error = f"{self.path}: {exc.strerror or exc}"
            return False

    def entries(self) -> list[dict]:
        """Newest first. A damaged line is reported as itself, not skipped silently."""
        if not self.path.is_file():
            return []
        out: list[dict] = []
        for raw in self.path.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(raw))
            except json.JSONDecodeError:
                out.append({"id": None, "outcome": "unreadable", "raw": raw})
        return list(reversed(out))


__all__ = ["Journal"]
```

- [ ] **Step 4: Proposals**

`civ_advisor/copilot/actions.py`:

```python
"""From a name the model chose to an integer the game gave, with the player between.

An ActingOffer exists only for a run started with --allow-actions AND a poll whose tuner
reading carried city ids and item hashes. It builds the `proposal` grammar from THIS
reading -- city names and items the game itself offered, minus anything that needs a
plot -- and maps a validated proposal to the integers the operation renders. A Proposal
is confirmed once, expires when the game turn moves or PROPOSAL_TTL passes, and is
refused if the snapshot it was built on has been superseded.
"""
from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass

from civ_advisor.tuner.base import TunerSnapshot
from civ_advisor.tuner.commands import render

PROPOSAL_TTL = 300.0       # seconds a proposal may wait for its confirmation

WARNING = ("The advisor cannot undo this. It can propose the reverse afterwards, and it "
           "will record what it sent; only a save you made can take the game back.")


@dataclass(frozen=True)
class ActingOffer:
    snapshot: TunerSnapshot

    def _settlements(self):
        return tuple(self.snapshot.build_option_ids) if self.snapshot.available else ()

    def schema(self) -> dict:
        cities = sorted({s.city for s in self._settlements()})
        items = sorted({o.item for s in self._settlements() for o in s.options
                        if not o.requires_placement})
        enum = lambda values: ({"type": "string", "enum": values} if values
                               else {"type": "string", "maxLength": 0})
        return {
            "type": "object",
            "properties": {
                "operation": {"type": "string", "enum": ["set_production"]},
                "city": enum(cities), "item": enum(items),
                "because": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
            },
            "required": ["operation", "city", "item", "because"], "additionalProperties": False,
        }

    def validate(self, data: dict, cited: tuple[str, ...]) -> dict:
        """The proposal with its integers bound, or ValueError naming what was wrong."""
        if data.get("operation") != "set_production":
            raise ValueError(f"{data.get('operation')!r} is not an operation in the catalog")
        city = data.get("city")
        settlement = next((s for s in self._settlements() if s.city == city), None)
        if settlement is None:
            raise ValueError(f"{city!r} is not a settlement in this poll's reading")
        option = settlement.offers(str(data.get("item")))
        if option is None:
            raise ValueError(f"the game did not offer {data.get('item')!r} to {city} this turn")
        if option.requires_placement:
            raise ValueError(f"{option.item} needs a plot; the catalog cannot place it")
        reading = self.snapshot.reading_for("build_options_ids")
        if reading is None:
            raise ValueError("the reading that named these options carries no turn")
        because = tuple(b for b in (data.get("because") or ()) if b in cited)
        return {
            "operation": "set_production", "city": settlement.city, "city_id": settlement.city_id,
            "item": option.item, "item_hash": option.item_hash, "turns": option.turns,
            "turn": reading.turn, "read_at": reading.read_at, "because": list(because),
            "lua": render("set_production", city_id=settlement.city_id,
                          item_hash=option.item_hash),
            "words": f"Set {settlement.city}'s production to {option.item} "
                     f"({option.turns} turns at this poll's estimate)",
            "warning": WARNING,
        }


class Proposals:
    """Pending proposals, each confirmable exactly once."""

    def __init__(self) -> None:
        self._held: dict[str, dict] = {}
        self._lock = threading.Lock()

    def add(self, proposal: dict) -> dict:
        proposal = dict(proposal)
        proposal.setdefault("id", secrets.token_hex(8))
        proposal.setdefault("created", time.monotonic())
        with self._lock:
            self._held[proposal["id"]] = proposal
        return proposal

    def take(self, proposal_id: str, *, turn: int, snapshot_revision: int,
             now: float | None = None) -> dict | None:
        """Remove and return the proposal if it is still valid; None otherwise. Removal
        happens even when it is not valid, so a stale proposal cannot be retried."""
        now = time.monotonic() if now is None else now
        with self._lock:
            held = self._held.pop(proposal_id, None)
        if held is None:
            return None
        if held["turn"] != turn or held["snapshot_revision"] != snapshot_revision:
            return None
        if now - held["created"] > PROPOSAL_TTL:
            return None
        return held


__all__ = ["PROPOSAL_TTL", "WARNING", "ActingOffer", "Proposals"]
```

- [ ] **Step 5: Wire it**

In `civ_advisor/api/app.py`, `create_app` gains `journal_path: Path | None = None` and `acting_port: int = 4318`. Inside: `journal = Journal(journal_path or (base / "<game>" / "actions.jsonl"))` — derive the per-game path the way `store_path_for` does, and re-derive it in `activate()` when the game changes; `proposals = Proposals()`; `save_acknowledged: dict[tuple[str, int], str] = {}` keyed by (session, epoch).

`chat_request` passes `acting=ActingOffer(captured.tuner) if allow_actions and captured.tuner.build_option_ids else None`. When a `ready` answer carries `answer.proposal`, `chat_response` registers it with `proposals.add({**answer.proposal, "snapshot_revision": captured.revision})` and returns the registered dict (with its id) under `answer.proposal`.

```python
    @app.post("/api/copilot/proposals", response_model=None)
    def api_copilot_propose(body: dict = Body(...)):
        """A proposal the PLAYER composed from the reading, without a model. Same
        validation as one the model composed; same confirmation afterwards."""
        if not allow_actions:
            raise HTTPException(status_code=403, detail=_ACTING_OFF)
        captured = current()
        offer = ActingOffer(captured.tuner)
        try:
            made = offer.validate(body, cited=())
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return proposals.add({**made, "snapshot_revision": captured.revision})

    @app.get("/api/copilot/proposals")
    def api_copilot_proposals() -> dict:
        return {"acting": allow_actions, "pending": list(proposals._held.values())}

    @app.get("/api/copilot/journal")
    def api_copilot_journal() -> dict:
        return {"path": str(journal.path), "entries": journal.entries(), "error": journal.last_error}

    @app.post("/api/copilot/act", response_model=None)
    def api_copilot_act(body: dict = Body(...)):
        if not allow_actions:
            raise HTTPException(status_code=403, detail=_ACTING_OFF)
        captured = current()
        now = datetime.now(UTC).isoformat(timespec="seconds")
        sitting = (captured.session, captured.epoch)
        if body.get("save_acknowledged"):
            save_acknowledged.setdefault(sitting, now)
        entry = {"id": str(body.get("proposal_id", "")), "at": now, "session": captured.session,
                 "epoch": captured.epoch, "snapshot_revision": captured.revision,
                 "save_acknowledged_at": save_acknowledged.get(sitting), "outcome": "not_sent",
                 "detail": "", "game_reply": [], "lua": "", "before_hash": None, "after_hash": None,
                 "turn_sent": None}

        def refused(detail: str) -> dict:
            entry["detail"] = detail
            journal.record(entry)
            return {"outcome": "not_sent", "detail": detail, "game_reply": [], "journal": entry}

        if sitting not in save_acknowledged:
            return refused("the first action of a sitting needs you to confirm you have a save "
                           "you would go back to; nothing was sent")
        held = proposals.take(str(body.get("proposal_id", "")), turn=int(body.get("turn", -1)),
                              snapshot_revision=int(body.get("snapshot_revision", -1)))
        if held is None:
            return refused("this proposal is not pending: it was already confirmed, it expired, "
                           "or the turn or snapshot it was built on has moved")
        entry.update({k: held[k] for k in ("operation", "city", "city_id", "item", "item_hash",
                                           "lua", "because", "words")})
        if not journal.record(entry):
            return refused(f"the action journal could not be written ({journal.last_error}), "
                           "so nothing was sent")
        tuner = open_acting_tuner(port=acting_port, timeout=3.0)
        if not getattr(tuner, "available", False):
            return refused(f"the tuner is not answering: {tuner.reason}")
        try:
            outcome = tuner.perform("set_production", city_id=held["city_id"],
                                    item_hash=held["item_hash"])
        finally:
            tuner.close()
        if outcome.reading is not None and outcome.reading.turn != held["turn"]:
            entry.update(outcome="not_sent" if outcome.kind.value == "not_sent" else outcome.kind.value,
                         detail=f"the game answered turn {outcome.reading.turn}; the proposal was "
                                f"built on turn {held['turn']}. " + outcome.detail)
        else:
            entry.update(outcome=outcome.kind.value, detail=outcome.detail)
        entry.update(game_reply=list(outcome.game_reply), before_hash=outcome.before_hash,
                     after_hash=outcome.after_hash,
                     turn_sent=None if outcome.reading is None else outcome.reading.turn)
        journal.record(entry)
        return {"outcome": entry["outcome"], "detail": entry["detail"],
                "game_reply": entry["game_reply"], "before_hash": entry["before_hash"],
                "after_hash": entry["after_hash"], "journal": entry,
                "reverse": (None if outcome.before_hash is None else
                            {"operation": "set_production", "city": held["city"],
                             "item_hash": outcome.before_hash})}
```

with `_ACTING_OFF = ("this run was started without --allow-actions, so the advisor will not send a command into the game; restart with the flag to enable acting")`.

The turn check inside the chunk: the command's Lua already prints the game's turn first (`_TURN_LUA`), and `perform` dates the outcome by it. A proposal is sent as one chunk, so the check above is after the fact and recorded; the *before* check is `proposals.take(turn=...)` against the turn the page sent back, which is the reading's turn from the poll the page is showing. Both are journaled.

In `civ_advisor/cli.py`: `--allow-actions` (`store_true`, help: *"Let the advisor send one confirmed operation at a time into a running Civilization VI through its tuner. Off by default. Every action is journaled under ~/.civ-advisor/<game>/actions.jsonl."*); before `create_app`, if set and `args.host not in {"127.0.0.1", "localhost", "::1"}`, print `--allow-actions needs a loopback --host: acting is confirmed from this machine's own browser and nowhere else.` to stderr and return 2; pass `allow_actions=args.allow_actions`. Add `Acting ON` to the startup line when set.

In `briefing.js`:

```javascript
  /* A proposal card's controls. With acting off there is no confirm button at all --
     the card is an instruction the player carries out by hand -- because a button that
     exists and is merely disabled invites the question of how to enable it mid-run. */
  function proposalControls(proposal, acting) {
    return acting
      ? { confirm: true, note: "Confirming sends exactly the command shown. The advisor cannot undo it." }
      : { confirm: false, note: "Acting is off for this run: carry this out by hand in the game if you agree with it." };
  }
```

In `app.js`: render a proposal card under an answer that carries one (words, the exact Lua in a `<pre>`, the cited evidence via `copilotEvidenceLines`, the current item from `state.briefing.tuner.build_option_ids`/the queue, the warning); a checkbox *I have a save I would go back to* shown until the sitting's first confirmation succeeds; the confirm button per `proposalControls`; after the POST, the outcome with the game's reply verbatim under *The game said*, and a *Propose the reverse* button when `reverse` is present, which POSTs to `/api/copilot/proposals`. Under the conversation, *What the advisor did, and why* from `/api/copilot/journal`, newest first.

- [ ] **Step 6: Run to verify pass, then everything**

Run: `uv run pytest tests/test_copilot_actions.py tests/test_cli.py tests/test_web_briefing.py -v && uv run pytest -q`
Expected: PASS, 11 action tests plus the CLI and briefing additions. Note the fixture the acting tests replay: `FakeGame` replies to every `InGame` command with the same bytes, so `write_set_production.bin`'s `after` hash is what `classify` sees regardless of the item asked for — the test therefore asserts the outcome is one of the three sent outcomes, and the unit tests in Task 10 pin which.

- [ ] **Step 7: Commit**

```bash
git add civ_advisor/copilot/journal.py civ_advisor/copilot/actions.py civ_advisor/copilot/conversation.py \
        civ_advisor/api/app.py civ_advisor/cli.py civ_advisor/web/app.js civ_advisor/web/briefing.js \
        tests/test_copilot_actions.py tests/test_cli.py tests/test_web_briefing.py
git commit -m "Let the player confirm one proposed operation at a time, off by default and journaled first"
```

---

### Task 12: The acting live check, the README, and the ADR

**Files:**
- Create: `tests/live/test_acting_against_a_throwaway_save.py`
- Modify: `tests/live/README.md`
- Modify: `README.md`
- Create: `docs/architecture/adr-003-copilot-grounding-and-acting.md`

If Task 1 recorded B, C or F, the live test is not created, and the README's acting subsection is written in the past tense: what was tried, what the game did, and that the copilot therefore shows the operation it would have performed for the player to carry out by hand.

- [ ] **Step 1: The live acting check, doubly gated**

`tests/live/test_acting_against_a_throwaway_save.py`:

```python
"""Sends ONE command into a running game. Skipped unless the socket is up AND
CIV_ADVISOR_LIVE_ACT=1 is set, so nobody running the read-only live suite writes into
their game by accident. Run it on a save you do not care about.

    CIV_ADVISOR_LIVE_ACT=1 uv run pytest tests/live -p no:cacheprovider -k acting
"""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("CIV_ADVISOR_LIVE_ACT") != "1",
                                reason="set CIV_ADVISOR_LIVE_ACT=1 on a throwaway save to run this")


def test_set_production_and_set_it_back(tuner):
    from civ_advisor.tuner.commands import OutcomeKind, open_acting_tuner

    ids = tuner.build_option_ids()
    assert ids, tuner.reason
    settlement = ids[0]
    choice = next((o for o in settlement.options if not o.requires_placement), None)
    assert choice is not None, "no placeable option offered; pick another save"

    acting = open_acting_tuner()
    try:
        first = acting.perform("set_production", city_id=settlement.city_id,
                               item_hash=choice.item_hash)
        assert first.kind in {OutcomeKind.APPLIED, OutcomeKind.REQUESTED_UNCONFIRMED,
                              OutcomeKind.REJECTED}, first.detail
        assert first.game_reply, "the game printed nothing; the chunk did not run"
        if first.before_hash is not None and first.kind is OutcomeKind.APPLIED:
            back = acting.perform("set_production", city_id=settlement.city_id,
                                  item_hash=first.before_hash)
            assert back.kind is OutcomeKind.APPLIED, back.detail
            assert back.after_hash == first.before_hash
    finally:
        acting.close()
```

Add to `tests/live/README.md` a section *Acting* that says what the test does, that it changes the loaded game, the env var, and the phrase *on a save you do not care about* in bold.

- [ ] **Step 2: The README**

Under **Playing Civilization VI**, after the tuner subsection, add **Ask the advisor anything** and **Letting the advisor act (off by default)**:

- *Ask the advisor anything*: the box on the This turn tab; that the model chooses from a fixed list of questions and never writes a query; that every number in its prose must appear in a fact it cites or the prose is not shown and the evidence itself is; that every answer lists what it could not find and why (no such log, tuner off with the exact cause, no ruleset, no such row); that with `--no-llm` the box becomes buttons; and that Civ VI's ruleset questions now cover rule constants, improvements, policies (slot and unlock only — never the effect), governments and their slot counts, and resources.
- *Letting the advisor act*: `--allow-actions`; that it is off by default and per run; that it needs the tuner on and a loopback `--host`; that the only operation is setting a city's production to something the game itself offered that city this turn; that each proposal shows the exact command, the evidence, and what the city is building now, and that you confirm each one individually; that the advisor cannot undo an action and can only propose the reverse; that the first action of a sitting asks you to confirm you have a save; where the journal is and what it records; the four outcomes and what `requested_unconfirmed` means; **and, plainly, that this sends commands into your running game over the same unauthenticated socket the tuner section already describes, and changes nothing about what that open port exposes to every local process.** Say that this program still never writes a file under either game's directories.

Also update the *Asking about a decision* paragraph: the validation list now includes *every number in the prose must appear in a fact it cited, and a figure only you reported is attributed to you*. Retire the tuner subsection's **One thing is unverified** paragraph: reading the game's turn in the UI VM was verified against a loaded match on 2026-09-13 (`Game.GetCurrentGameTurn()` answered 49 in `InGame`, build options for two cities), so build options are dated by the game's own turn; replace it with one sentence saying so. Leave every statement that WRITING is unverified exactly as it stands unless Task 1 has run.

- [ ] **Step 3: The ADR**

`docs/architecture/adr-003-copilot-grounding-and-acting.md`, in ADR-002's shape: Context (the three player decisions, the unverified write), Decision (named questions not queries; the number rule; the operation catalog and per-action confirmation; off by default; journal before send; acting is not provenance), Consequences (what the number rule will reject that a reader might want; that acting's outcome vocabulary is decided by read-back; that one operation exists and each further one needs its own spike; the spike's recorded outcome and what it ruled out).

- [ ] **Step 4: Verify and commit**

Run: `uv run pytest -q` (offline; the live directory is ignored), then, with a throwaway save loaded and the tuner on: `CIV_ADVISOR_LIVE_ACT=1 uv run pytest tests/live -p no:cacheprovider -k acting`.

```bash
git add tests/live/test_acting_against_a_throwaway_save.py tests/live/README.md README.md
git add -f docs/architecture/adr-003-copilot-grounding-and-acting.md
git commit -m "Say what the copilot can answer, what acting does, and what it cannot undo"
```

---

## Self-review notes

- **Spec coverage:** §4.6 establishing absence → Task 2 (the file) and Task 3 (the bounded retry); §10 isolation → landed as `1e78a2f`, kept honest by Task 2; §4.3 rules 6 and 7 (player figures attributed; typed numbers as claims, disagreements named) → Task 4, with the fallback half in Task 8; §3 interaction → Tasks 8, 9; §4.1 catalog → Tasks 5, 6, 7; §4.2 allowlist growth → Task 6 (every table verified against the installed file on 2026-09-13, and re-verified by the real-file test); §4.3 number rule → Task 4, applied in Tasks 4 and 8; §4.4 sources distinct → `source_phrase` in Task 8 and the badges in Task 9; §4.5 absence kinds → Task 5's `Unanswerable`, exercised in Tasks 5, 6, 7; §5.1–5.8 acting → Tasks 10, 11; §5.7 saving → Task 11's `save_acknowledged`; §6 the spike → Task 1 and the decision gate; §8 honesty when off → Tasks 7, 9, 11; §9 security → the global constraints and Task 11's loopback refusal; §10 testing → each task; §11 scope → one operation, in `COMMANDS`.
- **Type consistency:** `EvidenceFact` is the only fact type; `Absence` is the only absence type; `Resolution`/`Resolved` carry both; `ChatRequest.acting` is `ActingOffer | None` and is the single seam between conversation and acting, so Tasks 8 and 9 compile and pass with acting never built.
- **Contingency:** Tasks 10–12 open by naming the outcome they assume. If Task 1 rules acting out, the deliverable is Tasks 4–9 plus Task 12's README in the past tense, and nothing in those tasks references a module that was not written.
- **Known risks:** Task 10's Lua names `VALUE_EXCLUSIVE`, `CanStartOperation`, `FindID` and `GetCurrentProductionTypeHash`, none verified over the socket before Task 1 runs. Task 1's probe records which of them exist; if the game accepted a different insert mode, the constant in Task 10 is the one the findings document recorded, and the fixture `write_set_production.bin` is its reply. Task 7's parser expects six tab-separated fields from `build_options_ids`; if the spike found `RequiresPlacement` prints differently than `true`/`false`, the parser's comparison follows the capture. Two shipped tests failed while a live game held port 4318; `1e78a2f` isolated them and Task 2 removes the inference they shared with the client.
