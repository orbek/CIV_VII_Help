import re
from dataclasses import fields

import pytest

from civ_advisor.decisions.evidence import EvidenceLedger, ruleset_fact
from civ_advisor.decisions.models import SourceKind
from civ_advisor.ruleset.base import (
    RulesetFigure, RulesetIdentity, RulesetMention, RulesetOutOfScope,
)
from civ_advisor.ruleset.civ6 import (
    COUNTABLE_COLUMNS, EFFECT_TABLES, READABLE_COLUMNS, clear_cache, open_ruleset,
)

from tests.ruleset_fixture import make_ruleset


@pytest.fixture
def ruleset(tmp_path):
    clear_cache()
    yield open_ruleset(make_ruleset(tmp_path))
    clear_cache()


def test_no_effect_table_is_readable_or_countable():
    """The allowlist, asserted from the other side. If someone adds one of these to make
    a number available, this fails before the number reaches a player."""
    assert EFFECT_TABLES.isdisjoint(READABLE_COLUMNS)
    assert EFFECT_TABLES.isdisjoint(COUNTABLE_COLUMNS)


def test_a_modifier_effect_never_surfaces_as_a_number(ruleset):
    """The Great Library's science effect. `ModifierArguments` says TechBoost=1, where 1
    is a flag meaning "apply the standard boost" and not a quantity of science. The
    advisor must be able to say the effect exists and must not be able to say how much.
    """
    facts = ruleset.building("BUILDING_GREAT_LIBRARY")

    assert facts is not None
    assert facts.yields == ()
    assert facts.mentions and all(isinstance(m, RulesetMention) for m in facts.mentions)
    assert all(not isinstance(m, RulesetFigure) for m in facts.mentions)
    # The one number in the chain is 1. It must appear nowhere in what a player is shown.
    unknown = facts.mentions[0].as_unknown()
    assert "does not state its magnitude" in unknown
    assert not re.search(r"\d", unknown.replace("1 conditional", ""))
    # And nothing derived from that building may be cited as a ruleset figure with a value
    # from an effect table.
    ledger = EvidenceLedger()
    for figure in facts.figures:
        ruleset_fact(ledger, figure)
    assert all(f.record_key[0] not in EFFECT_TABLES for f in ledger.facts.values())


def test_a_building_with_no_yield_rows_does_not_claim_to_yield_nothing(ruleset):
    """Only 79 building types have any Building_YieldChanges row. An empty list is not a
    finding, and the mention is what stops it being read as one."""
    facts = ruleset.building("BUILDING_GREAT_LIBRARY")

    assert "not evidence that this building yields nothing" in facts.mentions[0].as_unknown()


def test_every_readable_column_is_a_value_and_not_a_key_into_an_effect(ruleset):
    """A readable column must be the figure itself. A column named *ModifierId or
    *Modifier is a pointer into the system this phase excludes."""
    for table, columns in READABLE_COLUMNS.items():
        assert not [c for c in columns if "Modifier" in c], table


def test_no_ruleset_fact_claims_a_version_a_dlc_or_a_mod(ruleset):
    """The database names none of the three. A figure that implied one would be the exact
    inference this phase exists to avoid."""
    ledger = EvidenceLedger()
    for figure in ruleset.building("BUILDING_LIBRARY").figures:
        ruleset_fact(ledger, figure)

    assert ledger.facts
    for fact in ledger.facts.values():
        assert fact.source_kind is SourceKind.INSTALLED_RULESET
        note = (fact.note or "").lower()
        assert "version" not in note
        assert not re.search(r"\bv?\d+\.\d+(\.\d+)?\b", note)
        assert "rise and fall" not in note and "gathering storm" not in note
    assert "version" not in {f.name for f in fields(RulesetIdentity)}


def test_the_provider_refuses_a_modifier_query_loudly(ruleset):
    """Raised, not degraded. A caller reaching for a magnitude is a bug in the advisor,
    and must fail in tests rather than quietly return nothing in front of a player."""
    with pytest.raises(RulesetOutOfScope, match="magnitude"):
        ruleset._select("ModifierArguments", ("Value",), {"Name": "TechBoost"})
