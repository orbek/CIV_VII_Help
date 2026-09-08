"""JSON shapes for the API. Enums become names/values; dataclasses become dicts."""
from __future__ import annotations

from dataclasses import asdict

from civ7_advisor.advisors import Insight, economy, intel, production, threat, victory
from civ7_advisor.state.models import GameState, PlayerKind, PlayerTurn

RANK_STATS = ["science", "culture", "production", "gold", "military_units"]
INTEL_LIMIT = 300  # newest events returned by /api/intel


def insight_to_dict(i: Insight) -> dict:
    d = asdict(i)
    d["severity"] = i.severity.name
    d["provenance"] = i.provenance.value
    return d


def intel_to_dict(e: intel.IntelEvent) -> dict:
    d = asdict(e)
    d["provenance"] = e.provenance.value
    return d


def _ranks(state: GameState) -> dict[str, list[int]]:
    """Human's rank (1 = best) and field size among alive majors, per stat."""
    t = state.complete_through_turn
    rows = [(p.id, state.at(p.id, t)) for p in state.majors()]
    rows = [(pid, pt) for pid, pt in rows if pt is not None]
    out: dict[str, list[int]] = {}
    for stat in RANK_STATS:
        ordered = sorted(rows, key=lambda r: getattr(r[1], stat), reverse=True)
        position = next((i for i, (pid, _) in enumerate(ordered) if pid == state.HUMAN), None)
        if position is not None:
            out[stat] = [position + 1, len(ordered)]
    return out


def _player_turn_dict(pt: PlayerTurn | None) -> dict | None:
    if pt is None:
        return None
    d = asdict(pt)
    d["settlements"] = pt.settlements
    d["military_units"] = pt.military_units
    d["net_gold"] = pt.net_gold
    d["celebration_progress"] = pt.celebration_progress
    return d


def _production(state: GameState, oracle: bool) -> dict:
    qs = production.queues(state)
    human = [asdict(c) for c in qs.get(state.HUMAN, [])]
    if not oracle:
        return {"human": human, "rivals": None}
    shares = production.rival_military_share(state)
    rivals = [
        {
            "player": r.id,
            "name": r.name,
            "military_share": shares.get(r.id),
            "cities": [asdict(c) for c in qs.get(r.id, [])],
        }
        for r in state.rivals()
        if qs.get(r.id)
    ]
    return {"human": human, "rivals": rivals}


def state_to_dict(state: GameState, oracle: bool = True) -> dict:
    t = state.complete_through_turn
    standings = []
    for p in sorted(state.players.values(), key=lambda p: p.id):
        if p.kind is PlayerKind.INDEPENDENT:
            continue
        standings.append({
            "id": p.id, "name": p.name, "kind": p.kind.value, "alive": p.alive,
            "last_seen_turn": p.last_seen_turn, "stats": _player_turn_dict(state.at(p.id, t)),
            "strategies": [
                asdict(s) | {"following": s.following} for s in state.strategies.get(p.id, {}).values()
            ],
        })
    return {
        "latest_turn": state.latest_turn,
        "complete_through_turn": t,
        "in_progress": state.latest_turn > t,
        "human": state.HUMAN,
        "standings": standings,
        "ranks": _ranks(state),
        "threats": [asdict(r) for r in threat.summarize(state)],
        "leaderboards": {
            path: [{"id": p.id, "name": p.name, "value": v} for p, v in board]
            for path, board in victory.leaderboards(state).items()
        },
        "economy": [asdict(c) for c in economy.comparison(state)],
        "production": _production(state, oracle),
        "files": {name: asdict(fs) for name, fs in state.files.items()},
    }
