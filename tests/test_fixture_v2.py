from civ_advisor.advisors import intel, production, run_all, threat
from civ_advisor.ingest.events import read_combat_log, read_diplomacy_summary, read_gossip
from civ_advisor.games.civ7 import CIV7
from civ_advisor.ingest.load import load_logs
from civ_advisor.ingest.production import read_build_queue


def test_every_log_in_the_v2_fixture_parses(fixture_v2_dir):
    raw = load_logs(fixture_v2_dir)
    assert all(raw.files[n].ok for n in CIV7.log_files), {
        n: f.error for n, f in raw.files.items() if not f.ok
    }
    assert raw.build_queue and raw.combat and raw.gossip and raw.diplomacy_summary and raw.deals
    assert raw.unit_operations and raw.tactical and raw.operations and raw.combat_orders
    assert raw.operation_evals and raw.unit_efficiency and raw.mayhem and raw.commander_promotions
    assert len(raw.player_identities) == 8


def test_feed_production_and_advice_are_populated(fixture_v2_state):
    assert intel.feed(fixture_v2_state)
    assert fixture_v2_state.HUMAN in production.queues(fixture_v2_state)
    insights = run_all(fixture_v2_state)
    assert insights
    assert all(i.title.strip() and i.recommendation.strip() and i.why.strip() for i in insights)


def test_peace_and_war_are_never_asserted_together(fixture_v2_state):
    for rival in threat.summarize(fixture_v2_state):
        assert not (rival.at_war_since is not None and rival.peace_since is not None)


def test_human_gossip_resolves_to_player_zero(fixture_v2_state):
    names = fixture_v2_state.names
    assert names is not None and names.human_civ is not None
    human_rows = [
        g for g in fixture_v2_state.gossip
        if names.player_for(g.leader, g.civilization) == fixture_v2_state.HUMAN
    ]
    assert human_rows, "no gossip about the human resolved — check FACTS.md civ prefix vs Gossip Civilization"


def test_comma_bearing_napoleon_gossip_resolves_from_gamecore(fixture_v2_state):
    names = fixture_v2_state.names
    assert names is not None and names.player_for("Napoleon, Revolutionary", "French Empire") == 2
    assert fixture_v2_state.players[2].name == "Napoleon, Revolutionary"


def test_gossip_rows_are_anchored_across_every_observed_width(fixture_v2_dir):
    rows = read_gossip(fixture_v2_dir / "Game_Gossip.csv")
    assert len(rows) == 2703
    assert {r.type for r in rows}
    assert all(r.type.startswith("GOSSIP_") for r in rows)
    assert any(r.leader == "Napoleon, Revolutionary" for r in rows)
    assert any(r.detail and "," in r.detail for r in rows)


def test_diplomacy_summary_has_one_numeric_mayhem_cell(fixture_v2_dir):
    rows = read_diplomacy_summary(fixture_v2_dir / "DiplomacySummary.csv")
    assert all(r.mayhem is not None and r.mayhem >= 0 for r in rows)
    assert all(r.visibility is None for r in rows)


def test_combat_value_sets_and_destroyed_health_order_are_pinned(fixture_v2_dir):
    rows = read_combat_log(fixture_v2_dir / "CombatLog.csv")
    assert {r.source_type for r in rows} == {"Unit Heal", "Unit vs Army", "Unit vs Location", "Unit vs Unit"}
    assert {r.destroyed for r in rows} == {"Attacker", "Defender", "District", "N/A"}
    destroyed_health = [
        r.att_health_raw if r.destroyed == "Attacker" else r.def_health_raw
        for r in rows if r.destroyed in {"Attacker", "Defender"}
    ]
    assert destroyed_health and all(cell.startswith("(0)") for cell in destroyed_health)


def test_idle_build_queue_item_is_the_empty_string(fixture_v2_dir):
    rows = read_build_queue(fixture_v2_dir / "CityBuildQueue.csv")
    non_constructibles = {
        r.item for r in rows
        if not r.item.startswith(("BUILDING_", "UNIT_", "IMPROVEMENT_", "WONDER_"))
    }
    assert non_constructibles == {""}
