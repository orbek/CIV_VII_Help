"""A small stand-in for Civ VI's DebugGameplay.sqlite.

Table and column names, and the Library/Bank/Warrior row values, are taken verbatim from
.superpowers/sdd/civ6-ruleset-research.md, which was produced by querying a real installed
database read-only. A fixture that renamed a column would make the provider's schema check
pass against something the game never writes.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE Buildings (
    BuildingType TEXT NOT NULL PRIMARY KEY, Name TEXT, Cost INTEGER, Maintenance INTEGER,
    PrereqDistrict TEXT, PrereqTech TEXT, PrereqCivic TEXT, Housing INTEGER,
    IsWonder BOOLEAN);
CREATE TABLE Building_YieldChanges (
    BuildingType TEXT NOT NULL, YieldType TEXT NOT NULL, YieldChange INTEGER,
    PRIMARY KEY (BuildingType, YieldType));
CREATE TABLE BuildingModifiers (
    BuildingType TEXT NOT NULL, ModifierId TEXT NOT NULL,
    PRIMARY KEY (BuildingType, ModifierId));
CREATE TABLE Modifiers (ModifierId TEXT NOT NULL PRIMARY KEY, ModifierType TEXT);
CREATE TABLE ModifierArguments (
    ModifierId TEXT NOT NULL, Name TEXT NOT NULL, Value TEXT,
    PRIMARY KEY (ModifierId, Name));
"""

ROWS = {
    "Buildings": [
        ("BUILDING_LIBRARY", "LOC_BUILDING_LIBRARY_NAME", 90, 1,
         "DISTRICT_CAMPUS", "TECH_WRITING", "", 0, 0),
        ("BUILDING_BANK", "LOC_BUILDING_BANK_NAME", 220, 2,
         "DISTRICT_COMMERCIAL_HUB", "TECH_BANKING", "", 0, 0),
        ("BUILDING_GREAT_LIBRARY", "LOC_BUILDING_GREAT_LIBRARY_NAME", 400, 0,
         "DISTRICT_CAMPUS", "TECH_RECORDED_HISTORY", "", 0, 1),
    ],
    "Building_YieldChanges": [
        ("BUILDING_LIBRARY", "YIELD_SCIENCE", 2),
        ("BUILDING_BANK", "YIELD_GOLD", 5),
    ],
    "BuildingModifiers": [
        ("BUILDING_GREAT_LIBRARY", "GREATLIBRARY_BOOST_SCIENTIST"),
    ],
    "Modifiers": [
        ("GREATLIBRARY_BOOST_SCIENTIST", "MODIFIER_PLAYER_GRANT_BOOST_WITH_GREAT_PERSON"),
    ],
    "ModifierArguments": [
        ("GREATLIBRARY_BOOST_SCIENTIST", "GreatPersonClass", "GREAT_PERSON_CLASS_SCIENTIST"),
        ("GREATLIBRARY_BOOST_SCIENTIST", "OtherPlayers", "1"),
        # The magnitude the database does not state: `1` is a flag meaning "apply the
        # standard tech boost", not a quantity of science. A test in Task 8 proves this
        # never reaches a player as a number.
        ("GREATLIBRARY_BOOST_SCIENTIST", "TechBoost", "1"),
    ],
}


SCHEMA += """
CREATE TABLE Districts (
    DistrictType TEXT NOT NULL PRIMARY KEY, Name TEXT, Cost INTEGER,
    PrereqTech TEXT, PrereqCivic TEXT);
CREATE TABLE Technologies (
    TechnologyType TEXT NOT NULL PRIMARY KEY, Name TEXT, Cost INTEGER, EraType TEXT);
CREATE TABLE TechnologyPrereqs (
    Technology TEXT NOT NULL, PrereqTech TEXT NOT NULL,
    PRIMARY KEY (Technology, PrereqTech));
CREATE TABLE Civics (
    CivicType TEXT NOT NULL PRIMARY KEY, Name TEXT, Cost INTEGER, EraType TEXT);
CREATE TABLE CivicPrereqs (
    Civic TEXT NOT NULL, PrereqCivic TEXT NOT NULL, PRIMARY KEY (Civic, PrereqCivic));
CREATE TABLE Boosts (
    BoostID INTEGER NOT NULL PRIMARY KEY, TechnologyType TEXT, CivicType TEXT,
    Boost INTEGER, BoostClass TEXT, Unit1Type TEXT, BuildingType TEXT,
    DistrictType TEXT, NumItems INTEGER);
CREATE TABLE Units (
    UnitType TEXT NOT NULL PRIMARY KEY, Name TEXT, Cost INTEGER, Maintenance INTEGER,
    Combat INTEGER, RangedCombat INTEGER, PrereqTech TEXT, PrereqCivic TEXT,
    StrategicResource TEXT);
CREATE TABLE UnitUpgrades (
    Unit TEXT NOT NULL PRIMARY KEY, UpgradeUnit TEXT NOT NULL);
"""

ROWS.update({
    "Districts": [("DISTRICT_CAMPUS", "LOC_DISTRICT_CAMPUS_NAME", 54, "TECH_WRITING", "")],
    "Technologies": [("TECH_WRITING", "LOC_TECH_WRITING_NAME", 50, "ERA_ANCIENT"),
                     ("TECH_POTTERY", "LOC_TECH_POTTERY_NAME", 25, "ERA_ANCIENT")],
    "TechnologyPrereqs": [("TECH_WRITING", "TECH_POTTERY")],
    "Civics": [("CIVIC_CODE_OF_LAWS", "LOC_CIVIC_CODE_OF_LAWS_NAME", 20, "ERA_ANCIENT"),
               ("CIVIC_STATE_WORKFORCE", "LOC_X", 70, "ERA_ANCIENT")],
    "CivicPrereqs": [("CIVIC_STATE_WORKFORCE", "CIVIC_CODE_OF_LAWS")],
    "Boosts": [(53, "TECH_WRITING", None, 40, "BOOST_TRIGGER_MEET_CIV",
                "UNIT_SCOUT", None, None, None),
               (4, None, "CIVIC_STATE_WORKFORCE", 40,
                "BOOST_TRIGGER_HAVE_X_UNIQUE_SPECIALTY_DISTRICTS", None, None, None, 1)],
    "Units": [("UNIT_WARRIOR", "LOC_UNIT_WARRIOR_NAME", 40, 0, 20, 0, "", "", ""),
              ("UNIT_SWORDSMAN", "LOC_UNIT_SWORDSMAN_NAME", 90, 2, 36, 0,
               "TECH_IRON_WORKING", "", "RESOURCE_IRON")],
    "UnitUpgrades": [("UNIT_WARRIOR", "UNIT_SWORDSMAN")],
})


def make_ruleset(tmp_path: Path, name: str = "DebugGameplay.sqlite",
                 rows: dict[str, list[tuple]] | None = None,
                 schema: str | None = None) -> Path:
    """Write a throwaway ruleset database and return its path.

    `rows` replaces whole tables, so a test can drop a column's value or a whole table to
    exercise degradation without editing this module.

    `schema` is resolved here rather than as a default argument, because Task 6 appends to
    `SCHEMA` after this function is defined and a default would have captured the old one.
    """
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / name
    schema = SCHEMA if schema is None else schema
    table_rows = {**ROWS, **(rows or {})}
    connection = sqlite3.connect(path)
    try:
        connection.executescript(schema)
        for table, values in table_rows.items():
            if not values:
                continue
            placeholders = ", ".join("?" * len(values[0]))
            connection.executemany(f"INSERT INTO {table} VALUES ({placeholders})", values)
        connection.commit()
    finally:
        connection.close()
    return path
