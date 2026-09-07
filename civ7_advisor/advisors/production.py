"""What everyone is building, how soon, and whether your queue matches your worst gap."""
from __future__ import annotations

from dataclasses import dataclass

from civ7_advisor.state.models import GameState

from . import economy
from .base import Insight, Provenance, Severity, humanize

RIVAL_MILITARY_SHARE = 0.5  # share of a rival's cities building military at/above which we warn
CIVILIAN_UNITS = {"UNIT_SETTLER", "UNIT_MIGRANT", "UNIT_FOUNDER", "UNIT_SCOUT", "UNIT_MERCHANT"}
CIVILIAN_PREFIXES = ("UNIT_GREAT_",)
# Which economy yield an item mainly serves. UNVERIFIED against current game rules (phase 3
# checks it); an item that is not listed suppresses the mismatch insight rather than guessing.
ITEM_YIELDS: dict[str, str] = {
    "BUILDING_BRICKYARD": "production", "BUILDING_SAWPIT": "production",
    "BUILDING_GRANARY": "food", "BUILDING_FISHING_QUAY": "food",
    "BUILDING_LIBRARY": "science", "BUILDING_ACADEMY": "science",
    "BUILDING_MONUMENT": "culture", "BUILDING_AMPHITHEATER": "culture",
    "BUILDING_MARKET": "gold", "BUILDING_BANK": "gold",
}


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
    """Latest logged queue row per (player, city).

    The human's row is written when they act, so their live queue is the row at latest_turn;
    rivals are read at complete_through_turn like every other AI-side fact.
    """
    latest: dict[tuple[int, str], object] = {}
    for q in state.build_queues:
        cutoff = state.latest_turn if q.player == state.HUMAN else state.complete_through_turn
        if q.turn > cutoff:
            continue
        key = (q.player, q.city)
        if key not in latest or q.turn > latest[key].turn:  # type: ignore[attr-defined]
            latest[key] = q
    out: dict[int, list[CityQueue]] = {}
    for (pid, city), q in sorted(latest.items()):
        out.setdefault(pid, []).append(
            CityQueue(pid, city, q.item, q.added, q.current, q.needed, q.turns_to_complete, q.turn)  # type: ignore[attr-defined]
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
    if c.turns_to_complete is None:
        return f"{_city(c.city)}: {humanize(c.item)} (stalled)"
    n = c.turns_to_complete
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
        behind = sorted((c for c in economy.comparison(state) if c.ratio < economy.BEHIND_RATIO), key=lambda c: c.ratio)
        building = [c for c in human if c.item]
        served = [ITEM_YIELDS.get(c.item) for c in building]
        if behind and building and all(served) and behind[0].stat not in served:
            worst = behind[0]
            out.append(Insight(
                id="production.mismatch", advisor="production", severity=Severity.ADVISE, provenance=Provenance.FAIR,
                title=f"Nothing in your queues addresses {worst.label}",
                recommendation=f"Your worst gap is {worst.label} ({worst.ratio:.0%} of the rival median). "
                               f"{economy.YIELDS[worst.stat][1]}",
                why=f"Turn {t}: you are building {', '.join(humanize(c.item) for c in building)}, which serve "
                    f"{', '.join(sorted(set(served)))}, not {worst.label}.",
                turn=t, subject_player=state.HUMAN,
            ))

    shares = rival_military_share(state)
    for r in state.rivals():
        share = shares.get(r.id)
        if share is None or share < RIVAL_MILITARY_SHARE:
            continue
        cities = qs[r.id]
        mil = [c for c in cities if is_military(c.item)]
        out.append(Insight(
            id=f"production.rival_military.{r.id}", advisor="production", severity=Severity.WARN,
            provenance=Provenance.ORACLE, title=f"{r.name} is building an army",
            recommendation="Treat this as the earliest warning you get — the units are built before the AI "
                           "decides to declare. Match the build, or shore up the shared border now.",
            why=f"Turn {t}: {len(mil)} of {r.name}'s {len(cities)} cities are producing military units "
                f"({', '.join(humanize(c.item) for c in mil)}).",
            turn=t, subject_player=r.id,
        ))
    return out
