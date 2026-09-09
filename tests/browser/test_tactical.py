"""The Phase 5 frontier exit checks, driven against a real page."""
from __future__ import annotations

import re

from playwright.sync_api import expect

VIEW = ".view-picker button"
ROWS = '#tactical-map tbody tr[role="button"]'


def view(page, label: str):
    return page.locator(VIEW).filter(has=page.locator(".view-label", has_text=label)).first


def test_two_distant_frontiers_are_individually_usable(frontier):
    """One fitted viewBox around both would be a picture of the sea between them."""
    labels = [v.inner_text().split("\n")[0] for v in frontier.locator(VIEW).all()]
    assert "Area around 11:10" in labels and "Area around 70:40" in labels

    view(frontier, "Area around 11:10").click()
    frontier.wait_for_timeout(150)
    first = [r.inner_text() for r in frontier.locator(ROWS).all()]
    assert [row for row in first if "12:12" in row], first
    assert not [row for row in first if "72:41" in row]

    view(frontier, "Area around 70:40").click()
    frontier.wait_for_timeout(150)
    second = [r.inner_text() for r in frontier.locator(ROWS).all()]
    assert [row for row in second if "72:41" in row], second
    assert not [row for row in second if "12:12" in row]

    # Each says how many recorded positions it leaves out, rather than dropping them.
    expect(frontier.locator(".map-coverage-note").first).to_contain_text(
        re.compile(r"recorded positions? (is|are) outside this view"))


def test_every_contact_stays_reachable(frontier):
    view(frontier, "All contacts").click()
    frontier.wait_for_timeout(150)
    expect(frontier.locator(".contact-count")).to_contain_text("7 contacts")
    assert frontier.locator(ROWS).count() == 7
    tiles = {r.inner_text().split("\t")[4] for r in frontier.locator(ROWS).all()}
    assert {"12:12", "72:41", "41:26"} <= tiles


def test_overlapping_markers_are_selectable_by_keyboard_through_the_table(frontier):
    """Two units on one hex share a marker, which cannot be clicked apart or focused."""
    view(frontier, "Area around 11:10").click()
    frontier.wait_for_timeout(150)
    expect(frontier.locator(".map-coverage-note").last).to_contain_text("Sharing a tile")

    shared = [r for r in frontier.locator(ROWS).all() if "13:12" in r.inner_text()]
    assert len(shared) == 2, "both contacts on the shared tile are listed separately"
    shared[0].focus()
    frontier.keyboard.press("Enter")
    frontier.wait_for_timeout(200)
    assert frontier.locator("#tactical-map tbody tr.selected").count() == 1
    expect(frontier.locator(".contact-detail")).to_contain_text("13:12")
    assert frontier.evaluate("document.activeElement.dataset.focusKey").startswith("contact:")
    first_key = frontier.evaluate("document.activeElement.dataset.focusKey")

    # The other one on the same tile is separately selectable.
    shared = [r for r in frontier.locator(ROWS).all() if "13:12" in r.inner_text()]
    shared[1].focus()
    frontier.keyboard.press("Enter")
    frontier.wait_for_timeout(200)
    assert frontier.evaluate("document.activeElement.dataset.focusKey") != first_key
    assert frontier.locator("#tactical-map .map-selected").count() == 1


def test_a_distant_exposed_unit_has_its_own_view(frontier):
    view(frontier, "Your exposed units").click()
    frontier.wait_for_timeout(150)
    rows = [r.inner_text() for r in frontier.locator(ROWS).all()]
    assert [row for row in rows if "41:26" in row], rows
    # The frontier views are unaffected by it.
    view(frontier, "Area around 11:10").click()
    frontier.wait_for_timeout(150)
    assert not [r for r in frontier.locator(ROWS).all() if "41:26" in r.inner_text()]


def test_the_selected_view_and_contact_survive_a_repaint(frontier):
    view(frontier, "Area around 70:40").click()
    frontier.wait_for_timeout(150)
    frontier.locator(ROWS).first.focus()
    frontier.keyboard.press("Enter")
    frontier.wait_for_timeout(200)
    selected = frontier.evaluate(
        "document.querySelector('#tactical-map tbody tr.selected').dataset.focusKey")
    for checked in ("false", "true"):
        frontier.evaluate(f"""
          const box = document.querySelector('#oracle');
          box.checked = {checked};
          box.dispatchEvent(new Event('change'));
        """)
        frontier.wait_for_timeout(400)
    frontier.wait_for_selector(VIEW)
    assert view(frontier, "Area around 70:40").get_attribute("aria-selected") == "true"
    assert frontier.evaluate(
        "document.querySelector('#tactical-map tbody tr.selected').dataset.focusKey"
    ) == selected


def test_the_map_is_withheld_entirely_with_oracle_off(frontier):
    frontier.locator("#oracle").uncheck()
    frontier.wait_for_timeout(300)
    expect(frontier.locator("#tactical-map")).to_contain_text("Oracle off")
    assert frontier.locator(VIEW).count() == 0
