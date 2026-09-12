from dataclasses import FrozenInstanceError, fields
from pathlib import Path

import pytest

from civ_advisor.ruleset.base import (
    NO_RULESET, BuildingFacts, NullRuleset, RulesetFigure, RulesetIdentity,
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
