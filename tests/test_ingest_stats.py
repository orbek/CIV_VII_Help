from pathlib import Path

import pytest

from civ7_advisor.ingest.csvfile import LogFormatError, latest_game_segment, read_table
from civ7_advisor.ingest.readers import read_player_stats


def test_read_table_strips_cells_and_skips_blank_lines(tmp_path: Path):
    p = tmp_path / "t.csv"
    p.write_text("A, B\n1,  2.0\n\n3, 4\n")
    table = read_table(p)
    assert table.header == ["A", "B"]
    assert table.rows == [["1", "2.0"], ["3", "4"]]


def test_read_table_empty_file_raises(tmp_path: Path):
    p = tmp_path / "t.csv"
    p.write_text("")
    with pytest.raises(LogFormatError):
        read_table(p)


def test_read_table_strips_a_utf8_bom(tmp_path: Path):
    """Civ VII writes some logs with a BOM; it must not stick to the first header cell."""
    p = tmp_path / "t.csv"
    p.write_text("Turn, Player\n1, 0\n", encoding="utf-8-sig")
    assert read_table(p).header == ["Turn", "Player"]


def test_latest_game_segment_keeps_rows_after_last_turn_drop():
    rows = [["1", "a"], ["2", "a"], ["3", "a"], ["1", "b"], ["2", "b"]]
    assert latest_game_segment(rows, turn_col=0) == [["1", "b"], ["2", "b"]]


def test_latest_game_segment_single_game_is_unchanged():
    rows = [["1", "a"], ["1", "b"], ["2", "a"]]
    assert latest_game_segment(rows, turn_col=0) == rows


def test_player_stats_fixture_row_count(fixture_dir: Path):
    rows = read_player_stats(fixture_dir / "Player_Stats.csv")
    assert len(rows) == 2523


def test_player_stats_last_row_matches_verified_values(fixture_dir: Path):
    last = read_player_stats(fixture_dir / "Player_Stats.csv")[-1]
    assert (last.turn, last.player) == (82, 0)
    assert (last.cities, last.towns, last.settlement_cap, last.settlements_over_cap) == (1, 1, 4, 0)
    assert (last.urban_pop, last.rural_pop, last.techs) == (6, 12, 9)
    assert (last.land_units, last.naval_units) == (4, 0)
    assert (last.tiles_owned, last.tiles_improved) == (47, 12)
    assert last.gold_balance == 136.0  # cross-checked against Player_Treasury "Gold Balance"
    assert last.science == 15.0
    assert last.culture == 14.0
    assert last.gold == 23.0  # cross-checked against Player_Treasury "Gold Yield"
    assert last.production == 24.0
    assert last.food == 24.0
    assert last.happiness == 20.0  # cross-checked against Player_Happiness "Per Turn Happiness"
    assert last.diplomacy == 10.0


def test_player_stats_wrong_column_count_raises(tmp_path: Path, fixture_dir: Path):
    header = (fixture_dir / "Player_Stats.csv").read_text().splitlines()[0]
    bad = tmp_path / "Player_Stats.csv"
    bad.write_text(header + "\n" + ", ".join(["1"] * 24) + "\n")
    with pytest.raises(LogFormatError, match="expected 25 columns"):
        read_player_stats(bad)


def test_player_stats_returns_only_the_latest_game(tmp_path: Path, fixture_dir: Path):
    """The reader must drop everything before the last turn drop, not just parse rows.

    The fixture is a single game, so this builds a two-game log from it: turns
    1-3 as the first game, then the real turn-1 rows appended as a second game.
    """
    lines = (fixture_dir / "Player_Stats.csv").read_text().splitlines()
    header, body = lines[0], lines[1:]
    first_game = [ln for ln in body if ln.split(",", 1)[0].strip() in {"1", "2", "3"}]
    second_game = [ln for ln in body if ln.split(",", 1)[0].strip() == "1"]
    assert len(first_game) > len(second_game)  # the two games really do differ in size
    p = tmp_path / "Player_Stats.csv"
    p.write_text("\n".join([header, *first_game, *second_game]) + "\n")

    rows = read_player_stats(p)

    assert [(r.turn, r.player) for r in rows] == [
        (1, int(ln.split(",")[1])) for ln in second_game
    ]
