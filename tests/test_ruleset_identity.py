import hashlib
import sqlite3

from civ_advisor.ruleset.civ6 import Civ6Ruleset
from civ_advisor.ruleset.identity import identify, stamp

from tests.ruleset_fixture import make_ruleset


def test_identity_is_the_file_itself(tmp_path):
    path = make_ruleset(tmp_path)

    identity = identify(path)

    assert identity.path == path
    assert identity.size == path.stat().st_size
    assert identity.mtime_ns == path.stat().st_mtime_ns
    assert identity.digest == hashlib.sha256(path.read_bytes()).hexdigest()


def test_two_rulesets_with_different_content_have_different_digests(tmp_path):
    """What makes a figure falsifiable: a reader with the same file gets the same digest,
    and a modded ruleset is visibly not the same ruleset."""
    vanilla = make_ruleset(tmp_path / "a", name="DebugGameplay.sqlite")
    modded = make_ruleset(tmp_path / "b", name="DebugGameplay.sqlite", rows={
        "Buildings": [("BUILDING_LIBRARY", "LOC_X", 45, 1, "DISTRICT_CAMPUS",
                       "TECH_WRITING", "", 0, 0)]})

    assert identify(vanilla).digest != identify(modded).digest


def test_the_stamp_is_cheap_and_moves_when_the_file_does(tmp_path):
    path = make_ruleset(tmp_path)
    before = stamp(path)

    path.write_bytes(path.read_bytes() + b"\x00" * 4096)

    assert stamp(path) != before


def test_a_figure_carries_the_digest_of_the_file_it_came_from(tmp_path):
    """The placeholder digest from Task 3 must be gone: an all-zero digest would make
    every ruleset look identical to every other."""
    path = make_ruleset(tmp_path)
    provider = Civ6Ruleset.open(path)
    try:
        figure = provider.building("BUILDING_LIBRARY").cost

        assert figure.identity.digest == hashlib.sha256(path.read_bytes()).hexdigest()
        assert set(figure.identity.digest) != {"0"}
    finally:
        provider.close()


def test_a_mod_toggle_is_never_served_from_a_stale_cache(tmp_path):
    """The worst failure this phase could produce: the player enables a mod, a cost
    changes in their install, and a long-lived provider keeps citing yesterday's number
    as fact from "your installed ruleset". Rewrites the file in place -- same path, same
    provider instance, no reopen -- and the next read must reflect the new value and a
    changed identity, never the cached one."""
    path = make_ruleset(tmp_path)
    provider = Civ6Ruleset.open(path)
    try:
        first = provider.building("BUILDING_LIBRARY").cost
        assert first.value == 90
        first_digest = provider.identity().digest

        # A mod (or a patch) rewrites the ruleset in place, through a separate
        # connection -- exactly as an external process touching the player's install
        # would, with the provider never closed or reopened.
        setup = sqlite3.connect(path)
        setup.execute(
            "UPDATE Buildings SET Cost = 999 WHERE BuildingType = 'BUILDING_LIBRARY'")
        setup.commit()
        setup.close()

        second = provider.building("BUILDING_LIBRARY").cost
        assert second.value == 999
        assert provider.identity().digest != first_digest
        assert second.identity.digest != first_digest
    finally:
        provider.close()


def test_an_unchanged_file_reuses_the_cached_figure(tmp_path):
    """The other half of the same property: `_refresh_if_changed` must not treat every
    call as a change, or the cache buys nothing and the file is re-hashed on every
    lookup -- the exact cost `stamp()` exists to avoid."""
    path = make_ruleset(tmp_path)
    provider = Civ6Ruleset.open(path)
    try:
        first = provider.building("BUILDING_LIBRARY")
        second = provider.building("BUILDING_LIBRARY")
        assert first is second  # the very same cached object, not merely equal
    finally:
        provider.close()
