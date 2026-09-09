/* Pure decisions the dashboard makes about a briefing response, with no DOM.

   These are the rules that keep the screen honest — which reply may paint, whether
   intercepted content may be shown right now, and how coverage is worded. They live
   here rather than inline in app.js so they can be executed and asserted directly
   (tests/test_web_briefing.py runs this file under node), instead of being pinned by
   grepping app.js for strings. */
(function (root) {
  "use strict";

  /* Whether a reply is still the one we want to paint.

     Three independent ways a reply can be obsolete:
       - a newer request has started since (`seq` no longer matches);
       - it carries an older snapshot revision than what is already on screen, i.e. it
         overtook a newer reply on the wire;
       - nothing at all came back.

     The revision comparison is scoped to a session: after a reload the server starts a
     new epoch, and its revisions must not be judged against the previous game's. */
  function acceptResponse(state, seq, status) {
    if (!status) return false;
    if (seq !== state.seq) return false;
    if (status.session === state.session && status.revision < state.revision) return false;
    return true;
  }

  /* Whether intercepted content may be shown at this instant.

     Both halves matter. The player must have Oracle on, AND the data on screen must have
     been fetched with Oracle on: while a fair-mode request is in flight the data in hand
     is still the oracle-mode data, and it must not be displayed. This is what stops a
     late Oracle-on reply — or the un-refreshed data behind it — from putting intercepts
     back after the toggle was switched off. */
  function seen(state) {
    return Boolean(state.showOracle) && state.dataMode !== "fair";
  }

  function ago(ms) {
    const s = Math.round(ms / 1000);
    if (s < 5) return "just now";
    if (s < 90) return s + "s ago";
    return Math.round(s / 60) + "m ago";
  }

  /* Coverage as sentences, not a list of file paths.

     A required domain failing is a warning. An optional domain the game never wrote is
     one quiet line naming the capability that is therefore off. "Readable but empty" and
     "nothing recent enough" are reported as exactly that, because neither one means the
     thing being measured is quiet — only that these logs do not cover it. */
  function coverageLines(coverage) {
    const lines = [];
    const disabled = [];
    (coverage || []).forEach(function (c) {
      if (c.status === "ok") return;
      if (c.required && (c.status === "unavailable" || c.status === "partial")) {
        lines.push({
          cls: "file-warn",
          text: c.label + " is unavailable" + (c.errors && c.errors.length ? ": " + c.errors[0] : ""),
        });
      } else if (c.status === "unavailable") {
        disabled.push(c.label);
      } else if (c.status === "partial") {
        lines.push({
          cls: "file-note",
          text: c.label + " is incomplete — " + c.missing.length + " of " + c.files.length
            + " log" + (c.files.length === 1 ? "" : "s") + " unreadable",
        });
      } else if (c.status === "empty") {
        lines.push({ cls: "file-note", text: c.label + ": readable, but nothing recorded yet" });
      } else if (c.status === "stale") {
        lines.push({
          cls: "file-note",
          text: c.label + ": nothing newer than turn " + c.latest_turn + " (" + c.lag
            + " turn" + (c.lag === 1 ? "" : "s") + " behind) — treat it as dated, not as quiet",
        });
      }
    });
    if (disabled.length) {
      lines.push({ cls: "file-note", text: "Not available in this game: " + disabled.join(", ") + "." });
    }
    return lines;
  }

  const api = { acceptResponse: acceptResponse, seen: seen, ago: ago, coverageLines: coverageLines };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.Civ7Briefing = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
