from pathlib import Path

from civ7_advisor.ingest.textlogs import DealItem, read_deals

# Captured live 2026-09-07 (verbatim lines).
LIVE_DEALS = (
    "Turn 79, Incoming for player 4 and 7\n"
    ", Item ID 2, from player 7, to player 4, type Peace, subType -751445167 (), value type , amount 0, duration 1\n"
    ", Item ID 3, from player 7, to player 4, type Influence Large Lump (100), subType -858063716 (), value type , amount 100, duration 0\n"
)


def test_reads_items_under_their_block_turn(tmp_path: Path):
    p = tmp_path / "DiplomacyDeals.log"
    p.write_text(LIVE_DEALS)
    assert read_deals(p) == [
        DealItem(79, 2, 7, 4, "Peace", 0, 1),
        DealItem(79, 3, 7, 4, "Influence Large Lump (100)", 100, 0),
    ]


def test_is_peace_and_parties():
    peace = DealItem(79, 2, 7, 4, "Peace", 0, 1)
    gold = DealItem(79, 3, 7, 4, "Influence Large Lump (100)", 100, 0)
    assert peace.is_peace and not gold.is_peace
    assert peace.parties() == frozenset({4, 7})


def test_unknown_lines_are_ignored_and_items_before_a_header_are_dropped(tmp_path: Path):
    p = tmp_path / "DiplomacyDeals.log"
    p.write_text(
        ", Item ID 9, from player 1, to player 0, type Peace, subType 1 (), value type , amount 0, duration 1\n"
        "Some engine chatter that is not a deal\n"
        + LIVE_DEALS
    )
    assert [d.item_id for d in read_deals(p)] == [2, 3]


def test_a_turn_going_backwards_starts_a_new_game(tmp_path: Path):
    p = tmp_path / "DiplomacyDeals.log"
    p.write_text(
        LIVE_DEALS
        + "Turn 3, Incoming for player 0 and 1\n"
        + ", Item ID 1, from player 1, to player 0, type Open Borders, subType 5 (), value type , amount 0, duration 30\n"
    )
    assert read_deals(p) == [DealItem(3, 1, 1, 0, "Open Borders", 0, 30)]


def test_empty_file_gives_no_deals(tmp_path: Path):
    p = tmp_path / "DiplomacyDeals.log"
    p.write_text("")
    assert read_deals(p) == []
