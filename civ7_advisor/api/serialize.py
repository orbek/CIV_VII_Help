"""JSON shapes for the API. Enums become names/values; dataclasses become dicts.

Every shape here takes its numbers from one `Snapshot`, and every one of them applies the
evidence filter on the server. The browser still drops the Oracle table columns, but that
is now belt-and-braces rather than the only thing standing between fair mode and
AI-internal data: with `oracle=0` the fields are simply not in the response.
"""
from __future__ import annotations

from dataclasses import asdict

from civ7_advisor.advisors import Insight, economy, intel, production, threat, victory
from civ7_advisor.advisors.base import visible
from civ7_advisor.decisions.context import DecisionContext
from civ7_advisor.decisions.evidence import EvidenceLedger
from civ7_advisor.decisions.models import ActionCandidate, DecisionCard, EvidenceFact
from civ7_advisor.knowledge.catalog import GuideEntry
from civ7_advisor.llm.models import Commentary, CommentaryResult
from civ7_advisor.state.models import GameState, PlayerKind, PlayerTurn
from civ7_advisor.store import Snapshot

RANK_STATS = ["science", "culture", "production", "gold", "military_units"]
INTEL_LIMIT = 300  # newest events returned by /api/intel

# RivalThreat fields read from the AI's own logs (AI_DiplomaticActions, AI_Targets).
# `peace_since` stays fair: a Peace deal is something the player signed and can see.
ORACLE_THREAT_FIELDS = ("war_score", "war_score_since", "at_war_since", "target_turn",
                        "city_tiles_targeted", "units_targeted", "target_box")

SCHEMA_VERSION = 1


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


def status_to_dict(snapshot: Snapshot, oracle: bool) -> dict:
    """Everything the header needs to say how trustworthy the numbers on screen are.

    The turn number alone is not enough: the player has to be able to tell a quiet turn
    from a dropped log file, and a continuing game from a reloaded one.
    """
    return {
        "schema_version": snapshot.schema_version,
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


def evidence_to_dict(fact: EvidenceFact, analysis_turn: int) -> dict:
    """One observation, readable. `label` leads, not the id: an internal key is a handle
    for the code, not something to put in front of a player as the primary label."""
    return {
        "id": fact.id, "label": fact.label, "kind": fact.source_kind.value,
        "provenance": fact.provenance.value, "value": fact.value, "unit": fact.unit,
        "observed_turn": fact.observed_turn, "age": fact.age_in(analysis_turn),
        "source_file": fact.source_file, "record_key": list(fact.record_key),
        "subject_id": fact.subject_id, "contributing": list(fact.contributing),
        "note": fact.note, "reported_at": fact.reported_at,
    }


def guide_to_dict(entry: GuideEntry) -> dict:
    """A guide reference with everything needed to say how far it may be trusted."""
    return {
        "id": entry.id, "title": entry.title, "publisher": entry.publisher,
        "url": entry.url, "reviewed_url": entry.reviewed_url, "section": entry.section,
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
        },
    }


def briefing_to_dict(snapshot: Snapshot, oracle: bool, commentary: CommentaryResult,
                     decisions: dict | None = None) -> dict:
    """The whole dashboard from one revision.

    The browser used to assemble five independent responses, which let a late reply from
    a superseded request repaint data the player had just switched off. One response
    carrying one revision removes that class of bug rather than papering over it.
    """
    from civ7_advisor.advisors import tactical  # local import: keeps serialize import-light

    state = snapshot.state
    events = visible(intel.feed(state), oracle)[:INTEL_LIMIT]
    return {
        "status": status_to_dict(snapshot, oracle),
        "state": state_to_dict(state, oracle),
        "insights": [insight_to_dict(i) for i in visible(snapshot.insights, oracle)],
        "hidden_insights": len(snapshot.insights) - len(visible(snapshot.insights, oracle)),
        "intel": [intel_to_dict(e) for e in events],
        "tactical": (tactical.snapshot(state) if oracle
                     else {"available": False, "reason": "oracle_off"}),
        "commentary": commentary_to_dict(commentary),
        "decisions": decisions,
    }
