"""Detect changes to the log files by polling their mtime and size.

Polling was chosen over a filesystem watcher: seven stat() calls a second are
free, it needs no extra dependency, and it avoids cross-thread debouncing.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Callable, Iterable

Snapshot = dict[str, tuple[int, int] | None]


def snapshot(logs_dir: Path, names: Iterable[str]) -> Snapshot:
    out: Snapshot = {}
    for name in names:
        try:
            st = (logs_dir / name).stat()
            out[name] = (st.st_mtime_ns, st.st_size)
        except FileNotFoundError:
            out[name] = None
    return out


async def watch(
    logs_dir: Path,
    names: list[str],
    on_change: Callable[[], None],
    interval: float = 1.0,
    initial: Snapshot | None = None,
) -> None:
    """Call `on_change` (in a worker thread) after the files change and then stay
    unchanged for one full interval — Civ VII writes its logs over a few hundred
    milliseconds, and we want the finished files, not the half-written ones.

    Runs until cancelled. `initial` is the snapshot the caller has already
    processed, so startup does not trigger a redundant rebuild.
    """
    last = snapshot(logs_dir, names) if initial is None else initial
    pending: Snapshot | None = None
    while True:
        await asyncio.sleep(interval)
        current = snapshot(logs_dir, names)
        if current == last:
            pending = None
            continue
        if pending is not None and current == pending:
            last = current
            pending = None
            await asyncio.to_thread(on_change)
        else:
            pending = current
