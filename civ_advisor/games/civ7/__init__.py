"""Civilization VII: where its logs live and how each one is read."""
from __future__ import annotations

from pathlib import Path

from civ_advisor.ingest.events import read_combat_log, read_diplomacy_summary, read_gossip
from civ_advisor.ingest.production import read_build_queue
from civ_advisor.ingest.readers import (
    read_diplomacy, read_happiness, read_historian, read_player_stats, read_targets,
    read_treasury, read_victories,
)
from civ_advisor.ingest.tactical import (
    read_combat_planning, read_commander_promotions, read_mayhem, read_operation_evals,
    read_operations, read_tactical, read_unit_efficiency, read_unit_operations,
)
from civ_advisor.ingest.textlogs import read_deals, read_player_identities

from ..base import GameProfile, LogReader
from ..registry import register

DEFAULT_LOGS_DIR = Path.home() / "Library/Application Support/Civilization VII/Logs"

READERS: tuple[LogReader, ...] = (
    LogReader("Player_Stats.csv", "stats", read_player_stats),
    LogReader("Player_Treasury.csv", "treasury", read_treasury),
    LogReader("Player_Happiness.csv", "happiness", read_happiness),
    LogReader("AI_Victories.csv", "victories", read_victories),
    LogReader("AI_DiplomaticActions.csv", "diplomacy", read_diplomacy),
    LogReader("AI_Targets.csv", "targets", read_targets),
    LogReader("Historian.csv", "historian", read_historian),
    LogReader("CityBuildQueue.csv", "build_queue", read_build_queue),
    LogReader("CombatLog.csv", "combat", read_combat_log),
    LogReader("Game_Gossip.csv", "gossip", read_gossip),
    LogReader("DiplomacySummary.csv", "diplomacy_summary", read_diplomacy_summary),
    LogReader("DiplomacyDeals.log", "deals", read_deals),
    LogReader("UnitOperations.log", "unit_operations", read_unit_operations),
    LogReader("AI_Tactical.csv", "tactical", read_tactical),
    LogReader("AI_Operation.csv", "operations", read_operations),
    LogReader("AI_CombatPlanning.csv", "combat_orders", read_combat_planning),
    LogReader("AI_Operation_Eval.csv", "operation_evals", read_operation_evals),
    LogReader("AI_UnitEfficiency.csv", "unit_efficiency", read_unit_efficiency),
    LogReader("AI_MayhemTracker.csv", "mayhem", read_mayhem),
    LogReader("AI_Commander_Promotions.csv", "commander_promotions", read_commander_promotions),
    LogReader("GameCore.log", "player_identities", read_player_identities),
)

CIV7 = GameProfile(
    id="civ7",
    display_name="Civilization VII",
    default_logs_dir=DEFAULT_LOGS_DIR,
    readers=READERS,
    knowledge_package="civ_advisor.knowledge.civ7",
)

register(CIV7)
