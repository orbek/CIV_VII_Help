"""A fact's note may carry figures. It may not carry provenance.

THE DEFECT THIS EXISTS TO STOP, in full, because the next person to write a note needs
to know which side of the line they are on. Spec 4.3 rule 2 admits every numeral in a
cited fact's note, on the ground that notes are written by the deterministic layer ABOUT
the figure -- "Your 11.0 against a rival median of 17.2", "25.0 of 30.0 production". Those
numbers are as much a reading as the value beside them, and the rule exists for them.

`ruleset_fact` then built its note out of `RulesetIdentity.describe()`, which embeds the
file's modification time and its sha256. Every ruleset fact therefore carried about a
dozen digits that say NOTHING about the figure, and generated prose could spend them:
against a fact holding only 90, this validated clean --

    "The Library costs 90 production. That is about 14 turns, returning 40 science by
     turn 32."

14 and 32 out of the timestamp, 40 out of "40e2" inside the digest. Two aggravators made
it worse than one bad sentence: a digest differs per install, so the same answer validated
on one player's machine and failed on another's; and "2026-09-13" parses as 2026, -09 and
-13, so a date admitted NEGATIVE values.

The fix was to keep provenance out of notes -- it lives in `EvidenceFact.source_detail`,
which `grounding.admitted` does not read -- rather than to stop reading notes, which would
have broken the six builders that legitimately state figures in them.

So the line is not "no numbers in a note". It is "nothing shaped like provenance in a
note": a digest, a timestamp, a clock time, a path. Those are the shapes whose digits are
arbitrary. A formatted yield is not one of them, and nothing here rejects one.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from civ_advisor.decisions import evidence
from civ_advisor.decisions.evidence import EvidenceLedger
from civ_advisor.ruleset.base import RulesetFigure, RulesetIdentity
from civ_advisor.tuner.base import BuildOption, CityAmenities, Maintenance, TunerReading

# Each shape carries digits that are not about the figure. The hex rule requires a letter
# in the run so a six-digit FIGURE ("152000 gold") is never mistaken for a digest.
PROVENANCE_SHAPES = {
    "a digest": re.compile(r"\b(?=[0-9a-fA-F]*[a-fA-F])[0-9a-fA-F]{6,}\b"),
    "an ISO date": re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
    "a clock time": re.compile(r"\b\d{1,2}:\d{2}\b"),
    "a file path with an extension": re.compile(r"\b[\w/\\-]+\.[A-Za-z]{2,6}\b"),
}

# Every builder in `evidence` that makes a fact. The sweep below calls all of them; this
# set is compared against the module so that ADDING a builder fails here until it is
# exercised, rather than quietly arriving unchecked.
BUILDERS = {
    "yield_fact", "yield_comparison_fact", "net_gold_fact", "happiness_fact",
    "queue_facts", "settlement_coverage_fact", "completed_item_facts", "age_fact",
    "human_identity_fact", "analysis_turn_fact", "ruleset_fact", "amenities_fact",
    "tuner_net_gold_fact", "build_option_fact", "defense_facts",
}

IDENTITY = RulesetIdentity(path=Path("/games/DebugGameplay.sqlite"), size=18_051_072,
                           mtime_ns=1_789_655_520_000_000_000,
                           digest="9f3a1c7b40e2" + "0" * 52)
READING = TunerReading(turn=53, read_at="2026-09-13T10:40:00Z", state="GameCore_Tuner")


def looks_like_provenance(note: str) -> str | None:
    """Which provenance shape a note carries, or None. See this module's docstring."""
    for what, pattern in PROVENANCE_SHAPES.items():
        if pattern.search(note):
            return what
    return None


def every_fact(state) -> tuple:
    """One call to every builder in `evidence`, with this fixture's real state."""
    ledger = EvidenceLedger()
    made = []
    for stat in evidence.YIELD_STATS:
        made.append(evidence.yield_fact(ledger, state, state.HUMAN, stat))
        made.append(evidence.yield_comparison_fact(ledger, state, stat))
        for rival in state.rivals():
            made.append(evidence.yield_fact(ledger, state, rival.id, stat))
    made.append(evidence.net_gold_fact(ledger, state))
    made.append(evidence.happiness_fact(ledger, state))
    made.extend(evidence.queue_facts(ledger, state))
    made.append(evidence.settlement_coverage_fact(ledger, state))
    made.extend(evidence.completed_item_facts(ledger, state))
    made.append(evidence.age_fact(ledger, state))
    made.append(evidence.human_identity_fact(ledger, state))
    made.append(evidence.analysis_turn_fact(ledger, state))
    made.extend(evidence.defense_facts(ledger, state))
    made.append(evidence.ruleset_fact(ledger, RulesetFigure(
        subject="BUILDING_LIBRARY", label="Library production cost", value=90,
        unit="production", table="Buildings", column="Cost",
        row_key=("BUILDING_LIBRARY",), identity=IDENTITY)))
    made.append(evidence.amenities_fact(ledger, READING, CityAmenities(
        city="Rome", total=3, from_luxuries=1, from_civics=0, from_entertainment=2,
        housing=9, food_surplus=1)))
    made.append(evidence.tuner_net_gold_fact(ledger, READING, Maintenance(
        total=1, buildings=0, districts=1, units=0, gold=152, gold_yield=8)))
    made.append(evidence.build_option_fact(ledger, READING, "Rome",
                                           BuildOption("BUILDING_GRANARY", 8)))
    return tuple(f for f in made if f is not None)


def test_the_sweep_covers_every_fact_builder():
    """A builder added to `evidence` and not exercised below would leave the next note
    unchecked, which is exactly how the last one arrived."""
    found = {name for name, obj in vars(evidence).items()
             if callable(obj) and name.endswith(("_fact", "_facts"))
             and getattr(obj, "__module__", "") == evidence.__name__}
    assert found == BUILDERS, "a fact builder was added or renamed: exercise it in every_fact"


def test_no_fact_note_carries_provenance(civ6_store):
    facts = every_fact(civ6_store.rebuild().state)
    notes = [(f.id, f.note) for f in facts if f.note]
    assert notes, "the sweep proves nothing if no builder wrote a note"
    for fact_id, note in notes:
        shape = looks_like_provenance(note)
        assert shape is None, (
            f"{fact_id}'s note carries {shape}: {note!r}. Provenance belongs in "
            "source_detail, which the number rule does not read -- see this module's "
            "docstring for the answer a digest in a note once licensed")


def test_the_figures_builders_state_in_notes_are_left_alone(civ6_store):
    """The other half of the line: the rule admits a note's figures, and this must not
    have been turned into a ban on digits."""
    notes = [f.note for f in every_fact(civ6_store.rebuild().state) if f.note]
    assert any(re.search(r"\d", note) for note in notes)


@pytest.mark.parametrize("note, shape", [
    ("Read from DebugGameplay.sqlite, sha256 9f3a1c7b40e2", "a digest"),
    ("Last written 2026-09-13 by the game", "an ISO date"),
    ("Read at 14:32 UTC", "a clock time"),
    ("Parsed from Logs/Player_Stats.csv", "a file path with an extension"),
])
def test_the_discriminator_names_each_shape(note, shape):
    assert looks_like_provenance(note) == shape


@pytest.mark.parametrize("note", [
    "Your 11.0 against a rival median of 17.2; the advisor's threshold is 0.8.",
    "25.0 of 30.0 production, added on turn 20.",
    "Luxuries 1, civics 0, entertainment 2; unexplained 0.",
    "Reserve is 152000 gold.",
])
def test_a_figure_in_a_note_is_not_provenance(note):
    """Six builders write sentences like these, and rule 2 exists for them."""
    assert looks_like_provenance(note) is None
