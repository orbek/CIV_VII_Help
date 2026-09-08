(() => {
  const $ = (sel) => document.querySelector(sel);
  const el = (tag, cls, text) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  };
  const fmt = (v, digits = 1) => (v === null || v === undefined) ? "—" : Number(v).toFixed(digits);
  const dim = (text = "—") => ({ text, cls: "dim" });
  const itemName = (key) => key.replace(/^(BUILDING|UNIT|IMPROVEMENT|WONDER)_/, "").replace(/_/g, " ")
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
  const ORACLE_OFF = "Oracle off — AI intent, targeting and legacy paths are hidden.";
  const INTEL_ORACLE_OFF = "Oracle off — fights, deals and diplomacy between rivals are hidden.";

  const state = { data: null, insights: [], intel: [], tactical: null, commentary: null,
    commentaryTimer: null, showOracle: true, shownTurn: null, viaEvent: false };

  try { state.showOracle = localStorage.getItem("civ7.oracle") !== "off"; } catch (_) { /* private mode */ }
  $("#oracle").checked = state.showOracle;
  $("#oracle").addEventListener("change", (e) => {
    state.showOracle = e.target.checked;
    try { localStorage.setItem("civ7.oracle", state.showOracle ? "on" : "off"); } catch (_) { /* ignore */ }
    refresh();
  });

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
    const [s, i, n, t, c] = await Promise.all([
      fetch(`/api/state?oracle=${o}`), fetch("/api/insights"), fetch(`/api/intel?oracle=${o}`),
      fetch(`/api/tactical?oracle=${o}`),
      fetch(`/api/commentary?oracle=${o}`),
    ]);
    if (!s.ok || !i.ok || !n.ok || !t.ok || !c.ok) return;
    state.data = await s.json();
    state.insights = await i.json();
    state.intel = await n.json();
    state.tactical = await t.json();
    state.commentary = await c.json();
    render();
  }

  const visible = () => state.insights.filter((x) => state.showOracle || x.provenance !== "oracle");

  /* Copy for an empty list: say plainly whether the toggle is what emptied it. */
  function emptyText(advisor) {
    const hidden = state.insights.some(
      (i) => (advisor === undefined || i.advisor === advisor) && i.provenance === "oracle");
    if (hidden && !state.showOracle) return "Nothing here with Oracle off.";
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

  function renderFiles(d) {
    $("#files").replaceChildren(...Object.values(d.files).filter((f) => !f.ok).map((f) =>
      el("p", "file-warn", f.error ? `${f.name} is not readable: ${f.error}` : `${f.name} is not readable.`)));
    $("#wipe").hidden = !Object.values(d.files).every((f) => !f.ok);
  }

  function render() {
    const d = state.data;
    if (!d) return;
    const ins = visible();
    renderHero(d, ins);
    renderRanks(d);
    renderFiles(d);

    const byAdvisor = (a) => ins.filter((i) => i.advisor === a);
    $("#checklist-stream").replaceChildren(stream(ins, undefined));
    renderCommentary();

    /* The toggle gates table content as well as cards: with Oracle off the
       AI-internal columns are dropped outright, not blanked. */
    const seen = state.showOracle;
    const threatCols = seen ? [...THREATS_FAIR_COLUMNS, ...THREATS_ORACLE_COLUMNS] : THREATS_FAIR_COLUMNS;
    $("#threats-table").replaceChildren(
      table(threatCols, d.threats.map((t) => threatCols.map((c) => c.cell(t)))),
      ...(seen ? [] : [withheld()]));
    $("#threats-cards").replaceChildren(stream(byAdvisor("threat"), "threat"));

    /* One order for both tables on this tab: the server's PATH_STATS order, which
       is the order the leaderboards arrive in. */
    const paths = Object.keys(d.leaderboards);
    const pathCols = paths.map((p) => ({ label: PATH_LABEL[p] || p }));

    $("#victory-head").hidden = !seen;
    $("#victory-table").replaceChildren(seen ? table(
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
    $("#rival-production-head").hidden = prod.rivals === null;
    $("#rival-production-table").replaceChildren(prod.rivals === null ? withheld()
      : table([{ label: "Rival" }, { label: "Cities building military", num: true }, { label: "Share", num: true }],
        prod.rivals.map((r) => [r.name, Math.round((r.military_share || 0) * r.cities.length),
          `${Math.round((r.military_share || 0) * 100)}%`])));

    $("#economy-cards").replaceChildren(stream(byAdvisor("economy"), "economy"));

    renderTactical();

    const feed = el("div", "intel");
    if (!state.intel.length && seen) feed.append(el("p", "empty", "No events yet."));
    state.intel.forEach((e) => {
      const row = el("div", `intel-row prov-${e.provenance}`);
      row.append(el("span", "intel-turn", String(e.turn)), el("span", "intel-kind", e.kind),
        el("span", "intel-text", e.text));
      if (e.provenance === "oracle") row.append(el("span", "tag", "intercept"));
      feed.append(row);
    });
    $("#intel-feed").replaceChildren(feed, ...(seen ? [] : [el("p", "oracle-off", INTEL_ORACLE_OFF)]));
  }

  function renderTactical() {
    const host = $("#tactical-map");
    const data = state.tactical;
    if (!data || !data.available) {
      host.replaceChildren(state.showOracle
        ? el("p", "empty", "No tactical positions are available yet.") : withheld());
      return;
    }
    const plots = [...data.city_tiles, ...data.human_units.filter((u) => u.x !== null),
      ...data.enemy_units, ...data.attack_goals];
    if (!plots.length) { host.replaceChildren(el("p", "empty", "No tactical positions are available yet.")); return; }
    const project = (p) => ({ x: (p.x + p.y / 2) * 42, y: p.y * 36 });
    const points = plots.map(project);
    const minX = Math.min(...points.map((p) => p.x)) - 24, maxX = Math.max(...points.map((p) => p.x)) + 24;
    const minY = Math.min(...points.map((p) => p.y)) - 24, maxY = Math.max(...points.map((p) => p.y)) + 24;
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", `${minX} ${minY} ${Math.max(maxX - minX, 48)} ${Math.max(maxY - minY, 48)}`);
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", `${data.enemy_units.length} recent rival unit positions around known human city tiles`);
    const mark = (kind, p, label) => {
      const at = project(p), node = document.createElementNS(svg.namespaceURI, kind === "city" ? "rect" : "circle");
      node.setAttribute("class", `map-${kind}`);
      if (kind === "city") { node.setAttribute("x", at.x - 9); node.setAttribute("y", at.y - 9); node.setAttribute("width", 18); node.setAttribute("height", 18); }
      else { node.setAttribute("cx", at.x); node.setAttribute("cy", at.y); node.setAttribute("r", kind === "goal" ? 10 : 7); }
      const title = document.createElementNS(svg.namespaceURI, "title"); title.textContent = label; node.append(title); svg.append(node);
    };
    data.city_tiles.forEach((p) => mark("city", p, `Your city tile ${p.x}:${p.y}`));
    data.human_units.forEach((p) => mark("human", p, `${itemName(p.unit_type)} — last planned ${p.x}:${p.y}`));
    data.enemy_units.forEach((p) => mark("enemy", p, `${p.name} ${itemName(p.unit_type)} — ${p.activity} at ${p.x}:${p.y}`));
    data.attack_goals.forEach((p) => mark("goal", p, `${p.name} attack goal ${p.x}:${p.y}`));
    const legend = el("p", "map-legend", "Squares: your city tiles · Brass: your units · Red: rival plans · Rings: attack goals");
    host.replaceChildren(svg, legend);
  }

  function renderCommentary() {
    const result = state.commentary;
    const status = $("#commentary-status"), opinion = $("#second-opinion");
    const explain = $("#commentary-explain"), plan = $("#turn-plan"), meta = $("#commentary-meta");
    const detailed = result && result.status === "ready" && result.commentary;
    $("#explain-head").hidden = !detailed; $("#plan-head").hidden = !detailed;
    if (!detailed) {
      status.replaceChildren(el("p", result && result.status === "error" ? "file-warn" : "empty",
        result ? result.message : "Local commentary is unavailable."));
      opinion.replaceChildren(); explain.replaceChildren(); plan.replaceChildren(); meta.textContent = "";
      if (result && result.status === "generating" && state.commentaryTimer === null) {
        state.commentaryTimer = setTimeout(() => { state.commentaryTimer = null; refresh(); }, 2000);
      }
      return;
    }
    status.replaceChildren();
    const c = result.commentary, valid = state.insights.map((i) => `[${i.id}]`);
    const paragraph = (text) => {
      const p = el("p", valid.some((id) => text.includes(id)) ? null : "uncited", text);
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
    es.onmessage = () => { state.viaEvent = true; refresh(); };
    es.onerror = () => { es.close(); setTimeout(connect, 2000); };
  }

  refresh();
  connect();
})();
