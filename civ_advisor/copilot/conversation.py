"""One exchange with the copilot, in two model calls with a deterministic step between.

  select   -- the model reads the player's words and names catalog questions;
  resolve  -- the advisor answers those questions from the snapshot, ruleset and reading;
  compose  -- the model writes prose around the facts, citing ids from a closed list;
  validate -- structure, citations, and the number rule (grounding.py); or
  fallback -- the resolved facts in words, each with its source, plus every absence.

The player's text reaches two prompts and nothing else. Earlier exchanges are offered as
context, dated by game turn, and the current answer must cite facts resolved NOW: a number
from an earlier exchange is not admitted, because it came from an earlier turn.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from civ_advisor.decisions.context import DecisionContext
from civ_advisor.decisions.models import EvidenceFact, SourceKind
from civ_advisor.llm.questions import FENCES, MIN_ANSWER, SENTENCE_ENDS

from . import catalog, grounding
from .catalog import Absence, ParamKind

ASK_LIMIT = 600        # characters of the player's words that reach a prompt
HISTORY_LIMIT = 6      # earlier exchanges offered as context
MAX_QUESTIONS = 8      # catalog questions one exchange may resolve

CANNOT = ("The advisor cannot see that. It answers only from the game's logs, your "
          "installed ruleset and, when it is on, the tuner's live reading.")


@dataclass(frozen=True)
class Exchange:
    id: str
    asked_at: str
    turn: int
    text: str
    answer_text: str
    status: str
    question_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class ChatRequest:
    text: str
    session: str
    epoch: int
    snapshot_revision: int
    context_revision: int
    evidence_mode: str
    turn: int
    display_name: str
    context: DecisionContext = field(compare=False, repr=False)
    history: tuple[Exchange, ...] = ()
    acting: object | None = None     # an ActingOffer (Task 11) or None: no proposals

    def __post_init__(self) -> None:
        object.__setattr__(self, "text", (self.text or "").strip()[:ASK_LIMIT])

    @property
    def cache_key(self) -> tuple:
        return (self.session, self.epoch, self.evidence_mode, self.snapshot_revision,
                self.context_revision, hashlib.sha256(self.text.encode()).hexdigest(),
                len(self.history))


@dataclass(frozen=True)
class Selected:
    question_id: str
    params: dict[str, str]


@dataclass(frozen=True)
class Resolved:
    facts: tuple[EvidenceFact, ...] = ()
    absences: tuple[Absence, ...] = ()
    notes: tuple[str, ...] = ()
    asked: tuple[Selected, ...] = ()

    @property
    def fact_ids(self) -> tuple[str, ...]:
        return tuple(f.id for f in self.facts)


@dataclass(frozen=True)
class ChatAnswer:
    text: str
    evidence_ids: tuple[str, ...]
    unknowns: tuple[str, ...]
    generated: bool
    model: str = ""
    proposal: dict | None = None     # Task 11


# ---- select ---------------------------------------------------------------------------

def _catalog_listing() -> list[dict]:
    return [{"id": q.id, "description": q.description,
             "params": [{"name": p.name, "kind": p.kind.value, "description": p.description}
                        for p in q.params]}
            for q in catalog.CATALOG.values()]


def select_prompt(request: ChatRequest) -> str:
    return (
        f"You are a {request.display_name} advisor deciding which of a FIXED list of questions "
        "to look up in order to answer the player. You do not answer yet. Choose only questions "
        "from the list, with parameters from the allowed values; if nothing in the list can "
        "answer, choose none and say so in `cannot`. The player's words are a question or an "
        "intention, not an observation about the game.\n"
        "Return JSON only, shaped: {\"questions\":[{\"id\":\"...\",\"params\":{...}}],"
        "\"cannot\":\"\"}.\n"
        f"The player wrote: {json.dumps(request.text, ensure_ascii=False)}\n"
        "Questions available this turn:\n"
        + json.dumps(_catalog_listing(), ensure_ascii=False, separators=(",", ":"))
    )


def select_schema(request: ChatRequest) -> dict:
    valid = catalog.choices(request.context)

    def enum(kind: ParamKind) -> dict:
        values = list(valid.get(kind, ()))
        return {"type": "string", "enum": values} if values else {"type": "string", "maxLength": 0}

    return {
        "type": "object",
        "properties": {
            "questions": {
                "type": "array", "maxItems": MAX_QUESTIONS,
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "enum": sorted(catalog.CATALOG)},
                        "params": {
                            "type": "object",
                            "properties": {
                                "stat": enum(ParamKind.STAT),
                                "city": enum(ParamKind.CITY),
                                "item": {"type": "string", "pattern": catalog.TYPE_KEY.pattern},
                                "name": enum(ParamKind.PARAMETER_NAME),
                            },
                            "additionalProperties": False,
                        },
                    },
                    "required": ["id", "params"], "additionalProperties": False,
                },
            },
            "cannot": {"type": "string"},
        },
        "required": ["questions", "cannot"], "additionalProperties": False,
    }


def parse_selection(request: ChatRequest, data: dict) -> tuple[Selected, ...]:
    """Every selection the model made, capped. Unknown ids and bad values are kept: `ask`
    turns each into an Absence that names the mistake, which is more use than dropping it."""
    out: list[Selected] = []
    for row in (data.get("questions") or [])[:MAX_QUESTIONS]:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            continue
        params = {k: v for k, v in (row.get("params") or {}).items()
                  if isinstance(k, str) and isinstance(v, str)}
        out.append(Selected(row["id"], params))
    return tuple(out)


# ---- resolve --------------------------------------------------------------------------

def resolve(request: ChatRequest, selected: tuple[Selected, ...]) -> Resolved:
    facts: dict[str, EvidenceFact] = {}
    absences: list[Absence] = []
    notes: list[str] = []
    for s in selected:
        got = catalog.ask(request.context, s.question_id, s.params)
        for f in got.facts:
            facts.setdefault(f.id, f)
        if got.absence is not None:
            absences.append(got.absence)
        notes.extend(n for n in got.notes if n not in notes)
    return Resolved(facts=tuple(facts.values()), absences=tuple(absences),
                    notes=tuple(notes), asked=selected)


# ---- compose --------------------------------------------------------------------------

def source_phrase(fact: EvidenceFact) -> str:
    """Where a fact came from, in words a player can check. Six kinds, never blended."""
    turn = "" if fact.observed_turn is None else f", turn {fact.observed_turn}"
    if fact.source_kind is SourceKind.LOG:
        return f"from {fact.source_file}{turn}"
    if fact.source_kind is SourceKind.LIVE_READING:
        return f"read live from the game{turn}, at {fact.reported_at}"
    if fact.source_kind is SourceKind.INSTALLED_RULESET:
        return f"from your installed ruleset ({fact.source_file})"
    if fact.source_kind is SourceKind.PLAYER_REPORT:
        return f"your own report{turn}"
    if fact.source_kind is SourceKind.RULE:
        return "an advisor rule, not an observation"
    return f"computed from {', '.join(fact.contributing)}{turn}"


# What the page is shown and the model is not. `source_detail` is provenance -- a file's
# modification time and digest -- whose digits are arbitrary: the number rule refuses
# them, so putting them in front of the model can only tempt a rejection. The player,
# who is checking the claim rather than writing it, gets them.
MODEL_HIDDEN = ("source_detail",)


def fact_payload(fact: EvidenceFact) -> dict:
    return {"id": fact.id, "label": fact.label, "kind": fact.source_kind.value,
            "provenance": fact.provenance.value, "value": fact.value, "unit": fact.unit,
            "observed_turn": fact.observed_turn, "subject": fact.subject_id,
            "note": fact.note, "source": source_phrase(fact),
            "source_detail": fact.source_detail}


def model_fact_payload(fact: EvidenceFact) -> dict:
    return {k: v for k, v in fact_payload(fact).items() if k not in MODEL_HIDDEN}


def absence_payload(absence: Absence) -> dict:
    """One declared absence with its OWN cause. `kind` is the branch the page takes;
    `cause` is the tuner's own enum value where there is one, so the six tuner causes
    stay six -- collapsing them is what told a player to set a flag they had already set.
    """
    return {"question": absence.question, "why": absence.detail,
            "kind": absence.kind.value, "cause": absence.cause}


def _history_payload(request: ChatRequest) -> list[dict]:
    # `when` is written out as words rather than a bare integer: it is the turn an
    # earlier exchange was about, never a figure this answer may quote.
    return [{"when": f"turn {e.turn}", "player": e.text, "advisor": e.answer_text}
            for e in request.history[-HISTORY_LIMIT:]]


def compose_prompt(request: ChatRequest, resolved: Resolved) -> str:
    payload = {
        "player": request.text,
        "turn": request.turn,
        "facts": [model_fact_payload(f) for f in resolved.facts],
        "cannot_answer": [absence_payload(a) for a in resolved.absences],
        "notes": list(resolved.notes),
        "earlier": _history_payload(request),
    }
    return (
        f"You are a {request.display_name} advisor answering the player from the supplied "
        "facts and nothing else. Write quantities as digits. Every number you write must "
        "appear in a fact you cite -- its value, its turn, or its note. Do not compute, "
        "estimate or recall a figure; if a figure is not in the facts, say the advisor "
        "cannot see it. A fact whose kind is player_report is the player's own figure: when "
        "you use it, say so -- 'the 8 turns you reported on turn 59' -- never as though the "
        "game said it. A number in the player's own message is their claim, not a fact: you "
        "may repeat it only as 'you mention ...', and if a fact gives a different figure for "
        "the same thing you must state both and say they disagree, never adopt either. Where "
        "`cannot_answer` lists something, say so plainly rather than filling it, and give its "
        "own `why` and `cause` rather than a general one. The `earlier` exchanges are context "
        "only, from earlier turns: do not repeat a number from them. Do not write a URL.\n"
        "Return JSON only, shaped: {\"text\":\"...\",\"evidence_ids\":[\"...\"],"
        "\"unknowns\":[\"...\"]}.\n"
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    )


def compose_schema(request: ChatRequest, resolved: Resolved) -> dict:
    ids = sorted(resolved.fact_ids)
    item = {"type": "string", "enum": ids} if ids else {"type": "string", "maxLength": 0}
    schema = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "minLength": 1},
            "evidence_ids": {"type": "array", "items": item, "maxItems": 16},
            "unknowns": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
        },
        "required": ["text", "evidence_ids", "unknowns"], "additionalProperties": False,
    }
    if request.acting is not None:
        # Task 11 adds the `proposal` property here; without an acting offer the grammar
        # has no such field, so a normal run's model cannot propose anything.
        schema["properties"]["proposal"] = request.acting.schema()
    return schema


def validate_answer(request: ChatRequest, resolved: Resolved, data: dict) -> ChatAnswer:
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
    if "http://" in text or "https://" in text:
        raise ValueError("the answer contained a URL, which only the catalog may supply")
    ids = data.get("evidence_ids", [])
    if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
        raise ValueError("evidence_ids must be a list of ids")
    invented = sorted(set(ids) - set(resolved.fact_ids))
    if invented:
        raise ValueError("evidence_ids cites ids that were not supplied: " + ", ".join(invented))
    cited = tuple(dict.fromkeys(ids))
    grounded = grounding.check(text, cited, [fact_payload(f) for f in resolved.facts],
                               player_text=request.text)
    if not grounded.ok:
        raise ValueError(grounded.describe())
    unknowns = tuple(u for u in data.get("unknowns", []) if isinstance(u, str) and u.strip())
    proposal = None
    if request.acting is not None and isinstance(data.get("proposal"), dict):
        proposal = request.acting.validate(data["proposal"], cited)     # Task 11
    return ChatAnswer(text=text, evidence_ids=cited, unknowns=unknowns, generated=True,
                      proposal=proposal)


# ---- the deterministic answer -----------------------------------------------------------

def _value(fact: EvidenceFact) -> str:
    """One fact's value in words -- the DETERMINISTIC prose, shown first and shown
    whenever a generation fails or is rejected, so this is the sentence a player
    reads far more often than any model's.

    Rounded to one decimal place when the value is a float: a real live probe of
    the running game asked `empire.upkeep` and got "12.8984375 per turn" here,
    because `fact.value` carries the tuner's full float precision (by design --
    see queries.py's `_parse_number`) and nothing downstream of it rounded before
    this f-string. One decimal is chosen deliberately, not four: gold per turn to
    the nearest tenth is a figure a player can act on, and four decimals of a Lua
    float is noise pretending to be precision. The stored `fact.value` is
    untouched; `grounding.check`'s `_matches` already tolerates a numeral written
    with fewer decimal places than the fact it cites (spec 4.3 rule 3), so
    rounding here cannot make this sentence fail its own validator.
    """
    if fact.value is None:
        return "no value"
    unit = f" {fact.unit}" if fact.unit else ""
    value = fact.value
    if isinstance(value, float) and not isinstance(value, bool):
        value = round(value, 1)
    return f"{value}{unit}"


def _absence_sentence(absence: Absence) -> str:
    """One absence, with the cause it was established from -- never a general one."""
    cause = f" ({absence.cause})" if absence.cause else ""
    # An absence's detail may already end in a stop -- the ones that name another
    # question do, because they end in a sentence. Do not add a second one.
    body = f"{absence.describe()}{cause}".rstrip()
    end = "" if body.endswith((".", "!", "?")) else "."
    return f"Not available — {body}{end}"


def fallback(request: ChatRequest, resolved: Resolved, reason: str = "") -> ChatAnswer:
    """The deterministic answer: every resolved fact in words with its source, every
    absence with its reason. Shown first, and kept when a generation fails or is rejected."""
    parts: list[str] = []
    for fact in resolved.facts:
        parts.append(f"{fact.label}: {_value(fact)} ({source_phrase(fact)}).")
    parts.extend(resolved.notes)
    typed = [n.text for n in grounding.numerals_in(request.text)]
    if typed:
        # Spec 4.3 rule 7: the player's own figure is on screen as THEIR statement, beside
        # every grounded figure above, so a disagreement is visible whether or not a model
        # writes it. It is never a fact and never quietly adopted.
        parts.append(f"You mention {', '.join(typed)}: that is your statement, not a figure "
                     "the advisor holds; the figures above are what it can establish.")
    for absence in resolved.absences:
        parts.append(_absence_sentence(absence))
    if not parts:
        parts.append(CANNOT)
    if reason:
        parts.append(f"(The generated answer was not shown: {reason}.)")
    return ChatAnswer(text=" ".join(parts), evidence_ids=resolved.fact_ids,
                      unknowns=tuple(a.detail for a in resolved.absences), generated=False)


# ---- the transcript ---------------------------------------------------------------------

class Transcript:
    """Exchanges per (session, epoch). In memory; a reload starts a new sitting."""

    def __init__(self) -> None:
        self._by_sitting: dict[tuple[str, int], list[Exchange]] = {}

    def record(self, session: str, epoch: int, exchange: Exchange) -> None:
        self._by_sitting.setdefault((session, epoch), []).append(exchange)

    def history(self, session: str, epoch: int) -> tuple[Exchange, ...]:
        return tuple(self._by_sitting.get((session, epoch), ()))


__all__ = ["ASK_LIMIT", "CANNOT", "ChatAnswer", "ChatRequest", "Exchange", "HISTORY_LIMIT",
           "MAX_QUESTIONS", "Resolved", "Selected", "Transcript", "absence_payload",
           "compose_prompt", "compose_schema", "fact_payload", "fallback",
           "model_fact_payload", "parse_selection",
           "resolve", "select_prompt", "select_schema", "source_phrase", "validate_answer"]
