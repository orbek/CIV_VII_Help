"""Execute the dashboard's response rules under node, rather than grepping app.js.

These cover the Phase 1 exit checks that concern the browser's own decisions: a delayed
Oracle-on reply must not be able to restore hidden data, and coverage must be worded
honestly. The end-to-end rendering check (that every oracle-derived region actually
consults `seen`) belongs to the Playwright suite added in Phase 4; what is asserted here
is the logic those regions call, run for real.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

BRIEFING_JS = Path(__file__).resolve().parents[1] / "civ7_advisor" / "web" / "briefing.js"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


def run_js(body: str) -> object:
    """Run `body` with `B` bound to the briefing module; its return value comes back as JSON."""
    script = (
        f"const B = require({str(BRIEFING_JS)!r});\n"
        f"const out = (() => {{ {body} }})();\n"
        "process.stdout.write(JSON.stringify(out === undefined ? null : out));\n"
    )
    done = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_a_delayed_oracle_on_reply_cannot_restore_data_the_player_switched_off():
    """The reproduction from the plan's findings.

    Sequence: the page is showing oracle data from revision 4; the player unchecks
    Oracle, which starts request 2 and immediately makes `seen` false; then the *old*
    oracle-on reply for request 1 arrives. It must be refused on sequence, and even if
    something did paint, `seen` must still be false because the data in hand was
    fetched in oracle mode.
    """
    result = run_js("""
      const state = { seq: 1, session: "s1", revision: 4, showOracle: true, dataMode: "oracle" };
      const oracleReply = { session: "s1", revision: 4, evidence_mode: "oracle" };
      const beforeToggle = B.acceptResponse(state, 1, oracleReply);

      // The player switches Oracle off: a new request starts and the toggle flips.
      state.showOracle = false;
      const mine = ++state.seq;                       // request 2
      const hiddenImmediately = !B.seen(state);       // repainted before any reply lands

      // The stale oracle-on reply for request 1 now arrives.
      const staleAccepted = B.acceptResponse(state, 1, oracleReply);

      // ... and so does an out-of-order reply carrying an older revision.
      const overtakenAccepted = B.acceptResponse(state, mine, {
        session: "s1", revision: 3, evidence_mode: "fair" });

      const freshAccepted = B.acceptResponse(state, mine, {
        session: "s1", revision: 5, evidence_mode: "fair" });
      state.dataMode = "fair";
      return { beforeToggle, hiddenImmediately, staleAccepted, overtakenAccepted,
               freshAccepted, seenAfter: B.seen(state) };
    """)
    assert result["beforeToggle"] is True          # it was legitimate when it was current
    assert result["hiddenImmediately"] is True     # intercepts hidden without waiting for the server
    assert result["staleAccepted"] is False        # the superseded reply is refused
    assert result["overtakenAccepted"] is False    # so is one that overtook a newer revision
    assert result["freshAccepted"] is True
    assert result["seenAfter"] is False


def test_revisions_are_only_compared_within_a_session():
    """After a reload the server starts a new epoch whose revision counter is unrelated,
    so a new session's reply must be accepted even if its revision reads lower."""
    accepted = run_js("""
      const state = { seq: 1, session: "s1", revision: 900, showOracle: true, dataMode: "oracle" };
      return B.acceptResponse(state, 1, { session: "s2", revision: 1, evidence_mode: "oracle" });
    """)
    assert accepted is True


def test_oracle_data_stays_hidden_until_a_fair_reply_actually_lands():
    states = run_js("""
      const s = (showOracle, dataMode) => B.seen({ showOracle, dataMode });
      return { onWithOracleData: s(true, "oracle"), offWithOracleData: s(false, "oracle"),
               onWithFairData: s(true, "fair"), offWithFairData: s(false, "fair"),
               beforeAnyReply: s(true, null) };
    """)
    assert states == {
        "onWithOracleData": True,
        "offWithOracleData": False,   # the point: stale oracle data is not shown
        "onWithFairData": False,      # nor is fair data dressed up as complete
        "offWithFairData": False,
        "beforeAnyReply": True,
    }


def test_coverage_wording_separates_broken_required_from_absent_optional():
    lines = run_js("""
      return B.coverageLines([
        { name: "empire", label: "Empire yields and standings", required: true,
          status: "ok", files: ["Player_Stats.csv"], missing: [], rows: 10,
          latest_turn: 81, lag: 0, errors: [] },
        { name: "tactical", label: "Tactical unit positions and plans", required: false,
          status: "unavailable", files: ["AI_Tactical.csv"], missing: ["AI_Tactical.csv"],
          rows: 0, latest_turn: null, lag: null, errors: ["file not found"] },
        { name: "production", label: "Settlement build queues", required: false,
          status: "empty", files: ["CityBuildQueue.csv"], missing: [], rows: 0,
          latest_turn: null, lag: null, errors: [] },
        { name: "gossip", label: "Observed world events", required: false,
          status: "stale", files: ["Game_Gossip.csv"], missing: [], rows: 4,
          latest_turn: 74, lag: 7, errors: [] },
      ]);
    """)
    text = " | ".join(line["text"] for line in lines)
    assert "Empire yields" not in text                      # a covered domain says nothing
    assert "Not available in this game: Tactical unit positions and plans." in text
    assert "readable, but nothing recorded yet" in text      # empty is not "no queues"
    assert "nothing newer than turn 74 (7 turns behind)" in text
    assert "treat it as dated, not as quiet" in text
    # An absent optional log is a quiet note, never a warning.
    assert [line["cls"] for line in lines] == ["file-note", "file-note", "file-note"]


def test_a_broken_required_source_is_a_warning_not_a_quiet_note():
    lines = run_js("""
      return B.coverageLines([
        { name: "empire", label: "Empire yields and standings", required: true,
          status: "unavailable", files: ["Player_Stats.csv"], missing: ["Player_Stats.csv"],
          rows: 0, latest_turn: null, lag: null, errors: ["unexpected header"] },
      ]);
    """)
    assert lines == [{"cls": "file-warn",
                      "text": "Empire yields and standings is unavailable: unexpected header"}]
