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

  /* A pin is HONOURED even when its logs directory does not exist or has never been
     written to (spec 8.1: an empty, correctly-labelled dashboard beats a silent
     fallback to the other game) -- but those two situations look identical on screen
     and have opposite remedies, so the header must name which one it is. Read off the
     matching detection candidate: `present` is whether the directory itself exists;
     `age` is null only when nothing the game declares has ever been written there.
     Returns null for auto mode, an unpinned game, or a pinned game with no gap at all. */
  function pinnedGameGap(game) {
    if (!game || game.mode !== "pinned") return null;
    const candidate = (game.detection.candidates || []).find(function (c) {
      return c.id === game.pinned;
    });
    if (!candidate) return null;
    if (!candidate.present) return "its logs folder was not found — install or launch the game";
    if (candidate.age === null) return "no log has been written for it yet — play a turn";
    return null;
  }

  /* Which capabilities each panel needs to be meaningful. A panel missing from this map
     depends on nothing game-specific and always renders: silence must be earned by a
     declaration, never by a lookup failing. */
  var PANEL_CAPABILITIES = {
    victory: ["victory_paths"],
    economy: ["maintenance", "happiness"],
  };

  /* An empty panel and an unsupported panel mean opposite things: "no rival is chasing
     a victory" versus "this game does not record which victory a rival is pursuing."
     One notice per capability this panel needs that the active game does not support,
     each carrying the profile's own reason rather than a generic placeholder. */
  function capabilityNotices(capabilities, panel) {
    var needed = PANEL_CAPABILITIES[panel] || [];
    var out = [];
    needed.forEach(function (name) {
      var held = (capabilities || {})[name];
      if (!held || held.supported) return;
      out.push({ capability: name, reason: held.reason || "not available in this game" });
    });
    return out;
  }

  /* ---- the live tuner's pre-fill for the Refine flow ----------------------------

     A tuner reading is a value the advisor asked the running game for at a moment it
     chose. It pre-fills the Refine form so the player is not asked to retype what the
     game already told the advisor -- but it is a suggestion, not a submission: the
     player still presses Record before it becomes their own report. These two lookups
     are pure so the wiring that decides WHAT gets pre-filled can be tested without a
     DOM, leaving app.js only the job of putting it on screen. */

  /* This settlement's live build options, or null: the tuner never answered for it, or
     is off, or has no reading for this city. */
  function tunerLiveOptions(tuner, city) {
    if (!tuner || !tuner.available) return null;
    var found = null;
    (tuner.build_options || []).forEach(function (so) {
      if (so.city === city) found = so;
    });
    return found;
  }

  /* How many turns the tuner said this settlement's build of `item` would take, or
     null if it did not answer for this item. The only metric a live reading may
     pre-fill -- see `civ_advisor/decisions/context.py:Previews` for why the other
     three stay for the ruleset or the player alone. */
  function tunerLiveTurns(liveOptions, item) {
    if (!liveOptions) return null;
    var match = null;
    (liveOptions.options || []).forEach(function (o) {
      if (o.item === item) match = o;
    });
    return match ? match.turns : null;
  }

  /* What the Economy tab shows from a live tuner reading, and what it says where the
     tuner could not supply a figure.

     Turning the tuner ON used to REPLACE an honest notice with a blank: the capability
     report flips happiness and maintenance to supported the moment the socket answers,
     which removes the "Civ VI writes no amenities log" notice -- and nothing rendered
     an amenities figure or an upkeep breakdown in its place. A player who did exactly
     what the notice asked was left with less on screen than before.

     Pure, so what the tab shows can be executed in a test rather than grepped for.
     Each section carries its OWN absence reason: one figure the game will not itemise
     must not be reported as the reason the others are missing, and must never be
     reported as a zero. */
  function tunerEconomy(tuner) {
    var live = !!(tuner && tuner.available);

    function label(read) {
      /* Every figure is labelled with the turn and instant THAT query produced, never
         with the snapshot's log-derived turn: the socket reads the live game, which
         can be ahead of the last complete log turn. */
      return read ? "read live — turn " + read.turn + " (" + read.read_at + ")" : null;
    }

    function section(figures, reason, read) {
      if (!live) return { figures: [], note: null, absent: (tuner && tuner.reason) || null };
      if (!figures.length) return { figures: [], note: null, absent: reason || null };
      return { figures: figures, note: label(read), absent: null };
    }

    var m = live ? (tuner.maintenance || null) : null;
    var upkeep = [];
    if (m) {
      upkeep.push({ label: "Buildings", value: m.buildings });
      upkeep.push({ label: "Districts", value: m.districts });
      upkeep.push({ label: "Units", value: m.units });
      /* Only when it is non-zero, and named for what it is: the three categories the
         game itemises are not known to be exhaustive, so the remainder is reported
         rather than silently folded into one of them. */
      if (m.unattributed !== 0) {
        upkeep.push({ label: "Not itemised by the game", value: m.unattributed });
      }
      upkeep.push({ label: "Total upkeep", value: m.total });
      upkeep.push({ label: "Net gold per turn", value: m.net_gold });
    }

    return {
      live: live,
      amenities: section(live ? (tuner.amenities || []) : [],
                         tuner && tuner.amenities_reason,
                         tuner && tuner.amenities_read),
      upkeep: section(upkeep, tuner && tuner.maintenance_reason,
                      tuner && tuner.maintenance_read),
    };
  }

  /* The badge text for one evidence fact's source kind. Its own case for a live
     reading, distinct from both "you told us" (typed) and a bare log row (the game's
     own write) -- the confusion this label exists to prevent from reaching the page. */
  function factKindLabel(kind) {
    if (kind === "player_report") return "you told us";
    if (kind === "live_reading") return "read live";
    if (kind === "derived") return "computed";
    if (kind === "rule") return "advisor rule";
    if (kind === "installed_ruleset") return "your installed ruleset";
    return "log";
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
    pinnedGameGap: pinnedGameGap, capabilityNotices: capabilityNotices,
    PANEL_CAPABILITIES: PANEL_CAPABILITIES,
    groupDecisions: groupDecisions, splitBrief: splitBrief, maxSeverity: maxSeverity,
    fingerprint: fingerprint, acknowledgementKey: acknowledgementKey,
    isAcknowledged: isAcknowledged, commentaryExplains: commentaryExplains,
    SEVERITY_ORDER: SEVERITY_ORDER,
    tunerLiveOptions: tunerLiveOptions, tunerLiveTurns: tunerLiveTurns,
    tunerEconomy: tunerEconomy,
    factKindLabel: factKindLabel,
  };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.Civ7Briefing = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
