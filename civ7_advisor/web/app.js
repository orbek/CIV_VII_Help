(() => {
  /* The response and coverage rules live in briefing.js so they can be tested by
     executing them rather than by grepping this file. */
  const { acceptResponse, seen: seenIn, ago: AGO, coverageLines } = window.Civ7Briefing;
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
    connected: false, lastUpdate: null };

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
    state.data = body.state;
    state.insights = body.insights;
    state.hiddenInsights = body.hidden_insights;
    state.intel = body.intel;
    state.tactical = body.tactical;
    state.commentary = body.commentary;
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
    if (!d) { renderStatus(); renderCoverage(); return; }
    const ins = visible();
    renderHero(d, ins);
    renderRanks(d);
    renderStatus();
    renderCoverage();

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

    $("#victory-head").hidden = !seen();
    $("#victory-table").replaceChildren(seen() ? table(
      [{ label: "Rival" }, ...pathCols],
      d.standings.filter((s) => s.kind === "rival" && s.alive).map((s) => [s.name, ...paths.map((p) => {
        const st = s.strategies.find((x) => x.strategy === p);
        if (!st) return { text: "—", cls: "dim" };
        if (!st.following) return { text: st.status, cls: "dim" };
        const span = el("span");
        span.append(document.createTextNode(st.status), el("span", "fig", String(st.weight)));
        return span;
      })])) : withheld());

    const depth = paths.reduce((n, p) => Math.max(n, d.leaderboards[p].length), 0);
    $("#victory-boards").replaceChildren(table(
      [{ label: "Rank", num: true }, ...pathCols],
      Array.from({ length: depth }, (_, i) => [ordinal(i + 1), ...paths.map((p) => {
        const entry = d.leaderboards[p][i];
        return entry ? named(entry.name, entry.value, entry.id === d.human) : { text: "—", cls: "dim" };
      })])));
    $("#victory-cards").replaceChildren(stream(byAdvisor("victory"), "victory"));

    $("#economy-table").replaceChildren(table([
      { label: "Yield" }, { label: "You", num: true }, { label: "Rival median", num: true },
      { label: "You vs median", num: true }, { label: "Best rival's", num: true }, { label: "Best rival" },
    ], d.economy.map((c) => [
      c.label, fmt(c.human), fmt(c.rival_median),
      { text: `${Math.round(c.ratio * 100)}%`, cls: c.ratio < 0.75 ? "behind" : "" },
      fmt(c.leader_value), c.leader_name,
    ])));

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

  function renderTactical() {
    const host = $("#tactical-map");
    const data = state.tactical;
    if (!seen()) { host.replaceChildren(withheld()); return; }
    if (!data || !data.available) {
      host.replaceChildren(el("p", "empty", "No tactical positions are available yet."));
      return;
    }
    const nearLimit = data.map_near_tiles || 8;
    const byDistance = [...data.enemy_units].sort((a, b) =>
      (a.distance_to_city ?? Number.MAX_SAFE_INTEGER) - (b.distance_to_city ?? Number.MAX_SAFE_INTEGER)
      || b.turn - a.turn || a.name.localeCompare(b.name));
    const allNearbyEnemies = byDistance.filter((u) => u.distance_to_city !== null
      && u.distance_to_city <= nearLimit);
    const nearbyEnemies = (data.city_tiles.length ? allNearbyEnemies : byDistance).slice(0, 12);
    const nearestEnemyDistance = (unit) => data.enemy_units.reduce((best, enemy) => {
      const distance = hexDistance(unit, enemy);
      return Math.min(best, distance);
    }, Number.MAX_SAFE_INTEGER);
    const focusedHumans = data.human_units.filter((u) => u.x !== null &&
      (data.city_tiles.some((city) => hexDistance(u, city) <= nearLimit)
        || nearestEnemyDistance(u) <= 4));
    const plots = [...data.city_tiles, ...focusedHumans, ...nearbyEnemies, ...data.attack_goals];
    if (!plots.length) { host.replaceChildren(el("p", "empty", "No tactical positions are available yet.")); return; }
    const project = (p) => ({ x: (p.x + (p.y & 1) / 2) * 42, y: p.y * 36 });
    const points = plots.map(project);
    const minX = Math.min(...points.map((p) => p.x)) - 24, maxX = Math.max(...points.map((p) => p.x)) + 24;
    const minY = Math.min(...points.map((p) => p.y)) - 24, maxY = Math.max(...points.map((p) => p.y)) + 24;
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", `${minX} ${minY} ${Math.max(maxX - minX, 48)} ${Math.max(maxY - minY, 48)}`);
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", `${nearbyEnemies.length} recent rival unit positions within ${nearLimit} hexes of known human city-area tiles`);
    const mark = (kind, p, label, number = null) => {
      const at = project(p);
      let node;
      if (kind === "city") {
        node = document.createElementNS(svg.namespaceURI, "polygon");
        const corners = Array.from({ length: 6 }, (_, i) => {
          const angle = Math.PI / 180 * (60 * i);
          return `${at.x + 18 * Math.cos(angle)},${at.y + 18 * Math.sin(angle)}`;
        });
        node.setAttribute("points", corners.join(" "));
      } else {
        node = document.createElementNS(svg.namespaceURI, "circle");
      }
      node.setAttribute("class", `map-${kind}`);
      if (kind !== "city") { node.setAttribute("cx", at.x); node.setAttribute("cy", at.y); node.setAttribute("r", kind === "goal" ? 13 : 10); }
      const title = document.createElementNS(svg.namespaceURI, "title"); title.textContent = label; node.append(title); svg.append(node);
      if (number !== null) {
        const textNode = document.createElementNS(svg.namespaceURI, "text");
        textNode.setAttribute("class", "map-number"); textNode.setAttribute("x", at.x);
        textNode.setAttribute("y", at.y); textNode.textContent = String(number); svg.append(textNode);
      }
    };
    /* Date every marker. "Known city area" with no turn on it reads as present-tense
       fact, when it is the newest AI targeting row we have — which can be several turns
       old if no rival has re-targeted since. */
    const dateOf = (p) => p.turn === undefined || p.turn === null ? ""
      : ` — observed turn ${p.turn}${p.age ? ` (${p.age} turn${p.age === 1 ? "" : "s"} ago)` : ""}`;
    data.city_tiles.forEach((p) => mark("city", p, `Known city-area tile ${p.x}:${p.y}${dateOf(p)}`));
    focusedHumans.forEach((p) => mark("human", p, `${itemName(p.unit_type)} — targeted at ${p.x}:${p.y}`));
    nearbyEnemies.forEach((p, i) => mark("enemy", p,
      `${p.name} ${itemName(p.unit_type)} — ${p.activity} at ${p.x}:${p.y}`, i + 1));
    data.attack_goals.forEach((p) => mark("goal", p, `${p.name} attack goal ${p.x}:${p.y}`
      + `${dateOf(p)}${p.fresh === false ? " — dated, no newer plan recorded" : ""}`));
    const stats = el("div", "map-stats");
    [[data.city_tiles.length, "known city-area tiles"], [data.human_units.length, "targeted units"],
      [data.enemy_units.length, "recent rival positions"], [allNearbyEnemies.length, `within ${nearLimit} hexes`]]
      .forEach(([figure, label]) => {
        const stat = el("span", "map-stat");
        stat.append(el("strong", null, String(figure)), document.createTextNode(` ${label}`)); stats.append(stat);
      });
    const omitted = data.enemy_units.length - nearbyEnemies.length;
    let focusCopy;
    if (!data.city_tiles.length) {
      focusCopy = `No city-area tile was detected; the map shows up to 12 positions without city-distance context${omitted ? ` and omits ${omitted} more` : ""}.`;
    } else if (nearbyEnemies.length) {
      focusCopy = `Map focus: up to 12 rival positions within ${nearLimit} hexes of a known city-area tile${omitted ? `; ${omitted} additional recent position${omitted === 1 ? " is" : "s are"} omitted` : ""}.`;
    } else {
      focusCopy = `No recorded rival position is within ${nearLimit} hexes of a known city-area tile; ${omitted} farther-away position${omitted === 1 ? " is" : "s are"} omitted.`;
    }
    const focusNote = el("p", "map-focus-note", focusCopy);
    const legend = el("p", "map-legend", "Hexes: known city area · Brass: your targeted units · Numbered red: rival positions · Rings: attack goals");
    /* Say what the map does not know. No contact recorded means these logs recorded
       none, which is not the same as a frontier being safe. */
    const stale = data.attack_goals.filter((g) => g.fresh === false).length;
    const coverageCopy = [
      data.city_tile_turn ? `City-area tiles last observed on turn ${data.city_tile_turn}.` : null,
      `Rival positions are kept for ${data.fresh_turns} turns after they are seen.`,
      stale ? `${stale} attack goal${stale === 1 ? " is" : "s are"} dated: no newer plan has been recorded either way.` : null,
      "Nothing recorded here does not mean nothing is there.",
    ].filter(Boolean).join(" ");
    const coverageNote = el("p", "map-coverage-note", coverageCopy);
    const contacts = byDistance.length ? table(
      [{ label: "#" }, { label: "Rival" }, { label: "Unit" }, { label: "From city area", num: true },
        { label: "Last AI activity" }, { label: "Turn", num: true }],
      byDistance.slice(0, 12).map((p) => {
        const mapIndex = nearbyEnemies.indexOf(p);
        return [mapIndex >= 0 ? mapIndex + 1 : "off map", p.name, itemName(p.unit_type),
          p.distance_to_city === null ? dim() : `${p.distance_to_city} hex${p.distance_to_city === 1 ? "" : "es"}`,
          itemName(p.activity), p.turn];
      })) : el("p", "empty", "No recent rival positions were recorded.");
    const contactsHead = el("h3", "map-subhead", "Closest recorded rival positions");
    const promotions = data.commander_promotions.length ? table(
      [{ label: "Rival commander" }, { label: "Discipline" }, { label: "Promotion" }],
      data.commander_promotions.map((p) => [`${p.name} · ${p.commander}`, itemName(p.discipline), itemName(p.promotion)])) : null;
    host.replaceChildren(stats, focusNote, svg, legend, coverageNote, contactsHead, contacts,
      ...(promotions ? [el("h3", "map-subhead", "Rival commander promotions"), promotions] : []));
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
    es.onmessage = () => { state.viaEvent = true; refresh(); };
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
