from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from civ7_advisor.api.app import create_app


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
    assert all(f["ok"] for f in body["files"].values())
    strategies = {s["strategy"]: s for s in body["standings"][4]["strategies"]}  # player 4
    assert strategies["CULTURAL"]["weight"] == 100 and strategies["CULTURAL"]["following"] is True


def test_insights_endpoint(client):
    body = client.get("/api/insights").json()
    assert body[0]["id"] == "threat.at_war.4"
    assert body[0]["severity"] == "CRITICAL" and body[0]["provenance"] == "oracle"
    assert all(i["why"] for i in body)


def test_index_and_static(client):
    assert "Civ VII Advisor" in client.get("/").text
    assert client.get("/static/index.html").status_code == 200


def test_state_is_503_before_first_rebuild(fixture_dir: Path):
    app = create_app(fixture_dir)  # no lifespan entered -> never rebuilt
    assert TestClient(app).get("/api/state").status_code == 503
