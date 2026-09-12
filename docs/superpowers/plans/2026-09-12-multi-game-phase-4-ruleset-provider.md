# Multi-Game Advisor — Phase 4: Civ VI Ruleset Provider — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a Civilization VI recommendation state a building's real cost,
maintenance, prerequisites and flat yields as fact, read from the player's own
installed `DebugGameplay.sqlite`, labelled as a source class of its own — while
making it structurally difficult to surface a conditional or modifier-derived
magnitude as a number, and structurally impossible to label any of it with a
game version.

**Architecture:** A new layer, `civ_advisor/ruleset/`, sits *below* the decision
layer and knows nothing about it. `base.py` holds the neutral contracts: a
`RulesetFigure` that cannot be constructed without naming the table, column and
row it came from; a `RulesetMention` that has no value field at all; a
`RulesetIdentity` that has no version field at all; a `RulesetProvider`
protocol; and `NullRuleset`, the provider that answers "I cannot tell you" to
everything. `civ6.py` implements the protocol over stdlib `sqlite3`, opened
read-only, with a column allowlist as the single query seam. `GameProfile`
gains an optional `ruleset` factory, so the advisor layer reaches a ruleset the
same way it reaches readers and guides: through the profile. `DecisionContext`
gains a `ruleset` field defaulting to `NullRuleset`, which is exactly the
Civ VII behaviour that exists today.

**Tech Stack:** Python 3.12, stdlib `sqlite3`, `hashlib`, dataclasses, pytest.
No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-12-multi-game-advisor-design.md`
(this plan implements §11 phase 4; see §7 for why VI diverges from VII here).
Research: `.superpowers/sdd/civ6-ruleset-research.md` — every table, column and
row value quoted in this plan comes from that report, which was produced by
querying a real installed database read-only.

**Assumptions carried in from phases 2a/2b**, which land in parallel:

- `civ_advisor/games/civ6/__init__.py` exists, defines `CIV6: GameProfile`, and
  is imported by `civ_advisor/games/__init__.py` so registration happens.
- `civ_advisor.games.base.Capability` is a `StrEnum` and
  `GameProfile.capabilities` is a `frozenset[Capability]`. This plan adds one
  member and one optional field; it does not restructure either.
- `profile` is a required argument at `ingest/load.py`, `store.py` and
  `api/app.py` by the time this phase runs. Task 7 threads the ruleset through
  the same call chain and assumes it is there.

If any of those is not true when this phase starts, stop and say so rather than
building the seam a second way.

## Global Constraints

- **The database is the player's file. It is opened read-only and never
  written.** `mode=ro` in the URI, `PRAGMA query_only = 1` on the connection,
  and a test that proves a write attempt raises. No temporary files beside it,
  no `PRAGMA optimize`, no WAL recovery, no `VACUUM`.
- **A figure needs a row.** `RulesetFigure.__post_init__` rejects a figure that
  does not name its table, its column and its row key. There is no code path
  that produces a number without one.
- **Modifier chains never become numbers.** `Modifiers`, `ModifierArguments`,
  `RequirementSets` and `Requirements` are not in the readable allowlist, and
  the one table that *is* reachable from the effect system —
  `BuildingModifiers` — is reachable only through `_count`, which returns a row
  count and never a value. The most a modifier can become is a
  `RulesetMention`, which has no value field.
- **No version, ever.** The database states no game build, no expansion list
  and no mod list (`PRAGMA user_version` is 0; no Version/DLC/Mod/Ruleset table
  exists). `RulesetIdentity` therefore has no version field, its `describe()`
  says only what is establishable — the file, when the game last wrote it, and
  a SHA-256 of its bytes — and Task 8 asserts that no ruleset-sourced fact's
  note contains the word "version".
- **Degrading is the default, not the exception.** Absent file, unreadable
  file, unexpected schema: every one of them yields a `NullRuleset` carrying a
  reason, and the advisor behaves exactly as it does for Civ VII — it asks the
  player. Nothing in this phase may raise out of a recommendation path.
- **No pre-existing test assertion may be edited.** `DecisionContext.ruleset`
  defaults to `NO_RULESET` and `build_context`'s new parameter is keyword-only
  with a default, so every existing call site and every existing assertion
  about Civ VII output stands unchanged. If a task requires editing an existing
  assertion, it has gone out of scope — stop and report it.
- Python `>=3.12`. No new runtime dependencies (`sqlite3` is stdlib).
- `filterwarnings = ["error", ...]` is set in `pyproject.toml`. Note that
  `datetime.utcfromtimestamp` is deprecated in 3.12 and would fail the suite;
  this plan uses `datetime.fromtimestamp(..., tz=timezone.utc)` throughout.
- Adjacency yields, government slot counts, policy effects, and the gold cost
  of a unit upgrade are **out of scope**, each for a reason recorded in the
  research report. Do not add them because they look adjacent.


## Two adjudicated decisions

Both were raised by the plan's author and settled before execution.

**`BuildingModifiers` may be COUNTED, never read. Approved.** Only 79
building types have `Building_YieldChanges` rows, so a building whose
effects are modifier-only would otherwise return an empty yield set — and
an empty yield set renders as "this building yields nothing", which is a
false statement, not a silence. Counting rows lets the advisor say instead
that the building has effects whose magnitude the ruleset does not state.
A count is not a magnitude, and this is the difference between admitting
ignorance and asserting a falsehood, which is the distinction this whole
project turns on.

Two conditions on it. The count may never be rendered where a reader could
take it for a yield figure — it drives a caveat, not a number. And Task 8
must include a test proving a modifier-only building does NOT report "no
yields"; without that test this exception is exactly the hole it was meant
to close.

**The evidence ledger is pre-populated, not filled lazily. Approved.**
Lazy addition is cheaper, but it makes a cited fact's existence depend on
the order things were traversed, so the same decision could show different
evidence on two runs. Evidence in this advisor must exist independently of
whether something happened to cite it. Queries run under 20ms and results
are cached, so the cost is affordable. `ruleset_fact` must therefore be
genuinely idempotent, and Task 1 must test that directly rather than
assuming it — calling it twice with the same key must yield one ledger
entry, not two.

---

### Task 1: The neutral ruleset contracts

The types that make the boundary structural. No SQL and no game in this task —
if the constraint cannot be expressed in `base.py`, it will not hold once there
is a database to query.

**Files:**
- Create: `civ_advisor/ruleset/__init__.py`
- Create: `civ_advisor/ruleset/base.py`
- Test: `tests/test_ruleset_contracts.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `civ_advisor.ruleset.base.RulesetIdentity(path, size, mtime_ns, digest)`,
    frozen, with `short_digest` and `describe()`.
  - `civ_advisor.ruleset.base.RulesetFigure(subject, label, value, unit, table, column, row_key, identity)`, frozen.
  - `civ_advisor.ruleset.base.RulesetMention(subject, label, detail, identity)`, frozen, with `as_unknown()`.
  - `civ_advisor.ruleset.base.BuildingFacts(building, cost, maintenance, prereq_district, prereq_tech, prereq_civic, yields, mentions)`, frozen, with a `figures` property.
  - `civ_advisor.ruleset.base.RulesetProvider`, a runtime-checkable `Protocol`.
  - `civ_advisor.ruleset.base.NullRuleset(reason)`, frozen, and the shared
    instance `NO_RULESET`.
  - `civ_advisor.ruleset.base.RulesetOutOfScope(Exception)`.
- Task 6 extends the protocol, `NullRuleset` and the sqlite provider together
  with `district`, `technology`, `civic` and `unit`. They are deliberately not
  declared here, so nothing can claim to implement a method that has no query
  behind it yet.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ruleset_contracts.py`:

```python
from dataclasses import FrozenInstanceError, fields
from pathlib import Path

import pytest

from civ_advisor.ruleset.base import (
    NO_RULESET, BuildingFacts, NullRuleset, RulesetFigure, RulesetIdentity,
    RulesetMention, RulesetProvider,
)

IDENTITY = RulesetIdentity(path=Path("/games/DebugGameplay.sqlite"), size=18_051_072,
                           mtime_ns=1_757_667_420_000_000_000, digest="ab" * 32)


def _figure(**overrides) -> RulesetFigure:
    row = dict(subject="BUILDING_LIBRARY", label="Library production cost", value=90,
               unit="production", table="Buildings", column="Cost",
               row_key=("BUILDING_LIBRARY",), identity=IDENTITY)
    row.update(overrides)
    return RulesetFigure(**row)


def test_a_figure_must_name_the_row_it_came_from():
    """The structural guard. A number with no table, column and row behind it is an
    assertion, not a figure, and must not be constructible at all."""
    for missing in ({"table": ""}, {"column": ""}, {"row_key": ()}):
        with pytest.raises(ValueError, match="table, column and row"):
            _figure(**missing)


def test_a_mention_has_no_value_to_state():
    """A modifier chain says an effect exists and never says how much. The type it
    becomes must have nowhere to put a magnitude."""
    assert "value" not in {f.name for f in fields(RulesetMention)}
    mention = RulesetMention(subject="BUILDING_GREAT_LIBRARY",
                             label="Great Library has 2 conditional effects",
                             detail="The ruleset records what triggers them.")
    assert "does not state its magnitude" in mention.as_unknown()


def test_identity_carries_no_version_and_claims_none():
    """No table in the database names a game build, an expansion or a mod. The identity
    type must therefore have nowhere to record one, and must not imply one in words."""
    names = {f.name for f in fields(RulesetIdentity)}
    assert names == {"path", "size", "mtime_ns", "digest"}
    described = IDENTITY.describe()
    assert "version" not in described.lower()
    assert IDENTITY.short_digest in described
    assert "DebugGameplay.sqlite" in described


def test_figures_are_immutable():
    with pytest.raises(FrozenInstanceError):
        _figure().value = 1  # type: ignore[misc]


def test_building_facts_collects_only_the_figures_that_exist():
    facts = BuildingFacts(building="BUILDING_LIBRARY", cost=_figure(),
                          maintenance=None, prereq_district=None, prereq_tech=None,
                          prereq_civic=None,
                          yields=(_figure(column="YieldChange", table="Building_YieldChanges",
                                          row_key=("BUILDING_LIBRARY", "YIELD_SCIENCE"),
                                          label="Library science yield", value=2,
                                          unit="per turn"),))
    assert [f.column for f in facts.figures] == ["Cost", "YieldChange"]


def test_the_null_ruleset_answers_nothing_and_says_why():
    null = NullRuleset("no database was found")
    assert isinstance(null, RulesetProvider)
    assert null.available is False
    assert null.reason == "no database was found"
    assert null.identity() is None
    assert null.building("BUILDING_LIBRARY") is None
    assert NO_RULESET.available is False
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_ruleset_contracts.py -q
```

Expected: collection error — `ModuleNotFoundError: No module named 'civ_advisor.ruleset'`.

- [ ] **Step 3: Create the package**

Create `civ_advisor/ruleset/__init__.py`:

```python
"""What the installed game files say, for the games that ship a queryable ruleset.

Below the advisor layer and unaware of it: this package answers "what does the ruleset
say about X" and nothing about the game in progress. Civilization VII has no such source
and gets `NullRuleset`, which is why the advisor's Civ VII behaviour is the fallback
behaviour here rather than a special case.
"""
```

- [ ] **Step 4: Write `base.py`**

Create `civ_advisor/ruleset/base.py`:

```python
"""What a ruleset provider may say, and what it may not.

Three constraints are types rather than intentions:

  - a figure names the table, column and row it was read from, or it cannot be
    constructed. There is no way to produce a number that has no row behind it.
  - a `RulesetMention` has no value field. Conditional effects live in modifier chains
    that record which effect fires under which condition and call the magnitude by a name
    the database never defines; this is what such an effect becomes instead of a number.
  - a `RulesetIdentity` has no version field. The database states no game build, no
    expansion list and no mod list, so what it *can* state — the file, when the game last
    wrote it, and a hash of its bytes — is all there is to record.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol, runtime_checkable


class RulesetOutOfScope(Exception):
    """A query asked for something this provider will not answer from this database.

    Raised, not returned: a caller reaching for a modifier magnitude is a bug in the
    advisor, not a gap in the player's data, and it must fail during tests rather than
    degrade quietly in front of a player.
    """


@dataclass(frozen=True)
class RulesetIdentity:
    """Which ruleset a figure came from, to the extent that is establishable.

    Not a version. `PRAGMA user_version` is unset and no Version, DLC, Mod or Ruleset
    table exists anywhere in the file, so a version number here would be invention. What
    is here is reproducible and falsifiable: another reader with the same file gets the
    same digest, and a mod that rewrites the ruleset changes it.
    """

    path: Path
    size: int
    mtime_ns: int
    digest: str                      # sha256 of the whole file, hex

    @property
    def short_digest(self) -> str:
        return self.digest[:12]

    def describe(self) -> str:
        written = datetime.fromtimestamp(self.mtime_ns / 1e9, tz=timezone.utc)
        return (f"{self.path.name} in your installed game files, last written "
                f"{written:%Y-%m-%d %H:%M} UTC, sha256 {self.short_digest}")


@dataclass(frozen=True)
class RulesetFigure:
    """One value read from one row of the installed ruleset."""

    subject: str                     # the type key this is about, e.g. "BUILDING_LIBRARY"
    label: str                       # what it is, in words
    value: float | int | str
    unit: str | None                 # "production", "gold per turn", "per turn", None
    table: str                       # the table the row came from
    column: str                      # the column the value came from
    row_key: tuple[str, ...]         # the primary key that selects that row
    identity: RulesetIdentity

    def __post_init__(self) -> None:
        if not self.table or not self.column or not self.row_key:
            raise ValueError(
                f"ruleset figure {self.label!r} must name the table, column and row it was "
                "read from; a value with no row behind it is not a figure")


@dataclass(frozen=True)
class RulesetMention:
    """Something the ruleset says exists but does not quantify.

    Has no value field, on purpose. `Modifiers` -> `ModifierArguments` records that an
    effect fires, who it applies to and what triggers it, but its magnitude is defined by
    the game's compiled logic and not by any row. Surfacing "this exists and the ruleset
    does not say how much" is an honest answer; surfacing a number is not.
    """

    subject: str
    label: str
    detail: str

    def as_unknown(self) -> str:
        return f"{self.label}. {self.detail} The installed ruleset does not state its magnitude."


@dataclass(frozen=True)
class BuildingFacts:
    """Every in-scope figure about one building, each carrying its own row."""

    building: str
    cost: RulesetFigure | None = None
    maintenance: RulesetFigure | None = None
    prereq_district: RulesetFigure | None = None
    prereq_tech: RulesetFigure | None = None
    prereq_civic: RulesetFigure | None = None
    yields: tuple[RulesetFigure, ...] = ()
    mentions: tuple[RulesetMention, ...] = ()

    @property
    def figures(self) -> tuple[RulesetFigure, ...]:
        """The stateable figures, in a stable order. Mentions are not here: they are not
        figures and must never be folded into a list of them."""
        named = (self.cost, self.maintenance, self.prereq_district, self.prereq_tech,
                 self.prereq_civic)
        return tuple(f for f in named if f is not None) + self.yields


@runtime_checkable
class RulesetProvider(Protocol):
    """What the advisor may ask an installed ruleset.

    A closed set of questions with typed answers, and no `query(sql)` anywhere: the
    boundary of what may be stated as fact is the boundary of this protocol.
    """

    @property
    def available(self) -> bool: ...

    @property
    def reason(self) -> str | None: ...

    def identity(self) -> RulesetIdentity | None: ...

    def building(self, building_type: str) -> BuildingFacts | None: ...


@dataclass(frozen=True)
class NullRuleset:
    """No ruleset is readable, and here is why.

    The fallback for Civilization VII, which ships no such database, and for a Civ VI
    install whose file is missing, unreadable or shaped differently than expected. Every
    answer is None, which is what makes the advisor fall back to asking the player: a
    provider that guessed would be worse than no provider.
    """

    _reason: str

    @property
    def available(self) -> bool:
        return False

    @property
    def reason(self) -> str | None:
        return self._reason

    def identity(self) -> RulesetIdentity | None:
        return None

    def building(self, building_type: str) -> BuildingFacts | None:
        return None


NO_RULESET = NullRuleset("This game ships no queryable ruleset, so every figure in a "
                         "recommendation comes from your own preview.")


__all__ = ["NO_RULESET", "BuildingFacts", "NullRuleset", "RulesetFigure", "RulesetIdentity",
           "RulesetMention", "RulesetOutOfScope", "RulesetProvider"]
```

Note that `NullRuleset("x")` is constructed positionally in the tests while the
field is named `_reason`; a dataclass accepts that. The leading underscore is
there so `reason` can be the property.

- [ ] **Step 5: Run the tests**

```bash
uv run pytest tests/test_ruleset_contracts.py -q
```

Expected: 6 passed.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "Add the neutral ruleset contracts

A figure cannot be constructed without the row it came from, a mention has
nowhere to put a magnitude, and an identity has nowhere to put a version."
```

---

### Task 2: `SourceKind.INSTALLED_RULESET` and how it is shown

A ruleset figure is neither an advisor threshold nor something the player told
us, and must not be badged as either. It gets its own source kind, and the same
citation plumbing every other fact uses — `source_file` for the database,
`record_key` for the table, column and row.

**Files:**
- Modify: `civ_advisor/decisions/models.py` (`SourceKind`, `EvidenceFact.__post_init__`)
- Modify: `civ_advisor/decisions/evidence.py` (a new builder)
- Modify: `civ_advisor/web/app.js` (`factNode`, the kind label)
- Test: `tests/test_ruleset_evidence.py`

**Interfaces:**
- Consumes: `RulesetFigure`, `RulesetIdentity` from Task 1.
- Produces: `civ_advisor.decisions.models.SourceKind.INSTALLED_RULESET` and
  `civ_advisor.decisions.evidence.ruleset_fact(ledger, figure) -> EvidenceFact`,
  whose id is `ruleset.<table>.<row key joined by dots>.<column>`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ruleset_evidence.py`:

```python
from pathlib import Path

import pytest

from civ_advisor.advisors.base import Provenance
from civ_advisor.decisions.evidence import EvidenceLedger, ruleset_fact
from civ_advisor.decisions.models import EvidenceFact, SourceKind
from civ_advisor.ruleset.base import RulesetFigure, RulesetIdentity

IDENTITY = RulesetIdentity(path=Path("/games/DebugGameplay.sqlite"), size=18_051_072,
                           mtime_ns=1_757_667_420_000_000_000, digest="ab" * 32)
LIBRARY_COST = RulesetFigure(subject="BUILDING_LIBRARY", label="Library production cost",
                             value=90, unit="production", table="Buildings", column="Cost",
                             row_key=("BUILDING_LIBRARY",), identity=IDENTITY)


def test_a_ruleset_figure_becomes_its_own_source_kind():
    """Not an advisor rule and not the player's report: a third thing, which a reader
    must be able to tell apart from both."""
    fact = ruleset_fact(EvidenceLedger(), LIBRARY_COST)

    assert fact.source_kind is SourceKind.INSTALLED_RULESET
    assert fact.provenance is Provenance.FAIR
    assert fact.value == 90 and fact.unit == "production"


def test_a_ruleset_fact_cites_the_row_and_carries_no_turn():
    """It is what the installed files say, not an observation of this game at this turn.
    The citation must lead back to the exact row."""
    fact = ruleset_fact(EvidenceLedger(), LIBRARY_COST)

    assert fact.id == "ruleset.Buildings.BUILDING_LIBRARY.Cost"
    assert fact.source_file == "DebugGameplay.sqlite"
    assert fact.record_key == ("Buildings", "Cost", "BUILDING_LIBRARY")
    assert fact.observed_turn is None


def test_a_ruleset_fact_never_claims_a_version():
    fact = ruleset_fact(EvidenceLedger(), LIBRARY_COST)

    assert fact.note is not None
    assert "version" not in fact.note.lower()
    assert IDENTITY.short_digest in fact.note


def test_adding_the_same_figure_twice_is_not_a_conflict():
    """The context pre-populates the ledger and a candidate cites the same figure again.
    Identical facts must coexist, or citing one would be a race with building it."""
    ledger = EvidenceLedger()

    first, second = ruleset_fact(ledger, LIBRARY_COST), ruleset_fact(ledger, LIBRARY_COST)

    assert first == second and len(ledger.facts) == 1


def test_a_ruleset_fact_must_name_its_source_file():
    with pytest.raises(ValueError, match="must name its source file"):
        EvidenceFact(id="r", label="l", source_kind=SourceKind.INSTALLED_RULESET,
                     provenance=Provenance.FAIR, observed_turn=None, value=1,
                     record_key=("Buildings", "Cost", "BUILDING_LIBRARY"))


def test_the_browser_renders_the_new_kind():
    """A fact whose kind the UI does not know falls through to the word "log", which
    would present the ruleset as something the game wrote this turn."""
    app_js = Path("civ_advisor/web/app.js").read_text(encoding="utf-8")

    assert "installed_ruleset" in app_js
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_ruleset_evidence.py -q
```

Expected: `ImportError: cannot import name 'ruleset_fact'`.

- [ ] **Step 3: Add the source kind**

In `civ_advisor/decisions/models.py`, add to `SourceKind` after `RULE`:

```python
    # A fifth kind. A cost read out of the installed game files is not an observation of
    # this game, not a derivation from one, not this advisor's rule, and not something the
    # player typed in. Badging it as any of those would misstate where the number is
    # checkable: this one is checkable against a file on the player's own disk.
    INSTALLED_RULESET = "installed_ruleset"
```

and add the matching guard to `EvidenceFact.__post_init__`, after the existing
`SourceKind.LOG` check — leave both existing checks exactly as they are:

```python
        if self.source_kind is SourceKind.INSTALLED_RULESET:
            if not self.source_file:
                raise ValueError(f"ruleset fact {self.id} must name its source file")
            if len(self.record_key) < 3:
                raise ValueError(f"ruleset fact {self.id} must cite a table, a column "
                                 "and the row key that selects the row")
```

- [ ] **Step 4: Add the builder**

In `civ_advisor/decisions/evidence.py`, add the import beside the existing ones:

```python
from civ_advisor.ruleset.base import RulesetFigure
```

and a new section immediately before `# ---- defence`:

```python
# ---- the installed ruleset -------------------------------------------------------

def ruleset_fact(ledger: EvidenceLedger, figure: RulesetFigure) -> EvidenceFact:
    """One figure read from the player's installed ruleset, cited to its row.

    Undated on purpose. A ruleset figure is not something that happened on a turn; it is
    what the installed files say, and dating it to the analysis turn would imply the game
    reported it this turn. The one honest "when" — when the game last wrote that file —
    lives in the note, together with the digest that makes the claim checkable.
    """
    return ledger.add(EvidenceFact(
        id=f"ruleset.{figure.table}.{'.'.join(figure.row_key)}.{figure.column}",
        label=figure.label,
        source_kind=SourceKind.INSTALLED_RULESET,
        provenance=Provenance.FAIR,
        observed_turn=None,
        value=figure.value, unit=figure.unit,
        source_file=figure.identity.path.name,
        record_key=(figure.table, figure.column) + figure.row_key,
        subject_id=figure.subject,
        note=(f"Read from {figure.identity.describe()}. That file records no game build, "
              "no expansion list and no mod list, so none is claimed here."),
    ))
```

- [ ] **Step 5: Teach the browser the new kind**

In `civ_advisor/web/app.js`, in `factNode` (around line 1015), replace the kind
label expression:

```javascript
      el("span", "fact-kind", fact.kind === "player_report" ? "you told us"
        : fact.kind === "derived" ? "computed" : fact.kind === "rule" ? "advisor rule"
        : fact.kind === "installed_ruleset" ? "your installed ruleset" : "log"));
```

- [ ] **Step 6: Run the tests and the full suite**

```bash
uv run pytest tests/test_ruleset_evidence.py -q
uv run pytest -q 2>&1 | tail -3
```

Expected: 6 passed, then the whole suite green with no pre-existing test
changed. `evidence_to_dict` already emits `source_kind.value`, so the API needs
no change — confirm that by grepping for the serializer rather than editing it:

```bash
grep -n '"kind": fact.source_kind.value' civ_advisor/api/serialize.py
```

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "Give a ruleset-derived figure its own source class

Distinct from the advisor's own thresholds and from the player's reports, and
cited to the table, column and row it was read from."
```

---

### Task 3: The read-only Civ VI provider, and the query seam

The single place a statement is built. Everything about the boundary is
enforced here, by construction, before any lookup method exists to abuse it.

**Files:**
- Create: `civ_advisor/ruleset/civ6.py`
- Create: `tests/ruleset_fixture.py`
- Test: `tests/test_ruleset_civ6.py`

**Interfaces:**
- Consumes: Task 1's contracts.
- Produces:
  - `civ_advisor.ruleset.civ6.DATABASE_NAME`, `DEFAULT_DATABASE`.
  - `civ_advisor.ruleset.civ6.READABLE_COLUMNS: dict[str, frozenset[str]]` and
    `READABLE_TABLES = frozenset(READABLE_COLUMNS)`.
  - `civ_advisor.ruleset.civ6.COUNTABLE_COLUMNS: dict[str, frozenset[str]]`.
  - `civ_advisor.ruleset.civ6.Civ6Ruleset`, implementing `RulesetProvider`,
    constructed by Task 5's `open_ruleset`. Task 3 constructs it directly in
    tests via `Civ6Ruleset.open(path)`.
  - `tests/ruleset_fixture.py:make_ruleset(tmp_path, **overrides) -> Path`.

- [ ] **Step 1: Write the fixture builder**

The real database is 18 MB of the player's own game files and cannot be
committed. The fixture builds a small one with the real table and column names
and the real row values quoted in the research report, so a test that passes
here is a test that would pass against the real file.

Create `tests/ruleset_fixture.py`:

```python
"""A small stand-in for Civ VI's DebugGameplay.sqlite.

Table and column names, and the Library/Bank/Warrior row values, are taken verbatim from
.superpowers/sdd/civ6-ruleset-research.md, which was produced by querying a real installed
database read-only. A fixture that renamed a column would make the provider's schema check
pass against something the game never writes.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE Buildings (
    BuildingType TEXT NOT NULL PRIMARY KEY, Name TEXT, Cost INTEGER, Maintenance INTEGER,
    PrereqDistrict TEXT, PrereqTech TEXT, PrereqCivic TEXT, Housing INTEGER,
    IsWonder BOOLEAN);
CREATE TABLE Building_YieldChanges (
    BuildingType TEXT NOT NULL, YieldType TEXT NOT NULL, YieldChange INTEGER,
    PRIMARY KEY (BuildingType, YieldType));
CREATE TABLE BuildingModifiers (
    BuildingType TEXT NOT NULL, ModifierId TEXT NOT NULL,
    PRIMARY KEY (BuildingType, ModifierId));
CREATE TABLE Modifiers (ModifierId TEXT NOT NULL PRIMARY KEY, ModifierType TEXT);
CREATE TABLE ModifierArguments (
    ModifierId TEXT NOT NULL, Name TEXT NOT NULL, Value TEXT,
    PRIMARY KEY (ModifierId, Name));
"""

ROWS = {
    "Buildings": [
        ("BUILDING_LIBRARY", "LOC_BUILDING_LIBRARY_NAME", 90, 1,
         "DISTRICT_CAMPUS", "TECH_WRITING", "", 0, 0),
        ("BUILDING_BANK", "LOC_BUILDING_BANK_NAME", 220, 2,
         "DISTRICT_COMMERCIAL_HUB", "TECH_BANKING", "", 0, 0),
        ("BUILDING_GREAT_LIBRARY", "LOC_BUILDING_GREAT_LIBRARY_NAME", 400, 0,
         "DISTRICT_CAMPUS", "TECH_RECORDED_HISTORY", "", 0, 1),
    ],
    "Building_YieldChanges": [
        ("BUILDING_LIBRARY", "YIELD_SCIENCE", 2),
        ("BUILDING_BANK", "YIELD_GOLD", 5),
    ],
    "BuildingModifiers": [
        ("BUILDING_GREAT_LIBRARY", "GREATLIBRARY_BOOST_SCIENTIST"),
    ],
    "Modifiers": [
        ("GREATLIBRARY_BOOST_SCIENTIST", "MODIFIER_PLAYER_GRANT_BOOST_WITH_GREAT_PERSON"),
    ],
    "ModifierArguments": [
        ("GREATLIBRARY_BOOST_SCIENTIST", "GreatPersonClass", "GREAT_PERSON_CLASS_SCIENTIST"),
        ("GREATLIBRARY_BOOST_SCIENTIST", "OtherPlayers", "1"),
        # The magnitude the database does not state: `1` is a flag meaning "apply the
        # standard tech boost", not a quantity of science. A test in Task 8 proves this
        # never reaches a player as a number.
        ("GREATLIBRARY_BOOST_SCIENTIST", "TechBoost", "1"),
    ],
}


def make_ruleset(tmp_path: Path, name: str = "DebugGameplay.sqlite",
                 rows: dict[str, list[tuple]] | None = None,
                 schema: str | None = None) -> Path:
    """Write a throwaway ruleset database and return its path.

    `rows` replaces whole tables, so a test can drop a column's value or a whole table to
    exercise degradation without editing this module.

    `schema` is resolved here rather than as a default argument, because Task 6 appends to
    `SCHEMA` after this function is defined and a default would have captured the old one.
    """
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / name
    schema = SCHEMA if schema is None else schema
    table_rows = {**ROWS, **(rows or {})}
    connection = sqlite3.connect(path)
    try:
        connection.executescript(schema)
        for table, values in table_rows.items():
            if not values:
                continue
            placeholders = ", ".join("?" * len(values[0]))
            connection.executemany(f"INSERT INTO {table} VALUES ({placeholders})", values)
        connection.commit()
    finally:
        connection.close()
    return path
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_ruleset_civ6.py`:

```python
import sqlite3

import pytest

from civ_advisor.ruleset.base import RulesetOutOfScope, RulesetProvider
from civ_advisor.ruleset.civ6 import COUNTABLE_COLUMNS, READABLE_TABLES, Civ6Ruleset

from tests.ruleset_fixture import make_ruleset


@pytest.fixture
def ruleset(tmp_path):
    provider = Civ6Ruleset.open(make_ruleset(tmp_path))
    yield provider
    provider.close()


def test_a_building_states_its_real_cost_prereqs_and_flat_yield(ruleset):
    """The figures the research report verified against a real install: Library costs 90
    production and 1 gold, needs a Campus and Writing, and yields a flat +2 science."""
    facts = ruleset.building("BUILDING_LIBRARY")

    assert facts is not None
    assert (facts.cost.value, facts.cost.unit) == (90, "production")
    assert (facts.maintenance.value, facts.maintenance.unit) == (1, "gold per turn")
    assert facts.prereq_district.value == "DISTRICT_CAMPUS"
    assert facts.prereq_tech.value == "TECH_WRITING"
    assert facts.prereq_civic is None          # empty in the row, so absent, not ""
    assert [(f.value, f.label) for f in facts.yields] == [(2, "Library science yield")]


def test_every_figure_carries_the_row_that_produced_it(ruleset):
    facts = ruleset.building("BUILDING_LIBRARY")

    assert (facts.cost.table, facts.cost.column) == ("Buildings", "Cost")
    assert facts.cost.row_key == ("BUILDING_LIBRARY",)
    science = facts.yields[0]
    assert (science.table, science.column) == ("Building_YieldChanges", "YieldChange")
    assert science.row_key == ("BUILDING_LIBRARY", "YIELD_SCIENCE")


def test_a_building_the_ruleset_does_not_have_is_absent_not_empty(ruleset):
    assert ruleset.building("BUILDING_NOT_A_BUILDING") is None


def test_the_provider_satisfies_the_protocol_and_names_its_identity(ruleset):
    assert isinstance(ruleset, RulesetProvider)
    assert ruleset.available is True and ruleset.reason is None
    assert ruleset.identity().path.name == "DebugGameplay.sqlite"


def test_the_modifier_tables_are_not_readable(ruleset):
    """The whole point of the allowlist. These tables wire up an effect and never state
    its magnitude; reading one would be inference wearing a citation."""
    for table in ("Modifiers", "ModifierArguments"):
        with pytest.raises(RulesetOutOfScope, match=table):
            ruleset._select(table, ("ModifierId",), {})
        assert table not in READABLE_TABLES


def test_a_readable_table_still_refuses_an_unlisted_column(ruleset):
    with pytest.raises(RulesetOutOfScope, match="Housing"):
        ruleset._select("Buildings", ("Housing",), {"BuildingType": "BUILDING_LIBRARY"})


def test_building_modifiers_may_be_counted_but_never_read(ruleset):
    """Counting is how "this building does something the ruleset does not quantify" is
    established. A count is not a magnitude, and the value columns stay unreachable."""
    assert ruleset._count("BuildingModifiers", {"BuildingType": "BUILDING_GREAT_LIBRARY"}) == 1
    assert COUNTABLE_COLUMNS["BuildingModifiers"] == frozenset({"BuildingType"})
    with pytest.raises(RulesetOutOfScope):
        ruleset._select("BuildingModifiers", ("ModifierId",), {})
    with pytest.raises(RulesetOutOfScope):
        ruleset._count("Modifiers", {"ModifierId": "GREATLIBRARY_BOOST_SCIENTIST"})


def test_the_database_is_opened_read_only(ruleset):
    """It is the player's own game file. Two locks, because one of them being right is
    not something to find out in production."""
    with pytest.raises(sqlite3.OperationalError, match="readonly|read-only"):
        ruleset._connection.execute("UPDATE Buildings SET Cost = 1")
```

- [ ] **Step 3: Run the tests to verify they fail**

```bash
uv run pytest tests/test_ruleset_civ6.py -q
```

Expected: `ModuleNotFoundError: No module named 'civ_advisor.ruleset.civ6'`.

- [ ] **Step 4: Write the provider**

Create `civ_advisor/ruleset/civ6.py`:

```python
"""The installed Civilization VI ruleset, read from the game's own cache database.

`Cache/DebugGameplay.sqlite` is written by the game and holds the compiled ruleset: what
a building costs, what it needs, what it yields. That makes VI the one game here where a
figure in a recommendation can be stated as fact rather than asked for — see §7 of the
design spec for why that is a capability divergence and not a parity gap.

What this module will *not* read is as deliberate as what it reads. The effect system
(`Modifiers` -> `ModifierArguments`) records that an effect fires, who it applies to and
what triggers it, while its magnitude is defined by the game's compiled logic and by no
row anywhere. `READABLE_COLUMNS` is the allowlist of plain indexed columns; `_select` is
the only place a statement is built, and it refuses anything outside it. `BuildingModifiers`
is reachable only through `_count`, which returns a row count and never a value, so the
most an effect can become is a `RulesetMention`.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from .base import (
    BuildingFacts, RulesetFigure, RulesetIdentity, RulesetMention, RulesetOutOfScope,
)

DATABASE_NAME = "DebugGameplay.sqlite"
DEFAULT_DATABASE = (Path.home() / "Library" / "Application Support"
                    / "Sid Meier's Civilization VI" / "Firaxis Games"
                    / "Sid Meier's Civilization VI" / "Cache" / DATABASE_NAME)

# The only columns this provider may read, by table. Every one is a plain indexed value
# that *is* the figure — not a key into an effect the database does not describe. The keys
# of this mapping are also the table allowlist, so there is one list to keep honest rather
# than two that can drift apart.
#
# Adding an entry here is not a small change. See
# docs/architecture/adr-002-ruleset-derived-figures.md before you do.
READABLE_COLUMNS: dict[str, frozenset[str]] = {
    "Buildings": frozenset({"BuildingType", "Cost", "Maintenance", "PrereqDistrict",
                            "PrereqTech", "PrereqCivic"}),
    "Building_YieldChanges": frozenset({"BuildingType", "YieldType", "YieldChange"}),
}

READABLE_TABLES = frozenset(READABLE_COLUMNS)

# Tables that may be counted and never read. A row in one of these establishes that an
# effect exists; only `_count` can reach them, and a count cannot be mistaken for a
# magnitude. The value is the set of columns a count may filter on.
COUNTABLE_COLUMNS: dict[str, frozenset[str]] = {
    "BuildingModifiers": frozenset({"BuildingType"}),
}

# Named only to give a precise refusal. Enforcement is the allowlist above, not this set:
# a table missing from both is refused just as firmly.
EFFECT_TABLES = frozenset({"Modifiers", "ModifierArguments", "DynamicModifiers",
                           "RequirementSets", "Requirements", "RequirementArguments",
                           "PolicyModifiers", "GovernmentModifiers", "TraitModifiers"})


def _title(type_key: str) -> str:
    """`BUILDING_LIBRARY` -> `Library`. A display convenience; every figure stays keyed on
    the type key, and no decision is made by matching on the pretty name."""
    return type_key.split("_", 1)[-1].replace("_", " ").title()


def _yield_label(yield_type: str) -> str:
    return yield_type.removeprefix("YIELD_").replace("_", " ").lower()


@dataclass
class Civ6Ruleset:
    """One open, read-only view of one ruleset database.

    Constructed by `open_ruleset` (Task 5), which owns the caching and the degradation.
    Constructing one directly opens a connection that the caller must `close()`.
    """

    _identity: RulesetIdentity
    _connection: sqlite3.Connection
    _countable: frozenset[str] = frozenset()
    _cache: dict[tuple[str, str], object] = field(default_factory=dict, repr=False)

    @property
    def available(self) -> bool:
        return True

    @property
    def reason(self) -> str | None:
        return None

    def identity(self) -> RulesetIdentity | None:
        return self._identity

    def close(self) -> None:
        self._connection.close()

    # -- the query seam ------------------------------------------------------------

    def _select(self, table: str, columns: Sequence[str],
                where: dict[str, str]) -> list[sqlite3.Row]:
        """The only place this module builds a statement.

        Table and column names cannot be bound as parameters, so they are checked against
        the allowlist instead of interpolated on trust — which makes the allowlist both the
        injection guard and the scope guard. Values are always bound.
        """
        allowed = READABLE_COLUMNS.get(table)
        if allowed is None:
            detail = (" It records that an effect exists without stating its magnitude."
                      if table in EFFECT_TABLES else "")
            raise RulesetOutOfScope(f"{table} is not a readable ruleset table.{detail}")
        unlisted = sorted((set(columns) | set(where)) - allowed)
        if unlisted:
            raise RulesetOutOfScope(
                f"{', '.join(unlisted)} is not a readable column of {table}")
        sql = f"SELECT {', '.join(columns)} FROM {table}"
        if where:
            sql += " WHERE " + " AND ".join(f"{column} = ?" for column in where)
        return self._connection.execute(sql, tuple(where.values())).fetchall()

    def _count(self, table: str, where: dict[str, str]) -> int:
        """How many rows exist, for the tables where existence is all that may be said.

        Returns an `int` and nothing else on purpose: there is no shape of this method's
        result that a magnitude could be smuggled through.
        """
        allowed = COUNTABLE_COLUMNS.get(table)
        if allowed is None:
            raise RulesetOutOfScope(f"{table} may not be counted")
        unlisted = sorted(set(where) - allowed)
        if unlisted:
            raise RulesetOutOfScope(f"{', '.join(unlisted)} is not a key column of {table}")
        sql = (f"SELECT count(*) FROM {table} WHERE "
               + " AND ".join(f"{column} = ?" for column in where))
        return int(self._connection.execute(sql, tuple(where.values())).fetchone()[0])

    # -- lookups -------------------------------------------------------------------

    def building(self, building_type: str) -> BuildingFacts | None:
        cached = self._cache.get(("building", building_type))
        if cached is not None:
            return cached  # type: ignore[return-value]
        rows = self._select("Buildings",
                            ("Cost", "Maintenance", "PrereqDistrict", "PrereqTech",
                             "PrereqCivic"),
                            {"BuildingType": building_type})
        if not rows:
            return None
        row, name = rows[0], _title(building_type)

        def figure(column: str, label: str, unit: str | None) -> RulesetFigure | None:
            value = row[column]
            # An empty prerequisite column means "none", and a missing one means the row
            # does not say. Both are absence: neither may become the number 0 or the
            # string "" in front of a player.
            if value is None or value == "":
                return None
            return RulesetFigure(subject=building_type, label=label, value=value, unit=unit,
                                 table="Buildings", column=column,
                                 row_key=(building_type,), identity=self._identity)

        yields = tuple(
            RulesetFigure(
                subject=building_type,
                label=f"{name} {_yield_label(y['YieldType'])} yield",
                value=y["YieldChange"], unit="per turn",
                table="Building_YieldChanges", column="YieldChange",
                row_key=(building_type, y["YieldType"]), identity=self._identity)
            for y in self._select("Building_YieldChanges",
                                  ("YieldType", "YieldChange"),
                                  {"BuildingType": building_type}))

        facts = BuildingFacts(
            building=building_type,
            cost=figure("Cost", f"{name} production cost", "production"),
            maintenance=figure("Maintenance", f"{name} maintenance", "gold per turn"),
            prereq_district=figure("PrereqDistrict", f"{name} requires district", None),
            prereq_tech=figure("PrereqTech", f"{name} requires technology", None),
            prereq_civic=figure("PrereqCivic", f"{name} requires civic", None),
            yields=yields,
            mentions=self._effect_mentions(building_type, bool(yields)),
        )
        self._cache[("building", building_type)] = facts
        return facts

    def _effect_mentions(self, building_type: str, has_yields: bool) -> tuple[RulesetMention, ...]:
        """What a building does beyond its flat yields, said without a number.

        Only 79 of the building types have any `Building_YieldChanges` row, so an empty
        yield list is not evidence that a building does nothing — some express their whole
        effect through a modifier. Counting is what stops "no rows, therefore no yield"
        from becoming a claim.
        """
        if "BuildingModifiers" not in self._countable:
            return ()
        count = self._count("BuildingModifiers", {"BuildingType": building_type})
        if not count:
            return ()
        return (RulesetMention(
            subject=building_type,
            label=(f"{_title(building_type)} has {count} conditional effect"
                   f"{'' if count == 1 else 's'} beyond its flat yields"),
            detail=("The ruleset records what each one applies to and what triggers it, in "
                    "a modifier chain whose magnitude is defined by the game's own code and "
                    "by no row in this file."
                    + ("" if has_yields else
                       " The absence of a flat yield is therefore not evidence that this "
                       "building yields nothing.")),
        ),)

    # -- construction --------------------------------------------------------------

    @classmethod
    def open(cls, path: Path) -> "Civ6Ruleset":
        """Open the file read-only. Raises `sqlite3.DatabaseError` if it is not a database;
        Task 5's `open_ruleset` is what turns that into a degraded provider."""
        from .identity import identify   # Task 4 adds this; see the import note below.

        connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True,
                                     check_same_thread=False)
        connection.row_factory = sqlite3.Row
        # `mode=ro` is the guarantee that matters. `query_only` is set as well so a bug in
        # this module fails here rather than modifying a file the advisor does not own.
        connection.execute("PRAGMA query_only = 1")
        present = {row[0] for row in
                   connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        return cls(_identity=identify(path), _connection=connection,
                   _countable=frozenset(COUNTABLE_COLUMNS) & present)
```

**Import note for Step 4:** `identify` lands in Task 4. Until then, define it
inline at the bottom of `civ6.py` and move it in Task 4 — or, simpler and what
this plan does, write Task 4 first if you prefer; the tasks are independent
except for this one symbol. If you keep the order as written, add this
placeholder at the top of `civ6.py` for Task 3 only and delete it in Task 4:

```python
def _identify_placeholder(path: Path) -> RulesetIdentity:
    stat = path.stat()
    return RulesetIdentity(path=path, size=stat.st_size, mtime_ns=stat.st_mtime_ns,
                           digest="0" * 64)
```

with `from .identity import identify` replaced by
`identify = _identify_placeholder`. Task 4 Step 5 removes it and the test there
proves the real digest is in place.

- [ ] **Step 5: Run the tests**

```bash
uv run pytest tests/test_ruleset_civ6.py -q
```

Expected: 8 passed.

- [ ] **Step 6: Run the full suite**

```bash
uv run pytest -q 2>&1 | tail -3
```

Expected: green. Nothing outside `civ_advisor/ruleset/` was touched.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "Read Civ VI building figures from the installed ruleset

Opened read-only, with a column allowlist as the single query seam. The
modifier tables are not readable; BuildingModifiers can only be counted."
```

---

### Task 4: Ruleset identity, and a cache keyed on the file

A mod changes the ruleset. Serving a cost derived from the previous file would
be worse than serving none, because it looks exactly like a verified one.

**Files:**
- Create: `civ_advisor/ruleset/identity.py`
- Modify: `civ_advisor/ruleset/civ6.py` (use `identify`, drop the placeholder)
- Test: `tests/test_ruleset_identity.py`

**Interfaces:**
- Consumes: `RulesetIdentity` from Task 1.
- Produces: `civ_advisor.ruleset.identity.identify(path: Path) -> RulesetIdentity`
  and `civ_advisor.ruleset.identity.stamp(path: Path) -> tuple[int, int]`, the
  cheap `(size, mtime_ns)` key Task 5 uses to decide whether to re-derive.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ruleset_identity.py`:

```python
import hashlib

from civ_advisor.ruleset.civ6 import Civ6Ruleset
from civ_advisor.ruleset.identity import identify, stamp

from tests.ruleset_fixture import make_ruleset


def test_identity_is_the_file_itself(tmp_path):
    path = make_ruleset(tmp_path)

    identity = identify(path)

    assert identity.path == path
    assert identity.size == path.stat().st_size
    assert identity.mtime_ns == path.stat().st_mtime_ns
    assert identity.digest == hashlib.sha256(path.read_bytes()).hexdigest()


def test_two_rulesets_with_different_content_have_different_digests(tmp_path):
    """What makes a figure falsifiable: a reader with the same file gets the same digest,
    and a modded ruleset is visibly not the same ruleset."""
    vanilla = make_ruleset(tmp_path / "a", name="DebugGameplay.sqlite")
    modded = make_ruleset(tmp_path / "b", name="DebugGameplay.sqlite", rows={
        "Buildings": [("BUILDING_LIBRARY", "LOC_X", 45, 1, "DISTRICT_CAMPUS",
                       "TECH_WRITING", "", 0, 0)]})

    assert identify(vanilla).digest != identify(modded).digest


def test_the_stamp_is_cheap_and_moves_when_the_file_does(tmp_path):
    path = make_ruleset(tmp_path)
    before = stamp(path)

    path.write_bytes(path.read_bytes() + b"\x00" * 4096)

    assert stamp(path) != before


def test_a_figure_carries_the_digest_of_the_file_it_came_from(tmp_path):
    """The placeholder digest from Task 3 must be gone: an all-zero digest would make
    every ruleset look identical to every other."""
    path = make_ruleset(tmp_path)
    provider = Civ6Ruleset.open(path)
    try:
        figure = provider.building("BUILDING_LIBRARY").cost

        assert figure.identity.digest == hashlib.sha256(path.read_bytes()).hexdigest()
        assert set(figure.identity.digest) != {"0"}
    finally:
        provider.close()
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_ruleset_identity.py -q
```

Expected: `ModuleNotFoundError: No module named 'civ_advisor.ruleset.identity'`.

- [ ] **Step 3: Write `identity.py`**

Create `civ_advisor/ruleset/identity.py`:

```python
"""Which file a figure came from, hashed so the claim can be checked.

The database names no game version, no DLC and no mods, so this is the strongest honest
statement available: this exact file, this many bytes, written at this time, with this
digest. A reader can re-run the hash; a mod that rewrites the ruleset changes it.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from .base import RulesetIdentity

BLOCK = 1 << 20


def stamp(path: Path) -> tuple[int, int]:
    """The cheap key: size and modification time.

    Used to decide whether anything needs re-deriving, so the 18 MB hash runs when the
    file moves rather than on every lookup. It is not the identity — a figure is labelled
    with the digest, which is what makes it checkable.
    """
    status = path.stat()
    return (status.st_size, status.st_mtime_ns)


def identify(path: Path) -> RulesetIdentity:
    size, mtime_ns = stamp(path)
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(BLOCK), b""):
            digest.update(block)
    return RulesetIdentity(path=path, size=size, mtime_ns=mtime_ns,
                           digest=digest.hexdigest())


__all__ = ["identify", "stamp"]
```

- [ ] **Step 4: Use it from the provider**

In `civ_advisor/ruleset/civ6.py`, delete `_identify_placeholder` and the
`identify = _identify_placeholder` line, and put the real import at the top of
the module with the others:

```python
from .identity import identify
```

(There is no cycle: `identity.py` imports only `base.py`.)

- [ ] **Step 5: Run the tests and the full suite**

```bash
uv run pytest tests/test_ruleset_identity.py tests/test_ruleset_civ6.py -q
uv run pytest -q 2>&1 | tail -3
```

Expected: 4 + 8 passed, whole suite green.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "Label a ruleset figure with the file it came from

Size, modification time and a SHA-256 — reproducible and falsifiable, and
not a version number, because the database states none."
```

---

### Task 5: `open_ruleset` — caching, and degrading instead of failing

Three ways the ruleset is not readable, and one behaviour for all of them: a
`NullRuleset` carrying a reason, which makes the advisor ask the player exactly
as it does for Civ VII.

**Files:**
- Modify: `civ_advisor/ruleset/civ6.py` (`open_ruleset`, `clear_cache`)
- Test: `tests/test_ruleset_open.py`

**Interfaces:**
- Consumes: Tasks 1, 3, 4.
- Produces:
  - `civ_advisor.ruleset.civ6.open_ruleset(path: Path | None = None) -> RulesetProvider`.
  - `civ_advisor.ruleset.civ6.clear_cache() -> None`, for tests and for a game switch.
  - `civ_advisor.ruleset.civ6.REQUIRED_TABLES`, checked at open.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ruleset_open.py`:

```python
import pytest

from civ_advisor.ruleset.civ6 import Civ6Ruleset, clear_cache, open_ruleset

from tests.ruleset_fixture import SCHEMA, make_ruleset


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_cache()
    yield
    clear_cache()


def test_a_missing_database_degrades_to_asking_the_player(tmp_path):
    provider = open_ruleset(tmp_path / "nothing-here.sqlite")

    assert provider.available is False
    assert provider.building("BUILDING_LIBRARY") is None
    assert "nothing-here.sqlite" in provider.reason
    assert "preview" in provider.reason


def test_a_file_that_is_not_a_database_degrades(tmp_path):
    path = tmp_path / "DebugGameplay.sqlite"
    path.write_bytes(b"this is not a database")

    provider = open_ruleset(path)

    assert provider.available is False
    assert "could not be read" in provider.reason


def test_a_changed_schema_degrades_and_names_what_is_missing(tmp_path):
    """A patch that renames a column must stop the advisor quoting figures, not make it
    quote the wrong ones."""
    renamed = SCHEMA.replace("Cost INTEGER", "ProductionCost INTEGER")
    path = make_ruleset(tmp_path, schema=renamed, rows={"Buildings": []})

    provider = open_ruleset(path)

    assert provider.available is False
    assert "Buildings" in provider.reason and "Cost" in provider.reason


def test_a_missing_table_degrades(tmp_path):
    without_yields = "".join(
        f"{statement};" for statement in SCHEMA.split(";")
        if statement.strip() and "Building_YieldChanges" not in statement)
    path = make_ruleset(tmp_path, schema=without_yields,
                        rows={"Building_YieldChanges": []})

    provider = open_ruleset(path)

    assert provider.available is False
    assert "Building_YieldChanges" in provider.reason


def test_the_same_unchanged_file_is_opened_once(tmp_path):
    path = make_ruleset(tmp_path)

    assert open_ruleset(path) is open_ruleset(path)


def test_a_modded_ruleset_is_re_derived_rather_than_served_stale(tmp_path):
    """The reason the cache is keyed on the file and not on the path. A stale cost is
    worse than no cost: it is indistinguishable from a verified one."""
    path = make_ruleset(tmp_path)
    assert open_ruleset(path).building("BUILDING_LIBRARY").cost.value == 90

    path.unlink()
    make_ruleset(tmp_path, rows={"Buildings": [
        ("BUILDING_LIBRARY", "LOC_X", 45, 1, "DISTRICT_CAMPUS", "TECH_WRITING", "", 0, 0)]})

    provider = open_ruleset(path)
    assert provider.building("BUILDING_LIBRARY").cost.value == 45
    assert isinstance(provider, Civ6Ruleset)
```

If the two writes land inside one filesystem timestamp tick, the second fixture
differs in size as well — but to keep the test honest rather than lucky, the
implementation compares `(size, mtime_ns)` and `st_mtime_ns` is nanosecond
resolution on APFS. If this test proves flaky on another filesystem, make the
rewrite change the file's length rather than loosening the check.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_ruleset_open.py -q
```

Expected: `ImportError: cannot import name 'open_ruleset'`.

- [ ] **Step 3: Add the schema requirement and the opener**

In `civ_advisor/ruleset/civ6.py`, add the imports `threading` and
`from .base import NullRuleset, RulesetProvider`, then append:

```python
# Every table this provider reads, and the columns it reads from each, must be present
# exactly as named. A patch that renames a column is the case this guards: the advisor
# must stop quoting figures rather than quote the wrong ones.
REQUIRED_TABLES = READABLE_COLUMNS

_OPEN: dict[Path, tuple[tuple[int, int], Civ6Ruleset]] = {}
_LOCK = threading.Lock()


def _schema_complaint(connection: sqlite3.Connection) -> str | None:
    """What the database is missing, or None if it has everything this module reads."""
    present = {row[0] for row in
               connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    for table, columns in sorted(REQUIRED_TABLES.items()):
        if table not in present:
            return f"it has no {table} table"
        found = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
        missing = sorted(columns - found)
        if missing:
            return f"{table} has no {', '.join(missing)} column"
    return None


def clear_cache() -> None:
    """Close and forget every open ruleset. For tests, and for a game switch."""
    with _LOCK:
        for _, provider in _OPEN.values():
            provider.close()
        _OPEN.clear()


def open_ruleset(path: Path | None = None) -> RulesetProvider:
    """The provider for this database, reused while the file has not changed.

    Keyed on the file's identity rather than on its path: a mod or a patch that rewrites
    the ruleset changes its size and modification time, and everything derived from the
    previous one is dropped rather than served stale.

    Never raises. Absent, unreadable, or shaped differently than expected all produce a
    `NullRuleset` carrying a reason — which is exactly the Civilization VII behaviour, so
    a failure here degrades to asking the player rather than to an error in front of one.
    """
    path = (path or DEFAULT_DATABASE).expanduser()
    with _LOCK:
        try:
            current = stamp(path)
        except OSError as exc:
            _forget(path)
            return NullRuleset(
                f"{path.name} was not readable at {path} ({exc.strerror or exc}), so no "
                "figure is taken from your installed ruleset; the advisor will ask you "
                "for the game's own preview instead.")
        cached = _OPEN.get(path)
        if cached is not None and cached[0] == current:
            return cached[1]
        _forget(path)
        try:
            provider = Civ6Ruleset.open(path)
        except (sqlite3.DatabaseError, OSError) as exc:
            return NullRuleset(
                f"{path.name} could not be read as a database ({exc}), so no figure is "
                "taken from your installed ruleset; the advisor will ask you for the "
                "game's own preview instead.")
        complaint = _schema_complaint(provider._connection)
        if complaint is not None:
            provider.close()
            return NullRuleset(
                f"{path.name} is not shaped the way this advisor knows how to read — "
                f"{complaint}. No figure is taken from it; the advisor will ask you for "
                "the game's own preview instead.")
        _OPEN[path] = (current, provider)
        return provider


def _forget(path: Path) -> None:
    """Drop a cached provider. Caller holds `_LOCK`."""
    previous = _OPEN.pop(path, None)
    if previous is not None:
        previous[1].close()
```

and add `from .identity import identify, stamp` to the imports.

A note on `Civ6Ruleset.open` raising: `sqlite3.connect` with `mode=ro` raises
`sqlite3.OperationalError` (a `DatabaseError`) for a missing file, and the first
statement raises `sqlite3.DatabaseError: file is not a database` for a
non-database. `identify` is called inside `open` and raises `OSError` if the
file vanishes between the `stamp` and the hash. All three are caught by the
`except (sqlite3.DatabaseError, OSError)` above, which is why that window is
not left open.

- [ ] **Step 4: Run the tests**

```bash
uv run pytest tests/test_ruleset_open.py -q
```

Expected: 6 passed.

- [ ] **Step 5: Run the full suite**

```bash
uv run pytest -q 2>&1 | tail -3
```

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "Open the ruleset once per file, and degrade when it is not readable

Absent, corrupt or reshaped all produce a NullRuleset with a reason, which is
the Civ VII behaviour: ask the player."
```

---

### Task 6: The rest of the in-scope surface

Districts, technologies, civics with their boosts, and units. Every one is a
plain indexed row per the research report; each extension is one allowlist
entry, one dataclass and one lookup, and nothing about the boundary changes.

**Files:**
- Modify: `civ_advisor/ruleset/base.py` (four dataclasses, four protocol
  methods, four `NullRuleset` methods)
- Modify: `civ_advisor/ruleset/civ6.py` (`READABLE_COLUMNS`, four lookups)
- Modify: `tests/ruleset_fixture.py` (the new tables and rows)
- Test: `tests/test_ruleset_civ6.py` (append)

**Interfaces:**
- Consumes: Tasks 1–5.
- Produces, in `civ_advisor.ruleset.base`:
  - `DistrictFacts(district, cost, prereq_tech, prereq_civic)`
  - `TechnologyFacts(technology, cost, era, prereqs, boosts)`
  - `CivicFacts(civic, cost, era, prereqs, boosts)`
  - `BoostFacts(percent, trigger, objects)`
  - `UnitFacts(unit, cost, maintenance, combat, ranged_combat, prereq_tech, prereq_civic, strategic_resource, upgrades_to, mentions)`
  - `RulesetProvider.district / technology / civic / unit`, and the same four
    on `NullRuleset` returning `None`.

**Deliberately not here**, each for a reason in the research report:

- **District adjacency yields.** The rows in `Adjacency_YieldChanges` are plain,
  but the join from a district to its set of adjacency ids was not verified, and
  an unverified join is how a Campus ends up quoting a Harbour's number.
- **Government slot counts.** `SELECT MilitarySlots FROM Governments` fails; the
  correct join was not found. Do not guess it.
- **Policy effects.** `PolicyModifiers` -> `Modifiers`, which is the whole thing
  this phase excludes. The slot a policy fits in is a plain column and could be
  added later; its effect never can be.
- **The gold cost of a unit upgrade.** Computed at runtime from a formula and
  stored in no row. `UnitFacts` carries a `RulesetMention` saying exactly that,
  because the upgrade *target* being stateable makes the cost the obvious next
  question.
- **Per-unit strategic resource quantity.** `Units.StrategicResource` names the
  resource; the quantity lives in a table not explored. The resource is in
  scope, the quantity is not.

- [ ] **Step 1: Extend the fixture**

Append to `SCHEMA` in `tests/ruleset_fixture.py`:

```python
SCHEMA += """
CREATE TABLE Districts (
    DistrictType TEXT NOT NULL PRIMARY KEY, Name TEXT, Cost INTEGER,
    PrereqTech TEXT, PrereqCivic TEXT);
CREATE TABLE Technologies (
    TechnologyType TEXT NOT NULL PRIMARY KEY, Name TEXT, Cost INTEGER, EraType TEXT);
CREATE TABLE TechnologyPrereqs (
    Technology TEXT NOT NULL, PrereqTech TEXT NOT NULL,
    PRIMARY KEY (Technology, PrereqTech));
CREATE TABLE Civics (
    CivicType TEXT NOT NULL PRIMARY KEY, Name TEXT, Cost INTEGER, EraType TEXT);
CREATE TABLE CivicPrereqs (
    Civic TEXT NOT NULL, PrereqCivic TEXT NOT NULL, PRIMARY KEY (Civic, PrereqCivic));
CREATE TABLE Boosts (
    BoostID INTEGER NOT NULL PRIMARY KEY, TechnologyType TEXT, CivicType TEXT,
    Boost INTEGER, BoostClass TEXT, Unit1Type TEXT, BuildingType TEXT,
    DistrictType TEXT, NumItems INTEGER);
CREATE TABLE Units (
    UnitType TEXT NOT NULL PRIMARY KEY, Name TEXT, Cost INTEGER, Maintenance INTEGER,
    Combat INTEGER, RangedCombat INTEGER, PrereqTech TEXT, PrereqCivic TEXT,
    StrategicResource TEXT);
CREATE TABLE UnitUpgrades (
    Unit TEXT NOT NULL PRIMARY KEY, UpgradeUnit TEXT NOT NULL);
"""

ROWS.update({
    "Districts": [("DISTRICT_CAMPUS", "LOC_DISTRICT_CAMPUS_NAME", 54, "TECH_WRITING", "")],
    "Technologies": [("TECH_WRITING", "LOC_TECH_WRITING_NAME", 50, "ERA_ANCIENT"),
                     ("TECH_POTTERY", "LOC_TECH_POTTERY_NAME", 25, "ERA_ANCIENT")],
    "TechnologyPrereqs": [("TECH_WRITING", "TECH_POTTERY")],
    "Civics": [("CIVIC_CODE_OF_LAWS", "LOC_CIVIC_CODE_OF_LAWS_NAME", 20, "ERA_ANCIENT"),
               ("CIVIC_STATE_WORKFORCE", "LOC_X", 70, "ERA_ANCIENT")],
    "CivicPrereqs": [("CIVIC_STATE_WORKFORCE", "CIVIC_CODE_OF_LAWS")],
    "Boosts": [(53, "TECH_WRITING", None, 40, "BOOST_TRIGGER_MEET_CIV",
                "UNIT_SCOUT", None, None, None),
               (4, None, "CIVIC_STATE_WORKFORCE", 40,
                "BOOST_TRIGGER_HAVE_X_UNIQUE_SPECIALTY_DISTRICTS", None, None, None, 1)],
    "Units": [("UNIT_WARRIOR", "LOC_UNIT_WARRIOR_NAME", 40, 0, 20, 0, "", "", ""),
              ("UNIT_SWORDSMAN", "LOC_UNIT_SWORDSMAN_NAME", 90, 2, 36, 0,
               "TECH_IRON_WORKING", "", "RESOURCE_IRON")],
    "UnitUpgrades": [("UNIT_WARRIOR", "UNIT_SWORDSMAN")],
})
```

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_ruleset_civ6.py`:

```python
def test_a_district_states_its_cost_and_prerequisite(ruleset):
    facts = ruleset.district("DISTRICT_CAMPUS")

    assert facts.cost.value == 54 and facts.cost.unit == "production"
    assert facts.prereq_tech.value == "TECH_WRITING"
    assert facts.prereq_civic is None


def test_a_technology_states_its_cost_prereqs_and_eureka(ruleset):
    """Boosts are a purpose-built table, not a modifier chain: the percentage is a row
    value and the trigger is named by a column."""
    facts = ruleset.technology("TECH_WRITING")

    assert (facts.cost.value, facts.cost.unit) == (50, "science")
    assert [p.value for p in facts.prereqs] == ["TECH_POTTERY"]
    boost = facts.boosts[0]
    assert (boost.percent.value, boost.percent.unit) == (40, "% of the cost")
    assert boost.trigger.value == "BOOST_TRIGGER_MEET_CIV"
    assert [(o.column, o.value) for o in boost.objects] == [("Unit1Type", "UNIT_SCOUT")]


def test_a_civic_states_its_cost_and_inspiration(ruleset):
    facts = ruleset.civic("CIVIC_STATE_WORKFORCE")

    assert (facts.cost.value, facts.cost.unit) == (70, "culture")
    assert [p.value for p in facts.prereqs] == ["CIVIC_CODE_OF_LAWS"]
    assert [(o.column, o.value) for o in facts.boosts[0].objects] == [("NumItems", 1)]


def test_a_unit_states_its_cost_strength_and_upgrade_target(ruleset):
    facts = ruleset.unit("UNIT_WARRIOR")

    assert (facts.cost.value, facts.cost.unit) == (40, "production")
    assert (facts.combat.value, facts.combat.unit) == (20, "combat strength")
    assert facts.ranged_combat is None            # 0 means no ranged attack, not "0 strength"
    assert facts.maintenance is None              # 0 gold is no maintenance
    assert facts.upgrades_to.value == "UNIT_SWORDSMAN"
    assert facts.strategic_resource is None


def test_the_gold_cost_of_an_upgrade_is_a_mention_and_never_a_number(ruleset):
    """The upgrade target is a row; the gold it costs is computed at runtime and stored
    nowhere. Stating the first without disclaiming the second is how a guess starts."""
    facts = ruleset.unit("UNIT_WARRIOR")

    assert facts.mentions
    assert all("gold" in m.as_unknown().lower() for m in facts.mentions)
    assert not any(f.column == "UpgradeCost" for f in facts.figures)


def test_the_boosts_table_may_not_be_read_for_anything_else(ruleset):
    with pytest.raises(RulesetOutOfScope, match="TriggerDescription"):
        ruleset._select("Boosts", ("TriggerDescription",), {})
```

The last test is the localisation guard: `TriggerDescription` is a `LOC_*` key
and resolving it needs `DebugLocalization.sqlite`, which spec §12 defers. The
trigger surfaces as its `BoostClass` type key instead.

- [ ] **Step 3: Run the tests to verify they fail**

```bash
uv run pytest tests/test_ruleset_civ6.py -q -k "district or technology or civic or unit or boosts_table"
```

Expected: `AttributeError: 'Civ6Ruleset' object has no attribute 'district'`.

- [ ] **Step 4: Extend the contracts**

In `civ_advisor/ruleset/base.py`, add beside `BuildingFacts`:

```python
@dataclass(frozen=True)
class DistrictFacts:
    district: str
    cost: RulesetFigure | None = None
    prereq_tech: RulesetFigure | None = None
    prereq_civic: RulesetFigure | None = None

    @property
    def figures(self) -> tuple[RulesetFigure, ...]:
        return tuple(f for f in (self.cost, self.prereq_tech, self.prereq_civic)
                     if f is not None)


@dataclass(frozen=True)
class BoostFacts:
    """One eureka or inspiration: how much, and what triggers it.

    The trigger is the `BoostClass` type key and the populated trigger-object columns.
    Which of the ~10 nullable object columns is populated is what says what kind of
    trigger it is, so the populated ones are carried as figures naming their own column
    and the empty ones are simply absent.
    """

    percent: RulesetFigure
    trigger: RulesetFigure
    objects: tuple[RulesetFigure, ...] = ()

    @property
    def figures(self) -> tuple[RulesetFigure, ...]:
        return (self.percent, self.trigger) + self.objects


@dataclass(frozen=True)
class TechnologyFacts:
    technology: str
    cost: RulesetFigure | None = None
    era: RulesetFigure | None = None
    prereqs: tuple[RulesetFigure, ...] = ()
    boosts: tuple[BoostFacts, ...] = ()

    @property
    def figures(self) -> tuple[RulesetFigure, ...]:
        named = tuple(f for f in (self.cost, self.era) if f is not None)
        return named + self.prereqs + tuple(f for b in self.boosts for f in b.figures)


@dataclass(frozen=True)
class CivicFacts:
    civic: str
    cost: RulesetFigure | None = None
    era: RulesetFigure | None = None
    prereqs: tuple[RulesetFigure, ...] = ()
    boosts: tuple[BoostFacts, ...] = ()

    @property
    def figures(self) -> tuple[RulesetFigure, ...]:
        named = tuple(f for f in (self.cost, self.era) if f is not None)
        return named + self.prereqs + tuple(f for b in self.boosts for f in b.figures)


@dataclass(frozen=True)
class UnitFacts:
    unit: str
    cost: RulesetFigure | None = None
    maintenance: RulesetFigure | None = None
    combat: RulesetFigure | None = None
    ranged_combat: RulesetFigure | None = None
    prereq_tech: RulesetFigure | None = None
    prereq_civic: RulesetFigure | None = None
    strategic_resource: RulesetFigure | None = None
    upgrades_to: RulesetFigure | None = None
    mentions: tuple[RulesetMention, ...] = ()

    @property
    def figures(self) -> tuple[RulesetFigure, ...]:
        return tuple(f for f in (self.cost, self.maintenance, self.combat,
                                 self.ranged_combat, self.prereq_tech, self.prereq_civic,
                                 self.strategic_resource, self.upgrades_to)
                     if f is not None)
```

Add the four methods to the `RulesetProvider` protocol:

```python
    def district(self, district_type: str) -> DistrictFacts | None: ...

    def technology(self, technology_type: str) -> TechnologyFacts | None: ...

    def civic(self, civic_type: str) -> CivicFacts | None: ...

    def unit(self, unit_type: str) -> UnitFacts | None: ...
```

and the same four to `NullRuleset`, each `return None`. Extend `__all__`.

- [ ] **Step 5: Extend the allowlist and add the lookups**

In `civ_advisor/ruleset/civ6.py`, extend the import from `.base` with the
four new types:

```python
from .base import (
    BoostFacts, BuildingFacts, CivicFacts, DistrictFacts, NullRuleset, RulesetFigure,
    RulesetIdentity, RulesetMention, RulesetOutOfScope, RulesetProvider, TechnologyFacts,
    UnitFacts,
)
```

then add to `READABLE_COLUMNS`:

```python
    "Districts": frozenset({"DistrictType", "Cost", "PrereqTech", "PrereqCivic"}),
    "Technologies": frozenset({"TechnologyType", "Cost", "EraType"}),
    "TechnologyPrereqs": frozenset({"Technology", "PrereqTech"}),
    "Civics": frozenset({"CivicType", "Cost", "EraType"}),
    "CivicPrereqs": frozenset({"Civic", "PrereqCivic"}),
    # `Boost` is the percentage and `BoostClass` names the trigger. `TriggerDescription`
    # is deliberately absent: it is a LOC_* key that only DebugLocalization.sqlite can
    # resolve, and spec §12 defers that.
    "Boosts": frozenset({"BoostID", "TechnologyType", "CivicType", "Boost", "BoostClass",
                         "Unit1Type", "BuildingType", "DistrictType", "NumItems"}),
    "Units": frozenset({"UnitType", "Cost", "Maintenance", "Combat", "RangedCombat",
                        "PrereqTech", "PrereqCivic", "StrategicResource"}),
    "UnitUpgrades": frozenset({"Unit", "UpgradeUnit"}),
```

Add a shared helper beside `_title`, so five lookups do not each re-derive the
same absence rule:

```python
BOOST_OBJECT_COLUMNS = ("Unit1Type", "BuildingType", "DistrictType", "NumItems")


def _absent(value) -> bool:
    """Whether a column value says nothing.

    An empty prerequisite means "none" and a zero combat strength means "cannot fight".
    Both are absence. Turning either into a figure would put "0" in front of a player as
    though the ruleset had asserted it.
    """
    return value is None or value == "" or value == 0
```

Then the four lookups, each following `building`'s shape — a `figure` closure
bound to one table and one row key, `_absent` for every optional column,
`self._cache` keyed on `(kind, type_key)`:

```python
    def district(self, district_type: str) -> DistrictFacts | None:
        cached = self._cache.get(("district", district_type))
        if cached is not None:
            return cached  # type: ignore[return-value]
        rows = self._select("Districts", ("Cost", "PrereqTech", "PrereqCivic"),
                            {"DistrictType": district_type})
        if not rows:
            return None
        row, name = rows[0], _title(district_type)
        make = self._figure_maker("Districts", district_type, (district_type,), row)
        facts = DistrictFacts(
            district=district_type,
            cost=make("Cost", f"{name} district production cost", "production"),
            prereq_tech=make("PrereqTech", f"{name} district requires technology", None),
            prereq_civic=make("PrereqCivic", f"{name} district requires civic", None))
        self._cache[("district", district_type)] = facts
        return facts

    def _figure_maker(self, table: str, subject: str, row_key: tuple[str, ...],
                      row: sqlite3.Row):
        """One row's figures, each naming that row. Shared so five lookups cannot drift
        into five slightly different ideas of what counts as absent."""

        def make(column: str, label: str, unit: str | None) -> RulesetFigure | None:
            value = row[column]
            if _absent(value):
                return None
            return RulesetFigure(subject=subject, label=label, value=value, unit=unit,
                                 table=table, column=column, row_key=row_key,
                                 identity=self._identity)

        return make

    def _boosts(self, column: str, subject: str) -> tuple[BoostFacts, ...]:
        """Every eureka or inspiration attached to one technology or civic."""
        out = []
        for row in self._select("Boosts",
                                ("BoostID", "Boost", "BoostClass") + BOOST_OBJECT_COLUMNS,
                                {column: subject}):
            key = (str(row["BoostID"]),)
            make = self._figure_maker("Boosts", subject, key, row)
            percent = make("Boost", f"{_title(subject)} boost", "% of the cost")
            trigger = make("BoostClass", f"{_title(subject)} boost trigger", None)
            if percent is None or trigger is None:
                continue
            objects = tuple(f for f in (make(c, f"{_title(subject)} boost {c}", None)
                                        for c in BOOST_OBJECT_COLUMNS) if f is not None)
            out.append(BoostFacts(percent=percent, trigger=trigger, objects=objects))
        return tuple(out)

    def technology(self, technology_type: str) -> TechnologyFacts | None:
        cached = self._cache.get(("technology", technology_type))
        if cached is not None:
            return cached  # type: ignore[return-value]
        rows = self._select("Technologies", ("Cost", "EraType"),
                            {"TechnologyType": technology_type})
        if not rows:
            return None
        name = _title(technology_type)
        make = self._figure_maker("Technologies", technology_type, (technology_type,),
                                  rows[0])
        prereqs = tuple(
            RulesetFigure(subject=technology_type, label=f"{name} requires technology",
                          value=r["PrereqTech"], unit=None, table="TechnologyPrereqs",
                          column="PrereqTech",
                          row_key=(technology_type, r["PrereqTech"]),
                          identity=self._identity)
            for r in self._select("TechnologyPrereqs", ("PrereqTech",),
                                  {"Technology": technology_type}))
        facts = TechnologyFacts(
            technology=technology_type,
            cost=make("Cost", f"{name} research cost", "science"),
            era=make("EraType", f"{name} era", None),
            prereqs=prereqs, boosts=self._boosts("TechnologyType", technology_type))
        self._cache[("technology", technology_type)] = facts
        return facts
```

`civic` is `technology` with `Civics` / `CivicPrereqs` / `Civic` / `PrereqCivic`
/ `"culture"` substituted, and `self._boosts("CivicType", civic_type)`. Write it
out rather than parameterising: two near-identical twenty-line methods read
better here than one method with four table-name arguments, and the tables are
not guaranteed to stay parallel.

`unit`:

```python
    def unit(self, unit_type: str) -> UnitFacts | None:
        cached = self._cache.get(("unit", unit_type))
        if cached is not None:
            return cached  # type: ignore[return-value]
        rows = self._select("Units",
                            ("Cost", "Maintenance", "Combat", "RangedCombat", "PrereqTech",
                             "PrereqCivic", "StrategicResource"),
                            {"UnitType": unit_type})
        if not rows:
            return None
        name = _title(unit_type)
        make = self._figure_maker("Units", unit_type, (unit_type,), rows[0])
        upgrades = self._select("UnitUpgrades", ("UpgradeUnit",), {"Unit": unit_type})
        upgrades_to = None
        mentions: tuple[RulesetMention, ...] = ()
        if upgrades:
            upgrades_to = RulesetFigure(
                subject=unit_type, label=f"{name} upgrades to", value=upgrades[0]["UpgradeUnit"],
                unit=None, table="UnitUpgrades", column="UpgradeUnit", row_key=(unit_type,),
                identity=self._identity)
            mentions = (RulesetMention(
                subject=unit_type, label=f"{name}'s upgrade has a gold cost",
                detail=("The ruleset states what it upgrades into and stores no row for "
                        "what that costs; the game computes it at the moment you upgrade.")),)
        facts = UnitFacts(
            unit=unit_type,
            cost=make("Cost", f"{name} production cost", "production"),
            maintenance=make("Maintenance", f"{name} maintenance", "gold per turn"),
            combat=make("Combat", f"{name} combat strength", "combat strength"),
            ranged_combat=make("RangedCombat", f"{name} ranged strength", "combat strength"),
            prereq_tech=make("PrereqTech", f"{name} requires technology", None),
            prereq_civic=make("PrereqCivic", f"{name} requires civic", None),
            strategic_resource=make("StrategicResource", f"{name} requires resource", None),
            upgrades_to=upgrades_to, mentions=mentions)
        self._cache[("unit", unit_type)] = facts
        return facts
```

Refactor `building` to use `_figure_maker` and `_absent` too, so there is one
absence rule in the module rather than two. Its existing tests must still pass
unchanged — note that `Library`'s `Maintenance` is 1, so the `_absent` change
from `value == ""` to `value == 0` does not alter that assertion, and
`Housing` is not read at all.

- [ ] **Step 6: Run the tests and the full suite**

```bash
uv run pytest tests/test_ruleset_civ6.py -q
uv run pytest -q 2>&1 | tail -3
```

Expected: 14 passed in that file (8 from Task 3, 6 new), whole suite green.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "Read districts, technologies, civics and units from the ruleset

Costs, prerequisites, combat strengths, eureka and inspiration triggers.
The gold cost of a unit upgrade is stored in no row and stays a mention."
```

---

### Task 7: Wire it into the profile and the recommendation path

**A measured cost this task must bound.** Task 4's fix dropped the
`(size, mtime_ns)` fast path — correctly, because it could miss a same-size
edit — so `building()` now re-derives the file's digest on every call, and
read-verify-reread hashes twice on a cache miss. Measured against the real
18.1 MB database: **5.7 ms per lookup even when the per-instance cache
hits**, and 572 ms for 100 lookups. Correctness is not in question; the
cache is simply bypassed by the verification.

That is fine for a handful of lookups per rebuild and bad for a path that
walks every building in a queue. So this task must establish how many
lookups a real recommendation actually makes, and if it is more than a
handful, verify identity ONCE per rebuild rather than once per call —
the file cannot plausibly change between two lookups in the same rebuild,
and a per-rebuild check still catches a mod toggle within one turn. Report
the real call count; do not assume it is small.

Where a Civ VI recommendation naming a building starts stating that building's
real cost, maintenance and yield. Civ VII is untouched, by construction: its
profile declares no ruleset, so it gets `NO_RULESET` and behaves exactly as it
does today.

**Files:**
- Modify: `civ_advisor/games/base.py` (`Capability.INSTALLED_RULESET`,
  `GameProfile.ruleset`)
- Modify: `civ_advisor/games/civ6/__init__.py` (declare both)
- Modify: `civ_advisor/decisions/context.py` (`DecisionContext.ruleset`,
  `build_context(..., ruleset=None)`)
- Modify: `civ_advisor/decisions/candidates.py` (`named_build`)
- Modify: `civ_advisor/api/app.py` (pass the profile's ruleset to `build_context`)
- Test: `tests/test_ruleset_wiring.py`

**Interfaces:**
- Consumes: Tasks 1–6.
- Produces:
  - `civ_advisor.games.base.Capability.INSTALLED_RULESET`.
  - `civ_advisor.games.base.GameProfile.ruleset: Callable[[], RulesetProvider] | None = None`.
  - `civ_advisor.decisions.context.DecisionContext.ruleset: RulesetProvider`,
    defaulting to `NO_RULESET`.
  - `build_context(snapshot, player=None, oracle=True, catalog=None, ruleset=None)`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ruleset_wiring.py`. The state helpers are the ones the
existing decision tests use — `tests/factories.py`, imported the same way
`tests/test_decision_culture.py` imports them — so there is one scenario builder
rather than two:

```python
import pytest

from civ_advisor.advisors import run_all
from civ_advisor.decisions.candidates import named_build
from civ_advisor.decisions.context import Previews, build_context
from civ_advisor.decisions.models import SourceKind
from civ_advisor.games.base import Capability
from civ_advisor.ruleset.base import NO_RULESET
from civ_advisor.ruleset.civ6 import clear_cache, open_ruleset
from tests.factories import build_queue_row, game_state, snapshot
from tests.ruleset_fixture import make_ruleset

CITY = "LOC_CITY_NAME_TEST1"
AMPHITHEATER = "BUILDING_AMPHITHEATER"


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_cache()
    yield
    clear_cache()


@pytest.fixture
def snap():
    """A settlement behind on culture with one logged queue — the same shape
    `tests/test_decision_culture.py` uses, so this exercises the real path."""
    state = game_state(turn=33, rivals={1: "Rival One"},
                       human_stats={"culture": 11.0, "gold": 20.0, "cities": 1, "towns": 0},
                       rival_stats={1: {"culture": 17.2}})
    state.build_queues = [build_queue_row(state.latest_turn, 0, CITY, "UNIT_WARRIOR",
                                          added=20.0, current=25.0, needed=30.0)]
    return snapshot(state, run_all(state))


def _ruleset(tmp_path):
    """The fixture database, holding the Amphitheater the shipped catalog already names,
    so the wiring is exercised through a real guide entry rather than a stub."""
    return open_ruleset(make_ruleset(tmp_path, rows={
        "Buildings": [(AMPHITHEATER, "LOC_X", 150, 1, "DISTRICT_THEATER", "",
                       "CIVIC_DRAMA", 0, 0)],
        "Building_YieldChanges": [(AMPHITHEATER, "YIELD_CULTURE", 2)]}))


def test_a_context_without_a_ruleset_is_todays_behaviour(snap):
    context = build_context(snap)

    assert context.ruleset is NO_RULESET
    assert context.ruleset.building("BUILDING_AMPHITHEATER") is None
    assert not [f for f in context.ledger.facts.values()
                if f.source_kind is SourceKind.INSTALLED_RULESET]


def test_a_ruleset_puts_the_real_figures_in_the_ledger(snap, tmp_path):
    context = build_context(snap, ruleset=_ruleset(tmp_path))

    facts = {f.id: f for f in context.ledger.facts.values()
             if f.source_kind is SourceKind.INSTALLED_RULESET}
    assert facts["ruleset.Buildings.BUILDING_AMPHITHEATER.Cost"].value == 150
    assert facts["ruleset.Building_YieldChanges.BUILDING_AMPHITHEATER.YIELD_CULTURE"
                 ".YieldChange"].value == 2


def test_a_named_build_cites_the_ruleset_and_drops_the_no_ruleset_caveat(snap, tmp_path):
    context = build_context(snap, ruleset=_ruleset(tmp_path))

    candidate = named_build(context, CITY, "Test1", AMPHITHEATER,
                            "culture is behind", Previews(item=AMPHITHEATER),
                            "culture")

    assert "ruleset.Buildings.BUILDING_AMPHITHEATER.Cost" in candidate.evidence_ids
    assert not any("installed ruleset is not recorded" in u for u in candidate.unknowns)
    assert any("your installed game files" in t for t in candidate.trade_offs)


def test_a_named_build_without_a_ruleset_keeps_the_caveat_word_for_word(snap):
    """The Civ VII path. This sentence is what the README promises, and a Civ VI feature
    must not have quietly rewritten it."""
    context = build_context(snap)

    candidate = named_build(context, CITY, "Test1", AMPHITHEATER,
                            "culture is behind", Previews(item=AMPHITHEATER),
                            "culture")

    assert ("The installed ruleset is not recorded, so no figure for this building is "
            "taken from any guide — only from your own preview.") in candidate.unknowns


def test_a_named_build_is_still_never_ready_with_a_ruleset(snap, tmp_path):
    """Knowing what a building costs says nothing about whether this settlement is offered
    it. A real cost must not turn a conditional recommendation into a confident one."""
    context = build_context(snap, ruleset=_ruleset(tmp_path))

    candidate = named_build(context, CITY, "Test1", AMPHITHEATER,
                            "culture is behind", Previews(item=AMPHITHEATER),
                            "culture")

    assert candidate.applicability.value == "conditional"
    assert dict(candidate.prerequisites)["offered in this settlement"].value == "unknown"


def test_the_civ6_profile_declares_the_capability_and_the_factory():
    from civ_advisor.games.civ6 import CIV6
    from civ_advisor.games.civ7 import CIV7

    assert CIV6.supports(Capability.INSTALLED_RULESET) and CIV6.ruleset is not None
    assert not CIV7.supports(Capability.INSTALLED_RULESET) and CIV7.ruleset is None
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_ruleset_wiring.py -q
```

Expected: `TypeError: build_context() got an unexpected keyword argument 'ruleset'`.

- [ ] **Step 3: Give the profile a ruleset**

In `civ_advisor/games/base.py`, add to `Capability`:

```python
    INSTALLED_RULESET = "installed_ruleset"
```

and to `GameProfile`, after `capabilities`:

```python
    # A factory rather than a provider: opening the database is I/O against a file the
    # player's game rewrites, and a profile is a module-level constant built at import
    # time. Calling it is what re-checks the file; see ruleset/civ6.py:open_ruleset.
    ruleset: Callable[[], "RulesetProvider"] | None = None
```

with `from civ_advisor.ruleset.base import RulesetProvider` under a
`TYPE_CHECKING` guard, so `games/base.py` keeps importing nothing at runtime
beyond the stdlib.

In `civ_advisor/games/civ6/__init__.py`, add `Capability.INSTALLED_RULESET` to
the profile's `capabilities` and:

```python
from civ_advisor.ruleset.civ6 import open_ruleset
...
    ruleset=open_ruleset,
```

- [ ] **Step 4: Thread it through the context**

In `civ_advisor/decisions/context.py`, add the import:

```python
from civ_advisor.ruleset.base import NO_RULESET, RulesetProvider
```

add the field to `DecisionContext` as the **last** field, after `insight_ids`.
`session` through `player` have no defaults, so a defaulted field may only go
among the defaulted ones at the end:

```python
    insight_ids: tuple[str, ...] = ()
    ruleset: RulesetProvider = NO_RULESET
```

and in `build_context`, add the parameter and populate the ledger:

```python
def build_context(snapshot: Snapshot, player: PlayerContext | None = None,
                  oracle: bool = True, catalog: Catalog | None = None,
                  ruleset: RulesetProvider | None = None) -> DecisionContext:
```

```python
    # Ruleset figures go into the ledger here rather than while a candidate is being
    # built, so the ledger is complete before anything cites it: a card citing a fact that
    # was added later would resolve through the API and not in a test that built only the
    # context. `ruleset_fact` is idempotent, so a candidate may re-derive the same figure.
    ruleset = ruleset or NO_RULESET
    for item in sorted({key for entry in catalog.entries for key in entry.item_keys}):
        item_facts = ruleset.building(item)
        if item_facts is not None:
            for figure in item_facts.figures:
                ruleset_fact(ledger, figure)
```

placed immediately after the `for report in player.reports:` loop, and
`ruleset=ruleset` added to the `DecisionContext(...)` call. Import
`ruleset_fact` from `.evidence` alongside `build_ledger`.

- [ ] **Step 5: Use it where a building is named**

In `civ_advisor/decisions/candidates.py`, add the imports:

```python
from civ_advisor.ruleset.base import BuildingFacts

from .evidence import ruleset_fact
```

(`candidates` -> `evidence` is not a cycle: `evidence` imports `advisors`,
`state` and `.models`, none of which reach back here.)

and in `named_build`, between the `prerequisites` list and the `unknowns` list:

```python
    ruleset_facts = context.ruleset.building(item)
    ruleset_ids: tuple[str, ...] = ()
    ruleset_trade_offs: tuple[str, ...] = ()
    if ruleset_facts is not None and ruleset_facts.figures:
        ruleset_ids = tuple(ruleset_fact(context.ledger, f).id
                            for f in ruleset_facts.figures)
        ruleset_trade_offs = (_ruleset_summary(ruleset_facts),)
```

then replace the single unconditional `unknowns.append(...)` — keeping it in
the same position in the list, so the order of an existing candidate's unknowns
is unchanged:

```python
    if ruleset_ids:
        unknowns.append("The figures above are read from your installed ruleset, not from "
                        "a guide. What this settlement is offered, and whether a placement "
                        "is legal, are still unknown.")
    else:
        unknowns.append("The installed ruleset is not recorded, so no figure for this "
                        "building is taken from any guide — only from your own preview.")
    unknowns.extend(m.as_unknown() for m in (ruleset_facts.mentions if ruleset_facts else ()))
```

and extend the two fields on the returned candidate:

```python
        evidence_ids=evidence_for(context, city, mechanic_key) + previews.fact_ids + ruleset_ids,
        trade_offs=trade_offs + ruleset_trade_offs + version_notes((entry,) + workflow),
```

with the summary helper beside `version_notes`:

```python
def _ruleset_summary(facts: BuildingFacts) -> str:
    """One sentence naming what the installed files say, and which file they are.

    Reads every figure off its own label and unit rather than picking out the ones this
    function expects: a building with only a prerequisite row still produces a correct
    sentence, and there is no index into a list that may be empty. Says the file and its
    digest rather than a version, because the database states no version — see
    docs/architecture/adr-002-ruleset-derived-figures.md.
    """
    said = "; ".join(f"{figure.label} {figure.value}"
                     + (f" {figure.unit}" if figure.unit else "")
                     for figure in facts.figures)
    return (f"Your installed ruleset states — {said}. Read from "
            f"{facts.figures[0].identity.describe()}.")
```

`_ruleset_summary` is only ever called when `facts.figures` is non-empty, which
is what makes `figures[0]` safe; the caller checks that before building it.

Note that `applicability` stays `Applicability.CONDITIONAL` and the
prerequisite list is untouched. A real cost changes what may be *stated*, not
what may be *assumed*: availability and placement are still things only the
screen can settle.

- [ ] **Step 6: Pass the profile's ruleset from the API**

In `civ_advisor/api/app.py`, at the `build_context(` call site:

```python
        context = build_context(
            snapshot, player=player, oracle=oracle,
            catalog=load_catalog(package=profile.knowledge_package),
            ruleset=profile.ruleset() if profile.ruleset else None)
```

Two things land together here: the catalog now follows the profile too, which
spec §7 records as the reason the per-game catalog split has no effect on what
a player sees. If phase 2b has already made that change, leave it alone and add
only the `ruleset=` argument.

- [ ] **Step 7: Run the tests and the full suite**

```bash
uv run pytest tests/test_ruleset_wiring.py -q
uv run pytest -q 2>&1 | tail -3
```

Expected: 6 passed, whole suite green **with no pre-existing assertion edited**.
If a Civ VII decision test fails here, the default is not reaching it — fix the
default, not the test.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "State a Civ VI building's real figures in the recommendation

The profile carries the ruleset factory; a game without one gets NO_RULESET,
which is the Civ VII behaviour unchanged."
```

---

### Task 8: The boundary tests, and writing down why the boundary is where it is

**One rough label to fix.** Boost figures embed raw column names, so a real
lookup produces `"Writing boost Unit1Type = UNIT_SCOUT"`. That is not a
localisation key and not a wrong figure, but `Unit1Type` is the database's
internal column name reaching the player as though it were a label. Either
give those columns readable labels or drop the ones that cannot be stated
plainly. The rest of this phase is careful that what reaches the player is
a fact rather than a row; this line is the exception.

**One conflation this task should resolve or record.** `building()` returns
`None` for three genuinely different situations: this subject has no row in
the ruleset; the provider is closed; and read-verify-reread exhausted its
retries because the file kept moving. The first is a fact about the
player's ruleset. The other two are facts about our ability to read it.

This project fixed exactly this conflation once before — phase 2a split
coverage into *not applicable* / *unavailable* / *partial* because "this
game does not log that" and "that log could not be read" are different
facts with different remedies. The same argument applies here: telling a
player a building has no recorded yield, when really the file was being
rewritten mid-read, is a false statement about their install.

Either give the caller a way to tell the three apart, or — if you judge
that unnecessary because the two failure paths are vanishingly rare in
practice — write down that reasoning explicitly, so the next person finds
an argued decision rather than an oversight. Do not leave it unaddressed
and unexplained.

The tests that would fail if someone later added `Modifiers` to the allowlist
because a number was needed, and the document that tells them why not to.

**Files:**
- Test: `tests/test_ruleset_boundary.py`
- Create: `docs/architecture/adr-002-ruleset-derived-figures.md`
- Modify: `docs/architecture/log-capability-matrix.md`
- Modify: `README.md` (the "Guides and figures" section, lines 128-145)
- Modify: `docs/superpowers/specs/2026-09-12-multi-game-advisor-design.md` (status line)

**Interfaces:**
- Consumes: everything above.
- Produces: no new code.

- [ ] **Step 1: Write the boundary tests**

Create `tests/test_ruleset_boundary.py`:

```python
import re
from dataclasses import fields

import pytest

from civ_advisor.decisions.evidence import EvidenceLedger, ruleset_fact
from civ_advisor.decisions.models import SourceKind
from civ_advisor.ruleset.base import (
    RulesetFigure, RulesetIdentity, RulesetMention, RulesetOutOfScope,
)
from civ_advisor.ruleset.civ6 import (
    COUNTABLE_COLUMNS, EFFECT_TABLES, READABLE_COLUMNS, clear_cache, open_ruleset,
)

from tests.ruleset_fixture import make_ruleset


@pytest.fixture
def ruleset(tmp_path):
    clear_cache()
    yield open_ruleset(make_ruleset(tmp_path))
    clear_cache()


def test_no_effect_table_is_readable_or_countable():
    """The allowlist, asserted from the other side. If someone adds one of these to make
    a number available, this fails before the number reaches a player."""
    assert EFFECT_TABLES.isdisjoint(READABLE_COLUMNS)
    assert EFFECT_TABLES.isdisjoint(COUNTABLE_COLUMNS)


def test_a_modifier_effect_never_surfaces_as_a_number(ruleset):
    """The Great Library's science effect. `ModifierArguments` says TechBoost=1, where 1
    is a flag meaning "apply the standard boost" and not a quantity of science. The
    advisor must be able to say the effect exists and must not be able to say how much.
    """
    facts = ruleset.building("BUILDING_GREAT_LIBRARY")

    assert facts is not None
    assert facts.yields == ()
    assert facts.mentions and all(isinstance(m, RulesetMention) for m in facts.mentions)
    assert all(not isinstance(m, RulesetFigure) for m in facts.mentions)
    # The one number in the chain is 1. It must appear nowhere in what a player is shown.
    unknown = facts.mentions[0].as_unknown()
    assert "does not state its magnitude" in unknown
    assert not re.search(r"\d", unknown.replace("1 conditional", ""))
    # And nothing derived from that building may be cited as a ruleset figure with a value
    # from an effect table.
    ledger = EvidenceLedger()
    for figure in facts.figures:
        ruleset_fact(ledger, figure)
    assert all(f.record_key[0] not in EFFECT_TABLES for f in ledger.facts.values())


def test_a_building_with_no_yield_rows_does_not_claim_to_yield_nothing(ruleset):
    """Only 79 building types have any Building_YieldChanges row. An empty list is not a
    finding, and the mention is what stops it being read as one."""
    facts = ruleset.building("BUILDING_GREAT_LIBRARY")

    assert "not evidence that this building yields nothing" in facts.mentions[0].as_unknown()


def test_every_readable_column_is_a_value_and_not_a_key_into_an_effect(ruleset):
    """A readable column must be the figure itself. A column named *ModifierId or
    *Modifier is a pointer into the system this phase excludes."""
    for table, columns in READABLE_COLUMNS.items():
        assert not [c for c in columns if "Modifier" in c], table


def test_no_ruleset_fact_claims_a_version_a_dlc_or_a_mod(ruleset):
    """The database names none of the three. A figure that implied one would be the exact
    inference this phase exists to avoid."""
    ledger = EvidenceLedger()
    for figure in ruleset.building("BUILDING_LIBRARY").figures:
        ruleset_fact(ledger, figure)

    assert ledger.facts
    for fact in ledger.facts.values():
        assert fact.source_kind is SourceKind.INSTALLED_RULESET
        note = (fact.note or "").lower()
        assert "version" not in note
        assert not re.search(r"\bv?\d+\.\d+(\.\d+)?\b", note)
        assert "rise and fall" not in note and "gathering storm" not in note
    assert "version" not in {f.name for f in fields(RulesetIdentity)}


def test_the_provider_refuses_a_modifier_query_loudly(ruleset):
    """Raised, not degraded. A caller reaching for a magnitude is a bug in the advisor,
    and must fail in tests rather than quietly return nothing in front of a player."""
    with pytest.raises(RulesetOutOfScope, match="magnitude"):
        ruleset._select("ModifierArguments", ("Value",), {"Name": "TechBoost"})
```

- [ ] **Step 2: Run them**

```bash
uv run pytest tests/test_ruleset_boundary.py -q
```

Expected: 6 passed. If `test_a_modifier_effect_never_surfaces_as_a_number`
fails on the digit check, the mention wording gained a number — fix the
wording, not the assertion.

- [ ] **Step 3: Write the ADR**

Create `docs/architecture/adr-002-ruleset-derived-figures.md`:

```markdown
# ADR-002: Figures read from an installed ruleset

Date: 2026-09-12
Status: proposed

## Context

Civilization VII gives the advisor no way to check a number. Its logs do not
record what a building yields or costs, and no packaged guide asserts a figure
verified against an installed ruleset — so the advisor asks the player to read
the game's own preview and records the answer as *your report*, dated to the
turn.

Civilization VI is different. It writes `Cache/DebugGameplay.sqlite`, the
compiled ruleset, 18 MB and 429 tables, queryable in under 20 ms. A Library
costs 90 production and 1 gold, needs a Campus and Writing, and yields a flat
+2 Science — each of those a plain indexed row.

Two problems follow. The database also contains an effect system whose numbers
are not numbers; and it identifies no version, so a figure from it cannot be
attributed to a ruleset by name.

## Decision

Read the plain rows. Refuse the effect system. Label with the file.

**Plain rows are stated as fact.** Building and district cost, maintenance,
prerequisites and flat yields; technology and civic cost, era and prerequisites;
eureka and inspiration percentages and triggers; unit cost, maintenance, combat
strength, prerequisites and upgrade target.

**The effect system is refused structurally, not by discipline.**
`Modifiers` -> `ModifierArguments` records that an effect fires, who it applies
to and what triggers it. Its magnitude is defined by an `EffectType` the
database does not catalogue: the Great Library's science modifier carries
`TechBoost=1`, where `1` is a flag meaning "apply the standard boost" and not a
quantity of science. Three mechanisms keep such a value from becoming a figure:

1. `READABLE_COLUMNS` is an allowlist of table-and-column pairs, and `_select`
   is the only place a statement is built. No effect table is in it.
2. `BuildingModifiers` — needed because an empty `Building_YieldChanges` result
   is not evidence that a building yields nothing — is reachable only through
   `_count`, which returns a row count and can carry no magnitude.
3. `RulesetFigure.__post_init__` requires a table, a column and a row key. A
   number with no row behind it cannot be constructed.

What an effect becomes instead is a `RulesetMention`, which has no value field
and renders as "this exists; the ruleset does not state its magnitude".

**Provenance is the file, not a version.** `PRAGMA user_version` is 0 and no
Version, DLC, Mod or Ruleset table exists. `XP1`/`XP2` table-name suffixes imply
both expansions are compiled in, and that is an inference we do not publish. A
figure is labelled with the filename, the time the game last wrote it, and a
SHA-256 of its bytes — reproducible by the reader, and changed by any mod that
rewrites the ruleset. `RulesetIdentity` has no version field, so there is
nowhere for one to be added by accident.

## Trade-offs and consequences

- Civ VI recommendations get better figures than Civ VII ones, and the two games
  will visibly differ. That is a real capability divergence, and the UI says
  which source each figure came from rather than hiding it.
- A number the player can see in game — a policy card's effect, a government
  bonus, a wonder ability — will not be quoted here. Saying "the ruleset does
  not state this" about something visible on screen looks like a gap. It is the
  correct answer, and the alternative is an authoritative-looking guess.
- A cached provider is keyed on the file's size and modification time, so a mod
  applied mid-session re-derives on the next lookup. A stale figure would be
  indistinguishable from a verified one, which is why the cache never serves
  across a change.
- Reading the player's own game file is a trust boundary. It is opened `mode=ro`
  with `PRAGMA query_only = 1`, and nothing in this package writes anywhere.

## Revisit triggers

Reconsider the effect system only with a hand-built, versioned table of
`EffectType` argument semantics, validated against observed game behaviour and
shipped with its own review status — the same bar the guide catalog holds to.
Reconsider the version question if Firaxis ever writes an identity table.
Reconsider adjacency yields once the join from a district to its adjacency ids
has actually been verified against a real install.
```

- [ ] **Step 4: Record the capability**

In `docs/architecture/log-capability-matrix.md`, add a row to the table
introduced in phase 1, in whatever shape that table now takes:

```markdown
| Installed ruleset figures (cost, prereqs, flat yields) | No — nothing to query | Yes — `Cache/DebugGameplay.sqlite`, plain rows only; conditional effects are not derivable (ADR-002) |
```

- [ ] **Step 5: Amend the README's claim**

`README.md` lines 128-145 make an unqualified promise that is now true of
Civ VII and not of Civ VI. Replace the first paragraph of **Guides and figures**
with:

```markdown
No figure in a recommendation comes from a wiki or from this advisor's own
guesses. For Civilization VII that means every figure comes from you: the logs
do not record what a building yields, what a settlement can build, what is
unlocked, or what a placement would cost, and no packaged guide asserts a number
verified against an installed ruleset. For Civilization VI, which ships its
compiled ruleset as a queryable database, costs, prerequisites and flat yields
are read from your own installed game files and labelled *your installed
ruleset* — with the file's timestamp and digest, never a version number, because
the file states none. Conditional effects — policy cards, government and wonder
abilities — are not derivable even there, and are never quoted. See
[docs/architecture/adr-002-ruleset-derived-figures.md](docs/architecture/adr-002-ruleset-derived-figures.md)
for where that boundary is and why, and
[docs/architecture/log-capability-matrix.md](docs/architecture/log-capability-matrix.md)
for exactly what is and is not knowable.
```

Leave the following paragraph, about **Refine this recommendation** and *your
report*, exactly as it is: it remains the whole of the Civ VII flow and the
larger part of the Civ VI one.

- [ ] **Step 6: Mark the phase in the spec**

Change the spec's status line to:

```markdown
**Status:** Phases 1 and 4 implemented on `feature/multi-game-advisor`; phases 2 and 3 in progress
```

Adjust to match what has actually landed when this task runs — do not claim a
phase that has not.

- [ ] **Step 7: Run everything one last time**

```bash
uv run pytest -q 2>&1 | tail -3
```

Expected: zero failures, and **48** tests more than the baseline recorded before
Task 1: 6 contracts, 6 evidence, 14 in `test_ruleset_civ6.py` (8 from Task 3 and
6 from Task 6), 4 identity, 6 open, 6 wiring, 6 boundary. Confirm no
pre-existing test was deleted or had an assertion changed:

```bash
git diff --stat main -- tests/ | tail -5
```

Expected: only new test files, plus `tests/ruleset_fixture.py`.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "Record why the ruleset boundary is where it is

ADR-002, the capability matrix row, and the README's figures claim made
per-game. Tests prove a modifier effect never surfaces as a number and that
no ruleset figure claims a version."
```

---

## Done when

- `uv run pytest` is green, with every pre-existing test unmodified.
- A Civ VI recommendation naming a building states that building's real cost,
  maintenance and flat yield, each citable to a table, a column and a row.
- A Civ VII recommendation is byte-for-byte what it was before this phase,
  including the sentence "The installed ruleset is not recorded, so no figure
  for this building is taken from any guide — only from your own preview."
- Deleting the database, truncating it, or renaming one of its columns each
  produce a recommendation that asks the player, and a `reason` saying why.
- `grep -rn 'ModifierArguments\|RequirementSets' civ_advisor/` returns only the
  refusal path in `civ6.py` and its docstrings — no query.
- No file under `civ_advisor/advisors/` was modified by this phase. If one was,
  the ruleset reached the advisor layer instead of the decision layer — stop and
  report it.
