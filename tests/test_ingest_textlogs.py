from pathlib import Path

import pytest

from civ7_advisor.ingest.csvfile import LogFormatError
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


def test_a_block_whose_items_do_not_parse_is_a_format_change(tmp_path: Path):
    """Silence is the one failure mode this parser must not have: a renamed or reordered item
    line would otherwise read as `deals == []`, ok=True — a peaceful game."""
    p = tmp_path / "DiplomacyDeals.log"
    p.write_text(
        "Turn 79, Incoming for player 4 and 7\n"
        ", from player 7, to player 4, Item ID 2, type Peace, subType 1 (), value type , amount 0, duration 1\n"
    )
    with pytest.raises(LogFormatError, match="no item line parsed"):
        read_deals(p)


def test_a_file_of_only_chatter_is_not_a_format_change(tmp_path: Path):
    """No block header means nothing was expected: a deal-free game is legitimately empty."""
    p = tmp_path / "DiplomacyDeals.log"
    p.write_text("Some engine chatter that is not a deal\nAnd another line\n")
    assert read_deals(p) == []


def test_a_non_incoming_block_does_not_leak_into_the_previous_turn(tmp_path: Path):
    """`Incoming` implies a complementary block kind. Its items are not concluded incoming
    deals — an outgoing Peace is an offer, and must never read as a peace."""
    p = tmp_path / "DiplomacyDeals.log"
    p.write_text(
        "Turn 79, Incoming for player 4 and 7\n"
        ", Item ID 2, from player 7, to player 4, type Peace, subType 1 (), value type , amount 0, duration 1\n"
        "Turn 80, Outgoing for player 0 and 4\n"
        ", Item ID 5, from player 0, to player 4, type Peace, subType 1 (), value type , amount 0, duration 1\n"
        "Turn 81, Incoming for player 4 and 2\n"
        ", Item ID 7, from player 2, to player 4, type Open Borders, subType 5 (), value type , amount 0, duration 30\n"
    )
    assert read_deals(p) == [
        DealItem(79, 2, 7, 4, "Peace", 0, 1),
        DealItem(81, 7, 2, 4, "Open Borders", 0, 30),
    ]


def test_involves_is_membership_in_parties():
    peace = DealItem(79, 2, 7, 4, "Peace", 0, 1)
    assert peace.involves(7) and peace.involves(4) and not peace.involves(0)


def test_a_byte_order_mark_does_not_hide_the_first_header(tmp_path: Path):
    """The reader opens with `utf-8-sig`; a BOM must not stop the first header from matching."""
    p = tmp_path / "DiplomacyDeals.log"
    p.write_text(LIVE_DEALS, encoding="utf-8-sig")
    assert [d.turn for d in read_deals(p)] == [79, 79]
