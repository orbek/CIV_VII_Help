from pathlib import Path

import pytest

from civ_advisor.ingest.csvfile import LogFormatError
from civ_advisor.ingest.production import BuildQueueRow, read_build_queue

HEADER = "Game Turn, Player, City, Production Added, Current Item, Current Production, Production Needed, Overflow\n"
# Captured from the live game on 2026-09-07 (turn 82, the human's capital building a Brickyard).
LIVE_ROW = "82, 0, LOC_CITY_NAME_MAURYA1, 15.0, BUILDING_BRICKYARD, 47.5, 55, 0.0\n"


def _write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "CityBuildQueue.csv"
    p.write_text(HEADER + body)
    return p


def test_reads_the_live_row_verbatim(tmp_path: Path):
    rows = read_build_queue(_write(tmp_path, LIVE_ROW))
    assert rows == [BuildQueueRow(82, 0, "LOC_CITY_NAME_MAURYA1", 15.0, "BUILDING_BRICKYARD", 47.5, 55.0, 0.0)]


@pytest.mark.parametrize(
    "added,current,needed,expected",
    [(15.0, 47.5, 55.0, 1), (15.0, 40.0, 55.0, 1), (15.0, 39.9, 55.0, 2), (15.0, 55.0, 55.0, 0),
     (15.0, 60.0, 55.0, 0), (0.0, 10.0, 55.0, None)],
)
def test_turns_to_complete_rounds_up_and_handles_stalls(added, current, needed, expected):
    row = BuildQueueRow(1, 0, "LOC_CITY_NAME_X", added, "BUILDING_BRICKYARD", current, needed, 0.0)
    assert row.turns_to_complete == expected


def test_idle_city_has_no_completion_estimate():
    row = BuildQueueRow(1, 0, "LOC_CITY_NAME_X", 12.0, "", 0.0, 0.0, 0.0)
    assert row.turns_to_complete is None


def test_header_mismatch_raises(tmp_path: Path):
    p = tmp_path / "CityBuildQueue.csv"
    p.write_text("Game Turn, Player, City\n1, 0, X\n")
    with pytest.raises(LogFormatError, match="unexpected header"):
        read_build_queue(p)


def test_only_latest_game_is_returned(tmp_path: Path):
    body = ("1, 0, LOC_CITY_NAME_A, 5.0, UNIT_WARRIOR, 0.0, 30, 0.0\n"
            "2, 0, LOC_CITY_NAME_A, 5.0, UNIT_WARRIOR, 5.0, 30, 0.0\n"
            "1, 0, LOC_CITY_NAME_B, 6.0, UNIT_SCOUT, 0.0, 20, 0.0\n")
    rows = read_build_queue(_write(tmp_path, body))
    assert [r.city for r in rows] == ["LOC_CITY_NAME_B"]
