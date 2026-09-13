"""The conversation: closed vocabularies in, grounded prose or the deterministic answer out."""
import json

import pytest

from civ_advisor.copilot import conversation as conv
from civ_advisor.copilot.catalog import CATALOG, ParamKind
from civ_advisor.decisions.context import build_context


@pytest.fixture
def context(civ7_store):
    return build_context(civ7_store.rebuild())


def request(context, text="How is my culture doing?", history=()):
    return conv.ChatRequest(
        text=text, session="s1", epoch=1, snapshot_revision=3, context_revision=0,
        evidence_mode="oracle", turn=context.analysis_turn, display_name="Civilization VII",
        context=context, history=tuple(history))


def test_the_players_text_is_trimmed_to_the_limit(context):
    made = request(context, text="x" * 2000)
    assert len(made.text) == conv.ASK_LIMIT


def test_the_select_schema_enumerates_exactly_this_polls_choices(context):
    schema = conv.select_schema(request(context))
    ids = schema["properties"]["questions"]["items"]["properties"]["id"]["enum"]
    assert set(ids) == set(CATALOG)
    params = schema["properties"]["questions"]["items"]["properties"]["params"]["properties"]
    assert params["stat"]["enum"] == list(conv.catalog.choices(context)[ParamKind.STAT])
    assert params["item"]["pattern"] == conv.catalog.TYPE_KEY.pattern
    assert schema["properties"]["questions"]["maxItems"] == conv.MAX_QUESTIONS


def test_the_select_prompt_carries_the_players_words_as_a_question_not_a_fact(context):
    prompt = conv.select_prompt(request(context, text="I have 40 gold"))
    assert "I have 40 gold" in prompt
    assert "not an observation" in prompt


def test_parse_selection_keeps_only_catalog_ids_and_caps_the_count(context):
    data = {"questions": [{"id": "empire.comparison", "params": {"stat": "culture"}},
                          {"id": "empire.everything", "params": {}}] * 6, "cannot": ""}
    selected = conv.parse_selection(request(context), data)
    assert len(selected) <= conv.MAX_QUESTIONS
    assert all(s.question_id in CATALOG or s.question_id == "empire.everything" for s in selected)


def test_resolve_separates_facts_from_absences(context):
    selected = (conv.Selected("empire.comparison", {"stat": "culture"}),
                conv.Selected("empire.everything", {}),
                conv.Selected("ruleset.building", {"item": "BUILDING_LIBRARY"}))
    resolved = conv.resolve(request(context), selected)
    assert resolved.facts
    kinds = {a.kind.value for a in resolved.absences}
    assert "not_in_catalog" in kinds and "ruleset_unavailable" in kinds


def test_the_compose_schema_enumerates_only_resolved_fact_ids(context):
    resolved = conv.resolve(request(context), (conv.Selected("empire.comparison", {"stat": "culture"}),))
    schema = conv.compose_schema(request(context), resolved)
    assert set(schema["properties"]["evidence_ids"]["items"]["enum"]) == {f.id for f in resolved.facts}
    assert "proposal" not in schema["properties"]


def test_a_composed_answer_with_an_ungrounded_number_is_rejected(context):
    resolved = conv.resolve(request(context), (conv.Selected("empire.comparison", {"stat": "culture"}),))
    fact = next(f for f in resolved.facts if f.id.startswith("comparison."))
    data = {"text": "You trail the median and it will take about 12 turns to catch up.",
            "evidence_ids": [fact.id], "unknowns": []}
    with pytest.raises(ValueError, match="12"):
        conv.validate_answer(request(context), resolved, data)


def test_a_composed_answer_whose_numbers_are_cited_passes(context):
    resolved = conv.resolve(request(context), (conv.Selected("turn.analysis", {}),))
    (fact,) = resolved.facts
    data = {"text": f"The logs are complete through turn {fact.value}, so that is the turn "
                    "this answer describes.", "evidence_ids": [fact.id], "unknowns": []}
    answer = conv.validate_answer(request(context), resolved, data)
    assert answer.generated and answer.evidence_ids == (fact.id,)


def test_a_composed_answer_may_not_cite_an_id_it_was_not_given(context):
    resolved = conv.resolve(request(context), (conv.Selected("turn.analysis", {}),))
    data = {"text": "This is a long enough sentence to count as an answer here.",
            "evidence_ids": ["gold.net.9"], "unknowns": []}
    with pytest.raises(ValueError, match="not supplied"):
        conv.validate_answer(request(context), resolved, data)


def test_history_numbers_are_not_admitted(context):
    """An earlier answer said 7. This answer must cite a fact that says so now."""
    earlier = conv.Exchange(id="e1", asked_at="2026-09-13T10:00:00Z", turn=80,
                            text="net gold?", answer_text="Your net gold is 7.",
                            status="ready", question_ids=("empire.net_gold",),
                            evidence_ids=("gold.net.80",))
    made = request(context, history=[earlier])
    resolved = conv.resolve(made, (conv.Selected("turn.analysis", {}),))
    data = {"text": "As before, your net gold is 7 and that has not changed at all.",
            "evidence_ids": [resolved.facts[0].id], "unknowns": []}
    with pytest.raises(ValueError, match="7"):
        conv.validate_answer(made, resolved, data)


def test_the_fallback_names_every_fact_with_its_source_and_every_absence(context):
    selected = (conv.Selected("empire.comparison", {"stat": "culture"}),
                conv.Selected("ruleset.building", {"item": "BUILDING_LIBRARY"}))
    resolved = conv.resolve(request(context), selected)
    answer = conv.fallback(request(context), resolved)
    assert not answer.generated
    for fact in resolved.facts:
        assert fact.label in answer.text
    assert "no queryable ruleset" in answer.text
    assert "Player_Stats.csv" in answer.text


def test_the_fallback_with_nothing_resolved_says_it_cannot_see_that(context):
    answer = conv.fallback(request(context), conv.Resolved())
    assert "cannot" in answer.text.lower()
    assert conv.grounding.check(answer.text, (), []).ok


def test_the_fallback_repeats_a_typed_number_only_as_the_players_statement(context):
    answer = conv.fallback(request(context, text="is 8 turns for a Granary good?"), conv.Resolved())
    assert "You mention 8" in answer.text and "your statement" in answer.text
    assert conv.grounding.check(answer.text, (), [], player_text="is 8 turns for a Granary good?").ok


def test_fallback_rounds_a_float_facts_value_to_one_decimal(context):
    """The bug this guards: asking `empire.upkeep` against a real running game
    produced "Your net gold per turn, read live: 12.8984375 per turn" -- the
    DETERMINISTIC answer, shown first and shown on every generation failure, so
    this is the sentence a player reads far more often than any model's. It came
    from `fallback` -> `_value` printing `fact.value` bare; the tuner carries full
    float precision by design (see queries.py's `_parse_number`), so nothing
    upstream of `_value` was ever going to round it."""
    from civ_advisor.decisions.models import EvidenceFact, SourceKind
    from civ_advisor.advisors.base import Provenance

    fact = EvidenceFact(
        id="tuner.net_gold.126", label="Your net gold per turn, read live",
        source_kind=SourceKind.LIVE_READING, provenance=Provenance.FAIR,
        observed_turn=126, reported_at="2026-09-13T18:59:04+00:00",
        value=12.8984375, unit="per turn")
    answer = conv.fallback(request(context), conv.Resolved(facts=(fact,)))
    assert "12.8984375" not in answer.text
    assert "12.9 per turn" in answer.text


def test_source_phrases_keep_the_five_kinds_apart(context):
    resolved = conv.resolve(request(context), (conv.Selected("empire.comparison", {"stat": "culture"}),))
    phrases = {conv.source_phrase(f) for f in resolved.facts}
    assert any("advisor rule" in p for p in phrases)
    assert any("Player_Stats.csv" in p for p in phrases)
    assert any("computed from" in p for p in phrases)


def test_the_transcript_is_scoped_to_session_and_epoch():
    t = conv.Transcript()
    e = conv.Exchange(id="e1", asked_at="t", turn=1, text="q", answer_text="a", status="ready",
                      question_ids=(), evidence_ids=())
    t.record("s1", 1, e)
    assert t.history("s1", 1) == (e,)
    assert t.history("s1", 2) == ()
    assert t.history("s2", 1) == ()


def test_history_offered_to_the_model_is_capped_and_dated(context):
    exchanges = [conv.Exchange(id=f"e{i}", asked_at="t", turn=70 + i, text=f"q{i}",
                               answer_text=f"a{i}", status="ready", question_ids=(),
                               evidence_ids=()) for i in range(10)]
    prompt = conv.compose_prompt(request(context, history=exchanges), conv.Resolved())
    assert "q9" in prompt and "q0" not in prompt
    assert "turn 79" in prompt
    assert "context only" in prompt


def test_an_absence_reaches_both_answers_as_its_own_cause(context):
    """Six tuner causes exist because collapsing them shipped a defect (spec 4.6). The
    cause travels with the absence into the prompt and into the deterministic answer."""
    absence = conv.catalog.Absence(
        "empire.upkeep", conv.catalog.Unanswerable.TUNER_ABSENT,
        "the tuner is enabled but the game is not answering", cause="not_answering")
    resolved = conv.Resolved(absences=(absence,))
    assert conv.absence_payload(absence)["cause"] == "not_answering"
    assert '"cause":"not_answering"' in conv.compose_prompt(request(context), resolved)
    text = conv.fallback(request(context), resolved).text
    assert "the tuner is enabled but the game is not answering" in text
    assert "not_answering" in text


def test_the_disagreement_rule_is_enforced_on_a_composed_answer(context):
    """Spec 4.3 rule 7: the player's figure repeated alone, with a cited figure unstated,
    is the quiet adoption the rule exists to stop. Both numbers, or neither."""
    made = request(context, text="is 8 turns right?")
    resolved = conv.resolve(made, (conv.Selected("turn.analysis", {}),))
    (fact,) = resolved.facts
    alone = {"text": "You mention 8 turns, which is a reasonable thing to be asking about.",
             "evidence_ids": [fact.id], "unknowns": []}
    with pytest.raises(ValueError, match="8"):
        conv.validate_answer(made, resolved, alone)
    both = {"text": f"You mention 8 turns; the logs are complete through turn {fact.value}, "
                    "so that is what the advisor can establish.",
            "evidence_ids": [fact.id], "unknowns": []}
    assert conv.validate_answer(made, resolved, both).generated


def test_an_absence_that_ends_in_a_sentence_does_not_get_a_second_full_stop():
    """Seen live: "... ask `empire.upkeep`.." — the detail already ended in a stop."""
    from civ_advisor.copilot.catalog import Absence, Unanswerable
    from civ_advisor.copilot.conversation import _absence_sentence

    ends_in_stop = Absence("empire.net_gold", Unanswerable.NOT_LOGGED,
                           "Civilization VI writes no log for this; ask `empire.upkeep`.")
    assert _absence_sentence(ends_in_stop).endswith("`empire.upkeep`.")
    assert not _absence_sentence(ends_in_stop).endswith("..")

    bare = Absence("empire.net_gold", Unanswerable.NOT_LOGGED, "no rival row to compare")
    assert _absence_sentence(bare).endswith("compare.")
