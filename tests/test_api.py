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
    assert js.status_code == 200 and "EventSource" in js.text and "/api/briefing?oracle=" in js.text
    assert client.get("/static/style.css").status_code == 200
    assert ">Strategy</button>" in page and "not victory score" in page


def _array_body(source: str, constant: str) -> str:
    """The body of a module-level array literal in app.js, without its brackets."""
    block = re.search(rf"\bconst {constant} = \[(.*?)^\s*\];", source, re.S | re.M)
    assert block, f"{constant} is not declared as an array literal in app.js"
    return block.group(1)


def _labels(body: str) -> list[str]:
    """The column labels declared in such a body, in order."""
    return re.findall(r'label:\s*"([^"]*)"', body)


def test_threats_table_columns_are_split_by_provenance():
    """The Oracle toggle gates oracle-derived table *columns*, not just cards. The server
    now also drops those fields from the response (see
    test_state_endpoint_drops_oracle_threat_fields_in_fair_mode), so this pins the
    browser's half of a two-layer boundary: the fair column set must read none of the
    AI-internal fields of RivalThreat even if a response ever carried them."""
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
        store.publish({"type": "state_changed", "turn": 82, "revision": 7})
        await until(lambda: any(c.startswith("data:") for c in chunks), "the published event")
        assert '{"type": "state_changed", "turn": 82, "revision": 7}' in "".join(chunks)

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
        "Turn 80, Enacting Deal id 1 for player 4 and 0\n"
        ", Enacting Deal Item ID 1, from player 4, to player 0, type Peace, subType 1 (), value type , amount 0, duration 1\n"
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
        def schedule(self, snapshot, oracle=True, revisions=None):
            pass

        def result(self, snapshot, oracle=True, revisions=None):
            return CommentaryResult("ready", snapshot.analysis_turn, "", commentary)

        def close(self):
            pass

    with TestClient(create_app(fixture_dir, poll_interval=60, commentary_worker=StubWorker())) as c:
        assert c.get("/api/commentary").json()["commentary"]["model"] == "local:test"
        # Fair mode is generated from a fair prompt, but a generation that still reports
        # having read intercepts is withheld rather than trusted.
        hidden = c.get("/api/commentary?oracle=0").json()
        assert hidden["status"] == "hidden" and hidden["commentary"] is None


def test_page_has_intel_tab_production_sections_and_wipe_copy(client):
    page = client.get("/").text
    for needle in (
        'data-tab="intel"',
        'id="intel-feed"',
        'id="tactical-map"',
        'id="commentary-panel"',
        'id="insight-summary"',
        'id="production-table"',
        'id="rival-production-table"',
        'id="wipe"',
    ):
        assert needle in page, needle
    js = client.get("/static/app.js").text
    # One request, one revision: the browser no longer assembles five independent
    # responses, which is what let a superseded reply repaint hidden data.
    assert "/api/briefing?oracle=" in js and "textContent" in js
    assert "/api/state?oracle=" not in js and "/api/tactical?oracle=" not in js
    assert "commentary-sentence uncited" in js
    assert "Closest recorded rival positions" in js and "distance_to_city" in js
    assert "(r.military_share || 0) * r.cities.length" in js


def test_briefing_serves_every_section_from_one_revision(client):
    body = client.get("/api/briefing").json()
    assert set(body) == {"status", "state", "insights", "hidden_insights", "intel",
                         "tactical", "commentary", "decisions"}
    status = body["status"]
    assert status["schema_version"] == 1 and status["revision"] >= 1
    assert status["session"] and status["epoch"] == 1
    assert status["analysis_turn"] == 81 and status["latest_turn"] == 82
    assert status["in_progress"] is True and status["evidence_mode"] == "oracle"
    assert body["state"]["complete_through_turn"] == status["analysis_turn"]
    assert body["insights"][0]["id"] == "threat.at_war.4"
    # Coverage is per capability, and names the ones this game cannot support.
    coverage = {c["name"]: c for c in status["coverage"]}
    assert coverage["empire"]["status"] == "ok" and coverage["empire"]["required"] is True
    assert coverage["tactical"]["status"] == "unavailable"
    assert coverage["tactical"]["required"] is False
    assert client.get("/api/status").json()["revision"] == status["revision"]


def test_briefing_in_fair_mode_omits_intercepted_evidence_rather_than_blanking_it(client):
    oracle = client.get("/api/briefing?oracle=1").json()
    fair = client.get("/api/briefing?oracle=0").json()
    assert fair["status"]["evidence_mode"] == "fair"
    assert any(i["provenance"] == "oracle" for i in oracle["insights"])
    assert all(i["provenance"] == "fair" for i in fair["insights"])
    assert fair["hidden_insights"] == len(oracle["insights"]) - len(fair["insights"])
    assert fair["hidden_insights"] > 0
    assert all(e["provenance"] == "fair" for e in fair["intel"])
    assert fair["tactical"] == {"available": False, "reason": "oracle_off"}


def test_fair_mode_strips_ai_internal_fields_from_the_response_itself(client):
    """The browser also drops the Oracle columns, but fair mode must not depend on that:
    with oracle=0 the AI-internal numbers are absent from the payload."""
    oracle = client.get("/api/state?oracle=1").json()
    fair = client.get("/api/state?oracle=0").json()
    assert all(field in oracle["threats"][0] for field in ORACLE_THREAT_FIELDS)
    for row in fair["threats"]:
        assert not [f for f in ORACLE_THREAT_FIELDS if f in row]
        assert "peace_since" in row      # a deal the player signed stays fair
    # A rival's victory weighting is the AI's own, and is withheld the same way.
    assert any(s["strategies"] for s in oracle["standings"])
    assert all(s["strategies"] == [] for s in fair["standings"])


def test_insights_endpoint_filters_by_mode_on_the_server(client):
    everything = client.get("/api/insights?oracle=1").json()
    fair = client.get("/api/insights?oracle=0").json()
    assert any(i["provenance"] == "oracle" for i in everything)
    assert fair and all(i["provenance"] == "fair" for i in fair)


def test_briefing_is_503_before_the_first_rebuild(fixture_dir: Path):
    app = create_app(fixture_dir)  # lifespan never entered -> nothing published
    assert TestClient(app).get("/api/briefing").status_code == 503
    assert TestClient(app).get("/api/status").status_code == 503


def test_commentary_reports_queued_and_carries_its_decision_identity(fixture_dir: Path):
    from civ7_advisor.llm.models import CommentaryIdentity

    identity = CommentaryIdentity(session="s", epoch=1, evidence_mode="oracle",
                                  snapshot_revision=3, turn=81, insight_ids=("threat.x",))
    ready = Commentary("local:test", "b" * 64, 81, False, "Opinion [threat.x].",
                       (Explanation("threat.x", "Why."),), (PlanStep("threat.x", "Act."),),
                       identity)

    class StubWorker:
        def schedule(self, snapshot, oracle=True, revisions=None):
            pass

        def result(self, snapshot, oracle=True, revisions=None):
            return CommentaryResult("queued", snapshot.analysis_turn,
                                    "Local commentary is queued behind another generation.",
                                    previous=ready)

        def close(self):
            pass

    with TestClient(create_app(fixture_dir, poll_interval=60, commentary_worker=StubWorker())) as c:
        body = c.get("/api/commentary").json()
        assert body["status"] == "queued" and body["commentary"] is None
        # Earlier prose travels as dated history, with the identity that dates it.
        assert body["previous"]["second_opinion"] == "Opinion [threat.x]."
        assert body["previous"]["identity"]["snapshot_revision"] == 3
        assert body["previous"]["identity"]["evidence_mode"] == "oracle"
        assert c.get("/api/briefing").json()["commentary"]["status"] == "queued"


def _behind_dir(tmp_path: Path, fixture_dir: Path) -> Path:
    """A log directory whose human is behind on culture with one logged queue, so the
    culture decision has something to decide."""
    import shutil

    d = tmp_path / "logs"
    shutil.copytree(fixture_dir, d)
    (d / "CityBuildQueue.csv").write_text(
        "Game Turn, Player, City, Production Added, Current Item, Current Production, "
        "Production Needed, Overflow\n"
        "82, 0, LOC_CITY_NAME_TEST1, 20.0, UNIT_WARRIOR, 25.0, 30, 0.0\n"
    )
    return d


def test_decisions_travel_with_their_evidence_and_guides_resolved(tmp_path, fixture_dir):
    """Citations resolve on the server. A bare id the drawer cannot look up would be a
    dead link, so the resolution happens where it can fail loudly."""
    with TestClient(create_app(_behind_dir(tmp_path, fixture_dir), poll_interval=60)) as c:
        body = c.get("/api/decisions").json()
        card = next(x for x in body["cards"] if x["id"].startswith("decision.culture."))
        assert card["subject"] == "Culture in Test1"
        action = card["preferred"]
        assert action["applicability"] == "inspect"
        assert action["steps"] and action["why_now"]
        assert action["guide_ids"]

        cited = {f["id"] for f in body["evidence"]}
        assert set(action["evidence_ids"]) <= cited
        assert set(card["evidence_ids"]) <= cited
        guides = {g["id"] for g in body["guides"]}
        assert set(action["guide_ids"]) <= guides
        # Each guide says how far it may be relied on, and carries a real URL.
        for guide in body["guides"]:
            assert guide["url"].startswith("https://")
            assert guide["review_status"] == "navigation_reviewed"
            assert "version_known" in guide and guide["attribution"]
        # Evidence leads with a readable label, not the internal id.
        fact = next(f for f in body["evidence"] if f["kind"] == "derived")
        assert fact["label"] and fact["contributing"]
        assert body["context"]["catalog_revision"]


def test_the_briefing_carries_the_decision_brief(tmp_path, fixture_dir):
    with TestClient(create_app(_behind_dir(tmp_path, fixture_dir), poll_interval=60)) as c:
        body = c.get("/api/briefing").json()
        assert body["decisions"]["cards"]
        assert body["decisions"]["context"]["snapshot_revision"] == body["status"]["revision"]
        assert body["decisions"]["context"]["evidence_mode"] == "oracle"
        fair = c.get("/api/briefing?oracle=0").json()
        assert fair["decisions"]["context"]["evidence_mode"] == "fair"


def test_a_submitted_preview_changes_the_recommendation_and_the_context_revision(
        tmp_path, fixture_dir):
    with TestClient(create_app(_behind_dir(tmp_path, fixture_dir), poll_interval=60)) as c:
        session = c.get("/api/status").json()["session"]
        before = c.get("/api/decisions").json()
        assert before["cards"][0]["preferred"]["applicability"] == "inspect"

        def submit(label, value, unit=None, base_revision=None, session_id=None):
            revision = (c.get("/api/context").json()["revision"]
                        if base_revision is None else base_revision)
            return c.post("/api/context", json={
                "id": f"report.TEST1.{label}.{value}", "subject": "LOC_CITY_NAME_TEST1",
                "label": label, "value": value, "unit": unit, "observed_turn": 81,
                "session": session_id or session, "reported_at": "2026-09-08T12:00:00",
                "epoch": 1, "base_revision": revision,
            })

        assert submit("available_options", "BUILDING_MONUMENT,BUILDING_AMPHITHEATER").status_code == 200
        assert submit("objective", "soonest_culture").status_code == 200
        for item, turns, delta in (("BUILDING_MONUMENT", 4, 3), ("BUILDING_AMPHITHEATER", 6, 5)):
            assert submit(f"preview.{item}.completion_turns", turns, "turns").status_code == 200
            assert submit(f"preview.{item}.culture_delta", delta, "culture per turn").status_code == 200

        held = c.get("/api/context").json()
        assert held["revision"] >= 6 and len(held["reports"]) == 6

        after = c.get("/api/decisions").json()
        card = after["cards"][0]
        assert card["preferred"]["id"].endswith("BUILDING_MONUMENT")
        # Named, and still conditional: availability of a *placement* and Age
        # applicability are not things any log settles.
        assert card["preferred"]["applicability"] == "conditional"
        states = {p["name"]: p["state"] for p in card["preferred"]["prerequisites"]}
        assert states["offered in this settlement"] == "met"
        assert states["Age and ruleset applicability"] == "unknown"
        shown = " ".join(card["preferred"]["trade_offs"])
        assert "2 more culture per turn" in shown and "2 turns longer" in shown
        assert after["context"]["context_revision"] == held["revision"]
        # The player's own figures are cited as reports, not dressed up as log rows.
        reports = [f for f in after["evidence"] if f["kind"] == "player_report"]
        assert reports and all(f["source_file"] is None for f in reports)


def test_a_submission_from_another_session_is_refused_with_a_recoverable_conflict(
        tmp_path, fixture_dir):
    with TestClient(create_app(_behind_dir(tmp_path, fixture_dir), poll_interval=60)) as c:
        response = c.post("/api/context", json={
            "id": "report.stale", "subject": "LOC_CITY_NAME_TEST1", "label": "objective",
            "value": "soonest_culture", "observed_turn": 81, "session": "a-previous-session",
            "reported_at": "2026-09-08T12:00:00", "epoch": 1, "base_revision": 0,
        })
        assert response.status_code == 409
        body = response.json()
        assert body["reason"] == "session_changed"
        assert body["session"] == c.get("/api/status").json()["session"]
        assert c.get("/api/context").json()["reports"] == []


def test_a_field_the_panel_does_not_collect_is_refused(tmp_path, fixture_dir):
    with TestClient(create_app(_behind_dir(tmp_path, fixture_dir), poll_interval=60)) as c:
        session = c.get("/api/status").json()["session"]
        response = c.post("/api/context", json={
            "id": "report.free", "subject": "LOC_CITY_NAME_TEST1", "label": "my_hopes",
            "value": "win", "observed_turn": 81, "session": session,
            "reported_at": "2026-09-08T12:00:00", "epoch": 1, "base_revision": 0,
        })
        assert response.status_code == 409 and response.json()["reason"] == "unknown_label"
        assert c.post("/api/context", json={"id": "x"}).status_code == 422


def test_clearing_a_report_moves_the_revision_and_restores_the_inspection(
        tmp_path, fixture_dir):
    with TestClient(create_app(_behind_dir(tmp_path, fixture_dir), poll_interval=60)) as c:
        session = c.get("/api/status").json()["session"]
        c.post("/api/context", json={
            "id": "report.options", "subject": "LOC_CITY_NAME_TEST1",
            "label": "available_options", "value": "BUILDING_MONUMENT",
            "observed_turn": 81, "session": session, "reported_at": "2026-09-08T12:00:00",
            "epoch": 1, "base_revision": 0,
        })
        assert any("BUILDING_MONUMENT" in x["id"]
                   for x in c.get("/api/decisions").json()["cards"][0]["alternatives"]
                   + [c.get("/api/decisions").json()["cards"][0]["preferred"]])
        cleared = c.delete("/api/context/report.options").json()
        assert cleared["removed"] is True and cleared["revision"] == 2
        card = c.get("/api/decisions").json()["cards"][0]
        assert card["preferred"]["applicability"] == "inspect"
        assert all("BUILDING_MONUMENT" not in x["id"] for x in card["alternatives"])
