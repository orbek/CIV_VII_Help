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
