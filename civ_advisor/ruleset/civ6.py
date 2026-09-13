"""The installed Civilization VI ruleset, read from the game's own cache database.

`Cache/DebugGameplay.sqlite` is written by the game and holds the compiled ruleset: what
a building costs, what it needs, what it yields. That makes VI the one game here where a
figure in a recommendation can be stated as fact rather than asked for.

What this module will *not* read is as deliberate as what it reads. The effect system
(`Modifiers` -> `ModifierArguments`) records that an effect fires, who it applies to and
what triggers it, while its magnitude is defined by the game's compiled logic and by no
row anywhere. `READABLE_COLUMNS` is the allowlist of plain indexed columns; `_select` is
the only place a statement is built, and it refuses anything outside it. `BuildingModifiers`
is reachable only through `_count`, which returns a row count and never a value, so the
most an effect can become is a `RulesetCount` (how many) alongside a `RulesetMention`
(what that means in words) -- never a `RulesetFigure`.

Also read here, all plain indexed rows per the research report: districts,
technologies and civics (with their eureka/inspiration `Boosts`), and units. Deliberately
not read, each for a reason in the research report: district adjacency yields (the join
from a district to its adjacency ids was not verified), government slot counts (the
correct join was not found), policy effects (the same `Modifiers` indirection this
module excludes everywhere else), the gold cost of a unit upgrade (computed at runtime,
stored in no row), and per-unit strategic resource quantity (a table not explored).

Two different kinds of "cannot answer" are told apart on purpose:

  - **absent data.** A query inside the allowlist runs cleanly and returns no rows -- the
    installed ruleset simply has nothing to say about this building. `building()` returns
    `None`; nothing was wrong with the file.
  - **an unexpected schema.** A query inside the allowlist fails at the database itself
    (`sqlite3.OperationalError`: no such table, no such column) because a mod or a patch
    reshaped a table this provider assumes exists in a known shape. This is not the same
    as `RulesetOutOfScope`, which means *this module's own code* asked for something
    outside the allowlist -- a bug here, not a fact about the player's install. An
    unexpected schema degrades to the same `None` that absent data does, so a mod never
    turns into a raw sqlite error reaching the advisor, and never into a silently wrong
    number either -- but the two are still told apart by the caller: `schema_complaint`
    reports what is wrong with the shape of the tables a given lookup reads, and a caller
    may state "no such row" only when that reports nothing. A `None` on its own is not
    evidence of a missing row, and saying so asserts a fact about the player's file that
    nothing ever read.
"""
from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from .base import (
    BoostFacts, BuildingFacts, CivicFacts, DistrictFacts, GovernmentFacts,
    ImprovementFacts, NullRuleset, PolicyFacts, ResourceFacts, RulesetCount,
    RulesetFigure, RulesetIdentity, RulesetMention, RulesetOutOfScope, RulesetProvider,
    TechnologyFacts, UnitFacts,
)
from .identity import identify, stamp

DATABASE_NAME = "DebugGameplay.sqlite"
DEFAULT_DATABASE = (Path.home() / "Library" / "Application Support"
                    / "Sid Meier's Civilization VI" / "Firaxis Games"
                    / "Sid Meier's Civilization VI" / "Cache" / DATABASE_NAME)

# The only columns this provider may read, by table. Every one is a plain indexed value
# that *is* the figure — not a key into an effect the database does not describe. The keys
# of this mapping are also the table allowlist, so there is one list to keep honest rather
# than two that can drift apart.
READABLE_COLUMNS: dict[str, frozenset[str]] = {
    "Buildings": frozenset({"BuildingType", "Cost", "Maintenance", "PrereqDistrict",
                            "PrereqTech", "PrereqCivic", "Housing", "Entertainment",
                            "CitizenSlots", "IsWonder", "RequiresPlacement"}),
    "Building_YieldChanges": frozenset({"BuildingType", "YieldType", "YieldChange"}),
    "Districts": frozenset({"DistrictType", "Cost", "PrereqTech", "PrereqCivic", "Housing",
                            "Entertainment", "CitizenSlots", "Maintenance"}),
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
                        "PrereqTech", "PrereqCivic", "StrategicResource", "BaseMoves",
                        "Range", "Domain", "PromotionClass"}),
    "UnitUpgrades": frozenset({"Unit", "UpgradeUnit"}),
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
}

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


# Which of the ~10 nullable trigger-object columns on `Boosts` is populated is what says
# what kind of trigger a boost has; there is no single "trigger value" column.
BOOST_OBJECT_COLUMNS = ("Unit1Type", "BuildingType", "DistrictType", "NumItems")

# Readable labels for those columns. Without this, a boost's object figure carries the
# database's own column name as its label -- "Writing boost Unit1Type = UNIT_SCOUT" --
# which is not a localisation key and not a wrong figure, but is the database's internal
# name reaching a player as though it were one. The rest of this phase is careful that
# what reaches a player is a fact stated in words, not a row; this dict is what keeps
# this one corner from being the exception.
BOOST_OBJECT_LABELS = {
    "Unit1Type": "unit",
    "BuildingType": "building",
    "DistrictType": "district",
    "NumItems": "count",
}


def _absent(value) -> bool:
    """Whether a column value says nothing at all.

    `None` means the row has no such column value; an empty string is how this
    database spells "no prerequisite". Neither is a number to state.

    Deliberately does NOT treat 0 as absence here. Review found that it used to: a
    building with `Maintenance = 0` produced no figure, so `gold_upkeep` stayed
    unstated and a later comparison could say "either option costs 1 gold" when the
    ruleset said one of them cost nothing. A stated zero -- free upkeep, a zero
    production cost -- is a real fact and must be stated as one, not suppressed as
    though the row said nothing.
    """
    return value is None or value == ""


def _zero_is_absent(value) -> bool:
    """For `Units.RangedCombat` only: a melee unit's row genuinely stores 0 there, and
    that 0 means "this unit has no ranged attack", not "attacks at zero strength" --
    the schema has no other way to spell "not applicable" for a combat-strength column.
    This is the narrow, named exception to `_absent` above, not a general rule; nothing
    else in this module calls it.
    """
    return _absent(value) or value == 0


# Which allowlisted table, columns and key column each lookup's PRIMARY read uses.
# One place, read by the reader itself and by `schema_complaint` below, so the two can
# never drift into different ideas of what this lookup touches -- the whole point of the
# complaint is that it describes the read that actually failed.
LOOKUP_SOURCES: dict[str, tuple[tuple[str, tuple[str, ...], str], ...]] = {
    "parameter": (("GlobalParameters", ("Value",), "Name"),),
    "improvement": (("Improvements", ("PrereqTech", "PrereqCivic", "Housing"),
                     "ImprovementType"),),
    "policy": (("Policies", ("GovernmentSlotType", "PrereqCivic"), "PolicyType"),),
    "government": (("Governments", ("PrereqCivic", "Tier"), "GovernmentType"),
                   ("Government_SlotCounts", ("GovernmentSlotType", "NumSlots"),
                    "GovernmentType")),
    "resource": (("Resources", ("ResourceClassType", "Happiness", "PrereqTech",
                                "PrereqCivic"), "ResourceType"),),
    "building": (("Buildings", ("Cost", "Maintenance", "PrereqDistrict", "PrereqTech",
                                "PrereqCivic", "Housing", "Entertainment", "CitizenSlots",
                                "IsWonder", "RequiresPlacement"), "BuildingType"),),
    "district": (("Districts", ("Cost", "PrereqTech", "PrereqCivic", "Housing",
                                "Entertainment", "CitizenSlots", "Maintenance"),
                  "DistrictType"),),
    "technology": (("Technologies", ("Cost", "EraType"), "TechnologyType"),),
    "civic": (("Civics", ("Cost", "EraType"), "CivicType"),),
    "unit": (("Units", ("Cost", "Maintenance", "Combat", "RangedCombat", "PrereqTech",
                        "PrereqCivic", "StrategicResource", "BaseMoves", "Range", "Domain",
                        "PromotionClass"), "UnitType"),),
}


@dataclass
class Civ6Ruleset:
    """One open, read-only view of one ruleset database.

    Constructed by `open_ruleset` (Task 5), which owns the caching and the degradation.
    Constructing one directly opens a connection that the caller must `close()`.

    A provider `open_ruleset` already handed out can be closed out from under a caller
    still holding it -- `clear_cache()` closes every cached provider for a game switch,
    and a rebuild that was already mid-flight against the old one does not know that
    happened. `_closed` is what makes that state explicit and checkable rather than an
    accident of whichever `sqlite3` exception a closed connection happens to raise:
    `close()` sets it, and every lookup checks it first and degrades -- `available`
    becomes False, `reason` explains why, `building()` returns `None` -- rather than
    ever touching the closed connection and letting `sqlite3.ProgrammingError` reach the
    advisor.
    """

    _identity: RulesetIdentity
    _connection: sqlite3.Connection
    _countable: frozenset[str] = frozenset()
    _cache: dict[tuple[str, str], object] = field(default_factory=dict, repr=False)
    _closed: bool = False

    @property
    def available(self) -> bool:
        return not self._closed

    @property
    def reason(self) -> str | None:
        if self._closed:
            return (f"{self._identity.path.name} was closed (the game was switched or "
                    "reloaded while this reference was still in use), so no figure is "
                    "taken from it now; the advisor will ask you for the game's own "
                    "preview instead.")
        return None

    def identity(self) -> RulesetIdentity | None:
        return self._identity

    def close(self) -> None:
        self._connection.close()
        self._closed = True

    def schema_complaint(self, kind: str) -> str | None:
        """What is wrong with the shape of the tables THIS lookup reads, or None if they
        are as this provider expects and a `None` result therefore means "no such row".

        Consulted when a lookup came back empty, to tell a MISSING ROW -- a fact about
        the player's install -- apart from a table a mod or a patch reshaped, where the
        query failed at the database and nothing about rows was ever established.
        Claiming the first when the second happened asserts a fact about the player's
        file that was never read, which is the defect this exists to stop.

        A failure to check is itself reported rather than read as "fine": the advisor
        would otherwise fall back on the missing-row claim by the same inference.
        """
        if self._closed:
            return None     # `available`/`reason` already say this, ahead of any lookup
        for table, columns, key in LOOKUP_SOURCES.get(kind, ()):
            try:
                present = {row[0] for row in self._connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
                    (table,))}
                if not present:
                    return f"has no {table} table"
                found = {row["name"] for row in
                         self._connection.execute(f"PRAGMA table_info({table})")}
            except sqlite3.Error as exc:
                return (f"could not be read to say whether its {table} table is the shape "
                        f"this advisor expects ({exc})")
            missing = sorted(({key} | set(columns)) - found)
            if missing:
                return f"{table} table has no {', '.join(missing)} column"
        return None

    def _refresh_if_changed(self) -> None:
        """Re-derive identity from the file's current bytes, and drop every cached
        figure if the digest has moved.

        No cheap fast path. An earlier version of this method gated the hash behind
        `stamp()` (size, mtime) and only re-derived when that disagreed; review found
        the two claims could not both be true at once -- `stamp()`'s own docstring
        admits a same-size edit or a coarse filesystem clock can leave it unchanged,
        while this method's docstring claimed such a change was "caught". Measured
        against a real 18.1 MB installed database, the full hash costs about 15 ms and
        a cached lookup costs 0.1 ms; for an interactive advisor that rebuilds on a
        poll tick, neither is worth trading correctness for, so this now always
        re-derives rather than trusting a proxy that can miss the exact case it exists
        to catch. What this still cannot see: a file rewritten between the moment this
        method reads it and the moment `building()`'s row queries run a moment later --
        `building()` re-verifies that specific window itself, below.
        """
        fresh = identify(self._identity.path)
        if fresh.digest != self._identity.digest:
            self._cache.clear()
        self._identity = fresh

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

    # A persistent race after this many tries means "cannot get a stable read", not
    # "keep trying forever" -- a file being rewritten on every attempt is not this
    # provider's problem to solve, and the honest answer at that point is "cannot
    # answer", the same as any other degraded case.
    _MAX_READ_ATTEMPTS = 3

    def _read_verified(self, kind: str, key: str, reader) -> object | None:
        """Run one lookup's `reader`, verify the whole read came from one state of the
        file, and cache a stable result. Shared by every lookup (`building`, `district`,
        `technology`, `civic`, `unit`) so the closed check, the retry loop and the cache
        are one implementation rather than five that could drift apart.

        `identify()` reads raw bytes outside SQLite's own consistency guarantees, while
        `reader` reads through the connection. In the default rollback-journal mode
        SQLite writes pages into the main file during a transaction and only makes that
        atomic at commit, so an external write landing mid-transaction could in
        principle leave the raw digest and the row read describing two different states
        of the file -- a figure whose citation does not match the bytes it came from,
        which is worse than no figure. Read-verify-reread closes that window: the
        digest is captured before `reader` runs and re-derived after, and a mismatch
        discards everything just read and retries against the file's new state rather
        than serving a figure assembled from a moving target.

        Returns `None` immediately, touching neither the connection nor the file, if
        this provider has been closed out from under its caller -- see the class
        docstring.

        THE THREE-WAY `None`, ARGUED RATHER THAN LEFT UNEXAMINED. Every lookup built on
        this returns `None` for three different situations: (1) this subject has no row
        in the ruleset, a fact about the player's install; (2) `self._closed`, a fact
        about this provider's own lifecycle; (3) `_MAX_READ_ATTEMPTS` exhausted because
        the file would not hold still, a fact about this one read. Phase 2a split log
        coverage into not-applicable / unavailable / partial for exactly this reason --
        "this game does not log that" and "that log could not be read" are different
        facts with different remedies -- and the same argument applies here on its face.

        It is not applied the same way, for a reason specific to this case rather than a
        shortcut: (2) is already distinguishable BEFORE calling a lookup at all, via
        `available`/`reason` on the provider itself -- the project's existing
        per-provider degradation signal, not a new one invented for this method. A
        caller that checks `available` first already has "my own read failed" separated
        from "the ruleset has nothing to say", without any of `BuildingFacts`,
        `DistrictFacts`, `TechnologyFacts`, `CivicFacts` or `UnitFacts` needing a fourth
        state bolted on. What is left conflated is narrower: (1) versus (3) alone.

        That narrower case is judged not worth a fourth state, and here is why: (3)
        requires the SAME file to be rewritten enough times to exhaust every attempt
        within the few milliseconds one lookup takes -- unlike phase 2a's log files,
        which can stay unreadable indefinitely (a missing reader, a permissions error,
        a game that never writes that log at all), this is a race that resolves itself.
        The very next lookup for the same subject, moments later, almost certainly
        returns a stable answer either way. A caller that treats a `None` it got as "no
        row" when it was actually a still-resolving race sees that corrected on its next
        poll tick, which is the same bound this project already accepts for a mod
        toggle. If this reasoning is ever found wrong -- if (3) turns out not to be rare
        in practice -- the fix is to give the caller the distinction, not to have missed
        that it needed one.
        """
        if self._closed:
            return None
        self._refresh_if_changed()
        cached = self._cache.get((kind, key))
        if cached is not None:
            return cached

        for _ in range(self._MAX_READ_ATTEMPTS):
            before = self._identity
            result = reader()
            after = identify(self._identity.path)
            if after.digest == before.digest:
                if result is not None:
                    self._cache[(kind, key)] = result
                self._identity = after
                return result
            # The file moved while this was being read. Every figure just built cites
            # `before`, which no longer describes the file -- discard all of it and
            # retry against the state `after` actually observed.
            self._identity = after
            self._cache.clear()
        return None

    def _figure_maker(self, table: str, subject: str, row_key: tuple[str, ...],
                      row: sqlite3.Row):
        """One row's figures, each naming that row. Shared so every lookup cannot drift
        into slightly different ideas of what counts as absent."""

        def make(column: str, label: str, unit: str | None,
                *, zero_is_absent: bool = False) -> RulesetFigure | None:
            value = row[column]
            if (_zero_is_absent(value) if zero_is_absent else _absent(value)):
                return None
            return RulesetFigure(subject=subject, label=label, value=value, unit=unit,
                                 table=table, column=column, row_key=row_key,
                                 identity=self._identity)

        return make

    def _yield_figures(self, table: str, key_column: str, subject: str,
                       label: str) -> tuple[RulesetFigure, ...]:
        """Every flat yield row for one subject, shared by improvements and resources
        the same way `Building_YieldChanges` is read inline for buildings."""
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
        table, columns, key = LOOKUP_SOURCES["parameter"][0]
        try:
            rows = self._select(table, columns, {key: name})
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
        table, columns, key = LOOKUP_SOURCES["improvement"][0]
        try:
            rows = self._select(table, columns, {key: improvement_type})
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
        table, columns, key = LOOKUP_SOURCES["policy"][0]
        try:
            rows = self._select(table, columns, {key: policy_type})
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
        (table, columns, key), (slot_table, slot_columns, slot_key) = \
            LOOKUP_SOURCES["government"]
        try:
            rows = self._select(table, columns, {key: government_type})
            slot_rows = self._select(slot_table, slot_columns, {slot_key: government_type})
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
        table, columns, key = LOOKUP_SOURCES["resource"][0]
        try:
            rows = self._select(table, columns, {key: resource_type})
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

    def building(self, building_type: str) -> BuildingFacts | None:
        return self._read_verified(
            "building", building_type, lambda: self._read_building(building_type))

    def _read_building(self, building_type: str) -> BuildingFacts | None:
        """One attempt at reading a building's figures, against whatever state of the
        file is current when it runs. Never itself decides whether that state held
        still; `_read_verified` is what verifies that and retries."""
        table, columns, key = LOOKUP_SOURCES["building"][0]
        try:
            rows = self._select(table, columns, {key: building_type})
        except sqlite3.OperationalError:
            # The installed ruleset's schema does not match what this provider expects
            # (a mod or a patch reshaped `Buildings`) -- degrade to "cannot answer",
            # never raise a raw sqlite error into the advisor.
            return None
        if not rows:
            return None
        row, name = rows[0], _title(building_type)
        make = self._figure_maker("Buildings", building_type, (building_type,), row)

        try:
            yield_rows = self._select("Building_YieldChanges",
                                      ("YieldType", "YieldChange"),
                                      {"BuildingType": building_type})
        except sqlite3.OperationalError:
            yield_rows = ()

        yields = tuple(
            RulesetFigure(
                subject=building_type,
                label=f"{name} {_yield_label(y['YieldType'])} yield",
                value=y["YieldChange"], unit="per turn",
                table="Building_YieldChanges", column="YieldChange",
                row_key=(building_type, y["YieldType"]), identity=self._identity)
            for y in yield_rows)

        mentions, counts = self._effect_facts(building_type, bool(yields))
        return BuildingFacts(
            building=building_type,
            cost=make("Cost", f"{name} production cost", "production"),
            maintenance=make("Maintenance", f"{name} maintenance", "gold per turn"),
            prereq_district=make("PrereqDistrict", f"{name} requires district", None),
            prereq_tech=make("PrereqTech", f"{name} requires technology", None),
            prereq_civic=make("PrereqCivic", f"{name} requires civic", None),
            housing=make("Housing", f"{name} housing", "housing"),
            entertainment=make("Entertainment", f"{name} amenities", "amenities"),
            citizen_slots=make("CitizenSlots", f"{name} citizen slots", "slots"),
            is_wonder=make("IsWonder", f"{name} is a wonder", None),
            requires_placement=make("RequiresPlacement", f"{name} requires plot placement",
                                    None),
            yields=yields, mentions=mentions, counts=counts,
        )

    def _effect_facts(self, building_type: str,
                      has_yields: bool) -> tuple[tuple[RulesetMention, ...],
                                                 tuple[RulesetCount, ...]]:
        """What a building does beyond its flat yields: a count of modifier-chain rows,
        never their magnitude, plus a sentence putting that count in words.

        Only some building types have any `Building_YieldChanges` row, so an empty yield
        list is not evidence that a building does nothing — some express their whole
        effect through a modifier. Counting is what stops "no rows, therefore no yield"
        from becoming a claim. The count itself is a `RulesetCount`, not a
        `RulesetFigure`: it has no `value`/`unit` field to carry a number a reader could
        mistake for a yield, so it cannot reach a player looking like one.
        """
        if "BuildingModifiers" not in self._countable:
            return (), ()
        try:
            n = self._count("BuildingModifiers", {"BuildingType": building_type})
        except sqlite3.OperationalError:
            return (), ()
        if not n:
            return (), ()
        count = RulesetCount(
            subject=building_type,
            label=f"{_title(building_type)} modifier-based effects beyond its flat yields",
            count=n, table="BuildingModifiers", column="COUNT(*)",
            row_key=(building_type,), identity=self._identity)
        mention = RulesetMention(
            subject=building_type,
            label=(f"{_title(building_type)} has {n} conditional effect"
                   f"{'' if n == 1 else 's'} beyond its flat yields"),
            detail=("The ruleset records what each one applies to and what triggers it, in "
                    "a modifier chain whose magnitude is defined by the game's own code and "
                    "by no row in this file."
                    + ("" if has_yields else
                       " The absence of a flat yield is therefore not evidence that this "
                       "building yields nothing.")),
        )
        return (mention,), (count,)

    def district(self, district_type: str) -> DistrictFacts | None:
        return self._read_verified(
            "district", district_type, lambda: self._read_district(district_type))

    def _read_district(self, district_type: str) -> DistrictFacts | None:
        table, columns, key = LOOKUP_SOURCES["district"][0]
        try:
            rows = self._select(table, columns, {key: district_type})
        except sqlite3.OperationalError:
            return None
        if not rows:
            return None
        row, name = rows[0], _title(district_type)
        make = self._figure_maker("Districts", district_type, (district_type,), row)
        return DistrictFacts(
            district=district_type,
            cost=make("Cost", f"{name} district production cost", "production"),
            prereq_tech=make("PrereqTech", f"{name} district requires technology", None),
            prereq_civic=make("PrereqCivic", f"{name} district requires civic", None),
            housing=make("Housing", f"{name} district housing", "housing"),
            entertainment=make("Entertainment", f"{name} district amenities", "amenities"),
            citizen_slots=make("CitizenSlots", f"{name} district citizen slots", "slots"),
            maintenance=make("Maintenance", f"{name} district maintenance", "gold per turn"))

    def _boosts(self, column: str, subject: str) -> tuple[BoostFacts, ...]:
        """Every eureka or inspiration attached to one technology or civic."""
        try:
            rows = self._select("Boosts",
                                ("BoostID", "Boost", "BoostClass") + BOOST_OBJECT_COLUMNS,
                                {column: subject})
        except sqlite3.OperationalError:
            return ()
        out = []
        for row in rows:
            key = (str(row["BoostID"]),)
            make = self._figure_maker("Boosts", subject, key, row)
            percent = make("Boost", f"{_title(subject)} boost", "% of the cost")
            trigger = make("BoostClass", f"{_title(subject)} boost trigger", None)
            if percent is None or trigger is None:
                continue
            objects = tuple(
                f for f in (make(c, f"{_title(subject)} boost {BOOST_OBJECT_LABELS[c]}", None)
                           for c in BOOST_OBJECT_COLUMNS) if f is not None)
            out.append(BoostFacts(percent=percent, trigger=trigger, objects=objects))
        return tuple(out)

    def technology(self, technology_type: str) -> TechnologyFacts | None:
        return self._read_verified(
            "technology", technology_type,
            lambda: self._read_technology(technology_type))

    def _read_technology(self, technology_type: str) -> TechnologyFacts | None:
        table, columns, key = LOOKUP_SOURCES["technology"][0]
        try:
            rows = self._select(table, columns, {key: technology_type})
        except sqlite3.OperationalError:
            return None
        if not rows:
            return None
        name = _title(technology_type)
        make = self._figure_maker("Technologies", technology_type, (technology_type,),
                                  rows[0])
        try:
            prereq_rows = self._select("TechnologyPrereqs", ("PrereqTech",),
                                       {"Technology": technology_type})
        except sqlite3.OperationalError:
            prereq_rows = ()
        prereqs = tuple(
            RulesetFigure(subject=technology_type, label=f"{name} requires technology",
                          value=r["PrereqTech"], unit=None, table="TechnologyPrereqs",
                          column="PrereqTech",
                          row_key=(technology_type, r["PrereqTech"]),
                          identity=self._identity)
            for r in prereq_rows)
        return TechnologyFacts(
            technology=technology_type,
            cost=make("Cost", f"{name} research cost", "science"),
            era=make("EraType", f"{name} era", None),
            prereqs=prereqs, boosts=self._boosts("TechnologyType", technology_type))

    def civic(self, civic_type: str) -> CivicFacts | None:
        return self._read_verified(
            "civic", civic_type, lambda: self._read_civic(civic_type))

    def _read_civic(self, civic_type: str) -> CivicFacts | None:
        table, columns, key = LOOKUP_SOURCES["civic"][0]
        try:
            rows = self._select(table, columns, {key: civic_type})
        except sqlite3.OperationalError:
            return None
        if not rows:
            return None
        name = _title(civic_type)
        make = self._figure_maker("Civics", civic_type, (civic_type,), rows[0])
        try:
            prereq_rows = self._select("CivicPrereqs", ("PrereqCivic",),
                                       {"Civic": civic_type})
        except sqlite3.OperationalError:
            prereq_rows = ()
        prereqs = tuple(
            RulesetFigure(subject=civic_type, label=f"{name} requires civic",
                          value=r["PrereqCivic"], unit=None, table="CivicPrereqs",
                          column="PrereqCivic",
                          row_key=(civic_type, r["PrereqCivic"]),
                          identity=self._identity)
            for r in prereq_rows)
        return CivicFacts(
            civic=civic_type,
            cost=make("Cost", f"{name} culture cost", "culture"),
            era=make("EraType", f"{name} era", None),
            prereqs=prereqs, boosts=self._boosts("CivicType", civic_type))

    def unit(self, unit_type: str) -> UnitFacts | None:
        return self._read_verified("unit", unit_type, lambda: self._read_unit(unit_type))

    def _read_unit(self, unit_type: str) -> UnitFacts | None:
        table, columns, key = LOOKUP_SOURCES["unit"][0]
        try:
            rows = self._select(table, columns, {key: unit_type})
        except sqlite3.OperationalError:
            return None
        if not rows:
            return None
        name = _title(unit_type)
        make = self._figure_maker("Units", unit_type, (unit_type,), rows[0])

        try:
            upgrade_rows = self._select("UnitUpgrades", ("UpgradeUnit",),
                                        {"Unit": unit_type})
        except sqlite3.OperationalError:
            upgrade_rows = ()
        upgrades_to = None
        mentions: tuple[RulesetMention, ...] = ()
        if upgrade_rows:
            upgrades_to = RulesetFigure(
                subject=unit_type, label=f"{name} upgrades to",
                value=upgrade_rows[0]["UpgradeUnit"], unit=None, table="UnitUpgrades",
                column="UpgradeUnit", row_key=(unit_type,), identity=self._identity)
            mentions = (RulesetMention(
                subject=unit_type, label=f"{name}'s upgrade has a gold cost",
                detail=("The ruleset states what it upgrades into and stores no row for "
                        "what that costs; the game computes it at the moment you "
                        "upgrade.")),)

        return UnitFacts(
            unit=unit_type,
            cost=make("Cost", f"{name} production cost", "production"),
            maintenance=make("Maintenance", f"{name} maintenance", "gold per turn"),
            combat=make("Combat", f"{name} combat strength", "combat strength"),
            ranged_combat=make("RangedCombat", f"{name} ranged strength",
                               "combat strength", zero_is_absent=True),
            prereq_tech=make("PrereqTech", f"{name} requires technology", None),
            prereq_civic=make("PrereqCivic", f"{name} requires civic", None),
            strategic_resource=make("StrategicResource", f"{name} requires resource", None),
            upgrades_to=upgrades_to,
            moves=make("BaseMoves", f"{name} moves", "moves"),
            # `Range` on a melee unit's row genuinely stores 0, meaning "no ranged
            # attack" -- the same shape as `RangedCombat` above, but here 0 is still a
            # stated fact (a unit's range being 0 is what makes it melee), not a
            # meaningless placeholder, so it is deliberately NOT `zero_is_absent`.
            range=make("Range", f"{name} range", "tiles"),
            domain=make("Domain", f"{name} domain", None),
            promotion_class=make("PromotionClass", f"{name} promotion class", None),
            mentions=mentions)

    # -- construction --------------------------------------------------------------

    @classmethod
    def open(cls, path: Path) -> "Civ6Ruleset":
        """Open the file read-only. Raises `sqlite3.DatabaseError` if it is not a database;
        Task 5's `open_ruleset` is what turns that into a degraded provider."""
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


# -- opening, caching and degrading ------------------------------------------------

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
    A provider this function already returned keeps degrading gracefully after
    `clear_cache()` closes it too: see `Civ6Ruleset.available`/`.reason`/`.building()`.

    `_LOCK` guards only `_OPEN` itself, never the file work. Opening a connection and
    hashing an 18 MB file (~15 ms) happens outside it, so one caller's open of one path
    cannot serialise a concurrent caller opening a different one -- or, with a cache hit,
    opening the same one. The recheck after that unlocked work is what stops two threads
    that both missed the cache from publishing two different providers for one path: the
    second to finish closes its own connection and returns the first's instead.
    """
    path = (path or DEFAULT_DATABASE).expanduser()
    try:
        current = stamp(path)
    except OSError as exc:
        with _LOCK:
            _forget(path)
        return NullRuleset(
            f"{path.name} was not readable ({exc.strerror or exc}), so no figure is "
            "taken from your installed ruleset; the advisor will ask you for the "
            "game's own preview instead.")

    with _LOCK:
        cached = _OPEN.get(path)
        if cached is not None and cached[0] == current:
            return cached[1]

    # Everything from here down is file IO -- deliberately outside `_LOCK`.
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

    with _LOCK:
        already = _OPEN.get(path)
        if already is not None and already[0] == current:
            # Another thread opened and published this same path, at this same
            # identity, while we were doing our own IO above. Keep the one already
            # published rather than two live connections to one file; ours is surplus.
            provider.close()
            return already[1]
        _forget(path)
        _OPEN[path] = (current, provider)
        return provider


def _forget(path: Path) -> None:
    """Drop a cached provider. Caller holds `_LOCK`."""
    previous = _OPEN.pop(path, None)
    if previous is not None:
        previous[1].close()
