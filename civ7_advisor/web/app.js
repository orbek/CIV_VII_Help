(() => {
  const $ = (sel) => document.querySelector(sel);
  const el = (tag, cls, text) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  };
  const fmt = (v, digits = 1) => (v === null || v === undefined) ? "—" : Number(v).toFixed(digits);
  const ordinal = (n) => {
    const tens = n % 100, ones = n % 10;
    const suffix = (tens > 10 && tens < 14) ? "th"
      : ones === 1 ? "st" : ones === 2 ? "nd" : ones === 3 ? "rd" : "th";
    return `${n}${suffix}`;
  };
  const PATHS = ["SCIENCE", "CULTURAL", "MILITARY", "ECONOMIC"];
  const PATH_LABEL = {
    SCIENCE: "Science", CULTURAL: "Cultural", MILITARY: "Military",
    ECONOMIC: "Economic", ESPIONAGE: "Espionage",
  };
  const SEVERITY_WORD = { CRITICAL: "Critical.", WARN: "Warning.", ADVISE: "Advice.", INFO: "Note." };
  const NOTHING_AT_ALL = "Nothing to report yet. Start a game, or point the advisor at another log folder.";
  const ORACLE_OFF = "Oracle off — AI intent, targeting and legacy paths are hidden.";

  const state = { data: null, insights: [], showOracle: true, shownTurn: null, viaEvent: false };

  try { state.showOracle = localStorage.getItem("civ7.oracle") !== "off"; } catch (_) { /* private mode */ }
  $("#oracle").checked = state.showOracle;
  $("#oracle").addEventListener("change", (e) => {
    state.showOracle = e.target.checked;
    try { localStorage.setItem("civ7.oracle", state.showOracle ? "on" : "off"); } catch (_) { /* ignore */ }
    render();
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
    const [s, i] = await Promise.all([fetch("/api/state"), fetch("/api/insights")]);
    if (!s.ok || !i.ok) return;
    state.data = await s.json();
    state.insights = await i.json();
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

  /* cols: [{label, num}]; a cell is a string, a Node, or {text, cls}. */
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
  }

  function render() {
    const d = state.data;
    if (!d) return;
    const ins = visible();
    renderHero(d, ins);
    renderRanks(d);
    renderFiles(d);

    const byAdvisor = (a) => ins.filter((i) => i.advisor === a);
    $("#checklist").replaceChildren(stream(ins, undefined));

    /* The toggle gates table content as well as cards: with Oracle off the
       AI-internal columns are dropped outright, not blanked. */
    const seen = state.showOracle;
    $("#threats-table").replaceChildren(table([
      { label: "Rival" }, { label: "Land units", num: true }, { label: "vs you", num: true },
      ...(seen ? [{ label: "War score", num: true }, { label: "Held since turn", num: true },
        { label: "At war" }] : []),
      { label: "Kills", num: true }, { label: "Your losses", num: true },
      ...(seen ? [{ label: "Targeting" }] : []),
    ], d.threats.map((t) => [
      t.name,
      t.land_units,
      `${fmt(t.military_ratio)}x`,
      ...(seen ? [
        t.war_score === null ? { text: "—", cls: "dim" } : fmt(t.war_score, 0),
        t.war_score_since === null ? { text: "—", cls: "dim" } : t.war_score_since,
        t.at_war_since === null ? { text: "no", cls: "dim" } : `since turn ${t.at_war_since}`,
      ] : []),
      t.kills, t.losses,
      ...(seen ? [
        (t.city_tiles_targeted || t.units_targeted)
          ? `${t.city_tiles_targeted} city tiles, ${t.units_targeted} units`
          : { text: "—", cls: "dim" },
      ] : []),
    ])), ...(seen ? [] : [withheld()]));
    $("#threats-cards").replaceChildren(stream(byAdvisor("threat"), "threat"));

    $("#victory-head").hidden = !seen;
    $("#victory-table").replaceChildren(seen ? table(
      [{ label: "Rival" }, ...PATHS.map((p) => ({ label: PATH_LABEL[p] }))],
      d.standings.filter((s) => s.kind === "rival" && s.alive).map((s) => [s.name, ...PATHS.map((p) => {
        const st = s.strategies.find((x) => x.strategy === p);
        if (!st) return { text: "—", cls: "dim" };
        if (!st.following) return { text: st.status, cls: "dim" };
        const span = el("span");
        span.append(document.createTextNode(st.status), el("span", "fig", String(st.weight)));
        return span;
      })])) : withheld());

    const boards = Object.keys(d.leaderboards);
    const depth = boards.reduce((n, p) => Math.max(n, d.leaderboards[p].length), 0);
    $("#victory-boards").replaceChildren(table(
      [{ label: "Rank", num: true }, ...boards.map((p) => ({ label: PATH_LABEL[p] || p }))],
      Array.from({ length: depth }, (_, i) => [ordinal(i + 1), ...boards.map((p) => {
        const entry = d.leaderboards[p][i];
        return entry ? named(entry.name, entry.value, entry.id === d.human) : { text: "—", cls: "dim" };
      })])));
    $("#victory-cards").replaceChildren(stream(byAdvisor("victory"), "victory"));

    $("#economy-table").replaceChildren(table([
      { label: "Yield" }, { label: "You", num: true }, { label: "Rival median", num: true },
      { label: "You vs median", num: true }, { label: "Best", num: true }, { label: "Held by" },
    ], d.economy.map((c) => [
      c.label, fmt(c.human), fmt(c.rival_median),
      { text: `${Math.round(c.ratio * 100)}%`, cls: c.ratio < 0.75 ? "behind" : "" },
      fmt(c.leader_value), c.leader_name,
    ])));
    $("#economy-cards").replaceChildren(stream(byAdvisor("economy"), "economy"));
  }

  function connect() {
    const es = new EventSource("/events");
    es.onmessage = () => { state.viaEvent = true; refresh(); };
    es.onerror = () => { es.close(); setTimeout(connect, 2000); };
  }

  refresh();
  connect();
})();
