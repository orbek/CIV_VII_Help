"""One background thread for the conversation's PROSE. Never blocks on the prose.

`ask` returns the deterministic answer and a status; the model's prose, if it arrives
and passes validation, replaces it on the next poll of the same request. A rejection is
recorded with its reason, so the page can say WHY the prose is missing rather than
looking as if there had never been a model.

WHICH HALF RUNS WHERE, AND WHY THE SELECTION IS NOT IN THE BACKGROUND. An exchange is
select (which questions) -> resolve (the advisor's own answer) -> compose (prose around
it). Only compose is a guess that may be thrown away; select+resolve IS the deterministic
answer, and until it has run there is nothing to show. It used to run inside the
background thread, so the first poll had no resolution at all and `ask` answered with
`fallback(request, Resolved())` -- an empty resolution, whose fallback appends the CANNOT
sentence. The player read "The advisor cannot see that" underneath a label saying a model
was writing an interpretation of it, on EVERY question, when nothing had been looked up
yet and most of them were about to be answered.

So select+resolve now runs in the calling thread, once per request identity and cached
under the same key the answer is, and only compose is submitted to the pool. A poll of a
generation already running reuses that resolution and never asks the model to select
again. The cost is one select call on the first poll of a new question; what it buys is
that the deterministic answer is real and present from that first poll, and the
generation only ever REPLACES it.

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
        # The resolution for each request identity, and one lock per identity so two
        # polls that arrive together select once rather than twice. The model call that
        # produces it must never be made while holding `self._lock`.
        self._resolved: dict[tuple, conv.Resolved] = {}
        self._resolving: dict[tuple, threading.Lock] = {}
        self._closed = False

    def ask(self, request: conv.ChatRequest) -> tuple[str, conv.ChatAnswer, conv.Resolved, str]:
        """(status, answer, resolved, rejection). Statuses: generating | ready | rejected.

        The deterministic answer is built here, on every request, and returned with it --
        see the module docstring for why this half is not in the background thread.
        """
        key = request.cache_key
        with self._lock:
            held = self._done.get(key)
            if held is not None:
                return held
        try:
            resolved = self._resolution(request)
        except (OllamaError, json.JSONDecodeError, ValueError, KeyError, TypeError) as exc:
            # The selection itself failed, so there is no deterministic answer to show
            # and no prose to wait for. Recorded as the result for this request, so the
            # page says what failed instead of polling a generation that will not come.
            log.warning("copilot selection failed: %s", exc)
            return self._selection_failed(key, request, exc)
        except Exception as exc:  # the optional path must never bite the request
            log.exception("unexpected copilot selection failure")
            return self._selection_failed(key, request, exc)
        with self._lock:
            held = self._done.get(key)
            if held is not None:
                return held
            if key not in self._futures and not self._closed:
                future = self._pool.submit(self._run, request, resolved)
                self._futures[key] = future
                future.add_done_callback(lambda _: self._forget(key))
        return "generating", conv.fallback(request, resolved), resolved, ""

    def _selection_failed(self, key: tuple, request: conv.ChatRequest, exc: Exception):
        result = ("rejected", conv.fallback(request, conv.Resolved(), str(exc)),
                  conv.Resolved(), str(exc))
        with self._lock:
            self._done[key] = result
            self._resolving.pop(key, None)
        return result

    def _resolution(self, request: conv.ChatRequest) -> conv.Resolved:
        """Select and resolve once per request identity. Raises what the model call and
        the parse raise; `ask` is what turns that into a stated rejection."""
        key = request.cache_key
        with self._lock:
            held = self._resolved.get(key)
            if held is not None:
                return held
            gate = self._resolving.setdefault(key, threading.Lock())
        with gate:
            with self._lock:
                held = self._resolved.get(key)
            if held is not None:
                return held
            chosen = json.loads(self.client.generate(
                conv.select_prompt(request), schema=conv.select_schema(request)))
            resolved = conv.resolve(request, conv.parse_selection(request, chosen))
            with self._lock:
                self._resolved[key] = resolved
            return resolved

    def _forget(self, key: tuple) -> None:
        with self._lock:
            self._futures.pop(key, None)

    def _run(self, request: conv.ChatRequest, resolved: conv.Resolved) -> None:
        """The prose, around a resolution that already exists and is already on screen."""
        key = request.cache_key
        try:
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
            # The resolution travels with the finished result from here on.
            self._resolved.pop(key, None)
            self._resolving.pop(key, None)

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
