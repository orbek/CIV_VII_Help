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
most an effect can become is a `RulesetMention`.

Two different kinds of "cannot answer" are told apart on purpose:

  - **absent data.** A query inside the allowlist runs cleanly and returns no rows -- the
    installed ruleset simply has nothing to say about this building. `building()` returns
    `None`; nothing was wrong with the file.
  - **an unexpected schema.** A query inside the allowlist fails at the database itself
    (`sqlite3.OperationalError`: no such table, no such column) because a mod or a patch
    reshaped a table this provider assumes exists in a known shape. This is not the same
    as `RulesetOutOfScope`, which means *this module's own code* asked for something
    outside the allowlist -- a bug here, not a fact about the player's install. An
    unexpected schema instead degrades the same way absent data does: `building()` catches
    it and returns `None`, so a mod never turns into a raw sqlite error reaching the
    advisor, and never into a silently wrong number either.
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


def _identify_placeholder(path: Path) -> RulesetIdentity:
    """Stands in for Task 4's `identify()`, which produces the real content digest.

    Removed once Task 4 lands `civ_advisor.ruleset.identity`; until then every ruleset
    reports the same all-zero digest, which is wrong but harmless -- nothing here compares
    digests across instances yet.
    """
    stat = path.stat()
    return RulesetIdentity(path=path, size=stat.st_size, mtime_ns=stat.st_mtime_ns,
                           digest="0" * 64)


identify = _identify_placeholder


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
        try:
            rows = self._select("Buildings",
                                ("Cost", "Maintenance", "PrereqDistrict", "PrereqTech",
                                 "PrereqCivic"),
                                {"BuildingType": building_type})
        except sqlite3.OperationalError:
            # The installed ruleset's schema does not match what this provider expects
            # (a mod or a patch reshaped `Buildings`) -- degrade to "cannot answer",
            # never raise a raw sqlite error into the advisor.
            return None
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

        Only some building types have any `Building_YieldChanges` row, so an empty yield
        list is not evidence that a building does nothing — some express their whole
        effect through a modifier. Counting is what stops "no rows, therefore no yield"
        from becoming a claim.
        """
        if "BuildingModifiers" not in self._countable:
            return ()
        try:
            count = self._count("BuildingModifiers", {"BuildingType": building_type})
        except sqlite3.OperationalError:
            return ()
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
