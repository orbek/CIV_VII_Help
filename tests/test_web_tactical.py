"""Execute the tactical view's own rules under node.

These are the rules that replaced the old twelve-contact cap and single fitted viewBox:
which views exist, what is in each, how the table pages, which contacts share a tile, and
how marks are sized for the span being shown.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

TACTICAL_JS = Path(__file__).resolve().parents[1] / "civ_advisor" / "web" / "tactical.js"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


def run_js(body: str) -> object:
    script = (
        f"const T = require({str(TACTICAL_JS)!r});\n"
        f"const out = (() => {{ {body} }})();\n"
        "process.stdout.write(JSON.stringify(out === undefined ? null : out));\n"
    )
    done = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


DATA = """
  const contact = (key, x, y, cluster, distance, name, unit, turn) => ({
    key, x, y, cluster, distance_to_city: distance, near: cluster !== null,
    name, unit_type: unit, activity: "Attack Units", turn: turn === undefined ? 20 : turn,
    age: 20 - (turn === undefined ? 20 : turn),
  });
  const data = {
    clusters: [
      { id: "area-10-10", label: "Area around 10:10", turn: 20,
        tiles: [{ x: 10, y: 10, turn: 20, age: 0 }, { x: 11, y: 10, turn: 20, age: 0 }] },
      { id: "area-70-40", label: "Area around 70:40", turn: 18,
        tiles: [{ x: 70, y: 40, turn: 18, age: 2 }] },
    ],
    enemy_units: [
      contact("1:1", 12, 12, "area-10-10", 2, "Rival One", "UNIT_ARCHER"),
      contact("1:2", 13, 12, "area-10-10", 3, "Rival One", "UNIT_SPEARMAN"),
      contact("1:3", 13, 12, "area-10-10", 3, "Rival One", "UNIT_ARCHER"),
      contact("2:4", 71, 41, "area-70-40", 1, "Rival Two", "UNIT_IMMORTAL"),
      contact("1:9", 41, 26, null, 30, "Rival One", "UNIT_SCOUT", 18),
    ],
    human_units: [
      { key: "0:100", x: 10, y: 10, cluster: "area-10-10", exposed: false,
        unit_type: "UNIT_WARRIOR", activity: "Alert", turn: 20, age: 0 },
      { key: "0:900", x: 40, y: 25, cluster: null, exposed: true,
        unit_type: "UNIT_SCOUT", activity: "Alert", turn: 20, age: 0,
        distance_to_enemy: 1, distance_to_city: 30 },
    ],
    attack_goals: [{ x: 10, y: 10, name: "Rival One", turn: 20, fresh: true,
                     cluster: "area-10-10", kind: "Attack Enemy City" }],
    fresh_turns: 3,
    city_tile_turn: 20,
  };
"""


def test_every_frontier_gets_its_own_view_plus_a_way_to_see_everything():
    result = run_js(DATA + """
      return T.views(data).map((v) => ({ id: v.id, label: v.label, detail: v.detail,
                                         kind: v.kind, count: v.count }));
    """)
    ids = [v["id"] for v in result]
    assert ids == ["area-10-10", "area-70-40", "exposed", "all"]
    assert result[0]["detail"] == "2 known tiles · 3 contacts"
    assert result[1]["detail"] == "1 known tile · 1 contact"
    # A distant exposed unit of your own is its own focus, not folded into a frontier.
    assert result[2]["kind"] == "exposed" and result[2]["count"] == 1
    # And nothing is ever unreachable.
    assert result[3]["label"] == "All contacts" and result[3]["count"] == 5


def test_each_frontier_shows_only_its_own_and_says_what_it_leaves_out():
    result = run_js(DATA + """
      const first = T.contents(data, "area-10-10");
      const second = T.contents(data, "area-70-40");
      const all = T.contents(data, "all");
      const exposed = T.contents(data, "exposed");
      const keys = (c) => c.contacts.map((x) => x.key);
      return {
        first: keys(first), firstOff: first.offMap, firstTiles: first.tiles.length,
        firstGoals: first.goals.length, firstUnits: exposedKeys(first),
        second: keys(second), secondOff: second.offMap,
        all: keys(all), allOff: all.offMap,
        exposed: exposedKeys(exposed), exposedContacts: keys(exposed),
        exposedOff: exposed.offMap,
      };
      function exposedKeys(c) { return c.units.map((u) => u.key); }
    """)
    assert result["first"] == ["1:1", "1:2", "1:3"]
    assert result["firstOff"] == 2            # stated, not silently dropped
    assert result["firstTiles"] == 2 and result["firstGoals"] == 1
    assert result["firstUnits"] == ["0:100"]
    assert result["second"] == ["2:4"] and result["secondOff"] == 4
    # All contacts holds every one, nearest first.
    assert result["all"] == ["2:4", "1:1", "1:2", "1:3", "1:9"]
    assert result["allOff"] == 0
    # The exposed view carries the unit and only what is within reach of it.
    assert result["exposed"] == ["0:900"] and result["exposedContacts"] == ["1:9"]


def test_contact_thirteen_is_reachable_by_paging_rather_than_being_dropped():
    """The defect the plan names. Twenty contacts, twelve to a page, none lost."""
    result = run_js("""
      const contacts = [];
      for (let i = 0; i < 20; i += 1) {
        contacts.push({ key: "1:" + i, x: i, y: 0, distance_to_city: i, turn: 20,
                        name: "Rival One", unit_type: "UNIT_ARCHER" });
      }
      const first = T.page(contacts, { page: 0 });
      const second = T.page(contacts, { page: 1 });
      const clamped = T.page(contacts, { page: 99 });
      return {
        size: first.rows.length, pages: first.pages, total: first.total,
        thirteenth: second.rows[0].key,
        seen: first.rows.concat(second.rows).map((r) => r.key).length,
        clampedPage: clamped.page,
      };
    """)
    assert result["size"] == 12 and result["pages"] == 2 and result["total"] == 20
    assert result["thirteenth"] == "1:12"      # contact thirteen, one page away
    assert result["seen"] == 20                # every contact is on some page
    assert result["clampedPage"] == 1          # an out-of-range page clamps, never empties


def test_filtering_narrows_without_losing_the_count_of_what_it_hid():
    result = run_js(DATA + """
      const contacts = T.contents(data, "all").contacts;
      const byName = T.page(contacts, { filter: "rival two" });
      const byUnit = T.page(contacts, { filter: "archer" });
      const none = T.page(contacts, { filter: "zzz" });
      return {
        byName: byName.rows.map((r) => r.key), nameMatched: byName.matched,
        byUnit: byUnit.rows.map((r) => r.key),
        noneRows: none.rows.length, noneTotal: none.total, nonePages: none.pages,
        totalStillKnown: byName.total,
      };
    """)
    assert result["byName"] == ["2:4"] and result["nameMatched"] == 1
    assert result["byUnit"] == ["1:1", "1:3"]
    assert result["noneRows"] == 0 and result["noneTotal"] == 5 and result["nonePages"] == 1
    assert result["totalStillKnown"] == 5      # how many exist is never hidden by a filter


def test_contacts_sharing_a_tile_are_listed_so_they_can_be_told_apart():
    """One marker cannot be used to pick between two units on the same hex — and cannot be
    reached by keyboard at all. The table is the way in."""
    result = run_js(DATA + """
      const groups = T.coincident(T.contents(data, "all").contacts);
      return groups.map((g) => ({ tile: g.tile, keys: g.contacts.map((c) => c.key) }));
    """)
    assert result == [{"tile": "13:12", "keys": ["1:2", "1:3"]}]


def test_marks_are_sized_from_the_span_being_shown():
    """A two-tile frontier drawn with pinhead markers, or a forty-tile one drawn with
    overlapping ones, is the same bug in two directions."""
    result = run_js("""
      const tight = T.frame([{ x: 10, y: 10 }, { x: 11, y: 10 }]);
      const wide = T.frame([{ x: 0, y: 0 }, { x: 60, y: 40 }]);
      const single = T.frame([{ x: 5, y: 5 }]);
      return {
        tight: { tile: tight.tile, font: tight.font, box: tight.viewBox },
        wide: { tile: wide.tile, font: wide.font },
        single: { tile: single.tile, width: single.width, height: single.height },
        empty: T.frame([]),
      };
    """)
    # Clamped at both ends, so both extremes stay legible.
    assert 8 <= result["tight"]["tile"] <= 26
    assert 8 <= result["wide"]["tile"] <= 26
    assert result["tight"]["font"] >= 6 and result["wide"]["font"] >= 6
    # A single point still gets a box with room around it rather than a zero-sized one.
    assert result["single"]["width"] > 0 and result["single"]["height"] > 0
    assert result["empty"] is None


def test_an_empty_view_is_reported_rather_than_drawn():
    result = run_js(DATA + """
      const bare = T.contents({ clusters: [], enemy_units: [], human_units: [] }, "all");
      return { contacts: bare.contacts.length, tiles: bare.tiles.length,
               views: T.views({ clusters: [], enemy_units: [], human_units: [] })
                 .map((v) => v.id) };
    """)
    assert result["contacts"] == 0 and result["tiles"] == 0
    # Even with nothing recorded, "All contacts" exists and says the count is zero.
    assert result["views"] == ["all"]
