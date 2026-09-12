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
    # Tasks 4 and 5 add the Civ VI variant readers here.
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
    # combat-odds log at all (spec §3.5).
    capabilities=frozenset({
        Capability.FAITH,
        Capability.CIVICS,
        Capability.TOURISM,
        Capability.DIPLOMATIC_FAVOR,
    }),
)

register(CIV6)
