"""Load every log file the advisor uses, isolating failures per file."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .csvfile import LogFormatError
from .readers import (
    DiplomacyRow,
    HappinessRow,
    HistorianRow,
    StatsRow,
    TargetRow,
    TreasuryRow,
    VictoryRow,
    read_diplomacy,
    read_happiness,
    read_historian,
    read_player_stats,
    read_targets,
    read_treasury,
    read_victories,
)
from .events import CombatRow, DiplomacySummaryRow, GossipRow, read_combat_log, read_diplomacy_summary, read_gossip
from .production import BuildQueueRow, read_build_queue
from .textlogs import DealItem, read_deals

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class FileStatus:
    name: str
    ok: bool
    rows: int
    latest_turn: int | None
    error: str | None = None


@dataclass
class RawLogs:
    stats: list[StatsRow] = field(default_factory=list)
    treasury: list[TreasuryRow] = field(default_factory=list)
    happiness: list[HappinessRow] = field(default_factory=list)
    victories: list[VictoryRow] = field(default_factory=list)
    diplomacy: list[DiplomacyRow] = field(default_factory=list)
    targets: list[TargetRow] = field(default_factory=list)
    historian: list[HistorianRow] = field(default_factory=list)
    build_queue: list[BuildQueueRow] = field(default_factory=list)
    combat: list[CombatRow] = field(default_factory=list)
    gossip: list[GossipRow] = field(default_factory=list)
    diplomacy_summary: list[DiplomacySummaryRow] = field(default_factory=list)
    deals: list[DealItem] = field(default_factory=list)
    files: dict[str, FileStatus] = field(default_factory=dict)


# (file name, RawLogs attribute, reader)
READERS: list[tuple[str, str, Callable[[Path], list]]] = [
    ("Player_Stats.csv", "stats", read_player_stats),
    ("Player_Treasury.csv", "treasury", read_treasury),
    ("Player_Happiness.csv", "happiness", read_happiness),
    ("AI_Victories.csv", "victories", read_victories),
    ("AI_DiplomaticActions.csv", "diplomacy", read_diplomacy),
    ("AI_Targets.csv", "targets", read_targets),
    ("Historian.csv", "historian", read_historian),
    ("CityBuildQueue.csv", "build_queue", read_build_queue),
    ("CombatLog.csv", "combat", read_combat_log),
    ("Game_Gossip.csv", "gossip", read_gossip),
    ("DiplomacySummary.csv", "diplomacy_summary", read_diplomacy_summary),
    ("DiplomacyDeals.log", "deals", read_deals),
]
LOG_FILES = [name for name, _, _ in READERS]


def load_logs(logs_dir: Path) -> RawLogs:
    """Read every log in READERS. A file that fails to parse is dropped for this load
    (its FileStatus says why) while every other file still contributes."""
    raw = RawLogs()
    for name, attr, reader in READERS:
        path = logs_dir / name
        try:
            rows = reader(path)
        except OSError as exc:
            error = "file not found" if isinstance(exc, FileNotFoundError) else str(exc)
            raw.files[name] = FileStatus(name, False, 0, None, error)
            continue
        except (LogFormatError, ValueError, IndexError) as exc:
            log.warning("%s: dropping file for this rebuild: %s", name, exc)
            raw.files[name] = FileStatus(name, False, 0, None, str(exc))
            continue
        setattr(raw, attr, rows)
        raw.files[name] = FileStatus(
            name, True, len(rows), max((r.turn for r in rows), default=None)
        )
    return raw
