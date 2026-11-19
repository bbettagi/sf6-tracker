"use strict";

/* ===================================================================================
   SF6 Tracker dashboard. Plain DOM + Chart.js; all numbers come from /api/stats.
   =================================================================================== */

const state = {
  meta: null,
  stats: null,
  matches: null,
  tab: "overview",
  matchupMin: 3,
  matchupSort: "matches",
  rankView: "match",
  rankMetric: null,
  matchLimit: 100,
  charts: [],
};

// ---- tiny DOM helpers (all text goes through textContent) ---------------------------
function h(tag, attrs, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else if (k === "style") node.style.cssText = v;
    else node.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return node;
}
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

function toast(msg, ms = 3500) {
  const t = $("#toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { t.hidden = true; }, ms);
}

// ---- formatting -----------------------------------------------------------------
const MINUS = "−";
const fmtNum = (n) => (n === null || n === undefined ? "—" : Number(n).toLocaleString());
const fmtPct = (x, digits = 1) => (x === null || x === undefined ? "—" : `${(x * 100).toFixed(digits)}%`);
const fmtSigned = (n) => {
  if (n === null || n === undefined) return "—";
  const v = Math.round(n * 10) / 10;
  return v > 0 ? `+${v.toLocaleString()}` : v < 0 ? `${MINUS}${Math.abs(v).toLocaleString()}` : "0";
};
const fmtDate = (t) => new Date(t * 1000).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
const fmtDay = (t) => new Date(t * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
const fmtIsoDay = (iso) => new Date(`${iso}T12:00:00`).toLocaleDateString(undefined, { month: "short", day: "numeric" });
const record = (s) => `${s.wins}–${s.losses}${s.draws ? `–${s.draws}` : ""}`;

function deltaNode(n) {
  if (n === null || n === undefined) return h("span", { class: "muted", text: "—" });
  const dir = n > 0 ? "up" : n < 0 ? "down" : null;
  return h("span", {}, dir ? h("i", { class: `delta-mark ${dir}`, "aria-hidden": "true" }) : null, fmtSigned(n));
}

// ---- API ------------------------------------------------------------------------
async function api(path, opts = {}) {
  const res = await fetch(path, {
    ...opts,
    headers: { "X-SF6-Tracker": "1", ...(opts.body ? { "Content-Type": "application/json" } : {}), ...(opts.headers || {}) },
  });
  let data = null;
  try { data = await res.json(); } catch (e) { /* empty body */ }
  if (!res.ok) throw new Error((data && data.error) || `HTTP ${res.status}`);
  return data;
}

function filterParams() {
  const p = new URLSearchParams();
  const range = $("#f-range").value;
  const now = new Date();
  const midnight = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  if (range === "today") p.set("from", Math.floor(midnight / 1000));
  else if (/^\d+$/.test(range)) p.set("from", Math.floor(now / 1000) - Number(range) * 86400);
  else if (range === "custom") {
    const from = $("#f-from").value, to = $("#f-to").value;
    if (from) p.set("from", Math.floor(new Date(`${from}T00:00:00`) / 1000));
    if (to) p.set("to", Math.floor(new Date(`${to}T00:00:00`) / 1000) + 86400);
  }
  const ch = $("#f-char").value;
  if (ch) p.set("character", ch);
  p.set("tz", new Date().getTimezoneOffset());
  return p;
}

async function loadMeta() {
  state.meta = await api("/api/meta");
  const sel = $("#f-char");
  const current = sel.value;
  sel.replaceChildren(h("option", { value: "", text: "All characters" }),
    ...state.meta.my_characters.map((c) => h("option", { value: c, text: c })));
  sel.value = state.meta.my_characters.includes(current) ? current : "";
  const cfg = state.meta.config;
  $("#quick-sync").hidden = !(cfg.cookie_set && cfg.sid);
}

async function loadStats() {
  $("#main").classList.add("loading");
  try {
    state.stats = await api(`/api/stats?${filterParams()}`);
    state.matches = null;
    const n = state.stats.overview.summary.matches;
    const total = state.meta.match_count;
    $("#filter-note").textContent = total
      ? (n === total ? `${fmtNum(total)} ranked matches` : `Showing ${fmtNum(n)} of ${fmtNum(total)} ranked matches`)
      : "";
    render();
  } finally {
    $("#main").classList.remove("loading");
  }
}

async function reloadAll() {
  await loadMeta();
  await loadStats();
}

// ---- Chart.js theme + plugins -----------------------------------------------------
function applyChartTheme() {
  const d = Chart.defaults;
  d.font.family = getComputedStyle(document.body).fontFamily;
  d.font.size = 12;
  d.color = css("--muted");
  d.borderColor = css("--grid");
  d.maintainAspectRatio = false;
  d.animation.duration = 250;
  d.plugins.legend.display = false;
  const tt = d.plugins.tooltip;
  Object.assign(tt, {
    backgroundColor: css("--surface"), titleColor: css("--text-2"), bodyColor: css("--text"),
    footerColor: css("--muted"), borderColor: css("--axis"), borderWidth: 1, padding: 10,
    cornerRadius: 8, usePointStyle: true, boxPadding: 6, caretSize: 0,
    titleFont: { weight: "500" }, bodyFont: { weight: "600" }, footerFont: { weight: "400" },
  });
  tt.callbacks.labelPointStyle = () => ({ pointStyle: "line", rotation: 0 });
  tt.callbacks.labelColor = (ctx) => {
    const ds = ctx.dataset;
    let c = Array.isArray(ds.backgroundColor) ? ds.backgroundColor[ctx.dataIndex] : ds.borderColor || ds.backgroundColor;
    return { borderColor: c, backgroundColor: c, borderWidth: 2 };
  };
}

const crosshairPlugin = {
  id: "crosshair",
  afterDatasetsDraw(chart) {
    if (!chart.options.plugins.crosshair) return;
    const active = chart.tooltip && chart.tooltip.getActiveElements();
    if (!active || !active.length) return;
    const { ctx, chartArea } = chart;
    const x = Math.round(active[0].element.x) + 0.5;
    ctx.save();
    ctx.strokeStyle = css("--axis");
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(x, chartArea.top);
    ctx.lineTo(x, chartArea.bottom);
    ctx.stroke();
    ctx.restore();
  },
};

// Horizontal reference lines (rank division floors, the 50% line, ...)
const refLinesPlugin = {
  id: "refLines",
  beforeDatasetsDraw(chart) {
    const opts = chart.options.plugins.refLines;
    if (!opts || !opts.lines || !opts.lines.length) return;
    const { ctx, chartArea } = chart;
    const y = chart.scales.y;
    ctx.save();
    ctx.font = `500 11px ${Chart.defaults.font.family}`;
    ctx.textBaseline = "bottom";
    let lastLabelY = Infinity;
    const lines = [...opts.lines].sort((a, b) => a.value - b.value);
    for (const line of lines) {
      const py = Math.round(y.getPixelForValue(line.value)) + 0.5;
      if (py < chartArea.top - 1 || py > chartArea.bottom + 1) continue;
      ctx.strokeStyle = line.strong ? css("--axis") : css("--grid");
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(chartArea.left, py);
      ctx.lineTo(chartArea.right, py);
      ctx.stroke();
      if (line.label && lastLabelY - py >= 14 && py - chartArea.top >= 12) {
        ctx.fillStyle = css("--muted");
        ctx.fillText(line.label, chartArea.left + 6, py - 3);
        lastLabelY = py;
      }
    }
    ctx.restore();
  },
};

// Value at the tip of each bar.
const tipLabelsPlugin = {
  id: "tipLabels",
  afterDatasetsDraw(chart) {
    // The formatter lives on the raw dataset: Chart.js would treat a function in
    // options as a scriptable option and call it with its own context.
    if (!chart.data.datasets.some((ds) => typeof ds.tipLabel === "function")) return;
    const { ctx } = chart;
    const horizontal = chart.options.indexAxis === "y";
    ctx.save();
    ctx.font = `600 11px ${Chart.defaults.font.family}`;
    ctx.fillStyle = css("--text-2");
    chart.data.datasets.forEach((ds, di) => {
      chart.getDatasetMeta(di).data.forEach((bar, i) => {
        const v = ds.data[i];
        if (typeof ds.tipLabel !== "function" || v === null || v === undefined) return;
        const text = ds.tipLabel(v, i);
        const neg = v < 0;
        if (horizontal) {
          ctx.textAlign = neg ? "right" : "left";
          ctx.textBaseline = "middle";
          ctx.fillText(text, bar.x + (neg ? -6 : 6), bar.y);
        } else {
          ctx.textAlign = "center";
          ctx.textBaseline = neg ? "top" : "bottom";
          ctx.fillText(text, bar.x, bar.y + (neg ? 4 : -4));
        }
      });
    });
    ctx.restore();
  },
};

Chart.register(crosshairPlugin, refLinesPlugin, tipLabelsPlugin);

function destroyCharts() {
  state.charts.forEach((c) => c.destroy());
  state.charts = [];
}

// ---- building blocks ---------------------------------------------------------------
function tile(label, value, sub, extra = {}) {
  return h("div", { class: `tile${extra.hero ? " hero" : ""}` },
    h("div", { class: "label", text: label }),
    h("div", { class: "value" }, value),
    sub ? h("div", { class: "sub" }, sub) : null);
}

function card(title, sub, ...body) {
  const tools = h("div", { class: "card-tools" });
  const node = h("div", { class: "card" },
    h("div", { class: "card-head" }, h("div", {}, h("h2", { text: title }), sub ? h("p", { text: sub }) : null), tools),
    ...body);
  node.tools = tools;
  return node;
}

function seg(options, value, onChange, label) {
  const group = h("div", { class: "seg", role: "group", "aria-label": label });
  for (const [val, text] of options) {
    group.append(h("button", { type: "button", "aria-pressed": String(val === value), text, onclick: () => onChange(val) }));
  }
  return group;
}

/**
 * Sortable table. columns: [{key, label, num, format(row) -> node|string, sort(row) -> value}]
 */
function table(columns, rows, opts = {}) {
  let sortKey = opts.sortKey || null;
  let dir = opts.sortDir || "desc";
  const wrap = h("div", { class: "table-wrap" });
  const draw = () => {
    const sorted = [...rows];
    if (sortKey) {
      const col = columns.find((c) => c.key === sortKey);
      const val = col.sort || ((r) => r[col.key]);
      sorted.sort((a, b) => {
        const x = val(a), y = val(b);
        if (x === y) return 0;
        if (x === null || x === undefined) return 1;
        if (y === null || y === undefined) return -1;
        return (x < y ? -1 : 1) * (dir === "asc" ? 1 : -1);
      });
    }
    const head = h("tr", {}, columns.map((c) => {
      const th = h("th", { class: `${c.num ? "num " : ""}${c.sortable === false ? "" : "sortable"}`, text: c.label, scope: "col" });
      if (c.key === sortKey) th.setAttribute("aria-sort", dir === "asc" ? "ascending" : "descending");
      if (c.sortable !== false) {
        th.tabIndex = 0;
        const go = () => { if (sortKey === c.key) dir = dir === "asc" ? "desc" : "asc"; else { sortKey = c.key; dir = c.num ? "desc" : "asc"; } draw(); };
        th.addEventListener("click", go);
        th.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } });
      }
      return th;
    }));
    const body = sorted.map((r) => h("tr", { class: opts.rowClass ? opts.rowClass(r) : null },
      columns.map((c) => h("td", { class: c.num ? "num" : null }, c.format ? c.format(r) : (r[c.key] ?? "—")))));
    wrap.replaceChildren(h("table", {}, h("thead", {}, head), h("tbody", {}, body)));
  };
  draw();
  return wrap;
}

/**
 * A card holding a chart plus its table-view twin.
 * spec: {title, sub, height, config: () => Chart config, table: () => node, tools: [nodes]}
 */
function chartCard(spec) {
  const c = card(spec.title, spec.sub);
  const box = h("div", { class: "chart-box", style: `height:${spec.height || 260}px` });
  const canvas = h("canvas", { role: "img", "aria-label": spec.title });
  box.append(canvas);
  const tableBox = h("div", { hidden: true });
  let showingTable = false;
  const toggle = h("button", { class: "btn btn-small", type: "button", "aria-pressed": "false", text: "Table" });
  toggle.addEventListener("click", () => {
    showingTable = !showingTable;
    toggle.setAttribute("aria-pressed", String(showingTable));
    toggle.textContent = showingTable ? "Chart" : "Table";
    box.hidden = showingTable;
    tableBox.hidden = !showingTable;
    if (showingTable && !tableBox.firstChild) tableBox.append(spec.table());
  });
  (spec.tools || []).forEach((t) => c.tools.append(t));
  if (spec.table) c.tools.append(toggle);
  c.append(box, tableBox);
  if (spec.note) c.append(h("p", { class: "note", text: spec.note }));
  requestAnimationFrame(() => {
    if (!canvas.isConnected) return;
    state.charts.push(new Chart(canvas, spec.config()));
  });
  return c;
}

const winColor = () => css("--win");
const lossColor = () => css("--loss");
const neutralColor = () => css("--neutral");
const signColor = (v) => (v > 0 ? winColor() : v < 0 ? lossColor() : neutralColor());

/** Diverging win-rate bars centred on 50%. rows: [{label, win_rate, matches, ...}] */
function winRateBarsConfig(rows, { horizontal = false, labelFor = (r) => r.label, extraTooltip } = {}) {
  const values = rows.map((r) => (r.win_rate === null ? null : Math.round((r.win_rate - 0.5) * 1000) / 10));
  const maxAbs = Math.max(10, ...values.filter((v) => v !== null).map(Math.abs));
  // Room past the longest bar for its tip label, snapped to 10% steps.
  const pad = Math.min(60, Math.ceil((maxAbs + 10) / 10) * 10);
  const valueAxis = {
    min: -pad, max: pad,
    grid: { color: (ctx) => (ctx.tick.value === 0 ? css("--axis") : css("--grid")) },
    border: { display: false },
    // Ticks at round win rates: 0/25/50/75/100% on a wide axis, every 10% on a narrow one.
    afterBuildTicks: (axis) => {
      const step = pad > 30 ? 25 : 10;
      const ticks = [];
      for (let v = -50; v <= 50; v += step) if (v >= -pad && v <= pad) ticks.push({ value: v });
      axis.ticks = ticks;
    },
    ticks: { callback: (v) => `${v + 50}%` },
  };
  const catAxis = { grid: { display: false }, border: { color: css("--axis") }, ticks: { color: css("--text-2"), autoSkip: false } };
  return {
    type: "bar",
    data: {
      labels: rows.map(labelFor),
      datasets: [{
        data: values,
        backgroundColor: values.map(signColor),
        borderRadius: 4,
        borderSkipped: "start",
        maxBarThickness: 24,
        categoryPercentage: 0.8,
        barPercentage: 0.9,
        tipLabel: (v) => `${(v + 50).toFixed(0)}%`,
      }],
    },
    options: {
      indexAxis: horizontal ? "y" : "x",
      scales: horizontal ? { x: valueAxis, y: catAxis } : { x: catAxis, y: valueAxis },
      plugins: {
        tooltip: {
          callbacks: {
            title: (items) => labelFor(rows[items[0].dataIndex]),
            label: (ctx) => `${fmtPct(rows[ctx.dataIndex].win_rate)} win rate`,
            afterLabel: (ctx) => {
              const r = rows[ctx.dataIndex];
              const lines = [`${record(r)} in ${fmtNum(r.matches)} matches`];
              if (extraTooltip) lines.push(...extraTooltip(r));
              return lines;
            },
          },
        },
      },
    },
  };
}

function winRateTable(rows, firstLabel = "Group") {
  return table([
    { key: "label", label: firstLabel },
    { key: "matches", label: "Matches", num: true },
    { key: "wins", label: "W–L", num: true, format: record },
    { key: "win_rate", label: "Win rate", num: true, format: (r) => fmtPct(r.win_rate) },
    { key: "net_lp", label: "Net LP", num: true, format: (r) => deltaNode(r.net_lp) },
  ], rows);
}

function noData(msg = "Not enough matches in this range.") {
  return h("p", { class: "note", text: msg });
}

// ---- rank presentation -----------------------------------------------------------
function rankHeadline(info) {
  if (!info) return { title: "Unranked", points: "", meta: "" };
  if (info.master_tier) {
    return {
      title: info.master_tier,
      points: `${fmtNum(info.mr)} MR`,
      meta: info.next ? `${fmtNum(info.to_next)} MR to ${info.next}` : "Top MR tier",
    };
  }
  if (info.division) {
    return {
      title: info.division,
      points: `${fmtNum(info.lp)} LP`,
      meta: info.next ? `${fmtNum(info.to_next)} LP to ${info.next}` : "",
    };
  }
  return { title: "Unranked", points: "", meta: "" };
}

function rankCard(row) {
  const r = rankHeadline(row.current);
  const peak = row.peak_mr ? `Peak ${fmtNum(row.peak_mr)} MR` : row.peak_lp ? `Peak ${fmtNum(row.peak_lp)} LP` : "";
  return h("div", { class: "card rank-card" },
    h("div", { class: "top" }, h("span", { class: "char", text: row.character }), h("span", { class: "points", text: `${record(row)} · ${fmtPct(row.win_rate)}` })),
    h("div", { class: "division", text: r.title }),
    h("div", { class: "points", text: r.points }),
    row.current && row.current.progress !== null
      ? h("div", { class: "meter", role: "meter", "aria-valuemin": "0", "aria-valuemax": "100", "aria-valuenow": String(Math.round(row.current.progress * 100)), "aria-label": r.meta },
        h("div", { style: `width:${Math.max(2, row.current.progress * 100)}%` }))
      : h("div", { style: "height:24px" }),
    h("div", { class: "meta" }, h("span", { text: r.meta }), h("span", { text: peak })));
}

// =====================================================================================
// Panels
// =====================================================================================
const PANELS = {
  overview: renderOverview,
  rank: renderRank,
  matchups: renderMatchups,
  sessions: renderSessions,
  opponents: renderOpponents,
  rounds: renderRounds,
  matches: renderMatches,
  sync: renderSync,
};
const DATA_TABS = new Set(["overview", "rank", "matchups", "sessions", "opponents", "rounds"]);

function render() {
  destroyCharts();
  applyChartTheme();
  const empty = !state.meta.match_count && DATA_TABS.has(state.tab);
  $("#empty").hidden = !empty;
  $$(".panel").forEach((p) => { p.hidden = p.dataset.panel !== state.tab || empty; });
  const panel = $(`.panel[data-panel="${state.tab}"]`);
  panel.replaceChildren();
  if (empty) return;
  if (DATA_TABS.has(state.tab) && !state.stats.overview.summary.matches) {
    panel.append(h("div", { class: "empty" }, h("h2", { text: "No matches in this range" }), h("p", { text: "Widen the date range or pick another character." })));
    return;
  }
  PANELS[state.tab](panel);
}

// ---- Overview ------------------------------------------------------------------------
function renderOverview(panel) {
  const o = state.stats.overview;
  const s = o.summary;
  const st = o.streaks;
  const cur = st.current.type ? `${st.current.length} ${st.current.type === "W" ? "win" : "loss"}${st.current.length === 1 ? "" : st.current.type === "W" ? "s" : "es"}` : "—";
  const mrFirst = s.net_mr !== null && (s.net_lp === null || state.stats.rank.current?.master_tier);
  const lpOrMr = mrFirst
    ? tile("Net MR", deltaNode(s.net_mr), s.net_lp !== null ? `and ${fmtSigned(s.net_lp)} LP on other characters` : `${fmtSigned(s.avg_mr)} per match`)
    : tile("Net LP", deltaNode(s.net_lp), s.net_mr !== null ? `and ${fmtSigned(s.net_mr)} MR in Master` : s.avg_lp !== null ? `${fmtSigned(s.avg_lp)} per match` : "");

  panel.append(
    h("div", { class: "kpis" },
      tile("Win rate", fmtPct(s.win_rate), `${record(s)}`, { hero: true }),
      tile("Ranked matches", fmtNum(s.matches), `${fmtNum(s.rounds_won + s.rounds_lost)} rounds played`),
      tile("Round win rate", fmtPct(s.round_win_rate), `${fmtNum(s.rounds_won)}–${fmtNum(s.rounds_lost)} rounds`),
      lpOrMr,
      tile("Current streak", cur, st.longest_win.length ? `Best: ${st.longest_win.length} wins in a row` : ""),
    ),
    h("div", { class: "rank-cards" }, o.characters.map(rankCard)),
  );

  const rolling = o.rolling;
  const grid = h("div", { class: "grid grid-2" });
  grid.append(rolling.length ? chartCard({
    title: "Win rate trend",
    sub: `Rolling win rate over your last ${rolling[rolling.length - 1].window} matches at each point`,
    height: 240,
    config: () => ({
      type: "line",
      data: { datasets: [{ data: rolling.map((p) => ({ x: p.n, y: Math.round(p.win_rate * 1000) / 10 })), borderColor: winColor(), borderWidth: 2, pointRadius: 0, pointHoverRadius: 5, pointHoverBorderWidth: 2, pointHoverBorderColor: css("--surface"), pointHoverBackgroundColor: winColor() }] },
      options: {
        interaction: { mode: "nearest", axis: "x", intersect: false },
        scales: {
          x: { type: "linear", grid: { display: false }, border: { color: css("--axis") }, title: { display: true, text: "Match", color: css("--muted") }, ticks: { precision: 0 } },
          y: { suggestedMin: 30, suggestedMax: 70, grid: { color: (ctx) => (ctx.tick.value === 50 ? css("--axis") : css("--grid")) }, border: { display: false }, ticks: { callback: (v) => `${v}%` } },
        },
        plugins: {
          crosshair: true,
          tooltip: { callbacks: { title: (items) => `Match ${items[0].raw.x} · ${fmtDay(rolling[items[0].dataIndex].t)}`, label: (ctx) => `${ctx.raw.y.toFixed(1)}% over last ${rolling[ctx.dataIndex].window}` } },
        },
      },
    }),
    table: () => table([
      { key: "n", label: "Match", num: true },
      { key: "t", label: "Date", format: (r) => fmtDate(r.t) },
      { key: "win_rate", label: "Rolling win rate", num: true, format: (r) => fmtPct(r.win_rate) },
    ], rolling.slice(-50).reverse()),
  }) : card("Win rate trend", null, noData("Play at least 10 matches to see a trend.")));

  const recent = card("Recent form", "Last 20 matches, oldest first",
    h("div", { class: "form-strip" }, o.form.map((m) => h("span", { class: `pill ${m.result}`, title: `${m.result === "W" ? "Win" : m.result === "L" ? "Loss" : "Draw"} vs ${m.opp} · ${fmtDate(m.t)}`, text: m.result }))));
  const mu = state.stats.matchups.filter((r) => r.matches >= 5 && r.win_rate !== null);
  const best = [...mu].sort((a, b) => b.win_rate - a.win_rate).slice(0, 3);
  const worst = [...mu].sort((a, b) => a.win_rate - b.win_rate).slice(0, 3);
  const muList = (rows) => h("ul", { class: "events" }, rows.map((r) => h("li", {},
    h("strong", { text: r.character }), h("span", { class: "muted", text: `${record(r)}` }), h("time", { text: fmtPct(r.win_rate) }))));
  recent.append(
    h("div", { class: "grid grid-2", style: "margin-top:16px" },
      h("div", {}, h("h3", { text: "Best matchups" }), best.length ? muList(best) : noData("Needs 5+ games vs a character.")),
      h("div", {}, h("h3", { text: "Toughest matchups" }), worst.length ? muList(worst) : noData("Needs 5+ games vs a character."))));
  grid.append(recent);
  panel.append(grid);
}

// ---- Rank --------------------------------------------------------------------------
function renderRank(panel) {
  const r = state.stats.rank;
  if (!r.character) return panel.append(noData());
  const pts = r.points;
  const hasMR = pts.some((p) => p.mr !== null || p.mr_before !== null);
  const hasLP = pts.some((p) => p.lp !== null || p.lp_before !== null);
  if (!state.rankMetric || (state.rankMetric === "mr" && !hasMR) || (state.rankMetric === "lp" && !hasLP)) {
    state.rankMetric = r.current && r.current.master_tier && hasMR ? "mr" : hasLP ? "lp" : "mr";
  }

  if (!$("#f-char").value && r.characters.length > 1) {
    panel.append(h("div", { class: "card" },
      h("div", { class: "chips" },
        h("span", { class: "muted", text: `Rank is tracked per character. Showing ${r.character} (most played). Switch to:` }),
        r.characters.filter((c) => c !== r.character).map((c) => h("button", { class: "btn btn-small", type: "button", text: c, onclick: () => { $("#f-char").value = c; loadStats(); } })))));
  }

  const head = rankHeadline(r.current);
  const lpDeltas = pts.map((p) => p.lp_delta).filter((v) => v !== null);
  const mrDeltas = pts.map((p) => p.mr_delta).filter((v) => v !== null);
  const avg = (xs) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null);
  const useMR = state.rankMetric === "mr";
  const ds = useMR ? mrDeltas : lpDeltas;
  const gains = ds.filter((v) => v > 0), losses = ds.filter((v) => v < 0);
  const peak = Math.max(...pts.flatMap((p) => (useMR ? [p.mr, p.mr_before] : [p.lp, p.lp_before])).filter((v) => v !== null));
  const unit = useMR ? "MR" : "LP";
  panel.append(h("div", { class: "kpis" },
    tile(`${r.character} rank`, head.title, `${head.points}${head.meta ? ` · ${head.meta}` : ""}`),
    tile(`Net ${unit} in range`, deltaNode(useMR ? r.summary.net_mr : r.summary.net_lp), `${fmtNum(ds.length)} matches with a known change`),
    tile(`Peak ${unit}`, Number.isFinite(peak) ? fmtNum(peak) : "—", "in this range"),
    tile("Avg gain per win", gains.length ? fmtSigned(avg(gains)) : "—", `${unit} · ${gains.length} gains`),
    tile("Avg loss per loss", losses.length ? fmtSigned(avg(losses)) : "—", `${unit} · ${losses.length} losses`),
  ));

  const metricSwitch = hasLP && hasMR
    ? seg([["lp", "LP"], ["mr", "MR"]], state.rankMetric, (v) => { state.rankMetric = v; render(); }, "Rating")
    : null;

  // Rating over time: one chart per currency, never two y-scales on one plot.
  const progressionCard = (metric) => {
    const key = metric;
    const series = pts.map((p) => ({ x: p.game, y: p[key] ?? null, p }));
    const valid = series.filter((s) => s.y !== null);
    const lines = metric === "lp"
      ? DIVISIONS.map(([name, floor]) => ({ value: floor, label: name, strong: name.endsWith(" 1") || name === "Master" }))
      : MASTER_TIERS.map(([name, floor]) => ({ value: floor, label: name, strong: true }));
    const color = winColor();
    return chartCard({
      title: metric === "lp" ? "League Points over time" : "Master Rate over time",
      sub: metric === "lp" ? "LP after each match. Lines mark division floors." : "MR after each match. Lines mark the Master tiers.",
      height: 320,
      tools: [metricSwitch].filter(Boolean),
      config: () => ({
        type: "line",
        data: { datasets: [{
          data: valid.map((s) => ({ x: s.x, y: s.y })),
          borderColor: color, borderWidth: 2, pointRadius: valid.length < 40 ? 3 : 0, pointBackgroundColor: color,
          pointHoverRadius: 5, pointHoverBorderWidth: 2, pointHoverBorderColor: css("--surface"), pointHoverBackgroundColor: color,
          fill: "start", backgroundColor: hexAlpha(color, 0.08), tension: 0,
        }] },
        options: {
          interaction: { mode: "nearest", axis: "x", intersect: false },
          scales: {
            x: { type: "linear", grid: { display: false }, border: { color: css("--axis") }, title: { display: true, text: `${r.character} match #`, color: css("--muted") }, ticks: { precision: 0 } },
            y: { grace: "8%", grid: { display: false }, border: { display: false }, ticks: { callback: (v) => compact(v) } },
          },
          plugins: {
            crosshair: true,
            refLines: { lines },
            tooltip: { callbacks: {
              title: (items) => { const s = valid[items[0].dataIndex].p; return `${fmtDate(s.t)} · match ${s.game}`; },
              label: (ctx) => `${fmtNum(ctx.raw.y)} ${metric.toUpperCase()}`,
              afterLabel: (ctx) => { const s = valid[ctx.dataIndex].p; const d = s[`${key}_delta`]; return `${s.result === "W" ? "Win" : s.result === "L" ? "Loss" : "Draw"} vs ${s.opp}${d !== null ? ` (${fmtSigned(d)})` : ""}`; },
            } },
          },
        },
      }),
      table: () => table([
        { key: "game", label: "Match", num: true },
        { key: "t", label: "Date", format: (p) => fmtDate(p.t) },
        { key: "opp", label: "Opponent" },
        { key: "result", label: "Result", format: (p) => h("span", { class: `pill ${p.result}`, text: p.result }) },
        { key: key, label: metric.toUpperCase(), num: true, format: (p) => fmtNum(p[key]) },
        { key: `${key}_delta`, label: "Change", num: true, format: (p) => deltaNode(p[`${key}_delta`]) },
      ], [...pts].reverse(), { sortKey: "game", sortDir: "desc" }),
      note: state.stats.timing.used === "pre" ? "Buckler records each match's LP/MR from before it was played, so your latest match's change shows up after your next one." : null,
    });
  };

  panel.append(progressionCard(state.rankMetric));

  // Gains and losses
  const view = state.rankView;
  const metric = state.rankMetric;
  const dkey = metric === "mr" ? "net_mr" : "net_lp";
  let rows;
  if (view === "match") {
    rows = pts.filter((p) => p[`${metric}_delta`] !== null).slice(-60).map((p) => ({
      label: `#${p.game}`, value: p[`${metric}_delta`], tip: `${fmtDate(p.t)} · ${p.result === "W" ? "Win" : "Loss"} vs ${p.opp}`, p,
    }));
  } else if (view === "day") {
    rows = r.by_day.filter((d) => d[dkey] !== null).slice(-45).map((d) => ({
      label: fmtIsoDay(d.day), value: d[dkey], tip: `${d.day} · ${record(d)} (${fmtPct(d.win_rate, 0)})`, d,
    }));
  } else {
    rows = r.by_session.filter((d) => d[dkey] !== null).slice(-40).map((d) => ({
      label: fmtDate(d.start), value: d[dkey], tip: `${fmtDate(d.start)} · ${d.matches} matches · ${record(d)}`, d,
    }));
  }
  const viewSwitch = seg([["match", "Per match"], ["day", "Per day"], ["session", "Per session"]], view, (v) => { state.rankView = v; render(); }, "Group by");
  const unitU = metric.toUpperCase();
  panel.append(rows.length ? chartCard({
    title: `${unitU} gained and lost`,
    sub: view === "match" ? `Your last ${rows.length} matches with a known change` : view === "day" ? `Net ${unitU} per day (last ${rows.length} days played)` : `Net ${unitU} per play session (last ${rows.length})`,
    height: 260,
    tools: [viewSwitch],
    config: () => ({
      type: "bar",
      data: { labels: rows.map((x) => x.label), datasets: [{ data: rows.map((x) => x.value), backgroundColor: rows.map((x) => signColor(x.value)), borderRadius: 4, borderSkipped: "start", maxBarThickness: 24, categoryPercentage: 0.85, barPercentage: 0.9 }] },
      options: {
        scales: {
          x: { grid: { display: false }, border: { display: false }, ticks: { maxRotation: 0, autoSkipPadding: 12 } },
          y: { grid: { color: (ctx) => (ctx.tick.value === 0 ? css("--axis") : css("--grid")) }, border: { display: false }, ticks: { callback: (v) => fmtSigned(v) } },
        },
        plugins: { tooltip: { callbacks: { title: (items) => rows[items[0].dataIndex].tip, label: (ctx) => `${fmtSigned(ctx.raw)} ${unitU}` } } },
      },
    }),
    table: () => table([
      { key: "label", label: view === "match" ? "Match" : view === "day" ? "Day" : "Session" },
      { key: "tip", label: "Detail" },
      { key: "value", label: unitU, num: true, format: (x) => deltaNode(x.value) },
    ], [...rows].reverse()),
  }) : card(`${unitU} gained and lost`, null, viewSwitch, noData("No matches with a known rating change yet.")));

  // Promotions & demotions
  const ev = [...r.events].reverse();
  panel.append(card("Promotions and demotions", `Every time ${r.character} changed division or Master tier in this range`,
    ev.length ? h("ul", { class: "events" }, ev.map((e) => h("li", {},
      h("span", { class: `pill ${e.up ? "W" : "L"}`, text: e.up ? "▲" : "▼", "aria-label": e.up ? "Promoted" : "Demoted" }),
      h("span", {}, `${e.from} → `, h("strong", { text: e.to })),
      h("time", { text: fmtDate(e.t) })))) : noData("No rank changes in this range.")));
}

// ---- Matchups ------------------------------------------------------------------------
function renderMatchups(panel) {
  const all = state.stats.matchups;
  const rows = all.filter((r) => r.matches >= state.matchupMin && r.win_rate !== null)
    .sort((a, b) => b.win_rate - a.win_rate || b.matches - a.matches);
  const minSwitch = seg([[1, "All"], [3, "3+ games"], [5, "5+"], [10, "10+"]], state.matchupMin, (v) => { state.matchupMin = v; render(); }, "Minimum games");
  panel.append(rows.length ? chartCard({
    title: "Win rate by opponent character",
    sub: "Blue: you win more than half. Red: you lose more than half. Sorted best to worst.",
    height: rows.length * 28 + 60,
    tools: [minSwitch],
    config: () => winRateBarsConfig(rows, {
      horizontal: true,
      labelFor: (r) => `${r.character} (${r.matches})`,
      extraTooltip: (r) => [r.net_lp !== null ? `Net LP ${fmtSigned(r.net_lp)}` : null, r.net_mr !== null ? `Net MR ${fmtSigned(r.net_mr)}` : null, `Round win rate ${fmtPct(r.round_win_rate)}`].filter(Boolean),
    }),
    table: () => winRateTable(rows.map((r) => ({ ...r, label: r.character })), "Opponent"),
  }) : card("Win rate by opponent character", null, minSwitch, noData("No opponent character meets the minimum games yet.")));

  panel.append(card("All matchups", `${all.length} opponent characters. Rows with fewer than ${Math.max(state.matchupMin, 3)} games are greyed out.`,
    table([
      { key: "character", label: "Opponent" },
      { key: "matches", label: "Games", num: true },
      { key: "wins", label: "W–L", num: true, format: record, sort: (r) => r.wins - r.losses },
      { key: "win_rate", label: "Win rate", num: true, format: (r) => h("span", {}, fmtPct(r.win_rate), h("span", { class: "wr-bar", "aria-hidden": "true" }, h("i", { style: `width:${(r.win_rate || 0) * 100}%` }))) },
      { key: "round_win_rate", label: "Round win rate", num: true, format: (r) => fmtPct(r.round_win_rate) },
      { key: "net_lp", label: "Net LP", num: true, format: (r) => deltaNode(r.net_lp) },
      { key: "avg_lp", label: "Avg LP", num: true, format: (r) => deltaNode(r.avg_lp) },
      { key: "net_mr", label: "Net MR", num: true, format: (r) => deltaNode(r.net_mr) },
      { key: "last_played", label: "Last played", num: true, format: (r) => fmtDay(r.last_played) },
    ], all, { sortKey: "matches", sortDir: "desc", rowClass: (r) => (r.matches < Math.max(state.matchupMin, 3) ? "low-sample" : null) })));
}

// ---- Sessions ----------------------------------------------------------------------
function renderSessions(panel) {
  const s = state.stats.sessions;
  const t = s.tilt;
  const st = s.streaks;
  const streakText = (x) => (x.length ? `${x.length}` : "—");
  panel.append(h("div", { class: "kpis" },
    tile("Play sessions", fmtNum(s.count), `${s.avg_matches ?? "—"} matches on average · new session after ${s.gap_minutes} min idle`),
    tile("After a win", fmtPct(t.after_win.win_rate), `${fmtNum(t.after_win.matches)} matches`),
    tile("After a loss", fmtPct(t.after_loss.win_rate), `${fmtNum(t.after_loss.matches)} matches`),
    tile("After 2 losses in a row", fmtPct(t.after_2_losses.win_rate), `${fmtNum(t.after_2_losses.matches)} matches`),
    tile("After 3 losses in a row", fmtPct(t.after_3_losses.win_rate), `${fmtNum(t.after_3_losses.matches)} matches`),
  ));
  const tiltGap = t.after_win.win_rate !== null && t.after_2_losses.win_rate !== null ? t.after_win.win_rate - t.after_2_losses.win_rate : null;
  if (tiltGap !== null && t.after_2_losses.matches >= 10) {
    panel.append(h("div", { class: "card" }, h("strong", { text: "Tilt check: " }),
      tiltGap >= 0.08
        ? `your win rate drops from ${fmtPct(t.after_win.win_rate, 0)} after a win to ${fmtPct(t.after_2_losses.win_rate, 0)} after two straight losses (${Math.round(tiltGap * 100)} points). A short break after back-to-back losses could save rating.`
        : "your win rate holds up after losing streaks. No sign of tilt in this range."));
  }

  panel.append(h("div", { class: "kpis" },
    tile("Current streak", st.current.type ? `${st.current.length} ${st.current.type === "W" ? "W" : "L"}` : "—", st.current.type === "W" ? "wins in a row" : st.current.type === "L" ? "losses in a row" : ""),
    tile("Longest win streak", streakText(st.longest_win), st.longest_win.end ? `ended ${fmtDay(st.longest_win.end)}` : ""),
    tile("Longest losing streak", streakText(st.longest_loss), st.longest_loss.end ? `ended ${fmtDay(st.longest_loss.end)}` : ""),
  ));

  const pos = s.by_position.filter((r) => r.matches);
  const tod = s.by_time_of_day.filter((r) => r.matches);
  panel.append(h("div", { class: "grid grid-2" },
    pos.length ? chartCard({
      title: "Win rate by match number in a session",
      sub: "Do you get better warmed up, or worse the longer you play?",
      height: 240,
      config: () => winRateBarsConfig(pos.map((r) => ({ ...r, label: `Matches ${r.label}` }))),
      table: () => winRateTable(pos.map((r) => ({ ...r, label: `Matches ${r.label}` })), "Position in session"),
    }) : card("Win rate by match number in a session", null, noData()),
    tod.length ? chartCard({
      title: "Win rate by time of day",
      sub: "Your local time",
      height: 240,
      config: () => winRateBarsConfig(tod),
      table: () => winRateTable(tod, "Time of day"),
    }) : card("Win rate by time of day", null, noData()),
  ));

  panel.append(card("Sessions", "Most recent first",
    table([
      { key: "start", label: "Started", format: (r) => fmtDate(r.start), num: false },
      { key: "minutes", label: "Length", num: true, format: (r) => `${r.minutes} min` },
      { key: "matches", label: "Matches", num: true },
      { key: "wins", label: "W–L", num: true, format: record, sort: (r) => r.wins - r.losses },
      { key: "win_rate", label: "Win rate", num: true, format: (r) => fmtPct(r.win_rate, 0) },
      { key: "net_lp", label: "Net LP", num: true, format: (r) => deltaNode(r.net_lp) },
      { key: "net_mr", label: "Net MR", num: true, format: (r) => deltaNode(r.net_mr) },
      { key: "characters", label: "Played", format: (r) => r.characters.join(", "), sortable: false },
      { key: "results", label: "Results", sortable: false, format: (r) => h("span", { class: "session-strip", "aria-label": r.results }, [...r.results].map((x) => h("i", { class: x }))) },
    ], s.sessions, { sortKey: "start", sortDir: "desc" })));
}

// ---- Opponents -----------------------------------------------------------------------
function renderOpponents(panel) {
  const o = state.stats.opponents;
  const grid = h("div", { class: "grid grid-2" });
  if (o.by_division_gap.length) {
    grid.append(chartCard({
      title: "Win rate vs opponent rank (LP)",
      sub: "Opponent's division compared with yours at match time",
      height: 260,
      config: () => winRateBarsConfig(o.by_division_gap, { extraTooltip: (r) => (r.avg_lp !== null ? [`Avg ${fmtSigned(r.avg_lp)} LP per match`] : []) }),
      table: () => winRateTable(o.by_division_gap, "Opponent rank"),
    }));
  }
  if (o.by_mr_gap.length) {
    grid.append(chartCard({
      title: "Win rate vs opponent Master Rate",
      sub: "Opponent's MR minus yours, Master matches only",
      height: 260,
      config: () => winRateBarsConfig(o.by_mr_gap, { extraTooltip: (r) => (r.avg_mr !== null ? [`Avg ${fmtSigned(r.avg_mr)} MR per match`] : []) }),
      table: () => winRateTable(o.by_mr_gap.map((r) => ({ ...r })), "MR gap"),
    }));
  }
  if (o.by_league.length) {
    grid.append(chartCard({
      title: "Win rate by opponent league",
      sub: "Which leagues you beat, and which beat you",
      height: 260,
      config: () => winRateBarsConfig(o.by_league),
      table: () => winRateTable(o.by_league, "League"),
    }));
  }
  if (!grid.childElementCount) grid.append(card("Opponent strength", null, noData("No opponent rating data in this range.")));
  panel.append(grid);

  panel.append(card("Rivals", `Players you've met more than once · ${fmtNum(o.unique_opponents)} different opponents in this range`,
    o.rivals.length ? table([
      { key: "name", label: "Player", format: (r) => r.name || `#${r.sid}` },
      { key: "characters", label: "Played", format: (r) => r.characters.join(", "), sortable: false },
      { key: "matches", label: "Games", num: true },
      { key: "wins", label: "W–L", num: true, format: record, sort: (r) => r.wins - r.losses },
      { key: "win_rate", label: "Win rate", num: true, format: (r) => fmtPct(r.win_rate, 0) },
      { key: "net_lp", label: "Net LP", num: true, format: (r) => deltaNode(r.net_lp) },
      { key: "last_played", label: "Last met", num: true, format: (r) => fmtDay(r.last_played) },
    ], o.rivals, { sortKey: "matches", sortDir: "desc" }) : noData("No repeat opponents yet.")));
}

// ---- Rounds -------------------------------------------------------------------------
function renderRounds(panel) {
  const r = state.stats.rounds;
  const s = r.summary;
  panel.append(h("div", { class: "kpis" },
    tile("Round win rate", fmtPct(s.round_win_rate), `${fmtNum(s.rounds_won)}–${fmtNum(s.rounds_lost)} rounds`, { hero: true }),
    tile("Won round 1 → won match", fmtPct(r.after_round1_win.win_rate), `${fmtNum(r.after_round1_win.matches)} matches`),
    tile("Lost round 1 → came back", fmtPct(r.after_round1_loss.win_rate), `${fmtNum(r.after_round1_loss.matches)} matches`),
    tile("Deciding rounds won", fmtPct(r.deciding_round.win_rate), `${fmtNum(r.deciding_round.matches)} matches went to a final round`),
    tile("Perfects", `${fmtNum(r.perfects_for)}`, `${fmtNum(r.perfects_against)} against you`),
  ));

  const grid = h("div", { class: "grid grid-2" });
  const scores = r.scores;
  if (scores.length) {
    const won = (sc) => Number(sc.split("-")[0]) > Number(sc.split("-")[1]);
    const total = scores.reduce((a, b) => a + b.matches, 0);
    grid.append(chartCard({
      title: "Match scores",
      sub: "How your matches finish, in rounds",
      height: scores.length * 36 + 50,
      config: () => ({
        type: "bar",
        data: { labels: scores.map((x) => x.score), datasets: [{ data: scores.map((x) => x.matches), backgroundColor: scores.map((x) => (won(x.score) ? winColor() : lossColor())), borderRadius: 4, borderSkipped: "start", maxBarThickness: 24, tipLabel: (v) => `${v} (${Math.round((v / total) * 100)}%)` }] },
        options: {
          indexAxis: "y",
          scales: { x: { grace: "15%", grid: { color: css("--grid") }, border: { display: false } }, y: { grid: { display: false }, border: { color: css("--axis") }, ticks: { color: css("--text-2") } } },
          plugins: {
            tooltip: { callbacks: { title: (i) => `${i[0].label} ${won(i[0].label) ? "win" : "loss"}`, label: (ctx) => `${ctx.raw} matches` } },
          },
        },
      }),
      table: () => table([{ key: "score", label: "Score" }, { key: "matches", label: "Matches", num: true }, { key: "share", label: "Share", num: true, format: (x) => fmtPct(x.matches / total) }], scores),
    }));
  }
  const per = r.per_round.filter((x) => x.round <= 3 && x.win_rate !== null).map((x) => ({ ...x, label: `Round ${x.round}`, matches: x.won + x.lost, wins: x.won, losses: x.lost, draws: x.draws }));
  if (per.length) {
    grid.append(chartCard({
      title: "Win rate by round",
      sub: "Round 3 only happens in close matches",
      height: 240,
      config: () => winRateBarsConfig(per),
      table: () => table([{ key: "label", label: "Round" }, { key: "won", label: "Won", num: true }, { key: "lost", label: "Lost", num: true }, { key: "win_rate", label: "Win rate", num: true, format: (x) => fmtPct(x.win_rate) }], per),
    }));
  }
  panel.append(grid);

  const finishCard = (rows, title, sub, color) => (rows.length ? chartCard({
    title, sub,
    height: rows.length * 34 + 50,
    config: () => ({
      type: "bar",
      data: { labels: rows.map((x) => `${x.label} (${x.short})`), datasets: [{ data: rows.map((x) => x.rounds), backgroundColor: rows.map(() => color()), borderRadius: 4, borderSkipped: "start", maxBarThickness: 22, tipLabel: (v, i) => fmtPct(rows[i].share, 0) }] },
      options: {
        indexAxis: "y",
        scales: { x: { grace: "18%", grid: { color: css("--grid") }, border: { display: false } }, y: { grid: { display: false }, border: { color: css("--axis") }, ticks: { color: css("--text-2") } } },
        plugins: {
          tooltip: { callbacks: { label: (ctx) => `${ctx.raw} rounds (${fmtPct(rows[ctx.dataIndex].share)})` } },
        },
      },
    }),
    table: () => table([{ key: "label", label: "Finish" }, { key: "short", label: "Icon" }, { key: "rounds", label: "Rounds", num: true }, { key: "share", label: "Share", num: true, format: (x) => fmtPct(x.share) }], rows),
  }) : card(title, null, noData("Round finishes come from Buckler syncs; hand-logged matches don't have them.")));

  panel.append(h("div", { class: "grid grid-2" },
    finishCard(r.my_finishes, "How you win rounds", "Finish type of every round you took", winColor),
    finishCard(r.opp_finishes, "How you lose rounds", "Finish type of every round taken from you", lossColor)));
  if (r.detailed_matches < s.matches) {
    panel.append(h("p", { class: "note", text: `Round order and finish types are known for ${fmtNum(r.detailed_matches)} of ${fmtNum(s.matches)} matches (Buckler syncs). Hand-logged matches count toward round totals only.` }));
  }
}

// ---- Matches ------------------------------------------------------------------------
async function renderMatches(panel) {
  const chars = state.meta.all_characters;
  const list = h("datalist", { id: "char-list" }, chars.map((c) => h("option", { value: c })));
  const lastMine = state.meta.my_characters.length ? (state.stats.rank.character || state.meta.my_characters[0]) : "";
  const now = new Date();
  const localNow = new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  const status = h("span", { class: "status" });
  const form = h("form", { class: "form-grid", autocomplete: "off" },
    list,
    field("Date and time", h("input", { type: "datetime-local", name: "played_at", value: localNow, required: true })),
    field("My character", h("input", { type: "text", name: "my_character", list: "char-list", value: lastMine, required: true })),
    field("Opponent character", h("input", { type: "text", name: "opp_character", list: "char-list", required: true })),
    field("Result", h("select", { name: "result" }, h("option", { value: "W", text: "Win" }), h("option", { value: "L", text: "Loss" }), h("option", { value: "D", text: "Draw" }))),
    field("Rounds won", h("select", { name: "rounds_won" }, ["", "0", "1", "2"].map((v) => h("option", { value: v, text: v || "—" })))),
    field("Rounds lost", h("select", { name: "rounds_lost" }, ["", "0", "1", "2"].map((v) => h("option", { value: v, text: v || "—" })))),
    field("My LP after match", h("input", { type: "number", name: "my_lp", min: "0", placeholder: "e.g. 12450" })),
    field("My MR after match", h("input", { type: "number", name: "my_mr", min: "0", placeholder: "Master only" })),
    field("Opponent LP", h("input", { type: "number", name: "opp_lp", min: "0" })),
    field("Opponent MR", h("input", { type: "number", name: "opp_mr", min: "0" })),
    field("Opponent name", h("input", { type: "text", name: "opp_name", maxlength: "40" })),
    field("Notes", h("input", { type: "text", name: "notes", maxlength: "200" }), "wide"),
  );
  const submit = h("button", { class: "btn btn-primary", type: "submit", text: "Add match" });
  form.append(h("div", { class: "form-actions", style: "grid-column:1/-1" }, submit, status));
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const data = Object.fromEntries(new FormData(form).entries());
    data.played_at = Math.floor(new Date(data.played_at) / 1000);
    submit.disabled = true;
    try {
      await api("/api/matches", { method: "POST", body: JSON.stringify(data) });
      toast("Match added.");
      form.elements.opp_character.value = "";
      form.elements.opp_name.value = "";
      form.elements.notes.value = "";
      await reloadAll();
    } catch (err) {
      status.className = "status error";
      status.textContent = err.message;
    } finally {
      submit.disabled = false;
    }
  });
  panel.append(card("Log a match by hand", "For matches Buckler missed, or if you'd rather not sync. Enter LP/MR as shown on the result screen.", form));

  const holder = card("Match history", "Ranked matches in the current filter, newest first");
  panel.append(holder);
  if (!state.matches) {
    holder.append(noData("Loading…"));
    state.matches = (await api(`/api/matches?${filterParams()}`)).matches;
    if (state.tab !== "matches") return;
    holder.lastChild.remove();
  }
  const rows = state.matches.slice(0, state.matchLimit);
  holder.append(rows.length ? table([
    { key: "played_at", label: "Date", format: (m) => fmtDate(m.played_at) },
    { key: "my_character", label: "Me" },
    { key: "opp_character", label: "Opponent" },
    { key: "opp_name", label: "Player", format: (m) => m.opp_name || "—" },
    { key: "result", label: "Result", format: (m) => h("span", { class: `pill ${m.result}`, text: m.result }) },
    { key: "rounds_won", label: "Score", num: true, format: (m) => (m.rounds_won !== null ? `${m.rounds_won}–${m.rounds_lost}` : "—"), sortable: false },
    { key: "lp_after", label: "LP", num: true, format: (m) => fmtNum(m.lp_after ?? m.lp_before) },
    { key: "lp_delta", label: "LP ±", num: true, format: (m) => deltaNode(m.lp_delta) },
    { key: "mr_after", label: "MR", num: true, format: (m) => fmtNum(m.mr_after ?? m.mr_before) },
    { key: "mr_delta", label: "MR ±", num: true, format: (m) => deltaNode(m.mr_delta) },
    { key: "source", label: "Source", format: (m) => (m.source === "manual" ? "Manual" : "Buckler") },
    { key: "id", label: "", sortable: false, format: (m) => h("button", { class: "btn btn-small btn-danger", type: "button", text: "Delete", "aria-label": `Delete match from ${fmtDate(m.played_at)}`, onclick: () => deleteMatch(m) }) },
  ], rows, { sortKey: "played_at", sortDir: "desc" }) : noData("No matches in this filter."));
  if (state.matches.length > state.matchLimit) {
    holder.append(h("div", { class: "form-actions" }, h("button", { class: "btn", type: "button", text: `Show more (${fmtNum(state.matches.length - state.matchLimit)} left)`, onclick: () => { state.matchLimit += 200; render(); } })));
  }
}

function field(label, input, cls) {
  return h("label", { class: `field${cls ? ` ${cls}` : ""}` }, h("span", { text: label }), input);
}

async function deleteMatch(m) {
  const what = `${m.result === "W" ? "win" : m.result === "L" ? "loss" : "draw"} vs ${m.opp_character} on ${fmtDate(m.played_at)}`;
  const extra = m.source === "buckler" ? "\n\nIt came from Buckler, so the next sync will add it back if Buckler still lists it." : "";
  if (!confirm(`Delete the ${what}?${extra}`)) return;
  try {
    await api(`/api/matches/${m.id}`, { method: "DELETE" });
    toast("Match deleted.");
    await reloadAll();
  } catch (err) {
    toast(err.message);
  }
}

// ---- Sync --------------------------------------------------------------------------
function renderSync(panel) {
  const cfg = state.meta.config;
  const timing = state.stats ? state.stats.timing : null;

  // Profile
  const sidInput = h("input", { type: "text", value: cfg.sid || "", placeholder: "e.g. 1234567890 or your profile URL", style: "min-width:280px" });
  const sidStatus = h("span", { class: "status" });
  panel.append(card("1. Your Buckler profile", "Your user code is the number at the end of your Buckler profile URL: streetfighter.com/6/buckler/profile/<user code>",
    h("div", { class: "form-actions" }, sidInput,
      h("button", { class: "btn", type: "button", text: "Save", onclick: async () => {
        try { await api("/api/config", { method: "POST", body: JSON.stringify({ sid: sidInput.value }) }); await loadMeta(); render(); toast("User code saved."); }
        catch (e) { sidStatus.className = "status error"; sidStatus.textContent = e.message; }
      } }), sidStatus)));

  // Cookie sync
  const cookieInput = h("input", { type: "password", placeholder: cfg.cookie_set ? "A cookie is saved. Paste a new one to replace it." : "Paste the Cookie header (or just the buckler_id value)", style: "flex:1;min-width:260px", autocomplete: "off" });
  const syncStatus = h("span", { class: "status" });
  const syncBtn = h("button", { class: "btn btn-primary", type: "button", text: "Sync now", disabled: !(cfg.sid && cfg.cookie_set) });
  syncBtn.addEventListener("click", () => runSync(syncBtn, syncStatus));
  const auto = h("select", {}, [[0, "Off"], [10, "Every 10 minutes"], [20, "Every 20 minutes"], [30, "Every 30 minutes"], [60, "Every hour"]].map(([v, t]) => h("option", { value: v, text: t, selected: Number(cfg.auto_sync_minutes) === v })));
  auto.addEventListener("change", async () => { await api("/api/config", { method: "POST", body: JSON.stringify({ auto_sync_minutes: Number(auto.value) }) }); await loadMeta(); toast("Auto sync updated."); });
  panel.append(card("2. Sync with your Buckler cookie", "One click (or automatic) sync. The cookie is stored only in this app's data folder and is sent only to streetfighter.com.",
    h("ol", { class: "steps" },
      h("li", {}, "Log in at ", h("a", { href: "https://www.streetfighter.com/6/buckler", target: "_blank", rel: "noopener", text: "streetfighter.com/6/buckler" }), " in your browser."),
      h("li", {}, "Press ", h("kbd", { text: "F12" }), ", open the ", h("strong", { text: "Network" }), " tab and reload the page."),
      h("li", {}, "Click the first request, find ", h("strong", { text: "Request Headers → Cookie" }), " and copy its whole value. (Or copy just the ", h("code", { text: "buckler_id" }), " cookie from Application → Cookies.)"),
      h("li", {}, "Paste it below and save, then press Sync now. Cookies expire after a few weeks; repeat this when sync says so.")),
    h("form", { class: "form-actions", onsubmit: (e) => e.preventDefault() }, cookieInput,
      h("button", { class: "btn", type: "button", text: "Save cookie", onclick: async () => {
        if (!cookieInput.value.trim()) return;
        await api("/api/config", { method: "POST", body: JSON.stringify({ cookie: cookieInput.value }) });
        cookieInput.value = "";
        await loadMeta(); render(); toast("Cookie saved.");
      } }),
      cfg.cookie_set ? h("button", { class: "btn btn-danger", type: "button", text: "Forget cookie", onclick: async () => { await api("/api/config", { method: "POST", body: JSON.stringify({ cookie: "", auto_sync_minutes: 0 }) }); await loadMeta(); render(); } }) : null),
    h("div", { class: "form-actions" }, syncBtn, field("Auto sync while the tracker runs", auto), syncStatus),
    state.meta.auto_sync_paused ? h("p", { class: "status error", text: `Auto sync paused: ${state.meta.auto_sync_paused}` }) : null,
    h("p", { class: "note", text: "Buckler only keeps your most recent matches (about 100), so sync at least once per play session. The tracker keeps everything it has seen." })));

  // Browser collector
  const fileInput = h("input", { type: "file", accept: "application/json,.json" });
  const importStatus = h("span", { class: "status" });
  const bm = h("a", { class: "bookmarklet", href: "#", text: "SF6 Tracker: collect", title: "Drag me to your bookmarks bar" });
  bm.addEventListener("click", (e) => { e.preventDefault(); toast("Drag this button to your bookmarks bar, then click it while on Buckler's Boot Camp."); });
  const copyBtn = h("button", { class: "btn", type: "button", text: "Copy collector script" });
  api("/api/collector").then(({ script }) => {
    bm.href = `javascript:${encodeURIComponent(script)}`;
    copyBtn.onclick = async () => {
      try { await navigator.clipboard.writeText(script); toast("Collector copied. Paste it into the browser console on Buckler."); }
      catch (e) { toast("Couldn't copy automatically; drag the bookmark button instead."); }
    };
  }).catch(() => {});
  panel.append(card("3. Or: collect from your browser", "Use this if cookie sync is blocked by Capcom's bot protection. It runs inside your logged-in Buckler tab, so no cookie is needed.",
    h("ol", { class: "steps" },
      h("li", {}, "Drag this to your bookmarks bar: ", bm, " (or use ", copyBtn, " and paste it into the browser console)."),
      h("li", {}, "Open your Buckler's Boot Camp profile while logged in and click the bookmark."),
      h("li", {}, "It reads your ranked battle log and sends it here. If your browser blocks that, it downloads a file instead: import it below.")),
    h("div", { class: "form-actions" }, fileInput,
      h("button", { class: "btn", type: "button", text: "Import file", onclick: async () => {
        const f = fileInput.files[0];
        if (!f) return;
        importStatus.className = "status";
        importStatus.textContent = "Importing…";
        try {
          const body = await f.text();
          const rep = await api("/api/import", { method: "POST", body });
          importStatus.textContent = `${rep.ranked} ranked matches in file, ${rep.added} new added.`;
          await reloadAll();
        } catch (e) {
          importStatus.className = "status error";
          importStatus.textContent = e.message;
        }
      } }), importStatus)));

  // Settings
  const timingSel = h("select", {}, [["auto", "Detect automatically"], ["pre", "Before the match"], ["post", "After the match"]].map(([v, t]) => h("option", { value: v, text: t, selected: cfg.lp_timing === v })));
  const gapInput = h("input", { type: "number", min: "5", max: "600", value: cfg.session_gap_minutes, style: "width:100px" });
  const detected = timing && timing.pairs
    ? `Detected: Buckler shows LP/MR from ${timing.timing === "pre" ? "before" : "after"} each match (${fmtPct(timing.agreement, 0)} of ${timing.pairs} rating changes agree).`
    : "Not enough synced matches to detect this yet.";
  panel.append(card("Settings", null,
    h("div", { class: "form-actions" },
      field("Buckler's LP/MR values are from", timingSel),
      field("New session after (minutes idle)", gapInput),
      h("button", { class: "btn", type: "button", text: "Save settings", onclick: async () => {
        await api("/api/config", { method: "POST", body: JSON.stringify({ lp_timing: timingSel.value, session_gap_minutes: Number(gapInput.value) }) });
        await reloadAll(); toast("Settings saved.");
      } })),
    h("p", { class: "note", text: detected })));

  // History
  const syncs = state.meta.syncs;
  panel.append(card("Sync history", null, syncs.length ? table([
    { key: "at", label: "When", format: (r) => fmtDate(r.at) },
    { key: "source", label: "How" },
    { key: "status", label: "Result", format: (r) => (r.status === "ok" ? "OK" : "Failed") },
    { key: "added", label: "New matches", num: true },
    { key: "message", label: "Details", format: (r) => h("span", { style: "white-space:normal", text: r.message || "" }) },
  ], syncs, { sortKey: "at", sortDir: "desc" }) : noData("Nothing synced yet.")));
}

async function runSync(btn, statusEl) {
  btn.disabled = true;
  const label = btn.textContent;
  btn.textContent = "Syncing…";
  if (statusEl) { statusEl.className = "status"; statusEl.textContent = "Reading your ranked battle log from Buckler. This takes a few seconds per page."; }
  try {
    const rep = await api("/api/sync", { method: "POST" });
    const msg = `Synced: ${rep.added} new ranked match${rep.added === 1 ? "" : "es"} (${rep.pages} page${rep.pages === 1 ? "" : "s"} read).`;
    if (statusEl) statusEl.textContent = msg;
    toast(msg);
    await reloadAll();
  } catch (e) {
    if (statusEl) { statusEl.className = "status error"; statusEl.textContent = e.message; }
    toast(`Sync failed: ${e.message}`, 6000);
    await loadMeta().catch(() => {});
  } finally {
    btn.disabled = false;
    btn.textContent = label;
  }
}

// ---- rank tables (mirrors sf6tracker/ranks.py) -------------------------------------------
const DIVISIONS = (() => {
  const out = [];
  for (const [league, start, width] of [["Rookie", 0, 200], ["Iron", 1000, 400], ["Bronze", 3000, 400], ["Silver", 5000, 800], ["Gold", 9000, 800], ["Platinum", 13000, 1200], ["Diamond", 19000, 1200]]) {
    for (let n = 0; n < 5; n++) out.push([`${league} ${n + 1}`, start + n * width]);
  }
  out.push(["Master", 25000]);
  return out;
})();
const MASTER_TIERS = [["Master start", 1500], ["High Master", 1600], ["Grand Master", 1700], ["Ultimate Master", 1800]];

function compact(v) {
  return Math.abs(v) >= 10000 ? `${(v / 1000).toFixed(v % 1000 === 0 ? 0 : 1)}K` : v.toLocaleString();
}

function hexAlpha(hex, a) {
  const m = hex.replace("#", "");
  const n = parseInt(m.length === 3 ? m.split("").map((c) => c + c).join("") : m, 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${a})`;
}

// =====================================================================================
// Wiring
// =====================================================================================
function selectTab(name, push = true) {
  if (!PANELS[name]) name = "overview";
  state.tab = name;
  $$(".tabs button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === name)));
  if (push) history.replaceState(null, "", `#${name}`);
  render();
}

function init() {
  $$(".tabs button").forEach((b) => b.addEventListener("click", () => selectTab(b.dataset.tab)));
  document.addEventListener("click", (e) => {
    const a = e.target.closest("[data-goto]");
    if (a) { e.preventDefault(); selectTab(a.dataset.goto); }
  });
  $("#f-range").addEventListener("change", () => {
    const custom = $("#f-range").value === "custom";
    $$(".custom-range").forEach((x) => { x.hidden = !custom; });
    if (!custom) loadStats();
  });
  $("#f-from").addEventListener("change", loadStats);
  $("#f-to").addEventListener("change", loadStats);
  $("#f-char").addEventListener("change", () => { state.rankMetric = null; loadStats(); });
  $("#quick-sync").addEventListener("click", (e) => runSync(e.currentTarget, null));
  $("#theme-toggle").addEventListener("click", () => {
    const dark = document.documentElement.dataset.theme
      ? document.documentElement.dataset.theme === "dark"
      : matchMedia("(prefers-color-scheme: dark)").matches;
    const next = dark ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("sf6t-theme", next); } catch (e) { /* private mode */ }
    if (state.stats) render();
  });
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { if (state.stats) render(); });

  state.tab = PANELS[location.hash.slice(1)] ? location.hash.slice(1) : "overview";
  $$(".tabs button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === state.tab)));
  reloadAll().then(() => {
    if (!state.meta.match_count && state.tab === "overview") selectTab("sync");
  }).catch((e) => {
    $("#main").replaceChildren(h("div", { class: "empty" }, h("h2", { text: "Can't reach the tracker" }), h("p", { text: e.message })));
  });
}

init();
