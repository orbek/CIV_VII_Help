"""Change detection, and the four ways it refuses to claim a trend."""
from __future__ import annotations

from dataclasses import replace

from civ_advisor.advisors.base import Provenance, Severity, visible
from civ_advisor.decisions import changes as tracking
from civ_advisor.decisions.models import DecisionCard
from civ_advisor.store import SCHEMA_VERSION, DomainCoverage, Snapshot
from tests.factories import game_state, insight


def coverage(**statuses: str) -> tuple[DomainCoverage, ...]:
    base = {"empire": "ok", "treasury": "ok", "happiness": "ok", "production": "ok",
            "tactical": "ok", "targets": "ok", "diplomacy": "ok", "combat": "ok",
            "strategy": "ok"}
    base.update(statuses)
    return tuple(
        DomainCoverage(name=name, label=name, required=name == "empire", turn_scoped=True,
                       status=status, files=(f"{name}.csv",), missing=(), rows=1,
                       latest_turn=None, lag=None, errors=())
        for name, status in sorted(base.items())
    )


def snapshot(turn: int, insights: tuple, *, session: str = "s1", epoch: int = 1,
             revision: int = 1, **statuses: str) -> Snapshot:
    state = game_state(turn=turn)
    return Snapshot(
        schema_version=SCHEMA_VERSION, game_id="civ7", session=session, epoch=epoch,
        epoch_reason="first_load", game_key=None, revision=revision, captured_at=0.0,
        latest_turn=turn + 1, analysis_turn=turn, state=state, insights=insights,
        coverage=coverage(**statuses),
    )


def entry(turn: int, insights: tuple, *, catalog: str = "cat-1", cards: tuple = (),
          comparisons: dict | None = None, session: str = "s1", epoch: int = 1,
          revision: int = 1, **statuses: str) -> tracking.HistoryEntry:
    return tracking.entry_from(
        snapshot(turn, insights, session=session, epoch=epoch, revision=revision, **statuses),
        cards, catalog, comparisons)


def gap(stat: str, ratio: float, turn: int):
    """A yield comparison fact, as the ledger produces one."""
    from civ_advisor.decisions.models import EvidenceFact, SourceKind

    return EvidenceFact(id=f"comparison.{stat}.{turn}", label=stat,
                        source_kind=SourceKind.DERIVED, provenance=Provenance.FAIR,
                        observed_turn=turn, value=ratio, contributing=("x",))


def test_a_single_observation_is_not_a_trend():
    """The first turn of a session reports nothing rather than everything as new."""
    current = entry(10, (insight("economy.behind.culture", advisor="economy"),))
    assert tracking.compare(None, current) == ()


def test_a_signal_that_appears_is_new_and_one_that_worsens_says_so():
    before = entry(10, (insight("threat.at_war.1", advisor="threat",
                                severity=Severity.WARN),))
    after = entry(11, (insight("threat.at_war.1", advisor="threat",
                               severity=Severity.CRITICAL),
                       insight("economy.behind.food", advisor="economy",
                               severity=Severity.ADVISE)))
    by_id = {c.signal_id: c for c in tracking.compare(before, after)}
    assert by_id["threat.at_war.1"].state == tracking.WORSENING
    assert "WARN to CRITICAL" in by_id["threat.at_war.1"].detail
    assert by_id["economy.behind.food"].state == tracking.NEW
    assert by_id["economy.behind.food"].previous_turn == 10


def test_a_reload_is_not_the_previous_turn():
    """A different epoch is a different sitting, possibly a different save."""
    history = tracking.History()
    history.record(entry(10, (insight("a"),), epoch=1))
    later = entry(11, (insight("a"),), epoch=2)
    assert history.previous(later) is None
    assert tracking.compare(history.previous(later), later) == ()


def test_a_same_turn_rebuild_replaces_its_entry_rather_than_adding_history():
    """Five log writes inside one turn are not five turns."""
    history = tracking.History()
    for revision in (1, 2, 3):
        history.record(entry(10, (insight("a"),), revision=revision))
    assert history.turns("s1", 1) == (10,)
    assert len(history.entries) == 1 and history.entries[0].revision == 3
    history.record(entry(11, (insight("a"),), revision=4))
    assert history.turns("s1", 1) == (10, 11)


def test_the_series_keeps_observed_turn_numbers_including_the_gaps():
    """Renumbering would imply turns the advisor never saw."""
    history = tracking.History()
    for turn in (10, 11, 20):
        history.record(entry(turn, (insight("a"),)))
    assert history.turns("s1", 1) == (10, 11, 20)


def test_history_is_bounded():
    history = tracking.History(limit=3)
    for turn in range(1, 8):
        history.record(entry(turn, (insight("a"),)))
    assert history.turns("s1", 1) == (5, 6, 7)


def test_a_source_that_stopped_being_readable_is_not_an_improvement():
    """The check that matters most: a warning that vanished with its log has not resolved."""
    before = entry(10, (insight("tactical.enemy_units_near.1", advisor="tactical",
                                severity=Severity.WARN),))
    after = entry(11, (), tactical="unavailable")
    [change] = [c for c in tracking.compare(before, after)
                if c.signal_id == "tactical.enemy_units_near.1"]
    assert change.state == tracking.NO_LONGER_OBSERVED
    assert "coverage of tactical changed" in change.detail
    assert "lost source rather than an observed change" in change.detail
    assert change.state != tracking.RESOLVED


def test_a_signal_that_simply_stops_being_reported_is_not_resolved_either():
    before = entry(10, (insight("economy.behind.gold", advisor="economy"),))
    after = entry(11, ())
    [change] = [c for c in tracking.compare(before, after)
                if c.signal_id == "economy.behind.gold"]
    assert change.state == tracking.NO_LONGER_OBSERVED
    assert "Nothing observed says the situation resolved" in change.detail


def test_resolved_requires_a_present_observation_that_the_condition_lifted():
    before = entry(10, (insight("economy.behind.culture", advisor="economy"),),
                   comparisons={"culture": gap("culture", 0.44, 10)})
    after = entry(11, (), comparisons={"culture": gap("culture", 1.05, 11)})
    [change] = [c for c in tracking.compare(before, after)
                if c.signal_id == "economy.behind.culture"]
    assert change.state == tracking.RESOLVED
    assert "back at 105% of the field, from 44%" in change.detail
    assert "not an inference from the warning stopping" in change.detail


def test_a_domain_whose_coverage_moved_makes_its_signals_incomparable():
    before = entry(10, (insight("economy.behind.culture", advisor="economy"),))
    after = entry(11, (insight("economy.behind.culture", advisor="economy"),),
                  treasury="unavailable")
    [change] = [c for c in tracking.compare(before, after)
                if c.signal_id == "economy.behind.culture"]
    assert change.state == tracking.NOT_COMPARABLE
    assert "coverage of treasury changed" in change.detail


def test_a_signal_first_seen_while_coverage_changed_is_not_called_new():
    """It may have been there all along and simply unreadable."""
    before = entry(10, (), tactical="unavailable")
    after = entry(11, (insight("tactical.own_exposed", advisor="tactical"),))
    [change] = tracking.compare(before, after)
    assert change.state == tracking.NOT_COMPARABLE
    assert "may have been there and unreadable rather than new" in change.detail


def test_a_new_guide_catalog_makes_decision_cards_incomparable():
    card = DecisionCard(id="decision.culture.C", subject="Culture in C",
                        severity=Severity.ADVISE, priority_reason="x", family="culture",
                        observed_turns=(10,))
    before = entry(10, (), cards=(card,), catalog="cat-1")
    after = entry(11, (), cards=(replace(card, observed_turns=(11,)),), catalog="cat-2")
    [change] = [c for c in tracking.compare(before, after)
                if c.signal_id == "decision.culture.C"]
    assert change.state == tracking.NOT_COMPARABLE
    assert "reviewed guide catalog changed" in change.detail


def test_a_ratio_moving_without_a_severity_change_still_reports_a_direction():
    before = entry(10, (insight("economy.behind.culture", advisor="economy"),),
                   comparisons={"culture": gap("culture", 0.44, 10)})
    after = entry(11, (insight("economy.behind.culture", advisor="economy"),),
                  comparisons={"culture": gap("culture", 0.61, 11)})
    [change] = [c for c in tracking.compare(before, after)
                if c.signal_id == "economy.behind.culture"]
    assert change.state == tracking.IMPROVING
    assert "44% to 61% of the field" in change.detail


def test_an_unchanged_signal_says_only_that():
    before = entry(10, (insight("economy.behind.culture", advisor="economy"),))
    after = entry(11, (insight("economy.behind.culture", advisor="economy"),))
    [change] = tracking.compare(before, after)
    assert change.state == tracking.UNCHANGED and change.detail == "No change observed."


def test_the_retrospective_puts_two_records_side_by_side_and_claims_nothing():
    before = entry(10, (insight("economy.behind.culture", advisor="economy"),),
                   comparisons={"culture": gap("culture", 0.44, 10)})
    after = entry(11, (), comparisons={"culture": gap("culture", 1.05, 11)})
    changes = tracking.compare(before, after)
    retro = tracking.retrospective(changes, ("decision.culture.C",))
    assert retro["states"][tracking.RESOLVED] == ["economy.behind.culture"]
    assert retro["acknowledged"] == ["decision.culture.C"]
    assert "Nothing here shows that acknowledging a decision caused" in retro["caveat"]
    assert "no success is being scored" in retro["caveat"]
    # No score, no rate, no causal field of any kind.
    assert set(retro) == {"states", "acknowledged", "caveat"}


def _serve(previous, current, *, oracle: bool):
    """Mirrors `api/app.py`'s `_changes`: the recorded history is always complete,
    and only the served rows are filtered by mode, at this single point."""
    return visible(tracking.compare(previous, current), oracle)


def test_fair_mode_changes_never_carries_an_oracle_insights_id_or_title():
    """The whole-phase review's Critical: `signals_from` iterated every insight with
    no oracle filter, so an Oracle-only insight's id and title reached the fair-mode
    "since last turn" payload even though cards and intel correctly hid it.

    Proved against a payload that actually HAS rows -- two recorded turns with a
    fair-visible signal changing between them -- so this cannot pass vacuously the
    way the guard it replaces did against an empty, single-turn fixture."""
    oracle_insight = insight("threat.combat_desire.7", advisor="threat",
                              provenance=Provenance.ORACLE,
                              title="Cyrus's appetite for a fight is rising")
    fair_insight_before = insight("threat.at_war.7", advisor="threat",
                                  severity=Severity.WARN)
    fair_insight_after = insight("threat.at_war.7", advisor="threat",
                                 severity=Severity.CRITICAL)

    before = entry(10, (fair_insight_before, oracle_insight))
    after = entry(11, (fair_insight_after, oracle_insight))
    # Recorded complete regardless of mode: both turns' history has the Oracle signal.
    assert "threat.combat_desire.7" in before.signals
    assert "threat.combat_desire.7" in after.signals

    served = _serve(before, after, oracle=False)
    assert served, "the payload under test must have rows, or this proves nothing"

    ids = {c.signal_id for c in served}
    assert "threat.at_war.7" in ids
    assert "threat.combat_desire.7" not in ids
    assert all("appetite for a fight" not in c.label for c in served)


def test_oracle_mode_changes_does_carry_the_oracle_signal():
    """The filter must be a filter, not a deletion: served with oracle=True the same
    Oracle-only insight shows up, proving the fair-mode test above exercises a real
    filter rather than an insight that never made it into a Signal at all."""
    oracle_insight = insight("threat.combat_desire.7", advisor="threat",
                              provenance=Provenance.ORACLE)
    before = entry(10, ())
    after = entry(11, (oracle_insight,))
    assert "threat.combat_desire.7" in after.signals
    ids = {c.signal_id for c in _serve(before, after, oracle=True)}
    assert "threat.combat_desire.7" in ids


def test_toggle_order_fair_then_oracle_does_not_manufacture_a_new_signal():
    """The instruction this fixes: filtering at record time made the recorded
    history depend on which mode happened to be active when a turn was captured. A
    signal present in the game data on turn 10 -- served fair -- must not be
    reported as "newly observed" on turn 11 just because turn 11 happens to be
    served with Oracle on."""
    desire_t10 = insight("threat.combat_desire.7", advisor="threat",
                         provenance=Provenance.ORACLE, turn=10)
    desire_t11 = insight("threat.combat_desire.7", advisor="threat",
                         provenance=Provenance.ORACLE, turn=11)

    history = tracking.History()
    e10 = entry(10, (desire_t10,))
    history.record(e10)
    served_t10 = _serve(history.previous(e10), e10, oracle=False)
    assert served_t10 == []   # first turn of the sitting: nothing to compare yet

    e11 = entry(11, (desire_t11,))
    previous = history.previous(e11)
    history.record(e11)
    served_t11 = _serve(previous, e11, oracle=True)

    by_id = {c.signal_id: c for c in served_t11}
    assert "threat.combat_desire.7" in by_id
    assert by_id["threat.combat_desire.7"].state != tracking.NEW


def test_toggle_order_oracle_then_fair_is_also_stable():
    """The reverse order: turn 10 served with Oracle on, turn 11 served fair. Fair
    mode must simply omit the Oracle row -- never report it as new -- and the
    recorded history itself must be identical either way."""
    desire_t10 = insight("threat.combat_desire.7", advisor="threat",
                         provenance=Provenance.ORACLE, turn=10)
    desire_t11 = insight("threat.combat_desire.7", advisor="threat",
                         provenance=Provenance.ORACLE, turn=11)

    history = tracking.History()
    e10 = entry(10, (desire_t10,))
    history.record(e10)
    _serve(history.previous(e10), e10, oracle=True)

    e11 = entry(11, (desire_t11,))
    previous = history.previous(e11)
    history.record(e11)
    served_t11 = _serve(previous, e11, oracle=False)

    assert all(c.signal_id != "threat.combat_desire.7" for c in served_t11)
    assert "threat.combat_desire.7" in e10.signals
    assert "threat.combat_desire.7" in e11.signals
