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

BRIEFING_JS = Path(__file__).resolve().parents[1] / "civ_advisor" / "web" / "briefing.js"

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


def test_unattributed_rows_are_reported_even_when_the_domain_is_healthy():
    lines = run_js(
        'return B.coverageLines([{name: "production", label: "Settlement build queues",'
        ' status: "ok", required: false, files: ["City_BuildQueue.csv"], missing: [],'
        ' rows: 807, errors: [], unattributed: 12}]);'
    )
    assert len(lines) == 1
    assert "12 rows could not be attributed" in lines[0]["text"]
    assert "not assigned to you" in lines[0]["text"]


def test_an_unbacked_partial_domain_never_claims_a_file_is_unreadable():
    """LIVE DEFECT this task fixes: before, a domain whose files all read fine but
    which has no reader at all for part of what it covers (Civ VI's diplomacy) rendered
    as "0 of 1 logs unreadable" -- a false reason for a real gap. `missing` is empty
    here on purpose; only `unbacked` explains why the domain is still "partial"."""
    lines = run_js("""
      return B.coverageLines([
        { name: "diplomacy", label: "Rival diplomatic intent", required: false,
          status: "partial", files: ["DiplomacySummary.csv"], missing: [], rows: 5,
          latest_turn: 81, lag: 0, errors: [], unbacked: ["diplomacy", "deals"] },
      ]);
    """)
    text = " | ".join(line["text"] for line in lines)
    assert "unreadable" not in text
    assert "0 of" not in text
    assert "does not log 2 parts of this" in text


def test_a_partial_domain_with_both_causes_reports_both():
    lines = run_js("""
      return B.coverageLines([
        { name: "tactical", label: "Tactical unit positions and plans", required: false,
          status: "partial", files: ["AI_Tactical.csv", "AI_Operation.csv"],
          missing: ["AI_Operation.csv"], rows: 3, latest_turn: 80, lag: 1,
          errors: ["file not found"], unbacked: ["mayhem"] },
      ]);
    """)
    text = " | ".join(line["text"] for line in lines)
    assert "1 of 2 logs unreadable" in text
    assert "does not log 1 part of this" in text


def _game(mode, pinned=None, candidates=()):
    return {"mode": mode, "pinned": pinned, "detection": {"candidates": list(candidates)}}


def test_a_pinned_game_whose_directory_is_absent_says_so():
    game = _game("pinned", "civ6", [{"id": "civ6", "present": False, "age": None}])
    gap = run_js(f"return B.pinnedGameGap({json.dumps(game)});")
    assert gap == "its logs folder was not found — install or launch the game"


def test_a_pinned_game_that_is_installed_but_unplayed_says_so_differently():
    """The two gap messages must never collapse into each other: "not found" is the
    remedy for an absent directory (install/launch), not for one that exists but has
    nothing written in it yet (play a turn) -- conflating them would send a player who
    already has the game installed off to reinstall it."""
    game = _game("pinned", "civ6", [{"id": "civ6", "present": True, "age": None}])
    gap = run_js(f"return B.pinnedGameGap({json.dumps(game)});")
    assert gap == "no log has been written for it yet — play a turn"
    assert "not found" not in gap


def test_a_pinned_game_with_no_gap_is_null():
    game = _game("pinned", "civ7", [{"id": "civ7", "present": True, "age": 12.3}])
    assert run_js(f"return B.pinnedGameGap({json.dumps(game)});") is None


def test_auto_mode_has_no_pinned_gap():
    game = _game("auto", None, [{"id": "civ6", "present": False, "age": None}])
    assert run_js(f"return B.pinnedGameGap({json.dumps(game)});") is None


# ---- the decision brief ----------------------------------------------------------

INSIGHTS = """
  const insights = [
    { id: "threat.at_war.4", advisor: "threat", severity: "CRITICAL", provenance: "oracle",
      subject_player: 4, title: "Rizal declared war", recommendation: "Garrison.", why: "..." },
    { id: "threat.targeting.4", advisor: "threat", severity: "WARN", provenance: "oracle",
      subject_player: 4, title: "Rizal is targeting you", recommendation: "Watch.", why: "..." },
    { id: "economy.behind.culture", advisor: "economy", severity: "ADVISE", provenance: "fair",
      subject_player: 0, title: "Culture behind", recommendation: "Invest.", why: "..." },
    { id: "victory.science", advisor: "victory", severity: "INFO", provenance: "fair",
      subject_player: null, title: "Science race", recommendation: "Note.", why: "..." },
  ];
  const card = { id: "decision.culture.TEST", subject: "Culture in Test1", severity: "ADVISE",
    priority_reason: "the observed gap", insight_ids: ["economy.behind.culture"],
    evidence_ids: ["comparison.culture.81"], observed_turns: [81],
    preferred: { id: "action.a", title: "Inspect", applicability: "inspect" },
    alternatives: [], unknowns: [] };
"""


def test_warnings_about_one_subject_are_grouped_without_losing_any():
    result = run_js(INSIGHTS + """
      const entries = B.groupDecisions(insights, [card]);
      return entries.map(function (e) {
        return { id: e.id, severity: e.severity, insights: e.insights.map(function (i) { return i.id; }),
                 hasCard: Boolean(e.card) };
      });
    """)
    # Most severe first, and the two Rizal warnings are one entry with both preserved.
    assert result[0]["severity"] == "CRITICAL"
    assert result[0]["insights"] == ["threat.at_war.4", "threat.targeting.4"]
    # The structured card claims the insight it names, so they are not two competing rows.
    culture = next(e for e in result if e["hasCard"])
    assert culture["id"] == "decision.culture.TEST"
    assert culture["insights"] == ["economy.behind.culture"]
    # Nothing is dropped: every insight appears exactly once across the entries.
    seen = [i for e in result for i in e["insights"]]
    assert sorted(seen) == sorted(i["id"] for i in [
        {"id": "threat.at_war.4"}, {"id": "threat.targeting.4"},
        {"id": "economy.behind.culture"}, {"id": "victory.science"}])


def test_a_group_is_named_after_its_most_severe_member():
    subject = run_js(INSIGHTS + """
      const entries = B.groupDecisions(insights, []);
      return entries[0].subject;
    """)
    assert subject == "Rizal declared war"


def test_a_fourth_critical_decision_is_shown_without_an_overflow_click():
    """An overflow count may defer an advisory. It may never hide a fourth emergency."""
    result = run_js("""
      const entries = [];
      for (let i = 0; i < 4; i += 1) {
        entries.push({ id: "crit" + i, subject: "Emergency " + i, severity: "CRITICAL",
                       insights: [], card: null });
      }
      for (let i = 0; i < 5; i += 1) {
        entries.push({ id: "adv" + i, subject: "Advice " + i, severity: "ADVISE",
                       insights: [], card: null });
      }
      const split = B.splitBrief(entries);
      return { critical: split.critical.map(function (e) { return e.id; }),
               top: split.top.map(function (e) { return e.id; }),
               overflow: split.overflow.map(function (e) { return e.id; }) };
    """)
    assert result["critical"] == ["crit0", "crit1", "crit2", "crit3"]   # all four, expanded
    assert result["top"] == ["adv0", "adv1", "adv2"]                     # three by default
    assert result["overflow"] == ["adv3", "adv4"]                        # only lower priority
    assert not [i for i in result["overflow"] if i.startswith("crit")]


def test_an_acknowledgement_resurfaces_when_the_evidence_or_severity_changes():
    """Acknowledging records that the player has seen something. It is not a promise that
    the situation will not change."""
    result = run_js(INSIGHTS + """
      const entry = B.groupDecisions(insights, [card]).find(function (e) { return e.card; });
      const store = {};
      store[B.acknowledgementKey("s1", entry)] = B.fingerprint(entry);
      const acknowledged = B.isAcknowledged(store, "s1", entry);

      const worse = JSON.parse(JSON.stringify(entry));
      worse.severity = "WARN";
      const afterSeverity = B.isAcknowledged(store, "s1", worse);

      const newEvidence = JSON.parse(JSON.stringify(entry));
      newEvidence.card.evidence_ids = ["comparison.culture.82"];
      const afterEvidence = B.isAcknowledged(store, "s1", newEvidence);

      const newSession = B.isAcknowledged(store, "s2", entry);
      return { acknowledged, afterSeverity, afterEvidence, newSession };
    """)
    assert result == {"acknowledged": True, "afterSeverity": False,
                      "afterEvidence": False, "newSession": False}


def test_generated_prose_may_only_explain_the_decision_context_it_was_written_about():
    result = run_js("""
      const current = { session: "s1", epoch: 1, evidence_mode: "oracle",
        snapshot_revision: 9, turn: 81, decision_revision: "abc123",
        context_revision: 4, catalog_revision: "2026-09-08.2" };
      const written = Object.assign({}, current, { insight_ids: ["a", "b"] });
      const out = { matching: B.commentaryExplains(written, current, ["a"]) };

      // The player supplied a preview while the generation was running: the preferred
      // action changed, so the decision fingerprint changed, so this prose is history.
      out.afterPreview = B.commentaryExplains(written, Object.assign({}, current,
        { decision_revision: "def456" }), ["a"]);
      out.afterContext = B.commentaryExplains(written, Object.assign({}, current,
        { context_revision: 5 }), ["a"]);
      out.afterCatalog = B.commentaryExplains(written, Object.assign({}, current,
        { catalog_revision: "2026-10-01.1" }), ["a"]);
      out.afterModeSwitch = B.commentaryExplains(written, Object.assign({}, current,
        { evidence_mode: "fair" }), ["a"]);
      out.afterReload = B.commentaryExplains(written, Object.assign({}, current,
        { session: "s2" }), ["a"]);
      out.afterRebuild = B.commentaryExplains(written, Object.assign({}, current,
        { snapshot_revision: 10 }), ["a"]);
      // Written about other insights than the ones now grouped here.
      out.differentInsights = B.commentaryExplains(written, current, ["c"]);
      out.noIdentity = B.commentaryExplains(null, current, ["a"]);
      return out;
    """)
    assert result["matching"] is True
    assert all(value is False for key, value in result.items() if key != "matching"), result
