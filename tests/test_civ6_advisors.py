from civ_advisor.advisors import run_all
from civ_advisor.games.base import Capability
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
    assert report[Capability.VICTORY_PATHS.value] is False
    assert report[Capability.HAPPINESS.value] is False
    assert report[Capability.FAITH.value] is True
