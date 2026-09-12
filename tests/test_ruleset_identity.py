import dataclasses
import hashlib
import sqlite3

import civ_advisor.ruleset.civ6 as civ6
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
    """The other half of the same property: a stable file must still hit the
    per-building cache -- always re-deriving identity does not mean always rebuilding
    every figure, or the cache would buy nothing at all."""
    path = make_ruleset(tmp_path)
    provider = Civ6Ruleset.open(path)
    try:
        first = provider.building("BUILDING_LIBRARY")
        second = provider.building("BUILDING_LIBRARY")
        assert first is second  # the very same cached object, not merely equal
    finally:
        provider.close()


def test_an_edit_invisible_to_stamp_is_still_caught(tmp_path):
    """The whole-phase review's Important #1: a same-size edit under a coalesced or
    coarse-resolution mtime is exactly what `stamp()`'s own docstring admits it can
    miss. Forces both size and mtime back to their pre-edit values after rewriting the
    file, so nothing but the content digest itself could catch this -- proving
    `_refresh_if_changed` no longer relies on the proxy that used to gate it."""
    import os

    path = make_ruleset(tmp_path)
    provider = Civ6Ruleset.open(path)
    try:
        assert provider.building("BUILDING_LIBRARY").cost.value == 90
        before = path.stat()

        setup = sqlite3.connect(path)
        setup.execute(
            "UPDATE Buildings SET Cost = 999 WHERE BuildingType = 'BUILDING_LIBRARY'")
        setup.commit()
        setup.close()
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        after = path.stat()
        assert (after.st_size, after.st_mtime_ns) == (before.st_size, before.st_mtime_ns)

        assert provider.building("BUILDING_LIBRARY").cost.value == 999
    finally:
        provider.close()


def test_a_race_between_the_digest_and_the_rows_is_detected_and_retried(tmp_path, monkeypatch):
    """The whole-phase review's Important #2: `identify()` reads raw bytes outside
    SQLite's consistency guarantees while `_select()` reads through the connection, so
    a write landing between them could in principle leave a figure citing a digest
    that does not match the bytes it came from. Simulated directly here, since the real
    race is a narrow timing window: the digest check disagrees on the first attempt and
    agrees on the second, and the returned figure must cite the identity the STABLE
    attempt was verified against, never the one caught mid-race."""
    path = make_ruleset(tmp_path)
    provider = Civ6Ruleset.open(path)
    try:
        real = civ6.identify(path)
        moved = dataclasses.replace(real, digest="f" * 64)
        # 1: _refresh_if_changed's own call (no real change). 2: attempt 1's
        # post-read check (reports a race). 3: attempt 2's post-read check (reports
        # the file has now settled at `moved`).
        calls = iter([real, moved, moved])
        monkeypatch.setattr(civ6, "identify", lambda p: next(calls))

        facts = provider.building("BUILDING_LIBRARY")

        assert facts is not None
        assert facts.cost.value == 90
        assert facts.cost.identity.digest == moved.digest
    finally:
        provider.close()


def test_a_persistent_race_degrades_to_cannot_answer_rather_than_retrying_forever(
    tmp_path, monkeypatch,
):
    """A file that never holds still long enough for a stable read is not this
    provider's problem to solve. Past `_MAX_READ_ATTEMPTS`, the honest answer is
    "cannot answer" -- the same degraded outcome as any other unreadable case -- not an
    infinite retry loop."""
    path = make_ruleset(tmp_path)
    provider = Civ6Ruleset.open(path)
    try:
        real = civ6.identify(path)
        counter = iter(range(1_000))
        monkeypatch.setattr(
            civ6, "identify",
            lambda p: dataclasses.replace(real, digest=f"{next(counter):064d}"))

        assert provider.building("BUILDING_LIBRARY") is None
    finally:
        provider.close()
