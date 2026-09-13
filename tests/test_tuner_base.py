"""What a tuner reading is allowed to be, and what absence looks like."""
import subprocess
import sys

import pytest

from civ_advisor.tuner.base import (
    BuildOption, CityAmenities, Maintenance, NullTuner, SettlementOptions,
    TUNER_OFF, TunerProvider, TunerReading, TunerUnavailable,
)


def test_a_reading_records_both_the_turn_and_the_moment_it_was_asked():
    """Unlike a log row, a reading is something we asked for at a time we chose."""
    r = TunerReading(turn=59, read_at="2026-09-13T10:40:00Z", state="GameCore_Tuner")
    assert r.turn == 59
    assert r.read_at == "2026-09-13T10:40:00Z"


def test_a_reading_must_name_the_vm_it_came_from():
    with pytest.raises(ValueError, match="state"):
        TunerReading(turn=59, read_at="2026-09-13T10:40:00Z", state="")


def test_war_weariness_is_accepted_and_reported_not_rejected():
    """A city at war names more positive sources than its total. That is real."""
    c = CityAmenities(city="Rome", total=4, from_luxuries=3, from_civics=0,
                      from_entertainment=2, housing=9, food_surplus=1)
    assert c.unexplained == -1


def test_net_gold_is_yield_minus_maintenance():
    m = Maintenance(total=1, buildings=0, districts=1, units=0, gold=152, gold_yield=8)
    assert m.net_gold == 7


def test_upkeep_the_breakdown_does_not_explain_is_reported_not_rejected():
    """The three queried categories are not known to be exhaustive."""
    m = Maintenance(total=9, buildings=0, districts=1, units=0, gold=152, gold_yield=8)
    assert m.unattributed == 8


def test_a_build_option_carries_its_own_completion_estimate():
    o = BuildOption(item="BUILDING_GRANARY", turns=8)
    assert o.turns == 8


def test_a_build_option_rejects_a_negative_estimate():
    with pytest.raises(ValueError, match="turns"):
        BuildOption(item="BUILDING_GRANARY", turns=-1)


def test_a_settlement_offering_nothing_is_different_from_not_being_asked():
    """An empty offer list is a fact. `None` would be an absence of one."""
    s = SettlementOptions(city="Puteoli", options=())
    assert s.options == ()
    assert s.offers("BUILDING_GRANARY") is None


def test_null_tuner_answers_every_question_with_its_reason():
    null = NullTuner(TunerUnavailable.NOT_ENABLED, "EnableTuner is 0 in AppOptions.txt")
    assert null.available is False
    assert null.amenities() == ()
    assert null.maintenance() is None
    assert null.build_options() == ()
    assert "EnableTuner" in null.reason


def test_the_off_singleton_says_which_absence_it_is():
    assert TUNER_OFF.unavailable is TunerUnavailable.NOT_ENABLED


def test_the_three_absences_are_distinct():
    """Told apart on purpose: only one of them is fixable by the player."""
    assert len(set(TunerUnavailable)) == 3


def test_null_tuner_satisfies_the_protocol():
    assert isinstance(TUNER_OFF, TunerProvider)


def test_the_tuner_package_imports_on_its_own():
    """In a SUBPROCESS, and importing the tuner FIRST.

    `civ_advisor.tuner.base` used to import `civ_advisor.games.base`, which runs
    `civ_advisor/games/__init__.py`, which imports civ6, which imports this module
    while it is still half-built. Importing civ6 first happens to initialise `games`
    before the tuner and hides the cycle entirely -- which is exactly what every test
    in this suite does, because pytest has already imported other modules by the time
    one of them runs. Only a fresh interpreter that touches the tuner first can catch
    it, so this test spends a subprocess on it.
    """
    done = subprocess.run(
        [sys.executable, "-c", "import civ_advisor.tuner.base, civ_advisor.tuner.client"],
        capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr


def test_the_tuner_package_names_no_game():
    """The tuner asks a socket questions; it has no opinion about which game's
    capabilities an answer backs. Nothing under civ_advisor/tuner/ may import
    anything under civ_advisor/games/ -- that edge is the cycle above.

    Read as imports rather than as text, so a comment explaining the rule cannot
    fail it and a `from civ_advisor import games` cannot slip past it.
    """
    import ast
    import pathlib

    package = pathlib.Path(__file__).resolve().parents[1] / "civ_advisor" / "tuner"
    for module in package.glob("*.py"):
        for node in ast.walk(ast.parse(module.read_text())):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""] + [f"{node.module or ''}.{a.name}"
                                               for a in node.names]
            else:
                continue
            for name in names:
                assert not name.startswith("civ_advisor.games"), f"{module.name}: {name}"
                assert name != "civ_advisor", f"{module.name}: {name}"


def test_capturing_an_unavailable_provider_carries_its_own_reason():
    from civ_advisor.tuner.base import capture

    snap = capture(NullTuner(TunerUnavailable.UNREACHABLE, "the game implements no such call"))
    assert snap.available is False
    assert snap.reason == "the game implements no such call"
    assert snap.amenities == () and snap.maintenance is None and snap.build_options == ()
    assert snap.absences == ()


def test_the_off_singleton_snapshot_carries_the_off_reason():
    from civ_advisor.tuner.base import TUNER_SNAPSHOT_OFF

    assert TUNER_SNAPSHOT_OFF.available is False
    assert TUNER_SNAPSHOT_OFF.reason == TUNER_OFF.reason


def test_capturing_a_live_provider_reads_every_figure_once():
    from civ_advisor.tuner.base import capture

    class Live:
        available = True
        reason = None

        def reading(self):
            return TunerReading(turn=12, read_at="2026-09-13T10:00:00Z", state="GameCore_Tuner")

        def amenities(self):
            return (CityAmenities(city="Rome", total=4, from_luxuries=2, from_civics=1,
                                  from_entertainment=1, housing=5, food_surplus=2),)

        def maintenance(self):
            return Maintenance(total=9, buildings=1, districts=1, units=0, gold=100, gold_yield=8)

        def build_options(self):
            return (SettlementOptions(city="Rome", options=()),)

    snap = capture(Live())
    assert snap.available is True
    assert snap.reading is not None and snap.reading.turn == 12
    assert len(snap.amenities) == 1
    assert snap.maintenance is not None and snap.maintenance.total == 9
    assert len(snap.build_options) == 1
    assert snap.absences == ()


def test_a_figure_that_raises_is_recorded_as_an_absence_not_a_crash():
    from civ_advisor.tuner.base import capture

    class Flaky:
        available = True
        reason = None

        def reading(self):
            return None

        def amenities(self):
            raise RuntimeError("socket dropped mid-read")

        def maintenance(self):
            return None

        def build_options(self):
            return ()

    snap = capture(Flaky())
    assert snap.available is True
    assert snap.amenities == ()
    assert snap.absence("amenities") is not None
