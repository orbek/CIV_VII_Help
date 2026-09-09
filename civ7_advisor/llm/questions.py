"""Questions about one decision, answered from that decision's own evidence.

Four questions, three of them fixed and one the player writes:

  why          — why is this the call?
  inspect      — what should I look at in game?
  what_changes — what would change this call?
  challenge    — the player's own short statement of what they intend instead.

Every one is scoped to a single decision and given only that decision's facts, candidates
and guides. Three properties this module exists to guarantee:

  - **Fair mode never sees Oracle evidence.** The evidence is filtered before the prompt
    is built, not after the answer comes back, and the evidence mode is part of the cache
    key — so a fair answer can never be served from an oracle-mode generation.
  - **The model chooses from supplied ids; it cannot invent one.** Answers name evidence,
    action and guide ids from a closed list, enforced by the response grammar and checked
    again on the way out. An answer citing anything else is rejected outright.
  - **A citation is not a warrant.** Including `[some.id]` does not make a sentence
    verified. What is verified is the deterministic data the id resolves to; the prose
    around it stays labelled as interpretation.

The player's own words are treated as intent. "I am going to build a Monument" is a plan,
never an observation that a Monument exists.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

WHY = "why"
INSPECT = "inspect"
WHAT_CHANGES = "what_changes"
CHALLENGE = "challenge"
KINDS = (WHY, INSPECT, WHAT_CHANGES, CHALLENGE)

CHALLENGE_LIMIT = 400  # characters of the player's own text that reach the prompt

# Structural checks on generated prose. These catch output that is visibly broken —
# truncated mid-sentence, wrapped in a code fence, or too short to be an answer. They say
# nothing whatever about whether the answer is *correct*: that is why the panel labels
# generated prose as interpretation and why every number, prerequisite and URL comes from
# the structured data instead. A real local model produced "...in Test```json way=" while
# citing a valid id, which is what these exist to stop reaching the screen.
MIN_ANSWER = 40          # characters; below this it is not an answer
FENCES = ("```", "~~~")
SENTENCE_ENDS = (".", "!", "?", '"', "'", ")")

PROMPTS = {
    WHY: ("Explain why this decision is the one to weigh now, using only the supplied "
          "facts. Do not restate the yield deficit alone: say what makes this the next "
          "thing to act on."),
    INSPECT: ("List what to look at in the game, in order, using only the supplied "
              "candidate steps. Do not name a screen, button or option that is not in "
              "them."),
    WHAT_CHANGES: ("State what would change this call: which unknown, if it turned out "
                   "one way rather than another, would make a different candidate "
                   "preferred, or would make this decision not worth acting on."),
    CHALLENGE: ("The player has said what they intend to do instead. Treat it as their "
                "stated intention, never as something that has happened. Say which "
                "supplied facts support or conflict with it, and which of the "
                "decision-changing unknowns it does not settle. Do not agree that it is "
                "better unless a supplied fact says so."),
}

UNSUPPORTED = ("That question cannot be answered from what this advisor can see. "
               "The missing information is listed below.")


@dataclass(frozen=True)
class QuestionRequest:
    """One question, and the closed world it may be answered from."""

    kind: str
    decision_id: str
    evidence_mode: str          # "oracle" | "fair"
    session: str
    epoch: int
    snapshot_revision: int
    decision_revision: str
    context_revision: int
    catalog_revision: str
    turn: int
    payload: dict               # the facts, candidates, guides and unknowns
    player_text: str = ""       # for CHALLENGE only, already trimmed

    @property
    def evidence_ids(self) -> tuple[str, ...]:
        return tuple(f["id"] for f in self.payload.get("evidence", ()))

    @property
    def action_ids(self) -> tuple[str, ...]:
        return tuple(c["id"] for c in self.payload.get("candidates", ()))

    @property
    def guide_ids(self) -> tuple[str, ...]:
        return tuple(g["id"] for g in self.payload.get("guides", ()))

    @property
    def cache_key(self) -> tuple:
        """Everything that changes what a correct answer would be.

        The evidence mode is in here, so a fair answer is never served from an
        oracle-mode generation; so are the decision, context and catalog revisions, so an
        answer written about a superseded recommendation is never reused.
        """
        return (self.session, self.epoch, self.evidence_mode, self.kind, self.decision_id,
                self.snapshot_revision, self.decision_revision, self.context_revision,
                self.catalog_revision, hashlib.sha256(self.player_text.encode()).hexdigest())


@dataclass(frozen=True)
class Answer:
    text: str
    evidence_ids: tuple[str, ...]
    action_ids: tuple[str, ...]
    guide_ids: tuple[str, ...]
    unknowns: tuple[str, ...]
    generated: bool          # False for the deterministic fallback
    model: str = ""


def build_request(kind: str, decision: dict, evidence: list[dict], guides: list[dict],
                  identity: dict, player_text: str = "") -> QuestionRequest:
    """Assemble the closed world for one question.

    `evidence` and `guides` must already be filtered for the evidence mode: this function
    does not filter, so that a caller cannot accidentally hand it Oracle facts and rely on
    something downstream to strip them.
    """
    if kind not in KINDS:
        raise ValueError(f"{kind!r} is not one of {', '.join(KINDS)}")
    candidates = [decision["preferred"]] if decision.get("preferred") else []
    candidates += list(decision.get("alternatives") or ())
    payload = {
        "decision": {
            "id": decision["id"], "subject": decision["subject"],
            "severity": decision["severity"], "why_first": decision["priority_reason"],
            "observed_turns": decision.get("observed_turns") or [],
        },
        "candidates": [
            {"id": c["id"], "title": c["title"], "target": c["target"],
             "applicability": c["applicability"], "why_now": c["why_now"],
             "steps": c.get("steps") or [], "trade_offs": c.get("trade_offs") or [],
             "prerequisites": c.get("prerequisites") or [],
             "unknowns": c.get("unknowns") or []}
            for c in candidates
        ],
        "evidence": [
            {"id": f["id"], "label": f["label"], "kind": f["kind"], "value": f.get("value"),
             "unit": f.get("unit"), "observed_turn": f.get("observed_turn"),
             "note": f.get("note")}
            for f in evidence
        ],
        "guides": [{"id": g["id"], "title": g["title"], "instructions": g.get("instructions") or []}
                   for g in guides],
        "unknowns": list(decision.get("unknowns") or ()),
    }
    return QuestionRequest(
        kind=kind, decision_id=decision["id"], evidence_mode=identity["evidence_mode"],
        session=identity["session"], epoch=identity["epoch"],
        snapshot_revision=identity["snapshot_revision"],
        decision_revision=identity.get("decision_revision", ""),
        context_revision=identity.get("context_revision", 0),
        catalog_revision=identity.get("catalog_revision", ""),
        turn=identity["turn"], payload=payload,
        player_text=(player_text or "").strip()[:CHALLENGE_LIMIT],
    )


def answerable(request: QuestionRequest) -> tuple[bool, tuple[str, ...]]:
    """Whether this question can be answered at all, and what is missing if not.

    A question about a decision with no candidate and no evidence has nothing to answer
    from. Saying which information is missing is more use than a fluent non-answer.
    """
    missing: list[str] = []
    if not request.evidence_ids:
        missing.append("No observation behind this decision could be resolved.")
    if request.kind in (INSPECT, WHAT_CHANGES) and not request.action_ids:
        missing.append("No reviewed candidate exists for this decision, so there are no "
                       "steps to describe.")
    if request.kind == INSPECT and not request.guide_ids:
        missing.append("No reviewed guide covers this mechanic, so no in-game steps can "
                       "be given.")
    if request.kind == CHALLENGE and not request.player_text:
        missing.append("Nothing was entered to weigh.")
    return (not missing), tuple(missing)


def prompt_for(request: QuestionRequest) -> str:
    evidence = json.dumps(request.payload, ensure_ascii=False,
                          separators=(",", ":"), sort_keys=True)
    instruction = PROMPTS[request.kind]
    said = ""
    if request.kind == CHALLENGE:
        said = ("\nThe player's own words, which are an intention and not an observed "
                f"fact: {json.dumps(request.player_text, ensure_ascii=False)}\n")
    return (
        "You are a Civilization VII turn advisor answering one question about one "
        "decision. Use only the supplied JSON. Do not introduce a number, a prerequisite, "
        "a game screen, an option or a URL that is not in it. Every id you cite must "
        "appear in the supplied lists.\n"
        f"{instruction}\n"
        "Return JSON only, shaped: {\"text\":\"your answer\","
        "\"evidence_ids\":[\"...\"],\"action_ids\":[\"...\"],\"guide_ids\":[\"...\"],"
        "\"unknowns\":[\"what you could not settle\"]}.\n"
        f"{said}"
        + evidence
    )


def response_schema(request: QuestionRequest) -> dict:
    """Constrain the grammar to this decision's own vocabulary.

    An empty list has no `enum`, because a schema with an empty enum matches nothing and
    would fail the whole generation rather than simply allowing no citations.
    """
    def ids(values: tuple[str, ...]) -> dict:
        item = {"type": "string"}
        if values:
            item = {"type": "string", "enum": sorted(values)}
        return {"type": "array", "items": item, "maxItems": 12}

    return {
        "type": "object",
        "properties": {
            "text": {"type": "string", "minLength": 1},
            "evidence_ids": ids(request.evidence_ids),
            "action_ids": ids(request.action_ids),
            "guide_ids": ids(request.guide_ids),
            "unknowns": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
        },
        "required": ["text", "evidence_ids", "action_ids", "guide_ids", "unknowns"],
        "additionalProperties": False,
    }


def validate(request: QuestionRequest, data: dict) -> Answer:
    """Turn a raw generation into an answer, or raise.

    Rejects any id the request did not supply. The grammar should already have prevented
    it, but a fabricated citation reaching the screen would be worse than a failed
    generation, and grammars are not guarantees.
    """
    text = data.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("the answer had no text")
    text = text.strip()
    if any(fence in text for fence in FENCES):
        raise ValueError("the answer contained a code fence, so it is not prose")
    if len(text) < MIN_ANSWER:
        raise ValueError(f"the answer was {len(text)} characters, too short to be one")
    if not text.endswith(SENTENCE_ENDS):
        raise ValueError("the answer stopped mid-sentence")

    def checked(field: str, allowed: tuple[str, ...]) -> tuple[str, ...]:
        values = data.get(field, [])
        if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
            raise ValueError(f"{field} must be a list of ids")
        invented = [v for v in values if v not in allowed]
        if invented:
            raise ValueError(f"{field} cites ids that were not supplied: "
                             + ", ".join(sorted(invented)))
        return tuple(dict.fromkeys(values))

    evidence = checked("evidence_ids", request.evidence_ids)
    actions = checked("action_ids", request.action_ids)
    guides = checked("guide_ids", request.guide_ids)
    unknowns = tuple(u for u in data.get("unknowns", []) if isinstance(u, str) and u.strip())
    if "http://" in text or "https://" in text:
        # URLs come from the catalog, resolved server-side. A model-written one is
        # rejected rather than rendered, however plausible it looks.
        raise ValueError("the answer contained a URL, which only the catalog may supply")
    return Answer(text=text, evidence_ids=evidence, action_ids=actions,
                  guide_ids=guides, unknowns=unknowns, generated=True)


def fallback(request: QuestionRequest, reason: str = "") -> Answer:
    """The deterministic answer, assembled from the structured data alone.

    This is what the panel shows when there is no local model, when a generation fails,
    and when one is rejected. It is not a degraded mode in any way that matters: every
    claim a generated answer is allowed to make already lives in this data.
    """
    decision = request.payload["decision"]
    candidates = request.payload["candidates"]
    unknowns = tuple(request.payload.get("unknowns") or ())
    preferred = candidates[0] if candidates else None

    if request.kind == WHY:
        parts = [decision["why_first"]]
        if preferred:
            parts.append(preferred["why_now"])
    elif request.kind == INSPECT:
        parts = ([f"In {preferred['target']}:"] + list(preferred["steps"])
                 if preferred else ["No reviewed steps are available for this decision."])
    elif request.kind == WHAT_CHANGES:
        parts = ["This call would change if any of the following turned out differently:"]
        parts += list(unknowns)
        if preferred:
            parts += [f"Prerequisite not established: {p['name']}."
                      for p in preferred["prerequisites"] if p["state"] != "met"]
    else:
        parts = [f"You said: {request.player_text}",
                 "That is recorded as your intention, not as something observed.",
                 "It does not settle these, which the recommendation still depends on:"]
        parts += list(unknowns)

    return Answer(
        text=" ".join(p for p in parts if p) + (f" ({reason})" if reason else ""),
        evidence_ids=request.evidence_ids[:6],
        action_ids=(preferred["id"],) if preferred else (),
        guide_ids=request.guide_ids[:3],
        unknowns=unknowns, generated=False,
    )


__all__ = ["Answer", "CHALLENGE", "CHALLENGE_LIMIT", "INSPECT", "KINDS", "PROMPTS",
           "QuestionRequest", "UNSUPPORTED", "WHAT_CHANGES", "WHY", "answerable",
           "build_request", "fallback", "prompt_for", "response_schema", "validate"]
