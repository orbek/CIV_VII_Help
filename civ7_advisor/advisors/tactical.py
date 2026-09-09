"""Oracle-only tactical intelligence from the AI's planning logs."""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass

from civ7_advisor.state.geo import hex_distance
from civ7_advisor.state.models import GameState

from .base import Insight, Provenance, Severity, humanize

NEAR_TILES = 4
FRESH_TURNS = 3
MAP_NEAR_TILES = 8
# An attack operation is an episodic plan: the AI re-emits it on every turn it still
# holds the objective, so a row that stops appearing is a plan that stopped, not a
# standing threat. Beyond this age the goal is reported as a dated last-known objective
# instead of an immediate one. Persistent state — a declared war, a signed peace — has
# nothing to do with this window and is dated by the threat advisor from its own sources.
GOAL_FRESH_TURNS = 2
# Known city-area tiles within this many hexes of each other are one frontier. An empire
# with settlements on two continents has two frontiers, and squeezing both into one view
# shrinks each until neither is readable — which is the defect this exists to fix.
CLUSTER_RADIUS = 6
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

    @property
    def key(self) -> str:
        """A stable identity for this contact within the session.

        The AI's own player and unit ids, not a position or a list index: a contact keeps
        its identity when it moves, and selecting it in a table selects the same unit on
        the map. Not stable across a reload, which is why the session's epoch changes.
        """
        return f"{self.player}:{self.unit_id}"


def _latest_turn(rows, through: int) -> int | None:
    return max((r.turn for r in rows if r.turn <= through), default=None)


def human_city_tiles(state: GameState) -> set[tuple[int, int]]:
    """Latest plots rivals classify as enemy-city tiles owned by player zero."""
    return set(city_tile_observations(state))


def city_tile_observations(state: GameState) -> dict[tuple[int, int], int]:
    """Those same tiles, each mapped to the turn it was observed on.

    Every tile in one reading comes from the same latest targeting turn, but the caller
    still needs that turn: "known city area" with no date reads as current fact, and
    these rows can be several turns old when the AI has not re-targeted since.
    """
    eligible = [r for r in state.targets if r.turn <= state.complete_through_turn
                and r.owner == state.HUMAN and r.target_type == "TARGET_ENEMY_CITY"]
    latest = _latest_turn(eligible, state.complete_through_turn)
    if latest is None:
        return {}
    return {(r.x, r.y): r.turn for r in eligible if r.turn == latest}


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
    positions = {}
    for target in state.targets:
        if (target.turn <= state.complete_through_turn
                and target.turn >= state.complete_through_turn - FRESH_TURNS
                and target.owner == state.HUMAN
                and target.target_type.endswith("_PRIORITY_UNIT")):
            positions[target.target_id] = target
    out = []
    for unit_id, row in latest.items():
        position = positions.get(unit_id)
        out.append(UnitSighting(
            state.HUMAN, unit_id, row.unit_type, position.turn if position else row.turn,
            position.x if position else None, position.y if position else None,
            humanize(position.target_type) if position else humanize(row.operation), None,
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
    for goal in out:
        goal["age"] = state.complete_through_turn - goal["turn"]
        goal["fresh"] = goal["age"] <= GOAL_FRESH_TURNS
    return sorted(out, key=lambda x: (x["player"], x["x"], x["y"]))


def city_clusters(state: GameState) -> list[dict]:
    """Known city-area tiles grouped into contiguous frontiers.

    Single-linkage on hex distance: tiles within `CLUSTER_RADIUS` of each other are one
    frontier. Each is labelled by its own coordinates, never by a settlement name — the
    source is a list of plots the AI targets, and nothing in it says which settlement any
    plot belongs to.
    """
    observed = city_tile_observations(state)
    tiles = sorted(observed)
    parent = list(range(len(tiles)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for a in range(len(tiles)):
        for b in range(a + 1, len(tiles)):
            if hex_distance(tiles[a], tiles[b]) <= CLUSTER_RADIUS:
                parent[find(a)] = find(b)

    grouped: dict[int, list[tuple[int, int]]] = {}
    for index, tile in enumerate(tiles):
        grouped.setdefault(find(index), []).append(tile)

    clusters = []
    for members in sorted(grouped.values(), key=lambda m: (-len(m), m[0])):
        xs = [x for x, _ in members]
        ys = [y for _, y in members]
        centre = (round(sum(xs) / len(xs)), round(sum(ys) / len(ys)))
        turns = [observed[t] for t in members]
        clusters.append({
            "id": f"area-{centre[0]}-{centre[1]}",
            "label": f"Area around {centre[0]}:{centre[1]}",
            "centre": {"x": centre[0], "y": centre[1]},
            "tiles": [{"x": x, "y": y, "turn": observed[(x, y)],
                       "age": state.complete_through_turn - observed[(x, y)]}
                      for x, y in members],
            "turn": max(turns),
            "bounds": {"min_x": min(xs), "max_x": max(xs),
                       "min_y": min(ys), "max_y": max(ys)},
        })
    return clusters


def _nearest_cluster(clusters: list[dict],
                     point: tuple[int, int]) -> tuple[str | None, int | None]:
    """(nearest frontier id, hexes to it). Both None when no city area is known at all."""
    best_id, best = None, None
    for cluster in clusters:
        distance = min(hex_distance(point, (t["x"], t["y"])) for t in cluster["tiles"])
        if best is None or distance < best:
            best_id, best = cluster["id"], distance
    return best_id, best


def _assign(clusters: list[dict], point: tuple[int, int]) -> dict:
    """Which frontier a position belongs to, and how far it is from the nearest one.

    `cluster` is only set when the position is actually near that frontier. A unit sixty
    hexes away is nearest to *some* area by arithmetic, and calling that its frontier
    would put it on a map of a place it is nowhere near — so it stays unassigned and
    appears under All contacts with its distance shown.
    """
    nearest_id, distance = _nearest_cluster(clusters, point)
    near = distance is not None and distance <= MAP_NEAR_TILES
    return {"cluster": nearest_id if near else None,
            "nearest_cluster": nearest_id, "distance_to_city": distance, "near": near}


def snapshot(state: GameState) -> dict:
    observed = city_tile_observations(state)
    cities = [{"x": x, "y": y, "turn": observed[(x, y)],
               "age": state.complete_through_turn - observed[(x, y)]}
              for x, y in sorted(observed)]
    clusters = city_clusters(state)
    rivals = {p.id: p.name for p in state.rivals()}
    enemies = []
    for unit in enemy_units(state):
        placement = _assign(clusters, (unit.x, unit.y))
        enemies.append(asdict(unit) | placement | {
            "key": unit.key,
            "name": rivals[unit.player],
            "age": state.complete_through_turn - unit.turn,
            "nearest_city_tile": None,
        })
        cluster_id = placement["nearest_cluster"]
        if cluster_id is not None:
            nearest = min(
                ((hex_distance((unit.x, unit.y), (t["x"], t["y"])), t)
                 for c in clusters if c["id"] == cluster_id for t in c["tiles"]),
                key=lambda pair: pair[0])[1]
            enemies[-1]["nearest_city_tile"] = {"x": nearest["x"], "y": nearest["y"]}
    own = []
    for unit in own_units(state):
        if unit.x is None:
            continue
        placement = _assign(clusters, (unit.x, unit.y))
        nearest_enemy = min(
            (hex_distance((unit.x, unit.y), (e["x"], e["y"]))
             for e in enemies if e["x"] is not None),
            default=None)
        distance = placement["distance_to_city"]
        own.append(asdict(unit) | placement | {
            "key": unit.key,
            "age": state.complete_through_turn - unit.turn,
            "distance_to_enemy": nearest_enemy,
            # A unit far from every known city area with an enemy close by needs its own
            # focus: folding it into the selected frontier would zoom that frontier out
            # until the thing being looked at is a dot.
            "exposed": nearest_enemy is not None and nearest_enemy <= NEAR_TILES
            and (distance is None or distance > MAP_NEAR_TILES),
        })
    promotions = [asdict(r) | {"name": rivals[r.player]} for r in state.commander_promotions
                  if r.turn <= state.complete_through_turn and r.player in rivals]
    goals = attack_goals(state)
    for goal in goals:
        # A goal names a tile the AI classifies as ours, so it always belongs to the
        # frontier that tile is in.
        goal["cluster"] = _nearest_cluster(clusters, (goal["x"], goal["y"]))[0]
    return {
        "available": bool(cities or enemies), "turn": state.complete_through_turn,
        "map_near_tiles": MAP_NEAR_TILES, "fresh_turns": FRESH_TURNS,
        "goal_fresh_turns": GOAL_FRESH_TURNS, "cluster_radius": CLUSTER_RADIUS,
        # Coverage, not safety: "no contact recorded" means these logs recorded none,
        # which is not the same as a quiet frontier.
        "city_tile_turn": max(observed.values(), default=None),
        "clusters": clusters,
        "city_tiles": cities, "human_units": own, "enemy_units": enemies,
        "attack_goals": goals, "commander_promotions": promotions,
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


def _realized_disagreement(state: GameState, counter: str, enemy: str) -> bool:
    cutoff = state.complete_through_turn - 10
    rival_ids = {p.id for p in state.rivals()}
    for combat in state.combats:
        if combat.turn < cutoff or combat.turn > state.complete_through_turn:
            continue
        if combat.att_player == state.HUMAN and combat.def_player in rival_ids:
            mine, theirs = combat.attacker.kind, combat.defender.kind
        elif combat.def_player == state.HUMAN and combat.att_player in rival_ids:
            mine, theirs = combat.defender.kind, combat.attacker.kind
        else:
            continue
        if mine == counter and theirs == enemy and combat.loser() == state.HUMAN:
            return True
    return False


def _matchup(state: GameState, nearby: dict[int, list[tuple[UnitSighting, int]]]) -> Insight | None:
    enemy_types = Counter(u.unit_type for rows in nearby.values() for u, _ in rows)
    own_types = {u.unit_type for u in own_units(state) if not any(word in u.unit_type for word in NON_COMBAT)}
    matrix = {row.attacker: row.ratings for row in state.unit_efficiency}
    if not enemy_types or not own_types or not matrix:
        return None
    matches = []
    for enemy, _ in enemy_types.most_common():
        choices = [(matrix.get(unit, {}).get(enemy), unit) for unit in own_types]
        choices = [(rating, unit) for rating, unit in choices if rating is not None]
        if choices:
            rating, counter = max(choices)
            matches.append((enemy, counter, rating, _realized_disagreement(state, counter, enemy)))
    if not matches:
        return None
    recommendations = "; ".join(f"{humanize(enemy)} → {humanize(counter)}" for enemy, counter, _, _ in matches)
    ratings = "; ".join(
        f"{humanize(counter)} vs {humanize(enemy)} {rating / 100:.2f}× same-type baseline"
        for enemy, counter, rating, _ in matches
    )
    disagreed = [(enemy, counter) for enemy, counter, _, mismatch in matches if mismatch]
    caveat = " These are heuristic ratings, not win odds."
    if disagreed:
        pairs = ", ".join(f"{humanize(counter)} vs {humanize(enemy)}" for enemy, counter in disagreed)
        caveat += f" Recent realized combat disagreed for {pairs}; treat that rating cautiously."
    return Insight(
        id="tactical.matchup", advisor="tactical", severity=Severity.ADVISE,
        provenance=Provenance.ORACLE, title="Best logged counters for nearby units",
        recommendation=f"Prefer these available counters where practical: {recommendations}.",
        why=f"The AI efficiency table rates {ratings}.{caveat}",
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
        observed = max(g["turn"] for g in theirs)
        age = t - observed
        if age <= GOAL_FRESH_TURNS:
            out.append(Insight(
                id=f"tactical.ordered_attack.{player}", advisor="tactical", severity=Severity.CRITICAL,
                provenance=Provenance.ORACLE,
                title=f"{rivals[player]} is planning against your city tiles",
                recommendation="Treat the marked tiles as immediate attack objectives and reposition defenders now.",
                why=f"Turn {observed} AI attack goals/orders overlap human city tiles at {coords}.",
                turn=t, subject_player=player,
            ))
        else:
            # An attack operation the AI has stopped re-emitting for several turns is a
            # last-known objective, not an order in force. Keep the observation — the
            # frontier was contested — but do not tell the player to react now to a plan
            # that may already be abandoned, and do not read the silence as safety either.
            out.append(Insight(
                id=f"tactical.stale_attack_goal.{player}", advisor="tactical", severity=Severity.ADVISE,
                provenance=Provenance.ORACLE,
                title=f"{rivals[player]}'s last recorded objective was your city tiles",
                recommendation=("Re-inspect that frontier before relying on it: this objective is "
                                "dated, and no newer plan has been recorded either way."),
                why=(f"Turn {observed} AI attack goals/orders overlapped human city tiles at {coords}; "
                     f"that is {age} turns before turn {t}, and no attack goal has been logged since. "
                     "Absence of a newer record is not evidence the objective was dropped."),
                turn=t, subject_player=player,
            ))
        evals = [r for r in state.operation_evals if r.player == player and r.turn <= t
                 and r.kind == "Attack Enemy City"]
        if evals:
            latest = max(evals, key=lambda r: r.turn)
            eval_age = t - latest.turn
            dated = "" if eval_age <= GOAL_FRESH_TURNS else f" That estimate is {eval_age} turns old."
            out.append(Insight(
                id=f"tactical.odds.{player}", advisor="tactical", severity=Severity.INFO,
                provenance=Provenance.ORACLE, title=f"{rivals[player]} attack estimate: {latest.odds:.0%}",
                recommendation="Use this as AI confidence context, not as a combat probability.",
                why=(f"AI_Operation_Eval recorded Attack Enemy City odds {latest.odds:.2f} "
                     f"on turn {latest.turn}.{dated}"),
                turn=t, subject_player=player,
            ))
    exposed = []
    for mine in (u for u in own_units(state) if u.x is not None and u.y is not None):
        distances = [(enemy, hex_distance((mine.x, mine.y), (enemy.x, enemy.y)))
                     for enemy in enemy_units(state) if enemy.x is not None and enemy.y is not None]
        if distances:
            enemy, distance = min(distances, key=lambda pair: pair[1])
            if distance <= NEAR_TILES:
                exposed.append((mine, enemy, distance))
    if exposed:
        details = ", ".join(
            f"your {humanize(mine.unit_type)} at {mine.x}:{mine.y} is {distance} hexes from "
            f"{rivals[enemy.player]}'s {humanize(enemy.unit_type)}"
            for mine, enemy, distance in exposed
        )
        out.append(Insight(
            id="tactical.own_exposed", advisor="tactical", severity=Severity.WARN,
            provenance=Provenance.ORACLE, title="Enemy tactical AI has targets on your units",
            recommendation="Review the exposed units before ending the turn; retreat or screen damaged targets.",
            why=f"Enemy target logs reveal {len(exposed)} exposed unit position(s): {details}.",
            turn=t,
        ))
    matchup = _matchup(state, nearby)
    if matchup:
        out.append(matchup)
    return out
