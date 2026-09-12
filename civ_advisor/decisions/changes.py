"""What changed since the last turn, and what merely stopped being visible.

A trend is a claim, and this module is deliberately reluctant to make one. Four ways it
refuses:

  - **No history, no trend.** A single observation is not a direction. The first turn of a
    session reports everything as newly observed and nothing as worsening.
  - **A reload is not a change.** Comparison is confined to one session and epoch; after a
    reload the history of the previous sitting is not the previous turn of this one.
  - **Like for like only.** If a source domain a signal depends on had different coverage
    then and now, the signal is reported as not comparable and says which domain moved.
    A warning that vanished because its log stopped being readable has not improved.
  - **"Resolved" needs positive evidence.** A signal that is simply absent is
    `no_longer_observed`. It becomes `resolved` only when the current snapshot contains an
    observation showing the condition no longer holds.

Same-turn rebuilds replace their history entry rather than appending, so five log writes
within one turn do not read as five turns of history.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from civ_advisor.advisors.base import Provenance, Severity
from civ_advisor.store import Snapshot

from .models import DecisionCard

# What can be said about one signal between two turns.
NEW = "newly_observed"
WORSENING = "worsening"
IMPROVING = "improving"
UNCHANGED = "unchanged"
NO_LONGER_OBSERVED = "no_longer_observed"
RESOLVED = "resolved"
NOT_COMPARABLE = "not_comparable"

HISTORY_LIMIT = 40  # turns of history kept per process; bounded on purpose

# Which coverage domains each advisor's signals depend on. A signal is only compared when
# every domain behind it was covered the same way in both turns.
ADVISOR_DOMAINS: dict[str, tuple[str, ...]] = {
    "economy": ("empire", "treasury", "happiness"),
    "production": ("production", "empire"),
    "threat": ("empire", "diplomacy", "combat", "targets"),
    "tactical": ("tactical", "targets"),
    "victory": ("empire", "strategy"),
    "checklist": ("empire",),
}
DECISION_DOMAINS: dict[str, tuple[str, ...]] = {
    "defense": ("tactical", "targets"),
}
YIELD_DOMAINS: tuple[str, ...] = ("empire", "production")


@dataclass(frozen=True)
class Signal:
    """One thing worth tracking between turns."""

    id: str
    label: str
    severity: int                      # Severity value; 0 for a satisfied signal
    observed_turn: int | None
    domains: tuple[str, ...] = ()      # coverage domains it rests on
    value: float | None = None         # a comparable magnitude, where one exists
    # True when the current snapshot positively shows the condition no longer holds —
    # the only thing that licenses calling a signal resolved.
    satisfied: bool = False
    catalog_dependent: bool = False    # its wording or ranking came from the guide catalog
    # Recorded regardless of which mode the request that captured this turn was in: the
    # history is the advisor's own memory and must not vary with how a player happened to
    # be looking at it. Oracle-ness is filtered out of what is SERVED, at `compare()`'s
    # output, never out of what is recorded here.
    provenance: Provenance = Provenance.FAIR


@dataclass(frozen=True)
class HistoryEntry:
    """One turn's signals, keyed so a same-turn rebuild replaces rather than appends."""

    session: str
    epoch: int
    turn: int
    revision: int
    captured_at: float
    catalog_revision: str
    coverage: dict[str, str] = field(default_factory=dict)
    signals: dict[str, Signal] = field(default_factory=dict)

    @property
    def key(self) -> tuple[str, int, int]:
        return (self.session, self.epoch, self.turn)


@dataclass(frozen=True)
class Change:
    signal_id: str
    label: str
    state: str
    detail: str
    severity: int
    previous_turn: int | None = None
    observed_turn: int | None = None
    # The signal's own provenance, carried onto the Change so a response can filter
    # Oracle-derived rows out at serialization without ever having filtered the history
    # they were computed from.
    provenance: Provenance = Provenance.FAIR


@dataclass
class History:
    """A bounded, in-process record of coherent turns.

    Not persistence — `context_store` owns what survives a restart. This exists so "since
    last turn" can be answered at all, and it is capped because a long game would
    otherwise grow it without limit.
    """

    limit: int = HISTORY_LIMIT
    entries: list[HistoryEntry] = field(default_factory=list)

    def record(self, entry: HistoryEntry) -> None:
        """Add or replace this turn's entry.

        A rebuild for a turn already recorded replaces it: the log files were written
        again, which is not another turn passing. Keeping both would let a burst of writes
        masquerade as history.
        """
        for index, held in enumerate(self.entries):
            if held.key == entry.key:
                if entry.revision >= held.revision:
                    self.entries[index] = entry
                return
        self.entries.append(entry)
        self.entries.sort(key=lambda e: (e.session, e.epoch, e.turn))
        if len(self.entries) > self.limit:
            del self.entries[: len(self.entries) - self.limit]

    def forget(self) -> None:
        """Drop every recorded turn. A game switch, not a reload: the entries are another
        game's turns and `previous()` must not be able to reach them even by accident."""
        self.entries.clear()

    def previous(self, entry: HistoryEntry) -> HistoryEntry | None:
        """The newest earlier turn of the same sitting, or None.

        Same session and epoch, strictly earlier turn. A different epoch is a different
        sitting and possibly a different save, so it is not this turn's past.
        """
        candidates = [e for e in self.entries
                      if e.session == entry.session and e.epoch == entry.epoch
                      and e.turn < entry.turn]
        return max(candidates, key=lambda e: e.turn) if candidates else None

    def turns(self, session: str, epoch: int) -> tuple[int, ...]:
        """The observed turn numbers recorded for this sitting, in order.

        Turn numbers, not positions: a series that silently renumbered gaps would imply
        turns we never saw.
        """
        return tuple(sorted(e.turn for e in self.entries
                            if e.session == session and e.epoch == epoch))


def signals_from(snapshot: Snapshot, cards: tuple[DecisionCard, ...],
                 comparisons: dict | None = None,
                 on_pace: float = 1.0) -> dict[str, Signal]:
    """Everything trackable in one snapshot, including what is now satisfied.

    Satisfied signals matter as much as the warnings: a yield that has climbed back to the
    field is the positive observation that lets last turn's warning be called resolved
    rather than merely gone.

    Recorded complete, with no oracle filter at all: every insight becomes a signal
    regardless of provenance, tagged with that provenance so a caller can filter what is
    SERVED later. Filtering here would make the recorded history depend on which mode
    happened to be active when a turn was captured -- a player toggling Oracle on would
    then be told a signal was "newly observed" when it had been there all along.
    """
    out: dict[str, Signal] = {}
    for insight in snapshot.insights:
        out[insight.id] = Signal(
            id=insight.id, label=insight.title, severity=int(insight.severity),
            observed_turn=insight.turn,
            domains=ADVISOR_DOMAINS.get(insight.advisor, ("empire",)),
            provenance=insight.provenance,
        )
    for card in cards:
        domains = DECISION_DOMAINS.get(card.family, YIELD_DOMAINS)
        out[card.id] = Signal(
            id=card.id, label=card.subject, severity=int(card.severity),
            observed_turn=max(card.observed_turns) if card.observed_turns else None,
            domains=domains, catalog_dependent=True,
        )
    for stat, fact in (comparisons or {}).items():
        if fact.value is None:
            continue
        ratio = float(fact.value)
        signal_id = f"economy.behind.{stat}"
        if ratio >= on_pace:
            # Positive evidence: the yield is level with or ahead of the field, observed
            # this turn from the same rows the warning would have come from.
            out[signal_id] = Signal(
                id=signal_id, label=f"Your {stat} against the field",
                severity=0, observed_turn=fact.observed_turn, domains=YIELD_DOMAINS,
                value=ratio, satisfied=True,
            )
        elif signal_id in out:
            out[signal_id] = Signal(**{**out[signal_id].__dict__, "value": ratio})
    return out


def entry_from(snapshot: Snapshot, cards: tuple[DecisionCard, ...],
               catalog_revision: str, comparisons: dict | None = None) -> HistoryEntry:
    """The complete recorded memory of one turn -- never filtered by oracle.

    Deliberately takes no `oracle` argument: what the advisor remembers about a turn
    must not depend on which mode the request that captured it happened to be in.
    Filtering for a response is `compare()`'s output's job, not this function's.
    """
    return HistoryEntry(
        session=snapshot.session, epoch=snapshot.epoch, turn=snapshot.analysis_turn,
        revision=snapshot.revision, captured_at=snapshot.captured_at,
        catalog_revision=catalog_revision,
        coverage={c.name: c.status for c in snapshot.coverage},
        signals=signals_from(snapshot, cards, comparisons),
    )


def compare(previous: HistoryEntry | None, current: HistoryEntry) -> tuple[Change, ...]:
    """What changed between two turns of one sitting.

    With no previous turn this returns nothing at all rather than a page of "new": the
    first look at a game is not a set of changes, and saying so would put a spurious
    "everything is new" banner on top of the brief.
    """
    if previous is None:
        return ()

    changes: list[Change] = []
    for signal_id, signal in sorted(current.signals.items()):
        before = previous.signals.get(signal_id)
        moved = _coverage_moved(signal, previous, current)
        if before is None:
            if moved:
                # It may have been there all along and simply unreadable.
                changes.append(Change(
                    signal_id, signal.label, NOT_COMPARABLE,
                    f"First seen this turn, but {moved} changed since last turn, so this "
                    "may have been there and unreadable rather than new.",
                    signal.severity, previous.turn, signal.observed_turn,
                    provenance=signal.provenance))
            elif not signal.satisfied:
                changes.append(Change(
                    signal_id, signal.label, NEW, "Not present last turn.",
                    signal.severity, previous.turn, signal.observed_turn,
                    provenance=signal.provenance))
            continue
        if moved:
            changes.append(Change(
                signal_id, signal.label, NOT_COMPARABLE,
                f"{moved} changed since last turn, so then and now are not comparable.",
                signal.severity, previous.turn, signal.observed_turn,
                provenance=signal.provenance))
            continue
        if signal.catalog_dependent and previous.catalog_revision != current.catalog_revision:
            changes.append(Change(
                signal_id, signal.label, NOT_COMPARABLE,
                "The reviewed guide catalog changed between these turns, so this "
                "decision's wording and ranking are not comparable.",
                signal.severity, previous.turn, signal.observed_turn,
                provenance=signal.provenance))
            continue
        if signal.satisfied and not before.satisfied:
            changes.append(Change(
                signal_id, signal.label, RESOLVED,
                _resolution_detail(before, signal), signal.severity,
                previous.turn, signal.observed_turn, provenance=signal.provenance))
        elif signal.severity > before.severity:
            changes.append(Change(
                signal_id, signal.label, WORSENING,
                f"Severity rose from {Severity(before.severity).name} to "
                f"{Severity(signal.severity).name}.",
                signal.severity, previous.turn, signal.observed_turn,
                provenance=signal.provenance))
        elif signal.severity < before.severity:
            changes.append(Change(
                signal_id, signal.label, IMPROVING,
                f"Severity fell from {Severity(before.severity).name} to "
                f"{Severity(signal.severity).name}.",
                signal.severity, previous.turn, signal.observed_turn,
                provenance=signal.provenance))
        elif signal.value is not None and before.value is not None \
                and abs(signal.value - before.value) > 0.005:
            direction = IMPROVING if signal.value > before.value else WORSENING
            changes.append(Change(
                signal_id, signal.label, direction,
                f"Went from {before.value:.0%} to {signal.value:.0%} of the field.",
                signal.severity, previous.turn, signal.observed_turn,
                provenance=signal.provenance))
        else:
            changes.append(Change(
                signal_id, signal.label, UNCHANGED, "No change observed.",
                signal.severity, previous.turn, signal.observed_turn,
                provenance=signal.provenance))

    for signal_id, before in sorted(previous.signals.items()):
        if signal_id in current.signals or before.satisfied:
            continue
        moved = _coverage_moved(before, previous, current)
        if moved:
            # Source loss is its own state. A warning that disappeared because its log
            # became unreadable has not improved, and must never read as resolved.
            changes.append(Change(
                signal_id, before.label, NO_LONGER_OBSERVED,
                f"Gone from this turn's advice, but {moved} changed, so this is a lost "
                "source rather than an observed change.",
                before.severity, previous.turn, None, provenance=before.provenance))
        else:
            changes.append(Change(
                signal_id, before.label, NO_LONGER_OBSERVED,
                "Not in this turn's advice. Nothing observed says the situation "
                "resolved — only that it is no longer being reported.",
                before.severity, previous.turn, None, provenance=before.provenance))
    return tuple(changes)


def _resolution_detail(before: Signal, now: Signal) -> str:
    if before.value is not None and now.value is not None:
        return (f"Observed back at {now.value:.0%} of the field, from {before.value:.0%}. "
                "This is a present observation, not an inference from the warning stopping.")
    return ("The current snapshot shows the condition no longer holding. This is a present "
            "observation, not an inference from the warning stopping.")


def _coverage_moved(signal: Signal, previous: HistoryEntry,
                    current: HistoryEntry) -> str | None:
    """Which of a signal's domains had different coverage then and now."""
    moved = [name for name in signal.domains
             if previous.coverage.get(name) != current.coverage.get(name)]
    if not moved:
        return None
    if len(moved) == 1:
        return f"coverage of {moved[0]}"
    return "coverage of " + ", ".join(sorted(moved))


def retrospective(changes: tuple[Change, ...], acknowledged: tuple[str, ...]) -> dict:
    """A short account of what moved, alongside what the player had acknowledged.

    Deliberately two lists side by side and no arithmetic between them. Acknowledging a
    decision and a yield improving in the same turn is a coincidence until something
    establishes otherwise, and nothing here can establish it — so no causation is claimed
    and no score is kept.
    """
    by_state: dict[str, list[Change]] = {}
    for change in changes:
        by_state.setdefault(change.state, []).append(change)
    return {
        "states": {state: [c.signal_id for c in rows] for state, rows in sorted(by_state.items())},
        "acknowledged": list(acknowledged),
        "caveat": ("These are two records of the same turns, shown side by side. Nothing "
                   "here shows that acknowledging a decision caused any of these changes, "
                   "and no success is being scored."),
    }


__all__ = ["ADVISOR_DOMAINS", "Change", "History", "HistoryEntry", "IMPROVING",
           "NEW", "NOT_COMPARABLE", "NO_LONGER_OBSERVED", "RESOLVED", "Signal",
           "UNCHANGED", "WORSENING", "compare", "entry_from", "retrospective",
           "signals_from"]
