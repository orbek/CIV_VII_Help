"""Single background generator with a per-identity cache.

One generation runs at a time. Requests are keyed by the full commentary identity —
session, evidence mode, turn and prompt digest — so a result can never be shown beside
a decision context it was not written about, and a fair-mode request is generated from a
fair-mode prompt rather than filtered after the fact.
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, replace

from civ7_advisor.store import Snapshot

from . import questions
from .client import OllamaClient, OllamaError
from .models import Commentary, CommentaryIdentity, CommentaryResult, Explanation, PlanStep
from .prompts import EXPLAIN_TOP_N, build_prompt, response_schema

log = logging.getLogger(__name__)

QUEUED = "Local commentary is queued behind another generation."
GENERATING = "Local commentary is being generated."
FAILED = ("Local commentary could not finish this turn. "
          "The evidence-backed advice above is still complete.")


@dataclass(frozen=True)
class _Request:
    identity: CommentaryIdentity
    digest: str
    prompt: str
    saw_oracle: bool
    top_ids: tuple[str, ...]

    @property
    def key(self) -> tuple[str, str, int, str]:
        i = self.identity
        return (i.session, i.evidence_mode, i.turn, self.digest)


class CommentaryWorker:
    def __init__(self, client: OllamaClient) -> None:
        self.client = client
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="civ7-ollama")
        # A completed Future may invoke its callback synchronously while it is
        # being registered, so this lock must allow that callback to re-enter.
        self._lock = threading.RLock()
        self._results: dict[tuple, CommentaryResult] = {}
        self._futures: dict[tuple, Future] = {}
        self._current: dict[tuple[str, str, int], tuple] = {}  # session/mode/turn -> newest key
        self._ready: dict[tuple[str, str], Commentary] = {}    # session/mode -> newest ready
        self._active: tuple | None = None
        self._pending: _Request | None = None
        # Questions run on their own single-worker pool. A turn's commentary can take a
        # 31B model minutes; a question the player just asked must not queue behind it,
        # and neither may block a rebuild or the refinement workflow.
        self._questions = ThreadPoolExecutor(max_workers=1, thread_name_prefix="civ7-answer")
        self._answers: dict[tuple, questions.Answer | str] = {}
        self._answer_futures: dict[tuple, Future] = {}
        self._closed = False

    # ---- scheduling -------------------------------------------------------------

    def schedule(self, snapshot: Snapshot, oracle: bool = True,
                 revisions: dict | None = None) -> None:
        """Queue the generation for this snapshot in one evidence mode.

        The store calls this after each rebuild for the default (oracle) mode. Fair mode
        is scheduled on demand by `result`, so a player who never turns intercepts off
        never pays for a second generation — and one who does gets commentary rather
        than a permanently hidden panel.
        """
        request = self._request(snapshot, oracle, revisions)
        if request is None:
            key = self._slot(snapshot, oracle)
            with self._lock:
                self._current.pop(key, None)
                if self._pending is not None and self._pending.key[:3] == key:
                    self._pending = None
            return
        with self._lock:
            self._enqueue_locked(request)

    def _slot(self, snapshot: Snapshot, oracle: bool) -> tuple[str, str, int]:
        return (snapshot.session, "oracle" if oracle else "fair", snapshot.analysis_turn)

    def _request(self, snapshot: Snapshot, oracle: bool,
                 revisions: dict | None = None) -> _Request | None:
        """The request for this snapshot and mode, or None when there is nothing to narrate."""
        if snapshot.analysis_turn <= 0:
            return None
        prompt, saw_oracle, insight_ids = build_prompt(
            snapshot.state, list(snapshot.insights), oracle
        )
        if not insight_ids:                 # nothing survived filtering: nothing to explain
            return None
        identity = CommentaryIdentity(
            session=snapshot.session, epoch=snapshot.epoch,
            evidence_mode="oracle" if oracle else "fair",
            snapshot_revision=snapshot.revision, turn=snapshot.analysis_turn,
            insight_ids=tuple(insight_ids),
            decision_revision=str((revisions or {}).get("decision_revision", "")),
            context_revision=int((revisions or {}).get("context_revision", 0)),
            catalog_revision=str((revisions or {}).get("catalog_revision", "")),
        )
        return _Request(identity, hashlib.sha256(prompt.encode()).hexdigest(), prompt,
                        saw_oracle, tuple(insight_ids[:EXPLAIN_TOP_N]))

    def _enqueue_locked(self, request: _Request) -> None:
        key, slot = request.key, request.key[:3]
        self._current[slot] = key
        existing = self._results.get(key)
        if existing is not None and existing.status in ("ready", "error"):
            return                          # already generated for this exact evidence
        if key == self._active:
            return
        if self._active is None:
            self._start_locked(request)
            return
        # Log files arrive in bursts. Keep only the newest not-yet-started prompt rather
        # than making a 31B model narrate stale snapshots — and drop the replaced
        # request's placeholder, or that prompt would be cached as forever-generating
        # and an A -> B -> C -> B sequence would leave B spinning with nothing running.
        if self._pending is not None and self._pending.key != key:
            self._results.pop(self._pending.key, None)
        self._pending = request
        self._results[key] = CommentaryResult("queued", request.identity.turn, QUEUED)

    def _start_locked(self, request: _Request) -> None:
        self._active = request.key
        self._results[request.key] = CommentaryResult("generating", request.identity.turn, GENERATING)
        future = self._executor.submit(self._generate, request)
        self._futures[request.key] = future
        future.add_done_callback(lambda _: self._finished(request.key))

    def _finished(self, key: tuple) -> None:
        with self._lock:
            self._futures.pop(key, None)
            if self._active == key:
                self._active = None
            pending, self._pending = self._pending, None
            if pending is not None and not self._closed:
                held = self._results.get(pending.key)
                if held is None or held.status not in ("ready", "error"):
                    self._start_locked(pending)

    # ---- generation -------------------------------------------------------------

    def _generate(self, request: _Request) -> None:
        identity, top_ids = request.identity, list(request.top_ids)
        valid_ids = set(identity.insight_ids)
        turn = identity.turn
        try:
            data = json.loads(self.client.generate(
                request.prompt, schema=response_schema(top_ids, valid_ids)
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
            commentary = Commentary(self.client.model, request.digest, turn, request.saw_oracle,
                                    data["second_opinion"], explanations, plan, identity)
            result = CommentaryResult("ready", turn, "", commentary)
        except (OllamaError, json.JSONDecodeError, ValueError, KeyError) as exc:
            with self._lock:
                current = self._current.get(request.key[:3]) == request.key
            if current:
                log.warning("local commentary failed for turn %s: %s", turn, exc)
            else:
                log.debug("stale local commentary failed for turn %s: %s", turn, exc)
            result = CommentaryResult("error", turn, FAILED)
        except Exception as exc:  # the optional worker must never damage deterministic rebuilds
            log.exception("unexpected local commentary failure for turn %s", turn)
            result = CommentaryResult("error", turn, f"Local commentary failed: {exc}")
        with self._lock:
            self._results[request.key] = result
            if result.commentary is not None:
                # Newest ready prose per session and mode, for the dated history panel.
                # A finishing generation for a turn we have already moved past must not
                # displace a newer one, so compare turns before replacing.
                slot = request.key[:2]
                held = self._ready.get(slot)
                if held is None or held.turn <= turn:
                    self._ready[slot] = result.commentary

    # ---- reading ----------------------------------------------------------------

    def result(self, snapshot: Snapshot | None, oracle: bool = True,
               revisions: dict | None = None) -> CommentaryResult:
        """The commentary for this exact snapshot and evidence mode, scheduling it if needed."""
        if snapshot is None or snapshot.analysis_turn <= 0:
            turn = None if snapshot is None else snapshot.analysis_turn
            return CommentaryResult("idle", turn, "Commentary starts after a complete turn.")
        request = self._request(snapshot, oracle, revisions)
        if request is None:
            return CommentaryResult("idle", snapshot.analysis_turn,
                                    "There is nothing to narrate for this turn.")
        with self._lock:
            held = self._results.get(request.key)
            if held is None:
                self._enqueue_locked(request)
                held = self._results.get(request.key) or CommentaryResult(
                    "queued", request.identity.turn, QUEUED)
            previous = self._ready.get(request.key[:2])
            stale_but_offerable = (
                held.commentary is None and previous is not None
                and previous.identity != request.identity
                and request.identity.same_session(previous.identity)
            )
            return replace(held, previous=previous if stale_but_offerable else None)

    def wait(self, snapshot: Snapshot, oracle: bool = True, timeout: float = 2.0,
             revisions: dict | None = None) -> CommentaryResult:
        """Block until this snapshot's generation reaches a terminal state, or `timeout`.

        For tests and for the CLI smoke check. Scheduling comes first — a caller may not
        have scheduled it yet — and a request sitting in the queue has no future to wait
        on until the active generation hands over, so poll across that handover rather
        than reporting "generating" and giving up.
        """
        request = self._request(snapshot, oracle, revisions)
        if request is None:
            return self.result(snapshot, oracle, revisions)
        deadline = time.monotonic() + timeout
        while True:
            with self._lock:
                if request.key not in self._results:
                    self._enqueue_locked(request)
                held = self._results.get(request.key)
                future = self._futures.get(request.key)
            if held is not None and held.status in ("ready", "error"):
                return self.result(snapshot, oracle, revisions)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return self.result(snapshot, oracle, revisions)
            if future is not None:
                try:
                    future.result(timeout=remaining)
                except Exception:      # _generate records its own failures
                    pass
            else:
                time.sleep(0.005)      # queued behind another generation

    # ---- questions ---------------------------------------------------------------

    def answer(self, request: questions.QuestionRequest) -> tuple[str, questions.Answer]:
        """(status, answer) for one question. Never blocks.

        Statuses: "ready" for a validated generation, "fallback" for the deterministic
        answer — which is what the caller shows immediately while a generation runs, and
        what it keeps if one fails or is rejected — and "generating" alongside that
        fallback while the model works.

        The deterministic answer is always available, so a slow or absent model delays
        nothing: the player reads the structured version now and the prose replaces it
        when and if it arrives.
        """
        answerable, missing = questions.answerable(request)
        if not answerable:
            return "unsupported", questions.Answer(
                text=questions.UNSUPPORTED, evidence_ids=(), action_ids=(), guide_ids=(),
                unknowns=missing, generated=False)
        key = request.cache_key
        with self._lock:
            held = self._answers.get(key)
            if isinstance(held, questions.Answer):
                return "ready", held
            if held is not None:                       # a recorded rejection or failure
                return "fallback", questions.fallback(request, held)
            running = key in self._answer_futures
            if not running and not self._closed:
                future = self._questions.submit(self._generate_answer, request)
                self._answer_futures[key] = future
                future.add_done_callback(lambda _: self._answer_done(key))
                running = True
        return ("generating" if running else "fallback"), questions.fallback(request)

    def _answer_done(self, key: tuple) -> None:
        with self._lock:
            self._answer_futures.pop(key, None)

    def _generate_answer(self, request: questions.QuestionRequest) -> None:
        key = request.cache_key
        try:
            data = json.loads(self.client.generate(
                questions.prompt_for(request), schema=questions.response_schema(request)))
            answer = questions.validate(request, data)
            result: questions.Answer | str = questions.Answer(
                **{**answer.__dict__, "model": self.client.model})
        except (OllamaError, json.JSONDecodeError, ValueError, KeyError) as exc:
            # A rejection is recorded as a reason, so the fallback can say why the prose is
            # missing rather than silently looking like there was never a model.
            log.warning("question %s for %s rejected: %s", request.kind,
                        request.decision_id, exc)
            result = f"the generated answer was rejected: {exc}"
        except Exception as exc:  # pragma: no cover - the optional path must never bite
            log.exception("unexpected question failure")
            result = f"the model failed: {exc}"
        with self._lock:
            self._answers[key] = result

    def wait_for_answer(self, request: questions.QuestionRequest,
                        timeout: float = 2.0) -> tuple[str, questions.Answer]:
        """Block until this question reaches a terminal state. Tests and the smoke check."""
        status, answer = self.answer(request)
        deadline = time.monotonic() + timeout
        while status == "generating" and time.monotonic() < deadline:
            with self._lock:
                future = self._answer_futures.get(request.cache_key)
            if future is None:
                time.sleep(0.005)
            else:
                try:
                    future.result(timeout=max(deadline - time.monotonic(), 0.01))
                except Exception:
                    pass
            status, answer = self.answer(request)
        return status, answer

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._pending = None
        self._executor.shutdown(wait=False, cancel_futures=True)
        self._questions.shutdown(wait=False, cancel_futures=True)
