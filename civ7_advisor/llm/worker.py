"""Single background generator with a per-complete-turn cache."""
from __future__ import annotations

import hashlib
import json
import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor

from civ7_advisor.advisors import Insight
from civ7_advisor.state.models import GameState

from .client import OllamaClient, OllamaError
from .models import Commentary, CommentaryResult, Explanation, PlanStep
from .prompts import EXPLAIN_TOP_N, build_prompt

log = logging.getLogger(__name__)


class CommentaryWorker:
    def __init__(self, client: OllamaClient) -> None:
        self.client = client
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="civ7-ollama")
        self._lock = threading.Lock()
        self._results: dict[int, CommentaryResult] = {}
        self._futures: dict[int, Future] = {}

    def schedule(self, state: GameState, insights: list[Insight]) -> None:
        turn = state.complete_through_turn
        if turn <= 0:
            return
        with self._lock:
            if turn in self._results or turn in self._futures:
                return
            self._results[turn] = CommentaryResult("generating", turn, "Local commentary is being generated.")
            future = self._executor.submit(self._generate, state, list(insights))
            self._futures[turn] = future
            future.add_done_callback(lambda _: self._finished(turn))

    def _finished(self, turn: int) -> None:
        with self._lock:
            self._futures.pop(turn, None)

    def _generate(self, state: GameState, insights: list[Insight]) -> None:
        turn = state.complete_through_turn
        prompt, saw_oracle = build_prompt(state, insights)
        digest = hashlib.sha256(prompt.encode()).hexdigest()
        valid_ids = {i.id for i in insights}
        top_ids = {i.id for i in insights[:EXPLAIN_TOP_N]}
        try:
            data = json.loads(self.client.generate(prompt))
            if not isinstance(data.get("second_opinion"), str):
                raise ValueError("missing second_opinion")
            explanations = tuple(
                Explanation(str(row["insight_id"]), str(row["text"])) for row in data.get("explain", [])
                if isinstance(row, dict) and row.get("insight_id") in top_ids and isinstance(row.get("text"), str)
            )
            plan = tuple(
                PlanStep(str(row["insight_id"]), str(row["step"])) for row in data.get("turn_plan", [])
                if isinstance(row, dict) and row.get("insight_id") in valid_ids and isinstance(row.get("step"), str)
            )
            if not explanations or not plan:
                raise ValueError("commentary omitted cited explanations or plan steps")
            commentary = Commentary(self.client.model, digest, turn, saw_oracle,
                                    data["second_opinion"], explanations, plan)
            result = CommentaryResult("ready", turn, "", commentary)
        except (OllamaError, json.JSONDecodeError, ValueError, KeyError) as exc:
            log.warning("local commentary failed for turn %s: %s", turn, exc)
            result = CommentaryResult("error", turn, str(exc))
        except Exception as exc:  # the optional worker must never damage deterministic rebuilds
            log.exception("unexpected local commentary failure for turn %s", turn)
            result = CommentaryResult("error", turn, f"Local commentary failed: {exc}")
        with self._lock:
            self._results[turn] = result

    def result(self, turn: int | None) -> CommentaryResult:
        if turn is None or turn <= 0:
            return CommentaryResult("idle", turn, "Commentary starts after a complete turn.")
        with self._lock:
            return self._results.get(turn, CommentaryResult("idle", turn, "Commentary has not started yet."))

    def wait(self, turn: int, timeout: float = 2.0) -> CommentaryResult:
        with self._lock:
            future = self._futures.get(turn)
        if future:
            future.result(timeout=timeout)
        return self.result(turn)

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
