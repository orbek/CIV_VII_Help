# Multi-Game Advisor — Phase 3: Civ VI-only Oracle signals — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Feed four Civilization VI logs that Civilization VII has no
equivalent of — `AI_Military.csv`, `DiplomacyModifiers.csv`,
`AI_Research.csv`, `AI_GovtPolicies.csv` — into the **existing** threat and
intel advisors. Every claim they support is the AI's private deliberation,
so every insight and intel event this phase adds is `Provenance.ORACLE`, and
with the Oracle toggle off none of it reaches the server's payload at all.

**Architecture:** Four new readers and four new row types live in one new
ingest module, `civ_advisor/ingest/aiscores.py`, in the same shape as
`ingest/tactical.py`: row dataclass, pinned header, `read_*` function. They
go in `ingest/` rather than `games/civ6/readers.py` because
`games/civ6/readers.py` is for readers that **reshape a Civ VII row type**
into the canonical form, and these four files have no Civ VII counterpart to
reshape — and because `RawLogs` must be able to name its own row types
without importing a game package, which would invert the layering and risk
an import cycle. The `civ6` profile wraps each with `simple()` and declares
it. `RawLogs` and `GameState` each gain four list fields; `build_state`
copies them across. `threat.py` and `intel.py` read them through
`GameState` like every other signal — no parallel Civ VI advisor exists, and
none may be created.

**Tech Stack:** Python 3.12, dataclasses, csv, pytest, FastAPI. No new
dependencies.

**Spec:** `docs/superpowers/specs/2026-09-12-multi-game-advisor-design.md`
(this plan implements §11 phase 3; see §3.3 for the files, §3.2 for the
victory-path question this phase must answer, §6 for the capability guard).

---

## The victory-path question, answered

Spec §3.2 declares `VICTORY_PATHS` unsupported for Civ VI, because
`AI_Victories.csv` records era postures (`STRATEGY_DARKAGE`,
`STRATEGY_CLASSICAL_CHANGES`), not victory conditions, and leaves open
whether `AI_Research`/`AI_GovtPolicies` scoring could support a *different,
honestly-labelled* inference. This plan answers it, and the answer is
binding on every task below.

**Scored tech and civic preferences cannot support any claim about which
victory a rival is pursuing.** Four reasons, each checkable against the
committed fixture:

1. **The score carries no victory label.** `AI_Research.csv` is
   `Game Turn, Player, Action, Tech, Score, Boost, Turns`. There is no
   column naming a victory condition, and no table anywhere in the log set
   that maps a tech to one. Any mapping from `TECH_ARCHERY` to "military
   victory" would be the advisor's own invention presented as the game's
   data — the single thing this project may not do.
2. **The scores are not comparable across turns or players.** In the
   fixture, `TECH_WRITING` is scored 187.5 by nine different players on
   turn 1 and 400.1 by two of them on turn 2. The number is a priority
   within one turn's deliberation over one player's currently-available
   options, not a magnitude that means the same thing twice.
3. **Techs and civics are multi-purpose.** Archery serves defence and
   conquest alike; Writing serves every path in the game. A rival scoring
   military civics highly is a rival scoring military civics highly. It is
   not evidence of a war plan, and certainly not of a victory condition.
4. **The set of options is itself a moving target.** A player scores only
   what is currently available to them, so "highest-scored" means "highest
   among what it can pick this turn" — a rival whose whole tree is
   military-adjacent will look militaristic regardless of intent.

**What the data does support, and the exact words to use.** Two claims, both
descriptive, both quoting the game's own keys:

- **The stated goal.** `AI_Research.csv`'s `Boost` column carries the
  literal value `GOAL` on exactly one row per (turn, player) where the AI
  has selected a research goal, and `RESEARCHING` on the row it is currently
  working. That is a direct statement by the AI, not an inference. Permitted
  wording: *"On turn 2 Cyrus's AI set Writing as its research goal (scored
  400.1 of 17 techs it weighed)."*
- **The ranked preference.** Permitted wording: *"On turn 1 Cyrus's AI
  scored these civics highest: Craftsmanship, Foreign Trade, Military
  Tradition (204.9 each, of 7 weighed)."* The item keys go through
  `humanize()` and are never translated into a path.

**Forbidden, and guarded by a test in Task 7.** The words "victory",
"victory path", "pursuing", "going for", "winning by", and any of
`SCIENCE`/`CULTURAL`/`MILITARY`/`ECONOMIC`/`ESPIONAGE` used as a *path*
label, in any insight or intel event built from these two files.
`GameState.strategies` must stay empty for Civ VI, and
`Capability.VICTORY_PATHS` must stay undeclared. This is the back door the
design has been most careful about; Task 7 nails it shut with an assertion,
not a comment.

---

## Global Constraints

- **TDD.** Failing test first, minimal implementation, verify, commit. Every
  step carries actual code.
- **No pre-existing test assertion may be edited.** Appending new
  assertions to an existing test *function* is also out — append new test
  functions instead. The one exception is
  `tests/test_profile_conformance.py`, where Task 3 appends new `if
  profile.supports(...)` clauses to the existing
  `test_every_declared_capability_is_backed_by_a_declared_reader`; that test
  is a registry of capability→reader pairs and extending its table is what
  it is for. The existing clauses stay byte-identical.
- **Civ VII gains nothing and loses nothing.** It declares none of these
  four files and none of the new capabilities, so every one of its readers,
  insights and payload fields must be unchanged. The existing ~590-test
  suite is the proof; a failure in a `civ7` test means this phase reached
  somewhere it should not have.
- **Every reader calls `latest_game_segment(rows, turn_col=0)`.** Civ VI
  never truncates its logs — they accumulate across every game ever played
  on the machine. Two bugs in this phase-family already shipped from
  forgetting this. A reader without it reads a previous match's rows as this
  match's.
- **Every reader pins its full header with `expect_header`.** Spec §9: a
  header that stops matching must fail loudly with both headers side by
  side.
- **A signal a game lacks is reported unavailable, never zero.** Every new
  field is `T | None`, and absence flows through the capability declaration.
- **Everything this phase adds is `Provenance.ORACLE`.** Not "mostly". A
  derived value with one Oracle contributor is Oracle
  (`decisions/evidence.py:provenance_of`).
- Python `>=3.12`, no new runtime dependencies. `filterwarnings =
  ["error", ...]` is set; a new `DeprecationWarning` fails the suite.
- Read-only with respect to both games' directories.

**Fixture facts the tests must be written against** (verified against
`tests/fixtures/logs_civ6/` on 2026-09-12; the Civ VI state built from it
has `latest_turn=53`, `complete_through_turn=52`, human 0, rivals 1–5
(Robert The Bruce, Cyrus, Dido, Mansa Musa, Kupe), independents 6–14 and
62):

| File | Size in fixture | Turns covered | Row shape |
|---|---|---|---|
| `AI_Military.csv` | full, 833 data rows | **1–53** | uniformly 9 columns |
| `DiplomacyModifiers.csv` | full, 22 data rows | **12–51** | **ragged: 11 / 6 / 5** |
| `AI_Research.csv` | trimmed to 400 lines | **1–2 only** | uniformly 7 columns |
| `AI_GovtPolicies.csv` | trimmed to 400 lines | **1–3 only** | **ragged: 6 / 5** |

The two trimmed files stop far short of `complete_through_turn`. No test may
assert research or policy content at turn 52, and no advisor may require a
current-turn row for them — the intel feed is chronological and an event at
turn 1 is a legitimate member of it.


## Two adjudicated decisions

Both raised by the plan's author and settled before execution.

**1. Combat desire is reported relatively and capped at ADVISE. Approved.**
The author's discomfort is right — a relative reading is weaker than the
warning a player might want — but a threshold is a claim about what a
number means, and nothing here establishes one. The repo has a calibration
tool (`scripts/calibrate_advisor.py`) that derives thresholds from archived
games; there are no archived Civ VI games yet, so there is nothing to
calibrate against. Rank-within-turn plus rise-over-ten-turns says only what
the data shows: this rival's desire is high relative to its peers, and
rising. That is honest and it is useful.

Record in the insight's own wording that no absolute threshold exists, so
a later calibration pass can raise the severity on evidence rather than
someone assuming the cap was arbitrary.

**2. Diplomatic modifiers are reported as standing BETWEEN two players,
not attributed to one. Approved, and it is the more important of the two.**
`DiplomacyModifiers.csv` records an ordered pair but never states which
side holds the opinion. The reading that fits — that Opponent holds it —
is an inference from 22 rows of one capture. Attributing a grievance to
the wrong side would invert the advice: a player told "Cyrus resents you"
plays differently from one told "you resent Cyrus."

So the clunkier phrasing is the correct one. If a later capture with a
known-asymmetric grievance settles the direction, attribute it then and
say what settled it. Twenty-two rows is not that.
---

### Task 1: Read `AI_Military.csv` and `DiplomacyModifiers.csv`

**Files:**
- Create: `civ_advisor/ingest/aiscores.py`
- Test: `tests/test_civ6_aiscores.py`

**Interfaces:**
- Consumes: `civ_advisor.ingest.csvfile` (`read_table`, `expect_header`,
  `latest_game_segment`, `LogFormatError`).
- Produces:
  - `MilitaryRow(turn, player, regional_strength, enemy_strength, other_strength, fav_tech, combat_desire)`
  - `read_military(path: Path) -> list[MilitaryRow]`
  - `DiplomacyModifierRow(turn, player, opponent, modifier, action, value, max_value, accum_amount, accum_turns, cooldown_turns, reduction)`
  - `read_diplomacy_modifiers(path: Path) -> list[DiplomacyModifierRow]`

**Two shapes this file's rows actually have, and why each is handled the way
it is.** `AI_Military.csv`'s `Current Explorers` and `Desired Explorers`
cells are not integers — they read `4:0` and `1:1`. They are kept as raw
strings on no field at all (dropped), because nothing here needs them and
guessing at the colon's meaning would be inventing a signal.
`DiplomacyModifiers.csv` is genuinely ragged: `Activate` rows carry all 11
columns, `Update` rows carry 6 (through `Change` only), `Deactivate` rows
carry 5 (through `Modifier` only). This is the file's real format, not
corruption, so the reader admits exactly those three widths and **raises on
anything else** — the same discipline `read_unit_operations_civ6` applies to
its diagnostic rows.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_civ6_aiscores.py`:

```python
import pytest

from civ_advisor.ingest.aiscores import (
    DiplomacyModifierRow, MilitaryRow, read_diplomacy_modifiers, read_military,
)
from civ_advisor.ingest.csvfile import LogFormatError


def test_military_parses_the_capture(civ6_dir):
    rows = read_military(civ6_dir / "AI_Military.csv")

    assert len(rows) == 833
    assert max(r.turn for r in rows) == 53
    last = [r for r in rows if r.turn == 53]
    assert last == [MilitaryRow(
        turn=53, player=0, regional_strength=65, enemy_strength=135,
        other_strength=20, fav_tech="TECH_ARCHERY", combat_desire=3.5,
    )]


def test_military_reads_combat_desire_for_every_major_on_a_full_turn(civ6_dir):
    rows = read_military(civ6_dir / "AI_Military.csv")
    turn52 = {r.player: r.combat_desire for r in rows if r.turn == 52}

    assert turn52[0] == 4.8
    assert turn52[2] == 1.0
    assert turn52[4] == 0.3


def test_military_rejects_a_changed_header(tmp_path):
    path = tmp_path / "AI_Military.csv"
    path.write_text("Game Turn, Player, Combat Desire\n1, 0, 2.0\n", encoding="utf-8")
    with pytest.raises(LogFormatError, match="AI_Military.csv"):
        read_military(path)


def test_military_reads_only_the_latest_game(tmp_path):
    """Civ VI never truncates this log: without segmenting, a previous match's
    combat desire would be read as this match's."""
    path = tmp_path / "AI_Military.csv"
    header = ("Game Turn, Player, Regional Strength, Enemy Strength, Other Strength, "
              "Current Explorers, Desired Explorers, Fav Tech, Combat Desire\n")
    path.write_text(
        header
        + "80, 0, 10, 10, 10, 1:0, 1:1, TECH_ARCHERY, 99.0\n"
        + "1, 0, 20, 20, 20, 1:0, 1:1, TECH_MINING, 1.0\n"
        + "2, 0, 20, 20, 20, 1:0, 1:1, TECH_MINING, 2.0\n",
        encoding="utf-8",
    )
    rows = read_military(path)

    assert [r.turn for r in rows] == [1, 2]
    assert 99.0 not in [r.combat_desire for r in rows]


def test_modifiers_parse_all_three_row_widths(civ6_dir):
    """Activate rows carry 11 columns, Update 6, Deactivate 5. All three are the
    file's real format; a reader that demanded 11 would drop two thirds of it."""
    rows = read_diplomacy_modifiers(civ6_dir / "DiplomacyModifiers.csv")

    assert len(rows) == 22
    assert {r.action for r in rows} == {"Activate", "Update", "Deactivate"}
    activate = [r for r in rows if r.action == "Activate"]
    update = [r for r in rows if r.action == "Update"]
    deactivate = [r for r in rows if r.action == "Deactivate"]
    assert len(activate) == 12 and len(update) == 6 and len(deactivate) == 4
    assert all(r.value is not None and r.reduction is not None for r in activate)
    assert all(r.value is not None and r.max_value is None for r in update)
    assert all(r.value is None for r in deactivate)


def test_modifiers_keep_the_games_own_wording(civ6_dir):
    rows = read_diplomacy_modifiers(civ6_dir / "DiplomacyModifiers.csv")
    worst = min((r for r in rows if r.value is not None), key=lambda r: r.value)

    assert worst == DiplomacyModifierRow(
        turn=50, player=5, opponent=0,
        modifier="Likes civs who respect the environment", action="Activate",
        value=-8.0, max_value=-8.0, accum_amount=1.0, accum_turns=0,
        cooldown_turns=0, reduction=1.0,
    )


def test_modifiers_raise_on_a_width_the_file_never_has(tmp_path):
    """Admitting 11/6/5 is not the same as admitting anything: an unrecognised
    width is a format change, and quietly dropping it would be data loss."""
    path = tmp_path / "DiplomacyModifiers.csv"
    path.write_text(
        "Game Turn, Player, Opponent, Modifier, Change, Value, Max, Accum Amt, "
        "Accum Turns, Cooldown Turns, Reduction\n"
        "12, 0, 5, First impressions of you, Activate, 2.0, 2.0\n",
        encoding="utf-8",
    )
    with pytest.raises(LogFormatError, match="7"):
        read_diplomacy_modifiers(path)
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_civ6_aiscores.py -q
```

Expected: collection error, `ModuleNotFoundError: No module named
'civ_advisor.ingest.aiscores'`.

- [ ] **Step 3: Write `civ_advisor/ingest/aiscores.py`**

```python
"""Readers for the AI's own scored deliberations.

Every file here is Civilization VI-only and every row is AI-internal: what
the AI wants, what it resents, and what it is weighing. Nothing in this
module is derivable from what a player can see in game, so everything built
from it is Provenance.ORACLE (spec §3.3).

Civ VII has no counterpart to any of these files, which is why they live
here as first-class readers rather than in games/civ6/readers.py -- that
module reshapes Civ VII row types into the canonical form, and there is no
Civ VII row type here to reshape.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .csvfile import LogFormatError, expect_header, latest_game_segment, read_table

MILITARY_HEADER = [
    "Game Turn", "Player", "Regional Strength", "Enemy Strength", "Other Strength",
    "Current Explorers", "Desired Explorers", "Fav Tech", "Combat Desire",
]

MODIFIERS_HEADER = [
    "Game Turn", "Player", "Opponent", "Modifier", "Change", "Value", "Max",
    "Accum Amt", "Accum Turns", "Cooldown Turns", "Reduction",
]


@dataclass(frozen=True)
class MilitaryRow:
    """One player's military posture on one turn, as the AI reads it.

    `combat_desire` is the AI's own appetite for a fight -- a far more direct
    war-intent signal than anything Civ VII exposes, and one the player has no
    way to see. The file's `Current Explorers`/`Desired Explorers` cells are
    colon-pairs ("4:0") whose meaning the logs never state, so they are not
    carried: an unexplained signal is worse than an absent one.
    """

    turn: int
    player: int
    regional_strength: int
    enemy_strength: int
    other_strength: int
    fav_tech: str
    combat_desire: float


def read_military(path: Path) -> list[MilitaryRow]:
    table = read_table(path)
    expect_header(table, MILITARY_HEADER)
    out: list[MilitaryRow] = []
    # Civ VI never truncates this log; see the module docstring in
    # games/civ6/readers.py. Without segmenting, a previous match's combat
    # desire would be reported as this match's.
    for row in latest_game_segment(table.rows, turn_col=0):
        if len(row) != len(MILITARY_HEADER):
            raise LogFormatError(
                f"{path.name}: expected {len(MILITARY_HEADER)} columns but a row "
                f"has {len(row)}: {row!r}"
            )
        out.append(MilitaryRow(
            turn=int(row[0]), player=int(row[1]), regional_strength=int(row[2]),
            enemy_strength=int(row[3]), other_strength=int(row[4]),
            fav_tech=row[7], combat_desire=float(row[8]),
        ))
    return out


# The file's three real row widths. An Activate row carries every column; an
# Update row stops after Change; a Deactivate row stops after Modifier. Any
# other width is a format change and raises.
_MODIFIER_WIDTHS = (11, 6, 5)


@dataclass(frozen=True)
class DiplomacyModifierRow:
    """One entry in the AI's grievance ledger for an ordered player/opponent pair.

    WHAT THIS ROW DOES NOT SAY: which of the two players holds the opinion.
    The `Modifier` text is the game's own second-person wording ("First
    impressions of you", "They dislike civilizations with a small standing
    army"), written from one side's voice, and the file records the pair but
    never labels the direction. The fixture's turn-48 rows appear in both
    orderings for one meeting, so the ordering does not disambiguate it
    either. Callers must therefore report a modifier as standing *between*
    two players, never as one player's opinion of the other.
    """

    turn: int
    player: int
    opponent: int
    modifier: str          # the game's own wording, kept verbatim
    action: str            # Activate | Update | Deactivate
    value: float | None = None
    max_value: float | None = None
    accum_amount: float | None = None
    accum_turns: int | None = None
    cooldown_turns: int | None = None
    reduction: float | None = None


def _opt_float(row: list[str], index: int) -> float | None:
    return float(row[index]) if index < len(row) and row[index] else None


def _opt_int(row: list[str], index: int) -> int | None:
    return int(row[index]) if index < len(row) and row[index] else None


def read_diplomacy_modifiers(path: Path) -> list[DiplomacyModifierRow]:
    table = read_table(path)
    expect_header(table, MODIFIERS_HEADER)
    out: list[DiplomacyModifierRow] = []
    for row in latest_game_segment(table.rows, turn_col=0):
        if len(row) not in _MODIFIER_WIDTHS:
            raise LogFormatError(
                f"{path.name}: a row has {len(row)} columns; this file's rows are "
                f"{_MODIFIER_WIDTHS[0]} (Activate), {_MODIFIER_WIDTHS[1]} (Update) "
                f"or {_MODIFIER_WIDTHS[2]} (Deactivate): {row!r}"
            )
        out.append(DiplomacyModifierRow(
            turn=int(row[0]), player=int(row[1]), opponent=int(row[2]),
            modifier=row[3], action=row[4],
            value=_opt_float(row, 5), max_value=_opt_float(row, 6),
            accum_amount=_opt_float(row, 7), accum_turns=_opt_int(row, 8),
            cooldown_turns=_opt_int(row, 9), reduction=_opt_float(row, 10),
        ))
    return out
```

- [ ] **Step 4: Run the tests**

```bash
uv run pytest tests/test_civ6_aiscores.py -q
```

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add civ_advisor/ingest/aiscores.py tests/test_civ6_aiscores.py
git commit -m "Read Civ VI's combat desire and diplomatic modifier ledger

DiplomacyModifiers.csv is genuinely ragged -- 11 columns for Activate, 6 for
Update, 5 for Deactivate -- so the reader admits exactly those three widths
and raises on any other. The file records the pair a modifier stands between
but never which side holds the opinion, which the row type says out loud."
```

---

### Task 2: Read `AI_Research.csv` and `AI_GovtPolicies.csv`

**Files:**
- Modify: `civ_advisor/ingest/aiscores.py`
- Test: `tests/test_civ6_aiscores.py` (new functions appended)

**Interfaces:**
- Consumes: Task 1's module.
- Produces:
  - `TechScoreRow(turn, player, action, tech, score, boost, turns)` with
    `GOAL = "GOAL"` and `RESEARCHING = "RESEARCHING"` module constants.
  - `read_tech_scores(path: Path) -> list[TechScoreRow]`
  - `PolicyScoreRow(turn, player, action, policy, score, turns)`
  - `read_policy_scores(path: Path) -> list[PolicyScoreRow]`

**The second ragged file.** `AI_GovtPolicies.csv` declares 6 columns, and its
`Civic` rows have 6 — but its `Policies` rows have 5, stopping after `Score`
with no `Turns`. Same rule as Task 1: admit 6 and 5, raise on anything else,
leave `turns` `None` on the short rows rather than zeroing it. A zero there
would read as "available now".

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_civ6_aiscores.py`:

```python
def test_tech_scores_parse_the_trimmed_capture(civ6_dir):
    """The committed AI_Research.csv is trimmed to 400 lines, which covers
    turns 1-2 only. Nothing may assume it reaches complete_through_turn."""
    from civ_advisor.ingest.aiscores import read_tech_scores

    rows = read_tech_scores(civ6_dir / "AI_Research.csv")

    assert len(rows) == 399
    assert sorted({r.turn for r in rows}) == [1, 2]
    assert {r.action for r in rows} == {"Tech"}


def test_tech_scores_carry_the_ais_stated_goal(civ6_dir):
    """`Boost` == GOAL is the AI saying which tech it selected -- a statement,
    not an inference. Exactly one such row per player per turn, where it has one."""
    from civ_advisor.ingest.aiscores import GOAL, read_tech_scores

    rows = read_tech_scores(civ6_dir / "AI_Research.csv")
    goals = [r for r in rows if r.boost == GOAL]

    assert all(r.tech == "TECH_WRITING" for r in goals)
    per_player_turn = [(r.turn, r.player) for r in goals]
    assert len(per_player_turn) == len(set(per_player_turn))
    cyrus = next(r for r in goals if r.turn == 2 and r.player == 2)
    assert cyrus.score == 400.1


def test_tech_score_boost_is_none_when_the_column_is_blank(civ6_dir):
    """352 of the fixture's 399 rows have an empty Boost cell. Empty means the
    AI said nothing about that tech, which is not the same as GOAL or OWNED."""
    from civ_advisor.ingest.aiscores import read_tech_scores

    rows = read_tech_scores(civ6_dir / "AI_Research.csv")

    assert sum(r.boost is None for r in rows) == 352
    assert {r.boost for r in rows if r.boost} == {"GOAL", "OWNED", "RESEARCHING"}


def test_policy_scores_parse_both_row_widths(civ6_dir):
    """Civic rows carry 6 columns, Policies rows 5 -- the Turns column is absent
    on a policy card, and is left None rather than zeroed."""
    from civ_advisor.ingest.aiscores import read_policy_scores

    rows = read_policy_scores(civ6_dir / "AI_GovtPolicies.csv")

    assert len(rows) == 399
    assert sorted({r.turn for r in rows}) == [1, 2, 3]
    civics = [r for r in rows if r.action == "Civic"]
    policies = [r for r in rows if r.action == "Policies"]
    assert len(civics) == 295 and len(policies) == 104
    assert all(r.turns is not None for r in civics)
    assert all(r.turns is None for r in policies)


def test_policy_scores_keep_the_games_own_keys(civ6_dir):
    from civ_advisor.ingest.aiscores import PolicyScoreRow, read_policy_scores

    rows = read_policy_scores(civ6_dir / "AI_GovtPolicies.csv")
    cyrus = [r for r in rows if r.turn == 1 and r.player == 2]

    assert cyrus[0] == PolicyScoreRow(
        turn=1, player=2, action="Civic", policy="CIVIC_CODE_OF_LAWS",
        score=145.2, turns=20,
    )
    assert max(cyrus, key=lambda r: r.score).score == 204.9


def test_policy_scores_read_only_the_latest_game(tmp_path):
    from civ_advisor.ingest.aiscores import read_policy_scores

    path = tmp_path / "AI_GovtPolicies.csv"
    path.write_text(
        "Game Turn, Player, Action, Policy, Score, Turns\n"
        "90, 0, Civic, CIVIC_MYSTICISM, 999.0, 3\n"
        "1, 0, Civic, CIVIC_CODE_OF_LAWS, 10.0, 20\n",
        encoding="utf-8",
    )
    rows = read_policy_scores(path)

    assert [r.turn for r in rows] == [1]


def test_tech_scores_reject_a_changed_header(tmp_path):
    from civ_advisor.ingest.aiscores import read_tech_scores

    path = tmp_path / "AI_Research.csv"
    path.write_text("Game Turn, Player, Tech, Score\n1, 0, TECH_MINING, 5.0\n",
                    encoding="utf-8")
    with pytest.raises(LogFormatError, match="AI_Research.csv"):
        read_tech_scores(path)
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_civ6_aiscores.py -q -k "tech_score or policy_score"
```

Expected: FAIL — `ImportError: cannot import name 'read_tech_scores'`.

- [ ] **Step 3: Append to `civ_advisor/ingest/aiscores.py`**

```python
RESEARCH_HEADER = ["Game Turn", "Player", "Action", "Tech", "Score", "Boost", "Turns"]
POLICIES_HEADER = ["Game Turn", "Player", "Action", "Policy", "Score", "Turns"]

# Values the Boost column takes. GOAL is the AI naming the tech it selected;
# RESEARCHING is the one it is working now. Both are statements the AI made,
# not readings we took.
GOAL = "GOAL"
RESEARCHING = "RESEARCHING"

# Civic rows carry Turns; Policies rows stop after Score.
_POLICY_WIDTHS = (6, 5)


@dataclass(frozen=True)
class TechScoreRow:
    """What one tech was worth to one player's AI on one turn.

    `score` is a priority within THAT turn's deliberation over THAT player's
    currently-available options. It is not comparable across turns or players,
    and it carries no victory-condition label -- see the plan's "victory-path
    question" section. Report what the AI scored; never what it is "going for".
    """

    turn: int
    player: int
    action: str            # "Tech" in every observed row
    tech: str
    score: float
    boost: str | None      # GOAL | RESEARCHING | OWNED | None when the cell is blank
    turns: int | None


def read_tech_scores(path: Path) -> list[TechScoreRow]:
    table = read_table(path)
    expect_header(table, RESEARCH_HEADER)
    out: list[TechScoreRow] = []
    for row in latest_game_segment(table.rows, turn_col=0):
        if len(row) != len(RESEARCH_HEADER):
            raise LogFormatError(
                f"{path.name}: expected {len(RESEARCH_HEADER)} columns but a row "
                f"has {len(row)}: {row!r}"
            )
        out.append(TechScoreRow(
            turn=int(row[0]), player=int(row[1]), action=row[2], tech=row[3],
            score=float(row[4]), boost=row[5] or None, turns=_opt_int(row, 6),
        ))
    return out


@dataclass(frozen=True)
class PolicyScoreRow:
    """What one civic or policy card was worth to one player's AI on one turn.

    Same caveat as TechScoreRow: a score, not a plan.
    """

    turn: int
    player: int
    action: str            # "Civic" | "Policies"
    policy: str
    score: float
    turns: int | None      # absent on Policies rows; None, never 0


def read_policy_scores(path: Path) -> list[PolicyScoreRow]:
    table = read_table(path)
    expect_header(table, POLICIES_HEADER)
    out: list[PolicyScoreRow] = []
    for row in latest_game_segment(table.rows, turn_col=0):
        if len(row) not in _POLICY_WIDTHS:
            raise LogFormatError(
                f"{path.name}: a row has {len(row)} columns; this file's rows are "
                f"{_POLICY_WIDTHS[0]} (Civic) or {_POLICY_WIDTHS[1]} (Policies): {row!r}"
            )
        out.append(PolicyScoreRow(
            turn=int(row[0]), player=int(row[1]), action=row[2], policy=row[3],
            score=float(row[4]), turns=_opt_int(row, 5),
        ))
    return out
```

- [ ] **Step 4: Run the tests**

```bash
uv run pytest tests/test_civ6_aiscores.py -q
```

Expected: 14 passed.

- [ ] **Step 5: Commit**

```bash
git add civ_advisor/ingest/aiscores.py tests/test_civ6_aiscores.py
git commit -m "Read the Civ VI AI's scored tech and civic preferences

A blank Boost cell becomes None, not an empty string: the AI saying nothing
about a tech is not the same as it saying GOAL. Policies rows have no Turns
column and keep it None rather than zeroed, which would read as available now."
```

---

### Task 3: Declare the four files on the `civ6` profile, and carry them into `GameState`

**Files:**
- Modify: `civ_advisor/ingest/load.py` (four new `RawLogs` fields + imports)
- Modify: `civ_advisor/state/models.py` (four new `GameState` fields + imports)
- Modify: `civ_advisor/state/build.py` (copy them across)
- Modify: `civ_advisor/games/base.py` (four new `Capability` members)
- Modify: `civ_advisor/games/civ6/__init__.py` (four `LogReader`s + capabilities)
- Modify: `tests/test_profile_conformance.py` (extend the capability→reader table)
- Test: `tests/test_civ6_state.py` (new functions appended)

**Interfaces:**
- Consumes: Tasks 1–2.
- Produces:
  - `RawLogs.military`, `.diplomacy_modifiers`, `.tech_scores`, `.policy_scores`
  - `GameState.military`, `.diplomacy_modifiers`, `.tech_scores`, `.policy_scores`
  - `Capability.COMBAT_DESIRE`, `.DIPLOMATIC_MODIFIERS`, `.RESEARCH_PREFERENCE`,
    `.POLICY_PREFERENCE`, declared by `civ6` and by no other profile.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_civ6_state.py`:

```python
def test_the_four_oracle_logs_parse_and_reach_the_state(civ6_dir):
    from civ_advisor.games.civ6 import CIV6
    from civ_advisor.ingest.load import load_logs
    from civ_advisor.state.build import build_state

    raw = load_logs(civ6_dir, profile=CIV6)
    for name in ("AI_Military.csv", "DiplomacyModifiers.csv",
                 "AI_Research.csv", "AI_GovtPolicies.csv"):
        status = raw.files[name]
        assert status.ok, f"{name}: {status.error}"
        assert status.rows > 0, f"{name} parsed but is empty"

    state = build_state(raw)
    assert len(state.military) == 833
    assert len(state.diplomacy_modifiers) == 22
    assert len(state.tech_scores) == 399
    assert len(state.policy_scores) == 399


def test_civ6_declares_the_four_new_capabilities(civ6_dir):
    from civ_advisor.games.base import Capability
    from civ_advisor.games.civ6 import CIV6

    assert CIV6.supports(Capability.COMBAT_DESIRE)
    assert CIV6.supports(Capability.DIPLOMATIC_MODIFIERS)
    assert CIV6.supports(Capability.RESEARCH_PREFERENCE)
    assert CIV6.supports(Capability.POLICY_PREFERENCE)


def test_civ7_declares_none_of_them():
    """Civ VII writes none of these four files. A capability declared there
    would promise a panel nothing can fill."""
    from civ_advisor.games.base import Capability
    from civ_advisor.games.civ7 import CIV7

    for capability in (Capability.COMBAT_DESIRE, Capability.DIPLOMATIC_MODIFIERS,
                       Capability.RESEARCH_PREFERENCE, Capability.POLICY_PREFERENCE):
        assert not CIV7.supports(capability)
    for name in ("AI_Military.csv", "DiplomacyModifiers.csv",
                 "AI_Research.csv", "AI_GovtPolicies.csv"):
        assert name not in CIV7.log_files


def test_a_civ7_state_reports_these_signals_as_empty_not_zero(fixture_state):
    """Civ VII has no such logs, so the lists are empty. Nothing downstream may
    turn that into a number -- Task 4 and Task 6 assert the advisors' side."""
    assert fixture_state.military == []
    assert fixture_state.diplomacy_modifiers == []
    assert fixture_state.tech_scores == []
    assert fixture_state.policy_scores == []
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_civ6_state.py -q
```

Expected: FAIL — `AttributeError: 'GameState' object has no attribute
'military'`, and `AttributeError: type object 'Capability' has no attribute
'COMBAT_DESIRE'`.

- [ ] **Step 3: Add the capabilities**

In `civ_advisor/games/base.py`, append to `Capability`, below
`DIPLOMATIC_FAVOR`:

```python
    # Civ VI-only, and all AI-internal: anything built from these is ORACLE.
    COMBAT_DESIRE = "combat_desire"                # AI_Military.csv
    DIPLOMATIC_MODIFIERS = "diplomatic_modifiers"  # DiplomacyModifiers.csv
    RESEARCH_PREFERENCE = "research_preference"    # AI_Research.csv
    POLICY_PREFERENCE = "policy_preference"        # AI_GovtPolicies.csv
```

`capability_report` enumerates `Capability` exhaustively, so the four appear
in the API's capability map for both games automatically — `True` for civ6,
`False` for civ7. That is exactly the "this game does not support X" signal
the UI needs, and it needs no serializer change.

- [ ] **Step 4: Add the `RawLogs` fields**

In `civ_advisor/ingest/load.py`, add to the imports:

```python
from .aiscores import DiplomacyModifierRow, MilitaryRow, PolicyScoreRow, TechScoreRow
```

and add to `RawLogs`, directly above `city_ownership`:

```python
    # Civ VI-only, AI-internal (spec §3.3). Civ VII declares no reader for any of
    # them, so these stay empty for it -- empty because the game has no such
    # concept, which the profile's capability declaration is what actually says.
    military: list[MilitaryRow] = field(default_factory=list)
    diplomacy_modifiers: list[DiplomacyModifierRow] = field(default_factory=list)
    tech_scores: list[TechScoreRow] = field(default_factory=list)
    policy_scores: list[PolicyScoreRow] = field(default_factory=list)
```

- [ ] **Step 5: Add the `GameState` fields and carry them across**

In `civ_advisor/state/models.py`, add to the imports:

```python
from civ_advisor.ingest.aiscores import (
    DiplomacyModifierRow, MilitaryRow, PolicyScoreRow, TechScoreRow,
)
```

and to `GameState`, directly above `peace_turns`:

```python
    military: list[MilitaryRow] = field(default_factory=list)
    diplomacy_modifiers: list[DiplomacyModifierRow] = field(default_factory=list)
    tech_scores: list[TechScoreRow] = field(default_factory=list)
    policy_scores: list[PolicyScoreRow] = field(default_factory=list)
```

In `civ_advisor/state/build.py`, beside the other `state.x = list(raw.x)`
lines:

```python
    state.military = list(raw.military)
    state.diplomacy_modifiers = list(raw.diplomacy_modifiers)
    state.tech_scores = list(raw.tech_scores)
    state.policy_scores = list(raw.policy_scores)
```

- [ ] **Step 6: Declare the readers on the civ6 profile**

In `civ_advisor/games/civ6/__init__.py`, add the import:

```python
from civ_advisor.ingest.aiscores import (
    read_diplomacy_modifiers, read_military, read_policy_scores, read_tech_scores,
)
```

append to `READERS`:

```python
    # Civ VI-only and strictly AI-internal (spec §3.3). Everything built from
    # these four is ORACLE; see advisors/threat.py and advisors/intel.py.
    LogReader("AI_Military.csv", "military", simple(read_military)),
    LogReader("DiplomacyModifiers.csv", "diplomacy_modifiers", simple(read_diplomacy_modifiers)),
    LogReader("AI_Research.csv", "tech_scores", simple(read_tech_scores)),
    LogReader("AI_GovtPolicies.csv", "policy_scores", simple(read_policy_scores)),
```

and extend the capability set — leaving the existing comment block above it
untouched, with this paragraph added to its end:

```python
    # VICTORY_PATHS stays undeclared. AI_Research and AI_GovtPolicies score
    # the AI's tech and civic preferences, and phase 3 answered the question
    # spec §3.2 left open: those scores carry no victory label, are not
    # comparable across turns or players, and name items that serve every
    # path. They support "Cyrus scored these civics highest", and nothing
    # about what Cyrus is pursuing.
    capabilities=frozenset({
        Capability.FAITH,
        Capability.CIVICS,
        Capability.COMBAT_DESIRE,
        Capability.DIPLOMATIC_MODIFIERS,
        Capability.RESEARCH_PREFERENCE,
        Capability.POLICY_PREFERENCE,
    }),
```

- [ ] **Step 7: Extend the conformance table**

`tests/test_profile_conformance.py::test_every_declared_capability_is_backed_by_a_declared_reader`
is the registry that stops the declaration and the code drifting apart, and
a new capability must be entered in it. Leave every existing clause
byte-identical and append, at the end of the function:

```python
    # Phase 3: each of these is one file, and the declaration is a promise
    # that file is read.
    for capability, filename in (
        (Capability.COMBAT_DESIRE, "AI_Military.csv"),
        (Capability.DIPLOMATIC_MODIFIERS, "DiplomacyModifiers.csv"),
        (Capability.RESEARCH_PREFERENCE, "AI_Research.csv"),
        (Capability.POLICY_PREFERENCE, "AI_GovtPolicies.csv"),
    ):
        if profile.supports(capability):
            assert filename in profile.log_files
```

- [ ] **Step 8: Run the full suite**

```bash
uv run pytest -q 2>&1 | tail -3
```

Expected: the phase-2b count **plus 18** (14 from Tasks 1–2, 4 here), zero
failures. Any `civ7` failure means this task reached into Civ VII's path;
stop and report it.

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "Carry Civ VI's four AI-internal logs into the canonical state

Four new capabilities, each backed by exactly one declared reader and
entered in the conformance table. VICTORY_PATHS stays undeclared: scored
tech and civic preferences carry no victory label and support no claim about
what a rival is pursuing."
```

---

### Task 4: Combat desire in the threat advisor

**Files:**
- Modify: `civ_advisor/advisors/threat.py`
- Modify: `civ_advisor/api/serialize.py` (`ORACLE_THREAT_FIELDS`)
- Test: `tests/test_threat_combat_desire.py`, `tests/factories.py`

**Interfaces:**
- Consumes: `GameState.military`.
- Produces:
  - `RivalThreat.combat_desire: float | None`,
    `.combat_desire_turn: int | None`, `.combat_desire_prior: float | None`,
    `.combat_desire_is_highest: bool` (all four new fields appended after
    `latest_combat`, all defaulting so existing construction sites in tests
    keep working).
  - Insight id `threat.combat_desire.<player>`, `Provenance.ORACLE`.
  - `tests/factories.py::military_row(turn, player, combat_desire, **overrides)`.

**Why there is no absolute danger threshold, and what replaces it.** The
turn-52 fixture has combat desire ranging 0.0–4.8 across sixteen players.
One capture cannot establish what value means "war is coming", and inventing
`COMBAT_DESIRE_CRITICAL = 3.0` would be exactly the wiki-figure guessing the
README forbids. Two claims the single log *does* support are used instead:
**rank within the same turn** (every player is scored on the same scale on
the same row set, so "highest among your rivals this turn" is a fact about
the file) and **change over a window** (the same player's own series, so
"risen from 0.3 to 1.0" is a fact about the file). The constants below are
noise floors, not calibrated danger levels, and the insight's `why` says so
in as many words. Severity never exceeds `ADVISE` for this signal — an
uncalibrated reading may not outrank an executed war declaration.

- [ ] **Step 1: Write the failing tests**

Add to `tests/factories.py`:

```python
def military_row(turn: int, player: int, combat_desire: float, **overrides):
    from civ_advisor.ingest.aiscores import MilitaryRow

    return MilitaryRow(**{
        "turn": turn, "player": player, "regional_strength": 50,
        "enemy_strength": 50, "other_strength": 0, "fav_tech": "TECH_ARCHERY",
        "combat_desire": combat_desire, **overrides,
    })
```

Create `tests/test_threat_combat_desire.py`:

```python
import pytest

from civ_advisor.advisors import threat
from civ_advisor.advisors.base import Provenance, Severity
from tests.factories import game_state, military_row


def ids(insights):
    return {i.id: i for i in insights}


def _rising(turn: int, player: int, start: float, end: float):
    """A player's combat desire across the comparison window, start to end."""
    window = threat.COMBAT_DESIRE_TURNS
    return [military_row(turn - window + 1, player, start),
            military_row(turn, player, end)]


def test_no_military_rows_produce_no_insight_and_no_zero():
    """Civ VII logs nothing of the kind. Absence must stay absence."""
    s = game_state(turn=20)
    assert "threat.combat_desire.1" not in ids(threat.advise(s))
    assert threat.summarize(s)[0].combat_desire is None


def test_a_rising_top_ranked_rival_is_advised_and_oracle():
    s = game_state(turn=20, rivals={1: "Rival One", 2: "Rival Two"})
    s.military = (_rising(20, 1, 0.3, 2.5)
                  + [military_row(20, 2, 0.4), military_row(20, 0, 1.0)])
    got = ids(threat.advise(s))["threat.combat_desire.1"]

    assert got.severity is Severity.ADVISE
    assert got.provenance is Provenance.ORACLE
    assert "2.5" in got.why and "0.3" in got.why
    assert "turn 20" in got.why


def test_the_why_refuses_to_call_the_reading_calibrated():
    """The number has no established danger level, and the evidence must say so
    rather than let a reader infer one from the severity."""
    s = game_state(turn=20, rivals={1: "Rival One"})
    s.military = _rising(20, 1, 0.3, 2.5)
    why = ids(threat.advise(s))["threat.combat_desire.1"].why

    assert "relative" in why.lower() or "compared" in why.lower()
    assert "not a calibrated" in why.lower()


def test_a_rival_that_is_not_the_highest_is_reported_as_info():
    s = game_state(turn=20, rivals={1: "Rival One", 2: "Rival Two"})
    s.military = _rising(20, 1, 0.3, 2.5) + [military_row(20, 2, 4.0)]
    got = ids(threat.advise(s))

    assert got["threat.combat_desire.1"].severity is Severity.INFO
    assert "threat.combat_desire.2" not in got  # flat: nothing rose


def test_a_flat_reading_is_not_reported():
    """Reporting an unchanged low number every turn would be noise, and noise is
    what makes a real warning invisible."""
    s = game_state(turn=20, rivals={1: "Rival One"})
    s.military = [military_row(20 - threat.COMBAT_DESIRE_TURNS + 1, 1, 1.0),
                  military_row(20, 1, 1.0)]
    assert "threat.combat_desire.1" not in ids(threat.advise(s))


def test_a_reading_below_the_noise_floor_is_not_reported():
    s = game_state(turn=20, rivals={1: "Rival One"})
    s.military = _rising(20, 1, 0.0, threat.COMBAT_DESIRE_MIN - 0.1)
    assert "threat.combat_desire.1" not in ids(threat.advise(s))


def test_a_stale_reading_is_not_reported_as_current():
    """AI_Military lags the human by up to a turn, like the other AI logs. Older
    than that and the reading is not about now."""
    s = game_state(turn=20, rivals={1: "Rival One"})
    s.military = _rising(15, 1, 0.3, 2.5)
    got = threat.summarize(s)[0]

    assert got.combat_desire is None
    assert "threat.combat_desire.1" not in ids(threat.advise(s))


def test_the_signal_is_real_in_the_civ6_capture(civ6_dir):
    from civ_advisor.games.civ6 import CIV6
    from civ_advisor.ingest.load import load_logs
    from civ_advisor.state.build import build_state

    state = build_state(load_logs(civ6_dir, profile=CIV6))
    by_player = {r.player: r for r in threat.summarize(state)}

    assert by_player[2].combat_desire == 1.0        # Cyrus, turn 52
    assert by_player[2].combat_desire_turn == 52
    assert all(r.provenance is Provenance.ORACLE
               for r in threat.advise(state) if "combat_desire" in r.id)
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_threat_combat_desire.py -q
```

Expected: FAIL — `AttributeError: module 'civ_advisor.advisors.threat' has
no attribute 'COMBAT_DESIRE_TURNS'`.

- [ ] **Step 3: Extend `threat.py`**

Add beside the existing constants:

```python
COMBAT_DESIRE_TURNS = 10     # window the rival's own reading is compared over
COMBAT_DESIRE_MIN = 0.5      # noise floor, not a danger level: below this, say nothing
COMBAT_DESIRE_RISE = 0.5     # rise over the window at/above which the change is worth saying
```

Append to `RivalThreat`, after `latest_combat` — with defaults, so the
existing construction in `_summarize_rival` and in tests stays valid:

```python
    # Civ VI only (AI_Military.csv). None everywhere else: a game that does not
    # log the AI's appetite for a fight has no reading, which is not a zero.
    combat_desire: float | None = None
    combat_desire_turn: int | None = None
    combat_desire_prior: float | None = None          # same rival, COMBAT_DESIRE_TURNS earlier
    combat_desire_is_highest: bool = False            # among rivals on combat_desire_turn
```

Add the helper, below `_army_growth`:

```python
def _combat_desire(state: GameState, rival_id: int) -> tuple[float, int, float | None, bool] | None:
    """The rival's latest combat-desire reading, what it was earlier, and whether it
    leads the field. None when this game logs no such thing at all.

    Only the newest reading at or before the complete turn counts, and only if it is
    no more than one turn stale -- the AI logs lag the human by up to a turn, exactly
    as the DECLARE_WAR scoring above does. `is_highest` compares only rows from the
    SAME turn: the score is a within-turn priority and comparing two turns' numbers
    would be comparing two different scales.
    """
    t = state.complete_through_turn
    rows = [m for m in state.military if m.player == rival_id and m.turn <= t]
    if not rows:
        return None
    latest = max(rows, key=lambda m: m.turn)
    if latest.turn < t - 1:
        return None
    prior = [m for m in rows if m.turn <= latest.turn - COMBAT_DESIRE_TURNS + 1]
    before = max(prior, key=lambda m: m.turn).combat_desire if prior else None
    rival_ids = {p.id for p in state.rivals()}
    same_turn = [m.combat_desire for m in state.military
                 if m.turn == latest.turn and m.player in rival_ids]
    return latest.combat_desire, latest.turn, before, latest.combat_desire >= max(same_turn)
```

Wire it into `_summarize_rival`'s return — computed just above the `return`:

```python
    desire = _combat_desire(state, rival.id)
```

and add to the `RivalThreat(...)` call:

```python
        combat_desire=desire[0] if desire else None,
        combat_desire_turn=desire[1] if desire else None,
        combat_desire_prior=desire[2] if desire else None,
        combat_desire_is_highest=bool(desire and desire[3]),
```

Add the insight in `advise`, immediately after the `threat.war_intent` block
so war intent and combat desire read together:

```python
        if (r.combat_desire is not None and r.combat_desire >= COMBAT_DESIRE_MIN
                and r.combat_desire_prior is not None
                and r.combat_desire - r.combat_desire_prior >= COMBAT_DESIRE_RISE):
            rose = r.combat_desire - r.combat_desire_prior
            out.append(Insight(
                id=f"threat.combat_desire.{r.player}",
                # Never above ADVISE: the scale has no established danger level, so this
                # may not outrank an executed declaration or a scored DECLARE_WAR.
                severity=Severity.ADVISE if r.combat_desire_is_highest else Severity.INFO,
                provenance=Provenance.ORACLE,
                title=f"{r.name}'s appetite for a fight is rising",
                recommendation="Treat this as time to prepare, not as a prediction: garrison "
                               "the border settlement, keep a healthy unit on the approach, "
                               "and check whether a grievance can be defused before it is acted on.",
                why=f"{r.name}'s AI logged a combat desire of {r.combat_desire:.1f} on turn "
                    f"{r.combat_desire_turn}, up {rose:.1f} from {r.combat_desire_prior:.1f} "
                    f"{COMBAT_DESIRE_TURNS} turns earlier"
                    + (", the highest of any rival that turn." if r.combat_desire_is_highest
                       else ", though another rival scored higher.")
                    + " This is read relative to the same turn's other rivals and to this "
                      "rival's own earlier reading — the game publishes no scale for it, so "
                      "it is not a calibrated danger level.",
                **common,
            ))
```

- [ ] **Step 4: Keep the new fields out of the fair-mode payload**

In `civ_advisor/api/serialize.py`, extend `ORACLE_THREAT_FIELDS` — this is a
constant, not a test assertion:

```python
ORACLE_THREAT_FIELDS = ("war_score", "war_score_since", "at_war_since", "target_turn",
                        "city_tiles_targeted", "units_targeted", "target_box",
                        "combat_desire", "combat_desire_turn", "combat_desire_prior",
                        "combat_desire_is_highest")
```

Task 5 extends it again with `grievances`, and Task 7 asserts against the
dataclass that nothing this phase added was missed.

- [ ] **Step 5: Run the suite**

```bash
uv run pytest tests/test_threat_combat_desire.py tests/test_threat.py tests/test_api.py -q
uv run pytest -q 2>&1 | tail -3
```

Expected: 8 new passes, zero failures, no change to any `test_threat.py`
result.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "Feed Civ VI's combat desire into the threat advisor

Reported as rank within the turn and change over a window, which the single
log supports, rather than against an absolute threshold it does not: one
capture cannot establish what 3.5 means, so the insight says the reading is
relative and never rises above ADVISE."
```

---

### Task 5: The diplomatic modifier ledger in the threat advisor

**Files:**
- Modify: `civ_advisor/advisors/threat.py`
- Test: `tests/test_threat_modifiers.py`, `tests/factories.py`

**Interfaces:**
- Consumes: `GameState.diplomacy_modifiers`.
- Produces:
  - `threat.Grievance(turn, modifier, value, pair)` — a frozen dataclass.
  - `RivalThreat.grievances: tuple[Grievance, ...] = ()`, standing negative
    modifiers between the human and this rival, most negative first.
  - Insight id `threat.grievances.<player>`, `Provenance.ORACLE`.
  - `tests/factories.py::modifier_row(turn, player, opponent, modifier, value, action="Activate")`.

**What this insight may and may not say.** The log records a modifier against
an ordered `(Player, Opponent)` pair and the game's own second-person wording
— but never which side holds the opinion. The fixture writes turn 48's
"First impressions of you" in both orderings for a single meeting, so the
ordering does not settle it. The reading that fits best (the row's
`Opponent` holds the opinion about its `Player`) is an inference from
twenty-two rows of one capture, and this advisor does not assert inferences.
So the insight reports a modifier as standing **between** the two players,
quotes the game's wording verbatim, and says in the evidence that the
direction is not recorded. A modifier the player can act on is still
actionable without knowing who holds it.

`Deactivate` rows close a modifier and `Update` rows change its value, so the
ledger folds in turn order per `(player, opponent, modifier)` and keeps only
what is still standing with a negative value. Nothing is summed across
orderings: two directions are two ledgers even when neither can be
attributed.

- [ ] **Step 1: Write the failing tests**

Add to `tests/factories.py`:

```python
def modifier_row(turn: int, player: int, opponent: int, modifier: str,
                 value: float | None = None, action: str = "Activate"):
    from civ_advisor.ingest.aiscores import DiplomacyModifierRow

    return DiplomacyModifierRow(turn=turn, player=player, opponent=opponent,
                                modifier=modifier, action=action, value=value)
```

Create `tests/test_threat_modifiers.py`:

```python
from civ_advisor.advisors import threat
from civ_advisor.advisors.base import Provenance, Severity
from tests.factories import game_state, modifier_row


def ids(insights):
    return {i.id: i for i in insights}


def test_no_modifier_rows_produce_no_grievances():
    s = game_state(turn=20)
    assert threat.summarize(s)[0].grievances == ()
    assert "threat.grievances.1" not in ids(threat.advise(s))


def test_a_standing_negative_modifier_is_reported_verbatim_and_oracle():
    s = game_state(turn=20, rivals={1: "Rival One"})
    s.diplomacy_modifiers = [
        modifier_row(12, 0, 1, "They dislike civilizations with a small standing army", -6.0),
    ]
    got = ids(threat.advise(s))["threat.grievances.1"]

    assert got.provenance is Provenance.ORACLE
    assert got.severity is Severity.ADVISE            # -6.0 is past GRIEVANCE_ADVISE
    assert "They dislike civilizations with a small standing army" in got.why
    assert "-6.0" in got.why
    assert "turn 12" in got.why


def test_the_evidence_refuses_to_attribute_the_opinion_to_a_side():
    """The log records the pair but never which side holds the modifier, and the
    advisor may not fill that in."""
    s = game_state(turn=20, rivals={1: "Rival One"})
    s.diplomacy_modifiers = [modifier_row(12, 0, 1, "Settled near them", -3.0)]
    why = ids(threat.advise(s))["threat.grievances.1"].why

    assert "does not record which side" in why


def test_a_deactivated_modifier_stops_counting():
    s = game_state(turn=20, rivals={1: "Rival One"})
    s.diplomacy_modifiers = [
        modifier_row(12, 0, 1, "Settled near them", -3.0),
        modifier_row(14, 0, 1, "Settled near them", action="Deactivate"),
    ]
    assert threat.summarize(s)[0].grievances == ()


def test_an_update_replaces_the_value_rather_than_adding_to_it():
    s = game_state(turn=20, rivals={1: "Rival One"})
    s.diplomacy_modifiers = [
        modifier_row(12, 0, 1, "First impressions of you", -4.0),
        modifier_row(18, 0, 1, "First impressions of you", -1.0, action="Update"),
    ]
    grievances = threat.summarize(s)[0].grievances

    assert [(g.turn, g.value) for g in grievances] == [(18, -1.0)]


def test_a_modifier_that_updated_to_zero_is_no_longer_a_grievance():
    s = game_state(turn=20, rivals={1: "Rival One"})
    s.diplomacy_modifiers = [
        modifier_row(12, 0, 1, "First impressions of you", -4.0),
        modifier_row(18, 0, 1, "First impressions of you", 0.0, action="Update"),
    ]
    assert threat.summarize(s)[0].grievances == ()


def test_the_two_orderings_stay_separate_ledgers():
    """(0,1) and (1,0) are two ledgers. Merging them would sum two opinions
    neither of which can be attributed."""
    s = game_state(turn=20, rivals={1: "Rival One"})
    s.diplomacy_modifiers = [
        modifier_row(12, 0, 1, "First impressions of you", -4.0),
        modifier_row(12, 1, 0, "First impressions of you", -2.0),
    ]
    grievances = threat.summarize(s)[0].grievances

    assert len(grievances) == 2
    assert {g.pair for g in grievances} == {(0, 1), (1, 0)}


def test_modifiers_not_involving_the_human_are_ignored():
    s = game_state(turn=20, rivals={1: "Rival One", 2: "Rival Two"})
    s.diplomacy_modifiers = [modifier_row(48, 2, 1, "Settled near them", -9.0)]
    got = ids(threat.advise(s))

    assert "threat.grievances.1" not in got
    assert "threat.grievances.2" not in got


def test_a_mild_grievance_is_info_not_advise():
    s = game_state(turn=20, rivals={1: "Rival One"})
    s.diplomacy_modifiers = [modifier_row(12, 0, 1, "First impressions of you", -1.0)]
    assert ids(threat.advise(s))["threat.grievances.1"].severity is Severity.INFO


def test_the_capture_produces_kupes_ledger(civ6_dir):
    from civ_advisor.games.civ6 import CIV6
    from civ_advisor.ingest.load import load_logs
    from civ_advisor.state.build import build_state

    state = build_state(load_logs(civ6_dir, profile=CIV6))
    got = ids(threat.advise(state))["threat.grievances.5"]

    assert got.provenance is Provenance.ORACLE
    assert got.severity is Severity.ADVISE
    assert "Likes civs who respect the environment" in got.why
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_threat_modifiers.py -q
```

Expected: FAIL — `AttributeError: 'RivalThreat' object has no attribute
'grievances'`.

- [ ] **Step 3: Extend `threat.py`**

Add beside the other constants:

```python
GRIEVANCE_ADVISE = -5.0   # a standing modifier at/below this is worth acting on
GRIEVANCE_SHOWN = 3       # how many are quoted in the evidence
```

Add the dataclass, above `RivalThreat`:

```python
@dataclass(frozen=True)
class Grievance:
    """One standing diplomatic modifier between the human and a rival.

    `pair` is the ordered (Player, Opponent) the log filed it under. It is NOT a
    direction: DiplomacyModifiers.csv never records which side holds the opinion,
    and the fixture writes a single meeting in both orderings. Carried so the two
    ledgers stay distinguishable, not so a caller can attribute one.
    """

    turn: int
    modifier: str          # the game's own wording, verbatim
    value: float
    pair: tuple[int, int]
```

Add to `RivalThreat`, after the combat-desire fields:

```python
    grievances: tuple[Grievance, ...] = ()   # standing and negative, most negative first
```

Add the helper below `_combat_desire`:

```python
def _grievances(state: GameState, rival_id: int) -> tuple[Grievance, ...]:
    """Standing negative modifiers between the human and this rival.

    Folded in turn order per (player, opponent, modifier): Activate and Update set
    the value, Deactivate ends it. The two orderings are kept as separate ledgers
    and never summed -- they are two opinions, and the log says which side holds
    neither of them.
    """
    t = state.complete_through_turn
    standing: dict[tuple[int, int, str], Grievance] = {}
    pair = {state.HUMAN, rival_id}
    for row in sorted(state.diplomacy_modifiers, key=lambda r: r.turn):
        if row.turn > t or {row.player, row.opponent} != pair:
            continue
        key = (row.player, row.opponent, row.modifier)
        if row.action == "Deactivate" or row.value is None:
            standing.pop(key, None)
            continue
        standing[key] = Grievance(row.turn, row.modifier, row.value, (row.player, row.opponent))
    return tuple(sorted((g for g in standing.values() if g.value < 0),
                        key=lambda g: (g.value, g.turn, g.modifier)))
```

Set it in `_summarize_rival`'s return:

```python
        grievances=_grievances(state, rival.id),
```

And add the insight in `advise`, after the `threat.combat_desire` block:

```python
        if r.grievances:
            worst = r.grievances[0]
            quoted = "; ".join(
                f'"{g.modifier}" at {g.value:.1f} (turn {g.turn})'
                for g in r.grievances[:GRIEVANCE_SHOWN]
            )
            more = len(r.grievances) - GRIEVANCE_SHOWN
            out.append(Insight(
                id=f"threat.grievances.{r.player}",
                severity=Severity.ADVISE if worst.value <= GRIEVANCE_ADVISE else Severity.INFO,
                provenance=Provenance.ORACLE,
                title=f"Diplomatic friction between you and {r.name}",
                recommendation="The modifiers name what is causing the friction; most can be "
                               "acted on directly — clear the barbarian camps nearby, open a "
                               "trade route, or stop settling toward their border. Do it before "
                               "the grievance is old enough to be acted on.",
                why=f"{len(r.grievances)} standing negative modifier"
                    f"{'s' if len(r.grievances) != 1 else ''} between you and {r.name}: "
                    f"{quoted}" + (f"; and {more} more." if more > 0 else ".")
                    + " DiplomacyModifiers.csv records the pair a modifier stands between "
                      "but does not record which side holds it, so these are not attributed "
                      "to either of you.",
                **common,
            ))
```

- [ ] **Step 4: Keep the ledger out of the fair-mode payload**

`grievances` is a `RivalThreat` field, so without this it would ship in the
fair-mode state payload with the game's own grievance wording intact. In
`civ_advisor/api/serialize.py`, extend the constant Task 4 last touched:

```python
ORACLE_THREAT_FIELDS = ("war_score", "war_score_since", "at_war_since", "target_turn",
                        "city_tiles_targeted", "units_targeted", "target_box",
                        "combat_desire", "combat_desire_turn", "combat_desire_prior",
                        "combat_desire_is_highest", "grievances")
```

Task 7 asserts against the dataclass that no field this phase added was
missed here.

- [ ] **Step 5: Run the suite**

```bash
uv run pytest tests/test_threat_modifiers.py -q
uv run pytest -q 2>&1 | tail -3
```

Expected: 10 new passes, zero failures.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "Feed Civ VI's diplomatic modifier ledger into the threat advisor

Reported as standing between two players rather than as one player's opinion
of the other: the log records the pair and the game's own second-person
wording but never the direction, and the fixture writes one meeting in both
orderings. The evidence says so rather than letting the ordering read as an
attribution."
```

---

### Task 6: Research and policy scores in the intel feed

**Fixture limitation, measured in Task 2.** The committed `AI_Research.csv`
covers only turns 1-2 and `AI_GovtPolicies.csv` only turns 1-3 — both were
trimmed to 400 lines in phase 2a to keep the repo small. So any insight
whose logic depends on a trend, a rise, or a comparison across more than a
couple of turns CANNOT be exercised by this fixture. Either keep the
insights within what two or three turns can demonstrate, or build a
synthetic multi-turn log in `tmp_path` for the trend tests and say in the
report which parts rest on synthetic data rather than a real capture. Do
not write a test that appears to prove a trend over a range the fixture
does not contain.

**Files:**
- Modify: `civ_advisor/advisors/intel.py`
- Test: `tests/test_intel_ai_scores.py`

**Interfaces:**
- Consumes: `GameState.tech_scores`, `.policy_scores`.
- Produces: `IntelEvent`s with `kind="ai_score"`,
  `event_type` in `{"ai_score.research_goal", "ai_score.tech",
  "ai_score.civic", "ai_score.policy"}`, `provenance=Provenance.ORACLE`,
  `source` the originating file. `KIND_ORDER` gains `"ai_score": 4`.

**Why the feed and not an advisor.** `intel.py` says in its own docstring
that it emits no `Insight`s — it is a chronological record of what happened,
each item labelled. A rival's scored preferences are exactly that: something
the AI did on a turn. They belong in the feed. `intel` is deliberately absent
from `ADVISORS`, and this task does not change that.

**Aggregation, and why one event per row is wrong.** The fixture holds 399
research rows over two turns for sixteen players — seventeen techs scored per
player per turn. One event per row would bury the feed. Each (player, turn)
therefore yields at most two events: the **stated goal** when the AI marked
one (`Boost == GOAL`), and the **top-scored items** otherwise. Item keys go
through `humanize()`; scores are quoted as the file gives them.

**Only rivals.** The human's own slot is scored too (player 0 has rows in the
fixture), but reporting the AI's scoring of the human's options as
intelligence about the human is confusing at best. Independents are excluded
for the same reason `_relevant` excludes them. Rivals only.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_intel_ai_scores.py`:

```python
from civ_advisor.advisors import intel
from civ_advisor.advisors.base import Provenance, visible
from civ_advisor.games.civ6 import CIV6
from civ_advisor.ingest.load import load_logs
from civ_advisor.state.build import build_state


def ai_score_events(state):
    return [e for e in intel.feed(state) if e.kind == "ai_score"]


def test_civ7_produces_no_ai_score_events(fixture_state):
    """Civ VII logs no scored preferences. Nothing may appear for it."""
    assert ai_score_events(fixture_state) == []


def test_the_capture_produces_research_and_policy_events(civ6_dir):
    state = build_state(load_logs(civ6_dir, profile=CIV6))
    events = ai_score_events(state)

    assert events
    assert {e.event_type for e in events} <= {
        "ai_score.research_goal", "ai_score.tech", "ai_score.civic", "ai_score.policy",
    }
    assert {e.source for e in events} == {"AI_Research.csv", "AI_GovtPolicies.csv"}


def test_every_ai_score_event_is_oracle(civ6_dir):
    state = build_state(load_logs(civ6_dir, profile=CIV6))

    assert all(e.provenance is Provenance.ORACLE for e in ai_score_events(state))


def test_fair_mode_drops_every_one_of_them(civ6_dir):
    state = build_state(load_logs(civ6_dir, profile=CIV6))
    fair = visible(intel.feed(state), oracle=False)

    assert all(e.kind != "ai_score" for e in fair)


def test_a_stated_research_goal_is_reported_as_the_ais_own_statement(civ6_dir):
    """Boost == GOAL is the AI naming its selection. That is a statement, and may
    be reported as one."""
    state = build_state(load_logs(civ6_dir, profile=CIV6))
    goals = [e for e in ai_score_events(state)
             if e.event_type == "ai_score.research_goal" and 2 in e.players]

    cyrus = next(e for e in goals if e.turn == 2)
    assert "Cyrus" in cyrus.text
    assert "research goal" in cyrus.text
    assert "Writing" in cyrus.text
    assert "400.1" in cyrus.text


def test_top_scored_civics_are_named_not_interpreted(civ6_dir):
    state = build_state(load_logs(civ6_dir, profile=CIV6))
    civics = [e for e in ai_score_events(state)
              if e.event_type == "ai_score.civic" and 2 in e.players and e.turn == 1]

    assert len(civics) == 1
    assert "scored these civics highest" in civics[0].text
    assert "Military Tradition" in civics[0].text
    assert "204.9" in civics[0].text


def test_the_human_and_independents_get_no_events(civ6_dir):
    state = build_state(load_logs(civ6_dir, profile=CIV6))
    rivals = {p.id for p in state.rivals()}

    for e in ai_score_events(state):
        assert set(e.players) <= rivals, f"{e.text} covers a non-rival"


def test_each_player_turn_yields_at_most_one_event_per_family(civ6_dir):
    """399 rows over two turns must not become 399 events."""
    state = build_state(load_logs(civ6_dir, profile=CIV6))
    keys = [(e.turn, e.players, e.event_type) for e in ai_score_events(state)]

    assert len(keys) == len(set(keys))
    assert len(keys) < 60


def test_the_raw_field_keeps_the_games_own_keys(civ6_dir):
    state = build_state(load_logs(civ6_dir, profile=CIV6))
    event = next(e for e in ai_score_events(state) if e.event_type == "ai_score.research_goal")

    assert "TECH_" in event.raw
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_intel_ai_scores.py -q
```

Expected: FAIL — `KeyError: 'ai_score'` from `KIND_ORDER` in `feed`'s sort,
once events start being emitted; before that, an empty-list assertion failure
on the civ6 tests.

- [ ] **Step 3: Extend `intel.py`**

Change the ordering constant — an AI's private deliberation sorts last within
a turn, behind everything that actually happened:

```python
KIND_ORDER = {"combat": 0, "deal": 1, "diplomacy": 2, "gossip": 3, "ai_score": 4}
```

Add beside it:

```python
TOP_SCORED = 3   # how many items a "scored these highest" event names
```

Add the builder, above `feed`:

```python
def _ai_score_events(state: GameState) -> list[IntelEvent]:
    """What each rival's AI was weighing, turn by turn (Civ VI only).

    ORACLE without exception: these are the AI's private deliberations, and no part
    of them is visible to a player in game.

    WHAT THESE EVENTS MAY NOT SAY. A score is a priority within one turn's
    deliberation over one player's currently-available options. It carries no
    victory-condition label, it is not comparable across turns or players, and the
    items it names (Writing, Archery) serve every path in the game. So an event says
    what was scored and what the AI marked as its goal -- never what the rival is
    pursuing, going for, or winning by. See the phase-3 plan's "victory-path
    question"; `GameState.strategies` stays empty for Civ VI and nothing here writes
    to it.

    Each (rival, turn) yields at most one event per family: with seventeen techs
    scored per player per turn, one event per row would bury the feed.
    """
    rivals = {p.id for p in state.rivals()}
    out: list[IntelEvent] = []

    by_turn: dict[tuple[int, int], list] = {}
    goals: dict[tuple[int, int], object] = {}
    for row in state.tech_scores:
        if row.player not in rivals:
            continue
        by_turn.setdefault((row.turn, row.player), []).append(row)
        if row.boost == aiscores.GOAL:
            goals[(row.turn, row.player)] = row

    for (turn, player), rows in sorted(by_turn.items()):
        weighed = len(rows)
        goal = goals.get((turn, player))
        if goal is not None:
            out.append(IntelEvent(
                turn, "ai_score", Provenance.ORACLE,
                f"{_name(state, player)}'s AI set {humanize(goal.tech)} as its research goal "
                f"(scored {goal.score:.1f} of {weighed} techs it weighed)",
                (player,), None, None, "AI_Research.csv",
                raw=f"{goal.tech} score {goal.score} boost {goal.boost}",
                event_type="ai_score.research_goal"))
            continue
        top = sorted(rows, key=lambda r: -r.score)[:TOP_SCORED]
        out.append(IntelEvent(
            turn, "ai_score", Provenance.ORACLE,
            f"{_name(state, player)}'s AI scored these techs highest: "
            + ", ".join(f"{humanize(r.tech)} ({r.score:.1f})" for r in top)
            + f", of {weighed} weighed",
            (player,), None, None, "AI_Research.csv",
            raw=" | ".join(f"{r.tech} {r.score}" for r in top),
            event_type="ai_score.tech"))

    policies: dict[tuple[int, int, str], list] = {}
    for row in state.policy_scores:
        if row.player not in rivals:
            continue
        policies.setdefault((row.turn, row.player, row.action), []).append(row)

    for (turn, player, action), rows in sorted(policies.items()):
        family = "civics" if action == "Civic" else "policy cards"
        top = sorted(rows, key=lambda r: -r.score)[:TOP_SCORED]
        out.append(IntelEvent(
            turn, "ai_score", Provenance.ORACLE,
            f"{_name(state, player)}'s AI scored these {family} highest: "
            + ", ".join(f"{humanize(r.policy)} ({r.score:.1f})" for r in top)
            + f", of {len(rows)} weighed",
            (player,), None, None, "AI_GovtPolicies.csv",
            raw=" | ".join(f"{r.policy} {r.score}" for r in top),
            event_type="ai_score.civic" if action == "Civic" else "ai_score.policy"))
    return out
```

Add the import at the top of `intel.py`:

```python
from civ_advisor.ingest import aiscores
```

and call the builder in `feed`, immediately before the final `sorted(...)`:

```python
    events.extend(_ai_score_events(state))
```

`humanize` strips `LOC_` and one domain prefix, so `TECH_WRITING` and
`CIVIC_MILITARY_TRADITION` come out as "Tech Writing" and "Civic Military
Tradition" — `TECH_` and `CIVIC_` are not in `_DOMAIN_PREFIXES`. Add both to
that tuple in `advisors/base.py`, which is additive and affects no existing
key:

```python
_DOMAIN_PREFIXES = ("GOSSIP_", "DISTRICT_", "UNIT_", "BUILDING_", "IMPROVEMENT_",
                    "WONDER_", "TECH_", "CIVIC_", "POLICY_")
```

- [ ] **Step 4: Run the suite**

```bash
uv run pytest tests/test_intel_ai_scores.py tests/test_intel.py -q
uv run pytest -q 2>&1 | tail -3
```

Expected: 9 new passes, zero failures, `test_intel.py` unchanged. If a
`humanize` test in `tests/test_intel.py` or elsewhere breaks on the new
prefixes, the prefix addition is out of scope — revert it and spell the
strip out locally in `_ai_score_events` instead.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "Put the Civ VI AI's scored preferences into the intel feed

One event per rival per turn per family, not one per row: 399 rows over two
turns would bury everything that actually happened. An event names what was
scored and what the AI marked as its goal, and says nothing about what the
rival is pursuing -- the score carries no victory label."
```

---

### Task 7: Prove the Oracle guard and the victory-path guard

**Files:**
- Test: `tests/test_civ6_oracle_guard.py`

**Interfaces:**
- Consumes: Tasks 3–6.
- Produces: nothing consumed by later tasks; this task adds no production
  code unless a test it writes fails, in which case the fix belongs here.

**Why a dedicated task.** Spec §6 and the product premise require Oracle
material to be **absent from the server's payload**, not hidden in the
browser — a field blanked client-side is a field that shipped. The per-task
tests above assert provenance on the objects; this one asserts it on the
JSON, against the whole Civ VI capture, end to end. It is also where the
victory-path back door gets nailed shut with assertions.

- [ ] **Step 1: Write the tests**

Create `tests/test_civ6_oracle_guard.py`:

```python
import dataclasses
import json

import pytest
from fastapi.testclient import TestClient

from civ_advisor.advisors import intel, run_all
from civ_advisor.advisors.base import Provenance
from civ_advisor.api.app import create_app
from civ_advisor.api.serialize import ORACLE_THREAT_FIELDS, state_to_dict
from civ_advisor.games.civ6 import CIV6
from civ_advisor.games.base import Capability
from civ_advisor.ingest.load import load_logs
from civ_advisor.state.build import build_state

# Every string this phase's Oracle material would put on the wire.
ORACLE_MARKERS = (
    "combat desire", "combat_desire", "standing negative modifier",
    "research goal", "scored these techs", "scored these civics",
    "scored these policy cards", "TECH_", "CIVIC_", "POLICY_",
    "Likes civs who respect the environment",
    "They dislike civilizations with a small standing army",
)

# Vocabulary that would mean the advisor had inferred a victory path from
# scored tech and civic preferences. See the phase-3 plan.
VICTORY_WORDS = ("victory", "pursuing", "going for", "winning by", "victory path")


@pytest.fixture(scope="module")
def civ6_state(civ6_dir):
    return build_state(load_logs(civ6_dir, profile=CIV6))


@pytest.fixture(scope="module")
def civ6_client(civ6_dir):
    with TestClient(create_app(civ6_dir, poll_interval=0.01, profile=CIV6)) as client:
        yield client


def test_every_insight_this_phase_adds_is_oracle(civ6_state):
    added = [i for i in run_all(civ6_state)
             if i.id.startswith(("threat.combat_desire.", "threat.grievances."))]

    assert added, "the capture should produce at least one of each"
    assert all(i.provenance is Provenance.ORACLE for i in added)


def test_fair_mode_insights_payload_carries_none_of_it(civ6_client):
    body = json.dumps(civ6_client.get("/api/insights?oracle=0").json())

    assert "threat.combat_desire" not in body
    assert "threat.grievances" not in body
    for marker in ORACLE_MARKERS:
        assert marker not in body, f"fair-mode insights payload leaked {marker!r}"


def test_fair_mode_intel_payload_carries_none_of_it(civ6_client):
    body = json.dumps(civ6_client.get("/api/intel?oracle=0").json())

    assert "ai_score" not in body
    for marker in ORACLE_MARKERS:
        assert marker not in body, f"fair-mode intel payload leaked {marker!r}"


def test_fair_mode_state_payload_drops_every_new_threat_field(civ6_state):
    """ORACLE_THREAT_FIELDS is hand-maintained, so assert the result rather than
    the list: a field added to RivalThreat and forgotten there would ship."""
    fair = state_to_dict(civ6_state, oracle=False)

    for entry in fair["threats"]:
        for field in ("combat_desire", "combat_desire_turn", "combat_desire_prior",
                      "combat_desire_is_highest", "grievances"):
            assert field not in entry, f"fair-mode state payload leaked {field}"
    assert json.dumps(fair).count("Likes civs who respect") == 0


def test_every_field_this_phase_added_to_rivalthreat_is_suppressed(civ6_state):
    """The complement of the test above, stated against the dataclass rather than a
    hand-written list: every RivalThreat field this phase added is Oracle by
    construction, so forgetting one in ORACLE_THREAT_FIELDS must fail here rather
    than ship."""
    from civ_advisor.advisors import threat

    added = {"combat_desire", "combat_desire_turn", "combat_desire_prior",
             "combat_desire_is_highest", "grievances"}
    assert added <= {f.name for f in dataclasses.fields(threat.RivalThreat)}
    assert added <= set(ORACLE_THREAT_FIELDS)


def test_fair_mode_briefing_payload_carries_none_of_it(civ6_client):
    body = json.dumps(civ6_client.get("/api/briefing?oracle=0").json())

    for marker in ORACLE_MARKERS:
        assert marker not in body, f"fair-mode briefing payload leaked {marker!r}"


def test_oracle_mode_does_show_it(civ6_client):
    """The guard must be a filter, not a deletion: with the toggle on, the
    material is there. A test that only proves absence would pass on a bug that
    dropped the signal entirely."""
    body = json.dumps(civ6_client.get("/api/briefing?oracle=1").json())

    assert "combat desire" in body or "Diplomatic friction" in body


def test_civ6_still_declares_no_victory_paths_and_populates_no_strategies(civ6_state):
    assert not CIV6.supports(Capability.VICTORY_PATHS)
    assert civ6_state.strategies == {}


def test_no_civ6_insight_or_intel_event_infers_a_victory_path(civ6_state):
    """The back door this design has been most careful about: scored tech and
    civic preferences must stay descriptive."""
    text = " ".join(
        [f"{i.title} {i.recommendation} {i.why}" for i in run_all(civ6_state)]
        + [e.text for e in intel.feed(civ6_state)]
    ).lower()

    for word in VICTORY_WORDS:
        assert word not in text, f"a Civ VI claim uses {word!r}"
    for path in ("science victory", "cultural victory", "military victory",
                 "economic victory", "espionage victory"):
        assert path not in text


def test_the_capability_report_tells_the_ui_what_each_game_has(civ6_dir):
    from civ_advisor.api.serialize import capability_report
    from civ_advisor.games.civ7 import CIV7

    six, seven = capability_report(CIV6), capability_report(CIV7)

    assert six[Capability.COMBAT_DESIRE.value] is True
    assert seven[Capability.COMBAT_DESIRE.value] is False
    assert six[Capability.VICTORY_PATHS.value] is False
    # Exhaustive on both sides: the UI must be able to say "not supported",
    # never merely omit.
    assert set(six) == set(seven)
```

- [ ] **Step 2: Run them, and fix production code if any fails**

```bash
uv run pytest tests/test_civ6_oracle_guard.py -q
```

Expected: 11 passed. A failure here is a real leak — fix the serializer or
the advisor, never the assertion. The likely fix sites are
`ORACLE_THREAT_FIELDS` in `civ_advisor/api/serialize.py` (a field added and
not listed) and `visible()`'s call sites (a payload that forgot to filter).

- [ ] **Step 3: Confirm Civ VII is untouched**

```bash
uv run pytest -q -k "not civ6" 2>&1 | tail -3
```

Expected: zero failures. Every Civ VII test predates this phase and none may
have changed behaviour — Civ VII declares none of these four files, so its
advisors see four empty lists and every new branch is skipped.

- [ ] **Step 4: Commit**

```bash
git add tests/test_civ6_oracle_guard.py
git commit -m "Prove the phase-3 Oracle material never reaches a fair-mode payload

Asserted on the served JSON, not on the objects: the spec requires Oracle
fields be absent from the response, and a field blanked in the browser is a
field that shipped. The same file nails the victory-path door shut -- no Civ
VI claim built from scored tech or civic preferences may use victory
vocabulary, and GameState.strategies stays empty."
```

---

### Task 8: Record what phase 3 established

**Files:**
- Modify: `docs/architecture/log-capability-matrix.md`
- Modify: `docs/superpowers/specs/2026-09-12-multi-game-advisor-design.md`
  (§3.2's open question, §11 phase 3, status line)
- Modify: `tests/fixtures/logs_civ6/README.md`

**Interfaces:**
- Consumes: everything above.
- Produces: nothing consumed by later tasks.

- [ ] **Step 1: Close §3.2's open question in the spec**

The last sentence of the `AI_Victories.csv` row currently reads "Whether
`AI_Research`/`AI_GovtPolicies` scoring can support a *different*,
honestly-labelled inference is a phase-3 question, not a parity claim."
Replace it with:

```markdown
**Phase 3 answered this: it cannot.** Those files score the AI's tech and
civic preferences with no victory-condition label, on a scale that is a
within-turn priority over currently-available options and so is not
comparable across turns or players, naming items that serve every path. They
support a descriptive claim — "Cyrus's AI set Writing as its research goal
(scored 400.1 of 17 techs it weighed)", "Cyrus's AI scored these civics
highest" — and nothing about what a rival is pursuing. Victory-path advice
remains unavailable in Civ VI; `GameState.strategies` stays empty for it, and
`tests/test_civ6_oracle_guard.py` asserts that no Civ VI claim uses victory
vocabulary.
```

- [ ] **Step 2: Give the capability matrix its Civ VI-only section**

In `docs/architecture/log-capability-matrix.md`, below the existing Civ VII
content, add:

```markdown
## Civilization VI-only signals (phase 3)

All four are AI-internal and every claim built from them is ORACLE. Civ VII
writes none of these files, declares none of these capabilities, and its
advisors see four empty lists.

| File | Capability | What it supports | What it does NOT support |
|---|---|---|---|
| `AI_Military.csv` | `combat_desire` | The AI's own appetite for a fight, per player per turn. Reported as rank within the turn and change over 10 turns. | An absolute danger level. The game publishes no scale, one capture cannot establish one, and the insight never rises above ADVISE. |
| `DiplomacyModifiers.csv` | `diplomatic_modifiers` | Standing negative modifiers between the human and a rival, quoted in the game's own wording. | Which side holds the opinion. The log records the ordered pair but never the direction, and the capture writes one meeting in both orderings. |
| `AI_Research.csv` | `research_preference` | The AI's stated research goal (`Boost == GOAL`) and its top-scored techs, per turn. | Any victory path. See the design §3.2. |
| `AI_GovtPolicies.csv` | `policy_preference` | Top-scored civics and policy cards, per turn. | Any victory path; also no `GOAL` marker exists in this file at all. |
```

- [ ] **Step 3: Note in the fixture README that four files are now read**

Append to `tests/fixtures/logs_civ6/README.md`:

```markdown
Phase 3 added readers for `AI_Military.csv`, `DiplomacyModifiers.csv`,
`AI_Research.csv` and `AI_GovtPolicies.csv`. The first two are whole. The
last two are the 400-line trims described above, which cover **turns 1–2**
(`AI_Research.csv`) and **turns 1–3** (`AI_GovtPolicies.csv`) — far short of
this capture's `complete_through_turn` of 52. No test may assert research or
policy content at a later turn, and no advisor may require a current-turn
row for either file.
```

- [ ] **Step 4: Mark phase 3 in the spec's status line**

```markdown
**Status:** Phases 1, 2a, 2b and 3 implemented on `feature/multi-game-advisor`; phase 4 not yet planned
```

- [ ] **Step 5: Confirm the whole suite is green one last time**

```bash
uv run pytest -q 2>&1 | tail -3
```

Expected: zero failures, and a pass count higher than the phase-2b baseline
by exactly **56** — 7 (Task 1) + 7 (Task 2) + 4 (Task 3) + 8 (Task 4) +
10 (Task 5) + 9 (Task 6) + 11 (Task 7). The four conformance clauses Task 3
adds fold into an existing parametrised test and add no count. No pre-existing test may
have been deleted or had an assertion changed.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "Record phase 3, and close the victory-path question in the spec

Scored tech and civic preferences cannot support a victory-path claim: no
victory label, no cross-turn or cross-player comparability, and items that
serve every path. They stay descriptive."
```

---

## Done when

- `uv run pytest` is green, with every pre-existing test assertion unmodified.
- `uv run civ-advisor --game civ6` serves combat desire, the grievance ledger
  and the AI's scored preferences with the Oracle toggle on, and none of it
  with the toggle off — verified in the served JSON, not the browser.
- `uv run civ-advisor --game civ7` behaves exactly as it did before this
  phase: no new file read, no new capability declared, no new insight.
- No parallel Civ VI advisor exists. `civ_advisor/advisors/` gained code in
  `threat.py`, `intel.py` and `base.py` only, and every branch it gained is
  guarded on data Civ VII does not have.
- `Capability.VICTORY_PATHS` is still undeclared for `civ6`, and
  `GameState.strategies` is still empty for a Civ VI state.
