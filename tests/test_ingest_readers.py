from pathlib import Path

import pytest

from civ7_advisor.ingest.csvfile import LogFormatError
from civ7_advisor.ingest.readers import (
    HappinessRow,
    TreasuryRow,
    VictoryRow,
    canonical_strategy,
    read_happiness,
    read_treasury,
    read_victories,
)


def test_treasury_fixture(fixture_dir: Path):
    rows = read_treasury(fixture_dir / "Player_Treasury.csv")
    assert len(rows) == 2523
    assert rows[-1] == TreasuryRow(
        turn=82, player=0, gold_balance=136.0, unit_maintenance=2,
        building_maintenance=2, total_maintenance=4, gold_yield=23.0,
    )


def test_treasury_header_mismatch_raises(tmp_path: Path):
    p = tmp_path / "Player_Treasury.csv"
    p.write_text("Turn, Player, Something Else\n1, 0, 3\n")
    with pytest.raises(LogFormatError, match="unexpected header"):
        read_treasury(p)


def test_happiness_fixture_covers_only_major_players(fixture_dir: Path):
    rows = read_happiness(fixture_dir / "Player_Happiness.csv")
    assert len(rows) == 646
    assert {r.player for r in rows} == set(range(8))
    assert rows[-1] == HappinessRow(
        turn=82, player=0, golden_age=False, threshold=1532, total=1058, per_turn=20, bonus=0,
    )
    assert any(r.golden_age for r in rows)  # the fixture has 102 "Yes" rows


def test_canonical_strategy_takes_last_segment():
    assert canonical_strategy("CD_VICTORY_STRATEGY_SCIENCE") == "SCIENCE"
    assert canonical_strategy("TRIUMPH_STRATEGY_ALLAGES_ESPIONAGE") == "ESPIONAGE"


def test_victories_fixture_is_event_based_with_canonical_strategies(fixture_dir: Path):
    rows = read_victories(fixture_dir / "AI_Victories.csv")
    assert len(rows) == 77
    assert rows[0] == VictoryRow(
        turn=1, player=1, owner_key="LOC_LEADER_IBN_BATTUTA_NAME",
        strategy="MILITARY", status="Following", weight=39,
    )
    assert {r.strategy for r in rows} == {"MILITARY", "SCIENCE", "CULTURAL", "ECONOMIC", "ESPIONAGE"}
    assert {r.status for r in rows} == {"Following", "Stopped", "Forbidden"}
    assert rows[-1] == VictoryRow(
        turn=80, player=1, owner_key="LOC_LEADER_IBN_BATTUTA_NAME",
        strategy="CULTURAL", status="Stopped", weight=0,
    )
