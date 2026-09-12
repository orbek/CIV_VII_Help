"""FastAPI application factory."""
from __future__ import annotations

import asyncio
import hashlib
import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from civ_advisor.advisors import tactical
from civ_advisor.advisors.base import visible
from civ_advisor.context_store import KINDS, PersistentContextStore, StoreError
from civ_advisor.decisions import changes as change_tracking
from civ_advisor.decisions import decide_all
from civ_advisor.decisions.context import (
    PREVIEW_METRICS,
    ContextConflict,
    ContextStore,
    build_context,
)
from civ_advisor.decisions.models import PlayerReport
from civ_advisor.games.base import GameProfile
from civ_advisor.ingest.poller import snapshot as poll_snapshot
from civ_advisor.ingest.poller import watch
from civ_advisor.llm import questions
from civ_advisor.llm.models import CommentaryResult
from civ_advisor.llm.worker import CommentaryWorker
from civ_advisor.store import Snapshot, Store

from .serialize import (
    INTEL_LIMIT,
    briefing_to_dict,
    changes_to_dict,
    commentary_to_dict,
    decisions_to_dict,
    insight_to_dict,
    intel_to_dict,
    player_record_to_dict,
    state_to_dict,
    status_to_dict,
)

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
KEEPALIVE_SECONDS = 15

DISABLED_MESSAGE = "Local commentary is off; start with an Ollama model to enable it."
HIDDEN_MESSAGE = "Oracle off — this local commentary saw intercepted evidence."


def create_app(logs_dir: Path, poll_interval: float = 1.0, archive_root: Path | None = None,
               commentary_worker: CommentaryWorker | None = None,
               player_store: PersistentContextStore | None = None,
               *, profile: GameProfile) -> FastAPI:
    context_store = ContextStore()
    history = change_tracking.History()
    record = player_store if player_store is not None else PersistentContextStore()
    record.load()

    def identity_provider(captured: Snapshot) -> dict:
        """The decision, context and catalog revisions that complete a generation's identity.

        `decision_revision` fingerprints the recommendations themselves, so prose written
        about a different preferred action cannot be shown as an explanation of this one —
        which is exactly what happens when the player supplies a preview while a
        generation is still running.
        """
        context_store.adopt(captured)
        context = build_context(captured, context_store.context())
        cards = decide_all(context)
        return {
            "decision_revision": decision_fingerprint(cards),
            "context_revision": context.context_revision,
            "catalog_revision": context.catalog_revision,
        }

    store = Store(logs_dir, archive_root, commentary_worker=commentary_worker,
                  identity_provider=identity_provider, profile=profile)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        loop = asyncio.get_running_loop()
        initial = poll_snapshot(logs_dir, profile.log_files)
        await asyncio.to_thread(store.rebuild)

        def on_change() -> None:  # runs in a worker thread
            captured = store.rebuild()
            loop.call_soon_threadsafe(store.publish, {
                "type": "state_changed", "turn": captured.analysis_turn,
                "latest_turn": captured.latest_turn, "revision": captured.revision,
                "session": captured.session, "epoch": captured.epoch,
            })

        task = asyncio.create_task(watch(logs_dir, profile.log_files, on_change, poll_interval, initial))
        try:
            yield
        finally:
            task.cancel()
            if store.commentary_worker is not None:
                store.commentary_worker.close()

    app = FastAPI(title="Civ VII Advisor", lifespan=lifespan)
    app.state.store = store
    app.state.context_store = context_store

    def current() -> Snapshot:
        """The published snapshot, or 503. Read once per request so no two sections of a
        response can come from different rebuilds."""
        captured = store.snapshot
        if captured is None or captured.state is None:
            raise HTTPException(status_code=503, detail="state not loaded yet")
        return captured

    def commentary_result(captured: Snapshot, oracle: bool) -> CommentaryResult:
        if store.commentary_worker is None:
            return CommentaryResult("disabled", captured.analysis_turn, DISABLED_MESSAGE)
        result = store.commentary_worker.result(captured, oracle, store.revisions(captured))
        # Fair mode is generated from a fair prompt, so this should never fire. It stays
        # as the last gate: if a generation ever reports having read intercepted evidence,
        # fair mode withholds it rather than trusting the layer above to have filtered.
        if not oracle:
            for prose in (result.commentary, result.previous):
                if prose is not None and prose.saw_oracle:
                    return CommentaryResult("hidden", result.turn, HIDDEN_MESSAGE)
        return result

    def brief_for(captured: Snapshot, oracle: bool):
        """(context, cards) for this snapshot, with the stores pointed at this sitting.

        Both stores follow the snapshot's session before anything is computed, so a
        reloaded game never inherits previews or acknowledgements from the previous one.
        """
        context_store.adopt(captured)
        record.adopt(captured.session, captured.epoch, captured.game_key,
                     captured.epoch_reason)
        context = build_context(captured, context_store.context(), oracle=oracle)
        return context, decide_all(context)

    def decisions_for(captured: Snapshot, oracle: bool) -> dict:
        """The decision brief for this snapshot, with its citations already resolved."""
        context, cards = brief_for(captured, oracle)
        return decisions_to_dict(context, cards)

    def changes_for(captured: Snapshot, oracle: bool) -> dict:
        """What moved since the previous turn of this sitting.

        The current turn is recorded first, then compared against the newest strictly
        earlier turn of the same session and epoch. A rebuild for a turn already recorded
        replaces it rather than adding one, so a burst of log writes is not history.
        """
        context, cards = brief_for(captured, oracle)
        return _changes(captured, oracle, context, cards)

    def _changes(captured: Snapshot, oracle: bool, context, cards) -> dict:
        entry = change_tracking.entry_from(
            captured, cards, context.catalog_revision, context.comparisons)
        previous = history.previous(entry)
        history.record(entry)
        return changes_to_dict(entry, previous, history,
                               change_tracking.compare(previous, entry),
                               record.of_kind("acknowledged"))

    @app.get("/api/briefing")
    def api_briefing(oracle: int = 1) -> dict:
        """Everything the dashboard renders, from one revision, already evidence-filtered."""
        captured = current()
        oracle_on = bool(oracle)
        context, cards = brief_for(captured, oracle_on)
        return briefing_to_dict(
            captured, oracle_on, commentary_result(captured, oracle_on),
            changes=_changes(captured, oracle_on, context, cards),
            record=player_record_to_dict(record),
            decisions=decisions_to_dict(context, cards))

    @app.get("/api/decisions")
    def api_decisions(oracle: int = 1) -> dict:
        return decisions_for(current(), bool(oracle))

    @app.get("/api/changes")
    def api_changes(oracle: int = 1) -> dict:
        return changes_for(current(), bool(oracle))

    @app.get("/api/record")
    def api_record() -> dict:
        """The player's own goals, watchlist and acknowledgements, plus anything held back
        from another sitting waiting to be associated."""
        captured = current()
        record.adopt(captured.session, captured.epoch, captured.game_key,
                     captured.epoch_reason)
        return player_record_to_dict(record)

    @app.post("/api/record", response_model=None)
    def api_write_record(body: dict = Body(...)):
        captured = current()
        record.adopt(captured.session, captured.epoch, captured.game_key,
                     captured.epoch_reason)
        try:
            entry = record.record(
                kind=str(body["kind"]), subject=str(body["subject"]),
                turn=int(body.get("turn", captured.analysis_turn)),
                text=str(body.get("text") or ""),
                fingerprint=str(body.get("fingerprint") or ""),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=f"malformed entry: {exc}") from exc
        except StoreError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"recorded": entry.id, "revision": record.revision,
                "kinds": list(KINDS), "error": record.last_error}

    @app.delete("/api/record/{entry_id}")
    def api_forget_record(entry_id: str) -> dict:
        return {"removed": record.forget(entry_id), "revision": record.revision,
                "error": record.last_error}

    @app.post("/api/record/associate", response_model=None)
    def api_associate(body: dict = Body(...)):
        """Adopt entries from another sitting, because the player said they belong here.

        Never automatic: after a reload the advisor cannot tell whether this is the same
        line of play, and an acknowledgement carried across silently could hide a live
        alert.
        """
        current()
        try:
            session, epoch = str(body["session"]), int(body["epoch"])
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        try:
            if body.get("discard"):
                return {"discarded": record.discard(session, epoch),
                        "revision": record.revision}
            adopted = record.associate(session, epoch)
        except StoreError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"associated": [e.id for e in adopted], "revision": record.revision}

    @app.post("/api/question", response_model=None)
    def api_question(body: dict = Body(...)):
        """Ask one question about one decision.

        The deterministic answer comes back immediately in every case. When a local model
        is available its prose replaces that answer once it has been generated *and*
        validated against this decision's own ids — so a slow model delays nothing and a
        fabricated citation is never rendered.
        """
        captured = current()
        oracle = bool(int(body.get("oracle", 1)))
        kind = str(body.get("kind", ""))
        decision_id = str(body.get("decision_id", ""))
        context, cards = brief_for(captured, oracle)
        brief = decisions_to_dict(context, cards)
        decision = next((c for c in brief["cards"] if c["id"] == decision_id), None)
        if decision is None:
            raise HTTPException(status_code=404, detail=f"no decision {decision_id!r} "
                                                        "in this brief")
        cited = set(decision["evidence_ids"])
        for candidate in [decision["preferred"]] + list(decision["alternatives"] or ()):
            if candidate:
                cited.update(candidate["evidence_ids"])
        # The evidence is filtered here, before the prompt exists. In fair mode an Oracle
        # fact never reaches the request, so it cannot reach the model or the cache key.
        evidence = [f for f in brief["evidence"]
                    if f["id"] in cited and (oracle or f["provenance"] == "fair")]
        guide_ids = {g for candidate in [decision["preferred"]]
                     + list(decision["alternatives"] or ()) if candidate
                     for g in candidate["guide_ids"]}
        guides = [g for g in brief["guides"] if g["id"] in guide_ids]
        identity = dict(brief["context"], turn=captured.analysis_turn)
        try:
            request = questions.build_request(
                kind, decision, evidence, guides, identity,
                player_text=str(body.get("text") or ""))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if store.commentary_worker is None:
            answerable, missing = questions.answerable(request)
            status = "fallback" if answerable else "unsupported"
            answer = (questions.fallback(request) if answerable
                      else questions.Answer(questions.UNSUPPORTED, (), (), (), missing, False))
        else:
            status, answer = store.commentary_worker.answer(request)
        return {
            "kind": kind, "decision_id": decision_id, "status": status,
            "evidence_mode": request.evidence_mode,
            "answer": {
                "text": answer.text, "evidence_ids": list(answer.evidence_ids),
                "action_ids": list(answer.action_ids), "guide_ids": list(answer.guide_ids),
                "unknowns": list(answer.unknowns), "generated": answer.generated,
                "model": answer.model,
            },
        }

    @app.get("/api/context")
    def api_context() -> dict:
        """What the player has told us, and which fields the panel collects."""
        captured = current()
        context_store.adopt(captured)
        held = context_store.context()
        return {
            "session": held.session, "epoch": context_store.epoch,
            "revision": held.revision,
            "preview_metrics": PREVIEW_METRICS,
            "reports": [
                {"id": r.id, "subject": r.subject, "label": r.label, "value": r.value,
                 "unit": r.unit, "observed_turn": r.observed_turn,
                 "reported_at": r.reported_at, "base_revision": r.base_revision}
                for r in held.reports
            ],
        }

    @app.post("/api/context", response_model=None)
    def api_submit_context(body: dict = Body(...)):
        """Accept one player report.

        The submission must carry the session, epoch and context revision it was rendered
        against. A mismatch is answered with 409 and the current context rather than being
        silently applied or silently dropped — the player has to be able to see what
        changed and confirm again.
        """
        captured = current()
        context_store.adopt(captured)
        try:
            report = PlayerReport(
                id=str(body["id"]), subject=str(body["subject"]), label=str(body["label"]),
                value=body.get("value"), unit=body.get("unit"),
                observed_turn=int(body["observed_turn"]), session=str(body["session"]),
                reported_at=str(body["reported_at"]), note=body.get("note"),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=f"malformed report: {exc}") from exc
        try:
            accepted = context_store.submit(
                report, epoch=int(body.get("epoch", 0)),
                base_revision=int(body.get("base_revision", -1)),
                dependencies=body.get("dependencies") or {},
                current_dependencies=_dependencies(captured, report.subject),
            )
        except ContextConflict as conflict:
            return JSONResponse(status_code=409, content={
                "reason": conflict.reason, "detail": conflict.detail,
                "session": conflict.current.session, "revision": conflict.current.revision,
                "epoch": context_store.epoch,
            })
        return {"accepted": accepted.id, "revision": context_store.revision}

    @app.delete("/api/context/{report_id}")
    def api_clear_context(report_id: str) -> dict:
        removed = context_store.clear(report_id)
        return {"removed": removed, "revision": context_store.revision}

    @app.get("/api/status")
    def api_status(oracle: int = 1) -> dict:
        return status_to_dict(current(), bool(oracle))

    @app.get("/api/state")
    def api_state(oracle: int = 1) -> dict:
        return state_to_dict(current().state, oracle=bool(oracle))

    @app.get("/api/insights")
    def api_insights(oracle: int = 1) -> list[dict]:
        return [insight_to_dict(i) for i in visible(current().insights, bool(oracle))]

    @app.get("/api/intel")
    def api_intel(oracle: int = 1) -> list[dict]:
        from civ_advisor.advisors import intel
        events = visible(intel.feed(current().state), bool(oracle))
        return [intel_to_dict(e) for e in events[:INTEL_LIMIT]]

    @app.get("/api/tactical")
    def api_tactical(oracle: int = 1) -> dict:
        captured = current()
        if not oracle:
            return {"available": False, "reason": "oracle_off"}
        return tactical.snapshot(captured.state)

    @app.get("/api/commentary")
    def api_commentary(oracle: int = 1) -> dict:
        captured = current()
        return commentary_to_dict(commentary_result(captured, bool(oracle)))

    @app.get("/events")
    async def events() -> StreamingResponse:
        return StreamingResponse(
            _event_stream(store), media_type="text/event-stream",
            headers={"Cache-Control": "no-cache"},
        )

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
    return app


def decision_fingerprint(cards) -> str:
    """A stable digest of the decisions on screen.

    Covers each card's id and severity, its preferred and alternative action ids, and the
    evidence behind them — everything whose change would make an explanation of the old
    recommendation misleading.
    """
    parts = []
    for card in cards:
        parts.append(f"{card.id}:{card.severity.name}")
        for candidate in card.candidates:
            parts.append(f"{candidate.id}:{candidate.applicability.value}")
        parts.extend(sorted(card.evidence_ids))
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16] if parts else ""


def _dependencies(captured: Snapshot, subject: str) -> dict[str, object]:
    """What a report about this subject depends on, as it stands now.

    Deliberately narrow. A settlement's queue row and the observed Age can change what a
    preview means; an unrelated rival event cannot, and must not discard it.
    """
    from civ_advisor.advisors import production

    row = next((q for q in production.queues(captured.state).get(captured.state.HUMAN, [])
                if q.city == subject), None)
    events = [e for e in captured.state.events if e.turn <= captured.analysis_turn and e.age]
    return {
        "queue": None if row is None else f"{row.item}@{row.turn}",
        "age": max(events, key=lambda e: e.turn).age if events else None,
        "session": captured.session,
    }


async def _event_stream(store: Store):
    queue = store.subscribe()
    try:
        yield "retry: 2000\n\n"
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=KEEPALIVE_SECONDS)
                yield f"data: {json.dumps(event)}\n\n"
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
    finally:
        store.unsubscribe(queue)
