"""Civilization VI: where its logs live and how each one is read.

Civ VI writes its gameplay logs with no configuration: no mod, no FireTuner,
no AppOptions change. What it does NOT write is as important as what it does
-- see the profile's capability set and spec §3.5.
"""
from __future__ import annotations

from pathlib import Path

from civ_advisor.ingest.aiscores import (
    read_diplomacy_modifiers, read_military, read_policy_scores, read_tech_scores,
)
from civ_advisor.ingest.events import read_diplomacy_summary
from civ_advisor.ingest.tactical import (
    read_mayhem, read_operations, read_tactical, read_unit_efficiency,
)
from civ_advisor.ingest.textlogs import read_player_identities
from civ_advisor.ruleset.civ6 import open_ruleset
from civ_advisor.tuner.base import TUNER_BACKED
from civ_advisor.tuner.client import open_tuner

from ..base import Capability, GameProfile, LogReader, simple
from ..registry import register
from .readers import (
    read_build_queue_civ6, read_city_ownership_status, read_player_stats_civ6,
    read_unit_operations_civ6,
)

DEFAULT_LOGS_DIR = (
    Path.home()
    / "Library/Application Support/Sid Meier's Civilization VI"
    / "Firaxis Games/Sid Meier's Civilization VI/Logs"
)

READERS: tuple[LogReader, ...] = (
    # Shared with Civ VII, byte-identical headers (spec §3.1).
    LogReader("DiplomacySummary.csv", "diplomacy_summary", simple(read_diplomacy_summary)),
    LogReader("AI_Tactical.csv", "tactical", simple(read_tactical)),
    LogReader("AI_Operation.csv", "operations", simple(read_operations)),
    LogReader("AI_MayhemTracker.csv", "mayhem", simple(read_mayhem)),
    LogReader("AI_UnitEfficiency.csv", "unit_efficiency", simple(read_unit_efficiency)),
    LogReader("GameCore.log", "player_identities", simple(read_player_identities)),
    LogReader("Player_Stats.csv", "stats", read_player_stats_civ6),
    LogReader("UnitOperations.log", "unit_operations", read_unit_operations_civ6),
    LogReader("City_BuildQueue.csv", "build_queue", read_build_queue_civ6),
    # AI_CityBuild.csv is joined privately by the build-queue reader above; declared
    # separately so it gets its own FileStatus rather than failing invisibly (spec §3.2).
    LogReader("AI_CityBuild.csv", "city_ownership", read_city_ownership_status),
    # Civ VI-only and strictly AI-internal (spec §3.3). Everything built from
    # these four is ORACLE; see advisors/threat.py and advisors/intel.py.
    LogReader("AI_Military.csv", "military", simple(read_military)),
    LogReader("DiplomacyModifiers.csv", "diplomacy_modifiers", simple(read_diplomacy_modifiers)),
    LogReader("AI_Research.csv", "tech_scores", simple(read_tech_scores)),
    LogReader("AI_GovtPolicies.csv", "policy_scores", simple(read_policy_scores)),
)

CIV6 = GameProfile(
    id="civ6",
    display_name="Civilization VI",
    default_logs_dir=DEFAULT_LOGS_DIR,
    readers=READERS,
    knowledge_package="civ_advisor.knowledge.civ6",
    # What Civ VI's logs cannot support, and therefore what this build must
    # not claim for it. AI_Victories exists but records era strategies, not
    # victory paths (spec §3.2); there is no deal or combat-odds log at all
    # (spec §3.5). HAPPINESS and MAINTENANCE moved to `tuner_backed`: Civ VI's
    # logs cannot support them, but its tuner socket can, when the player has
    # turned it on -- so they are conditional on a live reading rather than
    # permanently unsupported. TOURISM and DIPLOMATIC_FAVOR are NOT declared
    # here even though Player_Stats_2.csv presumably carries them: no reader
    # for that file exists yet, and a capability is a promise to fill a panel
    # -- declaring one with nothing behind it is the exact defect this phase
    # exists to prevent. Add them back only alongside a Player_Stats_2.csv
    # reader and the canonical fields it would populate.
    #
    # VICTORY_PATHS stays undeclared. AI_Research and AI_GovtPolicies score
    # the AI's tech and civic preferences, and phase 3 answered the question
    # spec §3.2 left open: those scores carry no victory label, are not
    # comparable across turns or players, and name items that serve every
    # path. They support "Cyrus scored these civics highest", and nothing
    # about what Cyrus is pursuing.
    capabilities=frozenset({
        Capability.FAITH,
        Capability.CIVICS,
        Capability.COMBAT_DESIRE,
        Capability.DIPLOMATIC_MODIFIERS,
        Capability.RESEARCH_PREFERENCE,
        Capability.POLICY_PREFERENCE,
        Capability.INSTALLED_RULESET,
    }),
    ruleset=open_ruleset,
    tuner_backed=TUNER_BACKED,
    tuner=open_tuner,
    unsupported=(
        (Capability.VICTORY_PATHS,
         "Civ VI's AI_Victories.csv records era and posture strategies "
         "(STRATEGY_DARKAGE, STRATEGY_EARLY_EXPLORATION), not which victory a rival is "
         "pursuing. Reading them as victory paths would assert a pursuit the log does "
         "not state."),
        (Capability.PEACE_DEALS,
         "Civ VI has no DiplomacyDeals.log, so a signed peace treaty is not observable "
         "and a war alert cannot be cleared by one."),
        (Capability.COMBAT_ODDS,
         "Civ VI's AI_Operation_Eval.csv has no Odds column, so the AI's own combat odds "
         "-- the basis of bounded combat prediction -- do not exist."),
        (Capability.SETTLEMENT_CAP, "Civ VI has no settlement cap."),
        (Capability.URBAN_RURAL_SPLIT, "Civ VI does not split population urban/rural."),
        (Capability.TOURISM,
         "Tourism is in Player_Stats_2.csv, for which this build has no reader yet."),
        (Capability.DIPLOMATIC_FAVOR,
         "Diplomatic favor is in Player_Stats_2.csv, for which this build has no reader yet."),
    ),
)

register(CIV6)
