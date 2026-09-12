import pytest

from civ_advisor.advisors import ADVISORS, production
from civ_advisor.advisors.base import Provenance, Severity, humanize
from civ_advisor.advisors.checklist import ADVISOR_ORDER
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


def test_a_city_that_stopped_being_logged_drops_out_of_the_queues():
    """A captured, razed or no-longer-logged city must not contribute its last row for ever.

    The human's cutoff is latest_turn 21, so 20 is the oldest row that still counts.
    """
    s = game_state(turn=20)  # latest 21, complete 20
    s.build_queues = [
        build_queue_row(15, 0, "LOC_CITY_NAME_GONE", item="BUILDING_GRANARY"),
        build_queue_row(16, 0, "LOC_CITY_NAME_GONE", item="BUILDING_GRANARY"),
        build_queue_row(17, 0, "LOC_CITY_NAME_GONE", item="BUILDING_GRANARY"),
        build_queue_row(20, 0, "LOC_CITY_NAME_HELD", item="BUILDING_BRICKYARD"),
    ]
    assert [c.city for c in production.queues(s)[0]] == ["LOC_CITY_NAME_HELD"]
    why = ids(production.advise(s))["production.own_queue"].why
    assert "Held:" in why and "Gone" not in why


def test_a_stale_rival_city_does_not_count_toward_the_military_share():
    """Rivals are read at complete_through_turn 20, so 19 is the oldest row that still counts.

    Without the bound the turn-10 row makes it 2 of 4 cities (0.5) and the warning fires.
    """
    s = game_state(turn=20)
    s.build_queues = [
        build_queue_row(10, 1, "LOC_CITY_NAME_GONE", item="UNIT_WARRIOR"),
        build_queue_row(20, 1, "LOC_CITY_NAME_R0", item="UNIT_WARRIOR"),
        build_queue_row(20, 1, "LOC_CITY_NAME_R1", item="BUILDING_GRANARY"),
        build_queue_row(20, 1, "LOC_CITY_NAME_R2", item="BUILDING_GRANARY"),
    ]
    assert production.rival_military_share(s) == {1: pytest.approx(1 / 3)}
    assert "production.rival_military.1" not in ids(production.advise(s))


def test_the_latest_of_two_rows_for_the_same_city_and_turn_wins():
    s = game_state(turn=20)
    s.build_queues = [
        build_queue_row(21, 0, "LOC_CITY_NAME_A", item="BUILDING_GRANARY"),
        build_queue_row(21, 0, "LOC_CITY_NAME_A", item="BUILDING_BRICKYARD"),
    ]
    assert [c.item for c in production.queues(s)[0]] == ["BUILDING_BRICKYARD"]


def test_own_queue_insight_lists_every_city_and_is_fair():
    s = game_state(turn=20)
    s.build_queues = [
        build_queue_row(21, 0, "LOC_CITY_NAME_A", item="BUILDING_BRICKYARD", added=15.0, current=47.5, needed=55.0),
        build_queue_row(21, 0, "LOC_CITY_NAME_B", item="", added=8.0),
    ]
    i = ids(production.advise(s))["production.own_queue"]
    assert i.severity is Severity.INFO and i.provenance is Provenance.FAIR and i.advisor == "production"
    assert "A: Brickyard in 1 turn" in i.why and "B: idle" in i.why


def test_a_queue_that_completes_this_turn_says_so_rather_than_in_0_turns():
    s = game_state(turn=20)
    s.build_queues = [build_queue_row(21, 0, "LOC_CITY_NAME_A", item="BUILDING_BRICKYARD",
                                      added=10.0, current=50.0, needed=50.0)]
    why = ids(production.advise(s))["production.own_queue"].why
    assert "A: Brickyard finishing this turn" in why and "0 turns" not in why


@pytest.mark.parametrize("item,fires", [("BUILDING_BRICKYARD", True), ("BUILDING_GRANARY", False), ("BUILDING_ZIGGURAT", False)])
def test_mismatch_fires_only_when_every_item_is_known_and_none_serves_the_worst_gap(item, fires):
    s = game_state(turn=20, human_stats={"food": 8.0})  # food 8 vs rival 20 -> worst gap
    s.build_queues = [build_queue_row(21, 0, "LOC_CITY_NAME_A", item=item)]
    got = ids(production.advise(s))
    assert ("production.mismatch" in got) is fires
    if fires:
        i = got["production.mismatch"]
        assert i.provenance is Provenance.FAIR and i.advisor == "production"
        assert "food" in i.title
        # The queue row is turn 21, the economy comparison is turn 20; each clause says its own turn.
        assert "Brickyard as of turn 21" in i.why and "worst gap on turn 20" in i.why


def test_mismatch_silent_when_nothing_is_behind():
    s = game_state(turn=20)
    s.build_queues = [build_queue_row(21, 0, "LOC_CITY_NAME_A", item="BUILDING_BRICKYARD")]
    assert "production.mismatch" not in ids(production.advise(s))


def test_mismatch_dates_each_queue_row_when_city_updates_are_mixed():
    s = game_state(turn=20, human_stats={"food": 8.0})
    s.build_queues = [
        build_queue_row(20, 0, "LOC_CITY_NAME_A", item="BUILDING_BRICKYARD"),
        build_queue_row(21, 0, "LOC_CITY_NAME_B", item="BUILDING_SAWPIT"),
    ]
    why = ids(production.advise(s))["production.mismatch"].why
    assert "Brickyard as of turn 20" in why and "Sawpit as of turn 21" in why


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
        assert i.severity is Severity.WARN and i.provenance is Provenance.ORACLE
        assert i.advisor == "production" and "1 of Rival One's 2 cities" in i.why


def test_no_queues_means_no_insights():
    assert production.advise(game_state(turn=20)) == []


def test_rival_military_copy_dates_mixed_rows_and_pluralises_one_city():
    s = game_state(turn=20)
    s.build_queues = [build_queue_row(19, 1, "LOC_CITY_NAME_A", item="UNIT_WARRIOR")]
    why = ids(production.advise(s))["production.rival_military.1"].why
    assert "Turn 19" in why and "1 city is producing" in why

    s.build_queues.append(build_queue_row(20, 1, "LOC_CITY_NAME_B", item="UNIT_ARCHER"))
    why = ids(production.advise(s))["production.rival_military.1"].why
    assert "Queue rows from turns 19–20" in why and "2 cities are producing" in why


def test_production_is_registered():
    assert production in ADVISORS and ADVISOR_ORDER["production"] == 4


def test_the_reviewed_catalog_wins_over_the_unverified_yield_table():
    """One lookup for the whole codebase, so the decision layer and this advisor cannot
    disagree about what a building is for."""
    from civ_advisor.advisors import production

    assert production.item_yield("BUILDING_MONUMENT") == "culture"
    assert production.reviewed_yield("BUILDING_MONUMENT") is True
    # Covered only by the unverified fallback, and labelled as such.
    assert production.item_yield("BUILDING_BRICKYARD") == "production"
    assert production.reviewed_yield("BUILDING_BRICKYARD") is False
    assert production.item_yield("BUILDING_NOT_A_REAL_THING") is None


def test_a_mismatch_says_when_its_yield_association_is_only_a_heuristic():
    from civ_advisor.advisors import production
    from tests.factories import build_queue_row, game_state

    state = game_state(turn=20, rivals={1: "Rival"},
                       human_stats={"culture": 5.0}, rival_stats={1: {"culture": 40.0}})
    state.build_queues = [build_queue_row(state.latest_turn, 0, "LOC_CITY_NAME_A",
                                          "BUILDING_BRICKYARD")]
    mismatch = next(i for i in production.advise(state) if i.id == "production.mismatch")
    assert "No reviewed guide establishes what Brickyard serves" in mismatch.why
    assert "our own heuristic" in mismatch.why


def test_a_reviewed_item_carries_no_heuristic_caveat():
    from civ_advisor.advisors import production
    from tests.factories import build_queue_row, game_state

    state = game_state(turn=20, rivals={1: "Rival"},
                       human_stats={"science": 5.0}, rival_stats={1: {"science": 40.0}})
    state.build_queues = [build_queue_row(state.latest_turn, 0, "LOC_CITY_NAME_A",
                                          "BUILDING_MONUMENT")]
    mismatch = next(i for i in production.advise(state) if i.id == "production.mismatch")
    assert "heuristic" not in mismatch.why
