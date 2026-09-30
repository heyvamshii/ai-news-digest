/* AI News Digest dashboard.
 *
 * Reads the JSON files written by build_site.py:
 *   data/index.json            every issue + totals + chart data
 *   data/issues/<date>.json    one day's newsletter
 *   data/articles.json         recent articles for search
 *
 * All text is inserted with textContent (never innerHTML), and only http(s)
 * links are rendered, so scraped content can't inject markup or scripts.
 */
"use strict";

const SVG_NS = "http://www.w3.org/2000/svg";
const DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const CATEGORY_ORDER = ["Models", "Research", "Tools", "Business", "Policy"];
const MAX_SOURCE_BARS = 10;
const MAX_RESULTS = 60;
const RECENT_COUNT = 8;

const state = {
  index: null,
  issueDates: new Set(),
  issueCache: new Map(),
  selected: null,
  month: null,                 // Date at the 1st of the month shown in the calendar
  articles: [],
  query: "",
  category: "All",
};

const $ = (id) => document.getElementById(id);

/* ---------- small DOM helpers ---------- */

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "text") node.textContent = value;
    else if (key === "className") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of [].concat(children)) {
    if (child !== null && child !== undefined) node.append(child);
  }
  return node;
}

function svg(tag, attrs = {}) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  return node;
}

function safeUrl(url) {
  return typeof url === "string" && /^https?:\/\//i.test(url) ? url : null;
}

/* PDFs: a web link when published, or a plain relative path (../file.pdf) on a local preview. */
function safePdf(url) {
  if (safeUrl(url)) return url;
  return typeof url === "string" && /^\.\.\/[\w.-]+\.pdf$/.test(url) ? url : null;
}

function externalLink(url, text, className) {
  const href = safeUrl(url);
  if (!href) return el("span", { className, text });
  return el("a", { href, text, className, target: "_blank", rel: "noopener noreferrer" });
}

const fmt = new Intl.NumberFormat("en-IN");
const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const parseDay = (s) => { const [y, m, d] = s.split("-").map(Number); return new Date(y, m - 1, d); };
const shortDate = (s) => parseDay(s).toLocaleDateString("en-GB", { day: "numeric", month: "short" });

async function getJSON(path) {
  const response = await fetch(path, { cache: "no-cache" });
  if (!response.ok) throw new Error(`${path}: HTTP ${response.status}`);
  return response.json();
}

/* ---------- header + stat tiles ---------- */

function renderHeader() {
  const { generated_at: generated, latest } = state.index;
  const when = new Date(generated).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" });
  $("updated").textContent = `Updated ${when}`;
  const button = $("latest-btn");
  button.disabled = !latest;
  button.onclick = () => latest && selectIssue(latest);
}

function renderStats() {
  const t = state.index.totals;
  const tiles = [
    ["Issues published", t.issues],
    ["Articles collected", t.articles],
    ["Sources tracked", t.sources],
    ["Stories summarised", t.summarised],
  ];
  $("stats").replaceChildren(...tiles.map(([label, value]) =>
    el("div", { className: "stat" }, [
      el("p", { className: "stat-label", text: label }),
      el("p", { className: "stat-value", text: fmt.format(value) }),
    ])));
}

/* ---------- calendar ---------- */

function monthBounds() {
  const dates = state.index.issues.map((i) => i.date).sort();
  const first = dates.length ? parseDay(dates[0]) : new Date();
  const last = dates.length ? parseDay(dates[dates.length - 1]) : new Date();
  return [new Date(first.getFullYear(), first.getMonth(), 1), new Date(last.getFullYear(), last.getMonth(), 1)];
}

function renderCalendar() {
  const month = state.month;
  const [min, max] = monthBounds();
  $("cal-title").textContent = month.toLocaleDateString("en-GB", { month: "long", year: "numeric" });
  $("cal-prev").disabled = month <= min;
  $("cal-next").disabled = month >= max;

  const cells = DOW.map((d) => el("div", { className: "cal-dow", text: d, "aria-hidden": "true" }));
  const offset = (month.getDay() + 6) % 7;                  // Monday-first grid
  for (let i = 0; i < offset; i++) cells.push(el("span"));
  const days = new Date(month.getFullYear(), month.getMonth() + 1, 0).getDate();
  const today = iso(new Date());

  for (let day = 1; day <= days; day++) {
    const date = iso(new Date(month.getFullYear(), month.getMonth(), day));
    const has = state.issueDates.has(date);
    const classes = ["cal-day", has && "has-issue", date === today && "is-today", date === state.selected && "is-selected"]
      .filter(Boolean).join(" ");
    cells.push(el("button", {
      type: "button",
      className: classes,
      text: String(day),
      disabled: !has,
      "aria-label": `${parseDay(date).toDateString()}${has ? ", issue available" : ", no issue"}`,
      "aria-pressed": date === state.selected ? "true" : "false",
      onclick: () => selectIssue(date),
    }));
  }
  $("cal-grid").replaceChildren(...cells);
}

function shiftMonth(step) {
  state.month = new Date(state.month.getFullYear(), state.month.getMonth() + step, 1);
  renderCalendar();
}

/* ---------- recent issues ---------- */

function renderRecent() {
  const recent = [...state.index.issues].reverse().slice(0, RECENT_COUNT);
  $("recent").replaceChildren(...recent.map((issue) => el("li", {}, el("button", {
    type: "button",
    "aria-current": issue.date === state.selected ? "true" : "false",
    onclick: () => selectIssue(issue.date),
  }, [
    el("span", { text: parseDay(issue.date).toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" }) }),
    el("span", { className: "count", text: `${issue.article_count} articles` }),
  ]))));
}

/* ---------- the newsletter reader ---------- */

async function loadIssue(date) {
  if (!state.issueCache.has(date)) state.issueCache.set(date, await getJSON(`data/issues/${date}.json`));
  return state.issueCache.get(date);
}

function storyItem(story) {
  const meta = el("div", { className: "story-meta" }, [
    el("span", { text: story.source }),
    story.category ? el("span", { className: "tag", text: story.category }) : null,
    story.importance ? el("span", { className: "score", text: `importance ${story.importance}/10` }) : null,
    el("span", { text: shortDate(story.published) }),
  ]);
  return el("li", { className: "story" }, [
    el("h4", { className: "story-title" }, externalLink(story.url, story.title)),
    meta,
    story.summary ? el("p", { className: "story-summary", text: story.summary }) : null,
    safeUrl(story.url) ? externalLink(story.url, "Read the article ↗", "read-link") : null,
  ]);
}

function alsoBlock(also) {
  if (!also.length) return [];
  const rank = (c) => (CATEGORY_ORDER.includes(c) ? CATEGORY_ORDER.indexOf(c) : 99);   // unknown last
  const sorted = [...also].sort((a, b) => rank(a.category) - rank(b.category));
  const groups = new Map();
  for (const item of sorted) {
    const key = item.category || "Other";
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(item);
  }
  return [
    el("h3", { className: "block-title", text: "Also worth knowing" }),
    ...[...groups].map(([category, items]) => el("div", { className: "also-group" }, [
      el("h4", { text: category }),
      el("ul", {}, items.map((a) => el("li", {}, [externalLink(a.url, a.title), " ", el("span", { className: "src", text: `(${a.source})` })]))),
    ])),
  ];
}

function renderIssue(issue, notice = "") {
  const reader = $("reader");
  const actions = el("div", { className: "reader-actions" }, [
    safePdf(issue.pdf) ? el("a", { className: "btn btn-accent", href: safePdf(issue.pdf), target: "_blank", rel: "noopener noreferrer", text: "Download PDF" }) : null,
    el("button", { type: "button", className: "btn btn-ghost", text: "Copy link to this issue", onclick: copyLink }),
  ]);
  const parts = [
    notice ? el("p", { className: "notice notice-top", text: notice }) : null,
    el("h2", { className: "reader-date", text: issue.date_label }),
    el("p", { className: "reader-meta" }, [
      el("span", { text: `${issue.article_count} articles scanned` }),
      el("span", { text: `${issue.source_count} sources` }),
      el("span", { text: `Summaries: ${issue.mode}` }),
    ]),
    actions,
    issue.rebuilt ? el("p", { className: "notice", text: "This issue was published before the dashboard existed, so its \"Today in AI\" summary isn't available. The stories and links are complete." }) : null,
    issue.overview.length ? el("section", { className: "overview", "aria-label": "Today in AI" }, [
      el("h3", { text: "Today in AI" }),
      el("ul", {}, issue.overview.map((point) => el("li", { text: point }))),
    ]) : null,
    issue.top.length ? el("h3", { className: "block-title", text: "Top stories" }) : null,
    issue.top.length ? el("ol", { className: "stories" }, issue.top.map(storyItem)) : null,
    ...alsoBlock(issue.also),
    issue.notes.length ? el("p", { className: "reader-foot", text: issue.notes.join(" ") }) : null,
  ];
  reader.replaceChildren(...parts.filter(Boolean));
}

function renderEmpty(title, text) {
  $("reader").replaceChildren(el("div", { className: "empty" }, el("div", {}, [
    el("h2", { text: title }), el("p", { text }),
  ])));
}

async function selectIssue(date, { replace = false, notice = "" } = {}) {
  if (!state.issueDates.has(date)) return;
  state.selected = date;
  const day = parseDay(date);
  state.month = new Date(day.getFullYear(), day.getMonth(), 1);
  if (location.hash !== `#${date}`) {
    // pushState lets the browser's Back button step between issues.
    history[replace ? "replaceState" : "pushState"](null, "", `#${date}`);
  }
  renderCalendar();
  renderRecent();
  try {
    const issue = await loadIssue(date);
    if (state.selected !== date) return;       // user clicked another date meanwhile
    renderIssue(issue, notice);
  } catch (error) {
    if (state.selected === date) renderEmpty("Couldn't load this issue", "Please refresh the page and try again.");
  }
}

async function copyLink() {
  const label = "Copy link to this issue";
  try {
    await navigator.clipboard.writeText(location.href);
    this.textContent = "Link copied";
  } catch {
    this.textContent = "Copy failed: use the address bar";
  }
  setTimeout(() => { this.textContent = label; }, 2000);
}

/* ---------- charts (hand-drawn SVG: single series, one accent colour) ---------- */

const tooltip = () => $("tooltip");

function showTip(event, text) {
  const tip = tooltip();
  tip.textContent = text;
  tip.hidden = false;
  const box = (event.currentTarget || event.target).getBoundingClientRect();
  const x = event.clientX ?? box.left + box.width / 2;
  const y = event.clientY ?? box.top;
  tip.style.left = `${Math.min(x + 12, window.innerWidth - tip.offsetWidth - 8)}px`;
  tip.style.top = `${Math.max(y - tip.offsetHeight - 10, 8)}px`;
}
const hideTip = () => { tooltip().hidden = true; };

function tableView(rows, labelHead, valueHead) {
  return el("details", {}, [
    el("summary", { text: "Show as table" }),
    el("table", {}, [
      el("thead", {}, el("tr", {}, [el("th", { text: labelHead }), el("th", { text: valueHead })])),
      el("tbody", {}, rows.map((r) => el("tr", {}, [el("td", { text: r.label }), el("td", { text: fmt.format(r.value) })]))),
    ]),
  ]);
}

/* Draw at the real on-screen width so text stays 12px on phones and desktops alike. */
function chartWidth(container) {
  return Math.max(Math.round(container.clientWidth), 260);
}

/* Horizontal bars: label on the left, value at the bar tip, tooltip on hover. */
function barChart(container, rows, noun) {
  if (!rows.length) { container.replaceChildren(el("p", { className: "muted", text: "No data yet." })); return; }
  const width = chartWidth(container), labelW = width < 420 ? 104 : 130, rowH = 30, barH = 16, pad = 36;
  const height = rows.length * rowH;
  const max = Math.max(...rows.map((r) => r.value));
  const scale = (v) => (v / max) * (width - labelW - pad);
  const chart = svg("svg", { viewBox: `0 0 ${width} ${height}`, role: "img", "aria-label": `${noun}: ${rows.map((r) => `${r.label} ${r.value}`).join(", ")}` });

  rows.forEach((r, i) => {
    const y = i * rowH;
    const w = Math.max(scale(r.value), 2);
    const g = svg("g", { tabindex: "0" });
    const label = svg("text", { x: labelW - 10, y: y + rowH / 2 + 4, "text-anchor": "end", class: "label" });
    label.textContent = r.label.length > 18 ? `${r.label.slice(0, 17)}…` : r.label;
    // 4px rounded data-end, square at the baseline: a rounded rect plus a square cap on the left.
    const bar = svg("path", {
      class: "bar",
      d: `M${labelW},${y + (rowH - barH) / 2} h${Math.max(w - 4, 0)} a4,4 0 0 1 4,4 v${barH - 8} a4,4 0 0 1 -4,4 h-${Math.max(w - 4, 0)} z`,
    });
    const value = svg("text", { x: labelW + w + 6, y: y + rowH / 2 + 4, class: "value" });
    value.textContent = fmt.format(r.value);
    const hit = svg("rect", { class: "hit", x: 0, y, width, height: rowH });
    const tip = `${r.label}: ${fmt.format(r.value)} ${noun}`;
    for (const node of [hit, g]) {
      node.addEventListener("mousemove", (e) => showTip(e, tip));
      node.addEventListener("mouseleave", hideTip);
    }
    g.addEventListener("focus", (e) => showTip(e, tip));
    g.addEventListener("blur", hideTip);
    g.append(label, bar, value, hit);
    chart.append(g);
  });
  container.replaceChildren(chart, tableView(rows, "Name", "Articles"));
}

/* Columns for the daily trend: hairline grid, label only the peak, tooltip per day. */
function columnChart(container, days) {
  const width = chartWidth(container), height = 190, left = 34, bottom = 24, top = 14;
  const plotH = height - bottom - top;
  const max = Math.max(1, ...days.map((d) => d.n));
  const nice = Math.ceil(max / 10) * 10 || 10;
  const slot = (width - left) / days.length;
  const barW = Math.min(18, slot - 2);
  const chart = svg("svg", { viewBox: `0 0 ${width} ${height}`, role: "img", "aria-label": "Articles collected per day for the last 30 days" });

  for (const tick of [0, nice / 2, nice]) {
    const y = top + plotH - (tick / nice) * plotH;
    chart.append(svg("line", { class: "grid", x1: left, x2: width, y1: y, y2: y }));
    const t = svg("text", { x: left - 6, y: y + 4, "text-anchor": "end" });
    t.textContent = fmt.format(tick);
    chart.append(t);
  }
  const peak = days.reduce((best, d) => (d.n > best.n ? d : best), days[0]);
  days.forEach((d, i) => {
    const x = left + i * slot + (slot - barW) / 2;
    const h = (d.n / nice) * plotH;
    const y = top + plotH - h;
    const g = svg("g", { tabindex: d.n ? "0" : "-1" });
    if (d.n) {
      const r = Math.min(4, h);
      g.append(svg("path", { class: "bar", d: `M${x},${top + plotH} v-${h - r} a${r},${r} 0 0 1 ${r},-${r} h${barW - 2 * r} a${r},${r} 0 0 1 ${r},${r} v${h - r} z` }));
    }
    if (d === peak && d.n) {
      const v = svg("text", { x: x + barW / 2, y: y - 4, "text-anchor": "middle", class: "value" });
      v.textContent = fmt.format(d.n);
      g.append(v);
    }
    const labelEvery = width < 560 ? 10 : 5;
    if (i % labelEvery === 0 || i === days.length - 1) {
      const t = svg("text", { x: x + barW / 2, y: height - 6, "text-anchor": "middle" });
      t.textContent = shortDate(d.day);
      g.append(t);
    }
    const hit = svg("rect", { class: "hit", x: left + i * slot, y: top, width: slot, height: plotH });
    const tip = `${shortDate(d.day)}: ${fmt.format(d.n)} articles`;
    hit.addEventListener("mousemove", (e) => showTip(e, tip));
    hit.addEventListener("mouseleave", hideTip);
    g.addEventListener("focus", (e) => showTip(e, tip));
    g.addEventListener("blur", hideTip);
    g.append(hit);
    chart.append(g);
  });
  container.replaceChildren(chart, tableView(days.map((d) => ({ label: d.day, value: d.n })), "Day", "Articles"));
}

function renderCharts() {
  const { by_category: cats, by_source: sources, daily } = state.index;
  barChart($("chart-category"), cats.map((c) => ({ label: c.name, value: c.n })), "articles");
  const top = sources.slice(0, MAX_SOURCE_BARS).map((s) => ({ label: s.name, value: s.n }));
  const rest = sources.slice(MAX_SOURCE_BARS).reduce((sum, s) => sum + s.n, 0);
  if (rest) top.push({ label: "Other sources", value: rest });
  barChart($("chart-source"), top, "articles");
  columnChart($("chart-daily"), daily);
}

/* ---------- search ---------- */

function renderChips() {
  const names = ["All", ...CATEGORY_ORDER];
  $("chips").replaceChildren(...names.map((name) => el("button", {
    type: "button", className: "chip", text: name,
    "aria-pressed": name === state.category ? "true" : "false",
    onclick: () => { state.category = name; renderChips(); renderResults(); },
  })));
}

function renderResults() {
  const q = state.query.trim().toLowerCase();
  const matches = state.articles.filter((a) =>
    (state.category === "All" || a.category === state.category) &&
    (!q || a.title.toLowerCase().includes(q) || a.source.toLowerCase().includes(q)));
  $("search-count").textContent = `${fmt.format(matches.length)} article${matches.length === 1 ? "" : "s"}` +
    (matches.length > MAX_RESULTS ? ` (showing the newest ${MAX_RESULTS})` : "");
  $("results").replaceChildren(...matches.slice(0, MAX_RESULTS).map((a) => el("li", { className: "result" }, [
    el("div", {}, [
      externalLink(a.url, a.title, "title"),
      el("div", { className: "meta", text: [a.source, a.category, shortDate(a.published)].filter(Boolean).join(" · ") }),
    ]),
    a.featured_on && state.issueDates.has(a.featured_on)
      ? el("button", { type: "button", className: "btn btn-ghost go", text: `In ${shortDate(a.featured_on)} issue`, onclick: () => { selectIssue(a.featured_on); $("reader").scrollIntoView({ behavior: "smooth" }); } })
      : null,
  ])));
}

/* ---------- start-up ---------- */

async function init() {
  $("cal-prev").addEventListener("click", () => shiftMonth(-1));
  $("cal-next").addEventListener("click", () => shiftMonth(1));
  $("search").addEventListener("input", (e) => { state.query = e.target.value; renderResults(); });
  let resizeTimer;
  let lastWidth = window.innerWidth;
  window.addEventListener("resize", () => {
    if (!state.index || window.innerWidth === lastWidth) return;
    lastWidth = window.innerWidth;
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(renderCharts, 150);
  });
  window.addEventListener("hashchange", () => {
    const date = location.hash.slice(1);
    if (date !== state.selected) selectIssue(date);
  });

  try {
    state.index = await getJSON("data/index.json");
  } catch (error) {
    $("updated").textContent = "Data unavailable";
    renderEmpty("No data yet", "The dashboard fills in after the first daily run.");
    return;
  }
  state.issueDates = new Set(state.index.issues.map((i) => i.date));
  state.month = monthBounds()[1];
  renderHeader();
  renderStats();
  renderCharts();
  renderChips();

  const wanted = location.hash.slice(1);
  const known = state.issueDates.has(wanted);
  const start = known ? wanted : state.index.latest;
  // An email link can arrive a few minutes before that day's issue is deployed.
  const notice = wanted && !known && /^\d{4}-\d{2}-\d{2}$/.test(wanted)
    ? `The issue for ${wanted} isn't on the dashboard yet (it appears a few minutes after the email). Showing the latest issue.`
    : "";
  if (start) await selectIssue(start, { replace: true, notice });
  else { renderCalendar(); renderRecent(); renderEmpty("No issues yet", "The first issue appears after the next daily run."); }

  try {
    state.articles = await getJSON("data/articles.json");
  } catch {
    state.articles = [];
  }
  renderResults();
}

init();
