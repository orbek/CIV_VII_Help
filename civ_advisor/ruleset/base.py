"""What a ruleset provider may say, and what it may not.

Four constraints are types rather than intentions:

  - a figure names the table, column and row it was read from, or it cannot be
    constructed. There is no way to produce a number that has no row behind it. Its
    column must also name one stored value, not an aggregate over many rows: a figure
    reads one row, and `COUNT(*)` is not that.
  - a count of rows (`RulesetCount`) is not a figure and cannot become one. It has no
    `value`/`unit` field to carry a number a reader could mistake for a yield or a cost —
    only a `count`. Adjudicated for `BuildingModifiers`: those rows may be counted, never
    priced, and the type is what keeps that true regardless of who writes the next reader.
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
        if "(" in self.column or ")" in self.column:
            raise ValueError(
                f"ruleset figure {self.label!r} names column {self.column!r}, which reads "
                "as an aggregate expression over many rows rather than one stored column; "
                "a count belongs in RulesetCount, never in RulesetFigure")


@dataclass(frozen=True)
class RulesetCount:
    """How many ruleset rows exist for one subject — never their combined magnitude.

    Structurally distinct from `RulesetFigure`: no `value` or `unit` field, so there is
    nowhere for a count to carry a number a reader could mistake for a yield or a cost.
    Built for the case that motivated it: `BuildingModifiers` rows may be counted — "this
    building has N modifier-based effects" — but the ruleset never states what any of
    them are worth, and adjudication requires that this never render as though it did.
    """

    subject: str
    label: str
    count: int
    table: str
    column: str
    row_key: tuple[str, ...]
    identity: RulesetIdentity

    def __post_init__(self) -> None:
        if not self.table or not self.column or not self.row_key:
            raise ValueError(
                f"ruleset count {self.label!r} must name the table, column and row(s) it "
                "was counted from; a count with no rows behind it is not a count")
        if self.count < 0:
            raise ValueError(f"ruleset count {self.label!r} cannot be negative: {self.count}")

    def describe(self) -> str:
        noun = "effect" if self.count == 1 else "effects"
        return (f"{self.label}: {self.count} modifier-based {noun}. The installed "
                "ruleset does not state their magnitude.")


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
    housing: RulesetFigure | None = None
    entertainment: RulesetFigure | None = None
    citizen_slots: RulesetFigure | None = None
    is_wonder: RulesetFigure | None = None
    requires_placement: RulesetFigure | None = None
    yields: tuple[RulesetFigure, ...] = ()
    mentions: tuple[RulesetMention, ...] = ()
    counts: tuple[RulesetCount, ...] = ()

    @property
    def figures(self) -> tuple[RulesetFigure, ...]:
        """The stateable figures, in a stable order. Mentions and counts are not here:
        neither is a figure, and must never be folded into a list of them."""
        named = (self.cost, self.maintenance, self.prereq_district, self.prereq_tech,
                 self.prereq_civic, self.housing, self.entertainment, self.citizen_slots,
                 self.is_wonder, self.requires_placement)
        return tuple(f for f in named if f is not None) + self.yields


@dataclass(frozen=True)
class DistrictFacts:
    """Every in-scope figure about one district, each carrying its own row."""

    district: str
    cost: RulesetFigure | None = None
    prereq_tech: RulesetFigure | None = None
    prereq_civic: RulesetFigure | None = None
    housing: RulesetFigure | None = None
    entertainment: RulesetFigure | None = None
    citizen_slots: RulesetFigure | None = None
    maintenance: RulesetFigure | None = None

    @property
    def figures(self) -> tuple[RulesetFigure, ...]:
        return tuple(f for f in (self.cost, self.prereq_tech, self.prereq_civic,
                                 self.housing, self.entertainment, self.citizen_slots,
                                 self.maintenance) if f is not None)


@dataclass(frozen=True)
class ImprovementFacts:
    """Every in-scope figure about one tile improvement, each carrying its own row."""

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
    """Every in-scope figure about one government, each carrying its own row."""

    government: str
    prereq_civic: RulesetFigure | None = None
    tier: RulesetFigure | None = None
    slots: tuple[RulesetFigure, ...] = ()     # one per Government_SlotCounts row

    @property
    def figures(self) -> tuple[RulesetFigure, ...]:
        return tuple(f for f in (self.prereq_civic, self.tier) if f is not None) + self.slots


@dataclass(frozen=True)
class ResourceFacts:
    """Every in-scope figure about one resource, each carrying its own row."""

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
    """Every in-scope figure about one technology, each carrying its own row."""

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
    """Every in-scope figure about one civic, each carrying its own row."""

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
    """Every in-scope figure about one unit, each carrying its own row.

    The gold cost of an upgrade is computed at runtime from a formula and stored in no
    row, so it stays a `RulesetMention` rather than a figure: the upgrade target being
    stateable makes the cost the obvious next question, and the honest answer is that
    this file does not have it.
    """

    unit: str
    cost: RulesetFigure | None = None
    maintenance: RulesetFigure | None = None
    combat: RulesetFigure | None = None
    ranged_combat: RulesetFigure | None = None
    prereq_tech: RulesetFigure | None = None
    prereq_civic: RulesetFigure | None = None
    strategic_resource: RulesetFigure | None = None
    upgrades_to: RulesetFigure | None = None
    moves: RulesetFigure | None = None
    range: RulesetFigure | None = None
    domain: RulesetFigure | None = None
    promotion_class: RulesetFigure | None = None
    mentions: tuple[RulesetMention, ...] = ()

    @property
    def figures(self) -> tuple[RulesetFigure, ...]:
        return tuple(f for f in (self.cost, self.maintenance, self.combat,
                                 self.ranged_combat, self.prereq_tech, self.prereq_civic,
                                 self.strategic_resource, self.upgrades_to, self.moves,
                                 self.range, self.domain, self.promotion_class)
                     if f is not None)


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

    # What is wrong with the shape of the tables one lookup reads, or None if they are
    # as expected. A lookup that returns None means "no such row" ONLY when this says
    # None as well: otherwise the query failed at the database and nothing about rows
    # was established. `kind` is the lookup's own name -- "building", "unit", ...
    def schema_complaint(self, kind: str) -> str | None: ...

    def building(self, building_type: str) -> BuildingFacts | None: ...

    def district(self, district_type: str) -> DistrictFacts | None: ...

    def technology(self, technology_type: str) -> TechnologyFacts | None: ...

    def civic(self, civic_type: str) -> CivicFacts | None: ...

    def unit(self, unit_type: str) -> UnitFacts | None: ...

    def parameter(self, name: str) -> RulesetFigure | None: ...

    def improvement(self, improvement_type: str) -> ImprovementFacts | None: ...

    def policy(self, policy_type: str) -> PolicyFacts | None: ...

    def government(self, government_type: str) -> GovernmentFacts | None: ...

    def resource(self, resource_type: str) -> ResourceFacts | None: ...


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

    def schema_complaint(self, kind: str) -> str | None:
        return None     # nothing is readable here at all; `reason` is what says why

    def building(self, building_type: str) -> BuildingFacts | None:
        return None

    def district(self, district_type: str) -> DistrictFacts | None:
        return None

    def technology(self, technology_type: str) -> TechnologyFacts | None:
        return None

    def civic(self, civic_type: str) -> CivicFacts | None:
        return None

    def unit(self, unit_type: str) -> UnitFacts | None:
        return None

    def parameter(self, name: str) -> RulesetFigure | None:
        return None

    def improvement(self, improvement_type: str) -> ImprovementFacts | None:
        return None

    def policy(self, policy_type: str) -> PolicyFacts | None:
        return None

    def government(self, government_type: str) -> GovernmentFacts | None:
        return None

    def resource(self, resource_type: str) -> ResourceFacts | None:
        return None


NO_RULESET = NullRuleset("This game ships no queryable ruleset, so every figure in a "
                         "recommendation comes from your own preview.")


__all__ = ["NO_RULESET", "BoostFacts", "BuildingFacts", "CivicFacts", "DistrictFacts",
           "GovernmentFacts", "ImprovementFacts", "NullRuleset", "PolicyFacts",
           "ResourceFacts", "RulesetCount", "RulesetFigure", "RulesetIdentity",
           "RulesetMention", "RulesetOutOfScope", "RulesetProvider", "TechnologyFacts",
           "UnitFacts"]
