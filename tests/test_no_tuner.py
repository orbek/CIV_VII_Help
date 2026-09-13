"""`--no-tuner` is a choice by this run, not a change to what the game supports.

`Store.use_tuner` gates the factory lookup in `rebuild()`; nothing about the
registered `GameProfile` singletons ever changes, so a second `Store` in the same
interpreter -- another test, another `create_app` -- is never affected by an earlier
one's `--no-tuner`.
"""
from civ_advisor.games.civ6 import CIV6


def _with_counting_tuner(store, calls):
    """Swap in a fresh profile carrying a counting factory, without touching CIV6."""
    def factory():
        calls.append(1)
        raise AssertionError("never reached: only whether this is CALLED matters")
    store.profile = store.profile.__class__(
        **{**store.profile.__dict__, "tuner": factory})


def test_no_tuner_leaves_the_registered_profiles_untouched(civ6_store):
    """The flag is a decision by this run, not a change to what the game supports."""
    before = CIV6.tuner
    civ6_store.use_tuner = False
    civ6_store.rebuild()
    assert CIV6.tuner is before


def test_no_tuner_means_the_factory_is_never_called(civ6_store):
    calls: list[int] = []
    _with_counting_tuner(civ6_store, calls)
    civ6_store.use_tuner = False
    civ6_store.rebuild()
    assert calls == []


def test_the_default_still_tries_the_tuner(civ6_store):
    """Absence of the flag must not silently disable the feature.

    A fix that disabled the tuner everywhere would pass the two tests above and
    fail only this one.
    """
    calls: list[int] = []
    _with_counting_tuner(civ6_store, calls)
    assert civ6_store.use_tuner is True   # the default, unset by this test
    civ6_store.rebuild()
    assert calls == [1]
