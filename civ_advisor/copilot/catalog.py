"""The fixed set of questions the copilot may ask, and how each is answered.

An allowlist in exactly the sense of tuner/queries.py and ruleset/civ6.py's
READABLE_COLUMNS: a question not written here cannot be asked. The model names an
entry and supplies parameter values; every parameter has a kind, and the kind decides
what may reach the resolver -- a member of a fixed set, a name this snapshot actually
contains, or a bound SQL value matching TYPE_KEY. No player text is ever a parameter.

Every resolver produces EvidenceFacts through the builders decisions/evidence.py already
has, so a fact the conversation cites is the same fact -- same id, kind, turn, note -- a
decision card would show. An unanswerable question resolves to an Absence carrying a
kind the page branches on and the REAL cause: the profile's own reason for a log this
game does not write, the tuner's own enum, the ruleset provider's own sentence.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Callable

from civ_advisor.advisors.base import Provenance
from civ_advisor.decisions import evidence
from civ_advisor.decisions.context import DecisionContext
from civ_advisor.decisions.models import EvidenceFact
from civ_advisor.games.base import Capability
from civ_advisor.games.registry import get_profile
from civ_advisor.ruleset.civ6 import RULE_PARAMETERS

TYPE_KEY = re.compile(r"[A-Z][A-Z0-9_]{2,63}")


class Unanswerable(StrEnum):
    NOT_LOGGED = "not_logged"                  # this game writes no log that could answer it
    TUNER_ABSENT = "tuner_absent"              # a live reading was needed; `cause` says why none
    RULESET_UNAVAILABLE = "ruleset_unavailable"
    NO_SUCH_ROW = "no_such_row"                # the ruleset has no row for that key
    ORACLE_HIDDEN = "oracle_hidden"            # it exists, and Oracle is off
    BAD_PARAMETER = "bad_parameter"            # a value outside the parameter's set
    NOT_IN_CATALOG = "not_in_catalog"
    # The source was consulted, it answered, and its answer holds nothing for this
    # subject. That is an EMPTY RESULT, which is a fact about the game, and not an
    # inability to see -- the two were one sentence until this kind existed, and the
    # first read as a failure of the advisor when nothing had failed at all.
    ANSWERED_EMPTY = "answered_empty"
    # A query inside the allowlist failed at the database itself, because a mod or a
    # patch reshaped the table it reads. Whether the ruleset holds a row for that key
    # was never established, so NO_SUCH_ROW would be a claim about the player's file
    # that nothing read.
    RULESET_SCHEMA = "ruleset_schema"


@dataclass(frozen=True)
class Absence:
    question: str
    kind: Unanswerable
    detail: str
    cause: str | None = None     # a TunerUnavailable value, for TUNER_ABSENT

    def describe(self) -> str:
        return f"{self.question}: {self.detail}"


class ParamKind(StrEnum):
    STAT = "stat"                      # one of YIELD_STATS
    CITY = "city"                      # a settlement name in this snapshot or reading
    TYPE_KEY = "type_key"              # a game type key, bound as a SQL value
    PARAMETER_NAME = "parameter_name"  # one of RULE_PARAMETERS


@dataclass(frozen=True)
class Param:
    name: str
    kind: ParamKind
    description: str


@dataclass(frozen=True)
class Resolution:
    facts: tuple[EvidenceFact, ...] = ()
    absence: Absence | None = None
    notes: tuple[str, ...] = ()      # deterministic sentences the model may read that
                                      # are not facts -- e.g. a RulesetMention.as_unknown()


Resolver = Callable[[DecisionContext, dict[str, str]], Resolution]


@dataclass(frozen=True)
class Question:
    id: str
    description: str          # what the model reads to choose it
    resolve: Resolver
    params: tuple[Param, ...] = ()
    verified_on: str = ""
    oracle: bool = False      # answered only with Oracle on
    # Set on the question that reads THIS capability live when a game's log cannot.
    # `_not_logged` derives which question to name from this field rather than a
    # hardcoded capability -> question-id table in the absence message, so a
    # question added or renamed later cannot leave that message pointing at a
    # question that no longer exists or missing one that now covers it.
    live_answers: Capability | None = None


def _city_names(context: DecisionContext) -> tuple[str, ...]:
    names: list[str] = []
    for s in context.settlements:
        for n in (s.name, s.city):
            if n and n not in names:
                names.append(n)
    tuner = context.tuner
    if tuner.available:
        for a in tuner.amenities:
            if a.city not in names:
                names.append(a.city)
        for so in tuner.build_options:
            if so.city not in names:
                names.append(so.city)
        for so in tuner.build_option_ids:
            if so.city not in names:
                names.append(so.city)
    return tuple(names)


def choices(context: DecisionContext) -> dict[ParamKind, tuple[str, ...]]:
    """The valid values for each enumerable parameter kind, from THIS snapshot."""
    return {
        ParamKind.STAT: evidence.YIELD_STATS,
        ParamKind.CITY: _city_names(context),
        ParamKind.PARAMETER_NAME: tuple(sorted(RULE_PARAMETERS)),
    }


def _validate(context: DecisionContext, question: Question,
              params: dict[str, str]) -> Absence | None:
    valid = choices(context)
    for p in question.params:
        value = params.get(p.name)
        if not isinstance(value, str) or not value:
            return Absence(question.id, Unanswerable.BAD_PARAMETER,
                           f"{p.name} was not supplied")
        if p.kind is ParamKind.TYPE_KEY:
            if not TYPE_KEY.fullmatch(value):
                return Absence(question.id, Unanswerable.BAD_PARAMETER,
                               f"{value!r} is not a game type key")
        elif value not in valid[p.kind]:
            return Absence(question.id, Unanswerable.BAD_PARAMETER,
                           f"{value!r} is not one of the {p.kind.value} values this turn")
    return None


def ask(context: DecisionContext, question_id: str, params: dict[str, str]) -> Resolution:
    """Resolve one question, or say precisely why it cannot be. Never raises for a
    bad id or a bad parameter: those are the model's mistakes, reported as absences."""
    question = CATALOG.get(question_id)
    if question is None:
        return Resolution(absence=Absence(question_id, Unanswerable.NOT_IN_CATALOG,
                                          "no catalog question covers this"))
    bad = _validate(context, question, params)
    if bad is not None:
        return Resolution(absence=bad)
    if question.oracle and context.evidence_mode != "oracle":
        return Resolution(absence=Absence(
            question.id, Unanswerable.ORACLE_HIDDEN,
            "this reads the AI's own logs, and Oracle is off"))
    return question.resolve(context, params)


# ---- log-backed resolvers ------------------------------------------------------------

def _live_question_for(capability: Capability) -> Question | None:
    """Which catalog question reads `capability` live, if any -- see
    `Question.live_answers` for why this is a lookup over the catalog's own data
    rather than a table hand-maintained beside this message."""
    return next((q for q in CATALOG.values() if q.live_answers is capability), None)


def _not_logged(context: DecisionContext, question_id: str,
                capability: Capability) -> Resolution:
    """The absence for a capability this game's LOG cannot answer.

    Three genuinely different situations, and collapsing any two of them produces
    a false reason:

    - tuner-backed and the tuner is AVAILABLE: the log truly has nothing, but a
      live reading does -- named here, by question id, so the player is not left
      to guess it. `tuner.reason` is None exactly when the tuner is working, so
      it must NEVER be printed in this branch: a live probe against a real game
      did exactly that -- `empire.net_gold` answered "the tuner supplied no
      reading this poll" in the same second `empire.upkeep` (backed by the same
      tuner) answered with a real figure. That sentence blamed a tuner that was
      not silent at all.
    - tuner-backed and the tuner is UNAVAILABLE: the tuner's own cause is the
      real one and is passed through as before.
    - not tuner-backed at all: the profile's own reason, as before.
    """
    profile = get_profile(context_game(context))
    if capability in profile.tuner_backed:
        tuner = context.tuner
        if tuner.available:
            live_q = _live_question_for(capability)
            detail = (f"{profile.display_name} writes no log for this; a live reading "
                      f"covers it instead -- ask `{live_q.id}`." if live_q is not None else
                      f"{profile.display_name} writes no log for this, and no catalog "
                      "question reads it live either.")
            return Resolution(absence=Absence(question_id, Unanswerable.NOT_LOGGED, detail))
        return Resolution(absence=Absence(
            question_id, Unanswerable.TUNER_ABSENT,
            tuner.reason or "the tuner has not been read this poll",
            cause=None if tuner.unavailable is None else tuner.unavailable.value))
    return Resolution(absence=Absence(
        question_id, Unanswerable.NOT_LOGGED,
        profile.reason(capability) or f"{profile.display_name} does not record this"))


def context_game(context: DecisionContext) -> str:
    """The game id this context was built for. `DecisionContext` does not carry it
    directly; the catalog it loaded does, and every game has its own."""
    return context.catalog.game


def _turn(context: DecisionContext, params: dict[str, str]) -> Resolution:
    return Resolution(facts=(evidence.analysis_turn_fact(context.ledger, context.state),))


def _yields(context: DecisionContext, params: dict[str, str]) -> Resolution:
    facts = tuple(f for f in (evidence.yield_fact(context.ledger, context.state,
                                                  context.state.HUMAN, stat)
                              for stat in evidence.YIELD_STATS) if f is not None)
    if not facts:
        return Resolution(absence=Absence("empire.yields", Unanswerable.NOT_LOGGED,
                                          "Player_Stats.csv has no row for you this turn"))
    return Resolution(facts=facts)


def _comparison(context: DecisionContext, params: dict[str, str]) -> Resolution:
    fact = evidence.yield_comparison_fact(context.ledger, context.state, params["stat"])
    if fact is None:
        return Resolution(absence=Absence("empire.comparison", Unanswerable.NOT_LOGGED,
                                          f"no rival row to compare {params['stat']} against"))
    return Resolution(facts=(fact,) + context.ledger.resolve(fact.contributing))


def _net_gold(context: DecisionContext, params: dict[str, str]) -> Resolution:
    fact = evidence.net_gold_fact(context.ledger, context.state)
    if fact is None:
        return _not_logged(context, "empire.net_gold", Capability.MAINTENANCE)
    return Resolution(facts=(fact,) + context.ledger.resolve(fact.contributing))


def _happiness(context: DecisionContext, params: dict[str, str]) -> Resolution:
    fact = evidence.happiness_fact(context.ledger, context.state)
    if fact is None:
        return _not_logged(context, "empire.happiness", Capability.HAPPINESS)
    return Resolution(facts=(fact,))


def _queues(context: DecisionContext, params: dict[str, str]) -> Resolution:
    facts = evidence.queue_facts(context.ledger, context.state)
    if not facts:
        return Resolution(absence=Absence("settlements.queues", Unanswerable.NOT_LOGGED,
                                          "no settlement of yours has a logged build queue"))
    return Resolution(facts=facts)


def _coverage(context: DecisionContext, params: dict[str, str]) -> Resolution:
    fact = evidence.settlement_coverage_fact(context.ledger, context.state)
    return Resolution(facts=(fact,) + context.ledger.resolve(fact.contributing))


def _rival_yields(context: DecisionContext, params: dict[str, str]) -> Resolution:
    facts = []
    for rival in context.state.rivals():
        for stat in evidence.YIELD_STATS:
            f = evidence.yield_fact(context.ledger, context.state, rival.id, stat)
            if f is not None:
                facts.append(f)
    if not facts:
        return Resolution(absence=Absence("rivals.yields", Unanswerable.NOT_LOGGED,
                                          "no rival has a stats row this turn"))
    return Resolution(facts=tuple(facts))


def _defense(context: DecisionContext, params: dict[str, str]) -> Resolution:
    facts = context.defense_facts or evidence.defense_facts(context.ledger, context.state)
    oracle = tuple(f for f in facts if f.provenance is Provenance.ORACLE)
    if not oracle:
        # The log was read and records nothing aimed at this player -- the ordinary case
        # on most turns, and an ANSWER. Returning an empty resolution here made `fallback`
        # reach CANNOT instead: "the advisor cannot see that", about a log it had just
        # read and understood.
        return Resolution(absence=Absence(
            "defense.objectives", Unanswerable.ANSWERED_EMPTY,
            "the AI's own logs record no attack objective against your tiles this turn"))
    return Resolution(facts=oracle)


def _brief(context: DecisionContext, params: dict[str, str]) -> Resolution:
    from civ_advisor.decisions import decide_all
    ids: list[str] = []
    for card in decide_all(context):
        ids.extend(card.evidence_ids)
        for candidate in card.candidates:
            ids.extend(candidate.evidence_ids)
    unique = tuple(dict.fromkeys(ids))
    if not unique:
        return Resolution(absence=Absence("decisions.brief", Unanswerable.NOT_LOGGED,
                                          "the brief holds no decision this turn"))
    return Resolution(facts=context.ledger.resolve(unique))


def _reports(context: DecisionContext, params: dict[str, str]) -> Resolution:
    facts = tuple(r.fact() for r in context.player.reports)
    if not facts:
        # Nothing to report is not an inability to see: the advisor holds the player's
        # reports itself and knows there are none.
        return Resolution(absence=Absence(
            "player.reports", Unanswerable.ANSWERED_EMPTY,
            "you have reported nothing to the advisor this sitting"))
    return Resolution(facts=facts)


# ---- live tuner resolvers (Task 7) -----------------------------------------------------

def _tuner_silence(question_id: str, context: DecisionContext,
                   query_id: str) -> Resolution | None:
    """The absence for a live question when the tuner said NOTHING about this figure --
    or None when it answered, and the caller must look at what it answered.

    Three situations that must never share a sentence, and only the first two are in
    here because only the first two are failures:

    - the tuner was never read: its own blanket `reason` and `unavailable` cause.
    - the tuner was read and THIS figure failed: `absence(query_id)`, the provider's own
      reason for this query, which can differ from every other query's in the same poll.
    - the tuner was read, answered, and simply has no row for the subject asked about.
      That is NOT handled here: it is not a failure, `None` is returned, and the caller
      declares it as `ANSWERED_EMPTY` naming the subject and the reading's turn. The old
      code funnelled it into `detail or "the tuner supplied no reading for this"` -- a
      working tuner reported as silent, for any city the logs know and the reply did not.
    """
    tuner = context.tuner
    if not tuner.available:
        return Resolution(absence=Absence(
            question_id, Unanswerable.TUNER_ABSENT,
            tuner.reason or "the tuner has not been read this poll",
            cause=None if tuner.unavailable is None else tuner.unavailable.value))
    why = tuner.absence(query_id)
    if why:
        return Resolution(absence=Absence(question_id, Unanswerable.TUNER_ABSENT, why))
    if tuner.reading_for(query_id) is None:
        # Either nothing asked the tuner for this figure this poll, or it was asked and
        # no reading came back to date the answer. Which of the two is not established
        # from the snapshot, so neither is asserted -- what is true of both is said.
        return Resolution(absence=Absence(
            question_id, Unanswerable.TUNER_ABSENT,
            "nothing dates this figure to a turn of the running game this poll, so no "
            "live reading can be quoted for it"))
    return None


def _read_at(context: DecisionContext, query_id: str) -> str:
    """The turn a query's own reply was stamped with, for the sentence that says the
    tuner answered. Never another query's: one reading per query, by design."""
    reading = context.tuner.reading_for(query_id)
    return "an unstamped turn" if reading is None else f"turn {reading.turn}"


def _amenities(context: DecisionContext, params: dict[str, str]) -> Resolution:
    silent = _tuner_silence("settlement.amenities", context, "amenities")
    if silent is not None:
        return silent
    tuner = context.tuner
    row = next((a for a in tuner.amenities if a.city == params["city"]), None)
    if row is None:
        return Resolution(absence=Absence(
            "settlement.amenities", Unanswerable.ANSWERED_EMPTY,
            f"the tuner answered the amenities query at {_read_at(context, 'amenities')} "
            f"and its reply names no settlement called {params['city']}"))
    return Resolution(facts=(evidence.amenities_fact(
        context.ledger, tuner.reading_for("amenities"), row),))


def _upkeep(context: DecisionContext, params: dict[str, str]) -> Resolution:
    silent = _tuner_silence("empire.upkeep", context, "maintenance")
    if silent is not None:
        return silent
    tuner = context.tuner
    if tuner.maintenance is None:
        return Resolution(absence=Absence(
            "empire.upkeep", Unanswerable.ANSWERED_EMPTY,
            f"the tuner answered the maintenance query at "
            f"{_read_at(context, 'maintenance')} and its reply carried no maintenance "
            "figure"))
    return Resolution(facts=(evidence.tuner_net_gold_fact(
        context.ledger, tuner.reading_for("maintenance"), tuner.maintenance),))


def _live_options(context: DecisionContext, params: dict[str, str]) -> Resolution:
    silent = _tuner_silence("settlement.build_options", context, "build_options")
    if silent is not None:
        return silent
    tuner = context.tuner
    reading = tuner.reading_for("build_options")
    so = next((s for s in tuner.build_options if s.city == params["city"]), None)
    if so is None:
        return Resolution(absence=Absence(
            "settlement.build_options", Unanswerable.ANSWERED_EMPTY,
            f"the tuner answered the build options query at "
            f"{_read_at(context, 'build_options')} and its reply names no settlement "
            f"called {params['city']}"))
    if not so.options:
        # An empty option list is what the GAME said, not something the advisor failed
        # to see: the settlement can build nothing right now. Saying "cannot see that"
        # here would hide a real answer behind a false one.
        return Resolution(absence=Absence(
            "settlement.build_options", Unanswerable.ANSWERED_EMPTY,
            f"the tuner answered at {_read_at(context, 'build_options')} and says "
            f"{params['city']} can build nothing right now"))
    return Resolution(facts=tuple(
        evidence.build_option_fact(context.ledger, reading, so.city, o) for o in so.options))


# ---- ruleset-backed resolvers (Task 6) ------------------------------------------------

def _ruleset(question_id: str, lookup: str, param: str, *, id_prefix: str) -> Resolver:
    def resolve(context: DecisionContext, params: dict[str, str]) -> Resolution:
        provider = context.ruleset
        if not provider.available:
            return Resolution(absence=Absence(
                question_id, Unanswerable.RULESET_UNAVAILABLE,
                provider.reason or "no installed ruleset is readable"))
        facts = getattr(provider, lookup)(params[param])
        if facts is None:
            # `None` alone does not establish that the row is missing: the reader
            # returns it for a reshaped table too, where the query never ran. Ask the
            # file which of the two happened rather than asserting the likelier story.
            complaint = provider.schema_complaint(lookup)
            if complaint:
                return Resolution(absence=Absence(
                    question_id, Unanswerable.RULESET_SCHEMA,
                    f"the installed ruleset {complaint}, so whether it holds a {lookup} "
                    f"row for {params[param]} could not be established; a mod or a patch "
                    "may have reshaped it"))
            return Resolution(absence=Absence(
                question_id, Unanswerable.NO_SUCH_ROW,
                f"the installed ruleset has no {lookup} row for {params[param]}"))
        figures = (facts,) if not hasattr(facts, "figures") else facts.figures
        notes = tuple(m.as_unknown() for m in getattr(facts, "mentions", ()))
        notes += tuple(c.describe() for c in getattr(facts, "counts", ()))
        return Resolution(facts=tuple(evidence.ruleset_fact(context.ledger, f) for f in figures),
                          notes=notes)
    return resolve


CATALOG: dict[str, Question] = {
    q.id: q for q in (
        Question("turn.analysis", "The turn the logs are complete through.", _turn,
                 verified_on="2026-09-13"),
        Question("empire.yields", "Your culture, science, gold, production and food per turn.",
                 _yields, verified_on="2026-09-13"),
        Question("empire.comparison", "One of your yields against the rival median, with the "
                 "advisor's threshold.", _comparison,
                 params=(Param("stat", ParamKind.STAT, "which yield"),), verified_on="2026-09-13"),
        Question("empire.net_gold", "Gold per turn after upkeep, from the logs.", _net_gold,
                 verified_on="2026-09-13"),
        Question("empire.happiness", "Empire happiness against the celebration threshold.",
                 _happiness, verified_on="2026-09-13"),
        Question("settlements.queues", "What each of your settlements is building, from the log.",
                 _queues, verified_on="2026-09-13"),
        Question("settlements.coverage", "How many settlements the queue log covers.",
                 _coverage, verified_on="2026-09-13"),
        Question("rivals.yields", "Every rival's yields per turn.", _rival_yields,
                 verified_on="2026-09-13"),
        Question("defense.objectives", "Recorded AI attack objectives against your tiles "
                 "(Oracle).", _defense, verified_on="2026-09-13", oracle=True),
        Question("decisions.brief", "The evidence behind every decision in this turn's brief.",
                 _brief, verified_on="2026-09-13"),
        Question("player.reports", "Figures you have told the advisor this sitting.", _reports,
                 verified_on="2026-09-13"),
        Question("settlement.amenities", "One settlement's amenities and their sources, read "
                 "live from the game.", _amenities,
                 params=(Param("city", ParamKind.CITY, "the settlement"),), verified_on="2026-09-13",
                 live_answers=Capability.HAPPINESS),
        Question("empire.upkeep", "Net gold after upkeep, read live from the game.", _upkeep,
                 verified_on="2026-09-13", live_answers=Capability.MAINTENANCE),
        Question("settlement.build_options", "What one settlement may build right now and how "
                 "many turns each would take, read live.", _live_options,
                 params=(Param("city", ParamKind.CITY, "the settlement"),), verified_on="2026-09-13"),
        Question("ruleset.building", "A building's cost, upkeep, prerequisites, flat yields, "
                 "housing, entertainment and whether it needs a plot, from your installed ruleset.",
                 _ruleset("ruleset.building", "building", "item", id_prefix="ruleset"),
                 params=(Param("item", ParamKind.TYPE_KEY, "e.g. BUILDING_LIBRARY"),),
                 verified_on="2026-09-13"),
        Question("ruleset.district", "A district's cost, prerequisites, housing and upkeep.",
                 _ruleset("ruleset.district", "district", "item", id_prefix="ruleset"),
                 params=(Param("item", ParamKind.TYPE_KEY, "e.g. DISTRICT_CAMPUS"),),
                 verified_on="2026-09-13"),
        Question("ruleset.unit", "A unit's cost, upkeep, strength, moves, range and prerequisites.",
                 _ruleset("ruleset.unit", "unit", "item", id_prefix="ruleset"),
                 params=(Param("item", ParamKind.TYPE_KEY, "e.g. UNIT_ARCHER"),),
                 verified_on="2026-09-13"),
        Question("ruleset.technology", "A technology's cost, era, prerequisites and eurekas.",
                 _ruleset("ruleset.technology", "technology", "item", id_prefix="ruleset"),
                 params=(Param("item", ParamKind.TYPE_KEY, "e.g. TECH_WRITING"),),
                 verified_on="2026-09-13"),
        Question("ruleset.civic", "A civic's cost, era, prerequisites and inspirations.",
                 _ruleset("ruleset.civic", "civic", "item", id_prefix="ruleset"),
                 params=(Param("item", ParamKind.TYPE_KEY, "e.g. CIVIC_CODE_OF_LAWS"),),
                 verified_on="2026-09-13"),
        Question("ruleset.improvement", "A tile improvement's prerequisites, housing and yields.",
                 _ruleset("ruleset.improvement", "improvement", "item", id_prefix="ruleset"),
                 params=(Param("item", ParamKind.TYPE_KEY, "e.g. IMPROVEMENT_FARM"),),
                 verified_on="2026-09-13"),
        Question("ruleset.policy", "Which slot a policy card fills and what unlocks it. Its "
                 "effect is not quantified by the ruleset.",
                 _ruleset("ruleset.policy", "policy", "item", id_prefix="ruleset"),
                 params=(Param("item", ParamKind.TYPE_KEY, "e.g. POLICY_URBAN_PLANNING"),),
                 verified_on="2026-09-13"),
        Question("ruleset.government", "A government's slot counts, tier and unlocking civic.",
                 _ruleset("ruleset.government", "government", "item", id_prefix="ruleset"),
                 params=(Param("item", ParamKind.TYPE_KEY, "e.g. GOVERNMENT_CLASSICAL_REPUBLIC"),),
                 verified_on="2026-09-13"),
        Question("ruleset.resource", "A resource's class, amenities and prerequisites.",
                 _ruleset("ruleset.resource", "resource", "item", id_prefix="ruleset"),
                 params=(Param("item", ParamKind.TYPE_KEY, "e.g. RESOURCE_SILK"),),
                 verified_on="2026-09-13"),
        Question("ruleset.parameter", "One of the game's global rule constants, by name.",
                 _ruleset("ruleset.parameter", "parameter", "name", id_prefix="ruleset"),
                 params=(Param("name", ParamKind.PARAMETER_NAME, "one of the fixed names"),),
                 verified_on="2026-09-13"),
    )
}

__all__ = ["Absence", "CATALOG", "Param", "ParamKind", "Question", "Resolution", "TYPE_KEY",
           "Unanswerable", "ask", "choices", "context_game"]
