from dataclasses import FrozenInstanceError, fields
from pathlib import Path

import pytest

from civ_advisor.ruleset.base import (
    NO_RULESET, BuildingFacts, NullRuleset, RulesetCount, RulesetFigure, RulesetIdentity,
    RulesetMention, RulesetProvider,
)

IDENTITY = RulesetIdentity(path=Path("/games/DebugGameplay.sqlite"), size=18_051_072,
                           mtime_ns=1_757_667_420_000_000_000, digest="ab" * 32)


def _figure(**overrides) -> RulesetFigure:
    row = dict(subject="BUILDING_LIBRARY", label="Library production cost", value=90,
               unit="production", table="Buildings", column="Cost",
               row_key=("BUILDING_LIBRARY",), identity=IDENTITY)
    row.update(overrides)
    return RulesetFigure(**row)


def test_a_figure_must_name_the_row_it_came_from():
    """The structural guard. A number with no table, column and row behind it is an
    assertion, not a figure, and must not be constructible at all."""
    for missing in ({"table": ""}, {"column": ""}, {"row_key": ()}):
        with pytest.raises(ValueError, match="table, column and row"):
            _figure(**missing)


def test_a_mention_has_no_value_to_state():
    """A modifier chain says an effect exists and never says how much. The type it
    becomes must have nowhere to put a magnitude."""
    assert "value" not in {f.name for f in fields(RulesetMention)}
    mention = RulesetMention(subject="BUILDING_GREAT_LIBRARY",
                             label="Great Library has 2 conditional effects",
                             detail="The ruleset records what triggers them.")
    assert "does not state its magnitude" in mention.as_unknown()


def test_identity_carries_no_version_and_claims_none():
    """No table in the database names a game build, an expansion or a mod. The identity
    type must therefore have nowhere to record one, and must not imply one in words."""
    names = {f.name for f in fields(RulesetIdentity)}
    assert names == {"path", "size", "mtime_ns", "digest"}
    described = IDENTITY.describe()
    assert "version" not in described.lower()
    assert IDENTITY.short_digest in described
    assert "DebugGameplay.sqlite" in described


def test_a_count_cannot_be_constructed_as_a_figure():
    """The whole-phase review's fix: BuildingModifiers rows may be counted, never
    priced. Attempting to build the exact leak the reviewer described -- a count
    smuggled in as a figure via an aggregate column -- must fail at construction."""
    with pytest.raises(ValueError, match="aggregate"):
        _figure(column="COUNT(*)", value=3, unit=None)


def test_a_count_has_no_value_or_unit_field_to_carry_a_magnitude():
    """Structurally distinct from RulesetFigure: nowhere to put a number a reader
    could mistake for a yield or a cost."""
    names = {f.name for f in fields(RulesetCount)}
    assert "value" not in names and "unit" not in names
    assert "count" in names


def test_a_count_must_also_name_the_rows_it_came_from():
    with pytest.raises(ValueError, match="table, column and row"):
        RulesetCount(subject="BUILDING_GREAT_LIBRARY", label="Modifier count", count=3,
                    table="", column="COUNT(*)", row_key=("BUILDING_GREAT_LIBRARY",),
                    identity=IDENTITY)


def test_a_count_cannot_be_negative():
    with pytest.raises(ValueError, match="cannot be negative"):
        RulesetCount(subject="BUILDING_GREAT_LIBRARY", label="Modifier count", count=-1,
                    table="BuildingModifiers", column="COUNT(*)",
                    row_key=("BUILDING_GREAT_LIBRARY",), identity=IDENTITY)


def test_a_count_renders_visibly_distinct_from_a_yield():
    count = RulesetCount(subject="BUILDING_GREAT_LIBRARY",
                         label="Great Library modifier-based effects", count=3,
                         table="BuildingModifiers", column="COUNT(*)",
                         row_key=("BUILDING_GREAT_LIBRARY",), identity=IDENTITY)
    described = count.describe()
    assert "3 modifier-based effects" in described
    assert "does not state their magnitude" in described


def test_ruleset_fact_refuses_a_count():
    """The same guard that already refuses a RulesetMention (no value field to read)
    must refuse a RulesetCount just as hard -- this is the whole point of the type."""
    from civ_advisor.decisions.evidence import EvidenceLedger, ruleset_fact

    count = RulesetCount(subject="BUILDING_GREAT_LIBRARY", label="Modifier count",
                         count=3, table="BuildingModifiers", column="ModifierId",
                         row_key=("BUILDING_GREAT_LIBRARY",), identity=IDENTITY)
    with pytest.raises(TypeError, match="only accepts a RulesetFigure"):
        ruleset_fact(EvidenceLedger(), count)


def test_building_facts_counts_are_never_folded_into_figures():
    count = RulesetCount(subject="BUILDING_GREAT_LIBRARY", label="Modifier count",
                         count=3, table="BuildingModifiers", column="ModifierId",
                         row_key=("BUILDING_GREAT_LIBRARY",), identity=IDENTITY)
    facts = BuildingFacts(building="BUILDING_GREAT_LIBRARY", cost=_figure(),
                          counts=(count,))
    assert facts.figures == (_figure(),)
    assert count not in facts.figures
    assert facts.counts == (count,)


def test_figures_are_immutable():
    with pytest.raises(FrozenInstanceError):
        _figure().value = 1  # type: ignore[misc]


def test_building_facts_collects_only_the_figures_that_exist():
    facts = BuildingFacts(building="BUILDING_LIBRARY", cost=_figure(),
                          maintenance=None, prereq_district=None, prereq_tech=None,
                          prereq_civic=None,
                          yields=(_figure(column="YieldChange", table="Building_YieldChanges",
                                          row_key=("BUILDING_LIBRARY", "YIELD_SCIENCE"),
                                          label="Library science yield", value=2,
                                          unit="per turn"),))
    assert [f.column for f in facts.figures] == ["Cost", "YieldChange"]


def test_the_null_ruleset_answers_nothing_and_says_why():
    null = NullRuleset("no database was found")
    assert isinstance(null, RulesetProvider)
    assert null.available is False
    assert null.reason == "no database was found"
    assert null.identity() is None
    assert null.building("BUILDING_LIBRARY") is None
    assert NO_RULESET.available is False
