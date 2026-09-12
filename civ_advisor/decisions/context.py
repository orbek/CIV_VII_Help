"""Assemble one decision context from one snapshot, plus the player's own reports.

Everything a decision is allowed to use arrives here first, dated, with its unknowns
named. Two things this module refuses to do:

  - fill a gap with a default. A missing preview is missing, not zero; an unlogged
    settlement is unobserved, not idle; an Age that has not been confirmed for this turn
    is unknown, not assumed.
  - let a player report quietly outrank a fresher log row. Reports are a separate source
    kind, are scoped to a session and a subject, and are invalidated when the things they
    describe move.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field, replace

from civ_advisor.advisors import tactical
from civ_advisor.advisors.base import Severity, visible
from civ_advisor.knowledge.catalog import Catalog, load_catalog
from civ_advisor.state.models import GameState
from civ_advisor.store import Snapshot

from .evidence import YIELD_STATS, EvidenceLedger, build_ledger
from .models import EvidenceFact, PlayerContext, PlayerReport, Prerequisite

# The report vocabulary. A submission naming anything else is refused, so the panel
# cannot grow free-text fields that nothing knows how to use.
OBJECTIVE = "objective"                     # subject: the city; value: an OBJECTIVES key
AVAILABLE_OPTIONS = "available_options"     # value: comma-separated item keys, as offered
PLACEMENT_LEGAL = "placement_legal"         # value: item key whose placement was confirmed
LOCAL_HAPPINESS_OK = "local_happiness_ok"   # value: item key the settlement can absorb
NO_DISPLACEMENT = "no_displacement"         # value: item key that displaces nothing
PREVIEW = "preview"                         # label: preview.<ITEM_KEY>.<metric>

# One metric vocabulary for every family. `yield_delta` is the change to the yield the
# decision is about — the unit string says which — rather than a per-family field name,
# so a second family with item-level guides needs no new plumbing.
PREVIEW_METRICS = {
    "completion_turns": "turns",
    "yield_delta": "per turn",
    "gold_upkeep": "gold per turn",
    "happiness_cost": "happiness per turn",
}

# What the player says they are optimising for. Ranking uses this instead of inventing a
# utility score: "best" is not a property of the game state, it is a property of a goal.
SOONEST = "soonest_culture"
LARGEST = "largest_culture"
# Written with a {yield_label} placeholder so one objective vocabulary serves every
# family: the player's goal is "soonest" or "largest", not "soonest culture".
OBJECTIVES = {
    SOONEST: "the next {yield_label} increase as soon as possible",
    LARGEST: "the largest eventual {yield_label} increase among feasible options",
}

SIMPLE_LABELS = (OBJECTIVE, AVAILABLE_OPTIONS, PLACEMENT_LEGAL, LOCAL_HAPPINESS_OK,
                 NO_DISPLACEMENT)


def preview_label(item: str, metric: str) -> str:
    return f"{PREVIEW}.{item}.{metric}"


def parse_preview_label(label: str) -> tuple[str, str] | None:
    parts = label.split(".")
    if len(parts) != 3 or parts[0] != PREVIEW or parts[2] not in PREVIEW_METRICS:
        return None
    return parts[1], parts[2]


def valid_label(label: str) -> bool:
    return label in SIMPLE_LABELS or parse_preview_label(label) is not None


# ---- the player-context store ---------------------------------------------------

class ContextConflict(Exception):
    """A submission could not be accepted as sent, and the caller must re-ask.

    Carries what changed so the UI can show the player the current values rather than
    silently discarding what they typed or silently overwriting newer context.
    """

    def __init__(self, reason: str, detail: str, current: PlayerContext) -> None:
        super().__init__(detail)
        self.reason = reason        # "session_changed" | "stale_revision" | "unknown_label"
        self.detail = detail
        self.current = current


@dataclass
class ContextStore:
    """Accepted player reports for the current session.

    In memory only; a durable local store is Phase 6. The revision moves whenever an
    accepted report changes what we know, *even when no log file moved*, because a
    recommendation that changed for that reason has to be able to say so.
    """

    session: str | None = None
    epoch: int = 0
    revision: int = 0
    _reports: dict[str, PlayerReport] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def context(self) -> PlayerContext:
        with self._lock:
            return PlayerContext(session=self.session or "", revision=self.revision,
                                 reports=tuple(self._reports[k] for k in sorted(self._reports)))

    def adopt(self, snapshot: Snapshot) -> None:
        """Follow the store's session, discarding reports that no longer apply.

        A new epoch means we may be looking at another game, so nothing carries over: a
        preview read off a different save would be worse than no preview.
        """
        with self._lock:
            if (self.session, self.epoch) == (snapshot.session, snapshot.epoch):
                return
            dropped = bool(self._reports)
            self.session, self.epoch = snapshot.session, snapshot.epoch
            self._reports.clear()
            if dropped or self.revision:
                self.revision += 1

    def submit(self, report: PlayerReport, epoch: int, base_revision: int,
               dependencies: dict[str, object] | None = None,
               current_dependencies: dict[str, object] | None = None) -> PlayerReport:
        """Accept one report, or raise `ContextConflict`.

        `base_revision` is the context revision the form was rendered against. When it is
        behind, the submission is not discarded out of hand: if the dependencies it was
        entered against are unchanged, it is revalidated and accepted. Only a real change
        to something the value depends on — this settlement's queue, the Age, the session
        — is a conflict, and then the caller is told which.
        """
        with self._lock:
            if not valid_label(report.label):
                raise ContextConflict(
                    "unknown_label", f"{report.label!r} is not a field this panel collects",
                    self._context_locked())
            if report.session != self.session or epoch != self.epoch:
                # A form opened before a reload must never attach its values to the new
                # session, however plausible they look.
                raise ContextConflict(
                    "session_changed",
                    "This game was reloaded since the form was opened, so these values "
                    "cannot be attached to it. Read them again and resubmit.",
                    self._context_locked())
            if base_revision != self.revision:
                changed = _changed_dependencies(dependencies or {}, current_dependencies or {})
                if changed:
                    raise ContextConflict(
                        "stale_revision",
                        "Something these values depend on changed while the form was open: "
                        + ", ".join(sorted(changed))
                        + ". The current values are shown; confirm them again.",
                        self._context_locked())
            stored = replace(report, base_revision=self.revision)
            previous = self._reports.get(stored.id)
            self._reports[stored.id] = stored
            # Compare what the report says, not the bookkeeping stamped onto it. Confirming
            # an unchanged value must not move the revision, or every reload of the panel
            # would look like new information and invalidate commentary for nothing.
            if _material(previous) != _material(stored):
                self.revision += 1
            return stored

    def clear(self, report_id: str) -> bool:
        with self._lock:
            if self._reports.pop(report_id, None) is None:
                return False
            self.revision += 1
            return True

    def invalidate(self, subject: str, reason: str) -> tuple[str, ...]:
        """Drop every report about one subject.

        Called when something that subject's values depend on moves. Deliberately
        subject-scoped: an unrelated rival event has no business discarding a city
        preview, while that city's queue changing does.
        """
        with self._lock:
            gone = tuple(sorted(k for k, r in self._reports.items() if r.subject == subject))
            for key in gone:
                del self._reports[key]
            if gone:
                self.revision += 1
            return gone

    def _context_locked(self) -> PlayerContext:
        return PlayerContext(session=self.session or "", revision=self.revision,
                             reports=tuple(self._reports[k] for k in sorted(self._reports)))


def _material(report: PlayerReport | None) -> tuple | None:
    """What a report actually asserts, for comparing two submissions."""
    if report is None:
        return None
    return (report.subject, report.label, report.value, report.unit, report.observed_turn)


def _changed_dependencies(claimed: dict[str, object], current: dict[str, object]) -> set[str]:
    return {key for key, value in claimed.items()
            if key in current and current[key] != value}


# ---- the assembled context ------------------------------------------------------

@dataclass(frozen=True)
class Previews:
    """Player-supplied preview figures for one candidate item in one settlement.

    Every metric is optional and stays `None` when it was not supplied. A comparison that
    needs a missing metric must say what is missing, not substitute zero.
    """

    item: str
    completion_turns: float | None = None
    yield_delta: float | None = None
    gold_upkeep: float | None = None
    happiness_cost: float | None = None
    observed_turn: int | None = None
    fact_ids: tuple[str, ...] = ()

    def missing(self, *metrics: str) -> tuple[str, ...]:
        return tuple(m for m in metrics if getattr(self, m) is None)


@dataclass(frozen=True)
class SettlementView:
    """What is known about one settlement, and what is not."""

    city: str
    name: str
    item: str
    turns_to_complete: int | None
    observed_turn: int
    queue_fact_id: str
    completed_items: tuple[str, ...] = ()

    @property
    def idle(self) -> bool:
        return not self.item


@dataclass(frozen=True)
class DecisionContext:
    """One coherent basis for a decision, from one snapshot and one context revision."""

    session: str
    epoch: int
    snapshot_revision: int
    context_revision: int
    catalog_revision: str
    analysis_turn: int
    evidence_mode: str
    state: GameState
    ledger: EvidenceLedger
    catalog: Catalog
    player: PlayerContext
    settlements: tuple[SettlementView, ...] = ()
    unobserved_settlements: int | None = None
    coverage_fact_id: str | None = None
    comparisons: dict[str, EvidenceFact] = field(default_factory=dict)
    net_gold: EvidenceFact | None = None
    happiness: EvidenceFact | None = None
    age: EvidenceFact | None = None
    identity: EvidenceFact | None = None
    defense_facts: tuple[EvidenceFact, ...] = ()
    defense_severity: Severity | None = None
    defense_titles: tuple[str, ...] = ()
    insight_ids: tuple[str, ...] = ()

    # -- what the player told us ---------------------------------------------------

    @property
    def culture_comparison(self) -> EvidenceFact | None:
        """The culture pilot's own comparison. One family's view of `comparisons`."""
        return self.comparisons.get("culture")

    def objective(self, city: str) -> str | None:
        for report in self.player.for_subject(city):
            if report.label == OBJECTIVE and report.value in OBJECTIVES:
                return str(report.value)
        return None

    def available_options(self, city: str) -> tuple[str, ...] | None:
        """The build options the player confirmed are offered, or None if never asked.

        None and () mean different things: nobody has told us, versus the player looked
        and there were none. Only the second justifies saying so.
        """
        for report in self.player.for_subject(city):
            if report.label == AVAILABLE_OPTIONS:
                raw = str(report.value or "")
                return tuple(part.strip() for part in raw.split(",") if part.strip())
        return None

    def flagged(self, city: str, label: str, item: str) -> bool:
        return any(r.label == label and r.value == item
                   for r in self.player.for_subject(city))

    def previews(self, city: str, item: str) -> Previews:
        values: dict[str, float | None] = {m: None for m in PREVIEW_METRICS}
        turns: list[int] = []
        fact_ids: list[str] = []
        for report in self.player.for_subject(city):
            parsed = parse_preview_label(report.label)
            if parsed is None or parsed[0] != item:
                continue
            _, metric = parsed
            try:
                values[metric] = float(report.value)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                continue
            turns.append(report.observed_turn)
            fact_ids.append(report.id)
        return Previews(item=item, observed_turn=max(turns) if turns else None,
                        fact_ids=tuple(sorted(fact_ids)), **values)

    def settlement(self, city: str) -> SettlementView | None:
        return next((s for s in self.settlements if s.city == city), None)

    @property
    def defense_is_urgent(self) -> bool:
        return (self.defense_severity is not None
                and self.defense_severity >= Severity.CRITICAL)


def build_context(snapshot: Snapshot, player: PlayerContext | None = None,
                  oracle: bool = True, catalog: Catalog | None = None) -> DecisionContext:
    """Everything the culture pilot may read, from this snapshot in this evidence mode."""
    state = snapshot.state
    catalog = catalog or load_catalog()
    ledger = build_ledger(state)
    insights = visible(snapshot.insights, oracle)

    # Accepted player reports become citable facts alongside the log rows — as their own
    # source kind, so a card that used one shows where it came from and the reader can
    # see it was read off the screen rather than parsed from a file.
    player = player or PlayerContext(session=snapshot.session)
    for report in player.reports:
        ledger.add(report.fact())

    settlements = []
    completed_by_city: dict[str, list[str]] = {}
    for fact in ledger.facts.values():
        if fact.id.startswith("completed.") and fact.subject_id:
            completed_by_city.setdefault(fact.subject_id, []).append(str(fact.value))
    from civ_advisor.advisors import production
    for row in production.queues(state).get(state.HUMAN, []):
        settlements.append(SettlementView(
            city=row.city, name=_city_name(row.city), item=row.item,
            turns_to_complete=row.turns_to_complete, observed_turn=row.turn,
            queue_fact_id=f"queue.{row.city}.{row.turn}",
            completed_items=tuple(sorted(set(completed_by_city.get(row.city, ())))),
        ))

    coverage = ledger.get(f"settlements.queue_coverage.{snapshot.analysis_turn}")
    unobserved = None
    if coverage is not None:
        empire = ledger.get(f"settlements.count.{snapshot.analysis_turn}")
        if empire is not None and isinstance(empire.value, (int, float)):
            unobserved = max(int(empire.value) - len(settlements), 0)

    defense = tuple(f for f in ledger.facts.values() if f.id.startswith("defense.attack_goal."))
    defense_insights = [i for i in insights if i.advisor == "tactical"]
    severity = max((i.severity for i in defense_insights), default=None)
    # Only the fresh, immediate objectives may set an urgent defence priority. A dated
    # last-known objective is real evidence and must stay visible, but it is not a reason
    # to tell the player to drop what they are doing.
    fresh = [g for g in tactical.attack_goals(state) if g["fresh"]]
    if not fresh and severity is not None and severity >= Severity.CRITICAL:
        severity = Severity.WARN

    return DecisionContext(
        session=snapshot.session, epoch=snapshot.epoch,
        snapshot_revision=snapshot.revision,
        context_revision=(player.revision if player else 0),
        catalog_revision=catalog.revision, analysis_turn=snapshot.analysis_turn,
        evidence_mode="oracle" if oracle else "fair",
        state=state, ledger=ledger, catalog=catalog, player=player,
        settlements=tuple(settlements), unobserved_settlements=unobserved,
        coverage_fact_id=coverage.id if coverage else None,
        comparisons={stat: fact for stat in YIELD_STATS
                     if (fact := ledger.get(f"comparison.{stat}.{snapshot.analysis_turn}"))
                     is not None},
        net_gold=ledger.get(f"gold.net.{snapshot.analysis_turn}"),
        happiness=ledger.get(f"happiness.total.{snapshot.analysis_turn}"),
        age=ledger.get(f"age.observed.{snapshot.analysis_turn}"),
        identity=ledger.get("identity.human"),
        defense_facts=defense if oracle else (),
        defense_severity=severity if oracle else None,
        defense_titles=tuple(i.title for i in defense_insights
                             if i.severity == severity) if oracle else (),
        insight_ids=tuple(i.id for i in insights),
    )


def age_prerequisite(context: DecisionContext) -> Prerequisite:
    """Whether an Age-gated action's Age requirement can be called met.

    Never MET. The newest historian event dates an Age; no log states the current one, and
    the catalog establishes no Age compatibility for any item — so the honest answer is
    UNKNOWN, which keeps every Age-sensitive action conditional.
    """
    return Prerequisite.UNKNOWN


def _city_name(city_key: str) -> str:
    return city_key.removeprefix("LOC_CITY_NAME_").replace("_", " ").title()


__all__ = ["AVAILABLE_OPTIONS", "ContextConflict", "ContextStore", "DecisionContext",
           "LARGEST", "LOCAL_HAPPINESS_OK", "NO_DISPLACEMENT", "OBJECTIVE", "OBJECTIVES",
           "PLACEMENT_LEGAL", "PREVIEW_METRICS", "Previews", "SOONEST", "SettlementView",
           "build_context", "preview_label", "valid_label"]
