"""One chronological feed of what happened — gossip, diplomacy, combat, deals — each labelled.

Not an advisor: it emits no Insights. It gives fair mode real substance, because gossip and the
diplomacy the human took part in are things the game itself showed the player.
"""
from __future__ import annotations

from dataclasses import dataclass

from civ7_advisor.state.models import GameState, PlayerKind

from . import diplomacy_language
from .base import Provenance, humanize

# Tie-break within one turn: what was done to you first, what was agreed next, then talk and rumour.
KIND_ORDER = {"combat": 0, "deal": 1, "diplomacy": 2, "gossip": 3}
SYMMETRIC_ACTIONS = frozenset({"Met"})  # the log writes these once from each side; show one


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
    # `raw` keeps the log's own wording for every event whose text we rewrote, so the
    # evidence view can show what was actually recorded rather than only our phrasing.
    raw: str | None = None
    event_type: str = ""      # stable key for filtering, e.g. "diplomacy.action"
    recognised: bool = True   # False when we had no words for it and said so
    # A verified multi-stage action collapses into one event. `stages` is how many rows it
    # covers, `first_turn` when it started. Only ever set when every row matched on the
    # same pair and the same action name — otherwise the rows stay separate.
    stages: int = 1
    first_turn: int | None = None


def event_types(events: list[IntelEvent]) -> list[str]:
    """The filterable types present, in a stable order."""
    return sorted({e.event_type for e in events if e.event_type})


def filter_events(events: list[IntelEvent], player: int | None = None,
                  event_type: str | None = None) -> list[IntelEvent]:
    """Narrow the feed by who was involved and what kind of thing it was.

    A player filter keeps events with no resolved party out: an unresolved gossip name is
    not evidence that the player in question was uninvolved, but it is not evidence that
    they were either, so it cannot answer the question being asked.
    """
    out = events
    if player is not None:
        out = [e for e in out if player in e.players]
    if event_type is not None:
        out = [e for e in out if e.event_type == event_type]
    return out


def _name(state: GameState, pid: int) -> str:
    if pid == state.HUMAN:
        return "You"
    player = state.players.get(pid)
    return player.name if player else f"Player {pid}"


def _poss(state: GameState, pid: int) -> str:
    """Possessive form: 'your' for the human, "<Name>'s" otherwise (capitalised by the caller if first)."""
    return "your" if pid == state.HUMAN else f"{_name(state, pid)}'s"


def _occurrences(rows: list) -> list[list]:
    """Split one pair-and-action history into separate runs, one per occurrence.

    The log's own lifecycle is the boundary: an `Ended` row closes an occurrence, so rows
    after it belong to the next time the same pair ran the same action. Merging across
    that boundary would report two Open Markets agreements, seventy turns apart, as one
    event — which is exactly the sort of tidy-looking summary that is simply wrong.
    """
    runs: list[list] = []
    current: list = []
    for pair in rows:
        current.append(pair)
        if pair[1].stage == "ended":
            runs.append(current)
            current = []
    if current:
        runs.append(current)
    return runs


def _party_forms(state: GameState, pid: int) -> diplomacy_language.Party:
    return diplomacy_language.Party(
        name=_name(state, pid), possessive=_poss(state, pid),
        second_person=pid == state.HUMAN,
    )


def _party(state: GameState, *players: int) -> Provenance:
    return Provenance.FAIR if state.HUMAN in players else Provenance.ORACLE


def _relevant(state: GameState, *players: int) -> bool:
    """Every party is a player we know, and at least one of them is a major (the human or a rival)."""
    # Drops what the game never means as an event: a sentinel party (-1 heal ticks, 63 NO_PLAYER) or two independents alone.
    kinds = [state.players[pid].kind for pid in players if pid in state.players]
    return len(kinds) == len(players) and any(k in (PlayerKind.HUMAN, PlayerKind.RIVAL) for k in kinds)


def feed(state: GameState) -> list[IntelEvent]:
    events: list[IntelEvent] = []
    for g in state.gossip:
        pid = state.names.player_for(g.leader, g.civilization) if state.names else None
        who = _name(state, pid) if pid is not None else f"{g.leader} ({g.civilization})"
        text = f"{who}: {humanize(g.type)}" + (f" — {g.detail}" if g.detail else "")
        # A plot is both axes or neither — half a coordinate points nowhere.
        x, y = (g.x, g.y) if g.x >= 0 and g.y >= 0 else (None, None)
        events.append(IntelEvent(
            g.turn, "gossip", Provenance.FAIR, text, (pid,) if pid is not None else (),
            x, y, "Game_Gossip.csv",
            raw=g.type + (f" — {g.detail}" if g.detail else ""),
            event_type=f"gossip.{g.type.removeprefix('GOSSIP_').lower()}"))
    seen_symmetric: set[tuple[int, str, frozenset[int]]] = set()
    staged: dict[tuple[int, int, str], list] = {}
    for d in state.diplomacy_events:
        if not _relevant(state, d.initiator, d.recipient):
            continue
        if d.action in SYMMETRIC_ACTIONS:
            key = (d.turn, d.action, frozenset({d.initiator, d.recipient}))
            if key in seen_symmetric:
                continue
            seen_symmetric.add(key)
        reading = diplomacy_language.read(
            d.action, d.details or "", _party_forms(state, d.initiator),
            _party_forms(state, d.recipient))
        if reading.stage is not None and reading.action_name:
            # Hold every row of one action's life together, keyed on the pair *and* the
            # action's own name. Rows that do not agree on both are never merged.
            staged.setdefault((d.initiator, d.recipient, reading.action_name), []).append(
                (d, reading))
            continue
        events.append(IntelEvent(
            d.turn, "diplomacy", _party(state, d.initiator, d.recipient), reading.text,
            (d.initiator, d.recipient), None, None, "DiplomacySummary.csv",
            raw=reading.raw, event_type=reading.event_type,
            recognised=reading.recognised))
    for (initiator, recipient, _action), rows in staged.items():
        rows.sort(key=lambda pair: pair[0].turn)
        for run in _occurrences(rows):
            row, reading = run[-1]
            text = reading.text
            if len(run) > 1:
                first = run[0][0].turn
                span = "" if first == row.turn else f", followed from turn {first}"
                text += f" (recorded over {len(run)} log rows{span})"
            events.append(IntelEvent(
                row.turn, "diplomacy", _party(state, initiator, recipient), text,
                (initiator, recipient), None, None, "DiplomacySummary.csv",
                raw=" | ".join(pair[1].raw for pair in run), event_type=reading.event_type,
                recognised=reading.recognised, stages=len(run),
                first_turn=run[0][0].turn))
    for c in state.combats:
        if not _relevant(state, c.att_player, c.def_player):
            continue
        outcome = {"Attacker": f"{humanize(c.attacker.kind)} destroyed",
                   "Defender": f"{humanize(c.defender.kind)} destroyed"}.get(c.destroyed, "no unit destroyed")
        text = (f"{_poss(state, c.att_player)} {humanize(c.attacker.kind)} attacked "
                f"{_poss(state, c.def_player)} {humanize(c.defender.kind)} — {outcome}")
        text = text[0].upper() + text[1:]
        events.append(IntelEvent(
            c.turn, "combat", _party(state, c.att_player, c.def_player), text,
            (c.att_player, c.def_player), c.x, c.y, "CombatLog.csv",
            raw=f"{c.attacker.kind} vs {c.defender.kind}, destroyed={c.destroyed or 'none'}",
            event_type="combat"))
    seen_deals: set[tuple[int, int, int, int, str, int, int]] = set()
    for d in state.deals:
        if not _relevant(state, d.from_player, d.to_player):
            continue
        # DiplomacyDeals.log writes every deal in both parties' blocks; identical items are one deal.
        key = (d.turn, d.item_id, d.from_player, d.to_player, d.kind, d.amount, d.duration)
        if key in seen_deals:
            continue
        seen_deals.add(key)
        text = f"{_name(state, d.from_player)} → {_name(state, d.to_player)}: {d.kind}"
        events.append(IntelEvent(
            d.turn, "deal", _party(state, d.from_player, d.to_player), text,
            (d.from_player, d.to_player), None, None, "DiplomacyDeals.log",
            raw=f"item {d.item_id} type {d.kind} amount {d.amount} duration {d.duration}",
            event_type=f"deal.{d.kind.lower().replace(' ', '_')}"))
    return sorted(events, key=lambda e: (-e.turn, KIND_ORDER[e.kind], e.text))
