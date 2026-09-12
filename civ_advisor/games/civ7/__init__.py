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

from ..base import Capability, GameProfile, LogReader, simple
from ..registry import register

DEFAULT_LOGS_DIR = Path.home() / "Library/Application Support/Civilization VII/Logs"

READERS: tuple[LogReader, ...] = (
    LogReader("Player_Stats.csv", "stats", simple(read_player_stats)),
    LogReader("Player_Treasury.csv", "treasury", simple(read_treasury)),
    LogReader("Player_Happiness.csv", "happiness", simple(read_happiness)),
    LogReader("AI_Victories.csv", "victories", simple(read_victories)),
    LogReader("AI_DiplomaticActions.csv", "diplomacy", simple(read_diplomacy)),
    LogReader("AI_Targets.csv", "targets", simple(read_targets)),
    LogReader("Historian.csv", "historian", simple(read_historian)),
    LogReader("CityBuildQueue.csv", "build_queue", simple(read_build_queue)),
    LogReader("CombatLog.csv", "combat", simple(read_combat_log)),
    LogReader("Game_Gossip.csv", "gossip", simple(read_gossip)),
    LogReader("DiplomacySummary.csv", "diplomacy_summary", simple(read_diplomacy_summary)),
    LogReader("DiplomacyDeals.log", "deals", simple(read_deals)),
    LogReader("UnitOperations.log", "unit_operations", simple(read_unit_operations)),
    LogReader("AI_Tactical.csv", "tactical", simple(read_tactical)),
    LogReader("AI_Operation.csv", "operations", simple(read_operations)),
    LogReader("AI_CombatPlanning.csv", "combat_orders", simple(read_combat_planning)),
    LogReader("AI_Operation_Eval.csv", "operation_evals", simple(read_operation_evals)),
    LogReader("AI_UnitEfficiency.csv", "unit_efficiency", simple(read_unit_efficiency)),
    LogReader("AI_MayhemTracker.csv", "mayhem", simple(read_mayhem)),
    LogReader("AI_Commander_Promotions.csv", "commander_promotions", simple(read_commander_promotions)),
    LogReader("GameCore.log", "player_identities", simple(read_player_identities)),
)

CIV7 = GameProfile(
    id="civ7",
    display_name="Civilization VII",
    default_logs_dir=DEFAULT_LOGS_DIR,
    readers=READERS,
    knowledge_package="civ_advisor.knowledge.civ7",
    # Civ VII's own Player_Stats.csv has no Faith, Civics, Tourism or
    # Diplomatic Favor column at all -- declaring every Capability here
    # (as this build once did) claimed four capabilities Civ VII's logs
    # do not carry. Only what a declared reader actually backs:
    capabilities=frozenset({
        Capability.VICTORY_PATHS,        # AI_Victories.csv
        Capability.HAPPINESS,            # Player_Happiness.csv
        Capability.MAINTENANCE,          # Player_Treasury.csv
        Capability.PEACE_DEALS,          # DiplomacyDeals.log
        Capability.COMBAT_ODDS,          # AI_Operation_Eval.csv (Odds column)
        Capability.SETTLEMENT_CAP,       # Player_Stats.csv (Settlement Cap, Settlements Over Cap)
        Capability.URBAN_RURAL_SPLIT,    # Player_Stats.csv (Urban Pop, Rural Pop)
    }),
)

register(CIV7)
