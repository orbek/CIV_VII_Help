"""The tuner is read once per rebuild, and never costs a poll that worked."""
from civ_advisor.tuner.base import TUNER_OFF, TunerUnavailable


def test_a_snapshot_always_carries_a_tuner(civ6_store):
    """Never None: callers must not branch on absence."""
    snap = civ6_store.rebuild()
    assert snap is not None
    assert snap.tuner is not None


def test_a_game_with_no_tuner_factory_gets_the_off_singleton(civ7_store):
    snap = civ7_store.rebuild()
    assert snap.tuner is TUNER_OFF


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
    assert snap.tuner.unavailable is TunerUnavailable.NOT_ANSWERING


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
