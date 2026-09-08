"""Oracle-only tactical intelligence from the AI's planning logs."""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass

from civ7_advisor.state.geo import hex_distance
from civ7_advisor.state.models import GameState

from .base import Insight, Provenance, Severity, humanize

NEAR_TILES = 4
FRESH_TURNS = 3
NON_COMBAT = ("FOUNDER", "SETTLER", "MIGRANT", "MERCHANT", "COMMANDER", "TREASURE")


@dataclass(frozen=True)
class UnitSighting:
    player: int
    unit_id: int
    unit_type: str
    turn: int
    x: int | None
    y: int | None
    activity: str
    order: str | None = None


def _latest_turn(rows, through: int) -> int | None:
    return max((r.turn for r in rows if r.turn <= through), default=None)


def human_city_tiles(state: GameState) -> set[tuple[int, int]]:
    """Latest plots rivals classify as enemy-city tiles owned by player zero."""
    eligible = [r for r in state.targets if r.turn <= state.complete_through_turn
                and r.owner == state.HUMAN and r.target_type == "TARGET_ENEMY_CITY"]
    latest = _latest_turn(eligible, state.complete_through_turn)
    return {(r.x, r.y) for r in eligible if r.turn == latest} if latest is not None else set()


def _orders_by_unit(state: GameState) -> dict[tuple[int, int], object]:
    latest = {}
    for row in state.combat_orders:
        if row.turn <= state.complete_through_turn and row.category == "Order" and row.unit_id is not None:
            latest[(row.player, row.unit_id)] = row
    return latest


def enemy_units(state: GameState) -> list[UnitSighting]:
    rival_ids = {p.id for p in state.rivals()}
    latest = {}
    for row in state.tactical:
        if row.player in rival_ids and row.turn <= state.complete_through_turn and row.move is not None:
            latest[(row.player, row.unit_id)] = row
    orders = _orders_by_unit(state)
    cutoff = state.complete_through_turn - FRESH_TURNS
    out = []
    for (player, unit_id), row in latest.items():
        if row.turn < cutoff:
            continue
        order = orders.get((player, unit_id))
        out.append(UnitSighting(
            player, unit_id, row.unit_type, row.turn, row.move[0], row.move[1], row.category,
            order.action if order is not None and order.turn >= cutoff else None,
        ))
    return sorted(out, key=lambda u: (u.player, u.unit_type, u.unit_id))


def own_units(state: GameState) -> list[UnitSighting]:
    latest = {}
    for row in state.unit_operations:
        if row.player == state.HUMAN and row.turn <= state.complete_through_turn:
            latest[row.unit_id] = row
    orders = _orders_by_unit(state)
    out = []
    for unit_id, row in latest.items():
        order = orders.get((state.HUMAN, unit_id))
        move = order.move if order is not None and order.turn >= state.complete_through_turn - 10 else None
        out.append(UnitSighting(
            state.HUMAN, unit_id, row.unit_type, row.turn,
            move[0] if move else None, move[1] if move else None,
            humanize(row.operation), order.action if order is not None else None,
        ))
    return sorted(out, key=lambda u: (u.unit_type, u.unit_id))


def attack_goals(state: GameState) -> list[dict]:
    tiles = human_city_tiles(state)
    rivals = {p.id: p.name for p in state.rivals()}
    t = _latest_turn(state.operations, state.complete_through_turn)
    if t is None:
        return []
    found = set()
    out = []
    for row in state.operations:
        if (row.turn == t and row.player in rivals and row.goal in tiles
                and row.operation.startswith("Attack Enemy City")):
            key = (row.player, row.goal)
            if key not in found:
                found.add(key)
                out.append({"player": row.player, "name": rivals[row.player], "x": row.goal[0],
                            "y": row.goal[1], "kind": row.operation, "turn": row.turn})
    order_turn = _latest_turn(state.combat_orders, state.complete_through_turn)
    for row in state.combat_orders:
        if (row.turn == order_turn and row.player in rivals and row.attacks and row.move in tiles):
            key = (row.player, row.move)
            if key not in found:
                found.add(key)
                out.append({"player": row.player, "name": rivals[row.player], "x": row.move[0],
                            "y": row.move[1], "kind": row.action, "turn": row.turn})
    return sorted(out, key=lambda x: (x["player"], x["x"], x["y"]))


def snapshot(state: GameState) -> dict:
    cities = [{"x": x, "y": y} for x, y in sorted(human_city_tiles(state))]
    rivals = {p.id: p.name for p in state.rivals()}
    enemies = [asdict(u) | {"name": rivals[u.player]} for u in enemy_units(state)]
    own = [asdict(u) for u in own_units(state) if u.x is not None]
    promotions = [asdict(r) for r in state.commander_promotions
                  if r.turn <= state.complete_through_turn and r.player in rivals]
    return {
        "available": bool(cities or enemies), "turn": state.complete_through_turn,
        "city_tiles": cities, "human_units": own, "enemy_units": enemies,
        "attack_goals": attack_goals(state), "commander_promotions": promotions,
    }


def _nearby(state: GameState) -> dict[int, list[tuple[UnitSighting, int]]]:
    cities = human_city_tiles(state)
    out: dict[int, list[tuple[UnitSighting, int]]] = {}
    if not cities:
        return out
    for unit in enemy_units(state):
        distance = min(hex_distance((unit.x, unit.y), city) for city in cities)  # type: ignore[arg-type]
        if distance <= NEAR_TILES:
            out.setdefault(unit.player, []).append((unit, distance))
    return out


def _matchup(state: GameState, nearby: dict[int, list[tuple[UnitSighting, int]]]) -> Insight | None:
    enemy_types = Counter(u.unit_type for rows in nearby.values() for u, _ in rows)
    own_types = {u.unit_type for u in own_units(state) if not any(word in u.unit_type for word in NON_COMBAT)}
    matrix = {row.attacker: row.ratings for row in state.unit_efficiency}
    if not enemy_types or not own_types or not matrix:
        return None
    enemy = enemy_types.most_common(1)[0][0]
    choices = [(matrix.get(unit, {}).get(enemy), unit) for unit in own_types]
    choices = [(rating, unit) for rating, unit in choices if rating is not None]
    if not choices:
        return None
    rating, counter = max(choices)
    return Insight(
        id="tactical.matchup", advisor="tactical", severity=Severity.ADVISE,
        provenance=Provenance.ORACLE, title=f"Best logged matchup: {humanize(counter)}",
        recommendation=f"Prefer {humanize(counter)} when answering nearby {humanize(enemy)} units.",
        why=(f"The AI efficiency table rates {humanize(counter)} at {rating:.0f} against "
             f"{humanize(enemy)} (100 is same-type baseline). This is a heuristic rating, not win odds."),
        turn=state.complete_through_turn,
    )


def advise(state: GameState) -> list[Insight]:
    t = state.complete_through_turn
    rivals = {p.id: p.name for p in state.rivals()}
    nearby = _nearby(state)
    out = []
    for player, rows in nearby.items():
        types = Counter(humanize(u.unit_type) for u, _ in rows)
        detail = ", ".join(f"{n} {kind}" for kind, n in types.most_common())
        closest = min(distance for _, distance in rows)
        orders = sorted({u.order for u, _ in rows if u.order})
        evidence = f"{detail}; closest planned tile is {closest} hexes from a human city tile"
        if orders:
            evidence += f"; orders include {', '.join(orders)}"
        out.append(Insight(
            id=f"tactical.enemy_units_near.{player}", advisor="tactical", severity=Severity.WARN,
            provenance=Provenance.ORACLE, title=f"{rivals[player]} has units near your city",
            recommendation="Inspect that frontier and reinforce the threatened city before ending the turn.",
            why=evidence + ".", turn=t, subject_player=player,
        ))
    goals = attack_goals(state)
    for player in sorted({g["player"] for g in goals}):
        theirs = [g for g in goals if g["player"] == player]
        coords = ", ".join(f"{g['x']}:{g['y']}" for g in theirs)
        out.append(Insight(
            id=f"tactical.ordered_attack.{player}", advisor="tactical", severity=Severity.CRITICAL,
            provenance=Provenance.ORACLE, title=f"{rivals[player]} is planning against your city tiles",
            recommendation="Treat the marked tiles as immediate attack objectives and reposition defenders now.",
            why=f"Turn {max(g['turn'] for g in theirs)} AI attack goals/orders overlap human city tiles at {coords}.",
            turn=t, subject_player=player,
        ))
        evals = [r for r in state.operation_evals if r.player == player and r.turn <= t
                 and r.kind == "Attack Enemy City"]
        if evals:
            latest = max(evals, key=lambda r: r.turn)
            out.append(Insight(
                id=f"tactical.odds.{player}", advisor="tactical", severity=Severity.INFO,
                provenance=Provenance.ORACLE, title=f"{rivals[player]} attack estimate: {latest.odds:.0%}",
                recommendation="Use this as AI confidence context, not as a combat probability.",
                why=f"AI_Operation_Eval recorded Attack Enemy City odds {latest.odds:.2f} on turn {latest.turn}.",
                turn=t, subject_player=player,
            ))
    exposed = [r for r in state.tactical if r.turn >= t - FRESH_TURNS and r.turn <= t
               and r.player in rivals and r.target_owner == state.HUMAN and r.attack is not None]
    if exposed:
        types = Counter(humanize(r.target_unit_type or "UNIT") for r in exposed)
        out.append(Insight(
            id="tactical.own_exposed", advisor="tactical", severity=Severity.WARN,
            provenance=Provenance.ORACLE, title="Enemy tactical AI has targets on your units",
            recommendation="Review the exposed units before ending the turn; retreat or screen damaged targets.",
            why=f"Recent AI attack rows target {sum(types.values())} sightings: "
                + ", ".join(f"{n} {kind}" for kind, n in types.most_common()) + ".",
            turn=t,
        ))
    matchup = _matchup(state, nearby)
    if matchup:
        out.append(matchup)
    return out
