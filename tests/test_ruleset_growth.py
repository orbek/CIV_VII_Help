"""The allowlist grew by the tables spec section 4.2 names -- and only those.

NOTE: the catalog-level tests from the task-6 brief (`ruleset.building` etc. resolving
through `civ_advisor.copilot.catalog.ask`) are not included here. That module does not
exist in this tree yet -- Task 5, which produces `civ_advisor/copilot/catalog.py`, has
not landed on this branch. See task-6-report.md for the discrepancy; wiring these
questions into the catalog is left for whichever task lands `civ_advisor/copilot`.
"""
import sqlite3
from pathlib import Path

import pytest

from civ_advisor.ruleset.base import RulesetMention
from civ_advisor.ruleset.civ6 import (
    DEFAULT_DATABASE, READABLE_COLUMNS, RULE_PARAMETERS, Civ6Ruleset,
)
from tests.ruleset_fixture import build_fixture


@pytest.fixture
def ruleset(tmp_path: Path):
    path = build_fixture(tmp_path / "DebugGameplay.sqlite")
    provider = Civ6Ruleset.open(path)
    yield provider
    provider.close()


def test_the_new_tables_are_in_the_allowlist_with_exactly_these_columns():
    assert READABLE_COLUMNS["GlobalParameters"] == frozenset({"Name", "Value"})
    assert READABLE_COLUMNS["Government_SlotCounts"] == frozenset(
        {"GovernmentType", "GovernmentSlotType", "NumSlots"})
    assert {"Housing", "Entertainment", "CitizenSlots", "IsWonder", "RequiresPlacement"} \
        <= READABLE_COLUMNS["Buildings"]
    assert {"BaseMoves", "Range", "Domain", "PromotionClass"} <= READABLE_COLUMNS["Units"]


def test_effect_tables_are_still_refused():
    for table in ("Modifiers", "ModifierArguments", "PolicyModifiers", "GovernmentModifiers"):
        assert table not in READABLE_COLUMNS


def test_a_parameter_is_read_only_from_the_fixed_name_set(ruleset):
    assert "CITY_AMENITIES_FOR_FREE" in RULE_PARAMETERS
    fig = ruleset.parameter("CITY_AMENITIES_FOR_FREE")
    assert fig is not None and fig.value == 0
    assert fig.table == "GlobalParameters" and fig.column == "Value"
    assert ruleset.parameter("SOMETHING_ELSE") is None


def test_a_government_states_its_slot_counts_as_figures(ruleset):
    facts = ruleset.government("GOVERNMENT_CLASSICAL_REPUBLIC")
    slots = {f.row_key[1]: f.value for f in facts.slots}
    assert slots == {"SLOT_DIPLOMATIC": 1, "SLOT_ECONOMIC": 2, "SLOT_WILDCARD": 1}


def test_a_policy_states_its_slot_and_civic_and_mentions_its_unquantified_effect(ruleset):
    facts = ruleset.policy("POLICY_URBAN_PLANNING")
    assert facts.slot.value == "SLOT_ECONOMIC"
    assert facts.prereq_civic.value == "CIVIC_CODE_OF_LAWS"
    assert any(isinstance(m, RulesetMention) for m in facts.mentions)


def test_a_luxury_resource_states_its_amenity_figure(ruleset):
    facts = ruleset.resource("RESOURCE_SILK")
    assert facts.resource_class.value == "RESOURCECLASS_LUXURY"
    assert facts.happiness.value == 4


def test_a_strategic_resource_states_zero_not_absence(ruleset):
    assert ruleset.resource("RESOURCE_IRON").happiness.value == 0


def test_an_improvement_states_housing_and_yields(ruleset):
    facts = ruleset.improvement("IMPROVEMENT_FARM")
    assert facts.housing.value == 1
    assert {(f.row_key[1], f.value) for f in facts.yields} == {("YIELD_FOOD", 1), ("YIELD_PRODUCTION", 0)}


def test_a_building_now_states_housing_and_placement(ruleset):
    facts = ruleset.building("BUILDING_GRANARY")
    assert facts.housing.value == 2
    assert facts.requires_placement.value == 0


def test_a_unit_now_states_moves_and_range(ruleset):
    facts = ruleset.unit("UNIT_ARCHER")
    assert facts.moves.value == 2 and facts.range.value == 2


@pytest.mark.skipif(not DEFAULT_DATABASE.is_file(), reason="no installed Civ VI ruleset here")
def test_every_allowlisted_column_exists_in_the_real_installed_file():
    """Read-only. A patch that renames a column must fail a developer's run, not a player's."""
    conn = sqlite3.connect(f"file:{DEFAULT_DATABASE.as_posix()}?mode=ro", uri=True)
    try:
        for table, columns in READABLE_COLUMNS.items():
            present = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
            assert present, f"{table} is not in the installed ruleset"
            assert columns <= present, (table, sorted(columns - present))
        names = {row[0] for row in conn.execute("SELECT Name FROM GlobalParameters")}
        assert RULE_PARAMETERS <= names, sorted(RULE_PARAMETERS - names)
    finally:
        conn.close()
