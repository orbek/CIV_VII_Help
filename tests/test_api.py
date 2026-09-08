import asyncio
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from civ7_advisor.api.app import create_app
from civ7_advisor.llm.models import Commentary, CommentaryResult, Explanation, PlanStep

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


def test_state_has_a_production_block_gated_by_the_oracle_flag(client):
    body = client.get("/api/state").json()
    assert body["production"] == {"human": [], "rivals": []}
    body = client.get("/api/state?oracle=0").json()
    assert body["production"]["rivals"] is None and body["production"]["human"] == []


def _v2_dir(tmp_path: Path, fixture_dir: Path) -> Path:
    import shutil

    d = tmp_path / "logs"
    shutil.copytree(fixture_dir, d)
    (d / "Game_Gossip.csv").write_text(
        "Game Turn, Player, Civilization, Plot X, Plot Y, Type\n"
        "81, Alexander, Maurya, 63, 31, GOSSIP_UNIT_DESTROYED, Warrior\n"
    )
    (d / "CombatLog.csv").write_text(
        "Turn, SourceType, Location, AttPlayer, DefPlayer, CombatType, Attacker, Defender, AttStr, DefStr, "
        "AttStrMod, DefStrMod, AttDmg, DefDmg, Destroyed, HealAmount, attHealth, defHealth\n"
        "81,Unit vs Unit,(63)(30),0,4,Melee,(14)UNIT_WARRIOR,(15)UNIT_SPEARMAN,20,30,0,0,34,12,Attacker,0,(0)100,(88)100\n"
        "81,Unit vs Unit,(10)(10),1,2,Melee,(16)UNIT_WARRIOR,(17)UNIT_WARRIOR,20,20,0,0,30,30,,0,(70)100,(70)100\n"
    )
    (d / "DiplomacyDeals.log").write_text(
        "Turn 80, Incoming for player 4 and 0\n"
        ", Item ID 1, from player 4, to player 0, type Peace, subType 1 (), value type , amount 0, duration 1\n"
    )
    (d / "CityBuildQueue.csv").write_text(
        "Game Turn, Player, City, Production Added, Current Item, Current Production, Production Needed, Overflow\n"
        "81, 4, LOC_CITY_NAME_MAYA1, 12.0, UNIT_WARRIOR, 0.0, 30, 0.0\n"
        "82, 0, LOC_CITY_NAME_MAURYA1, 15.0, BUILDING_BRICKYARD, 47.5, 55, 0.0\n"
    )
    return d


def test_intel_endpoint_filters_oracle_events_server_side(tmp_path: Path, fixture_dir: Path):
    with TestClient(create_app(_v2_dir(tmp_path, fixture_dir), poll_interval=60)) as c:
        events = c.get("/api/intel").json()
        kinds = {(e["kind"], e["provenance"]) for e in events}
        assert ("gossip", "fair") in kinds and ("combat", "fair") in kinds
        assert ("combat", "oracle") in kinds and ("deal", "fair") in kinds
        fair_only = c.get("/api/intel?oracle=0").json()
        assert fair_only and all(e["provenance"] == "fair" for e in fair_only)
        assert [e["turn"] for e in events] == sorted((e["turn"] for e in events), reverse=True)
        state = c.get("/api/state").json()
        assert state["production"]["human"][0]["item"] == "BUILDING_BRICKYARD"
        assert state["production"]["rivals"][0]["name"] == "José Rizal"
        assert state["production"]["rivals"][0]["military_share"] == 1.0
        rizal = next(t for t in state["threats"] if t["player"] == 4)
        assert rizal["at_war_since"] is None and rizal["peace_since"] == 80


def test_intel_is_503_before_first_rebuild(fixture_dir: Path):
    assert TestClient(create_app(fixture_dir)).get("/api/intel").status_code == 503


def test_tactical_endpoint_is_gated_server_side(client):
    hidden = client.get("/api/tactical?oracle=0").json()
    assert hidden == {"available": False, "reason": "oracle_off"}
    shown = client.get("/api/tactical?oracle=1").json()
    assert shown["available"] and shown["city_tiles"]
    assert "enemy_units" in shown and "attack_goals" in shown


def test_commentary_endpoint_is_disabled_by_default_and_hides_oracle_output(fixture_dir):
    with TestClient(create_app(fixture_dir, poll_interval=60)) as c:
        assert c.get("/api/commentary").json()["status"] == "disabled"

    commentary = Commentary("local:test", "a" * 64, 81, True, "Opinion [threat.x].",
                            (Explanation("threat.x", "Why."),), (PlanStep("threat.x", "Act."),))

    class StubWorker:
        def schedule(self, state, insights):
            pass

        def result(self, turn):
            return CommentaryResult("ready", turn, "", commentary)

        def close(self):
            pass

    with TestClient(create_app(fixture_dir, poll_interval=60, commentary_worker=StubWorker())) as c:
        assert c.get("/api/commentary").json()["commentary"]["model"] == "local:test"
        hidden = c.get("/api/commentary?oracle=0").json()
        assert hidden["status"] == "hidden" and "commentary" not in hidden


def test_page_has_intel_tab_production_sections_and_wipe_copy(client):
    page = client.get("/").text
    for needle in (
        'data-tab="intel"',
        'id="intel-feed"',
        'id="tactical-map"',
        'id="commentary-panel"',
        'id="production-table"',
        'id="rival-production-table"',
        'id="wipe"',
    ):
        assert needle in page, needle
    js = client.get("/static/app.js").text
    assert "/api/intel?oracle=" in js and "/api/state?oracle=" in js and "/api/tactical?oracle=" in js
    assert "/api/commentary?oracle=" in js and "textContent" in js
    assert "(r.military_share || 0) * r.cities.length" in js
