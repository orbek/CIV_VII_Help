import sqlite3

import pytest

from civ_advisor.ruleset.base import RulesetOutOfScope, RulesetProvider
from civ_advisor.ruleset.civ6 import COUNTABLE_COLUMNS, READABLE_TABLES, Civ6Ruleset

from tests.ruleset_fixture import make_ruleset


@pytest.fixture
def ruleset(tmp_path):
    provider = Civ6Ruleset.open(make_ruleset(tmp_path))
    yield provider
    provider.close()


def test_a_building_states_its_real_cost_prereqs_and_flat_yield(ruleset):
    """The figures the research report verified against a real install: Library costs 90
    production and 1 gold, needs a Campus and Writing, and yields a flat +2 science."""
    facts = ruleset.building("BUILDING_LIBRARY")

    assert facts is not None
    assert (facts.cost.value, facts.cost.unit) == (90, "production")
    assert (facts.maintenance.value, facts.maintenance.unit) == (1, "gold per turn")
    assert facts.prereq_district.value == "DISTRICT_CAMPUS"
    assert facts.prereq_tech.value == "TECH_WRITING"
    assert facts.prereq_civic is None          # empty in the row, so absent, not ""
    assert [(f.value, f.label) for f in facts.yields] == [(2, "Library science yield")]


def test_every_figure_carries_the_row_that_produced_it(ruleset):
    facts = ruleset.building("BUILDING_LIBRARY")

    assert (facts.cost.table, facts.cost.column) == ("Buildings", "Cost")
    assert facts.cost.row_key == ("BUILDING_LIBRARY",)
    science = facts.yields[0]
    assert (science.table, science.column) == ("Building_YieldChanges", "YieldChange")
    assert science.row_key == ("BUILDING_LIBRARY", "YIELD_SCIENCE")


def test_a_building_the_ruleset_does_not_have_is_absent_not_empty(ruleset):
    assert ruleset.building("BUILDING_NOT_A_BUILDING") is None


def test_the_provider_satisfies_the_protocol_and_names_its_identity(ruleset):
    assert isinstance(ruleset, RulesetProvider)
    assert ruleset.available is True and ruleset.reason is None
    assert ruleset.identity().path.name == "DebugGameplay.sqlite"


def test_the_modifier_tables_are_not_readable(ruleset):
    """The whole point of the allowlist. These tables wire up an effect and never state
    its magnitude; reading one would be inference wearing a citation."""
    for table in ("Modifiers", "ModifierArguments"):
        with pytest.raises(RulesetOutOfScope, match=table):
            ruleset._select(table, ("ModifierId",), {})
        assert table not in READABLE_TABLES


def test_a_readable_table_still_refuses_an_unlisted_column(ruleset):
    with pytest.raises(RulesetOutOfScope, match="Housing"):
        ruleset._select("Buildings", ("Housing",), {"BuildingType": "BUILDING_LIBRARY"})


def test_building_modifiers_may_be_counted_but_never_read(ruleset):
    """Counting is how "this building does something the ruleset does not quantify" is
    established. A count is not a magnitude, and the value columns stay unreachable."""
    assert ruleset._count("BuildingModifiers", {"BuildingType": "BUILDING_GREAT_LIBRARY"}) == 1
    assert COUNTABLE_COLUMNS["BuildingModifiers"] == frozenset({"BuildingType"})
    with pytest.raises(RulesetOutOfScope):
        ruleset._select("BuildingModifiers", ("ModifierId",), {})
    with pytest.raises(RulesetOutOfScope):
        ruleset._count("Modifiers", {"ModifierId": "GREATLIBRARY_BOOST_SCIENTIST"})


def test_the_database_is_opened_read_only(ruleset):
    """It is the player's own game file. Two locks, because one of them being right is
    not something to find out in production."""
    with pytest.raises(sqlite3.OperationalError, match="readonly|read-only"):
        ruleset._connection.execute("UPDATE Buildings SET Cost = 1")


def test_reading_never_leaves_a_journal_or_touches_the_files_mtime(tmp_path):
    """The hard constraint stated in words above is checked here, not assumed: after a
    full run of lookups (including a rejected write attempt and an out-of-scope query),
    no new file has appeared beside the database and its mtime has not moved."""
    path = make_ruleset(tmp_path)
    before_files = {p.name for p in tmp_path.iterdir()}
    before_mtime = path.stat().st_mtime_ns

    provider = Civ6Ruleset.open(path)
    try:
        provider.building("BUILDING_LIBRARY")
        provider.building("BUILDING_BANK")
        provider.building("BUILDING_NOT_A_BUILDING")
        with pytest.raises(RulesetOutOfScope):
            provider._select("Modifiers", ("ModifierId",), {})
        with pytest.raises(sqlite3.OperationalError):
            provider._connection.execute("UPDATE Buildings SET Cost = 1")
    finally:
        provider.close()

    after_files = {p.name for p in tmp_path.iterdir()}
    assert after_files == before_files, (
        f"a file appeared beside the database: {after_files - before_files}")
    assert path.stat().st_mtime_ns == before_mtime


def test_an_unexpected_schema_degrades_instead_of_raising(tmp_path):
    """The two kinds of "cannot answer" this provider tells apart: absent data (no row)
    returns None already; an unexpected schema -- a mod or patch renaming a column this
    provider assumes exists -- must degrade the same way, not raise a raw sqlite error
    into the advisor and not silently return a wrong number."""
    path = make_ruleset(tmp_path)
    # A read-write connection just to reshape the schema, as a mod's installer would;
    # closed immediately so the provider under test opens its own read-only connection.
    setup = sqlite3.connect(path)
    setup.execute("ALTER TABLE Buildings RENAME COLUMN Cost TO CostRenamed")
    setup.commit()
    setup.close()

    provider = Civ6Ruleset.open(path)
    try:
        assert provider.building("BUILDING_LIBRARY") is None
    finally:
        provider.close()


def test_the_placeholder_identity_names_the_real_file(ruleset):
    """Task 4 replaces the digest; until then the size and path must still be real,
    not a stand-in for the whole identity."""
    identity = ruleset.identity()
    assert identity.path.name == "DebugGameplay.sqlite"
    assert identity.size > 0


def test_a_district_states_its_cost_and_prerequisite(ruleset):
    facts = ruleset.district("DISTRICT_CAMPUS")

    assert facts.cost.value == 54 and facts.cost.unit == "production"
    assert facts.prereq_tech.value == "TECH_WRITING"
    assert facts.prereq_civic is None


def test_a_technology_states_its_cost_prereqs_and_eureka(ruleset):
    """Boosts are a purpose-built table, not a modifier chain: the percentage is a row
    value and the trigger is named by a column."""
    facts = ruleset.technology("TECH_WRITING")

    assert (facts.cost.value, facts.cost.unit) == (50, "science")
    assert [p.value for p in facts.prereqs] == ["TECH_POTTERY"]
    boost = facts.boosts[0]
    assert (boost.percent.value, boost.percent.unit) == (40, "% of the cost")
    assert boost.trigger.value == "BOOST_TRIGGER_MEET_CIV"
    assert [(o.column, o.value) for o in boost.objects] == [("Unit1Type", "UNIT_SCOUT")]


def test_a_civic_states_its_cost_and_inspiration(ruleset):
    facts = ruleset.civic("CIVIC_STATE_WORKFORCE")

    assert (facts.cost.value, facts.cost.unit) == (70, "culture")
    assert [p.value for p in facts.prereqs] == ["CIVIC_CODE_OF_LAWS"]
    assert [(o.column, o.value) for o in facts.boosts[0].objects] == [("NumItems", 1)]


def test_a_unit_states_its_cost_strength_and_upgrade_target(ruleset):
    facts = ruleset.unit("UNIT_WARRIOR")

    assert (facts.cost.value, facts.cost.unit) == (40, "production")
    assert (facts.combat.value, facts.combat.unit) == (20, "combat strength")
    assert facts.ranged_combat is None            # 0 means no ranged attack, not "0 strength"
    assert facts.maintenance is None              # 0 gold is no maintenance
    assert facts.upgrades_to.value == "UNIT_SWORDSMAN"
    assert facts.strategic_resource is None


def test_the_gold_cost_of_an_upgrade_is_a_mention_and_never_a_number(ruleset):
    """The upgrade target is a row; the gold it costs is computed at runtime and stored
    nowhere. Stating the first without disclaiming the second is how a guess starts."""
    facts = ruleset.unit("UNIT_WARRIOR")

    assert facts.mentions
    assert all("gold" in m.as_unknown().lower() for m in facts.mentions)
    assert not any(f.column == "UpgradeCost" for f in facts.figures)


def test_the_boosts_table_may_not_be_read_for_anything_else(ruleset):
    with pytest.raises(RulesetOutOfScope, match="TriggerDescription"):
        ruleset._select("Boosts", ("TriggerDescription",), {})


def test_a_real_modifier_count_from_the_schema_cannot_reach_the_player_as_a_figure(ruleset):
    """The acceptance test set when RulesetCount was built: a modifier count must not
    be able to reach the player looking like a yield, without deliberately
    circumventing the type -- proved here against a real count Task 6 actually
    produces from the fixture's schema, not only a constructed one."""
    facts = ruleset.building("BUILDING_GREAT_LIBRARY")

    assert facts.counts, "the Great Library fixture must produce a real count"
    count = facts.counts[0]
    assert count.count == 1
    assert count.table == "BuildingModifiers"
    # Structurally incapable of being read as a magnitude: no value/unit field exists
    # to check, and it is provably absent from the figures a renderer would show.
    assert not hasattr(count, "value") and not hasattr(count, "unit")
    assert count not in facts.figures
    assert all(f.table != "BuildingModifiers" for f in facts.figures)
    # What a reader would actually take from it: a description naming a count of
    # effects and disclaiming their magnitude, not a number that reads like a yield.
    assert "1 modifier-based effect" in count.describe()
    assert "does not state their magnitude" in count.describe()
