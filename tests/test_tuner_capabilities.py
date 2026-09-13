"""A tuner-backed capability is live only when the socket answered."""
from civ_advisor.api.serialize import capability_report
from civ_advisor.games.base import Capability
from civ_advisor.games.civ6 import CIV6, TUNER_BACKED
from civ_advisor.games.civ7 import CIV7
from civ_advisor.tuner.base import NullTuner, TUNER_OFF, TunerUnavailable


def test_civ6_declares_the_tuner_backed_capabilities():
    assert CIV6.tuner_backed == TUNER_BACKED


def test_civ7_declares_none():
    """No claim is made that Civ VII has an equivalent socket. It was never tested."""
    assert CIV7.tuner_backed == frozenset()


def test_a_tuner_backed_capability_is_not_unconditionally_supported():
    for cap in TUNER_BACKED:
        assert cap not in CIV6.capabilities


def test_with_no_tuner_the_reason_tells_the_player_what_to_change():
    report = capability_report(CIV6, tuner=TUNER_OFF)
    assert report["happiness"]["supported"] is False
    assert "EnableTuner" in report["happiness"]["reason"]


def test_with_a_live_tuner_the_capability_is_supported():
    class Live:
        available = True
        reason = None
        unavailable = None
        def reading(self): return None
        def amenities(self): return ()
        def maintenance(self): return None
        def build_options(self): return ()

    report = capability_report(CIV6, tuner=Live())
    assert report["happiness"]["supported"] is True
    assert report["maintenance"]["supported"] is True


def test_an_unreachable_figure_says_so_rather_than_blaming_the_setting():
    null = NullTuner(TunerUnavailable.UNREACHABLE, "the game implements no such call")
    report = capability_report(CIV6, tuner=null)
    assert report["happiness"]["supported"] is False
    assert "EnableTuner" not in report["happiness"]["reason"]


def test_omitting_the_tuner_keeps_the_old_behaviour():
    """Civ VII and every existing caller must be unaffected."""
    report = capability_report(CIV7)
    assert report["victory_paths"]["supported"] is True


def test_a_tuner_backed_capability_never_reports_supported_with_no_reason():
    report = capability_report(CIV6, tuner=TUNER_OFF)
    for cap in TUNER_BACKED:
        entry = report[cap.value]
        assert entry["supported"] is False and entry["reason"]
