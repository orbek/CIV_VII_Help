"""Turn `DiplomacySummary.csv`'s own vocabulary into ordinary language.

The log writes an action's life in stages — `Diplomacy Action Enter Stage`, `Started`,
`Support Changed`, `Ended` — with the action's own name buried in a free-text `Details`
column, sometimes as an unresolved `LOC_*` key. Rendering those rows verbatim gives the
player lines like "Diplomacy Action Ended — Hinder Research result: Success", which is
neither English nor useful.

Two rules run through this module:

  - **Nothing is invented.** A phrase is only produced for a key this file lists. Anything
    else keeps a cautious label that says plainly we do not have words for it, and the
    original text travels alongside so the player can read the log's own wording.
  - **A stage is not an event.** "Entering stage" rows are the engine narrating its own
    state machine. They are marked as progress so the feed can group them under the action
    they belong to instead of presenting each one as something that happened.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Actions we have words for. Anything absent is labelled cautiously rather than guessed.
# `{initiator}` / `{recipient}` take resolved names and `{be}` the verb agreeing with the
# initiator, so the human reads as "You are at war" rather than "You is at war".
ACTION_PHRASES: dict[str, str] = {
    "Met": "{initiator} and {recipient} have met",
    "At War": "{initiator} {be} at war with {recipient}",
    "Peace": "{initiator} made peace with {recipient}",
    "Allied": "{initiator} allied with {recipient}",
    "City Capture": "{initiator} captured a settlement from {recipient}",
}

# The stage rows, and what each one means for grouping.
STAGE_ACTIONS: dict[str, str] = {
    "Diplomacy Action Started": "started",
    "Diplomacy Action Enter Stage": "progress",
    "Diplomacy Action Support Changed": "progress",
    "Diplomacy Action Opposition Changed": "progress",
    "Diplomacy Action Ended": "ended",
}

# How the log qualifies a declaration of war. Kept exactly as three distinct things: a
# surprise war is not a formal one, and a suzerain's war is neither.
WAR_KINDS: dict[str, str] = {
    "Formal": "after a formal declaration",
    "Surprise": "in a surprise attack",
    "Suzerain War": "through a suzerain's war",
}

RESULT_PHRASES: dict[str, str] = {
    "Success": "and it succeeded",
    "Canceled": "and it was cancelled before finishing",
    "Cancelled": "and it was cancelled before finishing",
}

_RESULT = re.compile(r"^(?P<action>.+?) result:\s*(?P<result>\S+)\s*$")
_ENTERING = re.compile(r"^(?P<action>.+?)\s+Entering Stage\s+(?P<stage>\S+)\s*$")
# Support and opposition rows name the action, then a dash, then who moved it and by how
# much: "Hinder Finances - P 1 increased support by 1". Without stripping the tail these
# rows would key a group of their own and the same action would appear twice.
_SUPPORT = re.compile(r"^(?P<action>.+?)\s+-\s+(?P<who>P?\s*\d+)\s+(?P<change>.+?)\s*$")
_CITY_KEY = re.compile(r"^LOC_CITY_NAME_(?P<name>[A-Z0-9_]+)$")


@dataclass(frozen=True)
class Party:
    """One side of a diplomatic row, in the forms a sentence needs.

    The human is second person, so both the verb and the possessive differ; carrying the
    forms rather than deriving them from the name keeps that out of string surgery.
    """

    name: str            # "You" | "Ibn Battuta"
    possessive: str      # "your" | "Ibn Battuta's"
    second_person: bool = False

    @property
    def be(self) -> str:
        return "are" if self.second_person else "is"


@dataclass(frozen=True)
class Reading:
    """One row, read as far as this module can honestly read it.

    `text` is what to show. `raw` is the log's own action and details, always retained so
    the evidence view can show what was actually written. `recognised` says whether the
    words came from the tables above or are a cautious fallback.
    """

    text: str
    raw: str
    stage: str | None       # "started" | "progress" | "ended" | None for a standalone event
    action_name: str | None  # the diplomatic action a staged row belongs to
    event_type: str          # a stable key for filtering
    recognised: bool


def _action_name(details: str) -> tuple[str | None, str | None, str | None]:
    """(action name, stage key, result) pulled out of the details column."""
    match = _RESULT.match(details)
    if match:
        return match.group("action").strip(), None, match.group("result")
    match = _ENTERING.match(details)
    if match:
        return match.group("action").strip(), match.group("stage"), None
    match = _SUPPORT.match(details)
    if match:
        return match.group("action").strip(), match.group("change").strip(), None
    return (details.strip() or None), None, None


def humanize_action_name(name: str | None) -> tuple[str, bool]:
    """A readable name for a diplomatic action, and whether we actually recognised it.

    An unresolved `LOC_DIPLOMACY_ACTION_*_NAME` key is turned into words because its
    shape is documented, but it is still reported as unrecognised: the engine failed to
    localise it, so the words are our reconstruction rather than the game's own label.
    """
    if not name:
        return "an unnamed action", False
    if name.startswith("LOC_"):
        words = (name.removeprefix("LOC_DIPLOMACY_ACTION_").removeprefix("LOC_")
                 .removesuffix("_NAME").replace("_", " ").title())
        return f"{words} (the game did not supply a name for this)", False
    return name, True


def read(action: str, details: str, initiator: Party, recipient: Party) -> Reading:
    """Read one DiplomacySummary row."""
    raw = f"{action}" + (f" — {details}" if details else "")

    phrase = ACTION_PHRASES.get(action)
    if phrase is not None:
        text = phrase.format(initiator=initiator.name, recipient=recipient.name,
                             be=initiator.be)
        recognised = True
        if action == "At War" and details:
            qualifier = WAR_KINDS.get(details.strip())
            if qualifier:
                text += f" {qualifier}"
            else:
                text += f" (the log calls this {details.strip()!r}, which we have no words for)"
                recognised = False
        elif action == "City Capture" and details:
            city = _CITY_KEY.match(details.strip())
            if city:
                # A key-derived name, not the name shown in game. Said plainly.
                readable = city.group("name").replace("_", " ").title()
                text += f" — logged as {readable}"
            else:
                text += f" — {details.strip()}"
        return Reading(text=text, raw=raw, stage=None, action_name=None,
                       event_type=f"diplomacy.{action.lower().replace(' ', '_')}",
                       recognised=recognised)

    stage = STAGE_ACTIONS.get(action)
    if stage is not None:
        name, _stage_key, result = _action_name(details)
        readable, recognised = humanize_action_name(name)
        if stage == "started":
            text = f"{initiator.name} began {readable} against {recipient.name}"
        elif stage == "ended":
            outcome = RESULT_PHRASES.get((result or "").strip())
            if outcome is None and result:
                outcome = f"with a result the log calls {result.strip()!r}"
                recognised = False
            text = f"{initiator.possessive} {readable} against {recipient.name} finished"
            if outcome:
                text += f" {outcome}"
        else:
            # The stage key carries what actually moved, where the log said so.
            moved = _stage_key if action.endswith(("Support Changed", "Opposition Changed")) \
                else None
            text = (f"{initiator.possessive} {readable} against {recipient.name} "
                    + (f"— {moved}" if moved else "moved on a stage"))
        text = text[0].upper() + text[1:]
        return Reading(text=text, raw=raw, stage=stage, action_name=name,
                       event_type="diplomacy.action", recognised=recognised)

    # Something this module has never seen. Say so, and show the log's own words.
    return Reading(
        text=(f"{initiator.name} → {recipient.name}: an action this advisor has no words "
              f"for ({raw})"),
        raw=raw, stage=None, action_name=None, event_type="diplomacy.unknown",
        recognised=False,
    )


__all__ = ["ACTION_PHRASES", "Party", "Reading", "STAGE_ACTIONS", "WAR_KINDS",
           "humanize_action_name", "read"]
