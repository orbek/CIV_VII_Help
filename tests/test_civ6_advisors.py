from civ_advisor.advisors import run_all
from civ_advisor.games.civ6 import CIV6
from civ_advisor.ingest.load import load_logs
from civ_advisor.state.build import build_state


def test_every_advisor_runs_against_a_civ6_state_without_raising(civ6_dir):
    """The point of the canonical state: advisors are game-agnostic."""
    state = build_state(load_logs(civ6_dir, profile=CIV6))
    insights = run_all(state)
    assert isinstance(insights, list)


def test_no_insight_asserts_a_signal_civ6_cannot_supply(civ6_dir):
    """An advisor that reads happiness or maintenance from a Civ VI state
    would be reporting a number the game never logged."""
    state = build_state(load_logs(civ6_dir, profile=CIV6))
    text = " ".join(
        f"{getattr(i, 'title', '')} {getattr(i, 'detail', '')}" for i in run_all(state)
    ).lower()
    for banned in ("happiness", "amenit", "maintenance", "celebration"):
        assert banned not in text, f"a Civ VI insight mentions {banned!r}"


def test_the_api_reports_which_capabilities_are_unavailable(civ6_dir):
    from civ_advisor.api.serialize import capability_report

    report = capability_report(CIV6)
    assert report["victory_paths"]["supported"] is False
    assert "victory" in report["victory_paths"]["reason"].lower()
    assert report["happiness"]["supported"] is False and report["happiness"]["reason"]
    assert report["faith"] == {"supported": True, "reason": None}


def test_civ6_production_advice_uses_civ6_s_own_empty_catalog(civ6_dir):
    """Civ VI's catalog is deliberately empty -- no guide has been reviewed against it
    yet. `run_all(state, CIV6)` must not fall back to Civ VII's reviewed guidance for a
    Civ VI item just because both games happen to name similar buildings; the correct
    outcome is no reviewed association at all, not Civ VII's."""
    from civ_advisor.advisors import production

    state = build_state(load_logs(civ6_dir, profile=CIV6))
    package = CIV6.knowledge_package
    for row in state.build_queues:
        if row.item:
            assert production.reviewed_yield(row.item, package) is False

    # Confirms the threading actually reaches run_all (not just production called
    # directly): passing the profile through must not raise, and production's own
    # insight still comes out the other end.
    insights = run_all(state, CIV6)
    assert any(i.id == "production.own_queue" for i in insights)
