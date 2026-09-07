(() => {
  const $ = (sel) => document.querySelector(sel);
  const el = (tag, cls, text) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  };
  const fmt = (v, digits = 1) => (v === null || v === undefined) ? "—" : Number(v).toFixed(digits);

  const state = { data: null, insights: [], showOracle: true };
  try { state.showOracle = localStorage.getItem("civ7.oracle") !== "off"; } catch (_) { /* private mode */ }
  $("#oracle").checked = state.showOracle;
  $("#oracle").addEventListener("change", (e) => {
    state.showOracle = e.target.checked;
    try { localStorage.setItem("civ7.oracle", state.showOracle ? "on" : "off"); } catch (_) { /* ignore */ }
    render();
  });

  document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => {
    document.querySelectorAll(".tabs button, .tab").forEach((x) => x.classList.remove("active"));
    b.classList.add("active");
    $("#" + b.dataset.tab).classList.add("active");
  }));

  async function refresh() {
    const [s, i] = await Promise.all([fetch("/api/state"), fetch("/api/insights")]);
    if (!s.ok || !i.ok) return;
    state.data = await s.json();
    state.insights = await i.json();
    render();
  }

  const visible = () => state.insights.filter((x) => state.showOracle || x.provenance !== "oracle");

  function card(ins) {
    const c = el("article", `card sev-${ins.severity.toLowerCase()} prov-${ins.provenance}`);
    const head = el("div", "card-head");
    head.append(el("span", "sev", ins.severity), el("span", "title", ins.title));
    if (ins.provenance === "oracle") head.append(el("span", "badge oracle", "Oracle"));
    c.append(head, el("p", "rec", ins.recommendation), el("p", "why", "Why: " + ins.why));
    return c;
  }
  function cards(list) {
    const wrap = el("div", "cards");
    if (!list.length) wrap.append(el("p", "empty", "Nothing to report."));
    list.forEach((i) => wrap.append(card(i)));
    return wrap;
  }
  function table(headers, rows) {
    const t = el("table");
    const head = el("tr");
    headers.forEach((h) => head.append(el("th", null, h)));
    t.append(head);
    rows.forEach((r) => { const tr = el("tr"); r.forEach((c) => tr.append(el("td", null, String(c)))); t.append(tr); });
    const wrap = el("div", "table-wrap");
    wrap.append(t);
    return wrap;
  }

  function render() {
    const d = state.data;
    if (!d) return;
    $("#turn").textContent = `Turn ${d.complete_through_turn}`;
    const progress = $("#progress");
    progress.classList.toggle("hidden", !d.in_progress);
    progress.textContent = `turn ${d.latest_turn} in progress`;
    $("#ranks").replaceChildren(...Object.entries(d.ranks).map(([k, [r, n]]) =>
      el("span", "chip", `${k.replace("_", " ")} #${r}/${n}`)));
    const ins = visible();
    $("#top").replaceChildren(ins.length
      ? el("span", `top-${ins[0].severity.toLowerCase()}`, `${ins[0].severity}: ${ins[0].title}`)
      : el("span", null, "All quiet"));
    $("#files").replaceChildren(...Object.values(d.files).filter((f) => !f.ok)
      .map((f) => el("span", "chip warn", `${f.name}: ${f.error}`)));

    $("#checklist").replaceChildren(cards(ins));
    const byAdvisor = (a) => ins.filter((i) => i.advisor === a);

    $("#threats-table").replaceChildren(table(
      ["Rival", "Land units", "vs you", "War score", "At war", "Kills / your losses", "Targeting"],
      d.threats.map((t) => [
        t.name, t.land_units, `${fmt(t.military_ratio)}x`,
        t.war_score === null ? "—" : `${fmt(t.war_score, 0)} since t${t.war_score_since}`,
        t.at_war_since === null ? "no" : `since t${t.at_war_since}`,
        `${t.kills} / ${t.losses}`,
        (t.city_tiles_targeted || t.units_targeted) ? `${t.city_tiles_targeted} city tiles, ${t.units_targeted} units` : "—",
      ])));
    $("#threats-cards").replaceChildren(cards(byAdvisor("threat")));

    const paths = ["SCIENCE", "CULTURAL", "MILITARY", "ECONOMIC"];
    const strategyRows = d.standings.filter((s) => s.kind === "rival" && s.alive).map((s) => [
      s.name, ...paths.map((p) => {
        const st = s.strategies.find((x) => x.strategy === p);
        return st ? `${st.status}${st.following ? " " + st.weight : ""}` : "—";
      }),
    ]);
    const boards = Object.entries(d.leaderboards).map(([p, b]) => [p, b.map((x) => `${x.name} ${fmt(x.value)}`).join("  ›  ")]);
    $("#victory-table").replaceChildren(
      table(["Rival", "Science", "Cultural", "Military", "Economic"], strategyRows),
      table(["Path", "Leaderboard (best first)"], boards));
    $("#victory-cards").replaceChildren(cards(byAdvisor("victory")));

    $("#economy-table").replaceChildren(table(
      ["Yield", "You", "Rival median", "You / median", "Leader"],
      d.economy.map((c) => [c.label, fmt(c.human), fmt(c.rival_median), `${Math.round(c.ratio * 100)}%`, `${c.leader_name} ${fmt(c.leader_value)}`])));
    $("#economy-cards").replaceChildren(cards(byAdvisor("economy")));
  }

  function connect() {
    const es = new EventSource("/events");
    es.onmessage = () => refresh();
    es.onerror = () => { es.close(); setTimeout(connect, 2000); };
  }

  refresh();
  connect();
})();
