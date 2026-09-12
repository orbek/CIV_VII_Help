"""Compact, evidence-only turn prompt construction."""
from __future__ import annotations

import json

from civ_advisor.advisors import Insight, intel, tactical
from civ_advisor.advisors.base import visible
from civ_advisor.state.models import GameState

EXPLAIN_TOP_N = 3
INTEL_WINDOW = 80        # newest events (of any kind) offered to the model
# ai_score events can number in the dozens per turn (Civ VI: up to three per rival), and
# the feed sorts newest-turn-first -- left uncapped they alone can fill INTEL_WINDOW and
# push out gossip, diplomacy and combat from every earlier turn. Capped independently so
# the window still covers several turns of the events the player could see in-game
# rather than becoming mostly AI score lists.
AI_SCORE_WINDOW = 24


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
    fed = visible(intel.feed(state), oracle)
    capped: list = []
    ai_score_seen = 0
    for event in fed:
        if event.kind == "ai_score":
            ai_score_seen += 1
            if ai_score_seen > AI_SCORE_WINDOW:
                continue
        capped.append(event)
    events = [{
        "turn": event.turn, "kind": event.kind, "provenance": event.provenance.value,
        "text": event.text,
    } for event in capped[:INTEL_WINDOW]]
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
                 oracle: bool = True,
                 display_name: str = "Civilization VII") -> tuple[str, bool, list[str]]:
    """The prompt, whether it read any Oracle evidence, and the insight ids it may cite.

    `saw_oracle` is a property of this prompt's contents, not of who asked for it: an
    oracle-mode prompt for a turn with no intercepted evidence at all is fair, and the
    result is safe to show in either mode.

    `display_name` names the game this data actually came from -- the caller's job, since
    only it knows which profile produced this state. Defaulting to Civilization VII keeps
    every existing Civ VII call site correct without a change; a Civ VI caller must pass
    its own profile's display name so the model is not told it is advising a different
    game than the one whose logs it just read.
    """
    insights = visible(insights, oracle)
    payload = turn_payload(state, insights, oracle)
    saw_oracle = "tactical" in payload or any(
        row["provenance"] == "oracle" for row in payload["insights"] + payload["intel"]
    )
    top_ids = [i.id for i in insights[:EXPLAIN_TOP_N]]
    evidence = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    prompt = (
        f"You are a {display_name} turn advisor. Use only the supplied deterministic JSON; do not "
        "invent or recompute figures. Do not attribute a victory path, win condition or overall "
        "strategy to any rival, including from a scored preference list -- a score ranks options, "
        "it is not a stated goal. Every claim and every plan step must cite an exact insight id. "
        "Return JSON only with this shape: {\"second_opinion\":\"text with [insight.id] citations\","
        "\"explain\":{\"insight.id\":\"why it matters, cost of ignoring it, and alternatives\"},"
        "\"turn_plan\":[{\"insight_id\":\"id\",\"step\":\"ordered action\"}]}. "
        f"Explain only these top ids: {json.dumps(top_ids)}. Valid insight ids occur in the JSON below.\n"
        + evidence
    )
    return prompt, saw_oracle, [i.id for i in insights]
