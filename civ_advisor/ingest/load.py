"""Load every log file the advisor uses, isolating failures per file."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field, fields
from pathlib import Path

from civ_advisor.games.base import GameProfile
from civ_advisor.games.civ7 import CIV7

from .csvfile import LogFormatError
from .readers import DiplomacyRow, HappinessRow, HistorianRow, StatsRow, TargetRow, TreasuryRow, VictoryRow
from .events import CombatRow, DiplomacySummaryRow, GossipRow
from .production import BuildQueueRow
from .textlogs import DealItem, PlayerIdentityRow
from .tactical import (
    CombatOrderRow,
    CommanderPromotionRow,
    MayhemRow,
    OperationEvalRow,
    OperationRow,
    TacticalRow,
    UnitEfficiencyRow,
    UnitOperationRow,
)

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
    unit_operations: list[UnitOperationRow] = field(default_factory=list)
    tactical: list[TacticalRow] = field(default_factory=list)
    operations: list[OperationRow] = field(default_factory=list)
    combat_orders: list[CombatOrderRow] = field(default_factory=list)
    operation_evals: list[OperationEvalRow] = field(default_factory=list)
    unit_efficiency: list[UnitEfficiencyRow] = field(default_factory=list)
    mayhem: list[MayhemRow] = field(default_factory=list)
    commander_promotions: list[CommanderPromotionRow] = field(default_factory=list)
    player_identities: list[PlayerIdentityRow] = field(default_factory=list)
    # Civ VI's build-queue reader joins AI_CityBuild.csv privately for ownership and
    # never sets this; it exists only so that file gets a declared reader of its own,
    # and therefore its own FileStatus below -- a joined-only file must not go
    # unreported just because nothing consumes rows from it directly (spec §3.2).
    city_ownership: list = field(default_factory=list)
    files: dict[str, FileStatus] = field(default_factory=dict)


def load_logs(logs_dir: Path, profile: GameProfile = CIV7) -> RawLogs:
    """Read every log `profile` declares. A file that fails to parse is dropped for
    this load (its FileStatus says why) while every other file still contributes.

    A file the profile does not declare is not read and not reported: absent by
    design is not the same as missing, and only the profile knows which is which.
    """
    raw = RawLogs()
    raw_log_fields = {f.name for f in fields(RawLogs)}
    for reader in profile.readers:
        path = logs_dir / reader.filename
        try:
            rows = reader.read(logs_dir, path)
        except OSError as exc:
            error = "file not found" if isinstance(exc, FileNotFoundError) else str(exc)
            raw.files[reader.filename] = FileStatus(reader.filename, False, 0, None, error)
            continue
        except (LogFormatError, ValueError, IndexError) as exc:
            log.warning("%s: dropping file for this rebuild: %s", reader.filename, exc)
            raw.files[reader.filename] = FileStatus(reader.filename, False, 0, None, str(exc))
            continue
        if reader.attr not in raw_log_fields:
            error = f"reader.attr {reader.attr!r} is not a RawLogs field"
            log.warning("%s: %s", reader.filename, error)
            raw.files[reader.filename] = FileStatus(reader.filename, False, 0, None, error)
            continue
        setattr(raw, reader.attr, rows)
        raw.files[reader.filename] = FileStatus(
            reader.filename, True, len(rows), max((r.turn for r in rows), default=None)
        )
    return raw
