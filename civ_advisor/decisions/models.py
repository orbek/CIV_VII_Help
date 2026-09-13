"""The decision contracts.

Every field that could carry an unstated assumption is explicit instead: what was
observed, when, from which record, and what remains unknown. Optional fields default so
advisors can be migrated one at a time without a flag day.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from civ_advisor.advisors.base import Provenance, Severity


class SourceKind(Enum):
    LOG = "log"                      # a row the game wrote
    PLAYER_REPORT = "player_report"  # something the player told us, dated and scoped
    DERIVED = "derived"              # computed from other facts, which it must cite
    # A fourth kind beyond the three the plan names. A derived comparison has to cite the
    # rule threshold it was judged against, and a threshold is neither an observation nor
    # a derivation from one: it is this advisor's own choice. Giving it its own kind keeps
    # it citable without letting it masquerade as something the game reported.
    RULE = "rule"
    # A fifth kind. A cost read out of the installed game files is not an observation of
    # this game, not a derivation from one, not this advisor's rule, and not something the
    # player typed in. Badging it as any of those would misstate where the number is
    # checkable: this one is checkable against a file on the player's own disk.
    INSTALLED_RULESET = "installed_ruleset"
    # A sixth kind. Every other source is something that happened without us asking: a
    # log row is what the game wrote on its own, a ruleset figure is a fact about the
    # player's install, a player report is a dated human observation. A tuner reading is
    # different in kind: it is a value WE asked for, at a moment WE chose, so it must
    # carry both the turn it describes and when we asked rather than either alone.
    LIVE_READING = "live_reading"     # a value we asked the running game for


class Applicability(Enum):
    """How far a candidate can be recommended on the evidence available.

    READY needs established applicability *and* met prerequisites. Anything short of
    that is CONDITIONAL, INSPECT or BLOCKED — never a confident instruction with a
    hedge bolted on.
    """

    READY = "ready"              # applicable, prerequisites met, safe to name outright
    CONDITIONAL = "conditional"  # applicable if a stated condition holds; say which
    INSPECT = "inspect"          # the next useful act is looking something up in game
    BLOCKED = "blocked"          # a prerequisite is known unmet; exclude from ready choices


class Prerequisite(Enum):
    MET = "met"
    UNMET = "unmet"
    UNKNOWN = "unknown"          # no source establishes it; never treated as met


@dataclass(frozen=True)
class EvidenceFact:
    """One observation, with everything needed to re-find it in the logs.

    `record_key` is a typed key into the parsed rows — file, turn, player, city — not a
    sentence. Evidence is never reconstructed by scraping an insight's `why` prose: prose
    is written *from* facts, and parsing it back would let a rewording silently change
    what a decision claims to rest on.
    """

    id: str
    label: str                       # what this fact is, in words
    source_kind: SourceKind
    provenance: Provenance
    observed_turn: int | None        # the game turn the observation is dated to
    value: float | int | str | None = None
    unit: str | None = None          # "per turn", "turns", "gold", ...
    source_file: str | None = None   # e.g. "Player_Stats.csv"; None for derived/reported
    record_key: tuple = ()           # typed key into that file's parsed rows
    subject_id: str | None = None    # player id, city key, plot — whatever this is about
    contributing: tuple[str, ...] = ()   # fact ids this one was derived from
    note: str | None = None          # a limitation the reader must not miss
    reported_at: str | None = None   # ISO timestamp, for player reports

    def __post_init__(self) -> None:
        if self.source_kind is SourceKind.DERIVED and not self.contributing:
            raise ValueError(f"derived fact {self.id} must cite the facts it came from")
        if self.source_kind is SourceKind.LOG and not self.source_file:
            raise ValueError(f"log fact {self.id} must name its source file")
        if self.source_kind is SourceKind.INSTALLED_RULESET:
            if not self.source_file:
                raise ValueError(f"ruleset fact {self.id} must name its source file")
            if len(self.record_key) < 3:
                raise ValueError(f"ruleset fact {self.id} must cite a table, a column "
                                 "and the row key that selects the row")
        if self.source_kind is SourceKind.LIVE_READING:
            # Both halves matter and neither is optional. A log row is something
            # the game wrote on its own; this is a value we asked for, so it must
            # say both which turn it describes and when we asked.
            if self.reported_at is None:
                raise ValueError(f"live reading fact {self.id} must record reported_at")
            if self.observed_turn is None:
                raise ValueError(f"live reading fact {self.id} must name its observed_turn")

    @property
    def freshness(self) -> str:
        """How this fact should be spoken about. Callers pass the analysis turn to
        `age_in`; this is only the shape of the answer when the turn is unknown."""
        return "undated" if self.observed_turn is None else f"turn {self.observed_turn}"

    def age_in(self, analysis_turn: int) -> int | None:
        if self.observed_turn is None:
            return None
        return max(analysis_turn - self.observed_turn, 0)


@dataclass(frozen=True)
class ActionCandidate:
    """One thing the player could do or inspect next, and why it is defensible."""

    id: str
    title: str
    target: str                      # the settlement, frontier or entity this acts on
    why_now: str
    applicability: Applicability
    steps: tuple[str, ...] = ()      # written from reviewed guides, never invented UI labels
    evidence_ids: tuple[str, ...] = ()
    guide_ids: tuple[str, ...] = ()
    prerequisites: tuple[tuple[str, Prerequisite], ...] = ()
    trade_offs: tuple[str, ...] = ()
    unknowns: tuple[str, ...] = ()   # decision-changing things we do not know
    provenance: Provenance = Provenance.FAIR

    def __post_init__(self) -> None:
        if self.applicability is Applicability.READY:
            if any(s is not Prerequisite.MET for _, s in self.prerequisites):
                raise ValueError(f"{self.id} cannot be ready with unmet or unknown prerequisites")
        if not self.steps and self.applicability is not Applicability.BLOCKED:
            raise ValueError(f"{self.id} must say what to do or what to inspect")

    @property
    def unmet(self) -> tuple[str, ...]:
        return tuple(name for name, s in self.prerequisites if s is Prerequisite.UNMET)

    @property
    def unproven(self) -> tuple[str, ...]:
        return tuple(name for name, s in self.prerequisites if s is Prerequisite.UNKNOWN)


@dataclass(frozen=True)
class DecisionCard:
    """A group of insights about one subject, with the action they point to."""

    id: str
    subject: str                     # what this decision is about, in words
    severity: Severity
    priority_reason: str             # why this sits where it does in the order
    insight_ids: tuple[str, ...] = ()
    preferred: ActionCandidate | None = None
    alternatives: tuple[ActionCandidate, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    evidence_mode: str = "oracle"    # the mode this card was computed under
    observed_turns: tuple[int, ...] = ()   # the turns its evidence comes from
    unknowns: tuple[str, ...] = ()
    family: str = ""                 # the yield or mechanic this decision is about
    # Other families trailing the field in the same settlement, worst first, as
    # (label, ratio). One inspection covers them all, so they are folded in here rather
    # than becoming near-identical cards that would push a real alert out of the brief.
    also_behind: tuple[tuple[str, float], ...] = ()

    @property
    def candidates(self) -> tuple[ActionCandidate, ...]:
        return ((self.preferred,) if self.preferred else ()) + self.alternatives


@dataclass(frozen=True)
class PlayerReport:
    """Something the player told us, scoped and dated so it can be invalidated.

    A report never overrides contradicting fresh log evidence silently: it is a separate
    source kind, and a decision that used one says so.
    """

    id: str
    subject: str                     # the entity it is about, e.g. a city key
    label: str
    value: float | int | str | None
    unit: str | None
    observed_turn: int               # the turn the player read it off the screen
    session: str                     # the epoch it belongs to; never reused across one
    reported_at: str                 # ISO timestamp
    base_revision: int = 0           # the decision revision it was entered against
    note: str | None = None

    def fact(self) -> EvidenceFact:
        return EvidenceFact(
            id=self.id, label=self.label, source_kind=SourceKind.PLAYER_REPORT,
            provenance=Provenance.FAIR, observed_turn=self.observed_turn,
            value=self.value, unit=self.unit, subject_id=self.subject,
            note=self.note, reported_at=self.reported_at,
        )


@dataclass(frozen=True)
class PlayerContext:
    """Every accepted report for one session, with its own revision.

    The revision changes when accepted input changes, even if no log file moved: a
    recommendation that changed because the player told us something must be able to say
    so, and commentary written against the old context must not be shown as current.
    """

    session: str
    revision: int = 0
    reports: tuple[PlayerReport, ...] = field(default=())

    def for_subject(self, subject: str) -> tuple[PlayerReport, ...]:
        return tuple(r for r in self.reports if r.subject == subject)


__all__ = ["ActionCandidate", "Applicability", "DecisionCard", "EvidenceFact",
           "PlayerContext", "PlayerReport", "Prerequisite", "SourceKind"]
