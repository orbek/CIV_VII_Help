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
      if (c.unattributed) {
        lines.push({
          cls: "file-note",
          text: c.label + ": " + c.unattributed + " row"
            + (c.unattributed === 1 ? "" : "s") + " could not be attributed to a player"
            + " — they are excluded, not assigned to you",
        });
      }
      if (c.status === "ok") return;
      if (c.required && (c.status === "unavailable" || c.status === "partial")) {
        lines.push({
          cls: "file-warn",
          text: c.label + " is unavailable" + (c.errors && c.errors.length ? ": " + c.errors[0] : ""),
        });
      } else if (c.status === "unavailable") {
        disabled.push(c.label);
      } else if (c.status === "partial") {
        // "partial" has two distinct causes and `missing` alone cannot tell them apart:
        // a declared file that failed to read, or (unbacked) this game having no reader
        // at all for part of what the domain needs. Stating "0 of N unreadable" when
        // nothing is actually unreadable would give a false reason for the gap.
        const missingNames = c.missing || [];
        const unbackedNames = c.unbacked || [];
        if (missingNames.length) {
          lines.push({
            cls: "file-note",
            text: c.label + " is incomplete — " + missingNames.length + " of " + c.files.length
              + " log" + (c.files.length === 1 ? "" : "s") + " unreadable",
          });
        }
        if (unbackedNames.length) {
          lines.push({
            cls: "file-note",
            text: c.label + " is incomplete — this game does not log "
              + unbackedNames.length + " part" + (unbackedNames.length === 1 ? "" : "s")
              + " of this",
          });
        }
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

  /* ---- the decision brief ------------------------------------------------------

     Grouping overlapping warnings by subject, without losing any of them. Two rival
     warnings about the same player belong in one entry; the evidence and severity of
     each stays distinct inside it, and every original insight remains reachable in the
     tabs below. */

  const SEVERITY_ORDER = { CRITICAL: 3, WARN: 2, ADVISE: 1, INFO: 0 };

  function subjectKey(insight) {
    if (insight.subject_player !== null && insight.subject_player !== undefined) {
      return "player:" + insight.subject_player;
    }
    return "advisor:" + insight.advisor;
  }

  /* Brief entries, most severe first. A structured decision card claims the insights it
     names, so the card and those warnings are one entry rather than two competing ones. */
  function groupDecisions(insights, cards) {
    const claimed = new Set();
    const entries = [];
    (cards || []).forEach(function (card) {
      const mine = (insights || []).filter(function (i) {
        return (card.insight_ids || []).indexOf(i.id) !== -1;
      });
      mine.forEach(function (i) { claimed.add(i.id); });
      entries.push({
        id: card.id, subject: card.subject, card: card, insights: mine,
        severity: maxSeverity([card.severity].concat(mine.map(function (i) { return i.severity; }))),
        source: "decision",
      });
    });
    const bySubject = new Map();
    (insights || []).forEach(function (insight) {
      if (claimed.has(insight.id)) return;
      const key = subjectKey(insight);
      if (!bySubject.has(key)) {
        bySubject.set(key, { id: "group." + key, subject: insight.title, card: null,
                             insights: [], severity: "INFO", source: "insights" });
      }
      const entry = bySubject.get(key);
      entry.insights.push(insight);
      entry.severity = maxSeverity([entry.severity, insight.severity]);
      // The entry is named after its most severe member, so a group is not labelled by
      // whichever warning happened to arrive first.
      if (SEVERITY_ORDER[insight.severity] >= SEVERITY_ORDER[entry.severity]) {
        entry.subject = insight.title;
      }
    });
    bySubject.forEach(function (entry) { entries.push(entry); });
    return entries.sort(function (a, b) {
      const bySeverity = SEVERITY_ORDER[b.severity] - SEVERITY_ORDER[a.severity];
      if (bySeverity) return bySeverity;
      if ((b.card ? 1 : 0) !== (a.card ? 1 : 0)) return (b.card ? 1 : 0) - (a.card ? 1 : 0);
      return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
    });
  }

  function maxSeverity(list) {
    return list.filter(Boolean).reduce(function (best, s) {
      return SEVERITY_ORDER[s] > SEVERITY_ORDER[best] ? s : best;
    }, "INFO");
  }

  /* What the brief shows without an interaction.

     Every distinct critical entry is always in `critical`, however many there are: an
     overflow count is a reasonable way to defer an advisory, and never a reasonable way
     to hide a fourth emergency. Only lower-priority entries may collapse. */
  function splitBrief(entries, limit) {
    const cap = limit === undefined ? 3 : limit;
    const critical = entries.filter(function (e) { return e.severity === "CRITICAL"; });
    const rest = entries.filter(function (e) { return e.severity !== "CRITICAL"; });
    return { critical: critical, top: rest.slice(0, cap), overflow: rest.slice(cap) };
  }

  /* ---- acknowledgements --------------------------------------------------------

     Recording that the player has seen something. Not a game action, and not permanent:
     the fingerprint covers the evidence and the severity, so an acknowledged decision
     resurfaces the moment either changes. */

  function fingerprint(entry) {
    const evidence = entry.card ? (entry.card.evidence_ids || []).slice().sort() : [];
    const insights = entry.insights.map(function (i) { return i.id + ":" + i.severity; }).sort();
    const turns = entry.card ? (entry.card.observed_turns || []).slice().sort() : [];
    return [entry.severity].concat(evidence, insights, turns).join("|");
  }

  function acknowledgementKey(session, entry) {
    return session + "::" + entry.id;
  }

  function isAcknowledged(store, session, entry) {
    return store[acknowledgementKey(session, entry)] === fingerprint(entry);
  }

  /* ---- generated prose --------------------------------------------------------- */

  /* Whether a generation may be shown as the explanation of what is on screen.

     Every field of the identity must match, and the insights it was written about must
     still be the ones in this entry. A generation that explained a different preferred
     action is history, not an explanation — however recent it is. */
  function commentaryExplains(identity, current, insightIds) {
    if (!identity || !current) return false;
    const fields = ["session", "epoch", "evidence_mode", "snapshot_revision", "turn",
                    "decision_revision", "context_revision", "catalog_revision"];
    for (let i = 0; i < fields.length; i += 1) {
      if (identity[fields[i]] !== current[fields[i]]) return false;
    }
    if (!insightIds || !insightIds.length) return true;
    const written = identity.insight_ids || [];
    return insightIds.every(function (id) { return written.indexOf(id) !== -1; });
  }

  const api = {
    acceptResponse: acceptResponse, seen: seen, ago: ago, coverageLines: coverageLines,
    groupDecisions: groupDecisions, splitBrief: splitBrief, maxSeverity: maxSeverity,
    fingerprint: fingerprint, acknowledgementKey: acknowledgementKey,
    isAcknowledged: isAcknowledged, commentaryExplains: commentaryExplains,
    SEVERITY_ORDER: SEVERITY_ORDER,
  };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.Civ7Briefing = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
