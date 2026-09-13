"""The number rule, spec section 4.3, as one pure function.

Every number in generated prose must be a number that appears in a fact the answer
cited: the fact's value, its observed turn, or a numeral in its note (notes are written
by the deterministic layer from the data). Nothing else is admitted -- not the player's
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
            parts.append(f"the answer contains {', '.join(self.ungrounded)}, which no cited "
                         "fact carries")
        if self.unattributed:
            parts.append(f"the answer states {', '.join(self.unattributed)} as though the game "
                         "said it, when only your own report does; it must say you reported it")
        if self.unreconciled:
            parts.append(f"you mentioned {', '.join(self.unreconciled)} and the evidence holds "
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
        for n in numerals_in(str(fact.get("note") or "")):
            out.append(Admitted(n.value, False, player))
    return tuple(out)


def _matches(numeral: Numeral, candidate: Admitted) -> bool:
    quant = Decimal(1).scaleb(-numeral.places)
    if numeral.percent:
        if not candidate.ratio:
            return False
        return numeral.value == (candidate.value * 100).quantize(quant)
    if numeral.value == candidate.value.quantize(quant):
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
    if typed and pool_has_values and states_a_cited_value and not repeats_a_claim:
        # The mirror of the case below: the game's figure stated, the player's number
        # never acknowledged. Quietly overriding them is the same defect as quietly
        # adopting them, so both numbers must be on the page.
        unreconciled.extend(n.text for n in numerals_in(player_text)
                            if n.text not in unreconciled)
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
            # not while a cited figure it might disagree with goes unstated.
            if pool_has_values and not states_a_cited_value and numeral.text not in unreconciled:
                unreconciled.append(numeral.text)
            continue
        if numeral.text not in ungrounded:
            ungrounded.append(numeral.text)
    return Grounding(ok=not ungrounded and not unattributed and not unreconciled,
                     ungrounded=tuple(ungrounded), unattributed=tuple(unattributed),
                     unreconciled=tuple(unreconciled))


__all__ = ["ATTRIBUTION", "CLAIM", "Admitted", "Grounding", "NUMBER_WORDS", "Numeral",
           "admitted", "check", "numerals_in"]
