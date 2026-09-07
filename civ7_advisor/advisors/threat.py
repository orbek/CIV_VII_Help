"""Who is coming for you, and how much time you have."""
from __future__ import annotations

from dataclasses import dataclass

from civ7_advisor.state.models import GameState, IntentKind, Player

from .base import Insight, Provenance, Severity

WAR_INTENT_WARN = 100.0      # AI DECLARE_WAR score at/above which we warn; committed AIs sit near 200
WAR_INTENT_WATCH = 50.0      # at/above this (but below WARN) we mention it as INFO
RECENT_TURNS = 10            # window in which executed actions and kills count as "recent"
MILITARY_RATIO_ADVISE = 1.5  # rival land units / human land units at/above which we advise
ARMY_GROWTH_TURNS = 10       # window over which army growth is compared
ARMY_GROWTH_DELTA = 3        # rival must have gained this many more land units than the human

KILL_EVENTS = ("UNIT_KILLED", "SHIP_SUNK")
CITY_TARGET = "TARGET_ENEMY_CITY"
UNIT_TARGET_SUFFIX = "_PRIORITY_UNIT"


@dataclass(frozen=True)
class RivalThreat:
    player: int
    name: str
    land_units: int
    human_land_units: int
    military_ratio: float
    war_score: float | None        # latest SCORED DECLARE_WAR against the human, if logged this/last turn
    war_score_since: int | None    # first turn of the current unbroken run at/above WAR_INTENT_WATCH
    at_war_since: int | None       # most recent EXECUTED DECLARE_WAR on the human within RECENT_TURNS
    kills: int                     # kills between the two within RECENT_TURNS
    losses: int                    # ... of which were the human's units
    latest_fight: tuple[int, int, int] | None  # (turn, x, y)
    target_turn: int | None        # turn the targeting rows below come from
    city_tiles_targeted: int
    units_targeted: int
    target_box: tuple[int, int, int, int] | None  # (min_x, max_x, min_y, max_y)


def summarize(state: GameState) -> list[RivalThreat]:
    human_turn = state.at(state.HUMAN)
    if human_turn is None:
        return []
    return [_summarize_rival(state, rival, human_turn.land_units) for rival in state.rivals()]


def _summarize_rival(state: GameState, rival: Player, human_land: int) -> RivalThreat:
    t = state.complete_through_turn
    window = range(t - RECENT_TURNS + 1, t + 1)
    rt = state.at(rival.id, t)
    land = rt.land_units if rt else 0

    war_rows = [
        i for i in state.intents
        if i.action == "DECLARE_WAR" and i.actor == rival.id and i.target == state.HUMAN
    ]
    executed = [i for i in war_rows if i.kind is IntentKind.EXECUTED and i.turn in window]
    at_war_since = max((i.turn for i in executed), default=None)

    scored = sorted((i for i in war_rows if i.kind is IntentKind.SCORED and i.turn <= t), key=lambda i: i.turn)
    war_score = war_since = None
    if scored and scored[-1].turn >= t - 1:  # the AI logs lag the human by up to one turn
        war_score = scored[-1].score
        if war_score is not None and war_score >= WAR_INTENT_WATCH:
            for i in reversed(scored):
                if i.score is None or i.score < WAR_INTENT_WATCH:
                    break
                war_since = i.turn

    fights = [
        e for e in state.events
        if e.type in KILL_EVENTS and e.turn in window and {e.player, e.opponent} == {state.HUMAN, rival.id}
    ]
    latest = max(fights, key=lambda e: e.turn, default=None)

    rows = [g for g in state.targets if g.player == rival.id and g.owner == state.HUMAN and g.turn <= t]
    target_turn = max((g.turn for g in rows), default=None)
    if target_turn is not None and target_turn < t - 1:
        target_turn = None
    rows = [g for g in rows if g.turn == target_turn]
    cities = [g for g in rows if g.target_type == CITY_TARGET]
    units = [g for g in rows if g.target_type.endswith(UNIT_TARGET_SUFFIX)]
    box = None
    if cities or units:
        xs = [g.x for g in cities + units]
        ys = [g.y for g in cities + units]
        box = (min(xs), max(xs), min(ys), max(ys))

    return RivalThreat(
        player=rival.id, name=rival.name, land_units=land, human_land_units=human_land,
        military_ratio=land / max(human_land, 1), war_score=war_score, war_score_since=war_since,
        at_war_since=at_war_since, kills=len(fights),
        losses=sum(e.player == state.HUMAN for e in fights),
        latest_fight=(latest.turn, latest.x, latest.y) if latest else None,
        target_turn=target_turn if (cities or units) else None,
        city_tiles_targeted=len(cities), units_targeted=len(units), target_box=box,
    )


def _army_growth(state: GameState, rival_id: int) -> tuple[list[float], list[float]] | None:
    rs = state.series(rival_id, "land_units", ARMY_GROWTH_TURNS)
    hs = state.series(state.HUMAN, "land_units", ARMY_GROWTH_TURNS)
    if len(rs) < 2 or len(hs) < 2:
        return None
    return rs, hs


def advise(state: GameState) -> list[Insight]:
    t = state.complete_through_turn
    out: list[Insight] = []
    for r in summarize(state):
        common = dict(advisor="threat", turn=t, subject_player=r.player)

        if r.at_war_since is not None:
            out.append(Insight(
                id=f"threat.at_war.{r.player}", severity=Severity.CRITICAL, provenance=Provenance.ORACLE,
                title=f"{r.name} has declared war on you",
                recommendation="Garrison border settlements, pull exposed units back to defensible "
                               "terrain, and switch production to military until the front stabilises.",
                why=f"{r.name}'s AI executed DECLARE_WAR against you on turn {r.at_war_since}.",
                **common,
            ))
        elif r.war_score is not None and r.war_score >= WAR_INTENT_WATCH:
            held = t - (r.war_score_since or t) + 1
            out.append(Insight(
                id=f"threat.war_intent.{r.player}",
                severity=Severity.WARN if r.war_score >= WAR_INTENT_WARN else Severity.INFO,
                provenance=Provenance.ORACLE,
                title=f"{r.name} is weighing war against you",
                recommendation="Build units now, not when the declaration comes: walls in the border "
                               "settlement, a commander, and enough melee to hold. A delegation or "
                               "improved relations can buy turns.",
                why=f"{r.name}'s AI scores declaring war on you at {r.war_score:.0f} "
                    f"(warn threshold {WAR_INTENT_WARN:.0f}), held for {held} "
                    f"turn{'s' if held != 1 else ''} since turn {r.war_score_since}.",
                **common,
            ))

        if r.kills:
            turn, x, y = r.latest_fight
            out.append(Insight(
                id=f"threat.active_front.{r.player}", severity=Severity.WARN, provenance=Provenance.FAIR,
                title=f"Active fighting with {r.name}",
                recommendation="Concentrate force at the front, heal inside friendly territory, and "
                               "stop feeding units in one at a time.",
                why=f"{r.kills} unit kills between you and {r.name} in the last {RECENT_TURNS} turns; "
                    f"you lost {r.losses}. Latest fight: turn {turn} at ({x},{y}).",
                **common,
            ))

        if r.city_tiles_targeted or r.units_targeted:
            parts = []
            if r.city_tiles_targeted:
                parts.append(f"{r.city_tiles_targeted} of your city tiles")
            if r.units_targeted:
                parts.append(f"{r.units_targeted} of your units")
            x0, x1, y0, y1 = r.target_box
            out.append(Insight(
                id=f"threat.targeting.{r.player}",
                severity=Severity.WARN if r.city_tiles_targeted else Severity.ADVISE,
                provenance=Provenance.ORACLE,
                title=f"{r.name}'s AI is targeting your {'cities' if r.city_tiles_targeted else 'units'}",
                recommendation=f"Fortify and garrison around x {x0}-{x1}, y {y0}-{y1}; keep ranged "
                               "units inside the settlement and a melee unit on the approach.",
                why=f"On turn {r.target_turn} {r.name}'s AI listed {' and '.join(parts)} as targets, "
                    f"spanning x {x0}-{x1}, y {y0}-{y1}.",
                **common,
            ))

        if r.military_ratio >= MILITARY_RATIO_ADVISE:
            out.append(Insight(
                id=f"threat.military_gap.{r.player}", severity=Severity.ADVISE, provenance=Provenance.FAIR,
                title=f"{r.name} out-muscles you {r.military_ratio:.1f}x",
                recommendation="Close the gap before it is tested: queue military units in your "
                               "highest-production settlement and keep a commander near the shared border.",
                why=f"Turn {t}: {r.name} has {r.land_units} land units to your {r.human_land_units}.",
                **common,
            ))

        growth = _army_growth(state, r.player)
        if growth is not None:
            rs, hs = growth
            if (rs[-1] - rs[0]) - (hs[-1] - hs[0]) >= ARMY_GROWTH_DELTA:
                out.append(Insight(
                    id=f"threat.army_growth.{r.player}", severity=Severity.INFO, provenance=Provenance.FAIR,
                    title=f"{r.name} is arming faster than you",
                    recommendation="Match the build-up or make sure your defences don't depend on parity.",
                    why=f"Over the last {len(rs)} turns {r.name} went from {rs[0]:.0f} to {rs[-1]:.0f} "
                        f"land units while you went from {hs[0]:.0f} to {hs[-1]:.0f}.",
                    **common,
                ))
    return out
