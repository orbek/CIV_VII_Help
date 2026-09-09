"""Evidence facts: typed source keys, honest derivations, and nothing invented."""
from __future__ import annotations

import pytest

from civ7_advisor.advisors.base import Provenance, Severity
from civ7_advisor.decisions.evidence import (
    EvidenceLedger,
    age_fact,
    build_ledger,
    completed_item_facts,
    defense_facts,
    happiness_fact,
    human_identity_fact,
    net_gold_fact,
    queue_facts,
    settlement_coverage_fact,
    yield_comparison_fact,
)
from civ7_advisor.decisions.models import (
    ActionCandidate,
    Applicability,
    DecisionCard,
    EvidenceFact,
    PlayerReport,
    Prerequisite,
    SourceKind,
)
from tests.factories import game_state


def test_a_log_fact_records_where_the_number_came_from(fixture_v2_state):
    ledger = build_ledger(fixture_v2_state)
    turn = fixture_v2_state.complete_through_turn
    fact = ledger.get(f"yield.culture.0.{turn}")
    assert fact is not None
    assert fact.source_kind is SourceKind.LOG
    assert fact.source_file == "Player_Stats.csv"
    # A typed key into the parsed rows, not a sentence to be re-parsed.
    assert fact.record_key == ("Player_Stats.csv", turn, 0)
    assert fact.observed_turn == turn and fact.age_in(turn) == 0
    assert fact.age_in(turn + 4) == 4


def test_a_derived_comparison_cites_every_row_and_the_rule_it_applied(fixture_v2_state):
    ledger = EvidenceLedger()
    turn = fixture_v2_state.complete_through_turn
    comparison = yield_comparison_fact(ledger, fixture_v2_state, "culture")
    assert comparison is not None and comparison.source_kind is SourceKind.DERIVED
    cited = ledger.resolve(comparison.contributing)
    assert ledger.get(f"yield.culture.0.{turn}") in cited          # the human's own row
    rivals = [f for f in cited if f.subject_id not in (None, "0") and f.source_file]
    assert len(rivals) == len(fixture_v2_state.rivals())            # every rival it compared
    # The threshold is citable, and is not dressed up as an observation.
    threshold = ledger.get("rule.economy.behind_ratio")
    assert threshold in cited
    assert threshold.source_kind is SourceKind.RULE and threshold.observed_turn is None
    assert "not an observation" in threshold.note
    assert "not which investment is best" in comparison.note


def test_a_derived_fact_must_cite_its_inputs_and_a_log_fact_must_name_its_file():
    with pytest.raises(ValueError, match="must cite the facts"):
        EvidenceFact(id="d", label="l", source_kind=SourceKind.DERIVED,
                     provenance=Provenance.FAIR, observed_turn=1)
    with pytest.raises(ValueError, match="must name its source file"):
        EvidenceFact(id="l", label="l", source_kind=SourceKind.LOG,
                     provenance=Provenance.FAIR, observed_turn=1)


def test_oracle_provenance_propagates_through_a_derivation():
    """A comparison built on an intercepted fact is itself intercepted. Dropping the
    sentence that mentions it would not make the conclusion fair."""
    ledger = EvidenceLedger()
    ledger.add(EvidenceFact(id="secret", label="AI intent", source_kind=SourceKind.LOG,
                            provenance=Provenance.ORACLE, observed_turn=5,
                            source_file="AI_DiplomaticActions.csv"))
    ledger.add(EvidenceFact(id="open", label="Your gold", source_kind=SourceKind.LOG,
                            provenance=Provenance.FAIR, observed_turn=5,
                            source_file="Player_Stats.csv"))
    ledger.add(EvidenceFact(id="mid", label="step", source_kind=SourceKind.DERIVED,
                            provenance=Provenance.FAIR, observed_turn=5,
                            contributing=("secret",)))
    ledger.add(EvidenceFact(id="top", label="conclusion", source_kind=SourceKind.DERIVED,
                            provenance=Provenance.FAIR, observed_turn=5,
                            contributing=("mid",)))
    assert ledger.provenance_of(("open",)) is Provenance.FAIR
    assert ledger.provenance_of(("top",)) is Provenance.ORACLE      # two levels down
    assert ledger.provenance_of(("open", "top")) is Provenance.ORACLE


def test_reusing_an_evidence_id_for_a_different_fact_is_refused():
    ledger = EvidenceLedger()
    first = EvidenceFact(id="x", label="one", source_kind=SourceKind.LOG,
                         provenance=Provenance.FAIR, observed_turn=1, source_file="a.csv")
    ledger.add(first)
    ledger.add(first)                                               # idempotent
    with pytest.raises(ValueError, match="already used"):
        ledger.add(EvidenceFact(id="x", label="two", source_kind=SourceKind.LOG,
                                provenance=Provenance.FAIR, observed_turn=1, source_file="a.csv"))


def test_an_unresolvable_citation_is_an_error_not_a_dead_link():
    ledger = EvidenceLedger()
    with pytest.raises(KeyError, match="unresolved evidence ids: nope"):
        ledger.resolve(("nope",))


def test_queue_coverage_says_how_many_settlements_were_not_observed(fixture_v2_state):
    """The plan's warning made concrete: this real session logs one queue for six
    settlements, so nothing may be said about the other five."""
    ledger = EvidenceLedger()
    coverage = settlement_coverage_fact(ledger, fixture_v2_state)
    settlements = fixture_v2_state.at(0).settlements
    assert coverage.value == 1 and settlements == 6
    assert "1 of 6 settlements has a logged queue" in coverage.note
    assert "5 are unobserved. Their queues are unknown, not idle." in coverage.note
    assert len(ledger.resolve(coverage.contributing)) == 2


def test_queue_facts_date_the_row_and_label_the_estimate_as_ours(fixture_v2_state):
    ledger = EvidenceLedger()
    facts = queue_facts(ledger, fixture_v2_state)
    assert facts and all(f.source_file == "CityBuildQueue.csv" for f in facts)
    fact = facts[0]
    assert fact.record_key[:2] == ("CityBuildQueue.csv", fact.observed_turn)
    assert fact.subject_id.startswith("LOC_CITY_NAME_")
    assert "not the game's own forecast" in fact.note


def test_completed_items_are_evidence_of_completion_not_a_completion_event(fixture_v2_state):
    ledger = EvidenceLedger()
    facts = completed_item_facts(ledger, fixture_v2_state)
    assert facts, "the fixture builds things"
    fact = facts[0]
    assert fact.source_kind is SourceKind.DERIVED
    assert "Evidence of completion, not a completion event" in fact.note
    progress = ledger.resolve(fact.contributing)[0]
    assert progress.source_kind is SourceKind.LOG and progress.source_file == "CityBuildQueue.csv"


def test_the_age_fact_dates_the_age_without_claiming_it_is_current(fixture_v2_state):
    ledger = EvidenceLedger()
    fact = age_fact(ledger, fixture_v2_state)
    assert fact is not None and fact.value == "AGE_ANTIQUITY"
    assert fact.observed_turn == fixture_v2_state.complete_through_turn
    assert "does not prove the Age has not changed since" in fact.note


def test_two_ages_on_one_turn_make_the_current_age_unreadable(fixture_v2_state):
    """A transition turn. Picking either label would be a guess."""
    from copy import deepcopy
    from dataclasses import replace as dc_replace

    state = deepcopy(fixture_v2_state)
    newest = max(e.turn for e in state.events if e.turn <= state.complete_through_turn)
    sample = next(e for e in state.events if e.turn == newest)
    state.events.append(dc_replace(sample, age="AGE_EXPLORATION"))
    fact = age_fact(EvidenceLedger(), state)
    assert fact.value == "AGE_ANTIQUITY / AGE_EXPLORATION"
    assert "cannot be read off this log" in fact.note


def test_human_identity_is_carried_explicitly(fixture_v2_state):
    fact = human_identity_fact(EvidenceLedger(), fixture_v2_state)
    assert fact is not None
    assert fact.value == "CIVILIZATION_AMERICA / LEADER_BENJAMIN_FRANKLIN"
    assert fact.source_file == "GameCore.log" and fact.observed_turn is None
    assert "carries no turn of its own" in fact.note


def test_defense_facts_are_oracle_and_never_report_quiet_as_safe(fixture_v2_state):
    ledger = EvidenceLedger()
    facts = defense_facts(ledger, fixture_v2_state)
    assert facts and all(f.provenance is Provenance.ORACLE for f in facts)
    coverage = facts[-1]
    assert "does not mean the frontier is safe" in coverage.note


def test_absent_optional_sources_produce_no_fact_rather_than_a_zero(fixture_dir):
    """No treasury or happiness row means net gold and happiness are *missing*. A
    placeholder zero would read as "you are breaking even"."""
    bare = game_state()                          # no treasury, no happiness, no queues
    ledger = EvidenceLedger()
    assert net_gold_fact(ledger, bare) is None
    assert happiness_fact(ledger, bare) is None
    assert queue_facts(ledger, bare) == ()
    assert human_identity_fact(ledger, bare) is None
    assert age_fact(ledger, bare) is None
    assert ledger.facts == {}


def test_the_pilot_ledger_is_deterministic(fixture_v2_state):
    first = build_ledger(fixture_v2_state)
    second = build_ledger(fixture_v2_state)
    assert first.facts == second.facts
    assert first.turns == second.turns


# ---- contracts ------------------------------------------------------------------

def test_a_candidate_cannot_be_ready_with_an_unknown_prerequisite():
    """The whole point of the applicability field. "Ready" means established, and an
    unknown prerequisite is never treated as met."""
    with pytest.raises(ValueError, match="cannot be ready"):
        ActionCandidate(
            id="a", title="Build it", target="Test City", why_now="behind on culture",
            applicability=Applicability.READY, steps=("do it",),
            prerequisites=(("available in this settlement", Prerequisite.UNKNOWN),),
        )
    conditional = ActionCandidate(
        id="a", title="Build it", target="Test City", why_now="behind on culture",
        applicability=Applicability.CONDITIONAL, steps=("do it",),
        prerequisites=(("available in this settlement", Prerequisite.UNKNOWN),),
    )
    assert conditional.unproven == ("available in this settlement",)
    assert conditional.unmet == ()


def test_a_candidate_must_say_what_to_do_or_what_to_inspect():
    with pytest.raises(ValueError, match="must say what to do"):
        ActionCandidate(id="a", title="t", target="c", why_now="w",
                        applicability=Applicability.INSPECT)


def test_a_player_report_stays_a_separate_source_kind():
    report = PlayerReport(
        id="report.monument.preview", subject="LOC_CITY_NAME_TEST", label="Monument culture",
        value=3, unit="per turn", observed_turn=33, session="session-1",
        reported_at="2026-09-08T12:00:00", base_revision=7,
    )
    fact = report.fact()
    assert fact.source_kind is SourceKind.PLAYER_REPORT
    assert fact.observed_turn == 33 and fact.reported_at == "2026-09-08T12:00:00"
    assert fact.source_file is None          # it is not a log row and must not look like one


def test_a_decision_card_lists_its_preferred_candidate_first():
    steps = ("inspect the production list",)
    preferred = ActionCandidate(id="p", title="p", target="c", why_now="w",
                                applicability=Applicability.INSPECT, steps=steps)
    other = ActionCandidate(id="o", title="o", target="c", why_now="w",
                            applicability=Applicability.INSPECT, steps=steps)
    card = DecisionCard(id="d", subject="Test City", severity=Severity.ADVISE,
                        priority_reason="worst observed gap", preferred=preferred,
                        alternatives=(other,))
    assert card.candidates == (preferred, other)
