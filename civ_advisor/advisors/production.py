"""What everyone is building, how soon, and whether your queue matches your worst gap."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache

from civ_advisor.state.models import BuildQueueRow, GameState

from . import economy
from .base import Insight, Provenance, Severity, humanize

log = logging.getLogger(__name__)

RIVAL_MILITARY_SHARE = 0.5  # share of a rival's cities building military at/above which we warn
QUEUE_STALE_TURNS = 1  # a city whose latest row is older than cutoff - this is treated as gone
# Non-combat units: queueing these is not building an army, so they never count as military.
CIVILIAN_UNITS = {"UNIT_SETTLER", "UNIT_MIGRANT", "UNIT_FOUNDER", "UNIT_SCOUT", "UNIT_MERCHANT"}
CIVILIAN_PREFIXES = ("UNIT_GREAT_",)  # whole civilian families matched by prefix (every Great Person)
# Which economy yield an item mainly serves, where no reviewed guide says otherwise.
# These are unverified heuristics: nothing in the logs or the shipped catalog establishes
# them. `item_yield` below prefers the reviewed guide catalog, so this table is the
# fallback for items the catalog does not cover yet — not a second rules table competing
# with it. An item in neither suppresses the mismatch insight rather than guessing.
UNVERIFIED_ITEM_YIELDS: dict[str, str] = {
    "BUILDING_BRICKYARD": "production", "BUILDING_SAWPIT": "production",
    "BUILDING_GRANARY": "food", "BUILDING_FISHING_QUAY": "food",
    "BUILDING_LIBRARY": "science", "BUILDING_ACADEMY": "science",
    "BUILDING_MONUMENT": "culture", "BUILDING_AMPHITHEATER": "culture",
    "BUILDING_MARKET": "gold", "BUILDING_BANK": "gold",
}


# Kept as the historical name so existing callers and tests keep working; it now names
# the unverified fallback explicitly.
ITEM_YIELDS = UNVERIFIED_ITEM_YIELDS


@lru_cache(maxsize=1)
def _catalog_item_yields() -> dict[str, tuple[str, ...]]:
    """The reviewed associations, or nothing if the catalog cannot be loaded.

    A broken catalog must not take the production advisor down with it: the advice degrades
    to the unverified table, which is what shipped before the catalog existed.
    """
    try:
        from civ_advisor.knowledge.catalog import load_catalog
        return load_catalog().item_yields
    except Exception:  # pragma: no cover - a packaging fault, not a gameplay path
        log.warning("guide catalog unavailable; falling back to unverified item yields")
        return {}


def item_yield(item: str) -> str | None:
    """Which yield this build item serves, reviewed source first.

    One lookup for the whole codebase, so the decision layer and this advisor cannot end
    up disagreeing about what a building is for.
    """
    reviewed = _catalog_item_yields().get(item)
    if reviewed:
        return reviewed[0]
    return UNVERIFIED_ITEM_YIELDS.get(item)


def reviewed_yield(item: str) -> bool:
    """Whether the association came from a reviewed guide rather than a heuristic."""
    return bool(_catalog_item_yields().get(item))


def is_military(item: str) -> bool:
    return item.startswith("UNIT_") and item not in CIVILIAN_UNITS and not item.startswith(CIVILIAN_PREFIXES)


@dataclass(frozen=True)
class CityQueue:
    player: int
    city: str
    item: str
    added: float
    current: float
    needed: float
    turns_to_complete: int | None
    turn: int


def queues(state: GameState) -> dict[int, list[CityQueue]]:
    """Latest logged queue row per (player, city), for cities still being logged.

    The human's row is written when they act, so their live queue is the row at latest_turn;
    rivals are read at complete_through_turn like every other AI-side fact. A city whose
    latest row is more than QUEUE_STALE_TURNS behind its player's cutoff is treated as gone
    (captured, razed, or no longer logged) rather than reported from an old row for ever.
    """
    latest: dict[tuple[int, str], BuildQueueRow] = {}
    for q in state.build_queues:
        cutoff = state.latest_turn if q.player == state.HUMAN else state.complete_through_turn
        if not cutoff - QUEUE_STALE_TURNS <= q.turn <= cutoff:
            continue
        key = (q.player, q.city)
        if key not in latest or q.turn >= latest[key].turn:  # ">=": the later row of a turn wins
            latest[key] = q
    out: dict[int, list[CityQueue]] = {}
    for (pid, city), q in sorted(latest.items()):
        out.setdefault(pid, []).append(
            CityQueue(pid, city, q.item, q.added, q.current, q.needed, q.turns_to_complete, q.turn)
        )
    return out


def rival_military_share(state: GameState) -> dict[int, float]:
    qs = queues(state)
    return {
        r.id: sum(is_military(c.item) for c in qs[r.id]) / len(qs[r.id])
        for r in state.rivals() if qs.get(r.id)
    }


def _city(city_key: str) -> str:
    return city_key.removeprefix("LOC_CITY_NAME_").replace("_", " ").title()


def _queue_phrase(c: CityQueue) -> str:
    if not c.item:
        return f"{_city(c.city)}: idle"
    n = c.turns_to_complete
    if n is None:
        return f"{_city(c.city)}: {humanize(c.item)} (stalled)"
    if n == 0:
        return f"{_city(c.city)}: {humanize(c.item)} finishing this turn"
    return f"{_city(c.city)}: {humanize(c.item)} in {n} turn{'s' if n != 1 else ''}"


def advise(state: GameState) -> list[Insight]:
    t = state.complete_through_turn
    out: list[Insight] = []
    qs = queues(state)
    human = qs.get(state.HUMAN, [])

    if human:
        out.append(Insight(
            id="production.own_queue", advisor="production", severity=Severity.INFO, provenance=Provenance.FAIR,
            title="What your cities are building",
            recommendation="Check each queue against the gap the Economy tab flags; an idle city is the first thing to fix.",
            why="; ".join(_queue_phrase(c) for c in human) + ".", turn=t, subject_player=state.HUMAN,
        ))
        gaps = economy.behind(state)
        building = [c for c in human if c.item]
        served = [item_yield(c.item) for c in building]
        if gaps and building and all(served) and gaps[0].stat not in served:
            worst = gaps[0]
            unreviewed = sorted({humanize(c.item) for c in building
                                 if not reviewed_yield(c.item)})
            # The queue rows are read at latest_turn, the economy comparison at complete_through_turn,
            # so each clause is dated from the rows it actually came from.
            queue_evidence = ", ".join(
                f"{humanize(c.item)} as of turn {c.turn}" for c in building
            )
            serve = "serves" if len(building) == 1 else "serve"
            out.append(Insight(
                id="production.mismatch", advisor="production", severity=Severity.ADVISE, provenance=Provenance.FAIR,
                title=f"Nothing in your queues addresses {worst.label}",
                recommendation=f"Your worst gap is {worst.label} ({worst.ratio:.0%} of the rival median). "
                               f"{economy.YIELDS[worst.stat][1]}",
                why=f"You are building {queue_evidence}, which {serve} "
                    f"{', '.join(sorted(set(served)))}, not {worst.label} — "
                    f"your worst gap on turn {t}."
                    + (f" No reviewed guide establishes what {', '.join(unreviewed)} "
                       "serves; that association is our own heuristic." if unreviewed else ""),
                turn=t, subject_player=state.HUMAN,
            ))

    shares = rival_military_share(state)
    for r in state.rivals():
        share = shares.get(r.id)
        if share is None or share < RIVAL_MILITARY_SHARE:
            continue
        cities = qs[r.id]
        mil = [c for c in cities if is_military(c.item)]
        row_turns = [c.turn for c in cities]
        dated = (f"Turn {row_turns[0]}" if len(set(row_turns)) == 1
                 else f"Queue rows from turns {min(row_turns)}–{max(row_turns)}")
        city_word = "city" if len(cities) == 1 else "cities"
        verb = "is" if len(mil) == 1 else "are"
        out.append(Insight(
            id=f"production.rival_military.{r.id}", advisor="production", severity=Severity.WARN,
            provenance=Provenance.ORACLE, title=f"{r.name} is building an army",
            recommendation="Treat this as a leading signal, not proof of war. Compare it with targeting and "
                           "war intent; match the build or reinforce the border if those signals agree.",
            why=f"{dated}: {len(mil)} of {r.name}'s {len(cities)} {city_word} {verb} producing military units "
                f"({', '.join(humanize(c.item) for c in mil)}).",
            turn=t, subject_player=r.id,
        ))
    return out
