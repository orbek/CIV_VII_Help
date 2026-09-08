"""Compact, evidence-only turn prompt construction."""
from __future__ import annotations

import json

from civ7_advisor.advisors import Insight, intel, tactical
from civ7_advisor.state.models import GameState

EXPLAIN_TOP_N = 3


def turn_payload(state: GameState, insights: list[Insight]) -> dict:
    turn = state.complete_through_turn
    standings = []
    for player in state.majors():
        row = state.at(player.id, turn)
        if row is not None:
            standings.append({
                "provenance": "fair", "player": player.name, "science": row.science,
                "culture": row.culture, "gold": row.gold, "production": row.production,
                "military_units": row.military_units, "settlements": row.settlements,
            })
    insight_rows = [{
        "id": item.id, "severity": item.severity.name, "provenance": item.provenance.value,
        "title": item.title, "recommendation": item.recommendation, "why": item.why,
    } for item in insights]
    events = [{
        "turn": event.turn, "kind": event.kind, "provenance": event.provenance.value,
        "text": event.text,
    } for event in intel.feed(state)[:80]]
    tactical_data = tactical.snapshot(state)
    tactical_summary = {
        "provenance": "oracle", "enemy_units": len(tactical_data["enemy_units"]),
        "attack_goals": tactical_data["attack_goals"],
        "commander_promotions": tactical_data["commander_promotions"][-20:],
    }
    return {"turn": turn, "standings": standings, "insights": insight_rows,
            "intel": events, "tactical": tactical_summary}


def build_prompt(state: GameState, insights: list[Insight]) -> tuple[str, bool]:
    payload = turn_payload(state, insights)
    # v2 always sends the full tactical block, which is explicitly Oracle even
    # when its current lists happen to be empty. Fair mode must therefore never
    # reveal this generation.
    saw_oracle = True
    top_ids = [i.id for i in insights[:EXPLAIN_TOP_N]]
    evidence = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    prompt = (
        "You are a Civilization VII turn advisor. Use only the supplied deterministic JSON; do not "
        "invent or recompute figures. Every claim and every plan step must cite an exact insight id. "
        "Return JSON only with this shape: {\"second_opinion\":\"text with [insight.id] citations\","
        "\"explain\":[{\"insight_id\":\"id\",\"text\":\"why it matters, cost of ignoring it, and alternatives\"}],"
        "\"turn_plan\":[{\"insight_id\":\"id\",\"step\":\"ordered action\"}]}. "
        f"Explain only these top ids: {json.dumps(top_ids)}. Valid insight ids occur in the JSON below.\n"
        + evidence
    )
    return prompt, saw_oracle
