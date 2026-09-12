"""Questions about a decision: closed vocabulary, fair/oracle separation, no fabrication."""
from __future__ import annotations

import json
import threading

import pytest

from civ_advisor.llm import questions
from civ_advisor.llm.worker import CommentaryWorker

DECISION = {
    "id": "decision.culture.CITY", "subject": "Culture in Test1", "severity": "ADVISE",
    "priority_reason": "Culture is the worst observed gap here.",
    "observed_turns": [81],
    "preferred": {
        "id": "action.culture.inspect.CITY", "title": "Inspect Test1's culture options",
        "target": "Test1", "applicability": "inspect",
        "why_now": "Test1 finishes its current item next turn.",
        "steps": ["Open Test1 and its production list."],
        "trade_offs": ["Looking commits nothing."],
        "prerequisites": [{"name": "options offered here", "state": "unknown"}],
        "unknowns": ["Which options this settlement is offered is not in any log."],
        "evidence_ids": ["comparison.culture.81"], "guide_ids": ["guide.culture"],
    },
    "alternatives": [],
    "unknowns": ["No log states the current Age."],
    "evidence_ids": ["comparison.culture.81"],
}
FAIR_FACT = {"id": "comparison.culture.81", "label": "Your culture against the field",
             "kind": "derived", "provenance": "fair", "value": 0.44, "unit": "ratio",
             "observed_turn": 81, "note": "A deficit says where you trail."}
ORACLE_FACT = {"id": "defense.attack_goal.4.4.5.81", "label": "Rizal's objective",
               "kind": "log", "provenance": "oracle", "value": "Attack Enemy City",
               "unit": None, "observed_turn": 81, "note": None}
GUIDE = {"id": "guide.culture", "title": "Culture",
         "instructions": ["Open the settlement's production list."]}
IDENTITY = {"session": "s1", "epoch": 1, "evidence_mode": "oracle",
            "snapshot_revision": 7, "decision_revision": "abc123",
            "context_revision": 2, "catalog_revision": "cat-1", "turn": 81}


def request(kind: str = questions.WHY, *, evidence=None, guides=None, identity=None,
            text: str = "", decision=None, display_name: str | None = None) -> questions.QuestionRequest:
    kwargs = {} if display_name is None else {"display_name": display_name}
    return questions.build_request(
        kind, decision or DECISION,
        [FAIR_FACT] if evidence is None else evidence,
        [GUIDE] if guides is None else guides,
        dict(IDENTITY, **(identity or {})), player_text=text, **kwargs)


def test_only_the_four_known_kinds_are_accepted():
    for kind in questions.KINDS:
        assert request(kind, text="something").kind == kind
    with pytest.raises(ValueError, match="is not one of"):
        request("tell me a story")


def test_the_request_carries_exactly_the_ids_it_was_given():
    made = request()
    assert made.evidence_ids == ("comparison.culture.81",)
    assert made.action_ids == ("action.culture.inspect.CITY",)
    assert made.guide_ids == ("guide.culture",)


def test_the_prompt_names_the_actual_game_this_question_is_about():
    """The whole-phase review's Important: `questions.py` hardcoded "Civilization VII"
    regardless of which game the decision was about."""
    made = request()
    assert "You are a Civilization VII turn advisor" in questions.prompt_for(made)

    made = request(display_name="Civilization VI")
    prompt = questions.prompt_for(made)
    assert "You are a Civilization VI turn advisor" in prompt
    assert "Civilization VII" not in prompt


def test_the_cache_key_separates_fair_from_oracle_and_every_revision():
    base = request(identity={"evidence_mode": "oracle"})
    fair = request(identity={"evidence_mode": "fair"})
    assert base.cache_key != fair.cache_key, "a fair answer must never be served from oracle"
    for field, value in (("decision_revision", "def456"), ("context_revision", 3),
                         ("catalog_revision", "cat-2"), ("snapshot_revision", 8),
                         ("session", "s2"), ("epoch", 2)):
        assert request(identity={field: value}).cache_key != base.cache_key, field
    # The player's own words are part of the key, so two challenges are two answers.
    assert request(questions.CHALLENGE, text="a").cache_key \
        != request(questions.CHALLENGE, text="b").cache_key


def test_a_fair_request_can_only_hold_what_it_was_handed():
    """Filtering happens before the request exists, so this module cannot leak what it
    never received — and the schema is built from the request."""
    fair = request(identity={"evidence_mode": "fair"}, evidence=[FAIR_FACT])
    assert ORACLE_FACT["id"] not in fair.evidence_ids
    assert ORACLE_FACT["id"] not in questions.prompt_for(fair)
    enum = questions.response_schema(fair)["properties"]["evidence_ids"]["items"]["enum"]
    assert enum == ["comparison.culture.81"]


def test_the_grammar_is_the_decisions_own_vocabulary():
    schema = questions.response_schema(request())
    assert schema["properties"]["action_ids"]["items"]["enum"] == ["action.culture.inspect.CITY"]
    assert schema["properties"]["guide_ids"]["items"]["enum"] == ["guide.culture"]
    assert schema["additionalProperties"] is False
    # With nothing to cite there is no enum, because an empty one matches nothing and
    # would fail the whole generation rather than allowing no citations.
    bare = request(questions.WHY, guides=[])
    assert "enum" not in questions.response_schema(bare)["properties"]["guide_ids"]["items"]


def test_a_fabricated_citation_is_rejected():
    made = request()
    sentence = ("Culture is the widest observed gap here, and this settlement's queue "
                "frees up next turn.")
    good = {"text": sentence, "evidence_ids": ["comparison.culture.81"],
            "action_ids": [], "guide_ids": ["guide.culture"], "unknowns": []}
    assert questions.validate(made, good).text == sentence
    for field, invented in (("evidence_ids", "comparison.invented.99"),
                            ("action_ids", "action.made.up"),
                            ("guide_ids", "guide.does.not.exist")):
        with pytest.raises(ValueError, match="cites ids that were not supplied"):
            questions.validate(made, dict(good, **{field: [invented]}))


def test_a_model_written_url_is_rejected():
    """URLs come from the catalog, resolved server-side."""
    with pytest.raises(ValueError, match="contained a URL"):
        questions.validate(request(), {
            "text": "See https://example.com/guide for details.",
            "evidence_ids": [], "action_ids": [], "guide_ids": [], "unknowns": []})


def test_an_answer_with_no_text_is_rejected():
    with pytest.raises(ValueError, match="had no text"):
        questions.validate(request(), {"text": "   ", "evidence_ids": [], "action_ids": [],
                                       "guide_ids": [], "unknowns": []})


def test_a_question_with_nothing_to_answer_from_says_what_is_missing():
    empty = dict(DECISION, preferred=None, alternatives=[], evidence_ids=[])
    made = request(questions.INSPECT, evidence=[], guides=[], decision=empty)
    answerable, missing = questions.answerable(made)
    assert answerable is False
    assert any("No observation behind this decision" in m for m in missing)
    assert any("no reviewed candidate" in m.lower() for m in missing)
    assert any("No reviewed guide covers this mechanic" in m for m in missing)


def test_an_empty_challenge_has_nothing_to_weigh():
    answerable, missing = questions.answerable(request(questions.CHALLENGE))
    assert answerable is False and missing == ("Nothing was entered to weigh.",)


def test_the_fallback_answers_every_kind_from_structured_data_alone():
    why = questions.fallback(request(questions.WHY))
    assert "worst observed gap" in why.text and why.generated is False
    inspect = questions.fallback(request(questions.INSPECT))
    assert "In Test1:" in inspect.text and "production list" in inspect.text
    changes = questions.fallback(request(questions.WHAT_CHANGES))
    assert "No log states the current Age." in changes.text
    assert "Prerequisite not established: options offered here." in changes.text


def test_the_players_words_are_treated_as_intent_not_as_an_observation():
    made = request(questions.CHALLENGE, text="I already built a Monument here")
    answer = questions.fallback(made)
    assert "You said: I already built a Monument here" in answer.text
    assert "your intention, not as something observed" in answer.text
    # The prompt says the same thing to the model.
    prompt = questions.prompt_for(made)
    assert "never as something that has happened" in prompt
    assert "Do not agree that it is better unless a supplied fact says so" in prompt


def test_the_players_words_are_trimmed_before_they_reach_a_prompt():
    made = request(questions.CHALLENGE, text="x" * 900)
    assert len(made.player_text) == questions.CHALLENGE_LIMIT


# ---- the worker path -------------------------------------------------------------

def client_returning(payload: dict):
    class Client:
        model = "local:test"
        calls = 0

        def generate(self, prompt, *, schema=None):
            self.calls += 1
            return json.dumps(payload)

    return Client()


def test_a_validated_generation_replaces_the_structured_answer():
    worker = CommentaryWorker(client_returning({
        "text": "The culture gap is wide and this settlement's queue frees up next turn.",
        "evidence_ids": ["comparison.culture.81"], "action_ids": [],
        "guide_ids": ["guide.culture"], "unknowns": ["Availability is unknown."],
    }))  # type: ignore[arg-type]
    status, answer = worker.wait_for_answer(request(), timeout=3)
    assert status == "ready" and answer.generated is True
    assert answer.model == "local:test"
    assert answer.evidence_ids == ("comparison.culture.81",)
    worker.close()


def test_a_rejected_generation_falls_back_and_says_why():
    worker = CommentaryWorker(client_returning({
        "text": "Trust me.", "evidence_ids": ["comparison.invented.1"],
        "action_ids": [], "guide_ids": [], "unknowns": [],
    }))  # type: ignore[arg-type]
    status, answer = worker.wait_for_answer(request(), timeout=3)
    assert status == "fallback" and answer.generated is False
    assert "rejected" in answer.text
    assert "worst observed gap" in answer.text        # the deterministic answer stands
    worker.close()


def test_a_slow_model_never_delays_the_answer():
    """The structured answer is returned at once; the prose arrives later or not at all."""
    entered, release = threading.Event(), threading.Event()

    class SlowClient:
        model = "local:slow"

        def generate(self, prompt, *, schema=None):
            entered.set()
            release.wait(5)
            return json.dumps({
                "text": "This arrived long after the structured answer did.",
                "evidence_ids": [], "action_ids": [], "guide_ids": [], "unknowns": []})

    worker = CommentaryWorker(SlowClient())  # type: ignore[arg-type]
    status, answer = worker.answer(request())
    assert status == "generating"
    assert answer.generated is False and "worst observed gap" in answer.text
    assert entered.wait(2)
    release.set()
    worker.close()


def test_a_question_does_not_queue_behind_a_turns_commentary(fixture_state):
    """Commentary can take minutes on a large local model. A question asked now must not
    wait for it, and neither must the refinement workflow that follows."""
    from civ_advisor.advisors import run_all
    from tests.factories import snapshot as make_snapshot

    commentary_running, release = threading.Event(), threading.Event()

    class Client:
        model = "local:test"

        def generate(self, prompt, *, schema=None):
            if "second_opinion" in prompt:
                commentary_running.set()
                release.wait(5)
                raise RuntimeError("still going")
            return json.dumps({
                "text": "This was answered while the turn commentary was still running.",
                "evidence_ids": [], "action_ids": [], "guide_ids": [], "unknowns": []})

    worker = CommentaryWorker(Client())  # type: ignore[arg-type]
    worker.schedule(make_snapshot(fixture_state, run_all(fixture_state)))
    assert commentary_running.wait(2), "the commentary generation started"
    status, answer = worker.wait_for_answer(request(), timeout=3)
    assert status == "ready"
    assert answer.text == "This was answered while the turn commentary was still running."
    release.set()
    worker.close()


def test_an_unsupported_question_is_reported_rather_than_answered():
    worker = CommentaryWorker(client_returning({}))  # type: ignore[arg-type]
    empty = dict(DECISION, preferred=None, alternatives=[], evidence_ids=[])
    status, answer = worker.answer(
        request(questions.INSPECT, evidence=[], guides=[], decision=empty))
    assert status == "unsupported"
    assert answer.text == questions.UNSUPPORTED and answer.unknowns
    assert worker.client.calls == 0, "nothing was asked of the model"
    worker.close()


def test_visibly_broken_prose_is_rejected_even_when_its_citations_are_valid():
    """From a real local-model run: it cited a supplied id and returned
    "...in Test```json way=" — truncated, fenced, and useless.

    These are structural checks only. Passing them says nothing about whether the answer
    is correct, which is why generated prose stays labelled as interpretation and why
    every number and URL comes from the structured data instead.
    """
    made = request()
    base = {"evidence_ids": ["comparison.culture.81"], "action_ids": [],
            "guide_ids": [], "unknowns": []}
    for text, complaint in (
        ("Inspect the culture options in Test```json way=", "code fence"),
        ("Because.", "too short"),
        ("The culture gap is wide and the queue frees up next turn so you should", "mid-sentence"),
    ):
        with pytest.raises(ValueError, match=complaint):
            questions.validate(made, dict(base, text=text))
    # A complete sentence of reasonable length passes.
    good = ("Culture is the widest observed gap here and the settlement's queue frees up "
            "next turn, which makes its next choice worth deciding now.")
    assert questions.validate(made, dict(base, text=good)).text == good
