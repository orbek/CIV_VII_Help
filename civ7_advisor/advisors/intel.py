"""One chronological feed of what happened — gossip, diplomacy, combat, deals — each labelled.

Not an advisor: it emits no Insights. It gives fair mode real substance, because gossip and the
diplomacy the human took part in are things the game itself showed the player.
"""
from __future__ import annotations

from dataclasses import dataclass

from civ7_advisor.state.models import GameState

from .base import Provenance, humanize

# Tie-break within one turn: what was done to you first, what was agreed next, then talk and rumour.
KIND_ORDER = {"combat": 0, "deal": 1, "diplomacy": 2, "gossip": 3}


@dataclass(frozen=True)
class IntelEvent:
    turn: int
    kind: str                 # combat | deal | diplomacy | gossip
    provenance: Provenance
    text: str
    players: tuple[int, ...]  # resolved ids involved; empty when a gossip name could not be resolved
    x: int | None
    y: int | None
    source: str               # the log file the event came from


def _name(state: GameState, pid: int) -> str:
    if pid == state.HUMAN:
        return "You"
    player = state.players.get(pid)
    return player.name if player else f"Player {pid}"


def _poss(state: GameState, pid: int) -> str:
    """Possessive form: 'your' for the human, "<Name>'s" otherwise (capitalised by the caller if first)."""
    return "your" if pid == state.HUMAN else f"{_name(state, pid)}'s"


def _party(state: GameState, *players: int) -> Provenance:
    return Provenance.FAIR if state.HUMAN in players else Provenance.ORACLE


def feed(state: GameState) -> list[IntelEvent]:
    events: list[IntelEvent] = []
    for g in state.gossip:
        pid = state.names.player_for(g.leader, g.civilization) if state.names else None
        who = _name(state, pid) if pid is not None else f"{g.leader} ({g.civilization})"
        text = f"{who}: {humanize(g.type)}" + (f" — {g.detail}" if g.detail else "")
        events.append(IntelEvent(g.turn, "gossip", Provenance.FAIR, text, (pid,) if pid is not None else (),
                                 g.x if g.x >= 0 else None, g.y if g.y >= 0 else None, "Game_Gossip.csv"))
    for d in state.diplomacy_events:
        text = f"{_name(state, d.initiator)} → {_name(state, d.recipient)}: {d.action}"
        if d.details:
            text += f" — {d.details}"
        events.append(IntelEvent(d.turn, "diplomacy", _party(state, d.initiator, d.recipient), text,
                                 (d.initiator, d.recipient), None, None, "DiplomacySummary.csv"))
    for c in state.combats:
        outcome = {"Attacker": f"{humanize(c.attacker.kind)} destroyed",
                   "Defender": f"{humanize(c.defender.kind)} destroyed"}.get(c.destroyed, "no unit destroyed")
        text = (f"{_poss(state, c.att_player)} {humanize(c.attacker.kind)} attacked "
                f"{_poss(state, c.def_player)} {humanize(c.defender.kind)} — {outcome}")
        text = text[0].upper() + text[1:]
        events.append(IntelEvent(c.turn, "combat", _party(state, c.att_player, c.def_player), text,
                                 (c.att_player, c.def_player), c.x, c.y, "CombatLog.csv"))
    for d in state.deals:
        text = f"{_name(state, d.from_player)} → {_name(state, d.to_player)}: {d.kind}"
        events.append(IntelEvent(d.turn, "deal", _party(state, d.from_player, d.to_player), text,
                                 (d.from_player, d.to_player), None, None, "DiplomacyDeals.log"))
    return sorted(events, key=lambda e: (-e.turn, KIND_ORDER[e.kind], e.text))
