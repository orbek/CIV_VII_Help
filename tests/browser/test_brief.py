"""The Phase 4 exit checks, driven against a real page.

These assert what a player would see and do: what fits on screen, what a keyboard can
reach, whether a citation opens the right observation, and whether hidden data can come
back. Source-string assertions cannot establish any of that, which is why this suite
exists alongside the node-level tests of the same rules.
"""
from __future__ import annotations

import re

import pytest
from playwright.sync_api import expect

CULTURE = '.decision[data-decision*="culture"]'


def test_the_top_decision_and_its_controls_fit_without_scrolling(dashboard):
    """At 1200x842, with the page not scrolled."""
    assert dashboard.evaluate("window.scrollY") == 0
    first = dashboard.locator("#brief-critical .decision").first
    expect(first).to_be_visible()
    box = first.locator(".decision-controls").bounding_box()
    assert box["y"] + box["height"] <= 842, "the first decision's controls are below the fold"
    expect(first.locator('[data-focus-key^="detail"]')).to_be_visible()
    # ... and the header still says how trustworthy the numbers are.
    expect(dashboard.locator("#connection")).to_have_text("connected")
    expect(dashboard.locator("#updated")).to_contain_text("analysed through turn 81")


def test_the_decision_and_its_how_to_work_with_no_local_model(dashboard):
    """The server runs with no commentary worker. The brief must be complete anyway."""
    expect(dashboard.locator("#commentary-status")).to_contain_text("Local commentary is off")
    card = dashboard.locator(CULTURE)
    expect(card).to_be_visible()
    card.locator('[data-focus-key^="detail"]').click()
    detail = card.locator(".decision-detail")
    expect(detail).to_contain_text("How to do it")
    expect(detail.locator(".decision-steps li").first).to_contain_text("production list")
    expect(detail.locator(".guide-links a").first).to_have_attribute(
        "href", re.compile(r"^https://"))
    # No generated interpretation is shown, because there is none.
    expect(card.locator(".generated")).to_have_count(0)


def test_every_citation_opens_its_own_observation(dashboard):
    card = dashboard.locator(CULTURE)
    button = card.locator('[data-focus-key^="evidence"]')
    count = int(re.search(r"\((\d+)\)", button.inner_text()).group(1))
    button.click()
    drawer = dashboard.locator("#evidence-drawer")
    expect(drawer).to_be_visible()
    facts = drawer.locator(".fact")
    expect(facts).to_have_count(count)
    # Each one is labelled in words, dated, and sourced — not shown as an internal id.
    for index in range(count):
        fact = facts.nth(index)
        expect(fact.locator(".fact-label")).not_to_have_text(re.compile(r"^[a-z.]+\.\d+$"))
        expect(fact.locator(".fact-meta").first).to_contain_text("turn")
    expect(drawer).to_contain_text("Why this one is first")
    expect(drawer).to_contain_text("Source coverage")


def test_closing_the_drawer_returns_focus_to_the_control_that_opened_it(dashboard):
    card = dashboard.locator(CULTURE)
    card.locator('[data-focus-key^="evidence"]').click()
    dashboard.locator("#drawer-close").click()
    expect(dashboard.locator("#evidence-drawer")).not_to_be_visible()
    focused = dashboard.evaluate("document.activeElement.dataset.focusKey")
    assert focused.startswith("evidence:")


def test_the_drawer_closes_on_escape_and_still_returns_focus(dashboard):
    card = dashboard.locator(CULTURE)
    card.locator('[data-focus-key^="evidence"]').click()
    dashboard.keyboard.press("Escape")
    expect(dashboard.locator("#evidence-drawer")).not_to_be_visible()
    assert dashboard.evaluate("document.activeElement.dataset.focusKey").startswith("evidence:")


def test_every_decision_control_is_reachable_and_operable_by_keyboard(dashboard):
    card = dashboard.locator(CULTURE)
    card.locator('[data-focus-key^="detail"]').focus()
    dashboard.keyboard.press("Enter")
    expect(card.locator(".decision-detail")).to_be_visible()
    # Tab from the detail toggle reaches the evidence control, and Enter opens it.
    card.locator('[data-focus-key^="detail"]').focus()
    dashboard.keyboard.press("Tab")
    assert dashboard.evaluate("document.activeElement.dataset.focusKey").startswith("evidence:")
    dashboard.keyboard.press("Enter")
    expect(dashboard.locator("#evidence-drawer")).to_be_visible()


def test_keyboard_focus_survives_a_repaint(dashboard):
    """A rebuild repaints the brief. It must not dump the reader back to the top.

    Driven through the real code path: toggling Oracle off and back on forces two full
    fetch-and-repaint cycles, which is what a turn update does.
    """
    card = dashboard.locator(CULTURE)
    card.locator('[data-focus-key^="detail"]').focus()
    focused = dashboard.evaluate("document.activeElement.dataset.focusKey")
    assert focused.startswith("detail:")
    # Fire the toggle's own change handler without clicking it — clicking would move
    # focus to the checkbox, which is the player choosing to go there, not a repaint
    # stealing focus from them.
    for checked in (False, True):
        dashboard.evaluate(f"""
          const box = document.querySelector('#oracle');
          box.checked = {str(checked).lower()};
          box.dispatchEvent(new Event('change'));
        """)
        dashboard.wait_for_timeout(400)
    dashboard.wait_for_selector("#brief-critical .decision")
    assert dashboard.evaluate("document.activeElement.dataset.focusKey") == focused


def test_acknowledging_a_decision_removes_it_and_leaves_a_count(dashboard):
    card = dashboard.locator(CULTURE)
    subject = card.locator(".decision-subject").inner_text()
    card.locator('[data-focus-key^="ack"]').click()
    expect(dashboard.locator(CULTURE)).to_have_count(0)
    expect(dashboard.locator("#brief-count")).to_contain_text("1 acknowledged")
    # It is recorded intent, not a game action, and the observation is still on its tab.
    dashboard.locator('[data-tab="economy"]').click()
    expect(dashboard.locator("#economy-cards")).to_contain_text("culture")
    assert subject


def test_pinning_keeps_an_acknowledged_decision_in_view(dashboard):
    card = dashboard.locator(CULTURE)
    card.locator('[data-focus-key^="pin"]').click()
    dashboard.locator(CULTURE).locator('[data-focus-key^="ack"]').click()
    expect(dashboard.locator(CULTURE)).to_have_count(1)
    expect(dashboard.locator(CULTURE)).to_have_class(re.compile("acknowledged"))


def test_switching_oracle_off_hides_intercepts_without_waiting_for_the_server(dashboard):
    """The Phase 1 reproduction, at the DOM. Block the network first, so the only thing
    that can hide the intercepted cards is the immediate repaint."""
    expect(dashboard.locator("#brief-critical .decision")).to_have_count(1)
    dashboard.route("**/api/briefing*", lambda route: None)      # never resolves
    dashboard.locator("#oracle").uncheck()
    expect(dashboard.locator("#brief-critical .decision")).to_have_count(0)
    expect(dashboard.locator("#tactical-map")).not_to_be_visible()  # on another tab, but empty
    dashboard.unroute("**/api/briefing*")


def test_a_delayed_oracle_on_reply_cannot_repaint_intercepts(dashboard, server):
    """Hold an Oracle-on reply, switch Oracle off, then release it."""
    expect(dashboard.locator("#brief-critical .decision")).to_have_count(1)
    dashboard.evaluate("""
      window.__held = [];
      const real = window.fetch;
      window.fetch = (url, opts) => {
        if (String(url).indexOf('/api/briefing') === 0 || String(url).indexOf('/api/briefing') > 0) {
          return new Promise((resolve) => { window.__held.push(() => resolve(real(url, opts))); });
        }
        return real(url, opts);
      };
    """)
    dashboard.locator("#oracle").uncheck()
    expect(dashboard.locator("#brief-critical .decision")).to_have_count(0)
    # Release every held request, oldest first: the stale Oracle-on one included.
    dashboard.evaluate("window.__held.forEach((release) => release())")
    dashboard.wait_for_timeout(700)
    expect(dashboard.locator("#brief-critical .decision")).to_have_count(0)
    assert dashboard.evaluate("document.querySelector('#oracle').checked") is False


def test_a_repaint_does_not_scroll_the_page(dashboard):
    dashboard.locator(CULTURE).locator('[data-focus-key^="detail"]').focus()
    dashboard.evaluate("window.scrollTo(0, 300)")
    before = dashboard.evaluate("window.scrollY")
    for checked in (False, True):
        dashboard.evaluate(f"""
          const box = document.querySelector('#oracle');
          box.checked = {str(checked).lower()};
          box.dispatchEvent(new Event('change'));
        """)
        dashboard.wait_for_timeout(400)
    dashboard.wait_for_selector("#brief-critical .decision")
    assert dashboard.evaluate("window.scrollY") == before


def test_only_meaningful_changes_are_announced(dashboard):
    """The freshness counter repaints every five seconds. It must not be announced."""
    live = dashboard.locator("#announce")
    expect(dashboard.locator(".status-line")).not_to_have_attribute("aria-live", "polite")
    assert live.get_attribute("role") == "status"
    assert live.inner_text() == ""              # the first paint is not news


@pytest.mark.parametrize("width", [390, 1200])
def test_controls_stay_usable_and_nothing_scrolls_sideways(dashboard, width):
    dashboard.set_viewport_size({"width": width, "height": 844})
    dashboard.wait_for_timeout(200)
    assert dashboard.evaluate("document.documentElement.scrollWidth") <= width
    for control in dashboard.locator("#brief-critical .decision-controls button").all():
        box = control.bounding_box()
        assert box["x"] >= 0 and box["x"] + box["width"] <= width
        assert box["height"] >= 24, "the control is too small to hit"


def test_five_critical_decisions_all_render_without_an_overflow_click(page, crowded_server):
    """Four is the plan's threshold; this session produces five, from real log rows.

    An overflow count is a reasonable way to defer an advisory. It is never a reasonable
    way to hide an emergency, so every one of them must be on screen with no interaction.
    """
    page.set_viewport_size({"width": 1200, "height": 842})
    page.goto(crowded_server)
    page.wait_for_selector("#brief-critical .decision")
    criticals = page.locator("#brief-critical .decision")
    expect(criticals).to_have_count(5)
    subjects = {criticals.nth(i).locator(".decision-subject").inner_text() for i in range(5)}
    assert len(subjects) == 5, "each critical alert is a distinct subject"
    expect(page.locator("#brief-count")).to_contain_text("5 critical")
    # Nothing critical was pushed into the collapsed overflow.
    expect(page.locator("#brief-rest .sev-critical")).to_have_count(0)
    # Scrolling to reach the fifth is acceptable; needing a click is not.
    assert page.locator("#brief-more").is_hidden() or \
        page.locator("#brief-more").get_attribute("aria-expanded") == "false"


def test_the_refinement_panel_changes_the_recommendation_and_can_be_cleared(dashboard):
    card = dashboard.locator(CULTURE)
    card.locator('[data-focus-key^="detail"]').click()
    panel = dashboard.locator(CULTURE).locator("details.refine")
    panel.locator("summary").click()
    panel.locator('[name="available_options"]').fill("BUILDING_MONUMENT, BUILDING_AMPHITHEATER")
    panel.locator('[name="objective"]').select_option("soonest_culture")
    for item, turns, delta in (("BUILDING_MONUMENT", "4", "3"), ("BUILDING_AMPHITHEATER", "6", "5")):
        panel.locator(f'[name="preview.{item}.completion_turns"]').fill(turns)
        panel.locator(f'[name="preview.{item}.culture_delta"]').fill(delta)
        panel.locator(f'[name="preview.{item}.gold_upkeep"]').fill("2")
    panel.locator('button[type="submit"]').click()

    updated = dashboard.locator(CULTURE)
    expect(updated.locator(".decision-action")).to_contain_text("Build Monument")
    expect(updated.locator(".applicability")).to_have_text("conditional")
    expect(updated.locator(".decision-reason")).to_contain_text("as soon as possible")
    # The detail panel is still open from before the submit; re-clicking would close it.
    detail = updated.locator(".decision-detail")
    expect(detail).to_contain_text("2 more culture per turn")
    expect(detail).to_contain_text("2 turns longer")
    expect(detail).to_contain_text("Unknown, so not assumed: Age and ruleset applicability")

    # The figures the player entered are cited as their own report, not as a log row.
    dashboard.locator(CULTURE).locator('[data-focus-key^="evidence"]').click()
    expect(dashboard.locator("#evidence-drawer")).to_contain_text("you told us")
    dashboard.locator("#drawer-close").click()

    # The panel stays open after a submit, and reports what it recorded.
    panel = dashboard.locator(CULTURE).locator("details.refine")
    expect(panel.locator(".refine-status")).to_contain_text("Recorded")
    panel.locator('[data-focus-key^="refine-clear"]').click()
    expect(dashboard.locator(CULTURE).locator(".decision-action")).to_contain_text("Inspect")
