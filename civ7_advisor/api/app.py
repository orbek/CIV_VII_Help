"""FastAPI application factory."""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from civ7_advisor.advisors import tactical
from civ7_advisor.advisors.base import visible
from civ7_advisor.decisions import culture
from civ7_advisor.decisions.context import (
    PREVIEW_METRICS,
    ContextConflict,
    ContextStore,
    build_context,
)
from civ7_advisor.decisions.models import PlayerReport
from civ7_advisor.ingest.load import LOG_FILES
from civ7_advisor.ingest.poller import snapshot as poll_snapshot
from civ7_advisor.ingest.poller import watch
from civ7_advisor.llm.models import CommentaryResult
from civ7_advisor.llm.worker import CommentaryWorker
from civ7_advisor.store import Snapshot, Store

from .serialize import (
    INTEL_LIMIT,
    briefing_to_dict,
    commentary_to_dict,
    decisions_to_dict,
    insight_to_dict,
    intel_to_dict,
    state_to_dict,
    status_to_dict,
)

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
KEEPALIVE_SECONDS = 15

DISABLED_MESSAGE = "Local commentary is off; start with an Ollama model to enable it."
HIDDEN_MESSAGE = "Oracle off — this local commentary saw intercepted evidence."


def create_app(logs_dir: Path, poll_interval: float = 1.0, archive_root: Path | None = None,
               commentary_worker: CommentaryWorker | None = None) -> FastAPI:
    store = Store(logs_dir, archive_root, commentary_worker=commentary_worker)
    context_store = ContextStore()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        loop = asyncio.get_running_loop()
        initial = poll_snapshot(logs_dir, LOG_FILES)
        await asyncio.to_thread(store.rebuild)

        def on_change() -> None:  # runs in a worker thread
            captured = store.rebuild()
            loop.call_soon_threadsafe(store.publish, {
                "type": "state_changed", "turn": captured.analysis_turn,
                "latest_turn": captured.latest_turn, "revision": captured.revision,
                "session": captured.session, "epoch": captured.epoch,
            })

        task = asyncio.create_task(watch(logs_dir, LOG_FILES, on_change, poll_interval, initial))
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
        result = store.commentary_worker.result(captured, oracle)
        # Fair mode is generated from a fair prompt, so this should never fire. It stays
        # as the last gate: if a generation ever reports having read intercepted evidence,
        # fair mode withholds it rather than trusting the layer above to have filtered.
        if not oracle:
            for prose in (result.commentary, result.previous):
                if prose is not None and prose.saw_oracle:
                    return CommentaryResult("hidden", result.turn, HIDDEN_MESSAGE)
        return result

    def decisions_for(captured: Snapshot, oracle: bool) -> dict:
        """The decision brief for this snapshot, with its citations already resolved.

        The context store follows the snapshot's session first, so a reloaded game never
        inherits previews read off the previous one.
        """
        context_store.adopt(captured)
        context = build_context(captured, context_store.context(), oracle=oracle)
        cards = tuple(card for card in (culture.decide(context),) if card is not None)
        return decisions_to_dict(context, cards)

    @app.get("/api/briefing")
    def api_briefing(oracle: int = 1) -> dict:
        """Everything the dashboard renders, from one revision, already evidence-filtered."""
        captured = current()
        return briefing_to_dict(captured, bool(oracle),
                                commentary_result(captured, bool(oracle)),
                                decisions_for(captured, bool(oracle)))

    @app.get("/api/decisions")
    def api_decisions(oracle: int = 1) -> dict:
        return decisions_for(current(), bool(oracle))

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
        from civ7_advisor.advisors import intel
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


def _dependencies(captured: Snapshot, subject: str) -> dict[str, object]:
    """What a report about this subject depends on, as it stands now.

    Deliberately narrow. A settlement's queue row and the observed Age can change what a
    preview means; an unrelated rival event cannot, and must not discard it.
    """
    from civ7_advisor.advisors import production

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
