"""JSON shapes for the API. Enums become names/values; dataclasses become dicts.

Every shape here takes its numbers from one `Snapshot`, and every one of them applies the
evidence filter on the server. The browser still drops the Oracle table columns, but that
is now belt-and-braces rather than the only thing standing between fair mode and
AI-internal data: with `oracle=0` the fields are simply not in the response.
"""
from __future__ import annotations

from dataclasses import asdict

from civ_advisor.advisors import Insight, economy, intel, production, threat, victory
from civ_advisor.advisors.base import visible
from civ_advisor.decisions.context import DecisionContext
from civ_advisor.decisions.evidence import EvidenceLedger
from civ_advisor.decisions.models import (
    ActionCandidate, DecisionCard, EvidenceFact, SourceKind,
)
from civ_advisor.games.base import Capability, GameProfile
from civ_advisor.games.selection import Resolution
from civ_advisor.knowledge.catalog import GuideEntry
from civ_advisor.llm.models import Commentary, CommentaryResult
from civ_advisor.state.models import GameState, PlayerKind, PlayerTurn
from civ_advisor.store import Snapshot

RANK_STATS = ["science", "culture", "production", "gold", "military_units"]
INTEL_LIMIT = 300  # newest events returned by /api/intel

# RivalThreat fields read from the AI's own logs (AI_DiplomaticActions, AI_Targets).
# `peace_since` stays fair: a Peace deal is something the player signed and can see.
ORACLE_THREAT_FIELDS = ("war_score", "war_score_since", "at_war_since", "target_turn",
                        "city_tiles_targeted", "units_targeted", "target_box",
                        "combat_desire", "combat_desire_turn", "combat_desire_prior",
                        "combat_desire_prior_turn", "combat_desire_is_highest", "grievances")

SCHEMA_VERSION = 1

_NO_TUNER = (
    "This figure comes from the game's tuner socket, which is not connected."
)


def capability_report(profile: GameProfile, tuner: object | None = None) -> dict[str, dict]:
    """Every capability this build models, whether this game supports it, and why not.

    Exhaustive on purpose, and the reason ships with the answer: the UI must be able to
    say "Civ VI's logs do not record which victory a rival is pursuing" rather than
    quietly rendering one panel fewer, which is indistinguishable from a quiet game.

    A tuner-backed capability is live only for a poll in which the socket
    answered. The three ways it can be absent are told apart, because only one
    of them is something the player can fix.
    """
    live = bool(tuner is not None and getattr(tuner, "available", False))
    tuner_reason = getattr(tuner, "reason", None) if tuner is not None else None
    report: dict[str, dict] = {}
    for c in Capability:
        if c in profile.tuner_backed:
            report[c.value] = {
                "supported": live,
                "reason": None if live else (tuner_reason or _NO_TUNER),
                "source": "tuner",
            }
        else:
            report[c.value] = {
                "supported": profile.supports(c),
                "reason": profile.reason(c),
            }
    return report


def game_to_dict(resolution: Resolution, tuner: object | None = None) -> dict:
    """Which game is being advised on, how that was decided, and what else is on offer.

    `mode` and `disagrees` are not decoration: a pinned choice that detection contradicts
    is the one case where the dashboard's numbers come from a game the player may not be
    looking at, and the header has to say so rather than leave it to be discovered.
    """
    from civ_advisor.games.registry import get_profile, profile_ids

    def described(profile, profile_tuner: object | None = None) -> dict:
        return {"id": profile.id, "display_name": profile.display_name,
                "capabilities": capability_report(profile, tuner=profile_tuner)}

    active = resolution.profile
    return {
        "mode": resolution.mode,
        "pinned": resolution.pinned_id,
        "active": None if active is None else dict(
            described(active, tuner), logs_dir=str(resolution.logs_dir)),
        "disagrees": resolution.disagrees,
        "detection": {
            "game": resolution.detected_id,
            "reason": resolution.detection_reason,
            "candidates": [
                {"id": c.game_id, "logs_dir": str(c.logs_dir), "present": c.present,
                 "age": None if c.age is None else round(c.age, 1)}
                for c in resolution.candidates
            ],
        },
        # Non-active profiles keep the no-tuner call: nothing has been asked of them.
        "games": [described(get_profile(g)) for g in profile_ids()],
    }


def insight_to_dict(i: Insight) -> dict:
    d = asdict(i)
    d["severity"] = i.severity.name
    d["provenance"] = i.provenance.value
    return d


def intel_to_dict(e: intel.IntelEvent) -> dict:
    d = asdict(e)
    d["provenance"] = e.provenance.value
    return d


def _threat_to_dict(t: threat.RivalThreat, oracle: bool) -> dict:
    d = asdict(t)
    if not oracle:
        for field in ORACLE_THREAT_FIELDS:
            d.pop(field, None)
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
            # A rival's victory strategy is read from AI_Victories, which is the AI's own
            # weighting: fair mode gets an empty list, not a blanked table.
            "strategies": [
                asdict(s) | {"following": s.following}
                for s in state.strategies.get(p.id, {}).values()
            ] if oracle else [],
        })
    return {
        "latest_turn": state.latest_turn,
        "complete_through_turn": t,
        "in_progress": state.latest_turn > t,
        "human": state.HUMAN,
        "standings": standings,
        "ranks": _ranks(state),
        "threats": [_threat_to_dict(r, oracle) for r in threat.summarize(state)],
        "leaderboards": {
            path: [{"id": p.id, "name": p.name, "value": v} for p, v in board]
            for path, board in victory.leaderboards(state).items()
        },
        "economy": [asdict(c) for c in economy.comparison(state)],
        "production": _production(state, oracle),
        "files": {name: asdict(fs) for name, fs in state.files.items()},
    }


def status_to_dict(snapshot: Snapshot, oracle: bool, game: dict | None = None) -> dict:
    """Everything the header needs to say how trustworthy the numbers on screen are.

    The turn number alone is not enough: the player has to be able to tell a quiet turn
    from a dropped log file, and a continuing game from a reloaded one.
    """
    return {
        "schema_version": snapshot.schema_version,
        "game_id": snapshot.game_id,
        "game": game,
        "session": snapshot.session,
        "epoch": snapshot.epoch,
        "epoch_reason": snapshot.epoch_reason,
        "game_key": snapshot.game_key,
        "revision": snapshot.revision,
        "captured_at": snapshot.captured_at,
        "latest_turn": snapshot.latest_turn,
        "analysis_turn": snapshot.analysis_turn,
        "in_progress": snapshot.in_progress,
        "evidence_mode": "oracle" if oracle else "fair",
        "coverage": [asdict(c) for c in snapshot.coverage],
    }


def _commentary_to_dict(c: Commentary | None) -> dict | None:
    if c is None:
        return None
    d = asdict(c)
    return d


def commentary_to_dict(result: CommentaryResult) -> dict:
    return {
        "status": result.status,
        "turn": result.turn,
        "message": result.message,
        "commentary": _commentary_to_dict(result.commentary),
        "previous": _commentary_to_dict(result.previous),
    }


# How a live reading's own turn stands against the turn the LOGS are complete through.
# Slugs rather than prose, following store.py's epoch_reason, because this is a fact a
# consumer branches on and not a sentence to match against.
#
# LOGS_BEHIND is the NORMAL case and not an anomaly: the socket reads the running game
# while a log row is only written as a turn finishes, which is exactly why this codebase
# already keeps `latest_turn` and `analysis_turn` apart. It is also the number that
# makes the live_reading/log distinction concrete for a player -- "read live on turn 60;
# logs complete through 59" is the whole difference between the two sources, stated.
#
# READING_BEHIND cannot happen against one continuous match, so it is evidence of
# something real: a reloaded save, a different game answering the socket, or a
# connection held across a session change. Both numbers are reported and neither is
# preferred. Nothing here reconciles them -- quietly picking one would hide the event.
LOGS_BEHIND = "logs_behind"
SAME_TURN = "same_turn"
READING_BEHIND = "reading_behind"


def reading_turn_relation(turn: int, analysis_turn: int | None) -> str | None:
    """Which way a live reading's turn stands against the logs', or None if unknown."""
    if analysis_turn is None:
        return None
    if turn > analysis_turn:
        return LOGS_BEHIND
    return SAME_TURN if turn == analysis_turn else READING_BEHIND


def reading_turn_disagreement(turn: int, analysis_turn: int | None) -> str | None:
    """What to say when a live reading is BEHIND the logs, and nothing otherwise.

    Being ahead of the logs is normal and gets no note -- calling the usual case an
    anomaly would teach a player to ignore the one that is not.
    """
    if reading_turn_relation(turn, analysis_turn) != READING_BEHIND:
        return None
    return (
        f"The running game answered turn {turn}, but the logs are complete through "
        f"turn {analysis_turn}. A live reading is never behind the logs of the same "
        "match, so these two are not describing one continuous game: a save was "
        "reloaded, another match is answering the socket, or this connection outlived "
        "the session it was opened in. Both turns are reported as read; neither has "
        "been corrected to the other.")


def reading_to_dict(reading, analysis_turn: int | None) -> dict:
    """One live reading, beside the turn the logs are complete through.

    Both travel. A figure read live on turn 60 while the logs stop at 59 is not an
    error and not a figure to re-date; it is the reason the two sources are labelled
    differently in the first place.
    """
    return {
        "turn": reading.turn,
        "read_at": reading.read_at,
        "state": reading.state,
        "logs_complete_through": analysis_turn,
        "relation": reading_turn_relation(reading.turn, analysis_turn),
        "disagreement": reading_turn_disagreement(reading.turn, analysis_turn),
    }


def evidence_to_dict(fact: EvidenceFact, analysis_turn: int) -> dict:
    """One observation, readable. `label` leads, not the id: an internal key is a handle
    for the code, not something to put in front of a player as the primary label.

    A live reading also carries the turn the LOGS are complete through, so the drawer
    can state the difference between the two sources rather than leave "read live" as a
    word: "read live on turn 60; logs complete through 59". `age` is clamped at zero and
    cannot express a figure that is AHEAD of the logs, which a live reading normally is.
    """
    live = fact.source_kind is SourceKind.LIVE_READING
    return {
        "id": fact.id, "label": fact.label, "kind": fact.source_kind.value,
        "provenance": fact.provenance.value, "value": fact.value, "unit": fact.unit,
        "observed_turn": fact.observed_turn, "age": fact.age_in(analysis_turn),
        "source_file": fact.source_file, "record_key": list(fact.record_key),
        "subject_id": fact.subject_id, "contributing": list(fact.contributing),
        "note": fact.note, "reported_at": fact.reported_at,
        "logs_complete_through": analysis_turn if live else None,
        "turn_disagreement": (
            reading_turn_disagreement(fact.observed_turn, analysis_turn)
            if live and fact.observed_turn is not None else None),
    }


def guide_to_dict(entry: GuideEntry) -> dict:
    """A guide reference with everything needed to say how far it may be trusted."""
    return {
        "id": entry.id, "title": entry.title, "publisher": entry.publisher,
        "url": entry.url, "reviewed_url": entry.reviewed_url, "section": entry.section,
        "kind": entry.kind, "item_keys": list(entry.item_keys),
        "mechanic_keys": list(entry.mechanic_keys), "yields": list(entry.yields),
        "instructions": list(entry.instructions),
        "prerequisites": list(entry.prerequisites),
        "review_status": entry.review_status, "reviewed_at": entry.reviewed_at,
        "supported_rulesets": list(entry.supported_rulesets),
        "version_known": entry.version_known,
        "notes": entry.notes, "attribution": entry.attribution,
    }


def candidate_to_dict(candidate: ActionCandidate) -> dict:
    return {
        "id": candidate.id, "title": candidate.title, "target": candidate.target,
        "why_now": candidate.why_now, "applicability": candidate.applicability.value,
        "steps": list(candidate.steps), "evidence_ids": list(candidate.evidence_ids),
        "guide_ids": list(candidate.guide_ids),
        "prerequisites": [{"name": name, "state": state.value}
                          for name, state in candidate.prerequisites],
        "trade_offs": list(candidate.trade_offs), "unknowns": list(candidate.unknowns),
        "provenance": candidate.provenance.value,
    }


def decision_to_dict(card: DecisionCard) -> dict:
    return {
        "id": card.id, "subject": card.subject, "severity": card.severity.name,
        "priority_reason": card.priority_reason, "insight_ids": list(card.insight_ids),
        "preferred": candidate_to_dict(card.preferred) if card.preferred else None,
        "alternatives": [candidate_to_dict(c) for c in card.alternatives],
        "evidence_ids": list(card.evidence_ids), "evidence_mode": card.evidence_mode,
        "observed_turns": list(card.observed_turns), "unknowns": list(card.unknowns),
        "family": card.family,
        "also_behind": [{"label": label, "ratio": ratio} for label, ratio in card.also_behind],
    }


def decisions_to_dict(context: DecisionContext, cards: tuple[DecisionCard, ...]) -> dict:
    """The decisions plus every fact and guide they cite, resolved once.

    Citations travel resolved rather than as bare ids so the evidence drawer never has to
    guess what an id meant, and an id nothing can resolve fails here instead of rendering
    as a dead link.
    """
    fact_ids: list[str] = []
    guide_ids: list[str] = []
    for card in cards:
        fact_ids.extend(card.evidence_ids)
        for candidate in card.candidates:
            fact_ids.extend(candidate.evidence_ids)
            guide_ids.extend(candidate.guide_ids)
    unique_facts = tuple(dict.fromkeys(fact_ids))
    unique_guides = tuple(dict.fromkeys(guide_ids))
    return {
        "cards": [decision_to_dict(c) for c in cards],
        "evidence": [evidence_to_dict(f, context.analysis_turn)
                     for f in context.ledger.resolve(unique_facts)],
        "guides": [guide_to_dict(g) for g in context.catalog.resolve(unique_guides)],
        "context": {
            "session": context.session, "epoch": context.epoch,
            "snapshot_revision": context.snapshot_revision,
            "context_revision": context.context_revision,
            "catalog_revision": context.catalog_revision,
            "evidence_mode": context.evidence_mode,
            "analysis_turn": context.analysis_turn,
            "unobserved_settlements": context.unobserved_settlements,
            "settlements": [
                {"city": s.city, "name": s.name, "item": s.item,
                 "turns_to_complete": s.turns_to_complete, "observed_turn": s.observed_turn,
                 "idle": s.idle, "completed_items": list(s.completed_items)}
                for s in context.settlements
            ],
            "reports": [
                {"id": r.id, "subject": r.subject, "label": r.label, "value": r.value,
                 "unit": r.unit, "observed_turn": r.observed_turn,
                 "reported_at": r.reported_at, "base_revision": r.base_revision}
                for r in context.player.reports
            ],
            # Runtime availability, not the game's static declaration: `capability_report`
            # says a game like Civ VI CAN have a ruleset, which stays true even the one
            # turn its database is missing or unreadable. This is whether THIS session's
            # provider is actually usable right now, and why not when it is not -- the
            # explanation `Civ6Ruleset`/`NullRuleset` already compute and, until this
            # field existed, no caller ever read.
            "ruleset": {"available": context.ruleset.available,
                       "reason": context.ruleset.reason},
        },
    }


def tuner_to_dict(tuner: object | None, analysis_turn: int | None = None) -> dict:
    """One tuner rebuild, ready for the page.

    Every reported figure carries the turn and instant it was read, and a figure the
    tuner could not supply says why -- "not enabled", "not answering" and "unreachable"
    are three different statements and only the browser needs to tell them apart, so
    the reason travels rather than a bare `False`, and `unavailable` travels beside it:
    the same distinction as a value a consumer can branch on, rather than one it would
    have to infer by matching on prose. `source` is always the literal
    `"live_reading"`: this is the one channel that carries values the game never wrote
    to a log, and the browser must never mistake one for a player's own report.

    Each figure carries its OWN reading, and there is deliberately no single turn for
    the whole section: every query asks the live game for its own turn, so a capture
    the player presses Enter through leaves amenities on turn 59 and build options on
    60 -- both true, and one of them false the moment they share a stamp.

    Every reading also carries `logs_complete_through`, so the page can say which
    source a number came from in the one way a player can check.
    """
    available = bool(tuner is not None and getattr(tuner, "available", False))
    reason = getattr(tuner, "reason", None) if tuner is not None else None
    unavailable = getattr(tuner, "unavailable", None) if tuner is not None else None
    maintenance = getattr(tuner, "maintenance", None) if available else None

    def absence(query_id: str) -> str | None:
        if tuner is None or not hasattr(tuner, "absence"):
            return None
        return tuner.absence(query_id)

    def read(query_id: str) -> dict | None:
        """The reading that dates this figure, as the page needs to label it."""
        if not available or tuner is None or not hasattr(tuner, "reading_for"):
            return None
        r = tuner.reading_for(query_id)
        return None if r is None else reading_to_dict(r, analysis_turn)

    return {
        "available": available,
        "reason": None if available else reason,
        "unavailable": None if available or unavailable is None else str(unavailable.value),
        "source": "live_reading",
        "amenities": [
            {"city": a.city, "total": a.total, "from_luxuries": a.from_luxuries,
             "from_civics": a.from_civics, "from_entertainment": a.from_entertainment,
             "housing": a.housing, "food_surplus": a.food_surplus,
             "unexplained": a.unexplained}
            for a in (getattr(tuner, "amenities", ()) if available else ())
        ],
        "amenities_reason": absence("amenities"),
        "amenities_read": read("amenities"),
        "maintenance": ({
            "total": maintenance.total, "buildings": maintenance.buildings,
            "districts": maintenance.districts, "units": maintenance.units,
            "gold": maintenance.gold, "gold_yield": maintenance.gold_yield,
            "unattributed": maintenance.unattributed, "net_gold": maintenance.net_gold,
        } if maintenance is not None else None),
        "maintenance_reason": absence("maintenance"),
        "maintenance_read": read("maintenance"),
        "build_options": [
            {"city": so.city,
             "options": [{"item": o.item, "turns": o.turns} for o in so.options]}
            for so in (getattr(tuner, "build_options", ()) if available else ())
        ],
        "build_options_reason": absence("build_options"),
        "build_options_read": read("build_options"),
    }


def briefing_to_dict(snapshot: Snapshot, oracle: bool, commentary: CommentaryResult,
                     changes: dict | None = None, record: dict | None = None,
                     decisions: dict | None = None, game: dict | None = None) -> dict:
    """The whole dashboard from one revision.

    The browser used to assemble five independent responses, which let a late reply from
    a superseded request repaint data the player had just switched off. One response
    carrying one revision removes that class of bug rather than papering over it.
    """
    from civ_advisor.advisors import tactical  # local import: keeps serialize import-light

    state = snapshot.state
    events = visible(intel.feed(state), oracle)[:INTEL_LIMIT]
    return {
        "status": status_to_dict(snapshot, oracle, game=game),
        "state": state_to_dict(state, oracle),
        "insights": [insight_to_dict(i) for i in visible(snapshot.insights, oracle)],
        "hidden_insights": len(snapshot.insights) - len(visible(snapshot.insights, oracle)),
        "intel": [intel_to_dict(e) for e in events],
        "tactical": (tactical.snapshot(state) if oracle
                     else {"available": False, "reason": "oracle_off"}),
        "commentary": commentary_to_dict(commentary),
        "decisions": decisions,
        "changes": changes,
        "record": record,
        "tuner": tuner_to_dict(snapshot.tuner, snapshot.analysis_turn),
    }


def changes_to_dict(entry, previous, history, changes, acknowledged) -> dict:
    """What moved since the previous turn, and what cannot be compared.

    `comparable` is false when there is no earlier turn of this sitting to compare
    against. The UI must say that rather than showing an empty change list, which reads
    as "nothing changed".
    """
    from civ_advisor.decisions import changes as tracking

    return {
        "session": entry.session, "epoch": entry.epoch, "turn": entry.turn,
        "previous_turn": previous.turn if previous is not None else None,
        "comparable": previous is not None,
        "reason": ("" if previous is not None else
                   "This is the first turn recorded for this game, so there is nothing to "
                   "compare it with. A single observation is not a trend."),
        "observed_turns": list(history.turns(entry.session, entry.epoch)),
        "changes": [
            {"signal_id": c.signal_id, "label": c.label, "state": c.state,
             "detail": c.detail, "severity": c.severity,
             "previous_turn": c.previous_turn, "observed_turn": c.observed_turn}
            for c in changes
        ],
        "retrospective": tracking.retrospective(
            changes, tuple(e.subject for e in acknowledged)),
    }


def player_record_to_dict(record) -> dict:
    """The player's own goals, watchlist and acknowledgements — plus what is held back."""
    def entry(e):
        return {"id": e.id, "kind": e.kind, "subject": e.subject, "turn": e.turn,
                "created_at": e.created_at, "text": e.text, "fingerprint": e.fingerprint}

    return {
        "session": record.session, "epoch": record.epoch, "revision": record.revision,
        "game_key": record.game_key,
        "entries": [entry(e) for e in sorted(record.entries.values(), key=lambda e: e.id)],
        # Never applied automatically: the player has to say these belong to this game.
        "pending": [
            {"session": a.session, "epoch": a.epoch, "game_key": a.game_key,
             "count": a.count, "reason": a.reason,
             "entries": [entry(e) for e in a.entries]}
            for a in record.pending
        ],
        "error": record.last_error,
    }
