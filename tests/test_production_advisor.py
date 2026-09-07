import pytest

from civ7_advisor.advisors import ADVISORS, production
from civ7_advisor.advisors.base import Provenance, Severity, humanize
from civ7_advisor.advisors.checklist import ADVISOR_ORDER
from tests.factories import build_queue_row, game_state


def ids(insights):
    return {i.id: i for i in insights}


def test_humanize_strips_game_key_decoration():
    assert humanize("LOC_DISTRICT_CITY_CENTER_NAME") == "City Center"
    assert humanize("UNIT_WARRIOR") == "Warrior"
    assert humanize("BUILDING_BRICKYARD") == "Brickyard"
    assert humanize("GOSSIP_UNIT_DESTROYED") == "Unit Destroyed"
    assert humanize("") == ""


@pytest.mark.parametrize("item,expected", [
    ("UNIT_WARRIOR", True), ("UNIT_ARMY_COMMANDER", True), ("UNIT_SCOUT", False),
    ("UNIT_SETTLER", False), ("UNIT_GREAT_MERCHANT", False), ("BUILDING_BRICKYARD", False), ("", False),
])
def test_is_military(item, expected):
    assert production.is_military(item) is expected


def test_queues_use_the_human_live_turn_but_rivals_complete_turn():
    s = game_state(turn=20)  # latest 21, complete 20
    s.build_queues = [
        build_queue_row(20, 0, "LOC_CITY_NAME_A", item="BUILDING_GRANARY"),
        build_queue_row(21, 0, "LOC_CITY_NAME_A", item="BUILDING_BRICKYARD", added=15.0, current=47.5, needed=55.0),
        build_queue_row(20, 1, "LOC_CITY_NAME_B", item="UNIT_WARRIOR"),
        build_queue_row(21, 1, "LOC_CITY_NAME_B", item="UNIT_ARCHER"),
    ]
    q = production.queues(s)
    assert [c.item for c in q[0]] == ["BUILDING_BRICKYARD"] and q[0][0].turns_to_complete == 1
    assert [c.item for c in q[1]] == ["UNIT_WARRIOR"]


def test_own_queue_insight_lists_every_city_and_is_fair():
    s = game_state(turn=20)
    s.build_queues = [
        build_queue_row(21, 0, "LOC_CITY_NAME_A", item="BUILDING_BRICKYARD", added=15.0, current=47.5, needed=55.0),
        build_queue_row(21, 0, "LOC_CITY_NAME_B", item="", added=8.0),
    ]
    i = ids(production.advise(s))["production.own_queue"]
    assert i.severity is Severity.INFO and i.provenance is Provenance.FAIR and i.advisor == "production"
    assert "A: Brickyard in 1 turn" in i.why and "B: idle" in i.why


@pytest.mark.parametrize("item,fires", [("BUILDING_BRICKYARD", True), ("BUILDING_GRANARY", False), ("BUILDING_ZIGGURAT", False)])
def test_mismatch_fires_only_when_every_item_is_known_and_none_serves_the_worst_gap(item, fires):
    s = game_state(turn=20, human_stats={"food": 8.0})  # food 8 vs rival 20 -> worst gap
    s.build_queues = [build_queue_row(21, 0, "LOC_CITY_NAME_A", item=item)]
    got = ids(production.advise(s))
    assert ("production.mismatch" in got) is fires
    if fires:
        assert got["production.mismatch"].provenance is Provenance.FAIR
        assert "food" in got["production.mismatch"].title and "Brickyard" in got["production.mismatch"].why


def test_mismatch_silent_when_nothing_is_behind():
    s = game_state(turn=20)
    s.build_queues = [build_queue_row(21, 0, "LOC_CITY_NAME_A", item="BUILDING_BRICKYARD")]
    assert "production.mismatch" not in ids(production.advise(s))


@pytest.mark.parametrize("items,fires", [
    (["UNIT_WARRIOR", "BUILDING_GRANARY"], True),            # 1/2 = 0.5, at the threshold
    (["UNIT_WARRIOR", "BUILDING_GRANARY", "BUILDING_X"], False),  # 1/3
    (["UNIT_SCOUT", "UNIT_SETTLER"], False),                 # civilians never count
])
def test_rival_military_share_threshold(items, fires):
    s = game_state(turn=20)
    s.build_queues = [build_queue_row(20, 1, f"LOC_CITY_NAME_R{n}", item=it) for n, it in enumerate(items)]
    got = ids(production.advise(s))
    assert ("production.rival_military.1" in got) is fires
    if fires:
        i = got["production.rival_military.1"]
        assert i.severity is Severity.WARN and i.provenance is Provenance.ORACLE and "1 of Rival One's 2 cities" in i.why


def test_no_queues_means_no_insights():
    assert production.advise(game_state(turn=20)) == []


def test_production_is_registered():
    assert production in ADVISORS and ADVISOR_ORDER["production"] == 3
