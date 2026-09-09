"""The Phase 6 panels, driven against a real page."""
from __future__ import annotations

from playwright.sync_api import expect

CULTURE = '.decision[data-decision*="culture"]'


def open_detail(page):
    page.locator(CULTURE).locator('[data-focus-key^="detail"]').click()
    page.wait_for_selector(f"{CULTURE} .questions")
    return page.locator(CULTURE)


def test_the_first_turn_says_there_is_nothing_to_compare(dashboard):
    """Not an empty change list, which would read as "nothing changed"."""
    expect(dashboard.locator("#changes-summary")).to_have_text(
        "Since last turn — nothing to compare yet")
    dashboard.locator("#changes-panel summary").click()
    expect(dashboard.locator("#changes-body")).to_contain_text(
        "A single observation is not a trend")


def test_each_question_is_answered_from_the_structured_data(dashboard):
    card = open_detail(dashboard)
    for kind, needle in (("why", "the next useful act is looking"),
                         ("inspect", "production list"),
                         ("what_changes", "turned out differently")):
        dashboard.locator(CULTURE).locator(f'[data-focus-key^="ask:{kind}"]').click()
        answer = dashboard.locator(f"{CULTURE} .answer")
        expect(answer).to_be_visible()
        expect(answer).to_contain_text(needle)
        # With no local model, the panel says the answer is not model-written.
        expect(answer).to_contain_text("Assembled from the structured decision data")
    assert card


def test_a_challenge_is_recorded_as_intent_and_not_as_an_observation(dashboard):
    open_detail(dashboard)
    form = dashboard.locator(f"{CULTURE} form.challenge")
    form.locator('[name="challenge"]').fill("I already built a Monument here, so this is done")
    form.locator('button[type="submit"]').click()
    answer = dashboard.locator(f"{CULTURE} .answer")
    expect(answer).to_contain_text("You said: I already built a Monument here")
    expect(answer).to_contain_text("your intention, not as something observed")
    # And it does not agree that the decision is settled.
    expect(answer).to_contain_text("does not settle these")


def test_acknowledging_writes_to_the_servers_own_record(dashboard, server):
    import json
    import urllib.request

    dashboard.locator(CULTURE).locator('[data-focus-key^="ack"]').click()
    expect(dashboard.locator(CULTURE)).to_have_count(0)
    expect(dashboard.locator("#brief-count")).to_contain_text("acknowledged")
    with urllib.request.urlopen(f"{server}/api/record") as response:
        record = json.load(response)
    kinds = [e["kind"] for e in record["entries"]]
    assert "acknowledged" in kinds
    # Recorded against a fingerprint, so it lapses when the evidence moves.
    assert all(e["fingerprint"] for e in record["entries"] if e["kind"] == "acknowledged")


def test_pinning_keeps_it_in_view_and_is_recorded_too(dashboard, server):
    import json
    import urllib.request

    dashboard.locator(CULTURE).locator('[data-focus-key^="pin"]').click()
    dashboard.wait_for_timeout(400)
    dashboard.locator(CULTURE).locator('[data-focus-key^="ack"]').click()
    dashboard.wait_for_timeout(400)
    expect(dashboard.locator(CULTURE)).to_have_count(1)
    with urllib.request.urlopen(f"{server}/api/record") as response:
        record = json.load(response)
    assert "watch" in [e["kind"] for e in record["entries"]]
