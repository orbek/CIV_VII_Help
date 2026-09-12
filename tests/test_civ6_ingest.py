from civ_advisor.games.base import Capability
from civ_advisor.games.civ6 import CIV6
from civ_advisor.ingest.load import load_logs


def test_civ6_is_registered_by_importing_the_games_package():
    import civ_advisor.games  # noqa: F401
    from civ_advisor.games.registry import get_profile, profile_ids

    assert "civ6" in profile_ids()
    assert get_profile("civ6") is CIV6


def test_civ6_declares_only_what_its_logs_can_support():
    """Civ VI's AI_Victories holds era strategies, not victory paths (spec
    §3.2), and it logs no amenities, maintenance or deals."""
    assert not CIV6.supports(Capability.VICTORY_PATHS)
    assert not CIV6.supports(Capability.HAPPINESS)
    assert not CIV6.supports(Capability.MAINTENANCE)
    assert not CIV6.supports(Capability.PEACE_DEALS)
    assert not CIV6.supports(Capability.COMBAT_ODDS)
    assert CIV6.supports(Capability.FAITH)
    assert CIV6.supports(Capability.CIVICS)


def test_civ6_does_not_declare_ai_victories():
    """Declaring it would populate GameState.strategies with era postures the
    victory advisor would report as victory pursuit."""
    assert "AI_Victories.csv" not in CIV6.log_files


def test_the_shared_readers_parse_the_civ6_capture(civ6_dir):
    raw = load_logs(civ6_dir, profile=CIV6)
    for name in ("DiplomacySummary.csv", "AI_Tactical.csv", "AI_Operation.csv",
                 "AI_MayhemTracker.csv", "AI_UnitEfficiency.csv", "GameCore.log"):
        status = raw.files[name]
        assert status.ok, f"{name}: {status.error}"
        assert status.rows > 0, f"{name} parsed but is empty"


def test_civ6_identities_come_from_the_shared_gamecore_reader(civ6_dir):
    """Verified against the capture: 6 majors, human at 0, Free Cities at 62."""
    raw = load_logs(civ6_dir, profile=CIV6)
    by_player = {r.player: r for r in raw.player_identities}

    assert by_player[0].civilization == "CIVILIZATION_ROME"
    assert by_player[0].leader == "LEADER_JULIUS_CAESAR"
    assert by_player[0].slot_status == "Human"
    assert by_player[1].civilization == "CIVILIZATION_SCOTLAND"
    majors = [r for r in raw.player_identities
              if r.level == "CIVILIZATION_LEVEL_FULL_CIV"]
    assert len(majors) == 6
    assert by_player[62].level == "CIVILIZATION_LEVEL_FREE_CITIES"
