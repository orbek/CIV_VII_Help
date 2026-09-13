"""The catalog is the allowlist: a question not written here cannot be asked, a
parameter outside its set never reaches a resolver, and every absence names its cause."""
import re

import pytest

from civ_advisor.copilot.catalog import (
    CATALOG, TYPE_KEY, Absence, ParamKind, Unanswerable, ask, choices,
)
from civ_advisor.decisions.context import build_context
from civ_advisor.decisions.models import SourceKind
from civ_advisor.games.civ7 import CIV7


@pytest.fixture
def civ7_context(civ7_store):
    return build_context(civ7_store.rebuild())


@pytest.fixture
def civ6_context(civ6_store):
    return build_context(civ6_store.rebuild())


def test_every_question_declares_its_parameters_and_a_verified_date():
    for q in CATALOG.values():
        assert q.verified_on, q.id
        assert q.description, q.id
        for p in q.params:
            assert isinstance(p.kind, ParamKind), (q.id, p.name)


def test_question_ids_are_dotted_lowercase():
    for qid in CATALOG:
        assert re.fullmatch(r"[a-z_]+(\.[a-z_]+)+", qid), qid


def test_an_unknown_question_is_an_absence_not_an_error(civ7_context):
    got = ask(civ7_context, "empire.everything", {})
    assert got.facts == ()
    assert got.absence is not None
    assert got.absence.kind is Unanswerable.NOT_IN_CATALOG


def test_a_parameter_outside_its_set_never_reaches_the_resolver(civ7_context):
    got = ask(civ7_context, "empire.comparison", {"stat": "faith'; DROP TABLE x"})
    assert got.absence is not None
    assert got.absence.kind is Unanswerable.BAD_PARAMETER
    assert "faith" in got.absence.detail


def test_choices_come_from_this_snapshot(civ7_context):
    got = choices(civ7_context)
    assert got[ParamKind.STAT] == ("culture", "science", "gold", "production", "food")
    assert all(isinstance(c, str) and c for c in got[ParamKind.CITY])


def test_type_key_regex_admits_game_keys_and_nothing_else():
    assert TYPE_KEY.fullmatch("BUILDING_LIBRARY")
    assert TYPE_KEY.fullmatch("TECH_WRITING")
    assert not TYPE_KEY.fullmatch("building_library")
    assert not TYPE_KEY.fullmatch("BUILDING LIBRARY")
    assert not TYPE_KEY.fullmatch("X")


def test_the_analysis_turn_is_a_log_fact(civ7_context):
    got = ask(civ7_context, "turn.analysis", {})
    (fact,) = got.facts
    assert fact.source_kind is SourceKind.LOG
    assert fact.value == civ7_context.analysis_turn
    assert fact.source_file == "Player_Stats.csv"


def test_a_comparison_resolves_to_derived_facts_citing_their_inputs(civ7_context):
    got = ask(civ7_context, "empire.comparison", {"stat": "culture"})
    assert got.absence is None
    kinds = {f.source_kind for f in got.facts}
    assert SourceKind.DERIVED in kinds and SourceKind.RULE in kinds and SourceKind.LOG in kinds


def test_a_capability_this_game_does_not_log_is_absent_with_the_profiles_own_reason(civ6_context):
    """Civ VI writes no happiness log; the reason is the profile's, not a generic one."""
    got = ask(civ6_context, "empire.happiness", {})
    assert got.facts == ()
    assert got.absence.kind is Unanswerable.TUNER_ABSENT   # Civ VI backs it by tuner
    assert got.absence.cause in {"not_enabled", "not_answering", "unreachable",
                                 "no_socket", "not_asked"}


def test_an_oracle_question_in_fair_mode_is_hidden_not_missing(civ7_store):
    context = build_context(civ7_store.rebuild(), oracle=False)
    got = ask(context, "defense.objectives", {})
    assert got.facts == ()
    assert got.absence.kind is Unanswerable.ORACLE_HIDDEN


def test_the_brief_resolves_to_the_facts_the_cards_cite(civ7_context):
    got = ask(civ7_context, "decisions.brief", {})
    assert got.absence is None
    assert all(f.id in civ7_context.ledger.facts for f in got.facts)


def test_player_reports_are_their_own_kind(civ7_context):
    got = ask(civ7_context, "player.reports", {})
    assert all(f.source_kind is SourceKind.PLAYER_REPORT for f in got.facts)
