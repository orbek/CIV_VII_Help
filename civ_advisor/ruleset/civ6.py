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
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from .base import (
    BuildingFacts, NullRuleset, RulesetFigure, RulesetIdentity, RulesetMention,
    RulesetOutOfScope, RulesetProvider,
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

    def building(self, building_type: str) -> BuildingFacts | None:
        """A building's figures, verified to have all come from one state of the file.

        `identify()` reads raw bytes outside SQLite's own consistency guarantees, while
        the rows below are read through the connection. In the default rollback-journal
        mode SQLite writes pages into the main file during a transaction and only makes
        that atomic at commit, so an external write landing mid-transaction could in
        principle leave the raw digest and the row read describing two different states
        of the file -- a figure whose citation does not match the bytes it came from,
        which is worse than no figure. Read-verify-reread closes that window: the
        digest is captured before the rows are read and re-derived after, and a
        mismatch discards everything read and retries against the file's new state
        rather than serving a figure assembled from a moving target.
        """
        self._refresh_if_changed()
        cached = self._cache.get(("building", building_type))
        if cached is not None:
            return cached  # type: ignore[return-value]

        for _ in range(self._MAX_READ_ATTEMPTS):
            before = self._identity
            facts = self._read_building(building_type)
            after = identify(self._identity.path)
            if after.digest == before.digest:
                if facts is not None:
                    self._cache[("building", building_type)] = facts
                self._identity = after
                return facts
            # The file moved while these rows were being read. Every figure just built
            # cites `before`, which no longer describes the file -- discard all of it
            # and retry against the state `after` actually observed.
            self._identity = after
            self._cache.clear()
        return None

    def _read_building(self, building_type: str) -> BuildingFacts | None:
        """One attempt at reading a building's figures, against whatever state of the
        file is current when it runs. Never itself decides whether that state held
        still; `building()` is what verifies that and retries."""
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

        return BuildingFacts(
            building=building_type,
            cost=figure("Cost", f"{name} production cost", "production"),
            maintenance=figure("Maintenance", f"{name} maintenance", "gold per turn"),
            prereq_district=figure("PrereqDistrict", f"{name} requires district", None),
            prereq_tech=figure("PrereqTech", f"{name} requires technology", None),
            prereq_civic=figure("PrereqCivic", f"{name} requires civic", None),
            yields=yields,
            mentions=self._effect_mentions(building_type, bool(yields)),
        )

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
