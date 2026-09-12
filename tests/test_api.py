import asyncio
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from civ_advisor.api.app import create_app
from civ_advisor.games.civ7 import CIV7
from civ_advisor.llm.models import Commentary, CommentaryResult, Explanation, PlanStep

APP_JS = Path(__file__).resolve().parents[1] / "civ_advisor" / "web" / "app.js"
# RivalThreat fields that come from the AI's own logs (AI_DiplomaticActions, AI_Targets).
ORACLE_THREAT_FIELDS = ("war_score", "war_score_since", "at_war_since",
                        "city_tiles_targeted", "units_targeted", "target_box", "target_turn")


@pytest.fixture(scope="module")
def client(fixture_dir: Path):
    with TestClient(create_app(fixture_dir, poll_interval=60, profile=CIV7)) as c:
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
    app = create_app(fixture_dir, profile=CIV7)  # no lifespan entered -> never rebuilt
    assert TestClient(app).get("/api/state").status_code == 503


def test_events_stream_delivers_and_drops_its_subscriber_on_disconnect(fixture_dir: Path):
    """Drive /events over raw ASGI: a published event reaches the client, and the queue is
    released when the client goes away — a leak here costs one queue per page refresh."""
    app = create_app(fixture_dir, profile=CIV7)  # no lifespan needed: /events reads no state
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
    with TestClient(create_app(_v2_dir(tmp_path, fixture_dir), poll_interval=60, profile=CIV7)) as c:
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
    assert TestClient(create_app(fixture_dir, profile=CIV7)).get("/api/intel").status_code == 503


def test_tactical_endpoint_is_gated_server_side(client):
    hidden = client.get("/api/tactical?oracle=0").json()
    assert hidden == {"available": False, "reason": "oracle_off"}
    shown = client.get("/api/tactical?oracle=1").json()
    assert shown["available"] and shown["city_tiles"]
    assert "enemy_units" in shown and "attack_goals" in shown


def test_commentary_endpoint_is_disabled_by_default_and_hides_oracle_output(fixture_dir):
    with TestClient(create_app(fixture_dir, poll_interval=60, profile=CIV7)) as c:
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

    with TestClient(create_app(fixture_dir, poll_interval=60, commentary_worker=StubWorker(), profile=CIV7)) as c:
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
    assert "Recorded rival positions" in js and "distance_to_city" in js
    # Every contact is reachable: the view picker and paged table replace the old cap.
    assert "All contacts" in client.get("/static/tactical.js").text
    assert "(r.military_share || 0) * r.cities.length" in js


def test_briefing_serves_every_section_from_one_revision(client):
    body = client.get("/api/briefing").json()
    assert set(body) == {"status", "state", "insights", "hidden_insights", "intel",
                         "tactical", "commentary", "decisions", "changes", "record"}
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
    app = create_app(fixture_dir, profile=CIV7)  # lifespan never entered -> nothing published
    assert TestClient(app).get("/api/briefing").status_code == 503
    assert TestClient(app).get("/api/status").status_code == 503


def test_commentary_reports_queued_and_carries_its_decision_identity(fixture_dir: Path):
    from civ_advisor.llm.models import CommentaryIdentity

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

    with TestClient(create_app(fixture_dir, poll_interval=60, commentary_worker=StubWorker(), profile=CIV7)) as c:
        body = c.get("/api/commentary").json()
        assert body["status"] == "queued" and body["commentary"] is None
        # Earlier prose travels as dated history, with the identity that dates it.
        assert body["previous"]["second_opinion"] == "Opinion [threat.x]."
        assert body["previous"]["identity"]["snapshot_revision"] == 3
        assert body["previous"]["identity"]["evidence_mode"] == "oracle"
        assert c.get("/api/briefing").json()["commentary"]["status"] == "queued"


CULTURE_COLUMN = 15   # "Culture" in Player_Stats.csv, zero-based


def _behind_dir(tmp_path: Path, fixture_dir: Path) -> Path:
    """A log directory whose human trails worst on *culture*, with one logged queue.

    Several yields trail the field in this session and the brief folds same-settlement
    gaps into the worst one, so the pilot's own card only exists when culture is the worst.
    An override row for the analysis turn makes that so — the last row for a
    (turn, player) pair wins.
    """
    import shutil

    d = tmp_path / "logs"
    shutil.copytree(fixture_dir, d)
    (d / "CityBuildQueue.csv").write_text(
        "Game Turn, Player, City, Production Added, Current Item, Current Production, "
        "Production Needed, Overflow\n"
        "82, 0, LOC_CITY_NAME_TEST1, 20.0, UNIT_WARRIOR, 25.0, 30, 0.0\n"
    )
    stats = d / "Player_Stats.csv"
    rows = stats.read_text().splitlines()
    index = next(i for i, r in enumerate(rows)
                 if [c.strip() for c in r.split(",")[:2]] == ["81", "0"])
    cells = rows[index].split(",")
    cells[CULTURE_COLUMN] = " 1.0"
    # Immediately after the row it overrides, not at the end of the file: the reader
    # treats a turn number that moves backwards as a new game and would drop everything
    # before it.
    rows.insert(index + 1, ",".join(cells))
    stats.write_text("\n".join(rows) + "\n")
    return d


def test_decisions_travel_with_their_evidence_and_guides_resolved(tmp_path, fixture_dir):
    """Citations resolve on the server. A bare id the drawer cannot look up would be a
    dead link, so the resolution happens where it can fail loudly."""
    with TestClient(create_app(_behind_dir(tmp_path, fixture_dir), poll_interval=60, profile=CIV7)) as c:
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
    with TestClient(create_app(_behind_dir(tmp_path, fixture_dir), poll_interval=60, profile=CIV7)) as c:
        body = c.get("/api/briefing").json()
        assert body["decisions"]["cards"]
        assert body["decisions"]["context"]["snapshot_revision"] == body["status"]["revision"]
        assert body["decisions"]["context"]["evidence_mode"] == "oracle"
        fair = c.get("/api/briefing?oracle=0").json()
        assert fair["decisions"]["context"]["evidence_mode"] == "fair"


def test_a_submitted_preview_changes_the_recommendation_and_the_context_revision(
        tmp_path, fixture_dir):
    with TestClient(create_app(_behind_dir(tmp_path, fixture_dir), poll_interval=60, profile=CIV7)) as c:
        session = c.get("/api/status").json()["session"]
        def culture_card(body):
            return next(x for x in body["cards"] if x["id"].startswith("decision.culture."))

        before = c.get("/api/decisions").json()
        # Culture is the worst gap here, so it owns the settlement's card and the other
        # trailing yields are folded into it rather than repeated.
        assert [x["id"].split(".")[1] for x in before["cards"]] == ["culture"]
        card = culture_card(before)
        assert card["preferred"]["applicability"] == "inspect"
        assert {row["label"] for row in card["also_behind"]} >= {"food", "science"}
        assert "the same inspection covers them" in card["priority_reason"]

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
            assert submit(f"preview.{item}.yield_delta", delta, "culture per turn").status_code == 200

        held = c.get("/api/context").json()
        assert held["revision"] >= 6 and len(held["reports"]) == 6

        after = c.get("/api/decisions").json()
        card = culture_card(after)
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
    with TestClient(create_app(_behind_dir(tmp_path, fixture_dir), poll_interval=60, profile=CIV7)) as c:
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
    with TestClient(create_app(_behind_dir(tmp_path, fixture_dir), poll_interval=60, profile=CIV7)) as c:
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
    with TestClient(create_app(_behind_dir(tmp_path, fixture_dir), poll_interval=60, profile=CIV7)) as c:
        session = c.get("/api/status").json()["session"]
        c.post("/api/context", json={
            "id": "report.options", "subject": "LOC_CITY_NAME_TEST1",
            "label": "available_options", "value": "BUILDING_MONUMENT",
            "observed_turn": 81, "session": session, "reported_at": "2026-09-08T12:00:00",
            "epoch": 1, "base_revision": 0,
        })
        def culture_card():
            body = c.get("/api/decisions").json()
            return next(x for x in body["cards"] if x["id"].startswith("decision.culture."))

        named = culture_card()
        assert any("BUILDING_MONUMENT" in x["id"]
                   for x in named["alternatives"] + [named["preferred"]])
        cleared = c.delete("/api/context/report.options").json()
        assert cleared["removed"] is True and cleared["revision"] == 2
        card = culture_card()
        assert card["preferred"]["applicability"] == "inspect"
        assert all("BUILDING_MONUMENT" not in x["id"] for x in card["alternatives"])


def _client_with_notes(tmp_path: Path, fixture_dir: Path, worker=None):
    """A client whose player record is a throwaway file, never the developer's own."""
    from civ_advisor.context_store import PersistentContextStore

    return TestClient(create_app(
        _behind_dir(tmp_path, fixture_dir), poll_interval=60, commentary_worker=worker,
        player_store=PersistentContextStore(path=tmp_path / "notes.json"), profile=CIV7))


def test_the_first_turn_reports_no_trend_at_all(tmp_path, fixture_dir):
    """A single observation is not a direction, and an empty change list would read as
    "nothing changed"."""
    with _client_with_notes(tmp_path, fixture_dir) as c:
        body = c.get("/api/changes").json()
        assert body["comparable"] is False and body["changes"] == []
        assert "nothing to compare it with" in body["reason"]
        assert body["previous_turn"] is None and body["observed_turns"] == [81]
        assert body["retrospective"]["states"] == {}


def test_repeated_reads_of_the_same_turn_do_not_become_history(tmp_path, fixture_dir):
    with _client_with_notes(tmp_path, fixture_dir) as c:
        for _ in range(4):
            body = c.get("/api/changes").json()
        assert body["observed_turns"] == [81]
        assert body["comparable"] is False


def test_a_question_is_answered_from_the_decisions_own_facts(tmp_path, fixture_dir):
    with _client_with_notes(tmp_path, fixture_dir) as c:
        card = next(x for x in c.get("/api/decisions").json()["cards"]
                    if x["id"].startswith("decision.culture."))
        for kind in ("why", "inspect", "what_changes"):
            body = c.post("/api/question", json={
                "kind": kind, "decision_id": card["id"], "oracle": 1}).json()
            assert body["status"] == "fallback"          # no model configured
            assert body["answer"]["generated"] is False
            assert body["answer"]["text"]
            assert set(body["answer"]["evidence_ids"]) <= set(card["evidence_ids"]) | {
                f["id"] for f in c.get("/api/decisions").json()["evidence"]}
        assert c.post("/api/question", json={
            "kind": "why", "decision_id": "decision.nope.X"}).status_code == 404
        assert c.post("/api/question", json={
            "kind": "sing", "decision_id": card["id"]}).status_code == 422


def test_a_fair_question_never_receives_intercepted_evidence(tmp_path, fixture_dir):
    """The evidence is filtered before the request exists, so nothing downstream has to
    remember to strip it."""
    from civ_advisor.llm import questions

    seen: list[questions.QuestionRequest] = []

    class RecordingWorker:
        def schedule(self, snapshot, oracle=True, revisions=None):
            pass

        def result(self, snapshot, oracle=True, revisions=None):
            return CommentaryResult("idle", snapshot.analysis_turn, "")

        def answer(self, request):
            seen.append(request)
            return "fallback", questions.fallback(request)

        def close(self):
            pass

    with _client_with_notes(tmp_path, fixture_dir, RecordingWorker()) as c:
        oracle_brief = c.get("/api/decisions?oracle=1").json()
        defensive = [x for x in oracle_brief["cards"] if x["id"].startswith("decision.defense")]
        target = (defensive or [x for x in oracle_brief["cards"]
                                if x["id"].startswith("decision.culture.")])[0]
        c.post("/api/question", json={"kind": "why", "decision_id": target["id"],
                                      "oracle": 0})
        [request] = seen
        assert request.evidence_mode == "fair"
        every = {f["id"]: f for f in oracle_brief["evidence"]}
        for fact_id in request.evidence_ids:
            assert every[fact_id]["provenance"] == "fair", fact_id
        assert "oracle" not in questions.prompt_for(request).lower().split('"provenance":')[-1][:40]


def test_the_player_record_persists_and_a_new_sitting_holds_it_back(tmp_path, fixture_dir):
    from civ_advisor.context_store import PersistentContextStore

    logs = _behind_dir(tmp_path, fixture_dir)
    notes = tmp_path / "notes.json"
    first = PersistentContextStore(path=notes)
    with TestClient(create_app(logs, poll_interval=60, player_store=first, profile=CIV7)) as c:
        card = next(x for x in c.get("/api/decisions").json()["cards"]
                    if x["id"].startswith("decision.culture."))
        written = c.post("/api/record", json={
            "kind": "acknowledged", "subject": card["id"], "fingerprint": "fp1"}).json()
        assert written["error"] is None and written["revision"] >= 1
        assert c.post("/api/record", json={"kind": "goal", "subject": card["id"],
                                           "text": "level with the field"}).status_code == 200
        held = c.get("/api/record").json()
        assert sorted(e["kind"] for e in held["entries"]) == ["acknowledged", "goal"]
        assert held["pending"] == []
        assert c.post("/api/record", json={"kind": "whatever", "subject": "x"}).status_code == 409
        assert c.post("/api/record", json={"subject": "x"}).status_code == 422

    # A second process is a new session, so the entries are offered rather than applied.
    second = PersistentContextStore(path=notes)
    with TestClient(create_app(logs, poll_interval=60, player_store=second, profile=CIV7)) as c:
        held = c.get("/api/record").json()
        assert held["entries"] == [] and len(held["pending"]) == 1
        group = held["pending"][0]
        assert group["count"] == 2 and group["reason"]
        # Still held on a second read, so the UI can offer it more than once.
        assert len(c.get("/api/record").json()["pending"]) == 1
        adopted = c.post("/api/record/associate", json={
            "session": group["session"], "epoch": group["epoch"]}).json()
        assert len(adopted["associated"]) == 2
        assert c.get("/api/record").json()["pending"] == []
        assert c.post("/api/record/associate", json={"session": "nope", "epoch": 1}
                      ).status_code == 409


def test_held_entries_can_be_discarded_instead(tmp_path, fixture_dir):
    from civ_advisor.context_store import PersistentContextStore

    logs = _behind_dir(tmp_path, fixture_dir)
    notes = tmp_path / "notes.json"
    with TestClient(create_app(logs, poll_interval=60,
                               player_store=PersistentContextStore(path=notes),
                               profile=CIV7)) as c:
        c.post("/api/record", json={"kind": "watch", "subject": "decision.x"})
    with TestClient(create_app(logs, poll_interval=60,
                               player_store=PersistentContextStore(path=notes),
                               profile=CIV7)) as c:
        group = c.get("/api/record").json()["pending"][0]
        assert c.post("/api/record/associate", json={
            "session": group["session"], "epoch": group["epoch"],
            "discard": True}).json()["discarded"] == 1
        assert c.get("/api/record").json() == {
            **c.get("/api/record").json(), "pending": [], "entries": []}


def test_the_briefing_carries_changes_and_the_record(tmp_path, fixture_dir):
    with _client_with_notes(tmp_path, fixture_dir) as c:
        body = c.get("/api/briefing").json()
        assert body["changes"]["turn"] == 81
        assert body["record"]["session"] == body["status"]["session"]
        assert body["record"]["entries"] == [] and body["record"]["error"] is None


def test_on_change_skips_publishing_when_rebuild_returns_none(tmp_path, fixture_dir, monkeypatch, caplog):
    """Store.rebuild() can return None: idle (no game selected), or a switch_to that
    landed mid-rebuild discarded this exact read. on_change must skip publishing
    rather than crash -- a crash here is silently swallowed by the poller's broad
    except, which has already advanced its own change-tracking before awaiting
    on_change, so nothing reschedules and the dashboard is stuck on a stale or
    absent snapshot until the game happens to write again."""
    import logging
    import shutil
    import time

    logs = tmp_path / "logs"
    shutil.copytree(fixture_dir, logs)
    app = create_app(logs, poll_interval=0.05, profile=CIV7)
    with TestClient(app):
        store = app.state.store
        published = []
        monkeypatch.setattr(store, "publish", lambda event: published.append(event))
        monkeypatch.setattr(store, "rebuild", lambda: None)
        with caplog.at_level(logging.ERROR, logger="civ_advisor.ingest.poller"):
            (logs / "Player_Stats.csv").touch()
            time.sleep(0.3)   # several poll intervals: seen, confirmed stable, on_change fires
        # Nothing raised out of on_change: the poller's own "poll failed" log line,
        # which fires only when on_change escapes with an exception, never appears.
        assert not any("poll failed" in r.message for r in caplog.records)
        assert published == []


def _selector(tmp_path, civ7_dir, civ6_dir, pinned=None):
    from civ_advisor.games.selection import GameSelector
    return GameSelector(pinned=pinned, logs_dirs={"civ7": civ7_dir, "civ6": civ6_dir})


def test_api_game_reports_the_mode_and_what_detection_thinks(fixture_dir, civ6_dir, tmp_path):
    from civ_advisor.games.selection import GameSelector

    selector = GameSelector(pinned="civ7", logs_dirs={"civ7": fixture_dir, "civ6": civ6_dir})
    with TestClient(create_app(fixture_dir, poll_interval=60, profile=CIV7,
                               selector=selector, storage_base=tmp_path)) as c:
        body = c.get("/api/game").json()
    assert body["mode"] == "pinned" and body["active"]["id"] == "civ7"
    assert [g["id"] for g in body["games"]] == ["civ6", "civ7"]
    assert body["active"]["display_name"] == "Civilization VII"


def test_posting_a_game_pins_it_and_switches_the_store(fixture_dir, civ6_dir, tmp_path):
    """Starts pinned to civ7 (not auto) so the starting point is deterministic: the
    committed fixtures' real mtimes are both well outside the detection window, so an
    unpinned selector would start with no active game at all rather than civ7."""
    from civ_advisor.games.selection import GameSelector

    selector = GameSelector(pinned="civ7", logs_dirs={"civ7": fixture_dir, "civ6": civ6_dir})
    with TestClient(create_app(fixture_dir, poll_interval=60, profile=CIV7,
                               selector=selector, storage_base=tmp_path)) as c:
        before = c.get("/api/status").json()
        assert c.post("/api/game", json={"game": "civ6"}).status_code == 200
        after = c.get("/api/status").json()
    assert before["game"]["active"]["id"] == "civ7"
    assert after["game"]["active"]["id"] == "civ6"
    assert after["game"]["mode"] == "pinned"
    assert after["epoch"] == before["epoch"] + 1       # a switch is a new sitting
    assert after["session"] != before["session"]


def test_posting_auto_returns_to_detection(fixture_dir, civ6_dir, tmp_path):
    from civ_advisor.games.selection import GameSelector

    selector = GameSelector(pinned="civ7", logs_dirs={"civ7": fixture_dir, "civ6": civ6_dir})
    with TestClient(create_app(fixture_dir, poll_interval=60, profile=CIV7,
                               selector=selector, storage_base=tmp_path)) as c:
        assert c.post("/api/game", json={"game": "auto"}).status_code == 200
        assert c.get("/api/game").json()["mode"] == "auto"


def test_posting_an_unknown_game_is_refused_without_changing_anything(fixture_dir, tmp_path):
    from civ_advisor.games.selection import GameSelector

    selector = GameSelector(pinned="civ7", logs_dirs={"civ7": fixture_dir})
    with TestClient(create_app(fixture_dir, poll_interval=60, profile=CIV7,
                               selector=selector, storage_base=tmp_path)) as c:
        assert c.post("/api/game", json={"game": "civ5"}).status_code == 422
        assert c.get("/api/game").json()["active"]["id"] == "civ7"


def test_status_carries_the_game_when_no_selector_is_configured(fixture_dir):
    """A fixed-profile app still says which game it is advising on."""
    with TestClient(create_app(fixture_dir, poll_interval=60, profile=CIV7)) as c:
        body = c.get("/api/status").json()
    assert body["game"]["active"]["id"] == "civ7" and body["game"]["mode"] == "pinned"


def test_an_idle_app_explains_itself_rather_than_erroring_blankly(tmp_path):
    """Auto mode, nothing recent on disk: the briefing is unavailable, and /api/game
    still answers so the header can say why and offer the control."""
    from civ_advisor.games.selection import GameSelector

    empty = {"civ7": tmp_path / "no7", "civ6": tmp_path / "no6"}
    selector = GameSelector(logs_dirs=empty)
    with TestClient(create_app(None, poll_interval=60, profile=None,
                               selector=selector, storage_base=tmp_path)) as c:
        assert c.get("/api/briefing").status_code == 503
        body = c.get("/api/game").json()
    assert body["active"] is None
    assert body["detection"]["reason"] in {"no_candidates", "all_stale"}
    assert body["mode"] == "auto"


def _age_declared_logs(directory: Path, game_id: str, mtime: float) -> None:
    """Set every log file the profile declares (that actually exists) to one mtime,
    so detection's "newest declared log" is exactly this value, not whatever real
    mtime `shutil.copytree` happened to preserve from an untouched file."""
    import os

    from civ_advisor.games.registry import get_profile

    for name in get_profile(game_id).log_files:
        path = directory / name
        if path.exists():
            os.utime(path, (mtime, mtime))


def test_detection_flipping_forces_an_immediate_rebuild_with_no_further_file_write(
    tmp_path, fixture_dir, civ6_dir
):
    """LANDMINE 1: a game switch changes logs_dir AND the declared file set at once.
    If the supervisor merely re-pointed the watcher without forcing a rebuild, the
    header would flip to Civ VI while the dashboard kept showing Civ VII's last
    snapshot until Civ VI's own files next changed -- which, right after a switch,
    they have no reason to. This drives the switch through detection (not a pin, so
    through `supervise()`/`start_watching()`, not the direct POST /api/game path) and
    asserts the new game's data appears without writing to its logs again after the
    clock moves.
    """
    import shutil
    import time

    civ7 = tmp_path / "logs_civ7"
    civ6 = tmp_path / "logs_civ6"
    storage = tmp_path / "storage"     # kept apart from the logs dirs: archive_root_for
    shutil.copytree(fixture_dir, civ7)  # nests under `base / game_id`, which must not
    shutil.copytree(civ6_dir, civ6)     # collide with the logs dir itself

    clock = [1_000_000.0]
    _age_declared_logs(civ7, "civ7", clock[0])              # fresh
    _age_declared_logs(civ6, "civ6", clock[0] - 10_000)      # stale

    from civ_advisor.games.selection import GameSelector

    selector = GameSelector(logs_dirs={"civ7": civ7, "civ6": civ6}, clock=lambda: clock[0])
    app = create_app(civ7, poll_interval=0.05, profile=CIV7,
                      selector=selector, storage_base=storage)

    def poll_status(c) -> dict:
        for _ in range(3):
            r = c.get("/api/status")
            if r.status_code == 200:
                return r.json()
            time.sleep(0.02)
        return r.json()

    with TestClient(app) as c:
        before = poll_status(c)
        assert before["game_id"] == "civ7"

        # Move the clock forward and make civ6 the freshest candidate -- civ7 falls
        # outside the recency window (600s) and out of detection's favor. No further
        # write to civ6 happens after this: whatever appears next comes from the
        # forced rebuild alone, not from the watcher noticing a later change.
        clock[0] += 20_000
        _age_declared_logs(civ6, "civ6", clock[0])

        deadline = time.monotonic() + 3.0
        after = before
        while time.monotonic() < deadline and after.get("game_id") != "civ6":
            time.sleep(0.05)
            after = poll_status(c)

    assert after["game_id"] == "civ6"
    assert after["game"]["mode"] == "auto"


def test_the_watcher_keeps_working_on_the_new_game_after_a_detected_switch(
    tmp_path, fixture_dir, civ6_dir
):
    """LANDMINE 2: `watch()` advances its own dedup state (`last`/`pending`) before
    calling `on_change`, regardless of what `on_change` does. The old watcher for
    civ7 is cancelled by `supervise()` the moment the switch is detected, so its
    dedup state cannot get anything stuck -- but the freshly created civ6 watcher
    must still notice a REAL subsequent civ6 file change, proving the switch left
    the poller in a working state rather than a wedged one.
    """
    import shutil
    import time

    civ7 = tmp_path / "logs_civ7"
    civ6 = tmp_path / "logs_civ6"
    storage = tmp_path / "storage"
    shutil.copytree(fixture_dir, civ7)
    shutil.copytree(civ6_dir, civ6)

    clock = [1_000_000.0]
    _age_declared_logs(civ7, "civ7", clock[0])
    _age_declared_logs(civ6, "civ6", clock[0] - 10_000)

    from civ_advisor.games.selection import GameSelector

    selector = GameSelector(logs_dirs={"civ7": civ7, "civ6": civ6}, clock=lambda: clock[0])
    app = create_app(civ7, poll_interval=0.05, profile=CIV7,
                      selector=selector, storage_base=storage)

    def poll_status(c) -> dict:
        for _ in range(3):
            r = c.get("/api/status")
            if r.status_code == 200:
                return r.json()
            time.sleep(0.02)
        return r.json()

    with TestClient(app) as c:
        assert poll_status(c)["game_id"] == "civ7"     # settled on civ7 before switching

        clock[0] += 20_000
        _age_declared_logs(civ6, "civ6", clock[0])

        deadline = time.monotonic() + 3.0
        switched = poll_status(c)
        while time.monotonic() < deadline and switched.get("game_id") != "civ6":
            time.sleep(0.05)
            switched = poll_status(c)
        assert switched["game_id"] == "civ6"
        revision_at_switch = switched["revision"]

        # A real content change to civ6's own log, well after the switch settled --
        # nothing here should still be "pending" from the old civ7 watcher.
        with open(civ6 / "Player_Stats.csv", "a") as f:
            f.write("\n")

        deadline = time.monotonic() + 3.0
        after = switched
        while time.monotonic() < deadline and after["revision"] <= revision_at_switch:
            time.sleep(0.05)
            after = poll_status(c)

    assert after["revision"] > revision_at_switch
    assert after["game_id"] == "civ6"
