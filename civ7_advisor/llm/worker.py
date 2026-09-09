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
from .prompts import EXPLAIN_TOP_N, build_prompt, response_schema

log = logging.getLogger(__name__)


class CommentaryWorker:
    def __init__(self, client: OllamaClient) -> None:
        self.client = client
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="civ7-ollama")
        # A completed Future may invoke its callback synchronously while it is
        # being registered, so this lock must allow that callback to re-enter.
        self._lock = threading.RLock()
        self._results: dict[tuple[int, str], CommentaryResult] = {}
        self._futures: dict[tuple[int, str], Future] = {}
        self._current: dict[int, str] = {}
        self._active: tuple[int, str] | None = None
        self._pending: tuple[int, str, str, bool, list[Insight]] | None = None
        self._closed = False

    def schedule(self, state: GameState, insights: list[Insight]) -> None:
        turn = state.complete_through_turn
        if turn <= 0:
            return
        if not insights:
            with self._lock:
                self._current.pop(turn, None)
                if self._pending is not None and self._pending[0] == turn:
                    self._pending = None
            return
        prompt, saw_oracle = build_prompt(state, insights)
        digest = hashlib.sha256(prompt.encode()).hexdigest()
        key = (turn, digest)
        with self._lock:
            self._current[turn] = digest
            if key in self._results or key == self._active:
                return
            self._results[key] = CommentaryResult("generating", turn, "Local commentary is being generated.")
            request = (turn, digest, prompt, saw_oracle, list(insights))
            if self._active is None:
                self._start_locked(request)
            else:
                # Log files arrive in bursts. Keep only the newest not-yet-started
                # prompt rather than making the 31B model narrate stale snapshots.
                self._pending = request

    def _start_locked(self, request: tuple[int, str, str, bool, list[Insight]]) -> None:
        turn, digest, prompt, saw_oracle, insights = request
        key = (turn, digest)
        self._active = key
        future = self._executor.submit(
            self._generate, turn, digest, prompt, saw_oracle, insights
        )
        self._futures[key] = future
        future.add_done_callback(lambda _: self._finished(key))

    def _finished(self, key: tuple[int, str]) -> None:
        with self._lock:
            self._futures.pop(key, None)
            if self._active == key:
                self._active = None
            pending, self._pending = self._pending, None
            if pending is not None and not self._closed:
                pending_key = (pending[0], pending[1])
                if pending_key not in self._results or self._results[pending_key].status == "generating":
                    self._start_locked(pending)

    def _generate(self, turn: int, digest: str, prompt: str, saw_oracle: bool,
                  insights: list[Insight]) -> None:
        key = (turn, digest)
        valid_ids = {i.id for i in insights}
        top_ids = [i.id for i in insights[:EXPLAIN_TOP_N]]
        try:
            data = json.loads(self.client.generate(
                prompt, schema=response_schema(top_ids, valid_ids)
            ))
            if not isinstance(data.get("second_opinion"), str):
                raise ValueError("missing second_opinion")
            explanation_rows = data.get("explain", [])
            if not isinstance(explanation_rows, dict):
                raise ValueError("explain must be an object keyed by insight id")
            explanation_by_id = {str(insight_id): text for insight_id, text in explanation_rows.items()
                                 if insight_id in top_ids and isinstance(text, str) and text.strip()}
            if set(explanation_rows) != set(top_ids) or set(explanation_by_id) != set(top_ids):
                raise ValueError("commentary must explain every requested top insight exactly once")
            explanations = tuple(Explanation(insight_id, explanation_by_id[insight_id])
                                 for insight_id in top_ids)
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
            with self._lock:
                current = self._current.get(turn) == digest
            if current:
                log.warning("local commentary failed for turn %s: %s", turn, exc)
            else:
                log.debug("stale local commentary failed for turn %s: %s", turn, exc)
            result = CommentaryResult(
                "error", turn,
                "Local commentary could not finish this turn. The evidence-backed advice above is still complete."
            )
        except Exception as exc:  # the optional worker must never damage deterministic rebuilds
            log.exception("unexpected local commentary failure for turn %s", turn)
            result = CommentaryResult("error", turn, f"Local commentary failed: {exc}")
        with self._lock:
            self._results[key] = result

    def result(self, turn: int | None) -> CommentaryResult:
        if turn is None or turn <= 0:
            return CommentaryResult("idle", turn, "Commentary starts after a complete turn.")
        with self._lock:
            digest = self._current.get(turn)
            if digest is None:
                return CommentaryResult("idle", turn, "Commentary has not started yet.")
            return self._results.get((turn, digest), CommentaryResult(
                "idle", turn, "Commentary has not started yet."
            ))

    def wait(self, turn: int, timeout: float = 2.0) -> CommentaryResult:
        with self._lock:
            digest = self._current.get(turn)
            future = self._futures.get((turn, digest)) if digest is not None else None
        if future:
            future.result(timeout=timeout)
        return self.result(turn)

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._pending = None
        self._executor.shutdown(wait=False, cancel_futures=True)
