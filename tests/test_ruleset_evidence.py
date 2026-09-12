from pathlib import Path

import pytest

from civ_advisor.advisors.base import Provenance
from civ_advisor.decisions.evidence import EvidenceLedger, ruleset_fact
from civ_advisor.decisions.models import EvidenceFact, SourceKind
from civ_advisor.ruleset.base import RulesetFigure, RulesetIdentity

IDENTITY = RulesetIdentity(path=Path("/games/DebugGameplay.sqlite"), size=18_051_072,
                           mtime_ns=1_757_667_420_000_000_000, digest="ab" * 32)
LIBRARY_COST = RulesetFigure(subject="BUILDING_LIBRARY", label="Library production cost",
                             value=90, unit="production", table="Buildings", column="Cost",
                             row_key=("BUILDING_LIBRARY",), identity=IDENTITY)


def test_a_ruleset_figure_becomes_its_own_source_kind():
    """Not an advisor rule and not the player's report: a third thing, which a reader
    must be able to tell apart from both."""
    fact = ruleset_fact(EvidenceLedger(), LIBRARY_COST)

    assert fact.source_kind is SourceKind.INSTALLED_RULESET
    assert fact.provenance is Provenance.FAIR
    assert fact.value == 90 and fact.unit == "production"


def test_a_ruleset_fact_cites_the_row_and_carries_no_turn():
    """It is what the installed files say, not an observation of this game at this turn.
    The citation must lead back to the exact row."""
    fact = ruleset_fact(EvidenceLedger(), LIBRARY_COST)

    assert fact.id == "ruleset.Buildings.BUILDING_LIBRARY.Cost"
    assert fact.source_file == "DebugGameplay.sqlite"
    assert fact.record_key == ("Buildings", "Cost", "BUILDING_LIBRARY")
    assert fact.observed_turn is None


def test_a_ruleset_fact_never_claims_a_version():
    fact = ruleset_fact(EvidenceLedger(), LIBRARY_COST)

    assert fact.note is not None
    assert "version" not in fact.note.lower()
    assert IDENTITY.short_digest in fact.note


def test_adding_the_same_figure_twice_is_not_a_conflict():
    """The context pre-populates the ledger and a candidate cites the same figure again.
    Identical facts must coexist, or citing one would be a race with building it."""
    ledger = EvidenceLedger()

    first, second = ruleset_fact(ledger, LIBRARY_COST), ruleset_fact(ledger, LIBRARY_COST)

    assert first == second and len(ledger.facts) == 1


def test_a_ruleset_fact_must_name_its_source_file():
    with pytest.raises(ValueError, match="must name its source file"):
        EvidenceFact(id="r", label="l", source_kind=SourceKind.INSTALLED_RULESET,
                     provenance=Provenance.FAIR, observed_turn=None, value=1,
                     record_key=("Buildings", "Cost", "BUILDING_LIBRARY"))


def test_the_browser_renders_the_new_kind():
    """A fact whose kind the UI does not know falls through to the word "log", which
    would present the ruleset as something the game wrote this turn."""
    app_js = Path("civ_advisor/web/app.js").read_text(encoding="utf-8")

    assert "installed_ruleset" in app_js
