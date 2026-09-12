import pytest

from civ_advisor.advisors import intel
from civ_advisor.advisors.base import Provenance
from civ_advisor.state.models import DealItem, GameState, Player, PlayerKind
from civ_advisor.state.names import NameResolver
from tests.factories import combat, deal, diplo_event, game_state, gossip_row


def _state():
    s = game_state(turn=20, rivals={1: "Ibn Battuta", 4: "José Rizal"})
    s.names = NameResolver.build({1: "Ibn Battuta", 4: "José Rizal"}, ["LOC_CITY_NAME_MAURYA1"])
    return s


def test_gossip_is_fair_and_resolves_names():
    s = _state()
    s.gossip = [gossip_row(20, "Alexander", "Maurya", "GOSSIP_UNIT_DESTROYED", 63, 31, "Warrior"),
                gossip_row(19, "Jose Rizal", "Maya", "GOSSIP_CITY_FOUNDED", -1, -1)]
    a, b = intel.feed(s)
    assert (a.kind, a.provenance, a.players, a.x, a.y) == ("gossip", Provenance.FAIR, (0,), 63, 31)
    assert a.text == "You: Unit Destroyed — Warrior"
    assert (b.players, b.x, b.y) == ((4,), None, None) and b.text.startswith("José Rizal: City Founded")


def test_unresolved_gossip_keeps_the_logged_name():
    s = _state()
    s.gossip = [gossip_row(20, "Napoleon", "France")]
    [e] = intel.feed(s)
    assert e.players == () and e.text.startswith("Napoleon (France):")


def test_diplomacy_combat_and_deals_follow_the_party_rule():
    s = _state()
    s.diplomacy_events = [diplo_event(20, 0, 1, "Diplomacy Action Started", details="Denounce"),
                          diplo_event(20, 1, 4, "Diplomacy Action Started", details="Denounce")]
    s.combats = [combat(20, 0, 4, destroyed="Attacker"), combat(20, 1, 4, destroyed="Defender")]
    s.deals = [deal(20, 4, 0, "Peace"), deal(20, 1, 4, "Open Borders")]
    by_text = {e.text: e for e in intel.feed(s)}
    assert by_text["You began Denounce against Ibn Battuta"].provenance is Provenance.FAIR
    assert by_text["Ibn Battuta began Denounce against José Rizal"].provenance is Provenance.ORACLE
    assert by_text["Your Warrior attacked José Rizal's Spearman — Warrior destroyed"].provenance is Provenance.FAIR
    assert by_text["Ibn Battuta's Warrior attacked José Rizal's Spearman — Spearman destroyed"].provenance is Provenance.ORACLE
    assert by_text["José Rizal → You: Peace"].provenance is Provenance.FAIR
    assert by_text["Ibn Battuta → José Rizal: Open Borders"].provenance is Provenance.ORACLE


def test_feed_is_newest_first_then_combat_deal_diplomacy_gossip():
    s = _state()
    s.gossip = [gossip_row(20, "Alexander", "Maurya")]
    s.deals = [deal(20, 4, 0)]
    s.combats = [combat(19, 0, 4), combat(20, 0, 4)]
    s.diplomacy_events = [diplo_event(20, 0, 1)]
    kinds = [(e.turn, e.kind) for e in intel.feed(s)]
    assert kinds == [(20, "combat"), (20, "deal"), (20, "diplomacy"), (20, "gossip"), (19, "combat")]


def test_empty_state_has_an_empty_feed():
    assert intel.feed(GameState()) == []


def _independent(s, pid):
    """Register a barbarian-camp-like player, the kind the real log meets by the dozen."""
    s.players[pid] = Player(pid, f"Independent {pid}", PlayerKind.INDEPENDENT, True, s.complete_through_turn)


def test_heal_ticks_against_the_no_player_sentinel_are_dropped():
    s = _state()
    s.combats = [combat(20, 0, -1, def_kind="N/A"), combat(20, 0, 4, destroyed="Defender")]
    events = intel.feed(s)
    assert [e.players for e in events] == [(0, 4)]
    assert not any("Player -1" in e.text or "N/A" in e.text for e in events)


def test_a_diplomacy_row_naming_the_no_player_sentinel_is_dropped():
    s = game_state(turn=20, rivals={1: "Ibn Battuta", 5: "Isabella"})
    s.diplomacy_events = [diplo_event(20, 5, 63, "Met")]
    assert intel.feed(s) == []


def test_independent_only_events_are_dropped_but_major_ones_are_kept():
    s = _state()
    _independent(s, 8)
    _independent(s, 9)
    s.diplomacy_events = [diplo_event(20, 8, 9, "Met"), diplo_event(20, 1, 8, "At War")]
    s.combats = [combat(20, 8, 0)]
    assert [(e.kind, e.players, e.provenance) for e in intel.feed(s)] == [
        ("combat", (8, 0), Provenance.FAIR), ("diplomacy", (1, 8), Provenance.ORACLE)]


def test_a_deal_logged_from_both_sides_is_shown_once():
    s = _state()
    s.deals = [deal(20, 4, 0), deal(20, 4, 0)]
    assert [e.text for e in intel.feed(s)] == ["José Rizal → You: Peace"]


def test_two_deals_that_differ_in_item_id_both_appear():
    s = _state()
    s.deals = [DealItem(20, 1, 4, 0, "Peace", 0, 1), DealItem(20, 2, 4, 0, "Peace", 0, 1)]
    assert len(intel.feed(s)) == 2


def test_a_meeting_is_shown_once_per_pair():
    s = _state()
    s.diplomacy_events = [diplo_event(20, 1, 4, "Met"), diplo_event(20, 4, 1, "Met")]
    [e] = intel.feed(s)
    assert e.text == "Ibn Battuta and José Rizal have met"


def test_every_other_action_stays_directional():
    s = _state()
    s.diplomacy_events = [diplo_event(20, 1, 4, "Diplomacy Action Started", details="Denounce"),
                          diplo_event(20, 4, 1, "Diplomacy Action Started", details="Denounce")]
    assert sorted(e.text for e in intel.feed(s)) == [
        "Ibn Battuta began Denounce against José Rizal",
        "José Rizal began Denounce against Ibn Battuta",
    ]


def test_gossip_without_a_name_resolver_keeps_the_logged_name():
    s = _state()
    s.names = None
    s.gossip = [gossip_row(20, "Alexander", "Maurya", "GOSSIP_CITY_FOUNDED")]
    [e] = intel.feed(s)
    assert e.players == () and e.text == "Alexander (Maurya): City Founded"


def test_diplomacy_details_are_appended():
    s = _state()
    s.diplomacy_events = [diplo_event(20, 0, 1, "Diplomacy Action Ended", details="Open Markets result: Success")]
    [e] = intel.feed(s)
    # The log's own vocabulary, read into a sentence; its wording is kept in `raw`.
    assert e.text == "Your Open Markets against Ibn Battuta finished and it succeeded"
    assert e.raw == "Diplomacy Action Ended — Open Markets result: Success"
    assert e.event_type == "diplomacy.action" and e.recognised is True


@pytest.mark.parametrize("destroyed, outcome", [("Attacker", "Warrior destroyed"),
                                                ("Defender", "Spearman destroyed"),
                                                ("District", "no unit destroyed"),
                                                ("N/A", "no unit destroyed"),
                                                (None, "no unit destroyed")])
def test_combat_outcome_names_a_unit_only_when_one_died(destroyed, outcome):
    s = _state()
    s.combats = [combat(20, 0, 4, destroyed=destroyed)]
    [e] = intel.feed(s)
    assert e.text == f"Your Warrior attacked José Rizal's Spearman — {outcome}"


def test_gossip_coordinates_are_both_axes_or_neither():
    s = _state()
    s.gossip = [gossip_row(20, "Alexander", "Maurya", x=-1, y=5)]
    [e] = intel.feed(s)
    assert (e.x, e.y) == (None, None)


def _staged(turn, initiator, recipient, action, details):
    return diplo_event(turn, initiator, recipient, action, details=details)


def test_one_actions_stages_become_one_event_with_the_rows_it_covers():
    s = _state()
    s.diplomacy_events = [
        _staged(10, 0, 1, "Diplomacy Action Started", "Cultural Exchange"),
        _staged(12, 0, 1, "Diplomacy Action Enter Stage",
                "Cultural Exchange Entering Stage DIPLOMACY_CULTURAL_EXCHANGE_COMPLETE"),
        _staged(14, 0, 1, "Diplomacy Action Ended", "Cultural Exchange result: Success"),
    ]
    [event] = intel.feed(s)
    assert event.stages == 3 and event.first_turn == 10 and event.turn == 14
    assert "finished and it succeeded" in event.text
    assert "recorded over 3 log rows, followed from turn 10" in event.text
    # The rows themselves are retained, so the evidence view can show what was written.
    assert event.raw.count("|") == 2 and "Entering Stage" in event.raw


def test_two_runs_of_the_same_action_stay_two_events():
    """The log's `Ended` row closes an occurrence. Merging across it would report two
    agreements seventy turns apart as one."""
    s = _state()
    s.diplomacy_events = [
        _staged(10, 0, 1, "Diplomacy Action Started", "Open Markets"),
        _staged(14, 0, 1, "Diplomacy Action Ended", "Open Markets result: Success"),
        _staged(80, 0, 1, "Diplomacy Action Started", "Open Markets"),
        _staged(84, 0, 1, "Diplomacy Action Ended", "Open Markets result: Canceled"),
    ]
    events = sorted(intel.feed(s), key=lambda e: e.turn)
    assert [(e.first_turn, e.turn, e.stages) for e in events] == [(10, 14, 2), (80, 84, 2)]
    assert "succeeded" in events[0].text and "cancelled" in events[1].text


def test_an_unfinished_action_is_reported_as_still_running():
    s = _state()
    s.diplomacy_events = [
        _staged(10, 0, 1, "Diplomacy Action Started", "Denounce"),
        _staged(12, 0, 1, "Diplomacy Action Support Changed",
                "Denounce - P 1 increased support by 1"),
    ]
    [event] = intel.feed(s)
    assert event.stages == 2 and "finished" not in event.text
    assert "increased support by 1" in event.text


def test_stages_of_different_actions_are_never_merged():
    s = _state()
    s.diplomacy_events = [
        _staged(10, 0, 1, "Diplomacy Action Started", "Denounce"),
        _staged(10, 0, 1, "Diplomacy Action Started", "Open Markets"),
    ]
    assert len(intel.feed(s)) == 2


def test_the_feed_can_be_filtered_by_player_and_by_event_type():
    s = _state()
    s.diplomacy_events = [
        diplo_event(20, 0, 1, "Met"),
        diplo_event(20, 1, 4, "Met"),
        _staged(20, 1, 4, "Diplomacy Action Ended", "Denounce result: Success"),
    ]
    events = intel.feed(s)
    assert "diplomacy.met" in intel.event_types(events)
    assert "diplomacy.action" in intel.event_types(events)
    mine = intel.filter_events(events, player=0)
    assert len(mine) == 1 and 0 in mine[0].players
    actions = intel.filter_events(events, event_type="diplomacy.action")
    assert len(actions) == 1 and actions[0].event_type == "diplomacy.action"
    assert intel.filter_events(events, player=4, event_type="diplomacy.met")


def test_every_kind_of_event_carries_the_logs_own_wording():
    s = _state()
    s.diplomacy_events = [diplo_event(20, 0, 1, "Met")]
    s.gossip = [gossip_row(20, "Ibn Battuta", "Abbasid", "GOSSIP_FOUND_CITY", detail="Baghdad")]
    s.combats = [combat(20, 0, 1, "Defender")]
    s.deals = [deal(20, 0, 1)]
    for event in intel.feed(s):
        assert event.raw, event
        assert event.event_type, event
