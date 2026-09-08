"""FastAPI application factory."""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from civ7_advisor.ingest.load import LOG_FILES
from civ7_advisor.ingest.poller import snapshot, watch
from civ7_advisor.store import Store

from .serialize import insight_to_dict, state_to_dict

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
KEEPALIVE_SECONDS = 15


def create_app(logs_dir: Path, poll_interval: float = 1.0, archive_root: Path | None = None) -> FastAPI:
    store = Store(logs_dir, archive_root)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        loop = asyncio.get_running_loop()
        initial = snapshot(logs_dir, LOG_FILES)
        await asyncio.to_thread(store.rebuild)

        def on_change() -> None:  # runs in a worker thread
            state = store.rebuild()
            loop.call_soon_threadsafe(
                store.publish, {"type": "state_changed", "turn": state.latest_turn}
            )

        task = asyncio.create_task(watch(logs_dir, LOG_FILES, on_change, poll_interval, initial))
        try:
            yield
        finally:
            task.cancel()

    app = FastAPI(title="Civ VII Advisor", lifespan=lifespan)
    app.state.store = store

    @app.get("/api/state")
    def api_state() -> dict:
        if store.state is None:
            raise HTTPException(status_code=503, detail="state not loaded yet")
        return state_to_dict(store.state)

    @app.get("/api/insights")
    def api_insights() -> list[dict]:
        return [insight_to_dict(i) for i in store.insights]

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
