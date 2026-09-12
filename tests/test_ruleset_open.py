import pytest

from civ_advisor.ruleset.civ6 import Civ6Ruleset, clear_cache, open_ruleset

from tests.ruleset_fixture import SCHEMA, make_ruleset


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_cache()
    yield
    clear_cache()


def test_a_missing_database_degrades_to_asking_the_player(tmp_path):
    provider = open_ruleset(tmp_path / "nothing-here.sqlite")

    assert provider.available is False
    assert provider.building("BUILDING_LIBRARY") is None
    assert "nothing-here.sqlite" in provider.reason
    assert "preview" in provider.reason


def test_a_file_that_is_not_a_database_degrades(tmp_path):
    path = tmp_path / "DebugGameplay.sqlite"
    path.write_bytes(b"this is not a database")

    provider = open_ruleset(path)

    assert provider.available is False
    assert "could not be read" in provider.reason


def test_a_changed_schema_degrades_and_names_what_is_missing(tmp_path):
    """A patch that renames a column must stop the advisor quoting figures, not make it
    quote the wrong ones."""
    renamed = SCHEMA.replace("Cost INTEGER", "ProductionCost INTEGER")
    path = make_ruleset(tmp_path, schema=renamed, rows={"Buildings": []})

    provider = open_ruleset(path)

    assert provider.available is False
    assert "Buildings" in provider.reason and "Cost" in provider.reason


def test_a_missing_table_degrades(tmp_path):
    without_yields = "".join(
        f"{statement};" for statement in SCHEMA.split(";")
        if statement.strip() and "Building_YieldChanges" not in statement)
    path = make_ruleset(tmp_path, schema=without_yields,
                        rows={"Building_YieldChanges": []})

    provider = open_ruleset(path)

    assert provider.available is False
    assert "Building_YieldChanges" in provider.reason


def test_the_same_unchanged_file_is_opened_once(tmp_path):
    path = make_ruleset(tmp_path)

    assert open_ruleset(path) is open_ruleset(path)


def test_a_modded_ruleset_is_re_derived_rather_than_served_stale(tmp_path):
    """The reason the cache is keyed on the file and not on the path. A stale cost is
    worse than no cost: it is indistinguishable from a verified one."""
    path = make_ruleset(tmp_path)
    assert open_ruleset(path).building("BUILDING_LIBRARY").cost.value == 90

    path.unlink()
    make_ruleset(tmp_path, rows={"Buildings": [
        ("BUILDING_LIBRARY", "LOC_X", 45, 1, "DISTRICT_CAMPUS", "TECH_WRITING", "", 0, 0)]})

    provider = open_ruleset(path)
    assert provider.building("BUILDING_LIBRARY").cost.value == 45
    assert isinstance(provider, Civ6Ruleset)
