"""Read whether the tuner is enabled from the file that enables it.

A refused connection is ONE observation with at least three causes: the flag is 0; the
flag is 1 but the game is at the main menu, between screens, or not running (confirmed
live: the listener cycles at the menu and is stable in a loaded match); or the file
cannot be read to say which. Until this module existed the advisor collapsed all three
into "set EnableTuner 1", and told a player with it already set to set it.

Read-only, and permitted: the rule this program lives by forbids WRITING under either
game's directories. It reads the logs and the ruleset database from inside them already.
Only the [Debug] section is consulted; a line elsewhere does not govern the tuner.
"""
from __future__ import annotations

from enum import StrEnum
from pathlib import Path

# The parent of Civ VI's own Logs/ directory. On the machine this was verified on, line
# 73 is `[Debug]`, line 74 `;Enable FireTuner.`, line 75 `EnableTuner 1`.
DEFAULT_APP_OPTIONS = (Path.home() / "Library" / "Application Support"
                       / "Sid Meier's Civilization VI" / "Firaxis Games"
                       / "Sid Meier's Civilization VI" / "AppOptions.txt")


class TunerFlag(StrEnum):
    ON = "on"
    OFF = "off"                 # the line says 0, or there is no line in [Debug]
    UNREADABLE = "unreadable"   # absent, unreadable, or undecodable: nothing is asserted


def read_enable_tuner(path: Path) -> tuple[TunerFlag, str]:
    """The flag as the file states it, and a sentence saying what was read."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return TunerFlag.UNREADABLE, f"{path} could not be read ({exc.strerror or exc})"
    section = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(";"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            continue
        if section != "Debug":
            continue
        parts = line.split(None, 1)
        if parts[0] == "EnableTuner" and len(parts) == 2:
            value = parts[1].strip()
            if value == "1":
                return TunerFlag.ON, f"{path.name} says `EnableTuner 1` under [Debug]"
            return TunerFlag.OFF, f"{path.name} says `EnableTuner {value}` under [Debug]"
    return TunerFlag.OFF, f"{path.name} has no EnableTuner line under [Debug]"


__all__ = ["DEFAULT_APP_OPTIONS", "TunerFlag", "read_enable_tuner"]
