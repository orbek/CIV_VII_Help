"""The number rule, spec section 4.3, as one pure function.

Every number in generated prose must be a number that appears in a fact the answer
cited: the fact's value, its observed turn, or a numeral in its note that is a figure
rather than part of a token (notes are written by the deterministic layer from the data;
`figures_in_note` says which of their numbers count and why). Nothing else is admitted -- not the player's
message, not an earlier exchange, not arithmetic the model did itself. A figure a
player might want derived is a resolver's job, as a DERIVED fact citing its inputs.

Deliberately NOT here: any check that a number is attached to the right noun. "Rome has
3 amenities" passes if a cited fact has value 3 even when that fact is Puteoli's, and
nothing here can tell whether a player's figure and a grounded one describe the same
thing. The evidence drawer under the answer shows each cited fact with its subject; that
is where a player catches it, and why generated prose stays labelled interpretation.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Iterable, Mapping

# `one` is absent on purpose: it is a pronoun in most English sentences ("one of",
# "one settlement"), and treating it as a numeral rejects grammar rather than claims.
NUMBER_WORDS: dict[str, int] = {
    "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
    "eighty": 80, "ninety": 90, "hundred": 100, "thousand": 1000,
}

# A comma is a thousands separator only between digits: `[\d,]*` would swallow the
# comma in "First 9, then 11" and report the numeral as "9,".
_DIGITS = re.compile(r"-?\d+(?:,\d{3})*(?:\.\d+)?%?")
_WORDS = re.compile(r"\b(" + "|".join(sorted(NUMBER_WORDS, key=len, reverse=True)) + r")\b",
                    re.IGNORECASE)


@dataclass(frozen=True)
class Numeral:
    """One number as written, with what it would have to match."""

    text: str
    value: Decimal
    places: int          # decimal places written; a number word has none
    percent: bool
    start: int = 0       # offset into the text it was read from, for sentence scoping


# How prose must own up to a figure the PLAYER supplied. A player report is citable --
# it is dated, labelled and stored -- but the game did not say it, and the sentence
# must not read as though it did. Lower-cased comparison; the phrases are fixed. Each
# phrase licenses only the numerals in its OWN sentence: one phrase covering an answer
# that names several figures is proximity, not attribution.
ATTRIBUTION = ("you reported", "your report", "you told the advisor", "you entered", "you recorded")

# How prose may repeat a number the player JUST TYPED. Kept apart from ATTRIBUTION on
# purpose: a report is a dated observation the advisor holds; this is an unverified
# assertion made a moment ago in conversation, and the words must say which it is.
CLAIM = ("you mention", "you mentioned", "you say", "you wrote", "your message")


# A numeral is quoted back to the player in the rejection reason, and prose can carry one
# thousands of characters long. Abbreviated there so the reason stays a sentence a person
# reads; the numeral itself is kept whole in the tuple for anything that checks it.
_READABLE_NUMERAL = 24


def _readable(numerals: tuple[str, ...]) -> str:
    return ", ".join(n if len(n) <= _READABLE_NUMERAL else f"{n[:_READABLE_NUMERAL]}..."
                     for n in numerals)


@dataclass(frozen=True)
class Grounding:
    ok: bool
    ungrounded: tuple[str, ...] = ()     # numerals no cited fact carries, once, in order
    unattributed: tuple[str, ...] = ()   # numerals grounded ONLY by a player report, unattributed
    # The player's typed numerals when the prose used one side alone: repeated them while
    # every cited figure went unstated, OR stated a cited figure while never acknowledging
    # them. Spec 4.3 rule 7: both numbers, the disagreement named, neither preferred.
    unreconciled: tuple[str, ...] = ()

    def describe(self) -> str:
        if self.ok:
            return ""
        parts = []
        if self.ungrounded:
            parts.append(f"the answer contains {_readable(self.ungrounded)}, which no cited "
                         "fact carries")
        if self.unattributed:
            parts.append(f"the answer states {_readable(self.unattributed)} as though the game "
                         "said it, when only your own report does; it must say you reported it")
        if self.unreconciled:
            parts.append(f"you mentioned {_readable(self.unreconciled)} and the evidence holds "
                         "a figure of its own; the answer used one side alone, and a "
                         "disagreement is named, never resolved by dropping either")
        return "; ".join(parts) + " -- a number the evidence does not state is not shown"


# A sentence ends at one of these followed by whitespace. Crude on purpose, and stated
# so nobody relies on more: "Fig. 3" and "e.g. two" split early, and a terminator at the
# very end of a clause without whitespace does not split at all. Splitting early can only
# move a phrase out of a numeral's sentence, which rejects an answer; it never licenses
# one. Decimals ("0.44") and dotted ids ("gold.net.59") are unaffected: no whitespace
# follows the dot.
_SENTENCE_END = re.compile(r"[.!?]\s+")


def _mask_citations(text: str, strip_ids: Iterable[str]) -> str:
    """Blank out the bracketed citations the answer is allowed to make.

    ONLY the bracketed form `[gold.net.59]` is removed. A bare `gold.net.59` written into
    the prose is left to be scanned like any other text: stripping it would make the
    digits inside it vanish from the check with nothing on screen to show for it. The
    blanks are the same length as what they replace, so every offset still indexes the
    original text.
    """
    for fact_id in strip_ids:
        marker = f"[{fact_id}]"
        text = text.replace(marker, " " * len(marker))
    return text


def _sentences(text: str) -> tuple[tuple[int, int, str], ...]:
    """`text` split into (start, end, lower-cased) spans covering it exactly."""
    spans: list[tuple[int, int, str]] = []
    start = 0
    for m in _SENTENCE_END.finditer(text):
        spans.append((start, m.end(), text[start:m.end()].lower()))
        start = m.end()
    spans.append((start, len(text), text[start:].lower()))
    return tuple(spans)


def _phrase_by(numeral: Numeral, spans: tuple[tuple[int, int, str], ...],
               phrases: tuple[str, ...]) -> bool:
    """Whether one of `phrases` appears in the sentence this numeral sits in.

    Scoped to the sentence rather than the whole answer: one "you mention" must not
    license every typed numeral on the page, or the rule is satisfied by proximity
    instead of by attribution.
    """
    for start, end, lowered in spans:
        if start <= numeral.start < end:
            return any(phrase in lowered for phrase in phrases)
    return False


# A numeral the player typed straight after "turn"/"turns" names a point on the game's
# clock -- the same form the advisor writes itself ("on turn 59") -- not a quantity.
_TURN_REFERENCE = re.compile(r"\bturns?\s*#?\s*$", re.IGNORECASE)


def quantity_claims(player_text: str) -> tuple[Numeral, ...]:
    """The numerals in the player's message that are CLAIMS ABOUT A QUANTITY, which is
    what rule 7 is about: their figure against the advisor's, neither quietly dropped.

    What this tells apart, and only this: a numeral that FOLLOWS the word "turn" or
    "turns" is a reference to a turn of the game ("what should I do on turn 130?"), and a
    reference is not a rival figure for anything the advisor holds. A numeral that
    precedes it ("the 8-turn Granary", "8 turns for the Granary") is a duration the
    player is asserting, and stays a claim. Firing on every digit instead rejected
    correct, fully grounded answers to any question that mentioned a turn, and the player
    then read the deterministic fallback and never the prose -- silently, and for every
    such question.

    What it CANNOT tell apart, stated so nobody relies on more: whether a quantity the
    player typed is about the same subject as any cited figure. "8 turns for the Granary"
    and a cited 4 turns for the Library are treated as rival figures here; only the
    evidence drawer, which shows each cited fact's subject, settles that. Erring that way
    costs a rejection and a deterministic answer, never a false figure.
    """
    out: list[Numeral] = []
    for numeral in numerals_in(player_text):
        if _TURN_REFERENCE.search(player_text[:numeral.start]):
            continue
        out.append(numeral)
    return tuple(out)


def numerals_in(text: str, *, strip_ids: Iterable[str] = ()) -> tuple[Numeral, ...]:
    """Every numeral in `text`, after the bracketed citations the answer is allowed to
    make are removed -- an id like `[comparison.culture.81]` carries a turn number that is
    not a claim about anything. Each numeral carries its offset into `text`."""
    text = _mask_citations(text, strip_ids)
    found: list[tuple[int, Numeral]] = []
    for m in _DIGITS.finditer(text):
        raw = m.group(0)
        percent = raw.endswith("%")
        body = raw.rstrip("%").replace(",", "")
        try:
            value = Decimal(body)
        except InvalidOperation:
            continue
        places = len(body.split(".")[1]) if "." in body else 0
        found.append((m.start(), Numeral(raw, value, places, percent, m.start())))
    for m in _WORDS.finditer(text):
        word = m.group(1).lower()
        found.append((m.start(),
                      Numeral(m.group(1), Decimal(NUMBER_WORDS[word]), 0, False, m.start())))
    return tuple(n for _, n in sorted(found, key=lambda pair: pair[0]))


@dataclass(frozen=True)
class Admitted:
    value: Decimal
    ratio: bool      # may also be written as a percentage
    player: bool = False   # carried by a player_report fact


def _decimal(value) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    return None      # a string value is a name, not a number source


# A numeral inside a TOKEN is not a figure: a hex digest ("9f3a1c7b40e2" offers 9, 3, 1,
# 7, 40, 2), a date ("2026-09-13" offers 2026 and, because of the hyphens, -09 and -13),
# a clock time ("14:32"), an identifier ("BUILDING_2"). Each is matched here so that
# `figures_in_note` can drop it.
_NOTE_TOKEN = re.compile(
    r"\d+(?::\d+)+"                      # 14:32, 14:32:05
    r"|\d{4}-\d{2}-\d{2}"                # 2026-09-13
    r"|[0-9]*[A-Za-z_][A-Za-z0-9_]*"      # anything with a letter in it: 9f3a1c7b40e2
)


def figures_in_note(note: str) -> tuple[Numeral, ...]:
    """The numerals in a fact's note that are FIGURES, which is what rule 2 admits.

    Rule 2 admits a note's numbers because notes are written by the deterministic layer
    about the figure -- "Luxuries 1, civics 0, entertainment 2" is as much a reading as
    the value beside it. A number that is part of a token is not one of those: a sha256,
    a modification time, a date, an identifier. Admitting them was how a ruleset fact
    handed generated prose a dozen arbitrary digits, enough to state a payback period
    computed from nothing -- and, because a digest differs per install, enough to make
    validation pass on one player's machine and fail on another's. A date is worse than
    it looks: "2026-09-13" parses as 2026, -09 and -13, so it admits NEGATIVE values.

    Provenance no longer goes into a note at all (`EvidenceFact.source_detail` holds it).
    This is the second line: rule 2 reaches every fact, and the next note written with a
    timestamp in it must not reopen the hole. It can only ever REMOVE numbers from the
    admitted pool, so it cannot license a figure -- at worst it rejects prose that quoted
    a number out of an identifier, which is prose quoting an identifier as a figure.
    """
    return numerals_in(_NOTE_TOKEN.sub(lambda m: " " * len(m.group(0)), note))


def admitted(facts: Iterable[Mapping]) -> tuple[Admitted, ...]:
    """Every number the cited facts carry: value, observed turn, numerals in the note."""
    out: list[Admitted] = []
    for fact in facts:
        ratio = fact.get("unit") == "ratio"
        player = fact.get("kind") == "player_report"
        value = _decimal(fact.get("value"))
        if value is not None:
            out.append(Admitted(value, ratio, player))
        turn = _decimal(fact.get("observed_turn"))
        if turn is not None:
            out.append(Admitted(turn, False, player))
        for n in figures_in_note(str(fact.get("note") or "")):
            out.append(Admitted(n.value, False, player))
    return tuple(out)


def _rounded(value: Decimal, places: int) -> Decimal | None:
    """`value` rounded to `places` decimals, or None when Decimal cannot represent that.

    `quantize` RAISES `InvalidOperation` rather than returning anything when the result
    would exceed the context's precision -- a numeral written with thousands of decimal
    places, or a cited value large enough that rounding it overflows. That exception
    used to escape `check`, be swallowed by the worker's blanket handler, and reach the
    player as the rejection reason "[<class 'decimal.InvalidOperation'>]". None instead
    means "this cannot be compared at that precision", which is not a match; exact
    equality is tried first in `_matches` and never raises, so a value written with
    absurd but harmless precision ("7.000...0") still matches the 7 it is.
    """
    try:
        return value.quantize(Decimal(1).scaleb(-places))
    except InvalidOperation:
        return None


def _matches(numeral: Numeral, candidate: Admitted) -> bool:
    if numeral.percent:
        if not candidate.ratio:
            return False
        scaled = candidate.value * 100
        if numeral.value == scaled:
            return True
        rounded = _rounded(scaled, numeral.places)
        return rounded is not None and numeral.value == rounded
    if numeral.value == candidate.value:
        return True
    rounded = _rounded(candidate.value, numeral.places)
    if rounded is not None and numeral.value == rounded:
        return True
    # Nothing else matches. A ratio written as its plain value ("0.44 of the median")
    # is already covered by the equality above; only the `%` form needs the extra rule.
    return False


def check(text: str, cited_ids: Iterable[str], facts: Iterable[Mapping],
          player_text: str = "") -> Grounding:
    """Spec section 4.3. `facts` is the full payload list; only those whose id is in
    `cited_ids` may ground a number. `player_text` is what the player typed: its numbers
    are never citations (rule 7), may be repeated only as the player's claim, and when
    the answer cites a numeric fact at all, at least one cited value must appear in the
    prose beside the claim -- the disagreement is named, never resolved by omission.

    An attribution or claim phrase counts only for numerals in the same sentence as the
    phrase (`_sentences` says how crudely a sentence is found).

    A mechanical proxy, and only that: "at least one cited value appears in the prose"
    does not establish that the cited value and the player's number describe the same
    thing, and nothing here knows whether they do. The deterministic answer lists the
    player's typed numbers beside every grounded figure so the comparison is on screen
    either way."""
    cited = set(cited_ids)
    pool = admitted(f for f in facts if f.get("id") in cited)
    typed = {n.value for n in numerals_in(player_text)}
    # Rule 7 weighs the player's QUANTITIES against the advisor's; a turn they named is
    # not one. `typed` above stays every numeral they wrote, because repeating any of
    # them as their claim is still governed by the CLAIM phrases below.
    claimed = quantity_claims(player_text)
    # Sentences are taken from the masked text so a dotted id cannot introduce a break,
    # and the mask preserves length so a numeral's offset still indexes into it.
    spans = _sentences(_mask_citations(text, cited))
    ungrounded: list[str] = []
    unattributed: list[str] = []
    unreconciled: list[str] = []
    numerals = numerals_in(text, strip_ids=cited)
    states_a_cited_value = any(
        _matches(n, c) for n in numerals for c in pool if not c.player)
    pool_has_values = any(not c.player for c in pool)
    repeats_a_claim = any(n.value in typed and _phrase_by(n, spans, CLAIM) for n in numerals)
    if claimed and pool_has_values and states_a_cited_value and not repeats_a_claim:
        # The mirror of the case below: the game's figure stated, the player's number
        # never acknowledged. Quietly overriding them is the same defect as quietly
        # adopting them, so both numbers must be on the page.
        unreconciled.extend(n.text for n in claimed if n.text not in unreconciled)
    for numeral in numerals:
        matches = [c for c in pool if _matches(numeral, c)]
        if matches:
            if all(c.player for c in matches) and not _phrase_by(numeral, spans, ATTRIBUTION):
                # Only the player's own report carries this number. Spec 4.3 rule 6: the
                # prose must say so, or it is stating the player's figure as the game's.
                if numeral.text not in unattributed:
                    unattributed.append(numeral.text)
            continue
        if numeral.value in typed and _phrase_by(numeral, spans, CLAIM):
            # The player's own typed figure, repeated as their claim. Allowed -- but
            # not while a cited figure it might disagree with goes unstated. A turn they
            # named is not a rival figure, so it does not have to be reconciled with one.
            claims_a_quantity = any(n.value == numeral.value for n in claimed)
            if (claims_a_quantity and pool_has_values and not states_a_cited_value
                    and numeral.text not in unreconciled):
                unreconciled.append(numeral.text)
            continue
        if numeral.text not in ungrounded:
            ungrounded.append(numeral.text)
    return Grounding(ok=not ungrounded and not unattributed and not unreconciled,
                     ungrounded=tuple(ungrounded), unattributed=tuple(unattributed),
                     unreconciled=tuple(unreconciled))


__all__ = ["ATTRIBUTION", "CLAIM", "Admitted", "Grounding", "NUMBER_WORDS", "Numeral",
           "admitted", "check", "figures_in_note", "numerals_in", "quantity_claims"]
