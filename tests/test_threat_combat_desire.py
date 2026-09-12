from civ_advisor.advisors import threat
from civ_advisor.advisors.base import Provenance, Severity
from tests.factories import game_state, military_row


def ids(insights):
    return {i.id: i for i in insights}


def _rising(turn: int, player: int, start: float, end: float):
    """A player's combat desire across the comparison window, start to end."""
    window = threat.COMBAT_DESIRE_TURNS
    return [military_row(turn - window + 1, player, start),
            military_row(turn, player, end)]


def test_no_military_rows_produce_no_insight_and_no_zero():
    """Civ VII logs nothing of the kind. Absence must stay absence."""
    s = game_state(turn=20)
    assert "threat.combat_desire.1" not in ids(threat.advise(s))
    assert threat.summarize(s)[0].combat_desire is None


def test_a_rising_top_ranked_rival_is_advised_and_oracle():
    s = game_state(turn=20, rivals={1: "Rival One", 2: "Rival Two"})
    s.military = (_rising(20, 1, 0.3, 2.5)
                  + [military_row(20, 2, 0.4), military_row(20, 0, 1.0)])
    got = ids(threat.advise(s))["threat.combat_desire.1"]

    assert got.severity is Severity.ADVISE
    assert got.provenance is Provenance.ORACLE
    assert "2.5" in got.why and "0.3" in got.why
    assert "turn 20" in got.why


def test_the_why_refuses_to_call_the_reading_calibrated():
    """The number has no established danger level, and the evidence must say so
    rather than let a reader infer one from the severity."""
    s = game_state(turn=20, rivals={1: "Rival One"})
    s.military = _rising(20, 1, 0.3, 2.5)
    why = ids(threat.advise(s))["threat.combat_desire.1"].why

    assert "relative" in why.lower() or "compared" in why.lower()
    assert "not a calibrated" in why.lower()


def test_a_rival_that_is_not_the_highest_is_reported_as_info():
    s = game_state(turn=20, rivals={1: "Rival One", 2: "Rival Two"})
    s.military = _rising(20, 1, 0.3, 2.5) + [military_row(20, 2, 4.0)]
    got = ids(threat.advise(s))

    assert got["threat.combat_desire.1"].severity is Severity.INFO
    assert "threat.combat_desire.2" not in got  # flat: nothing rose


def test_a_flat_reading_is_not_reported():
    """Reporting an unchanged low number every turn would be noise, and noise is
    what makes a real warning invisible."""
    s = game_state(turn=20, rivals={1: "Rival One"})
    s.military = [military_row(20 - threat.COMBAT_DESIRE_TURNS + 1, 1, 1.0),
                  military_row(20, 1, 1.0)]
    assert "threat.combat_desire.1" not in ids(threat.advise(s))


def test_a_reading_below_the_noise_floor_is_not_reported():
    s = game_state(turn=20, rivals={1: "Rival One"})
    s.military = _rising(20, 1, 0.0, threat.COMBAT_DESIRE_MIN - 0.1)
    assert "threat.combat_desire.1" not in ids(threat.advise(s))


def test_a_stale_reading_is_not_reported_as_current():
    """AI_Military lags the human by up to a turn, like the other AI logs. Older
    than that and the reading is not about now."""
    s = game_state(turn=20, rivals={1: "Rival One"})
    s.military = _rising(15, 1, 0.3, 2.5)
    got = threat.summarize(s)[0]

    assert got.combat_desire is None
    assert "threat.combat_desire.1" not in ids(threat.advise(s))


def test_a_gap_in_the_log_reports_the_priors_real_turn_not_the_constant():
    """The whole-phase review's Important: the prior reading is the newest row at or
    before the nominal COMBAT_DESIRE_TURNS boundary, which can be much older than that
    boundary when AI_Military has a gap. The evidence must quote the row it actually
    found, not assert the constant unconditionally."""
    s = game_state(turn=20, rivals={1: "Rival One"})
    # No row at turn 11 (20 - COMBAT_DESIRE_TURNS + 1): the newest row at or before it
    # is from turn 5, fifteen turns back, not ten.
    s.military = [military_row(5, 1, 0.3), military_row(20, 1, 2.5)]
    got = threat.summarize(s)[0]

    assert got.combat_desire_prior_turn == 5
    why = ids(threat.advise(s))["threat.combat_desire.1"].why
    assert "turn 5" in why
    assert f"{threat.COMBAT_DESIRE_TURNS} turns earlier" not in why


def test_the_signal_is_real_in_the_civ6_capture(civ6_dir):
    from civ_advisor.games.civ6 import CIV6
    from civ_advisor.ingest.load import load_logs
    from civ_advisor.state.build import build_state

    state = build_state(load_logs(civ6_dir, profile=CIV6))
    by_player = {r.player: r for r in threat.summarize(state)}

    assert by_player[2].combat_desire == 1.0        # Cyrus, turn 52
    assert by_player[2].combat_desire_turn == 52
    assert all(r.provenance is Provenance.ORACLE
               for r in threat.advise(state) if "combat_desire" in r.id)
