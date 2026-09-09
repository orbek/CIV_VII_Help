"""Compact, evidence-only turn prompt construction."""
from __future__ import annotations

import json

from civ7_advisor.advisors import Insight, intel, tactical
from civ7_advisor.advisors.base import visible
from civ7_advisor.state.models import GameState

EXPLAIN_TOP_N = 3


def response_schema(top_ids: list[str], valid_ids: set[str]) -> dict:
    """Constrain Ollama's grammar to the exact citation vocabulary for this turn."""
    explanations = {
        "type": "object",
        "properties": {insight_id: {"type": "string", "minLength": 1}
                       for insight_id in top_ids},
        "required": top_ids,
        "additionalProperties": False,
    }
    plan_step = {
        "type": "object",
        "properties": {
            "insight_id": {"type": "string", "enum": sorted(valid_ids)},
            "step": {"type": "string", "minLength": 1},
        },
        "required": ["insight_id", "step"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "second_opinion": {"type": "string", "minLength": 1},
            "explain": explanations,
            "turn_plan": {"type": "array", "items": plan_step, "minItems": 1, "maxItems": 6},
        },
        "required": ["second_opinion", "explain", "turn_plan"],
        "additionalProperties": False,
    }


def turn_payload(state: GameState, insights: list[Insight], oracle: bool = True) -> dict:
    """The evidence the model is allowed to read this turn.

    With `oracle` false this is the fair payload: Oracle insights and Oracle intel events
    are dropped and the tactical block — which reads the AI's own planning logs and is
    Oracle whether or not its lists happen to be empty — is omitted entirely. Filtering
    here rather than after generation is what lets fair mode have commentary at all
    instead of hiding every generation that ever saw an intercept.
    """
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
    insights = visible(insights, oracle)
    insight_rows = [{
        "id": item.id, "severity": item.severity.name, "provenance": item.provenance.value,
        "title": item.title, "recommendation": item.recommendation, "why": item.why,
    } for item in insights]
    events = [{
        "turn": event.turn, "kind": event.kind, "provenance": event.provenance.value,
        "text": event.text,
    } for event in visible(intel.feed(state), oracle)[:80]]
    payload = {"turn": turn, "standings": standings, "insights": insight_rows, "intel": events}
    if oracle:
        tactical_data = tactical.snapshot(state)
        payload["tactical"] = {
            "provenance": "oracle", "enemy_units": len(tactical_data["enemy_units"]),
            "attack_goals": tactical_data["attack_goals"],
            "commander_promotions": tactical_data["commander_promotions"][-20:],
        }
    return payload


def build_prompt(state: GameState, insights: list[Insight],
                 oracle: bool = True) -> tuple[str, bool, list[str]]:
    """The prompt, whether it read any Oracle evidence, and the insight ids it may cite.

    `saw_oracle` is a property of this prompt's contents, not of who asked for it: an
    oracle-mode prompt for a turn with no intercepted evidence at all is fair, and the
    result is safe to show in either mode.
    """
    insights = visible(insights, oracle)
    payload = turn_payload(state, insights, oracle)
    saw_oracle = "tactical" in payload or any(
        row["provenance"] == "oracle" for row in payload["insights"] + payload["intel"]
    )
    top_ids = [i.id for i in insights[:EXPLAIN_TOP_N]]
    evidence = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    prompt = (
        "You are a Civilization VII turn advisor. Use only the supplied deterministic JSON; do not "
        "invent or recompute figures. Every claim and every plan step must cite an exact insight id. "
        "Return JSON only with this shape: {\"second_opinion\":\"text with [insight.id] citations\","
        "\"explain\":{\"insight.id\":\"why it matters, cost of ignoring it, and alternatives\"},"
        "\"turn_plan\":[{\"insight_id\":\"id\",\"step\":\"ordered action\"}]}. "
        f"Explain only these top ids: {json.dumps(top_ids)}. Valid insight ids occur in the JSON below.\n"
        + evidence
    )
    return prompt, saw_oracle, [i.id for i in insights]
