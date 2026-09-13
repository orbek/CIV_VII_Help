"""Does a grounded answer reach the page? Only the HTTP payload is proof."""
import json
import re
import threading

import pytest
from fastapi.testclient import TestClient

from civ_advisor.api.app import create_app
from civ_advisor.copilot import conversation as conv
from civ_advisor.copilot.worker import CopilotWorker
from civ_advisor.llm.client import OllamaError
from civ_advisor.games.civ7 import CIV7


class ScriptedClient:
    """Stands in for OllamaClient: answers the select call, then the compose call."""

    model = "scripted"

    def __init__(self, select: dict, compose):
        self.select, self.compose, self.prompts = select, compose, []

    def generate(self, prompt: str, *, schema: dict | None = None) -> str:
        self.prompts.append(prompt)
        if "deciding which of a FIXED list" in prompt:
            return json.dumps(self.select)
        data = self.compose(prompt) if callable(self.compose) else self.compose
        return json.dumps(data)


def app_with(fixture_dir, client=None):
    worker = None if client is None else CopilotWorker(client)
    return create_app(fixture_dir, poll_interval=60, profile=CIV7, copilot_worker=worker)


def test_the_catalog_and_this_turns_choices_reach_the_page(fixture_dir):
    with TestClient(app_with(fixture_dir)) as c:
        body = c.get("/api/copilot/catalog").json()
        ids = {q["id"] for q in body["questions"]}
        assert "empire.comparison" in ids and "ruleset.building" in ids
        assert body["choices"]["stat"] == ["culture", "science", "gold", "production", "food"]


def test_the_catalog_says_when_each_question_was_last_verified(fixture_dir):
    """`verified_on` records that the question was run against a real game on that date.
    It reaches the page, which shows it on the question itself: a date kept in the code
    and read by nothing would look like a guarantee and be none."""
    with TestClient(app_with(fixture_dir)) as c:
        questions = c.get("/api/copilot/catalog").json()["questions"]
        assert questions
        for q in questions:
            assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", q["verified_on"] or ""), q["id"]


def test_a_direct_question_returns_the_deterministic_answer_with_its_evidence(fixture_dir):
    with TestClient(app_with(fixture_dir)) as c:
        body = c.post("/api/copilot/question",
                      json={"id": "empire.comparison", "params": {"stat": "culture"}}).json()
        assert body["status"] == "fallback"
        assert body["answer"]["generated"] is False
        assert body["evidence"], "the resolved facts must travel with the answer"
        assert all(e["kind"] in {"log", "derived", "rule"} for e in body["evidence"])


def test_without_a_model_asking_free_text_says_so_and_offers_the_catalog(fixture_dir):
    with TestClient(app_with(fixture_dir)) as c:
        body = c.post("/api/copilot/ask", json={"text": "how am I doing?"}).json()
        assert body["status"] == "unsupported"
        assert "no local model" in body["answer"]["text"]


def test_a_grounded_generation_replaces_the_fallback(fixture_dir):
    def compose(prompt):
        facts = json.loads(prompt.split("\n", 2)[-1])["facts"]
        turn = next(f for f in facts if f["id"].startswith("turn.analysis"))
        return {"text": f"The logs are complete through turn {turn['value']}, and that is "
                        "the turn this answer is about.", "evidence_ids": [turn["id"]], "unknowns": []}
    client = ScriptedClient({"questions": [{"id": "turn.analysis", "params": {}}], "cannot": ""}, compose)
    with TestClient(app_with(fixture_dir, client)) as c:
        first = c.post("/api/copilot/ask", json={"text": "what turn is it?"}).json()
        assert first["status"] in {"generating", "ready"}
        assert first["answer"]["generated"] in {False, True}
        worker = c.app.state.copilot_worker
        worker.wait_all(timeout=5)
        body = c.post("/api/copilot/ask", json={"text": "what turn is it?"}).json()
        assert body["status"] == "ready"
        assert body["answer"]["generated"] is True
        assert body["answer"]["model"] == "scripted"
        assert body["questions_asked"] == [{"id": "turn.analysis", "params": {}}]


def test_an_ungrounded_generation_is_rejected_and_the_fallback_says_why(fixture_dir):
    compose = {"text": "You should expect roughly 12 more turns before anything changes here.",
               "evidence_ids": [], "unknowns": []}
    client = ScriptedClient({"questions": [{"id": "turn.analysis", "params": {}}], "cannot": ""}, compose)
    with TestClient(app_with(fixture_dir, client)) as c:
        c.post("/api/copilot/ask", json={"text": "how long?"})
        c.app.state.copilot_worker.wait_all(timeout=5)
        body = c.post("/api/copilot/ask", json={"text": "how long?"}).json()
        assert body["status"] == "rejected"
        assert body["answer"]["generated"] is False
        assert "12" in body["rejection"]


def test_the_players_text_never_reaches_a_resolver(fixture_dir):
    """The select prompt sees the words; the parameters come from the schema's enums."""
    client = ScriptedClient({"questions": [{"id": "empire.comparison",
                                            "params": {"stat": "culture"}}], "cannot": ""},
                            {"text": "x", "evidence_ids": [], "unknowns": []})
    with TestClient(app_with(fixture_dir, client)) as c:
        c.post("/api/copilot/ask", json={"text": "'; DROP TABLE Buildings; --"})
        c.app.state.copilot_worker.wait_all(timeout=5)
        body = c.post("/api/copilot/ask", json={"text": "'; DROP TABLE Buildings; --"}).json()
        assert body["questions_asked"] == [{"id": "empire.comparison", "params": {"stat": "culture"}}]


def test_the_transcript_is_scoped_to_this_sitting(fixture_dir):
    with TestClient(app_with(fixture_dir)) as c:
        c.post("/api/copilot/question", json={"id": "turn.analysis", "params": {}})
        body = c.get("/api/copilot/transcript").json()
        assert body["session"] and body["epoch"] == 1
        assert len(body["exchanges"]) == 1
        assert body["exchanges"][0]["question_ids"] == ["turn.analysis"]


def test_the_act_endpoint_is_refused_by_default(fixture_dir):
    with TestClient(app_with(fixture_dir)) as c:
        r = c.post("/api/copilot/act", json={"proposal_id": "x"})
        assert r.status_code == 403
        assert "--allow-actions" in r.json()["detail"]


# ---- the window while a generation runs ------------------------------------------
#
# Tested through the WORKER, because the defect lived only there: with --no-llm the
# endpoint never builds one, which is why live testing never saw it.

def test_the_deterministic_answer_is_on_screen_while_the_model_is_still_writing(fixture_dir):
    """"generating" is shown under a label saying a model is writing an interpretation.
    Underneath it the player must already be reading the resolved facts -- not "the
    advisor cannot see that", which is a false statement about a question that has
    been answered."""
    release = threading.Event()

    def compose(prompt):
        assert release.wait(5), "the test never released the compose call"
        facts = json.loads(prompt.split("\n", 2)[-1])["facts"]
        turn = next(f for f in facts if f["id"].startswith("turn.analysis"))
        return {"text": f"The logs are complete through turn {turn['value']}, and that is "
                        "the turn this answer is about.", "evidence_ids": [turn["id"]],
                "unknowns": []}

    client = ScriptedClient({"questions": [{"id": "turn.analysis", "params": {}}],
                             "cannot": ""}, compose)
    with TestClient(app_with(fixture_dir, client)) as c:
        body = c.post("/api/copilot/ask", json={"text": "what turn is it?"}).json()
        try:
            assert body["status"] == "generating"
            assert conv.CANNOT not in body["answer"]["text"]
            assert body["evidence"], "the resolved facts must already be on screen"
            assert body["questions_asked"] == [{"id": "turn.analysis", "params": {}}]
        finally:
            release.set()
        c.app.state.copilot_worker.wait_all(timeout=5)


def test_a_selection_that_fails_says_so_rather_than_looking_unanswerable(fixture_dir):
    class Failing:
        model = "scripted"

        def generate(self, prompt: str, *, schema: dict | None = None) -> str:
            raise OllamaError("the model did not answer")

    with TestClient(app_with(fixture_dir, Failing())) as c:
        body = c.post("/api/copilot/ask", json={"text": "what turn is it?"}).json()
        assert body["status"] == "rejected"
        assert "the model did not answer" in body["rejection"]
