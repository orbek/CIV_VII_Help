(() => {
  /* The response and coverage rules live in briefing.js so they can be tested by
     executing them rather than by grepping this file. */
  const B = window.Civ7Briefing;
  const { acceptResponse, seen: seenIn, ago: AGO, coverageLines, pinnedGameGap } = B;
  const $ = (sel) => document.querySelector(sel);
  const el = (tag, cls, text) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  };
  const fmt = (v, digits = 1) => (v === null || v === undefined) ? "—" : Number(v).toFixed(digits);
  const dim = (text = "—") => ({ text, cls: "dim" });
  const itemName = (key) => key.replace(/^LOC_/, "").replace(/_NAME$/, "")
    .replace(/^(BUILDING|UNIT|IMPROVEMENT|WONDER|DISCIPLINE|PROMOTION)_/, "").replace(/_/g, " ")
    .toLowerCase().replace(/\b\w/g, (ch) => ch.toUpperCase());
  const ordinal = (n) => {
    const tens = n % 100, ones = n % 10;
    const suffix = (tens > 10 && tens < 14) ? "th"
      : ones === 1 ? "st" : ones === 2 ? "nd" : ones === 3 ? "rd" : "th";
    return `${n}${suffix}`;
  };
  const PATH_LABEL = {
    SCIENCE: "Science", CULTURAL: "Cultural", MILITARY: "Military",
    ECONOMIC: "Economic", ESPIONAGE: "Espionage",
  };
  /* Threats table. The columns are declared once, here, split by provenance:
     the Oracle toggle drops THREATS_ORACLE_COLUMNS outright rather than blanking
     them, so this split *is* the fair/oracle boundary for the table, and
     tests/test_api.py pins both lists so an AI-internal column cannot drift into
     the fair set. Each label says exactly what its number is: `kills` counts the
     dead on both sides, so the rival's share is "Their losses" = kills - losses;
     and at_war_since only sees declarations inside the advisor's recent window. */
  const THREATS_FAIR_COLUMNS = [
    { label: "Rival", cell: (t) => t.name },
    { label: "Land units", num: true, cell: (t) => t.land_units },
    { label: "vs you", num: true, cell: (t) => `${fmt(t.military_ratio)}x` },
    { label: "Their losses", num: true, cell: (t) => t.kills - t.losses },
    { label: "Your losses", num: true, cell: (t) => t.losses },
  ];
  const THREATS_ORACLE_COLUMNS = [
    { label: "War score", num: true, cell: (t) => t.war_score === null ? dim() : fmt(t.war_score, 0) },
    { label: "Since turn", num: true, cell: (t) => t.war_score_since === null ? dim() : t.war_score_since },
    { label: "War declared", cell: (t) => t.at_war_since !== null
        ? `turn ${t.at_war_since}` : t.peace_since !== null ? `peace turn ${t.peace_since}` : dim() },
    { label: "Targeting", cell: (t) => (t.city_tiles_targeted || t.units_targeted)
        ? `${t.city_tiles_targeted} city tiles, ${t.units_targeted} units` : dim() },
  ];
  const SEVERITY_WORD = { CRITICAL: "Critical.", WARN: "Warning.", ADVISE: "Advice.", INFO: "Note." };
  const NOTHING_AT_ALL = "Nothing to report yet. Start a game, or point the advisor at another log folder.";
  const ORACLE_OFF = "Oracle off — AI intent, targeting and strategic focus are hidden.";
  const INTEL_ORACLE_OFF = "Oracle off — fights, deals and diplomacy between rivals are hidden.";

  const state = { data: null, status: null, insights: [], intel: [], tactical: null,
    commentary: null, commentaryTimer: null, showOracle: true, shownTurn: null, viaEvent: false,
    /* Request bookkeeping. `seq` numbers every fetch we start; only the newest one may
       paint. `dataMode` is the mode the data on screen was fetched in, which is not the
       same as the mode the player has selected while a request is in flight — see
       `seen()`. `revision` is the server's monotonic snapshot revision, so a reply that
       overtook a newer one on the wire is dropped rather than rendered. */
    seq: 0, dataMode: null, revision: 0, session: null, controller: null,
    connected: false, lastUpdate: null,
    /* Brief state. `acks` and `pins` record what the player has seen or wants kept in
       view — intent, never a game action. `expanded` remembers which decisions are open
       through a refresh so a turn update does not collapse what is being read. */
    decisions: null, acks: {}, pins: {}, expanded: {}, briefOpen: false,
    drawerOpener: null, refineStatus: {},
    /* Tactical view state, kept through a refresh so a turn update does not throw the
       player back to a different frontier or lose the contact they had selected. */
    tacticalView: null, contactPage: 0, contactFilter: "", selectedContact: null,
    changes: null, record: null, answers: {}, challengeText: {},
    /* Which game, and whether a switch is in flight (disables the control so a second
       click cannot race the first's request). */
    game: null, gameBusy: false };

  try { state.acks = JSON.parse(localStorage.getItem("civ7.acks") || "{}"); } catch (_) { /* ignore */ }
  try { state.pins = JSON.parse(localStorage.getItem("civ7.pins") || "{}"); } catch (_) { /* ignore */ }
  const persist = (key, value) => {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch (_) { /* private mode */ }
  };

  try { state.showOracle = localStorage.getItem("civ7.oracle") !== "off"; } catch (_) { /* private mode */ }
  $("#oracle").checked = state.showOracle;
  $("#oracle").addEventListener("change", (e) => {
    state.showOracle = e.target.checked;
    try { localStorage.setItem("civ7.oracle", state.showOracle ? "on" : "off"); } catch (_) { /* ignore */ }
    /* Repaint before fetching. The data in hand was fetched in the old mode, so leaving
       it up until the reply lands would keep intercepted content on screen after the
       player switched it off. `seen()` is false the moment the box is unchecked, and
       every oracle-derived region checks it. */
    render();
    refresh();
  });

  $("#game-select").addEventListener("change", async (e) => {
    const chosen = e.target.value;
    state.gameBusy = true;
    renderGame();
    try {
      const response = await fetch("/api/game", {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ game: chosen }),
      });
      if (response.ok) state.game = await response.json();
    } catch (_) { /* the refresh below reports the real state either way */ }
    state.gameBusy = false;
    /* Everything on screen was computed under the previous game. Clear it before the
       new brief lands rather than leaving one game's advice under another's name. */
    state.data = null; state.insights = []; state.intel = []; state.decisions = null;
    state.changes = null; state.tactical = null; state.commentary = null;
    render();
    refresh();
  });

  /* Whether intercepted content may be shown right now: the player must have it on AND
     the data on screen must have been fetched with it on. */
  const seen = () => seenIn(state);

  const tabs = Array.from(document.querySelectorAll(".tabs button"));
  function selectTab(button) {
    tabs.forEach((b) => {
      const on = b === button;
      b.classList.toggle("active", on);
      b.setAttribute("aria-selected", on ? "true" : "false");
      b.tabIndex = on ? 0 : -1;
      $("#" + b.dataset.tab).classList.toggle("active", on);
    });
  }
  tabs.forEach((b, i) => {
    b.addEventListener("click", () => selectTab(b));
    b.addEventListener("keydown", (e) => {
      const step = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
      if (!step) return;
      e.preventDefault();
      const next = tabs[(i + step + tabs.length) % tabs.length];
      selectTab(next);
      next.focus();
    });
  });

  async function refresh() {
    const o = state.showOracle ? 1 : 0;
    const mine = ++state.seq;
    if (state.controller) state.controller.abort();   // stop the superseded request
    const controller = new AbortController();
    state.controller = controller;
    let body;
    try {
      const response = await fetch(`/api/briefing?oracle=${o}`, { signal: controller.signal });
      if (!response.ok) { renderStatus(); return; }
      body = await response.json();
    } catch (_) {
      /* Aborted, or the server went away. An abort is not a failure: a newer request is
         already running, so say nothing and let that one report. */
      if (mine === state.seq) { state.connected = false; renderStatus(); }
      return;
    }
    /* A superseded or overtaken reply is dropped, never painted: this is how an old
       Oracle-on reply used to restore intercepted content after Oracle was switched off. */
    if (!acceptResponse(state, mine, body.status)) return;
    const status = body.status;
    state.session = status.session;
    state.revision = status.revision;
    state.dataMode = status.evidence_mode;
    state.status = status;
    state.game = status.game;
    state.data = body.state;
    state.insights = body.insights;
    state.hiddenInsights = body.hidden_insights;
    state.intel = body.intel;
    state.tactical = body.tactical;
    state.commentary = body.commentary;
    state.decisions = body.decisions;
    state.changes = body.changes;
    state.record = body.record;
    state.connected = true;
    state.lastUpdate = Date.now();
    render();
  }

  /* The server already filtered by mode; filter again so a reply still in flight after
     the player switched the toggle off cannot leave an intercept on screen. */
  const visible = () => state.insights.filter((x) => seen() || x.provenance !== "oracle");
  const visibleIntel = () => state.intel.filter((x) => seen() || x.provenance !== "oracle");

  /* Copy for an empty list: say plainly whether the toggle is what emptied it. In fair
     mode the server does not send the intercepted cards at all, so the count of what it
     withheld comes from the envelope rather than from the list on screen. */
  function emptyText(advisor) {
    const withheldHere = !seen() && (advisor === undefined
      ? (state.hiddenInsights || 0) > 0
      : state.insights.some((i) => i.advisor === advisor && i.provenance === "oracle")
        || (state.hiddenInsights || 0) > 0);
    if (withheldHere) return "Nothing here with Oracle off.";
    if (advisor === undefined) return NOTHING_AT_ALL;
    return "No advice here this turn.";
  }

  function insight(ins) {
    const node = el("article", `insight sev-${ins.severity.toLowerCase()} prov-${ins.provenance}`);
    const title = el("h3", "insight-title");
    title.append(el("span", "sr-only", SEVERITY_WORD[ins.severity] || ins.severity),
      el("span", "title-text", ins.title));
    if (ins.provenance === "oracle") title.append(document.createTextNode(" "), el("span", "tag", "intercept"));
    node.append(title, el("p", "insight-rec", ins.recommendation), el("p", "insight-why", ins.why));
    return node;
  }

  const withheld = () => el("p", "oracle-off", ORACLE_OFF);

  function stream(list, advisor) {
    const wrap = el("div", "stream");
    if (!list.length) wrap.append(el("p", "empty", emptyText(advisor)));
    list.forEach((i) => wrap.append(insight(i)));
    return wrap;
  }

  /* cols: [{label, num}] (a column may carry more, e.g. the threats table's cell fn);
     a cell is a string, a Node, or {text, cls}. */
  function table(cols, rows) {
    const t = el("table");
    const head = el("tr");
    cols.forEach((c) => head.append(el("th", c.num ? "num" : null, c.label)));
    const thead = el("thead");
    thead.append(head);
    const body = el("tbody");
    rows.forEach((row) => {
      const tr = el("tr");
      row.forEach((cell, i) => {
        const classes = cols[i].num ? ["num"] : [];
        const td = el("td");
        if (cell instanceof Node) td.append(cell);
        else if (cell && typeof cell === "object") { td.textContent = cell.text; if (cell.cls) classes.push(cell.cls); }
        else td.textContent = String(cell);
        if (classes.length) td.className = classes.join(" ");
        tr.append(td);
      });
      body.append(tr);
    });
    t.append(thead, body);
    const wrap = el("div", "table-scroll");
    wrap.append(t);
    return wrap;
  }

  /* A name with its figure trailing, e.g. "Ibn Battuta 37.0". */
  function named(name, value, mine) {
    const span = el("span", mine ? "you" : null);
    span.append(document.createTextNode(name), el("span", "fig", fmt(value)));
    return span;
  }

  function renderHero(d, ins) {
    $("#turn").textContent = String(d.complete_through_turn);
    $("#progress").textContent = d.in_progress
      ? `turn ${d.latest_turn} in progress`
      : `turn ${d.complete_through_turn} complete`;

    const headline = $("#headline");
    if (ins.length) {
      const top = ins[0];
      headline.className = `hero-headline sev-${top.severity.toLowerCase()}`;
      headline.replaceChildren(el("span", "headline-text", top.title));
      if (top.provenance === "oracle") headline.append(document.createTextNode(" "), el("span", "tag", "intercept"));
    } else {
      headline.className = "hero-headline quiet";
      headline.replaceChildren(el("span", "headline-text",
        state.insights.length ? "Nothing to report with Oracle off." : "Nothing to report yet."));
    }

    if (state.viaEvent && state.shownTurn !== null && d.complete_through_turn !== state.shownTurn) {
      const figure = document.querySelector(".turn-figure");
      figure.classList.remove("lands");
      void figure.offsetWidth;              // restart the one animation on the page
      figure.classList.add("lands");
    }
    state.shownTurn = d.complete_through_turn;
    state.viaEvent = false;
  }

  function renderRanks(d) {
    let field = null;
    $("#ranks").replaceChildren(...Object.entries(d.ranks).map(([stat, [rank, count]]) => {
      const item = el("span", "rank");
      const figure = count === field ? ordinal(rank) : `${ordinal(rank)} of ${count}`;
      field = count;
      item.append(el("span", null, stat.replace(/_/g, " ")), el("span", "rank-figure", figure));
      return item;
    }));
  }

  /* The header has to answer "can I trust these numbers?" before it answers "what should
     I do?". Three separate facts, never conflated: are we talking to the server; when did
     we last get an answer; and which turn the advice was computed on. */
  function renderStatus() {
    const link = $("#connection");
    link.textContent = state.connected ? "connected" : "reconnecting…";
    link.className = `conn ${state.connected ? "conn-up" : "conn-down"}`;
    const status = state.status;
    const parts = [];
    if (state.lastUpdate !== null) parts.push(`updated ${AGO(Date.now() - state.lastUpdate)}`);
    if (status) {
      parts.push(`analysed through turn ${status.analysis_turn}`);
      if (status.in_progress) parts.push(`turn ${status.latest_turn} in progress`);
    }
    $("#updated").textContent = parts.join(" · ");
  }

  /* Announce only what changed and matters: the analysis turn, the connection, and how
     many critical alerts are outstanding. The freshness counter ticks every five
     seconds and would otherwise talk over everything else. */
  let announced = null;
  function announce(criticalCount) {
    const status = state.status;
    const key = [state.connected, status && status.analysis_turn, criticalCount].join("|");
    if (key === announced) return;
    const first = announced === null;
    announced = key;
    if (first) return;                       // the initial paint is not news
    const said = [];
    if (!state.connected) said.push("Lost contact with the advisor; reconnecting.");
    else if (status) said.push(`Turn ${status.analysis_turn} analysed.`);
    if (criticalCount) {
      said.push(`${criticalCount} critical alert${criticalCount === 1 ? "" : "s"}.`);
    }
    $("#announce").textContent = said.join(" ");
  }

  /* Which game, and how that was decided. The mode is stated in words rather than left
     to be inferred from which option is selected: a pinned choice that detection
     contradicts is the one case where the numbers on screen may come from a game the
     player is not looking at, and they have to be told rather than left to find out. */
  const DETECTION_WORDS = {
    detected: (g) => `detection says ${g}`,
    all_stale: () => "nothing written recently — detection cannot tell",
    no_candidates: () => "no game's log folder found — detection cannot tell",
    ambiguous: () => "two games wrote at the same moment — detection cannot tell",
  };

  // `pinnedGameGap` (whether the pinned game's own directory is absent or just unplayed)
  // lives in briefing.js, imported above: it is pure logic over the `game` object with no
  // DOM, so it belongs where node can execute and assert it directly (tests/test_web_briefing.py),
  // the same reason `coverageLines` lives there rather than inline here.

  function renderGame() {
    const game = state.game;
    const select = $("#game-select");
    const mode = $("#game-mode");
    if (!game) { mode.textContent = ""; return; }
    const names = {};
    game.games.forEach((g) => { names[g.id] = g.display_name; });
    const wanted = ["auto"].concat(game.games.map((g) => g.id)).join("|");
    if (select.dataset.built !== wanted) {
      select.replaceChildren(...[el("option", null, "Auto — detect from the logs")]
        .concat(game.games.map((g) => el("option", null, g.display_name))));
      select.children[0].value = "auto";
      game.games.forEach((g, i) => { select.children[i + 1].value = g.id; });
      select.dataset.built = wanted;
    }
    select.value = game.mode === "pinned" ? game.pinned : "auto";
    select.disabled = state.gameBusy;

    const detected = game.detection.game ? names[game.detection.game] : null;
    const said = DETECTION_WORDS[game.detection.reason] || (() => game.detection.reason);
    const gap = pinnedGameGap(game);
    if (game.mode === "pinned") {
      const parts = [`pinned to ${names[game.pinned]}`];
      if (gap) parts.push(gap);
      if (game.disagrees) parts.push(said(detected));
      mode.textContent = parts.join(" — ");
      mode.className = (gap || game.disagrees) ? "game-mode game-disagrees" : "game-mode";
    } else if (game.active) {
      mode.textContent = `following detection — ${names[game.active.id]}`;
      mode.className = "game-mode";
    } else {
      mode.textContent = `${said(detected)} — pick a game to start`;
      mode.className = "game-mode game-disagrees";
    }
  }

  /* An unsupported panel keeps its tab and states its reason. Removing the tab would
     make the dashboard's shape depend on the game in a way the player cannot ask about;
     an empty panel would read as "nothing is happening", which is a different claim. */
  function capabilityBlock(panel) {
    const caps = state.game && state.game.active ? state.game.active.capabilities : null;
    const notices = B.capabilityNotices(caps, panel);
    if (!notices.length) return null;
    const box = el("div", "cap-absent");
    box.append(el("p", "cap-absent-head", "Not available in this game"));
    notices.forEach((n) => box.append(el("p", "cap-absent-why", n.reason)));
    return box;
  }

  /* Coverage, not a wall of file paths. A required domain failing is a real warning; an
     optional one that the game simply has not written disables its capability and says
     so once. "Empty but readable" and "no rows recent enough" are stated as what they
     are, because neither one means the situation they describe is quiet. */
  function renderCoverage() {
    const lines = coverageLines(state.status && state.status.coverage);
    $("#files").replaceChildren(...lines.map((l) => el("p", l.cls, l.text)));
    const coverage = (state.status && state.status.coverage) || [];
    const empire = coverage.find((c) => c.name === "empire");
    $("#wipe").hidden = !(empire && empire.status === "unavailable");
  }

  /* replaceChildren throws away the focused node. Remember what was focused by its
     stable key and put focus back, so a refresh mid-keyboard-navigation does not dump
     the player back at the top of the document. */
  function withFocusPreserved(paint) {
    const active = document.activeElement;
    const key = active && active !== document.body
      ? (active.id || active.getAttribute("data-focus-key")) : null;
    const scroll = window.scrollY;
    paint();
    if (!key) return;
    if (document.activeElement === active) return;    // survived the repaint
    const restored = document.getElementById(key)
      || document.querySelector(`[data-focus-key="${key}"]`);
    if (restored) {
      restored.focus({ preventScroll: true });
      window.scrollTo({ top: scroll });               // never auto-scroll on a turn update
    }
  }

  function render() {
    withFocusPreserved(paint);
  }

  function paint() {
    const d = state.data;
    if (!d) { renderStatus(); renderGame(); renderCoverage(); return; }
    const ins = visible();
    renderHero(d, ins);
    renderRanks(d);
    renderStatus();
    renderGame();
    renderCoverage();
    renderBrief();

    const byAdvisor = (a) => ins.filter((i) => i.advisor === a);
    const actionable = ins.filter((i) => i.severity !== "INFO").length;
    const hidden = (state.hiddenInsights || 0) + (state.insights.length - ins.length);
    $("#insight-summary").textContent = `${ins.length} evidence-backed call${ins.length === 1 ? "" : "s"} `
      + `for turn ${d.complete_through_turn} · ${actionable} actionable`
      + (hidden ? ` · ${hidden} intercept${hidden === 1 ? "" : "s"} hidden` : "");
    $("#checklist-stream").replaceChildren(stream(ins, undefined));
    renderCommentary();

    /* The toggle gates table content as well as cards: with Oracle off the
       AI-internal columns are dropped outright, not blanked — and the response does
       not carry those fields either. */
    const threatCols = seen() ? [...THREATS_FAIR_COLUMNS, ...THREATS_ORACLE_COLUMNS] : THREATS_FAIR_COLUMNS;
    $("#threats-table").replaceChildren(
      table(threatCols, d.threats.map((t) => threatCols.map((c) => c.cell(t)))),
      ...(seen() ? [] : [withheld()]));
    $("#threats-cards").replaceChildren(stream(byAdvisor("threat"), "threat"));

    /* One order for both tables on this tab: the server's PATH_STATS order, which
       is the order the leaderboards arrive in. */
    const paths = Object.keys(d.leaderboards);
    const pathCols = paths.map((p) => ({ label: PATH_LABEL[p] || p }));

    // Victory paths gates ONLY the strategy-pursuit table: showing Civ VI's era/posture
    // strategy rows under "victory path" column headers would misrepresent data the log
    // does not claim. The output-proxy leaderboards and the advice stream are yield-based
    // and real for any game, so they are never suppressed by this capability.
    const victoryAbsent = capabilityBlock("victory");
    $("#victory-head").hidden = !seen();
    $("#victory-table").replaceChildren(victoryAbsent ? victoryAbsent : (seen() ? table(
      [{ label: "Rival" }, ...pathCols],
      d.standings.filter((s) => s.kind === "rival" && s.alive).map((s) => [s.name, ...paths.map((p) => {
        const st = s.strategies.find((x) => x.strategy === p);
        if (!st) return { text: "—", cls: "dim" };
        if (!st.following) return { text: st.status, cls: "dim" };
        const span = el("span");
        span.append(document.createTextNode(st.status), el("span", "fig", String(st.weight)));
        return span;
      })])) : withheld()));

    const depth = paths.reduce((n, p) => Math.max(n, d.leaderboards[p].length), 0);
    $("#victory-boards").replaceChildren(table(
      [{ label: "Rank", num: true }, ...pathCols],
      Array.from({ length: depth }, (_, i) => [ordinal(i + 1), ...paths.map((p) => {
        const entry = d.leaderboards[p][i];
        return entry ? named(entry.name, entry.value, entry.id === d.human) : { text: "—", cls: "dim" };
      })])));
    $("#victory-cards").replaceChildren(stream(byAdvisor("victory"), "victory"));

    // Maintenance and happiness back no rendered element on this tab today -- the yield
    // comparison, production queues and rival-production share are all independent of
    // them. A capability gap here is therefore a notice ALONGSIDE real data, never a
    // reason to hide the data: Civ VI's own gold/production/food numbers and its build
    // queue are real and must render regardless of what this tab cannot also show.
    const economyAbsent = capabilityBlock("economy");
    $("#economy-table").replaceChildren(table([
      { label: "Yield" }, { label: "You", num: true }, { label: "Rival median", num: true },
      { label: "You vs median", num: true }, { label: "Best rival's", num: true }, { label: "Best rival" },
    ], d.economy.map((c) => [
      c.label, fmt(c.human), fmt(c.rival_median),
      { text: `${Math.round(c.ratio * 100)}%`, cls: c.ratio < 0.75 ? "behind" : "" },
      fmt(c.leader_value), c.leader_name,
    ])), ...(economyAbsent ? [economyAbsent] : []));

    const turnsCell = (c) => c.item === "" ? dim("idle")
      : c.turns_to_complete === null ? dim("stalled") : c.turns_to_complete;
    const cityName = (key) => key.replace(/^LOC_CITY_NAME_/, "").replace(/_/g, " ").toLowerCase()
      .replace(/\b\w/g, (ch) => ch.toUpperCase());
    const prod = d.production;
    $("#production-table").replaceChildren(prod.human.length
      ? table([{ label: "City" }, { label: "Building" }, { label: "Turns left", num: true }],
        prod.human.map((c) => [cityName(c.city), c.item ? itemName(c.item) : dim("nothing"), turnsCell(c)]))
      : el("p", "empty", d.files["CityBuildQueue.csv"] && d.files["CityBuildQueue.csv"].ok
        ? "No cities yet." : "No production data — CityBuildQueue.csv is not readable yet."));
    $("#rival-production-head").hidden = !seen() || prod.rivals === null;
    $("#rival-production-table").replaceChildren(!seen() || prod.rivals === null ? withheld()
      : table([{ label: "Rival" }, { label: "Cities building military", num: true }, { label: "Share", num: true }],
        prod.rivals.map((r) => [r.name, Math.round((r.military_share || 0) * r.cities.length),
          `${Math.round((r.military_share || 0) * 100)}%`])));

    $("#economy-cards").replaceChildren(stream(byAdvisor("economy"), "economy"));

    renderTactical();

    const feed = el("div", "intel");
    const events = visibleIntel();
    if (!events.length && seen()) feed.append(el("p", "empty", "No events yet."));
    events.forEach((e) => {
      const row = el("div", `intel-row prov-${e.provenance}`);
      row.append(el("span", "intel-turn", String(e.turn)), el("span", "intel-kind", e.kind),
        el("span", "intel-text", e.text));
      if (e.provenance === "oracle") row.append(el("span", "tag", "intercept"));
      feed.append(row);
    });
    $("#intel-feed").replaceChildren(feed, ...(seen() ? [] : [el("p", "oracle-off", INTEL_ORACLE_OFF)]));
  }

  /* ================= the decision brief ================= */

  const APPLICABILITY_WORD = {
    ready: "ready", conditional: "conditional", inspect: "go and look", blocked: "blocked",
  };

  const factsById = () => {
    const map = new Map();
    ((state.decisions && state.decisions.evidence) || []).forEach((f) => map.set(f.id, f));
    return map;
  };
  const guidesById = () => {
    const map = new Map();
    ((state.decisions && state.decisions.guides) || []).forEach((g) => map.set(g.id, g));
    return map;
  };

  function currentIdentity() {
    const context = (state.decisions && state.decisions.context) || {};
    const status = state.status || {};
    return {
      session: status.session, epoch: status.epoch, evidence_mode: status.evidence_mode,
      snapshot_revision: status.revision, turn: status.analysis_turn,
      decision_revision: context.decision_revision,
      context_revision: context.context_revision,
      catalog_revision: context.catalog_revision,
    };
  }

  /* Generated prose may sit beside a decision only when it was written about exactly
     this decision context. Anything else is history and belongs in the dated panel. */
  function explanationFor(entry) {
    const result = state.commentary;
    if (!result || result.status !== "ready" || !result.commentary) return null;
    const identity = result.commentary.identity;
    const ids = entry.insights.map((i) => i.id);
    if (!B.commentaryExplains(identity, currentIdentity(), ids)) return null;
    const rows = (result.commentary.explain || []).filter((x) => ids.indexOf(x.insight_id) !== -1);
    return rows.length ? rows : null;
  }

  /* Acknowledgements and pins live in the server's own record, so they survive a
     restart and are scoped to the sitting they were made in. `localStorage` stays as a
     fallback for when that store cannot be written — the control must still work. */
  const recordEntries = (kind) => ((state.record && state.record.entries) || [])
    .filter((e) => e.kind === kind);
  const storeBroken = () => Boolean(state.record && state.record.error);

  function acknowledged(entry) {
    const print = B.fingerprint(entry);
    if (recordEntries("acknowledged").some((e) => e.subject === entry.id
        && e.fingerprint === print)) return true;
    const session = (state.status && state.status.session) || "";
    return storeBroken() && B.isAcknowledged(state.acks, session, entry);
  }

  function pinned(entry) {
    if (recordEntries("watch").some((e) => e.subject === entry.id)) return true;
    const session = (state.status && state.status.session) || "";
    return storeBroken() && Boolean(state.pins[B.acknowledgementKey(session, entry)]);
  }

  async function writeRecord(kind, entry, on) {
    const status = state.status || {};
    if (storeBroken()) {                       // keep working without the server store
      const key = B.acknowledgementKey(status.session || "", entry);
      const bucket = kind === "acknowledged" ? state.acks : state.pins;
      if (on) bucket[key] = kind === "acknowledged" ? B.fingerprint(entry) : true;
      else delete bucket[key];
      persist(kind === "acknowledged" ? "civ7.acks" : "civ7.pins", bucket);
      render();
      return;
    }
    if (on) {
      await fetch("/api/record", {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ kind, subject: entry.id, turn: status.analysis_turn,
                               fingerprint: B.fingerprint(entry) }),
      });
    } else {
      const held = recordEntries(kind).find((e) => e.subject === entry.id);
      if (held) await fetch(`/api/record/${encodeURIComponent(held.id)}`, { method: "DELETE" });
    }
    await refresh();
  }

  function renderBrief() {
    const cards = (state.decisions && state.decisions.cards) || [];
    const entries = B.groupDecisions(visible(), cards);
    const session = (state.status && state.status.session) || "";
    const live = entries.filter((e) => pinned(e) || !acknowledged(e));
    const { critical, top, overflow } = B.splitBrief(live);

    $("#brief-critical").replaceChildren(...critical.map((e) => decisionCard(e, session)));
    $("#brief-cards").replaceChildren(...top.map((e) => decisionCard(e, session)));

    const wrap = $("#brief-overflow"), rest = $("#brief-rest"), more = $("#brief-more");
    wrap.hidden = overflow.length === 0;
    if (overflow.length) {
      more.textContent = state.briefOpen
        ? `Hide ${overflow.length} lower-priority item${overflow.length === 1 ? "" : "s"}`
        : `${overflow.length} more lower-priority item${overflow.length === 1 ? "" : "s"}`;
      more.setAttribute("aria-expanded", state.briefOpen ? "true" : "false");
      rest.hidden = !state.briefOpen;
      rest.replaceChildren(...overflow.map((e) => decisionCard(e, session)));
    } else {
      rest.replaceChildren();
    }

    renderChanges();
    renderAssociation();
    announce(critical.length);
    const hidden = entries.length - live.length;
    const parts = [];
    if (critical.length) parts.push(`${critical.length} critical`);
    parts.push(`${live.length} to weigh`);
    if (hidden) parts.push(`${hidden} acknowledged`);
    $("#brief-count").textContent = parts.join(" · ");
    const empty = $("#brief-empty");
    empty.hidden = live.length > 0;
    empty.textContent = entries.length
      ? "Everything here is acknowledged. It comes back if its evidence or severity changes."
      : (state.insights.length || state.hiddenInsights
        ? "Nothing above the noticing threshold this turn."
        : "Nothing to report yet.");
  }

  const CHANGE_WORD = {
    newly_observed: "new", worsening: "worse", improving: "better",
    unchanged: "unchanged", no_longer_observed: "no longer reported",
    resolved: "resolved", not_comparable: "not comparable",
  };
  /* States worth opening the panel for. "Unchanged" is recorded but not counted: a list
     of things that did not move is not news. */
  const NOTABLE = ["worsening", "newly_observed", "resolved", "improving",
                   "no_longer_observed", "not_comparable"];

  function renderChanges() {
    const panel = $("#changes-panel"), body = $("#changes-body");
    const data = state.changes;
    if (!data) { panel.hidden = true; return; }
    panel.hidden = false;
    if (!data.comparable) {
      $("#changes-summary").textContent = "Since last turn — nothing to compare yet";
      body.replaceChildren(el("p", "refine-note", data.reason));
      return;
    }
    const notable = (data.changes || []).filter((c) => NOTABLE.includes(c.state));
    const counts = NOTABLE
      .map((state_) => [state_, notable.filter((c) => c.state === state_).length])
      .filter(([, n]) => n > 0)
      .map(([state_, n]) => `${n} ${CHANGE_WORD[state_]}`);
    $("#changes-summary").textContent = `Since turn ${data.previous_turn} — `
      + (counts.length ? counts.join(", ") : "nothing observed moved");

    const nodes = [];
    NOTABLE.forEach((wanted) => {
      const rows = notable.filter((c) => c.state === wanted);
      if (!rows.length) return;
      nodes.push(el("h4", null, `${CHANGE_WORD[wanted][0].toUpperCase()}`
        + `${CHANGE_WORD[wanted].slice(1)}`));
      const list = el("ul", "decision-unknowns");
      rows.forEach((c) => {
        const item = el("li");
        item.append(el("strong", null, c.label), document.createTextNode(` — ${c.detail}`));
        list.append(item);
      });
      nodes.push(list);
    });
    const turns = data.observed_turns || [];
    if (turns.length > 1) {
      nodes.push(el("p", "refine-note",
        `Turns recorded this session: ${turns.join(", ")}. Gaps are turns the advisor `
        + "did not see, not turns where nothing happened."));
    }
    const retro = data.retrospective || {};
    if ((retro.acknowledged || []).length) {
      nodes.push(el("h4", null, "Alongside what you acknowledged"));
      const list = el("ul", "decision-unknowns");
      retro.acknowledged.forEach((subject) => list.append(el("li", null, subject)));
      nodes.push(list, el("p", "guide-note", retro.caveat));
    }
    body.replaceChildren(...nodes);
  }

  /* Entries from another sitting are offered, never applied: after a reload the advisor
     cannot tell whether this is the same line of play. */
  function renderAssociation() {
    const node = $("#association");
    const pending = (state.record && state.record.pending) || [];
    if (!pending.length) { node.hidden = true; node.replaceChildren(); return; }
    node.hidden = false;
    const group = pending[0];
    node.replaceChildren(document.createTextNode(group.reason + " "));
    const adopt = button("These belong to this game", "associate", async () => {
      await fetch("/api/record/associate", {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ session: group.session, epoch: group.epoch }),
      });
      await refresh();
    });
    const drop = button("Discard them", "discard", async () => {
      await fetch("/api/record/associate", {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ session: group.session, epoch: group.epoch, discard: true }),
      });
      await refresh();
    });
    node.append(adopt, document.createTextNode(" "), drop);
  }

  $("#brief-more").addEventListener("click", () => {
    state.briefOpen = !state.briefOpen;
    render();
    $("#brief-more").focus({ preventScroll: true });
  });

  function decisionCard(entry, session) {
    const key = B.acknowledgementKey(session, entry);
    const node = el("article", `decision sev-${entry.severity.toLowerCase()}`
      + (acknowledged(entry) ? " acknowledged" : ""));
    node.dataset.decision = entry.id;

    const head = el("div", "decision-head");
    head.append(el("h3", "decision-subject", entry.subject),
      el("span", "decision-severity", entry.severity));
    node.append(head);

    const card = entry.card;
    const action = card && card.preferred;
    if (action) {
      const line = el("p", "decision-action");
      line.append(document.createTextNode(action.title + " "),
        el("span", "applicability", APPLICABILITY_WORD[action.applicability] || action.applicability));
      node.append(line, el("p", "decision-why", action.why_now));
    } else if (entry.insights.length) {
      const worst = entry.insights.reduce((best, i) =>
        B.SEVERITY_ORDER[i.severity] > B.SEVERITY_ORDER[best.severity] ? i : best, entry.insights[0]);
      node.append(el("p", "decision-action", worst.recommendation),
        el("p", "decision-why", worst.why));
    }
    if (card) {
      node.append(el("p", "decision-reason", card.priority_reason));
      if (card.observed_turns && card.observed_turns.length) {
        const turns = card.observed_turns;
        node.append(el("p", "decision-dates", turns.length === 1
          ? `Evidence observed on turn ${turns[0]}.`
          : `Evidence observed on turns ${turns[0]}–${turns[turns.length - 1]}.`));
      }
    }
    if (card && (card.also_behind || []).length) {
      const listed = card.also_behind
        .map((row) => `${row.label} at ${Math.round(row.ratio * 100)}%`).join(", ");
      node.append(el("p", "decision-dates",
        `The same inspection also covers ${listed}, which trail the field here too.`));
    }
    if (entry.insights.length > 1) {
      node.append(el("p", "decision-dates",
        `${entry.insights.length} warnings about this subject are grouped here; each is `
        + "listed in full on its own tab."));
    }

    node.append(controls(entry, key, node));
    if (state.expanded[entry.id]) node.append(detail(entry));
    return node;
  }

  function controls(entry, key, node) {
    const row = el("div", "decision-controls");
    const open = Boolean(state.expanded[entry.id]);

    const detailButton = button(`Why this? · How to do it`, `detail:${entry.id}`, () => {
      state.expanded[entry.id] = !open;
      render();
      focusKey(`detail:${entry.id}`);
    });
    detailButton.setAttribute("aria-expanded", open ? "true" : "false");
    row.append(detailButton);

    const evidenceIds = collectEvidence(entry);
    if (evidenceIds.length) {
      row.append(button(`Evidence (${evidenceIds.length})`, `evidence:${entry.id}`,
        () => openDrawer(entry, `evidence:${entry.id}`)));
    }
    if (entry.card && entry.card.subject.indexOf(" in ") !== -1) {
      row.append(button("Open economy", `goto:${entry.id}`, () => {
        selectTab(tabs.find((b) => b.dataset.tab === "economy"));
        focusKey(`goto:${entry.id}`);
      }));
    }

    const isAcknowledged = acknowledged(entry);
    const ack = button(isAcknowledged ? "Acknowledged" : "Acknowledge", `ack:${entry.id}`,
      () => writeRecord("acknowledged", entry, !isAcknowledged));
    ack.setAttribute("aria-pressed", isAcknowledged ? "true" : "false");
    ack.title = "Records that you have seen this. It is not an action in the game, and it "
      + "comes back if the evidence or severity changes.";
    row.append(ack);

    const isPinned = pinned(entry);
    const pin = button(isPinned ? "Pinned" : "Pin", `pin:${entry.id}`,
      () => writeRecord("watch", entry, !isPinned));
    pin.setAttribute("aria-pressed", isPinned ? "true" : "false");
    pin.title = "Keeps this in view even once acknowledged.";
    row.append(pin);
    return row;
  }

  function button(label, focusKeyValue, onClick) {
    const b = el("button", null, label);
    b.type = "button";
    b.dataset.focusKey = focusKeyValue;
    b.addEventListener("click", onClick);
    return b;
  }

  function focusKey(value) {
    const node = document.querySelector(`[data-focus-key="${value}"]`);
    if (node) node.focus({ preventScroll: true });
  }

  function collectEvidence(entry) {
    const ids = [];
    if (entry.card) {
      (entry.card.evidence_ids || []).forEach((i) => ids.push(i));
      (entry.card.preferred ? [entry.card.preferred] : [])
        .concat(entry.card.alternatives || [])
        .forEach((c) => (c.evidence_ids || []).forEach((i) => ids.push(i)));
    }
    const facts = factsById();
    return Array.from(new Set(ids)).filter((i) => facts.has(i));
  }

  /* "Why this?" and "How to do it", inline beside the action rather than behind a long
     scroll. Steps come from the reviewed guides the server resolved; no URL is ever
     produced here or by the model. */
  function detail(entry) {
    const wrap = el("div", "decision-detail");
    const card = entry.card;
    const guides = guidesById();

    if (card) {
      (card.preferred ? [card.preferred] : []).concat(card.alternatives || [])
        .forEach((candidate, index) => {
          wrap.append(el("h4", null, index === 0 ? "How to do it" : `Alternative: ${candidate.title}`));
          if (index > 0) wrap.append(el("p", "decision-why", candidate.why_now));
          const steps = el("ol", "decision-steps");
          (candidate.steps || []).forEach((step) => steps.append(el("li", null, step)));
          wrap.append(steps);
          (candidate.prerequisites || []).forEach((p) => {
            wrap.append(el("p", `prereq prereq-${p.state}`,
              p.state === "met" ? `Confirmed: ${p.name}.`
                : p.state === "unmet" ? `Not met: ${p.name}.`
                  : `Unknown, so not assumed: ${p.name}.`));
          });
          (candidate.trade_offs || []).forEach((t) => wrap.append(el("p", "decision-why", t)));
          if ((candidate.unknowns || []).length) {
            const list = el("ul", "decision-unknowns");
            candidate.unknowns.forEach((u) => list.append(el("li", null, u)));
            wrap.append(list);
          }
          wrap.append(guideLinks(candidate.guide_ids || [], guides));
        });
      if ((card.unknowns || []).length) {
        wrap.append(el("h4", null, "What is not known"));
        const list = el("ul", "decision-unknowns");
        card.unknowns.forEach((u) => list.append(el("li", null, u)));
        wrap.append(list);
      }
      /* Offer the panel only where a named build is actually possible: the card must be
         about a settlement, and the catalog must document a build for that family. */
      if (card.id.split(".").length > 2 && !card.id.endsWith(".unobserved")
          && refinableItems(card).length) {
        wrap.append(refinePanel(card));
      }
    } else {
      wrap.append(el("h4", null, "Why this?"));
      entry.insights.forEach((insight) => {
        const block = el("div", "commentary-item");
        block.append(el("p", "insight-rec", insight.recommendation),
          el("p", "insight-why", insight.why));
        wrap.append(block);
      });
      wrap.append(el("p", "guide-note",
        "No reviewed guide covers this family yet, so no steps are offered here. The "
        + "observation above stands on its own."));
    }

    if (card) wrap.append(questionPanel(card));

    const explanation = explanationFor(entry);
    if (explanation) {
      const block = el("div", "generated");
      block.append(el("p", "generated-label",
        "Generated interpretation — written about this exact decision context"));
      explanation.forEach((row) => block.append(el("p", null, row.text)));
      wrap.append(block);
    }
    return wrap;
  }

  /* ================= questions about one decision ================= */

  const QUESTIONS = [
    ["why", "Why this?"],
    ["inspect", "What should I inspect?"],
    ["what_changes", "What would change this call?"],
  ];

  function questionPanel(card) {
    const wrap = el("div", "questions");
    wrap.append(el("h4", null, "Ask about this decision"));
    const row = el("div", "decision-controls");
    QUESTIONS.forEach(([kind, label]) => {
      const b = button(label, `ask:${kind}:${card.id}`, () => ask(card, kind));
      row.append(b);
    });
    wrap.append(row);

    const form = el("form", "challenge");
    const field = el("label", null);
    field.append(el("span", null, "Challenge this: say what you mean to do instead"));
    const input = el("input");
    input.type = "text";
    input.name = "challenge";
    input.maxLength = 400;
    input.dataset.focusKey = `challenge:${card.id}`;
    input.value = (state.challengeText || {})[card.id] || "";
    field.append(input);
    form.append(field);
    const send = el("button", null, "Weigh it");
    send.type = "submit";
    send.dataset.focusKey = `challenge-send:${card.id}`;
    form.append(send);
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      state.challengeText = Object.assign({}, state.challengeText,
        { [card.id]: input.value });
      ask(card, "challenge", input.value);
    });
    wrap.append(form);
    wrap.append(el("p", "refine-note",
      "Your words are recorded as your intention, never as something the advisor "
      + "observed happening."));

    const held = (state.answers || {})[`${card.id}`];
    if (held) wrap.append(answerBlock(held));
    return wrap;
  }

  async function ask(card, kind, text) {
    const status = state.status || {};
    state.answers = Object.assign({}, state.answers, {
      [card.id]: { kind, status: "asking", answer: null },
    });
    render();
    try {
      const response = await fetch("/api/question", {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({
          kind, decision_id: card.id, oracle: state.showOracle ? 1 : 0, text: text || "",
        }),
      });
      const body = await response.json();
      if (!response.ok) {
        state.answers[card.id] = { kind, status: "error",
          answer: { text: body.detail || "That could not be asked.", unknowns: [] } };
      } else {
        state.answers[card.id] = body;
      }
    } catch (_) {
      state.answers[card.id] = { kind, status: "error",
        answer: { text: "The advisor could not be reached.", unknowns: [] } };
    }
    render();
    /* A "generating" answer means a local model is working on prose to replace the
       deterministic answer already on screen. Poll for it; nothing waits on it. */
    if (state.answers[card.id].status === "generating") {
      setTimeout(() => ask(card, kind, text), 2500);
    }
  }

  function answerBlock(held) {
    const wrap = el("div", "answer");
    const answer = held.answer || {};
    const label = held.status === "asking" ? "Asking…"
      : held.status === "generating" ? "Structured answer — the local model is writing one"
        : held.status === "ready" ? "Generated interpretation"
          : held.status === "unsupported" ? "This cannot be answered"
            : held.status === "error" ? "Could not ask" : "Structured answer";
    wrap.append(el("p", "generated-label", label));
    if (answer.text) wrap.append(el("p", null, answer.text));
    if ((answer.unknowns || []).length) {
      const list = el("ul", "decision-unknowns");
      answer.unknowns.forEach((u) => list.append(el("li", null, u)));
      wrap.append(list);
    }
    if (held.status === "ready") {
      wrap.append(el("p", "guide-note",
        "Written by the local model from this decision's own facts. It cites them, which "
        + "is not the same as being verified: what is verified is the evidence itself."));
    } else if (answer.generated === false && held.status !== "unsupported") {
      wrap.append(el("p", "guide-note",
        "Assembled from the structured decision data, not written by a model."));
    }
    return wrap;
  }

  function guideLinks(ids, guides) {
    const row = el("div");
    const links = el("p", "guide-links");
    const notes = [];
    ids.forEach((id) => {
      const guide = guides.get(id);
      if (!guide) return;                       // the server resolves these; never invent one
      const a = el("a", null, `Read: ${guide.title}`);
      a.href = guide.url;
      a.target = "_blank";
      a.rel = "noopener noreferrer";            // the dashboard stays put
      a.title = `${guide.publisher}, reviewed ${guide.reviewed_at}`;
      links.append(a);
      if (guide.supported_rulesets && guide.supported_rulesets.length) {
        notes.push(`${guide.title}: describes ${guide.supported_rulesets.join(", ")}; `
          + "the installed version is not recorded anywhere we can read.");
      } else {
        notes.push(`${guide.title}: reviewed ${guide.reviewed_at} for navigation only — `
          + "no figure from it is used.");
      }
    });
    if (links.childNodes.length) row.append(links);
    notes.forEach((n) => row.append(el("p", "guide-note", n)));
    return row;
  }

  /* ================= the evidence drawer ================= */

  const drawer = $("#evidence-drawer");

  function openDrawer(entry, opener) {
    const facts = factsById();
    const body = $("#drawer-body");
    const nodes = [el("p", "fact-meta", `${entry.subject} — every observation this rests on, `
      + "with the turn it came from.")];
    collectEvidence(entry).forEach((id) => nodes.push(factNode(facts.get(id), facts)));
    if (entry.card) {
      if ((entry.card.unknowns || []).length) {
        nodes.push(el("h3", "map-subhead", "Not known"));
        const list = el("ul", "decision-unknowns");
        entry.card.unknowns.forEach((u) => list.append(el("li", null, u)));
        nodes.push(list);
      }
      nodes.push(el("h3", "map-subhead", "Why this one is first"),
        el("p", "fact-note", entry.card.priority_reason));
    }
    const coverage = (state.status && state.status.coverage) || [];
    const gaps = coverageLines(coverage);
    if (gaps.length) {
      nodes.push(el("h3", "map-subhead", "Source coverage"));
      gaps.forEach((line) => nodes.push(el("p", "fact-meta", line.text)));
    }
    const explanation = explanationFor(entry);
    if (explanation) {
      nodes.push(el("h3", "map-subhead", "Generated interpretation"));
      nodes.push(el("p", "fact-meta",
        "Written by the local model about this decision context. It is an interpretation "
        + "of the facts above, not one of them."));
      explanation.forEach((row) => nodes.push(el("p", "fact-note", row.text)));
    }
    body.replaceChildren(...nodes);
    state.drawerOpener = opener;
    if (typeof drawer.showModal === "function") drawer.showModal();
    else drawer.setAttribute("open", "open");
  }

  function factNode(fact, facts) {
    const node = el("div", "fact");
    const label = el("p", "fact-label");
    label.append(document.createTextNode(fact.label + " "),
      el("span", "fact-kind", fact.kind === "player_report" ? "you told us"
        : fact.kind === "derived" ? "computed" : fact.kind === "rule" ? "advisor rule" : "log"));
    if (fact.provenance === "oracle") label.append(document.createTextNode(" "), el("span", "tag", "intercept"));
    node.append(label);
    const value = fact.value === null || fact.value === undefined ? "—" : String(fact.value);
    node.append(el("p", "fact-value", fact.unit ? `${value} ${fact.unit}` : value));
    const meta = [];
    if (fact.observed_turn !== null && fact.observed_turn !== undefined) {
      meta.push(`observed turn ${fact.observed_turn}`
        + (fact.age ? ` (${fact.age} turn${fact.age === 1 ? "" : "s"} ago)` : ""));
    } else {
      meta.push("no turn recorded");
    }
    if (fact.source_file) meta.push(`from ${fact.source_file}`);
    if (fact.reported_at) meta.push(`entered ${fact.reported_at}`);
    node.append(el("p", "fact-meta", meta.join(" · ")));
    if (fact.note) node.append(el("p", "fact-note", fact.note));
    if ((fact.contributing || []).length) {
      const names = fact.contributing
        .map((id) => (facts.get(id) || {}).label || null)
        .filter(Boolean);
      if (names.length) {
        node.append(el("p", "fact-meta", `Computed from: ${names.join("; ")}.`));
      }
    }
    return node;
  }

  function closeDrawer() {
    if (typeof drawer.close === "function") drawer.close();
    else drawer.removeAttribute("open");
    if (state.drawerOpener) focusKey(state.drawerOpener);   // focus returns to the opener
    state.drawerOpener = null;
  }

  $("#drawer-close").addEventListener("click", closeDrawer);
  drawer.addEventListener("close", () => {
    if (state.drawerOpener) { focusKey(state.drawerOpener); state.drawerOpener = null; }
  });

  /* ================= the refinement panel ================= */

  /* The panel's fields. The yield label comes from the card, so one panel serves any
     family the catalog documents specific buildings for. */
  const REFINE_METRICS = [
    ["completion_turns", "Turns to complete", "turns"],
    ["yield_delta", "added", "per turn"],
    ["gold_upkeep", "Gold upkeep", "gold per turn"],
    ["happiness_cost", "Local happiness cost", "happiness per turn"],
  ];

  function refinePanel(card) {
    const family = card.id.split(".")[1];
    const city = card.id.split(".").slice(2).join(".");
    const context = (state.decisions && state.decisions.context) || {};
    const settlement = (context.settlements || []).find((s) => s.city === city);
    const panel = el("details", "refine");
    panel.open = Boolean(state.refineStatus[city]);
    panel.append(el("summary", null, "Refine this recommendation"));
    panel.append(el("p", "refine-note",
      "Read these off the game's own preview for this settlement and enter them here. "
      + "They are recorded as your report, dated to the turn you read them, and are "
      + "discarded if this game is reloaded or this settlement's queue changes."));

    const form = el("form");
    form.dataset.focusKey = `refine:${city}`;
    const options = el("label", null);
    options.append(el("span", null,
      `${family} options this settlement offers (comma separated, blank if none)`));
    const optionsInput = el("input");
    optionsInput.type = "text";
    optionsInput.name = "available_options";
    optionsInput.placeholder = "BUILDING_MONUMENT, BUILDING_AMPHITHEATER";
    options.append(optionsInput);
    form.append(options);

    const objective = el("label", null);
    objective.append(el("span", null, "What are you optimising for?"));
    const select = el("select");
    select.name = "objective";
    [["", "not stated"], ["soonest_culture", `the next ${family} increase soonest`],
      ["largest_culture", `the largest eventual ${family} increase`]].forEach(([value, text]) => {
      const option = el("option", null, text);
      option.value = value;
      select.append(option);
    });
    objective.append(select);
    form.append(objective);

    const grid = el("div", "refine-grid");
    const items = refinableItems(card);
    items.forEach((item) => {
      REFINE_METRICS.forEach(([metric, label, unit]) => {
        const field = el("label", null);
        field.append(el("span", null, metric === "yield_delta"
          ? `${itemName(item)} — ${family} ${label}` : `${itemName(item)} — ${label}`));
        const input = el("input");
        input.type = "number";
        input.step = "any";
        input.name = `preview.${item}.${metric}`;
        input.dataset.unit = metric === "yield_delta" ? `${family} ${unit}` : unit;
        field.append(input);
        grid.append(field);
      });
    });
    form.append(grid);

    const submit = el("button", null, "Record these figures");
    submit.type = "submit";
    submit.dataset.focusKey = `refine-submit:${city}`;
    const clear = el("button", null, "Clear my figures");
    clear.type = "button";
    clear.dataset.focusKey = `refine-clear:${city}`;
    const row = el("div", "decision-controls");
    row.append(submit, clear);
    form.append(row);

    const status = el("p", "refine-status");
    const held = state.refineStatus[city];
    if (held) { status.textContent = held.text; if (held.conflict) status.classList.add("conflict"); }
    form.append(status);

    form.addEventListener("submit", (event) => {
      event.preventDefault();
      submitRefinement(city, settlement, form);
    });
    clear.addEventListener("click", () => clearRefinement(city));
    panel.append(form);
    return panel;
  }

  /* Which items this card's panel may ask about: exactly the ones the server sent a
     reviewed item guide for. Never a build we invented a name for. */
  function refinableItems(card) {
    const family = card.id.split(".")[1];
    return Array.from(new Set(
      ((state.decisions && state.decisions.guides) || [])
        .filter((g) => g.id.indexOf("guide.building.") === 0
          && (g.yields || []).indexOf(family) !== -1)
        .flatMap((g) => g.item_keys || [])
    ));
  }

  function refinementReports(city, settlement, form) {
    const status = state.status || {};
    const turn = settlement ? settlement.observed_turn : status.analysis_turn;
    const now = new Date().toISOString();
    const out = [];
    const push = (label, value, unit) => out.push({
      id: `report.${city}.${label}`, subject: city, label, value, unit,
      observed_turn: turn, session: status.session, reported_at: now,
      epoch: status.epoch,
    });
    const options = form.elements.available_options.value.trim();
    if (options) push("available_options", options.split(/[,\s]+/).join(","), null);
    const objective = form.elements.objective.value;
    if (objective) push("objective", objective, null);
    Array.from(form.querySelectorAll('input[type="number"]')).forEach((input) => {
      if (input.value === "") return;           // missing stays missing, never zero
      push(input.name, Number(input.value), input.dataset.unit);
    });
    return out;
  }

  async function submitRefinement(city, settlement, form) {
    const reports = refinementReports(city, settlement, form);
    if (!reports.length) {
      state.refineStatus[city] = { text: "Nothing entered yet." };
      render();
      return;
    }
    const context = (state.decisions && state.decisions.context) || {};
    let accepted = 0;
    for (const report of reports) {
      const response = await fetch("/api/context", {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify(Object.assign({}, report, {
          base_revision: context.context_revision,
          dependencies: settlement
            ? { queue: `${settlement.item}@${settlement.observed_turn}` } : {},
        })),
      });
      if (response.status === 409) {
        const conflict = await response.json();
        state.refineStatus[city] = { text: conflict.detail, conflict: true };
        await refresh();
        return;
      }
      if (!response.ok) {
        state.refineStatus[city] = { text: "That could not be recorded.", conflict: true };
        render();
        return;
      }
      accepted += 1;
    }
    state.refineStatus[city] = { text: `Recorded ${accepted} figure${accepted === 1 ? "" : "s"}.` };
    await refresh();
  }

  async function clearRefinement(city) {
    const context = (state.decisions && state.decisions.context) || {};
    const mine = (context.reports || []).filter((r) => r.subject === city);
    for (const report of mine) {
      await fetch(`/api/context/${encodeURIComponent(report.id)}`, { method: "DELETE" });
    }
    state.refineStatus[city] = { text: `Cleared ${mine.length} figure${mine.length === 1 ? "" : "s"}.` };
    await refresh();
  }

  /* ================= the tactical view ================= */

  const T = window.Civ7Tactical;

  function renderTactical() {
    const host = $("#tactical-map");
    const data = state.tactical;
    if (!seen()) { host.replaceChildren(withheld()); return; }
    if (!data || !data.available) {
      host.replaceChildren(el("p", "empty", "No tactical positions are available yet."));
      return;
    }
    const available = T.views(data);
    if (!available.length) {
      host.replaceChildren(el("p", "empty", "No tactical positions are available yet."));
      return;
    }
    if (!available.some((v) => v.id === state.tacticalView)) {
      /* Default to the busiest frontier rather than the first, so the view that opens is
         the one with something in it. */
      const busiest = available
        .filter((v) => v.kind === "cluster")
        .sort((a, b) => b.count - a.count)[0];
      state.tacticalView = (busiest || available[available.length - 1]).id;
    }
    const view = available.find((v) => v.id === state.tacticalView);
    const content = T.contents(data, state.tacticalView);

    host.replaceChildren(
      viewPicker(available, view),
      coverageSummary(data, view, content),
      frontierMap(data, content),
      el("p", "map-legend", "Hexes: known city area · Brass: your units · Numbered red: "
        + "rival positions · Rings: recorded attack objectives"),
      ...contactSection(content),
      ...promotionSection(data),
    );
  }

  function viewPicker(available, current) {
    const wrap = el("div", "view-picker");
    wrap.setAttribute("role", "tablist");
    wrap.setAttribute("aria-label", "Tactical views");
    available.forEach((view) => {
      const on = view.id === current.id;
      const b = el("button");
      b.type = "button";
      b.dataset.focusKey = `view:${view.id}`;
      b.setAttribute("role", "tab");
      b.setAttribute("aria-selected", on ? "true" : "false");
      b.className = on ? "active" : "";
      b.append(el("span", "view-label", view.label), el("span", "view-detail", view.detail));
      b.addEventListener("click", () => {
        state.tacticalView = view.id;
        state.contactPage = 0;
        state.selectedContact = null;
        render();
        focusKey(`view:${view.id}`);
      });
      wrap.append(b);
    });
    return wrap;
  }

  function coverageSummary(data, view, content) {
    const wrap = el("div");
    const stats = el("div", "map-stats");
    const rows = [
      [content.tiles.length || (data.city_tiles || []).length, "known city-area tiles"],
      [content.contacts.length, "positions in this view"],
      [(data.enemy_units || []).length, "recorded positions in all"],
      [content.units.length, "of your units here"],
    ];
    rows.forEach(([figure, label]) => {
      const stat = el("span", "map-stat");
      stat.append(el("strong", null, String(figure)), document.createTextNode(` ${label}`));
      stats.append(stat);
    });
    wrap.append(stats);
    const notes = [];
    if (content.offMap > 0) {
      notes.push(`${content.offMap} recorded position${content.offMap === 1 ? " is" : "s are"} `
        + "outside this view — open All contacts to see every one.");
    }
    if (content.cluster) {
      notes.push(`This area's tiles were last observed on turn ${content.cluster.turn}.`);
    } else if (data.city_tile_turn) {
      notes.push(`City-area tiles were last observed on turn ${data.city_tile_turn}.`);
    }
    notes.push(`Rival positions are kept for ${data.fresh_turns} turns after they are seen. `
      + "Nothing recorded here does not mean nothing is there.");
    const stale = (data.attack_goals || []).filter((g) => g.fresh === false).length;
    if (stale) {
      notes.push(`${stale} recorded attack objective${stale === 1 ? " is" : "s are"} dated: `
        + "no newer plan has been logged either way.");
    }
    notes.forEach((note) => wrap.append(el("p", "map-coverage-note", note)));
    return wrap;
  }

  function frontierMap(data, content) {
    const plots = [...content.tiles, ...content.units, ...content.contacts, ...content.goals]
      .filter((p) => p.x !== null && p.x !== undefined);
    const geometry = T.frame(plots);
    if (!geometry) {
      return el("p", "empty", "Nothing in this view has a recorded position.");
    }
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", geometry.viewBox);
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label",
      `${content.contacts.length} recorded rival positions and ${content.tiles.length} `
      + "known city-area tiles in this view. The table below lists the same contacts and "
      + "is the way to select one.");
    const at = (p) => ({ x: (p.x + (p.y & 1) / 2) * 42, y: p.y * 36 });
    const mark = (kind, p, label, number = null) => {
      const point = at(p);
      let node;
      if (kind === "city") {
        node = document.createElementNS(svg.namespaceURI, "polygon");
        node.setAttribute("points", Array.from({ length: 6 }, (_, i) => {
          const angle = Math.PI / 180 * (60 * i);
          return `${point.x + geometry.tile * Math.cos(angle)},`
            + `${point.y + geometry.tile * Math.sin(angle)}`;
        }).join(" "));
      } else {
        node = document.createElementNS(svg.namespaceURI, "circle");
        node.setAttribute("cx", point.x);
        node.setAttribute("cy", point.y);
        node.setAttribute("r", kind === "goal" ? geometry.marker * 1.3 : geometry.marker);
      }
      node.setAttribute("class", `map-${kind}`
        + (p.key && p.key === state.selectedContact ? " map-selected" : ""));
      node.setAttribute("stroke-width", String(geometry.stroke));
      const title = document.createElementNS(svg.namespaceURI, "title");
      title.textContent = label;
      node.append(title);
      svg.append(node);
      if (number !== null) {
        const text = document.createElementNS(svg.namespaceURI, "text");
        text.setAttribute("class", "map-number");
        text.setAttribute("x", point.x);
        text.setAttribute("y", point.y);
        text.setAttribute("font-size", String(geometry.font));
        text.textContent = String(number);
        svg.append(text);
      }
    };
    const dated = (p) => p.turn === undefined || p.turn === null ? ""
      : ` — observed turn ${p.turn}${p.age ? ` (${p.age} turn${p.age === 1 ? "" : "s"} ago)` : ""}`;
    content.tiles.forEach((p) => mark("city", p, `Known city-area tile ${p.x}:${p.y}${dated(p)}`));
    content.units.forEach((p) => mark("human", p,
      `${itemName(p.unit_type)} — ${p.activity} at ${p.x}:${p.y}${dated(p)}`));
    content.contacts.forEach((p, i) => mark("enemy", p,
      `${p.name} ${itemName(p.unit_type)} — ${itemName(p.activity)} at ${p.x}:${p.y}${dated(p)}`,
      i + 1));
    content.goals.forEach((p) => mark("goal", p,
      `${p.name} attack objective ${p.x}:${p.y}${dated(p)}`
      + (p.fresh === false ? " — dated, no newer plan recorded" : "")));
    return svg;
  }

  function contactSection(content) {
    const nodes = [el("h3", "map-subhead", "Recorded rival positions")];
    if (!content.contacts.length) {
      nodes.push(el("p", "empty",
        "No rival position is recorded in this view. That is what these logs contain, "
        + "not a statement that the area is clear."));
      return nodes;
    }
    const paged = T.page(content.contacts, {
      page: state.contactPage, filter: state.contactFilter,
    });
    nodes.push(contactControls(paged));

    const numbering = new Map(content.contacts.map((c, i) => [c.key, i + 1]));
    const cols = [
      { label: "#" }, { label: "Rival" }, { label: "Unit" },
      { label: "From city area", num: true }, { label: "At" },
      { label: "Last AI activity" }, { label: "Seen", num: true },
    ];
    const rows = paged.rows.map((p) => [
      String(numbering.get(p.key)), p.name, itemName(p.unit_type),
      p.distance_to_city === null || p.distance_to_city === undefined ? dim()
        : `${p.distance_to_city} hex${p.distance_to_city === 1 ? "" : "es"}`,
      `${p.x}:${p.y}`, itemName(p.activity),
      p.age === 0 ? "this turn" : `turn ${p.turn}`,
    ]);
    const wrap = table(cols, rows);
    /* Selection is driven from the table, not the markers: two contacts can share a hex,
       and a shared marker cannot be used to pick between them — nor reached by keyboard. */
    Array.from(wrap.querySelectorAll("tbody tr")).forEach((tr, index) => {
      const contact = paged.rows[index];
      tr.tabIndex = 0;
      tr.dataset.focusKey = `contact:${contact.key}`;
      tr.setAttribute("role", "button");
      tr.setAttribute("aria-pressed", contact.key === state.selectedContact ? "true" : "false");
      if (contact.key === state.selectedContact) tr.classList.add("selected");
      const select = () => {
        state.selectedContact = contact.key === state.selectedContact ? null : contact.key;
        render();
        focusKey(`contact:${contact.key}`);
      };
      tr.addEventListener("click", select);
      tr.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") { event.preventDefault(); select(); }
      });
    });
    nodes.push(wrap);

    const selected = content.contacts.find((c) => c.key === state.selectedContact);
    if (selected) nodes.push(contactDetail(selected));

    const shared = T.coincident(paged.rows);
    if (shared.length) {
      const lines = shared.map((group) => `${group.tile}: `
        + group.contacts.map((c) => `${c.name} ${itemName(c.unit_type)}`).join(", "));
      nodes.push(el("p", "map-coverage-note",
        `Sharing a tile, so one marker covers more than one contact — select them here: ${lines.join(" · ")}`));
    }
    return nodes;
  }

  function contactControls(paged) {
    const row = el("div", "contact-controls");
    const label = el("label", "contact-filter");
    label.append(el("span", "sr-only", "Filter contacts by rival or unit"));
    const input = el("input");
    input.type = "search";
    input.placeholder = "Filter by rival or unit";
    input.value = state.contactFilter || "";
    input.dataset.focusKey = "contact-filter";
    input.addEventListener("input", (event) => {
      state.contactFilter = event.target.value;
      state.contactPage = 0;
      render();
      focusKey("contact-filter");
    });
    label.append(input);
    row.append(label);

    const count = paged.filtered
      ? `${paged.matched} of ${paged.total} contacts match`
      : `${paged.total} contact${paged.total === 1 ? "" : "s"}`;
    row.append(el("span", "contact-count",
      `${count} · page ${paged.page + 1} of ${paged.pages}`));

    if (paged.pages > 1) {
      const step = (delta, text) => {
        const b = el("button", null, text);
        b.type = "button";
        b.dataset.focusKey = `contact-page:${delta}`;
        b.disabled = delta < 0 ? paged.page === 0 : paged.page >= paged.pages - 1;
        b.addEventListener("click", () => {
          state.contactPage = paged.page + delta;
          render();
          focusKey(`contact-page:${delta}`);
        });
        return b;
      };
      row.append(step(-1, "Previous"), step(1, "Next"));
    }
    return row;
  }

  function contactDetail(contact) {
    const wrap = el("div", "contact-detail");
    wrap.append(el("h4", null, `${contact.name}'s ${itemName(contact.unit_type)}`));
    const lines = [
      `Recorded at ${contact.x}:${contact.y} on turn ${contact.turn}`
      + (contact.age ? `, ${contact.age} turn${contact.age === 1 ? "" : "s"} ago.` : "."),
      `Last activity the AI logged: ${itemName(contact.activity)}.`,
    ];
    if (contact.order) lines.push(`Order recorded: ${itemName(contact.order)}.`);
    if (contact.nearest_city_tile) {
      lines.push(`Nearest known city-area tile: `
        + `${contact.nearest_city_tile.x}:${contact.nearest_city_tile.y}, `
        + `${contact.distance_to_city} hex${contact.distance_to_city === 1 ? "" : "es"} away.`);
    }
    lines.push("This is the position the AI planned, not necessarily where the unit ended "
      + "the turn, and it is intercepted rather than something you can see.");
    lines.forEach((line) => wrap.append(el("p", "fact-meta", line)));
    return wrap;
  }

  function promotionSection(data) {
    if (!data.commander_promotions || !data.commander_promotions.length) return [];
    return [
      el("h3", "map-subhead", "Rival commander promotions"),
      table([{ label: "Rival commander" }, { label: "Discipline" }, { label: "Promotion" }],
        data.commander_promotions.map((p) => [
          `${p.name} · ${p.commander}`, itemName(p.discipline), itemName(p.promotion)])),
    ];
  }

  function hexDistance(a, b) {
    const axial = (p) => ({ q: p.x - (p.y - (p.y & 1)) / 2, r: p.y });
    const aa = axial(a), bb = axial(b), dq = aa.q - bb.q, dr = aa.r - bb.r;
    return (Math.abs(dq) + Math.abs(dr) + Math.abs(dq + dr)) / 2;
  }

  /* Waiting states poll; terminal ones do not. "queued" and "generating" are kept
     distinct because they tell the player different things about how long to wait. */
  const WAITING = ["queued", "generating"];

  function renderCommentary() {
    const result = state.commentary;
    const status = $("#commentary-status"), opinion = $("#second-opinion");
    const explain = $("#commentary-explain"), plan = $("#turn-plan"), meta = $("#commentary-meta");
    const detailed = result && result.status === "ready" && result.commentary;
    $("#explain-head").hidden = !detailed; $("#plan-head").hidden = !detailed;
    const dated = $("#commentary-previous");
    if (!detailed) {
      status.replaceChildren(el("p", result && result.status === "error" ? "file-warn" : "empty",
        result ? result.message : "Local commentary is unavailable."));
      opinion.replaceChildren(); explain.replaceChildren(); plan.replaceChildren(); meta.textContent = "";
      /* A previous generation from this same sitting and evidence mode may be offered as
         history while a new one runs. It is labelled with the turn it was written about
         and never presented as an explanation of the advice currently on screen. */
      if (result && result.previous) {
        dated.hidden = false;
        dated.replaceChildren(
          el("h3", "commentary-dated-head", `Earlier commentary · turn ${result.previous.turn}`),
          el("p", "commentary-dated-note",
            "Written about an earlier turn in this session. It does not explain the calls above."),
          el("p", "commentary-dated-text", result.previous.second_opinion));
      } else {
        dated.hidden = true;
        dated.replaceChildren();
      }
      if (result && WAITING.includes(result.status) && state.commentaryTimer === null) {
        state.commentaryTimer = setTimeout(() => { state.commentaryTimer = null; refresh(); }, 2000);
      }
      return;
    }
    dated.hidden = true;
    dated.replaceChildren();
    status.replaceChildren();
    const c = result.commentary, valid = state.insights.map((i) => `[${i.id}]`);
    const paragraph = (text) => {
      const p = el("p"), pieces = text.split(/([.!?]+(?:\s+|$))/);
      for (let i = 0; i < pieces.length; i += 2) {
        const sentence = pieces[i] + (pieces[i + 1] || "");
        if (!sentence) continue;
        p.append(el("span", valid.some((id) => sentence.includes(id))
          ? "commentary-sentence" : "commentary-sentence uncited", sentence));
      }
      return p;
    };
    opinion.replaceChildren(paragraph(c.second_opinion));
    explain.replaceChildren(...c.explain.map((x) => {
      const block = el("div", "commentary-item");
      block.append(el("p", "commentary-cite", x.insight_id), paragraph(x.text)); return block;
    }));
    const ol = el("ol", "turn-plan");
    c.turn_plan.forEach((x) => { const li = el("li"); li.append(document.createTextNode(x.step + " "), el("span", "commentary-cite", x.insight_id)); ol.append(li); });
    plan.replaceChildren(ol);
    meta.textContent = `${c.model} · turn ${c.turn} · prompt ${c.prompt_hash.slice(0, 10)}`;
  }

  function connect() {
    const es = new EventSource("/events");
    es.onopen = () => { state.connected = true; renderStatus(); };
    es.onmessage = (event) => {
      state.viaEvent = true;
      // The stream carries every event as a plain `data:` frame (no SSE `event:`
      // field), so the server's own event.type -- "state_changed" or "game_changed" --
      // lives inside the JSON payload, not on the DOM MessageEvent.
      let payload = null;
      try { payload = JSON.parse(event.data); } catch (_) { /* not JSON; refresh() below still runs */ }
      if (payload && payload.type === "game_changed") {
        // Everything on screen was computed under the previous game. Clear it before
        // the new brief lands rather than leaving one game's advice under another's
        // name for however long the round trip to refresh() takes.
        state.data = null; state.insights = []; state.intel = []; state.decisions = null;
        state.changes = null; state.tactical = null; state.commentary = null;
        render();
      }
      refresh();
    };
    es.onerror = () => {
      es.close();
      state.connected = false;
      renderStatus();
      setTimeout(connect, 2000);
    };
  }

  refresh();
  connect();
  /* Keep "updated 40s ago" honest without refetching: this only repaints the header. */
  setInterval(renderStatus, 5000);
})();
