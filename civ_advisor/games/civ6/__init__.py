"""Civilization VI: where its logs live and how each one is read.

Civ VI writes its gameplay logs with no configuration: no mod, no FireTuner,
no AppOptions change. What it does NOT write is as important as what it does
-- see the profile's capability set and spec §3.5.
"""
from __future__ import annotations

from pathlib import Path

from civ_advisor.ingest.events import read_diplomacy_summary
from civ_advisor.ingest.tactical import (
    read_mayhem, read_operations, read_tactical, read_unit_efficiency,
)
from civ_advisor.ingest.textlogs import read_player_identities

from ..base import Capability, GameProfile, LogReader, simple
from ..registry import register
from .readers import read_build_queue_civ6, read_player_stats_civ6, read_unit_operations_civ6

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
)

CIV6 = GameProfile(
    id="civ6",
    display_name="Civilization VI",
    default_logs_dir=DEFAULT_LOGS_DIR,
    readers=READERS,
    knowledge_package="civ_advisor.knowledge.civ6",
    # What Civ VI's logs cannot support, and therefore what this build must
    # not claim for it. AI_Victories exists but records era strategies, not
    # victory paths (spec §3.2); there is no amenities, maintenance, deal or
    # combat-odds log at all (spec §3.5). TOURISM and DIPLOMATIC_FAVOR are
    # NOT declared here even though Player_Stats_2.csv presumably carries
    # them: no reader for that file exists yet, and a capability is a promise
    # to fill a panel -- declaring one with nothing behind it is the exact
    # defect this phase exists to prevent. Add them back only alongside a
    # Player_Stats_2.csv reader and the canonical fields it would populate.
    capabilities=frozenset({
        Capability.FAITH,
        Capability.CIVICS,
    }),
)

register(CIV6)
