"""Owns the current GameState and ranked insights; rebuilds, archives, and fans out change events."""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

from civ7_advisor.advisors import Insight, run_all
from civ7_advisor.archive import UNKNOWN_GAME, archive_logs, game_key
from civ7_advisor.ingest.load import load_logs
from civ7_advisor.state.build import build_state
from civ7_advisor.state.models import GameState

if TYPE_CHECKING:
    from civ7_advisor.llm.worker import CommentaryWorker

log = logging.getLogger(__name__)

ARCHIVE_SUFFIXES = {".csv", ".log"}  # mirror every log the game writes, not just the ones we parse


class Store:
    def __init__(self, logs_dir: Path, archive_root: Path | None = None,
                 commentary_worker: CommentaryWorker | None = None) -> None:
        self.logs_dir = logs_dir
        self.archive_root = archive_root
        self.state: GameState | None = None
        self.insights: list[Insight] = []
        self._lock = threading.Lock()
        self._subscribers: set[asyncio.Queue] = set()
        self._session: str | None = None   # one archive session per life of the logs directory
        self._game_key: str | None = None  # the loaded save's identity, read once per session
        self._session_seq = 0              # keeps two sessions started in the same second distinct
        self.commentary_worker = commentary_worker

    def rebuild(self) -> GameState:
        """Re-read every log, archive it, and recompute advice. Safe to call from a worker thread."""
        raw = load_logs(self.logs_dir)
        state = build_state(raw)
        insights = run_all(state)
        with self._lock:
            self.state, self.insights = state, insights
        self._archive(raw)
        if self.commentary_worker is not None:
            self.commentary_worker.schedule(state, insights)
        return state

    def _archive(self, raw) -> None:
        if self.archive_root is None:
            return
        if not raw.stats:            # the directory was wiped (game relaunch): next data is a new session
            self._session = self._game_key = None
            return
        try:
            if self._session is None:
                self._game_key = game_key(self.logs_dir) or UNKNOWN_GAME
                self._session_seq += 1
                self._session = f"{time.strftime('%Y%m%dT%H%M%S')}-{self._session_seq}"
            names = sorted(p.name for p in self.logs_dir.iterdir() if p.suffix in ARCHIVE_SUFFIXES)
            archive_logs(self.logs_dir, self.archive_root / self._game_key / self._session, names)
        except Exception:            # archiving must never cost the player their advice
            log.exception("archiving failed; continuing without it")

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    def publish(self, event: dict) -> None:
        """Deliver an event to every subscriber. Call on the event-loop thread."""
        for q in list(self._subscribers):
            q.put_nowait(event)
