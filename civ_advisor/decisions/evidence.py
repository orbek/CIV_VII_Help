"""Build `EvidenceFact`s from parsed observations.

Each builder reads the same parsed rows the advisors read and records where the number
came from — file, turn, player, city — so a citation in the UI can open the actual
observation. Derived facts (a comparison, a ratio, a threshold test) cite every fact they
consumed, including the rule threshold, because a comparison is only as fair as its
inputs: one Oracle contributor makes the whole derivation Oracle.

What is *not* here matters as much as what is. The game's logs do not record unlocks,
available builds, existing buildings, policies, specialist slots, tile adjacency or
per-city upkeep; see docs/architecture/log-capability-matrix.md. Those fields have no
builder rather than a guessed one.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from civ_advisor.advisors import economy, production, tactical
from civ_advisor.advisors.base import Provenance
from civ_advisor.state.models import GameState

from .models import EvidenceFact, SourceKind

STATS_FILE = "Player_Stats.csv"
TREASURY_FILE = "Player_Treasury.csv"
HAPPINESS_FILE = "Player_Happiness.csv"
QUEUE_FILE = "CityBuildQueue.csv"
HISTORIAN_FILE = "Historian.csv"
IDENTITY_FILE = "GameCore.log"
OPERATIONS_FILE = "AI_Operation.csv"
TACTICAL_FILE = "AI_Tactical.csv"

# The yields the economy advisor compares, and so the families a decision can be about.
# Kept in the same order the advisor uses so a ledger built twice is identical.
YIELD_STATS: tuple[str, ...] = ("culture", "science", "gold", "production", "food")


@dataclass
class EvidenceLedger:
    """The facts one decision context rests on, addressable by id."""

    facts: dict[str, EvidenceFact] = field(default_factory=dict)

    def add(self, fact: EvidenceFact) -> EvidenceFact:
        """Record a fact. Re-adding the same id must not change what it says: a citation
        that silently starts meaning something else is worse than a duplicate."""
        existing = self.facts.get(fact.id)
        if existing is not None and existing != fact:
            raise ValueError(f"evidence id {fact.id} is already used for a different fact")
        self.facts[fact.id] = fact
        return fact

    def get(self, fact_id: str) -> EvidenceFact | None:
        return self.facts.get(fact_id)

    def resolve(self, ids: tuple[str, ...]) -> tuple[EvidenceFact, ...]:
        """Every named fact, or an error. A card citing an id we cannot produce is a bug,
        not something to render as a dead link."""
        missing = [i for i in ids if i not in self.facts]
        if missing:
            raise KeyError(f"unresolved evidence ids: {', '.join(missing)}")
        return tuple(self.facts[i] for i in ids)

    def provenance_of(self, ids: tuple[str, ...]) -> Provenance:
        """Oracle if any cited fact — or anything it was derived from — is Oracle."""
        seen: set[str] = set()
        stack = list(ids)
        while stack:
            fact_id = stack.pop()
            if fact_id in seen:
                continue
            seen.add(fact_id)
            fact = self.facts.get(fact_id)
            if fact is None:
                continue
            if fact.provenance is Provenance.ORACLE:
                return Provenance.ORACLE
            stack.extend(fact.contributing)
        return Provenance.FAIR

    @property
    def turns(self) -> tuple[int, ...]:
        return tuple(sorted({f.observed_turn for f in self.facts.values()
                             if f.observed_turn is not None}))


# ---- empire yields ---------------------------------------------------------------

def yield_fact(ledger: EvidenceLedger, state: GameState, player: int, stat: str) -> EvidenceFact | None:
    """One player's per-turn yield at the analysis turn."""
    turn = state.complete_through_turn
    row = state.at(player, turn)
    if row is None:
        return None
    name = state.players[player].name if player in state.players else f"player {player}"
    return ledger.add(EvidenceFact(
        id=f"yield.{stat}.{player}.{turn}",
        label=f"{name}'s {stat} per turn",
        source_kind=SourceKind.LOG,
        # Every major's yields are in the player's own stats log, which the game writes
        # for all players: this is a readable comparison, not intercepted intent.
        provenance=Provenance.FAIR,
        observed_turn=turn, value=getattr(row, stat), unit="per turn",
        source_file=STATS_FILE, record_key=(STATS_FILE, turn, player),
        subject_id=str(player),
    ))


def yield_comparison_fact(ledger: EvidenceLedger, state: GameState,
                          stat: str) -> EvidenceFact | None:
    """The human's yield against the rival median, citing every row it used.

    The threshold is itself a fact: "behind the field" is this advisor's rule, not an
    observation, and a reader must be able to see which rule was applied.
    """
    comparisons = {c.stat: c for c in economy.comparison(state)}
    row = comparisons.get(stat)
    if row is None:
        return None
    turn = state.complete_through_turn
    contributing = []
    human = yield_fact(ledger, state, state.HUMAN, stat)
    if human is not None:
        contributing.append(human.id)
    for rival in state.rivals():
        fact = yield_fact(ledger, state, rival.id, stat)
        if fact is not None:
            contributing.append(fact.id)
    threshold = ledger.add(EvidenceFact(
        id="rule.economy.behind_ratio",
        label="Advisor rule: a yield below this share of the rival median counts as behind",
        source_kind=SourceKind.RULE, provenance=Provenance.FAIR, observed_turn=None,
        value=economy.BEHIND_RATIO, unit="ratio",
        note="An advisor threshold, not an observation, and not a claim about what is optimal.",
    ))
    contributing.append(threshold.id)
    return ledger.add(EvidenceFact(
        id=f"comparison.{stat}.{turn}",
        label=f"Your {row.label} against the rival median",
        source_kind=SourceKind.DERIVED, provenance=Provenance.FAIR, observed_turn=turn,
        value=round(row.ratio, 4), unit="ratio",
        subject_id=str(state.HUMAN), contributing=tuple(contributing),
        note=(f"Your {row.human:.1f} against a rival median of {row.rival_median:.1f}; "
              f"highest observed is {row.leader_name} at {row.leader_value:.1f}. "
              "A deficit says where you trail, not which investment is best."),
    ))


def net_gold_fact(ledger: EvidenceLedger, state: GameState) -> EvidenceFact | None:
    """Gold yield minus recorded maintenance. Absent when the treasury log is missing —
    a balance alone never establishes what the empire can afford per turn."""
    turn = state.complete_through_turn
    row = state.at(state.HUMAN, turn)
    if row is None or row.net_gold is None:
        return None
    gold = ledger.add(EvidenceFact(
        id=f"gold.yield.{turn}", label="Your gold yield", source_kind=SourceKind.LOG,
        provenance=Provenance.FAIR, observed_turn=turn, value=row.gold, unit="per turn",
        source_file=STATS_FILE, record_key=(STATS_FILE, turn, state.HUMAN),
        subject_id=str(state.HUMAN),
    ))
    upkeep = ledger.add(EvidenceFact(
        id=f"gold.maintenance.{turn}", label="Your total maintenance",
        source_kind=SourceKind.LOG, provenance=Provenance.FAIR, observed_turn=turn,
        value=row.total_maintenance, unit="per turn", source_file=TREASURY_FILE,
        record_key=(TREASURY_FILE, turn, state.HUMAN), subject_id=str(state.HUMAN),
    ))
    return ledger.add(EvidenceFact(
        id=f"gold.net.{turn}", label="Your net gold per turn", source_kind=SourceKind.DERIVED,
        provenance=Provenance.FAIR, observed_turn=turn, value=row.net_gold, unit="per turn",
        subject_id=str(state.HUMAN), contributing=(gold.id, upkeep.id),
        note=(f"Reserve is {row.gold_balance:.0f} gold. An empire-wide figure; it does not "
              "establish what one settlement can afford, or what a new building will cost."),
    ))


def happiness_fact(ledger: EvidenceLedger, state: GameState) -> EvidenceFact | None:
    """Empire happiness against the celebration threshold. Empire totals cannot validate
    a local decision such as a specialist placement."""
    turn = state.complete_through_turn
    row = state.at(state.HUMAN, turn)
    if row is None or row.happiness_total is None or not row.happiness_threshold:
        return None
    return ledger.add(EvidenceFact(
        id=f"happiness.total.{turn}", label="Your happiness against the celebration threshold",
        source_kind=SourceKind.LOG, provenance=Provenance.FAIR, observed_turn=turn,
        value=row.happiness_total, unit="happiness", source_file=HAPPINESS_FILE,
        record_key=(HAPPINESS_FILE, turn, state.HUMAN), subject_id=str(state.HUMAN),
        note=(f"Threshold {row.happiness_threshold}. An empire total: it says nothing about "
              "one settlement's local happiness capacity."),
    ))


# ---- settlements ----------------------------------------------------------------

def queue_facts(ledger: EvidenceLedger, state: GameState) -> tuple[EvidenceFact, ...]:
    """One fact per human settlement whose build queue was logged.

    These rows are a record of the settlements the game wrote about, not a census: a
    settlement with no row is unobserved, not idle, and callers must say so.
    """
    out = []
    for row in production.queues(state).get(state.HUMAN, []):
        remaining = None if row.turns_to_complete is None else row.turns_to_complete
        out.append(ledger.add(EvidenceFact(
            id=f"queue.{row.city}.{row.turn}",
            label=f"{_city(row.city)}'s current production",
            source_kind=SourceKind.LOG, provenance=Provenance.FAIR, observed_turn=row.turn,
            value=row.item or "", unit=None, source_file=QUEUE_FILE,
            record_key=(QUEUE_FILE, row.turn, state.HUMAN, row.city), subject_id=row.city,
            note=(f"{row.current:.1f} of {row.needed:.0f} production"
                  + ("" if remaining is None else f"; about {remaining} turn"
                     f"{'' if remaining == 1 else 's'} left at the logged rate")
                  + ". An estimate from the logged rate, not the game's own forecast."
                  if row.item else "This settlement's queue was logged as empty."),
        )))
    return tuple(out)


def settlement_coverage_fact(ledger: EvidenceLedger, state: GameState) -> EvidenceFact:
    """How many settlements the empire has against how many the queue log covers.

    This is the fact that stops "your other cities are fine" from being said: when the
    counts disagree, some settlements are simply unobserved.
    """
    turn = state.complete_through_turn
    row = state.at(state.HUMAN, turn)
    observed = len(production.queues(state).get(state.HUMAN, []))
    total = None if row is None else row.settlements
    contributing = []
    if row is not None:
        contributing.append(ledger.add(EvidenceFact(
            id=f"settlements.count.{turn}", label="Your settlement count",
            source_kind=SourceKind.LOG, provenance=Provenance.FAIR, observed_turn=turn,
            value=total, unit="settlements", source_file=STATS_FILE,
            record_key=(STATS_FILE, turn, state.HUMAN), subject_id=str(state.HUMAN),
        )).id)
    contributing.append(ledger.add(EvidenceFact(
        id=f"settlements.observed_queues.{turn}", label="Settlements with a logged build queue",
        source_kind=SourceKind.LOG, provenance=Provenance.FAIR, observed_turn=turn,
        value=observed, unit="settlements", source_file=QUEUE_FILE,
        record_key=(QUEUE_FILE, turn, state.HUMAN), subject_id=str(state.HUMAN),
    )).id)
    unobserved = None if total is None else max(total - observed, 0)
    return ledger.add(EvidenceFact(
        id=f"settlements.queue_coverage.{turn}",
        label="Build-queue coverage of your settlements",
        source_kind=SourceKind.DERIVED, provenance=Provenance.FAIR, observed_turn=turn,
        value=observed, unit="settlements", subject_id=str(state.HUMAN),
        contributing=tuple(contributing),
        note=("Settlement count is unknown, so queue coverage cannot be judged."
              if unobserved is None else
              f"{observed} of {total} settlement{'' if total == 1 else 's'} "
              f"{'has' if observed == 1 else 'have'} a logged queue"
              + ("." if not unobserved else
                 f"; {unobserved} {'is' if unobserved == 1 else 'are'} unobserved. "
                 f"{'Its queue is' if unobserved == 1 else 'Their queues are'} "
                 "unknown, not idle.")),
    ))


def completed_item_facts(ledger: EvidenceLedger, state: GameState) -> tuple[EvidenceFact, ...]:
    """Items whose logged production reached what they needed before the queue moved on.

    Evidence that a build finished, not proof: the log records progress, not completion
    events, and a player can also replace a queue item by hand. Absence of such a record
    is not evidence a building is missing — the log only started when the session did.
    """
    out = []
    by_city: dict[str, list] = {}
    for row in state.build_queues:
        if row.player == state.HUMAN and row.turn <= state.latest_turn:
            by_city.setdefault(row.city, []).append(row)
    for city, rows in sorted(by_city.items()):
        rows.sort(key=lambda r: r.turn)
        for current, following in zip(rows, rows[1:]):
            if not current.item or current.item == following.item:
                continue
            if current.needed and current.current >= current.needed:
                out.append(ledger.add(EvidenceFact(
                    id=f"completed.{city}.{current.item}.{current.turn}",
                    label=f"{_city(city)} appears to have completed {current.item}",
                    source_kind=SourceKind.DERIVED, provenance=Provenance.FAIR,
                    observed_turn=current.turn, value=current.item, unit=None,
                    subject_id=city,
                    contributing=(ledger.add(EvidenceFact(
                        id=f"queue.progress.{city}.{current.item}.{current.turn}",
                        label=f"{_city(city)}'s production on {current.item}",
                        source_kind=SourceKind.LOG, provenance=Provenance.FAIR,
                        observed_turn=current.turn, value=current.current, unit="production",
                        source_file=QUEUE_FILE,
                        record_key=(QUEUE_FILE, current.turn, state.HUMAN, city),
                        subject_id=city,
                        note=f"Needed {current.needed:.0f}.",
                    )).id,),
                    note=(f"Logged production {current.current:.1f} met the {current.needed:.0f} "
                          f"needed, and turn {following.turn} shows {following.item or 'nothing'} "
                          "queued instead. Evidence of completion, not a completion event."),
                )))
    return tuple(out)


# ---- ruleset and identity --------------------------------------------------------

def age_fact(ledger: EvidenceLedger, state: GameState) -> EvidenceFact | None:
    """The Age label on the most recent historian event.

    Dated evidence about the Age, not proof of the current Age: the label belongs to the
    event, and after a transition the newest event can still carry the old Age until
    something else happens. Callers treat an Age that has not been confirmed for the
    current turn as unknown rather than assumed.
    """
    events = [e for e in state.events if e.turn <= state.complete_through_turn and e.age]
    if not events:
        return None
    newest = max(e.turn for e in events)
    ages = sorted({e.age for e in events if e.turn == newest})
    # Two Ages on one turn means a transition was recorded mid-turn. Reporting either one
    # as "the Age" would be a guess, so report both and let the caller treat it as unknown.
    note = ("The Age this event was filed under. It dates the Age; it does not prove the "
            "Age has not changed since, and no log states the current Age directly.")
    if len(ages) > 1:
        note = (f"Turn {newest} recorded events under more than one Age ({', '.join(ages)}), "
                "so the current Age cannot be read off this log.")
    return ledger.add(EvidenceFact(
        id=f"age.observed.{newest}", label="Age recorded on the most recent world event",
        source_kind=SourceKind.LOG, provenance=Provenance.FAIR, observed_turn=newest,
        value=ages[0] if len(ages) == 1 else " / ".join(ages), unit=None,
        source_file=HISTORIAN_FILE, record_key=(HISTORIAN_FILE, newest), subject_id=None,
        note=note,
    ))


def human_identity_fact(ledger: EvidenceLedger, state: GameState) -> EvidenceFact | None:
    """The human's civilization and leader, as the engine recorded them at load.

    Unique abilities depend on exact identity, so this is carried explicitly rather than
    inferred from city-name prefixes.
    """
    row = state.identities.get(state.HUMAN)
    if row is None:
        return None
    leader = row.leader or "unknown leader"
    return ledger.add(EvidenceFact(
        id="identity.human", label="Your civilization and leader", source_kind=SourceKind.LOG,
        provenance=Provenance.FAIR, observed_turn=None, value=f"{row.civilization} / {leader}",
        unit=None, source_file=IDENTITY_FILE, record_key=(IDENTITY_FILE, state.HUMAN),
        subject_id=str(state.HUMAN),
        note="Recorded when the save loaded; it carries no turn of its own.",
    ))


# ---- defence --------------------------------------------------------------------

def defense_facts(ledger: EvidenceLedger, state: GameState) -> tuple[EvidenceFact, ...]:
    """Dated attack objectives against known city-area tiles.

    Oracle: these are the AI's own plans. Each carries the turn it was recorded and
    whether anything newer has been logged, because an objective the AI stopped
    re-emitting is not an order in force — and no record at all is not safety.
    """
    out = []
    for goal in tactical.attack_goals(state):
        out.append(ledger.add(EvidenceFact(
            id=f"defense.attack_goal.{goal['player']}.{goal['x']}.{goal['y']}.{goal['turn']}",
            label=f"{goal['name']}'s recorded objective at {goal['x']}:{goal['y']}",
            source_kind=SourceKind.LOG, provenance=Provenance.ORACLE,
            observed_turn=goal["turn"], value=goal["kind"], unit=None,
            source_file=OPERATIONS_FILE,
            record_key=(OPERATIONS_FILE, goal["turn"], goal["player"], goal["x"], goal["y"]),
            subject_id=str(goal["player"]),
            note=("Recorded this turn." if goal["age"] == 0 else
                  f"{goal['age']} turn{'' if goal['age'] == 1 else 's'} old"
                  + ("." if goal["fresh"] else
                     "; nothing newer has been logged either way, which is not evidence it "
                     "was dropped.")),
        )))
    coverage = tactical.snapshot(state)
    out.append(ledger.add(EvidenceFact(
        id=f"defense.coverage.{state.complete_through_turn}",
        label="Tactical coverage of your frontier", source_kind=SourceKind.LOG,
        provenance=Provenance.ORACLE, observed_turn=state.complete_through_turn,
        value=len(coverage["enemy_units"]), unit="recorded rival positions",
        source_file=TACTICAL_FILE,
        record_key=(TACTICAL_FILE, state.complete_through_turn),
        note=(f"{len(coverage['city_tiles'])} known city-area tiles"
              + (f", last observed on turn {coverage['city_tile_turn']}"
                 if coverage["city_tile_turn"] is not None else "")
              + ". No recorded contact means these logs recorded none; it does not mean the "
                "frontier is safe."),
    )))
    return tuple(out)


def _city(city_key: str) -> str:
    return city_key.removeprefix("LOC_CITY_NAME_").replace("_", " ").title()


def build_ledger(state: GameState, stats: tuple[str, ...] = YIELD_STATS) -> EvidenceLedger:
    """Every fact the decision layer needs, from one state.

    Builders that have no source return nothing rather than a placeholder, so a caller
    that needs a missing fact finds it absent and has to say so.
    """
    ledger = EvidenceLedger()
    for stat in stats:
        yield_comparison_fact(ledger, state, stat)
    net_gold_fact(ledger, state)
    happiness_fact(ledger, state)
    queue_facts(ledger, state)
    settlement_coverage_fact(ledger, state)
    completed_item_facts(ledger, state)
    age_fact(ledger, state)
    human_identity_fact(ledger, state)
    defense_facts(ledger, state)
    return ledger
