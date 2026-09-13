import dataclasses

import pytest

from civ_advisor.games import profile_ids
from civ_advisor.games.registry import get_profile
from civ_advisor.ingest.load import RawLogs

PROFILES = [get_profile(i) for i in profile_ids()]


@pytest.mark.parametrize("profile", PROFILES, ids=lambda p: p.id)
def test_every_reader_targets_a_real_rawlogs_field(profile):
    known = {f.name for f in dataclasses.fields(RawLogs)}
    assert {r.attr for r in profile.readers} <= known


@pytest.mark.parametrize("profile", PROFILES, ids=lambda p: p.id)
def test_no_profile_declares_a_file_twice(profile):
    assert len(set(profile.log_files)) == len(profile.log_files)


@pytest.mark.parametrize("profile", PROFILES, ids=lambda p: p.id)
def test_every_profile_has_a_loadable_guide_catalog(profile):
    from civ_advisor.knowledge.catalog import load_catalog

    catalog = load_catalog(package=profile.knowledge_package)
    assert {e.game for e in catalog.entries} <= {profile.id}


@pytest.mark.parametrize("profile", PROFILES, ids=lambda p: p.id)
def test_every_declared_capability_is_backed_by_a_declared_reader(profile):
    """Stops the capability declaration and the reader table drifting apart:
    a profile claiming FAITH with no reader that can produce it would promise
    a panel it cannot fill."""
    from civ_advisor.games.base import Capability

    if profile.supports(Capability.VICTORY_PATHS):
        assert "AI_Victories.csv" in profile.log_files
    if profile.supports(Capability.MAINTENANCE):
        assert "Player_Treasury.csv" in profile.log_files
    if profile.supports(Capability.HAPPINESS):
        assert "Player_Happiness.csv" in profile.log_files
    if profile.supports(Capability.PEACE_DEALS):
        assert "DiplomacyDeals.log" in profile.log_files
    # The other direction, which is the one that actually bites: a capability
    # declared with no reader able to produce it promises a panel that cannot
    # be filled. Civ VI declares FAITH/CIVICS from Player_Stats and
    # TOURISM/DIPLOMATIC_FAVOR from Player_Stats_2.
    stats_backed = {Capability.FAITH, Capability.CIVICS}
    stats2_backed = {Capability.TOURISM, Capability.DIPLOMATIC_FAVOR}
    if stats_backed & set(profile.capabilities):
        assert "Player_Stats.csv" in profile.log_files
    if stats2_backed & set(profile.capabilities):
        assert "Player_Stats_2.csv" in profile.log_files
    # Phase 3: each of these is one file, and the declaration is a promise
    # that file is read.
    for capability, filename in (
        (Capability.COMBAT_DESIRE, "AI_Military.csv"),
        (Capability.DIPLOMATIC_MODIFIERS, "DiplomacyModifiers.csv"),
        (Capability.RESEARCH_PREFERENCE, "AI_Research.csv"),
        (Capability.POLICY_PREFERENCE, "AI_GovtPolicies.csv"),
    ):
        if profile.supports(capability):
            assert filename in profile.log_files


@pytest.mark.parametrize("profile", PROFILES, ids=lambda p: p.id)
def test_every_unsupported_capability_carries_a_reason(profile):
    """A capability that is merely absent from the set tells the player nothing. The
    profile is the source of truth for WHY, and this is what stops the two drifting."""
    from civ_advisor.games.base import Capability

    for capability in Capability:
        if profile.supports(capability):
            assert profile.reason(capability) is None, \
                f"{profile.id} declares {capability.value} supported AND gives a reason it is not"
        elif capability in profile.tuner_backed:
            # Not a fixed reason: this capability's absence is explained by the live
            # tuner state (see capability_report), not by a static profile string.
            continue
        else:
            assert profile.reason(capability), \
                f"{profile.id} does not support {capability.value} and does not say why"
