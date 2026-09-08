from pathlib import Path

import pytest

from civ7_advisor.ingest.csvfile import LogFormatError
from civ7_advisor.ingest.textlogs import DealItem, PlayerIdentityRow, read_deals, read_player_identities

# Captured live 2026-09-07 (verbatim lines).
LIVE_DEALS = (
    "Turn 79, Enacting Deal id 1 for player 4 and 7\n"
    ", Enacting Deal Item ID 2, from player 7, to player 4, type Peace, subType -751445167 (), value type , amount 0, duration 1\n"
    ", Enacting Deal Item ID 3, from player 7, to player 4, type Influence Large Lump (100), subType -858063716 (), value type , amount 100, duration 0\n"
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
        ", Enacting Deal Item ID 9, from player 1, to player 0, type Peace, subType 1 (), value type , amount 0, duration 1\n"
        "Some engine chatter that is not a deal\n"
        + LIVE_DEALS
    )
    assert [d.item_id for d in read_deals(p)] == [2, 3]


def test_a_turn_going_backwards_starts_a_new_game(tmp_path: Path):
    p = tmp_path / "DiplomacyDeals.log"
    p.write_text(
        LIVE_DEALS
        + "Turn 3, Enacting Deal id 2 for player 0 and 1\n"
        + ", Enacting Deal Item ID 1, from player 1, to player 0, type Open Borders, subType 5 (), value type , amount 0, duration 30\n"
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
        "Turn 79, Enacting Deal id 1 for player 4 and 7\n"
        ", from player 7, to player 4, Enacting Deal Item ID 2, type Peace, subType 1 (), value type , amount 0, duration 1\n"
    )
    with pytest.raises(LogFormatError, match="no item line parsed"):
        read_deals(p)


def test_a_file_of_only_chatter_is_not_a_format_change(tmp_path: Path):
    """No block header means nothing was expected: a deal-free game is legitimately empty."""
    p = tmp_path / "DiplomacyDeals.log"
    p.write_text("Some engine chatter that is not a deal\nAnd another line\n")
    assert read_deals(p) == []


def test_a_non_enacting_block_does_not_leak_into_the_previous_turn(tmp_path: Path):
    """Incoming Peace is a proposal and must never read as a concluded peace."""
    p = tmp_path / "DiplomacyDeals.log"
    p.write_text(
        "Turn 79, Enacting Deal id 1 for player 4 and 7\n"
        ", Enacting Deal Item ID 2, from player 7, to player 4, type Peace, subType 1 (), value type , amount 0, duration 1\n"
        "Turn 80, Incoming for player 0 and 4\n"
        ", Item ID 5, from player 0, to player 4, type Peace, subType 1 (), value type , amount 0, duration 1\n"
        "Turn 81, Enacting Deal id 2 for player 4 and 2\n"
        ", Enacting Deal Item ID 7, from player 2, to player 4, type Open Borders, subType 5 (), value type , amount 0, duration 30\n"
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


def test_a_non_enacting_block_still_advances_the_new_game_watermark(tmp_path: Path):
    """A block kind we do not read is still evidence of where the file has got to. If it did
    not advance the watermark, the turn drop that follows it would go unseen and game-1 deals
    would survive into game 2 — the false-peace direction."""
    p = tmp_path / "DiplomacyDeals.log"
    p.write_text(
        "Turn 79, Enacting Deal id 1 for player 4 and 7\n"
        ", Enacting Deal Item ID 2, from player 7, to player 4, type Peace, subType 1 (), value type , amount 0, duration 1\n"
        "Turn 200, Incoming for player 0 and 4\n"
        "Turn 100, Enacting Deal id 2 for player 4 and 2\n"
        ", Enacting Deal Item ID 7, from player 2, to player 4, type Open Borders, subType 5 (), value type , amount 0, duration 30\n"
    )
    assert read_deals(p) == [DealItem(100, 7, 2, 4, "Open Borders", 0, 30)]


def test_incoming_proposal_without_enacting_is_not_a_deal(tmp_path: Path):
    p = tmp_path / "DiplomacyDeals.log"
    p.write_text(
        "Turn 80, Incoming for player 0 and 4\n"
        ", Item ID 5, from player 0, to player 4, type Peace, subType 1 (), value type , amount 0, duration 1\n"
    )
    assert read_deals(p) == []


def test_gamecore_uses_last_resolved_identity_and_ignores_random(tmp_path: Path):
    p = tmp_path / "GameCore.log"
    p.write_text(
        "Player 1: Civilization - RANDOM (1)  Leader - RANDOM (1), - Level - CIVILIZATION_LEVEL_FULL_CIV, SlotStatus - AI\n"
        "Player 0: Civilization - CIVILIZATION_AMERICA (2)  Leader - LEADER_BENJAMIN_FRANKLIN (3), - Level - CIVILIZATION_LEVEL_FULL_CIV, SlotStatus - Human\n"
        "Player 1: Civilization - CIVILIZATION_PERSIA (4)  Leader - LEADER_XERXES (5), - Level - CIVILIZATION_LEVEL_FULL_CIV, SlotStatus - AI\n"
        "Player 1: Civilization - CIVILIZATION_PRUSSIA (6)  Leader - LEADER_AUGUSTUS (7), - Level - CIVILIZATION_LEVEL_FULL_CIV, SlotStatus - AI\n"
        "Player 8: Civilization - CIVILIZATION_PLACEHOLDER_CITYSTATE (8)  Leader - (null) (-1), - Level - CIVILIZATION_LEVEL_CITY_STATE, SlotStatus - AI\n"
    )
    assert read_player_identities(p) == [
        PlayerIdentityRow(0, 0, "CIVILIZATION_AMERICA", "LEADER_BENJAMIN_FRANKLIN", "CIVILIZATION_LEVEL_FULL_CIV", "Human"),
        PlayerIdentityRow(0, 1, "CIVILIZATION_PRUSSIA", "LEADER_AUGUSTUS", "CIVILIZATION_LEVEL_FULL_CIV", "AI"),
        PlayerIdentityRow(0, 8, "CIVILIZATION_PLACEHOLDER_CITYSTATE", None, "CIVILIZATION_LEVEL_CITY_STATE", "AI"),
    ]
