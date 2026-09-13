"""One background thread for the conversation. Never blocks a request.

`ask` returns immediately with the deterministic answer and a status; the model's prose,
if it arrives and passes validation, replaces it on the next poll of the same request.
A rejection is recorded with its reason, so the page can say WHY the prose is missing
rather than looking as if there had never been a model.

The cache key is the whole request identity (session, epoch, evidence mode, snapshot and
context revisions, the player's words, the depth of the transcript). A generation that
finishes after the context moved on is therefore never served beside the new context: its
key no longer matches, and the new request generates its own answer. That is the same rule
llm/worker.py applies to commentary, for the same reason.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor

from civ_advisor.llm.client import OllamaClient, OllamaError

from . import conversation as conv

log = logging.getLogger(__name__)


class CopilotWorker:
    def __init__(self, client: OllamaClient) -> None:
        self.client = client
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="civ-copilot")
        # A finished Future may run its callback while it is still being registered,
        # so the lock has to be re-entrant.
        self._lock = threading.RLock()
        self._done: dict[tuple, tuple[str, conv.ChatAnswer, conv.Resolved, str]] = {}
        self._futures: dict[tuple, Future] = {}
        self._closed = False

    def ask(self, request: conv.ChatRequest) -> tuple[str, conv.ChatAnswer, conv.Resolved, str]:
        """(status, answer, resolved, rejection). Statuses: generating | ready | rejected."""
        key = request.cache_key
        with self._lock:
            held = self._done.get(key)
            if held is not None:
                return held
            if key not in self._futures and not self._closed:
                future = self._pool.submit(self._run, request)
                self._futures[key] = future
                future.add_done_callback(lambda _: self._forget(key))
        return "generating", conv.fallback(request, conv.Resolved()), conv.Resolved(), ""

    def _forget(self, key: tuple) -> None:
        with self._lock:
            self._futures.pop(key, None)

    def _run(self, request: conv.ChatRequest) -> None:
        key = request.cache_key
        resolved = conv.Resolved()
        try:
            chosen = json.loads(self.client.generate(
                conv.select_prompt(request), schema=conv.select_schema(request)))
            selected = conv.parse_selection(request, chosen)
            resolved = conv.resolve(request, selected)
            composed = json.loads(self.client.generate(
                conv.compose_prompt(request, resolved),
                schema=conv.compose_schema(request, resolved)))
            answer = conv.validate_answer(request, resolved, composed)
            result = ("ready", conv.ChatAnswer(**{**answer.__dict__, "model": self.client.model}),
                      resolved, "")
        except (OllamaError, json.JSONDecodeError, ValueError, KeyError, TypeError) as exc:
            log.warning("copilot answer rejected: %s", exc)
            result = ("rejected", conv.fallback(request, resolved, str(exc)), resolved, str(exc))
        except Exception as exc:  # pragma: no cover - the optional path must never bite
            log.exception("unexpected copilot failure")
            result = ("rejected", conv.fallback(request, resolved, str(exc)), resolved, str(exc))
        with self._lock:
            self._done[key] = result

    def wait_all(self, timeout: float = 2.0) -> None:
        """Tests and the smoke check: block until every running exchange is done."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                pending = list(self._futures.values())
            if not pending:
                return
            for f in pending:
                try:
                    f.result(timeout=max(deadline - time.monotonic(), 0.01))
                except Exception:
                    pass

    def close(self) -> None:
        with self._lock:
            self._closed = True
        self._pool.shutdown(wait=False, cancel_futures=True)


__all__ = ["CopilotWorker"]
