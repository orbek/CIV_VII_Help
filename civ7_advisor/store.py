"""Owns the current GameState and ranked insights; rebuilds and fans out change events."""
from __future__ import annotations

import asyncio
import threading
from pathlib import Path

from civ7_advisor.advisors import Insight, run_all
from civ7_advisor.ingest.load import load_logs
from civ7_advisor.state.build import build_state
from civ7_advisor.state.models import GameState


class Store:
    def __init__(self, logs_dir: Path) -> None:
        self.logs_dir = logs_dir
        self.state: GameState | None = None
        self.insights: list[Insight] = []
        self._lock = threading.Lock()
        self._subscribers: set[asyncio.Queue] = set()

    def rebuild(self) -> GameState:
        """Re-read every log and recompute advice. Safe to call from a worker thread."""
        state = build_state(load_logs(self.logs_dir))
        insights = run_all(state)
        with self._lock:
            self.state, self.insights = state, insights
        return state

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
