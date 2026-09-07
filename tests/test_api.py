import asyncio
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from civ7_advisor.api.app import create_app

APP_JS = Path(__file__).resolve().parents[1] / "civ7_advisor" / "web" / "app.js"
# RivalThreat fields that come from the AI's own logs (AI_DiplomaticActions, AI_Targets).
ORACLE_THREAT_FIELDS = ("war_score", "war_score_since", "at_war_since",
                        "city_tiles_targeted", "units_targeted", "target_box", "target_turn")


@pytest.fixture(scope="module")
def client(fixture_dir: Path):
    with TestClient(create_app(fixture_dir, poll_interval=60)) as c:
        yield c


def test_state_endpoint(client):
    r = client.get("/api/state")
    assert r.status_code == 200
    body = r.json()
    assert body["latest_turn"] == 82 and body["complete_through_turn"] == 81 and body["in_progress"] is True
    assert [s["id"] for s in body["standings"]] == [0, 1, 2, 3, 4, 5, 6, 7]
    napoleon = body["standings"][3]
    assert napoleon["alive"] is False and napoleon["stats"] is None
    assert body["ranks"]["science"] == [7, 7]
    assert body["ranks"]["gold"] == [4, 7]
    assert body["ranks"]["military_units"] == [6, 7]
    assert body["standings"][0]["stats"]["net_gold"] == 19.0
    assert {t["player"] for t in body["threats"]} == {1, 2, 4, 5, 6, 7}
    assert body["leaderboards"]["ECONOMIC"][0]["name"] == "Harriet Tubman"
    assert {c["stat"] for c in body["economy"]} == {"science", "culture", "gold", "production", "food"}
    from tests.test_ingest_load import V1_FILES
    assert all(body["files"][name]["ok"] for name in V1_FILES)
    strategies = {s["strategy"]: s for s in body["standings"][4]["strategies"]}  # player 4
    assert strategies["CULTURAL"]["weight"] == 100 and strategies["CULTURAL"]["following"] is True


def test_insights_endpoint(client):
    body = client.get("/api/insights").json()
    assert body[0]["id"] == "threat.at_war.4"
    assert body[0]["severity"] == "CRITICAL" and body[0]["provenance"] == "oracle"
    assert all(i["why"] for i in body)


def test_index_and_static(client):
    page = client.get("/").text
    assert "<title>Civ VII Advisor</title>" in page and 'id="oracle"' in page
    for tab in ("checklist", "threats", "victory", "economy"):
        assert f'data-tab="{tab}"' in page
    js = client.get("/static/app.js")
    assert js.status_code == 200 and "EventSource" in js.text and "/api/insights" in js.text
    assert client.get("/static/style.css").status_code == 200


def _array_body(source: str, constant: str) -> str:
    """The body of a module-level array literal in app.js, without its brackets."""
    block = re.search(rf"\bconst {constant} = \[(.*?)^\s*\];", source, re.S | re.M)
    assert block, f"{constant} is not declared as an array literal in app.js"
    return block.group(1)


def _labels(body: str) -> list[str]:
    """The column labels declared in such a body, in order."""
    return re.findall(r'label:\s*"([^"]*)"', body)


def test_threats_table_columns_are_split_by_provenance():
    """The Oracle toggle gates oracle-derived table *columns*, not just cards, and that
    gating lives only in app.js: /api/state ships the oracle fields either way, so
    nothing else in the suite would notice `War score` or `Targeting` reappearing in
    fair mode. Pin both column sets, and pin that the fair set reads none of the
    AI-internal fields of RivalThreat."""
    source = APP_JS.read_text(encoding="utf-8")
    fair, oracle = _array_body(source, "THREATS_FAIR_COLUMNS"), _array_body(source, "THREATS_ORACLE_COLUMNS")

    assert _labels(fair) == ["Rival", "Land units", "vs you", "Their losses", "Your losses"]
    assert _labels(oracle) == ["War score", "Since turn", "War declared", "Targeting"]
    assert not set(_labels(fair)) & set(_labels(oracle))
    assert [f for f in ORACLE_THREAT_FIELDS if f in oracle], "the oracle columns should read oracle fields"
    assert not [f for f in ORACLE_THREAT_FIELDS if f in fair]


def test_state_is_503_before_first_rebuild(fixture_dir: Path):
    app = create_app(fixture_dir)  # no lifespan entered -> never rebuilt
    assert TestClient(app).get("/api/state").status_code == 503


def test_events_stream_delivers_and_drops_its_subscriber_on_disconnect(fixture_dir: Path):
    """Drive /events over raw ASGI: a published event reaches the client, and the queue is
    released when the client goes away — a leak here costs one queue per page refresh."""
    app = create_app(fixture_dir)  # no lifespan needed: /events reads no state
    store = app.state.store
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},  # what uvicorn's HTTP protocols send
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/events",
        "raw_path": b"/events",
        "root_path": "",
        "query_string": b"",
        "headers": [(b"host", b"testserver")],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
    }

    async def scenario():
        disconnect, chunks = asyncio.Event(), []

        async def receive() -> dict:
            await disconnect.wait()
            return {"type": "http.disconnect"}

        async def send(message: dict) -> None:
            if message["type"] == "http.response.body":
                chunks.append(message["body"].decode())

        async def until(ready, what: str) -> None:
            for _ in range(200):  # 2 s
                if ready():
                    return
                await asyncio.sleep(0.01)
            raise AssertionError(f"timed out waiting for {what}")

        task = asyncio.create_task(app(scope, receive, send))
        await until(lambda: store._subscribers, "the stream to subscribe")
        store.publish({"type": "state_changed", "turn": 82})
        await until(lambda: any(c.startswith("data:") for c in chunks), "the published event")
        assert '{"type": "state_changed", "turn": 82}' in "".join(chunks)

        disconnect.set()
        await asyncio.wait_for(task, 2)
        assert store._subscribers == set()  # no queue left behind

    asyncio.run(scenario())
