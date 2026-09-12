"""Mirror the game's logs into a directory of our own.

Civ VII deletes its entire Logs/ directory on every launch and regenerates it from the loaded
save's current turn, so without this a game's history is lost the moment the game restarts.
This module is the ONLY place the advisor writes to disk, and it writes only under `dest`.
"""
from __future__ import annotations

import json
import re
import shutil
import time
from pathlib import Path
from typing import Iterable

DEFAULT_ROOT = Path.home() / ".civ-advisor"      # our own directory, never the game's
# Where a pre-2b install kept everything. Still named, and still readable: the tooling
# lists it, and --archive-dir accepts it. Nothing here moves a user's files.
LEGACY_ARCHIVE_ROOT = Path.home() / ".civ7-advisor" / "archive"
DEFAULT_ARCHIVE_ROOT = LEGACY_ARCHIVE_ROOT       # retained: existing imports and tests
MANIFEST = "archived.json"     # written in each session directory: what is mirrored there, and when
# Archive dir for a logs directory whose GameCore.log has no seeds line. Civ VI's
# GameCore.log never carries one at all (checked the real capture and the committed
# fixture: zero matches) -- every Civ VI archive lands here. Namespacing this per game
# (see `archive_root_for`) is what keeps Civ VI's unknown-game bucket from colliding
# with Civ VII's, since Civ VII usually DOES have a real seeds-keyed directory instead.
UNKNOWN_GAME = "unknown-game"


def archive_root_for(game_id: str, base: Path = DEFAULT_ROOT) -> Path:
    """Where this game's logs are mirrored. `game_id` is the TITLE (civ6/civ7); the
    save-seeds key is a directory deeper, under this root."""
    return base / game_id / "archive"

# The engine writes this once per save load, e.g. "Random Seeds: Game 1571231116, Map 1516997327".
_SEEDS = re.compile(r"Random Seeds: Game (\d+), Map (\d+)")


def game_key(logs_dir: Path) -> str | None:
    """The save's identity: the game and map seeds the engine logs at load. Stable across
    relaunches of the same save (a turn range is not); the LAST match wins because loading
    another save in the same app session appends a new line. None when unknown."""
    path = logs_dir / "GameCore.log"
    if not path.is_file():
        return None
    matches = _SEEDS.findall(path.read_text(errors="replace"))
    if not matches:
        return None
    game, map_ = matches[-1]
    return f"seeds-{game}-{map_}"


def archive_logs(logs_dir: Path, dest: Path, names: Iterable[str]) -> list[str]:
    """Copy each named log into `dest`, skipping files that are unchanged (same size and
    mtime) since the last copy. Returns the names copied. Never touches `logs_dir`."""
    logs_dir, dest = logs_dir.resolve(), dest.resolve()
    if dest == logs_dir or logs_dir in dest.parents:
        raise ValueError(f"archive destination {dest} is inside the logs directory {logs_dir}")
    dest.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    for name in names:
        relative = Path(name)
        if relative.is_absolute() or relative.name != name:
            raise ValueError(f"archive name must be a file name, got {name!r}")
        src, dst = logs_dir / name, dest / name
        if not src.is_file():
            continue
        if dst.is_symlink():
            raise ValueError(f"archive destination file must not be a symlink: {dst}")
        s = src.stat()
        if dst.exists():
            d = dst.stat()
            if (d.st_size, d.st_mtime_ns) == (s.st_size, s.st_mtime_ns):
                continue
        shutil.copy2(src, dst)  # copy2 preserves mtime, which is what makes the skip above work
        copied.append(name)
    manifest = {"updated": time.strftime("%Y-%m-%dT%H:%M:%S"), "logs_dir": str(logs_dir),
                "files": sorted(p.name for p in dest.iterdir() if p.name != MANIFEST)}
    manifest_path = dest / MANIFEST
    if manifest_path.is_symlink():
        raise ValueError(f"archive manifest must not be a symlink: {manifest_path}")
    manifest_path.write_text(json.dumps(manifest, indent=2))
    return copied
