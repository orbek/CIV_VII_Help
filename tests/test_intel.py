from civ7_advisor.advisors import intel
from civ7_advisor.advisors.base import Provenance
from civ7_advisor.state.models import GameState
from civ7_advisor.state.names import NameResolver
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
    s.diplomacy_events = [diplo_event(20, 0, 1, "Denounce"), diplo_event(20, 1, 4, "Denounce")]
    s.combats = [combat(20, 0, 4, destroyed="Attacker"), combat(20, 1, 4, destroyed="Defender")]
    s.deals = [deal(20, 4, 0, "Peace"), deal(20, 1, 4, "Open Borders")]
    by_text = {e.text: e for e in intel.feed(s)}
    assert by_text["You → Ibn Battuta: Denounce"].provenance is Provenance.FAIR
    assert by_text["Ibn Battuta → José Rizal: Denounce"].provenance is Provenance.ORACLE
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
