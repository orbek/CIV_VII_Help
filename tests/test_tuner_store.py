"""The tuner is read once per rebuild, frozen into the snapshot, never costs a poll
that worked, and one bad figure does not take the others down with it."""
from civ_advisor.games.civ6 import CIV6
from civ_advisor.store import Store
from civ_advisor.tuner.base import (
    CityAmenities, Maintenance, SettlementOptions, TunerUnavailable,
)
from civ_advisor.tuner.client import open_tuner

from tests.test_tuner_client import FakeGame, replies


def test_a_snapshot_always_carries_a_tuner(civ6_store):
    """Never None: callers must not branch on absence."""
    snap = civ6_store.rebuild()
    assert snap is not None
    assert snap.tuner is not None


def test_a_game_with_no_tuner_factory_is_told_it_has_no_socket(civ7_store):
    """Not "your socket is off". Civ VII has no tuner at all, and the snapshot used to
    carry Civ VI's prose -- so a Civ VII player was told to set `EnableTuner 1` in
    Civilization VI's AppOptions.txt, naming a cause that does not exist and a fix they
    cannot make. This ships in /api/briefing."""
    snap = civ7_store.rebuild()
    assert snap.tuner.available is False
    assert snap.tuner.unavailable is TunerUnavailable.NO_SOCKET
    assert "EnableTuner" not in snap.tuner.reason
    assert "AppOptions" not in snap.tuner.reason
    assert "Civilization VI" not in snap.tuner.reason
    assert "no tuner socket" in snap.tuner.reason


def test_a_game_that_has_a_socket_is_still_told_the_socket_is_off(civ6_store):
    """The other half: NO_SOCKET must not swallow the one absence a player CAN act on.
    Civ VI has a tuner, so a closed socket is still the actionable "switch it on"."""
    snap = civ6_store.rebuild()
    assert snap.tuner.available is False
    assert snap.tuner.unavailable is TunerUnavailable.NOT_ENABLED
    assert "EnableTuner" in snap.tuner.reason


def test_no_tuner_says_this_run_chose_not_to_ask(civ6_store):
    """`--no-tuner` is neither absence: the game has a socket and nothing is wrong
    with it. Repeating either of the other two reasons would send the player to fix
    something that is not broken."""
    civ6_store.use_tuner = False
    snap = civ6_store.rebuild()
    assert snap.tuner.available is False
    assert "--no-tuner" in snap.tuner.reason
    assert "EnableTuner" not in snap.tuner.reason
    assert "no tuner socket" not in snap.tuner.reason
    # The machine-readable cause too, not just the prose: shipping "not_enabled" for a
    # socket nobody contacted is the same reason-vs-cause split one layer down, and a
    # consumer branching on the enum would act on a story the player never reads.
    assert snap.tuner.unavailable is TunerUnavailable.NOT_ASKED


def test_a_tuner_that_raises_does_not_fail_the_rebuild(civ6_store):
    """The logs were read perfectly well. A socket problem must not discard that.

    GameProfile is a frozen dataclass, so this swaps in a copy carrying the
    raising factory rather than mutating CIV6's shared singleton in place.
    """
    def explode():
        raise OSError("boom")
    civ6_store.profile = civ6_store.profile.__class__(
        **{**civ6_store.profile.__dict__, "tuner": explode})
    snap = civ6_store.rebuild()
    assert snap is not None
    assert snap.tuner.available is False
    assert "tuner socket" in snap.tuner.reason


def test_the_tuner_is_asked_once_per_rebuild_not_once_per_question(civ6_store):
    calls = []
    class Counting:
        available = True
        reason = None
        unavailable = None
        def __init__(self): calls.append(1)
        def reading(self): return None
        def amenities(self): return ()
        def maintenance(self): return None
        def build_options(self): return ()
    civ6_store.profile = civ6_store.profile.__class__(
        **{**civ6_store.profile.__dict__, "tuner": Counting})
    civ6_store.rebuild()
    assert len(calls) == 1


def test_a_published_snapshot_owns_no_open_socket(civ6_store):
    """Nothing on a snapshot can be invalidated by a later rebuild."""
    snap = civ6_store.rebuild()
    assert not hasattr(snap.tuner, "close")


def test_one_unreachable_figure_does_not_discard_the_others(civ6_store):
    """And does not become the stated reason the others are missing."""
    class Provider:
        available = True
        _reason = None

        @property
        def reason(self):
            return self._reason

        def reading(self):
            return None

        def amenities(self):
            self._reason = None
            return (CityAmenities(city="Rome", total=4, from_luxuries=2,
                                  from_civics=1, from_entertainment=1,
                                  housing=5, food_surplus=2),)

        def maintenance(self):
            self._reason = ("the game's GameCore_Tuner state does not implement "
                            "the calls maintenance needs")
            return None

        def build_options(self):
            self._reason = None
            return (SettlementOptions(city="Rome", options=()),)

    civ6_store.profile = civ6_store.profile.__class__(
        **{**civ6_store.profile.__dict__, "tuner": Provider})
    snap = civ6_store.rebuild()
    tuner = snap.tuner
    assert tuner.available is True
    assert len(tuner.amenities) == 1
    assert len(tuner.build_options) == 1
    assert tuner.maintenance is None
    assert tuner.absence("maintenance") is not None
    assert tuner.absence("amenities") is None
    assert tuner.absence("build_options") is None


def test_a_figure_absence_names_its_own_cause(civ6_store):
    class Provider:
        available = True
        _reason = None

        @property
        def reason(self):
            return self._reason

        def reading(self):
            return None

        def amenities(self):
            self._reason = "amenities-specific reason"
            return ()

        def maintenance(self):
            self._reason = "maintenance-specific reason"
            return None

        def build_options(self):
            self._reason = "build-options-specific reason"
            return ()

    civ6_store.profile = civ6_store.profile.__class__(
        **{**civ6_store.profile.__dict__, "tuner": Provider})
    snap = civ6_store.rebuild()
    tuner = snap.tuner
    assert tuner.absence("amenities") == "amenities-specific reason"
    assert tuner.absence("maintenance") == "maintenance-specific reason"
    assert tuner.absence("build_options") == "build-options-specific reason"


def test_build_options_ids_is_asked_only_when_a_run_allows_acting(civ6_dir):
    """A normal advisory run sends exactly the three queries it sends today -- an
    assertion of the COUNT, not just "the fourth query's absence is harmless",
    because a poll that silently grew a fourth query would still pass a test that
    only checked the first three came back."""
    game = FakeGame(replies())
    try:
        profile = CIV6.__class__(
            **{**CIV6.__dict__, "tuner": lambda: open_tuner(port=game.port, timeout=3.0)})

        store = Store(civ6_dir, profile=profile, allow_actions=False)
        store.rebuild()
        assert len(game.asked) == 3

        game.asked.clear()
        store = Store(civ6_dir, profile=profile, allow_actions=True)
        store.rebuild()
        assert len(game.asked) == 4
    finally:
        game.close()
