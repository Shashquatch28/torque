/* Torque UI. Vanilla JS, no build. Renders backend data only:
   it never computes a metric, a score, or a ranking — those come from the API. */
"use strict";

const API = ""; // same origin
const $ = (s, r = document) => r.querySelector(s);
const view = $("#view");
const merchantInput = $("#merchant");

let MERCHANT = localStorage.getItem("torque.merchant") || "";
let pollTimer = null;

// --- helpers ---------------------------------------------------------
async function api(path, opts) {
  const r = await fetch(API + path, opts);
  if (!r.ok) {
    let detail = r.statusText;
    try { detail = (await r.json()).detail || detail; } catch (e) {}
    const err = new Error(detail); err.status = r.status; throw err;
  }
  return r.status === 204 ? null : r.json();
}
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function rupees(v) {
  const n = Number(v || 0);
  if (n >= 1e7) return "₹" + (n / 1e7).toFixed(2) + " Cr";
  if (n >= 1e5) return "₹" + (n / 1e5).toFixed(2) + " L";
  return "₹" + n.toLocaleString("en-IN", { maximumFractionDigits: 0 });
}
const rupeesExact = (v) => "₹" + Number(v || 0).toLocaleString("en-IN",
  { maximumFractionDigits: 2 });
const pct = (v) => (Number(v || 0) * 100).toFixed(1) + "%";
// null-safe percent, and a signed percent for a lift that can be < 0.
const pctN = (v) => v == null ? "—" : (Number(v) * 100).toFixed(1) + "%";
const pctSigned = (v) => v == null ? "—"
  : (Number(v) >= 0 ? "+" : "") + (Number(v) * 100).toFixed(1) + "%";
const prob = (v) => v == null ? "—" : Math.round(Number(v) * 100) + "%";
const num = (v) => Number(v || 0).toLocaleString("en-IN");
const titleize = (s) => String(s || "").replace(/_/g, " ").toLowerCase()
  .replace(/\b\w/g, (c) => c.toUpperCase());
const when = (s) => s ? new Date(s).toLocaleString("en-IN",
  { hour12: false, dateStyle: "medium", timeStyle: "short" }) : "—";

// Human-readable errors everywhere — never a raw Error.message/stack. Kept
// close to the mapping explainCase already used for the AI route.
function friendlyError(e) {
  if (e && e.status === 404) return "This could not be found.";
  if (e && e.status === 503) return "This feature is not enabled for this deployment.";
  if (e && e.status >= 500) return "Something went wrong loading this. Please try again.";
  if (e && e.status === 409) return "That action is no longer available for this case.";
  if (e && e.status === 422) return "That request could not be understood.";
  return "Something went wrong loading this. Please try again.";
}

const STATUS_EDGE = { RECOVERED: "green", PARTIALLY_RECOVERED: "green", CANCELLED: "blue",
  ESCALATED_TO_HUMAN: "amber", EXHAUSTED: "red", WRITTEN_OFF: "red", PAUSED: "amber" };
function statusPill(s) {
  const cls = STATUS_EDGE[s] || "";
  return `<span class="pill ${cls}">${titleize(s)}</span>`;
}
function toast(msg, isErr) {
  const t = document.createElement("div");
  t.className = "toast" + (isErr ? " err" : "");
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 3200);
}
function setActiveNav(name) {
  document.querySelectorAll(".nav a").forEach((a) => {
    const isActive = a.dataset.nav === name;
    a.classList.toggle("active", isActive);
    if (isActive) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  });
}

// A frontend-only, no-new-field convention: cases this browser has already
// generated an AI explanation for in this session are remembered so the
// dashboard's "AI available, not yet reviewed" dot only lights up for cases
// that genuinely have not been looked at yet in this session.
const explainedCases = new Set(
  JSON.parse(sessionStorage.getItem("torque.explained") || "[]")
);
function markExplained(caseId) {
  explainedCases.add(caseId);
  sessionStorage.setItem("torque.explained", JSON.stringify([...explainedCases]));
}

// small skeleton building blocks — layout-matching, not a spinner
const skelLine = (w) => `<div class="skel skel-line ${w || ""}"></div>`;
const skelBlock = () => `<div class="skel skel-block"></div>`;
function skeletonPanel(lines) {
  return `<div class="panel">${(lines || 3).toString().split("").map(() => skelLine("w60")).join("")}</div>`;
}

// --- routing --------------------------------------------------------
async function route() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  const hash = location.hash.replace(/^#\/?/, "") || "dashboard";
  const [name, arg] = hash.split("/");
  setActiveNav(name === "console" ? "console" : name);
  closeMobileNav();
  if (!MERCHANT) { await bootstrapMerchant(); }
  view.classList.remove("fade-in");
  try {
    if (name === "dashboard") { renderDashboardSkeleton(); await renderDashboard(); }
    else if (name === "cases" && arg) { renderCaseViewSkeleton(); await renderCaseView(arg, { viaConsole: false }); }
    else if (name === "cases") { renderCasesSkeleton(); await renderCases(); }
    else if (name === "console" && arg) { renderCaseViewSkeleton(); await renderCaseView(arg, { viaConsole: true }); }
    else if (name === "console") { renderConsoleSkeleton(); await renderConsole(); }
    else if (name === "demo") { renderDemoSkeleton(); await renderDemo(); }
    else { view.innerHTML = '<div class="empty">Not found</div>'; }
    view.classList.add("fade-in");
  } catch (e) {
    view.innerHTML = `<div class="panel"><h2>Could not load this page</h2>
      <p class="muted">${esc(friendlyError(e))}</p>
      <p class="faint">merchant: <code>${esc(MERCHANT)}</code></p></div>`;
  }
}

async function bootstrapMerchant() {
  try {
    const d = await api("/demo/merchant");
    MERCHANT = d.merchant_id;
    if (!d.seeded) toast("Demo not seeded — open Live Demo → Seed", false);
  } catch (e) { MERCHANT = "acc_demo"; }
  localStorage.setItem("torque.merchant", MERCHANT);
  merchantInput.value = MERCHANT;
}

// --- loading skeletons (layout-aware, per screen) -------------------
function renderDashboardSkeleton() {
  view.innerHTML = `
  <div class="panel hero"><div class="skel skel-hero"></div></div>
  <div class="loop mt">${"123".split("").map(() => `<div class="loop-stage">${skelLine("w40")}${skelLine("w60")}</div>`).join("")}</div>
  <div class="grid cols-2 mt">${skeletonPanel(5)}${skeletonPanel(5)}</div>
  ${skeletonPanel(4)}`;
}
function renderCasesSkeleton() {
  view.innerHTML = `<div class="panel">${skelLine("w40")}
    ${"12345".split("").map(() => `<div class="skel skel-row"></div>`).join("")}</div>`;
}
function renderCaseViewSkeleton() {
  view.innerHTML = `
  <div class="skel skel-line w40" style="margin-bottom:12px"></div>
  <div class="panel casehead lg">${skelLine("w60")}${skelLine("w40")}${skelBlock()}</div>
  <div class="grid cols-2 mt">${skeletonPanel(4)}${skeletonPanel(4)}</div>
  ${skeletonPanel(6)}`;
}
function renderConsoleSkeleton() {
  view.innerHTML = `<div class="panel">${skelLine("w40")}
    ${"123".split("").map(() => `<div class="skel skel-row"></div>`).join("")}</div>`;
}
function renderDemoSkeleton() {
  view.innerHTML = `<div class="grid cols-2">${skeletonPanel(4)}${skeletonPanel(6)}</div>`;
}

// =====================================================================
// Component: the recovery loop rendered in money, not stat tiles.
// Each stage is an independent, honestly-labeled figure straight off
// RecoverySummary — never a proportional/stacked chart that would imply
// an exact waterfall between them (the four figures are not disjoint
// partitions of one total; showing them as a proportional Sankey would
// overstate the precision of that relationship).
// =====================================================================
function loopPipeline(rep) {
  const heldBack = Number(rep.blocked_amount || 0) + Number(rep.deferred_amount || 0);
  const stage = (cls, k, v, cap) => `<div class="loop-stage ${cls}">
    <div class="k">${k}</div><div class="v mono">${v}</div><div class="cap">${cap}</div></div>`;
  const arrow = `<div class="loop-arrow" aria-hidden="true">&rarr;</div>`;
  return `
  <div class="loop">
    ${stage("risk", "Revenue at risk", rupees(rep.revenue_at_risk), `${num(rep.case_count)} cases opened`)}
    ${arrow}
    ${stage("hold", "Held back by guardrails", rupees(heldBack), "compliance-by-construction")}
    ${arrow}
    ${stage("active", "Still in motion", rupees(rep.unresolved_amount), `${num(rep.unresolved_case_count)} cases open`)}
    ${arrow}
    ${stage("recovered", "Recovered", rupees(rep.recovered_amount), `${num(rep.recovered_case_count)} cases closed`)}
  </div>
  ${rep.escalated_case_count ? `<div class="loop-note"><span class="pill amber">human</span>
    ${num(rep.escalated_case_count)} case${rep.escalated_case_count === 1 ? "" : "s"} escalated to a human reviewer — restraint, not failure</div>` : ""}`;
}

// =====================================================================
// Component: an interactive area/line chart with a hover tooltip and a
// real bucket toggle (Day/Week/Month — all three already accepted by
// GET /reports/{m}/over-time?bucket=). Pure inline SVG, no library.
// =====================================================================

// `series` is real backend buckets (one entry per day/week/month that has
// ANY recovered amount, ascending) — this function never invents a value.
// With few real buckets a naive render reads as one decorative block
// rather than a trend, so we left-pad with explicit zero-recovery periods
// immediately before the earliest real bucket (a period with no recovery
// genuinely recovered ₹0 — this is not a fabricated number, just the true
// value for periods the backend has no row for) up to a minimum count.
const MIN_BARS = 7;
function padSeries(series, bucket) {
  let padded = series;
  if (padded.length && padded.length < MIN_BARS) {
    const earliest = new Date(padded[0].bucket_start);
    const filler = [];
    for (let i = MIN_BARS - padded.length; i >= 1; i--) {
      const d = new Date(earliest);
      if (bucket === "month") d.setUTCMonth(d.getUTCMonth() - i);
      else if (bucket === "week") d.setUTCDate(d.getUTCDate() - i * 7);
      else d.setUTCDate(d.getUTCDate() - i);
      filler.push({ bucket_start: d.toISOString(), recovered_amount: "0" });
    }
    padded = filler.concat(padded);
  }
  return padded.slice(-24);
}

function areaChartSvg(series) {
  const W = 640, H = 160, PAD = 6;
  const max = Math.max(...series.map((s) => Number(s.recovered_amount)), 1);
  const n = series.length;
  const x = (i) => (n === 1 ? W / 2 : (i / (n - 1)) * W);
  const y = (v) => H - PAD - (Number(v) / max) * (H - PAD * 2);
  const pts = series.map((s, i) => [x(i), y(s.recovered_amount)]);
  const line = pts.map(([px, py], i) => `${i === 0 ? "M" : "L"}${px.toFixed(1)},${py.toFixed(1)}`).join(" ");
  const area = `${line} L${x(n - 1).toFixed(1)},${H} L${x(0).toFixed(1)},${H} Z`;
  return `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="Recovered amount over time">
    <defs><linearGradient id="areafill" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="var(--green)" stop-opacity=".35" />
      <stop offset="100%" stop-color="var(--green)" stop-opacity="0" />
    </linearGradient></defs>
    <path d="${area}" fill="url(#areafill)" stroke="none"></path>
    <path d="${line}" fill="none" stroke="var(--green)" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"></path>
    <line class="chart-guide" id="chartGuide" x1="0" y1="0" x2="0" y2="${H}"></line>
    <circle class="chart-dot" id="chartDot" r="4"></circle>
  </svg>`;
}

function renderChartCard(series, bucket) {
  const padded = padSeries(series, bucket);
  return `
  <div class="rowflex">
    <h2>Recovery over time</h2>
    <div class="chart-tabs" role="tablist" aria-label="Time bucket">
      ${["day", "week", "month"].map((b) => `<button type="button" role="tab" aria-selected="${b === bucket}"
        class="${b === bucket ? "active" : ""}" data-bucket="${b}">${titleize(b)}</button>`).join("")}
    </div>
  </div>
  ${series.length ? `<div class="chart-wrap" id="chartWrap">${areaChartSvg(padded)}<div class="chart-tip" id="chartTip"></div></div>`
    : '<div class="hatch">No recoveries in range yet</div>'}
  <div class="faint" style="margin-top:8px">Torque-credited recoveries, by ${bucket} (UTC). Hover to inspect a point.</div>`;
}

function wireChartInteraction(container, padded) {
  const wrap = container.querySelector("#chartWrap");
  if (!wrap) return;
  const svg = wrap.querySelector("svg");
  const guide = wrap.querySelector("#chartGuide");
  const dot = wrap.querySelector("#chartDot");
  const tip = wrap.querySelector("#chartTip");
  const W = 640, H = 160;
  const n = padded.length;
  const move = (clientX) => {
    const rect = svg.getBoundingClientRect();
    const frac = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
    const i = Math.round(frac * (n - 1));
    const s = padded[i];
    if (!s) return;
    const px = n === 1 ? W / 2 : (i / (n - 1)) * W;
    const max = Math.max(...padded.map((p) => Number(p.recovered_amount)), 1);
    const py = H - 6 - (Number(s.recovered_amount) / max) * (H - 12);
    guide.setAttribute("x1", px); guide.setAttribute("x2", px); guide.style.opacity = "1";
    dot.setAttribute("cx", px); dot.setAttribute("cy", py); dot.style.opacity = "1";
    const tipLeftPct = (px / W) * 100;
    tip.style.left = tipLeftPct + "%";
    tip.style.top = (py / H) * 100 + "%";
    const d = new Date(s.bucket_start);
    tip.innerHTML = `<span class="date">${d.toDateString()}</span><br><span class="amt">${rupeesExact(s.recovered_amount)}</span>`;
    tip.classList.add("show");
  };
  const leave = () => {
    guide.style.opacity = "0"; dot.style.opacity = "0"; tip.classList.remove("show");
  };
  svg.addEventListener("pointermove", (e) => move(e.clientX));
  svg.addEventListener("pointerdown", (e) => move(e.clientX));
  svg.addEventListener("pointerleave", leave);
}

// =====================================================================
// Component: proportional leg bars — replaces a plain leg table with a
// scannable at-risk-vs-recovered comparison across the four legs.
// =====================================================================
function legBars(legs) {
  const max = Math.max(...legs.map((l) => Number(l.revenue_at_risk)), 1);
  return `<div class="legbars">${legs.map((l) => {
    const fillPct = Math.min(100, (Number(l.recovered_amount) / max) * 100);
    const trackPct = Math.min(100, (Number(l.revenue_at_risk) / max) * 100);
    return `<div class="legbar-row">
      <div class="hd"><span class="name">${titleize(l.leg_type)}</span>
        <span class="rate">${pct(l.amount_recovery_rate)} recovered</span></div>
      <div class="legbar-track" style="width:${trackPct}%">
        <div class="legbar-fill" style="width:${(fillPct / Math.max(trackPct, 0.01) * 100).toFixed(1)}%"></div>
      </div>
      <div class="meta"><span>${num(l.cases_recovered)}/${num(l.cases_attempted)} cases recovered</span>
        <span>${rupees(l.recovered_amount)} of ${rupees(l.revenue_at_risk)}</span></div>
    </div>`;
  }).join("")}</div>`;
}

// =====================================================================
// Component: a priority feed row — used for both the dashboard's
// top-at-risk list and the Agent Console's human queue. A triage feed,
// not a spreadsheet: one glance gives identity, why it matters
// economically, and where it stands.
// =====================================================================
function feedRow({ caseId, href, edge, title, badges, sub, amountLabel, amount, metaLines }) {
  const hrefAttr = href ? ` data-href="${esc(href)}"` : "";
  return `<div class="feed-row ${edge}" data-case="${caseId}"${hrefAttr} tabindex="0" role="button">
    <div class="identity">
      <div class="name">${title}${badges || ""}</div>
      <div class="sub">${sub}</div>
    </div>
    <div class="amt"><div class="v mono">${amount}</div><div class="k">${amountLabel}</div></div>
    <div class="meta">${metaLines}</div>
  </div>`;
}

function priorityFeed(rows) {
  return `<div class="feedlist">${rows.join("") || '<div class="empty">Nothing here right now</div>'}</div>`;
}

function wireFeedRows(container) {
  container.querySelectorAll("[data-case]").forEach((row) => {
    const go = () => { location.hash = row.dataset.href || ("#/cases/" + row.dataset.case); };
    row.addEventListener("click", go);
    row.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } });
  });
}

// --- dashboard --------------------------------------------------------
let dashboardState = { bucket: "day" };
async function renderDashboard() {
  const m = encodeURIComponent(MERCHANT);
  const [rep, legs, series, top, exc, inc] = await Promise.all([
    api(`/reports/${m}/summary`),
    api(`/reports/${m}/by-intervention?by=leg`),
    api(`/reports/${m}/over-time?bucket=${dashboardState.bucket}`),
    api(`/reports/${m}/top-at-risk?limit=8`),
    api(`/reports/${m}/exceptions`),
    api(`/reports/${m}/incrementality`),
  ]);

  view.innerHTML = `
  <div class="panel hero">
    <div class="label">Revenue recovered by Torque</div>
    <div class="big mono">${rupees(rep.recovered_amount)}</div>
    <div class="sub">${num(rep.recovered_case_count)} recovered cases &middot;
      ${pct(rep.amount_recovery_rate)} of at-risk revenue &middot;
      self-recovered (not counted): ${rupees(rep.self_recovered_amount)}</div>
  </div>

  <div class="mt">${loopPipeline(rep)}</div>

  <div class="grid cols-2 mt">
    <div class="panel">
      <h2>Recovery by leg</h2>
      ${legBars(legs)}
    </div>
    <div class="panel" id="chartCard">
      ${renderChartCard(series, dashboardState.bucket)}
    </div>
  </div>

  ${incrementalityCard(inc)}

  <div class="panel mt">
    <div class="rowflex"><h2>Top at-risk cases</h2>
      <span class="faint">ranked by recovery score (backend order)</span></div>
    ${priorityFeed(top.items.map((c) => {
      const notReviewed = c.escalated && !explainedCases.has(c.case_id);
      return feedRow({
        caseId: c.case_id,
        edge: STATUS_EDGE[c.status] || "",
        title: `${notReviewed ? '<span class="aidot" title="AI assessment available, not yet reviewed"></span>' : ""}${esc(c.counterparty_label)}`,
        badges: c.escalated ? ' <span class="pill amber">human</span>' : "",
        sub: `${titleize(c.leg_type)} &middot; ${statusPill(c.status)}`,
        amountLabel: "At risk",
        amount: rupees(c.amount_at_risk),
        metaLines: `<div class="score">${prob(c.recovery_probability)} probability</div>
          <div>${c.next_intervention ? "Next: " + titleize(c.next_intervention) : "Score " + (c.recovery_score == null ? "—" : num(Math.round(c.recovery_score)))}</div>`,
      });
    }))}
  </div>

  <div class="panel mt">
    <div class="rowflex"><h2>Where Torque deliberately held back</h2>
      <span class="faint">compliance-by-construction &mdash; not failures</span></div>
    <div class="table-wrap"><table class="stackable"><thead><tr><th>Guardrail block reason</th><th class="num">Actions</th>
      <th class="num">Cases</th><th class="num">Revenue held</th></tr></thead><tbody>
      ${exc.blocked_by_reason.map((b) => `<tr>
        <td data-label="Reason"><span class="pill amber">${titleize(b.block_reason)}</span></td>
        <td class="num" data-label="Actions">${num(b.action_count)}</td>
        <td class="num" data-label="Cases">${num(b.case_count)}</td>
        <td class="num" data-label="Revenue held">${rupees(b.revenue_at_risk)}</td></tr>`).join("")
        || '<tr><td colspan="4" class="empty">No blocked actions</td></tr>'}
      ${exc.deferred_action_count ? `<tr><td data-label="Reason"><span class="pill amber">Outreach Coordinator Deferred</span></td>
        <td class="num" data-label="Actions">${num(exc.deferred_action_count)}</td>
        <td class="num" data-label="Cases">${num(exc.deferred_case_count)}</td><td class="num faint" data-label="Revenue held">rescheduled</td></tr>` : ""}
    </tbody></table></div>
  </div>`;

  wireFeedRows(view);
  wireChartInteraction(view, padSeries(series, dashboardState.bucket));
  view.querySelectorAll("[data-bucket]").forEach((btn) => btn.onclick = async () => {
    dashboardState.bucket = btn.dataset.bucket;
    try {
      const s2 = await api(`/reports/${m}/over-time?bucket=${dashboardState.bucket}`);
      const card = $("#chartCard");
      card.innerHTML = renderChartCard(s2, dashboardState.bucket);
      wireChartInteraction(view, padSeries(s2, dashboardState.bucket));
      card.querySelectorAll("[data-bucket]").forEach((b2) => b2.onclick = btn.onclick);
    } catch (e) { toast(friendlyError(e), true); }
  });
}

// The causal layer. Renders ONLY numbers from the /incrementality response;
// it computes no rate, lift, or interval itself. Statistical, not
// AI-generated — blue is the correct, honest color here, never gold.
function incrementalityCard(inc) {
  const ci = (o) => (o.ci_low == null ? "" :
    `<span class="ci">95% CI ${pctSigned(o.ci_low)} … ${pctSigned(o.ci_high)}</span>`);
  const ciRate = (o) => (o.ci_low == null ? "" :
    `<span class="ci">95% CI ${pctN(o.ci_low)} … ${pctN(o.ci_high)}</span>`);
  const enough = inc.lift.point != null;
  const s = inc.sutva;
  return `
  <div class="panel mt causal">
    <div class="rowflex">
      <h2>Incrementality &mdash; estimated causal effect</h2>
      <span class="pill blue">causal estimate</span>
    </div>
    <p class="faint" style="margin:2px 0 12px">
      The metrics above are <b>descriptive</b> &mdash; what happened. This is
      <b>causal</b> &mdash; treatment vs. a held-out control, a point estimate with an
      honest interval. Not proof of causation.</p>
    ${enough ? `
    <div class="causal-grid">
      <div class="metric"><div class="k">Treatment recovery rate</div>
        <div class="v">${pctN(inc.treatment.rate)}</div>
        <div class="faint">${num(inc.treatment.successes)}/${num(inc.treatment.total)} cases ${ciRate(inc.treatment)}</div></div>
      <div class="metric"><div class="k">Control recovery rate</div>
        <div class="v">${pctN(inc.control.rate)}</div>
        <div class="faint">${num(inc.control.successes)}/${num(inc.control.total)} held out ${ciRate(inc.control)}</div></div>
      <div class="metric hl"><div class="k">Incremental lift</div>
        <div class="v">${pctSigned(inc.lift.point)}</div>
        <div class="faint">${ci(inc.lift)}</div></div>
      <div class="metric"><div class="k">SUTVA-adjusted lift</div>
        <div class="v">${pctSigned(s.lift.point)}</div>
        <div class="faint">${num(s.contaminated_control_counterparties)} contaminated control
          counterpart${s.contaminated_control_counterparties === 1 ? "y" : "ies"} removed ${ci(s.lift)}</div></div>
    </div>
    <p class="faint mt">${esc(s.note)}</p>
    <p class="faint">${esc(inc.recovery_definition)}</p>
    ` : `<div class="hatch">Not enough cohort data yet &mdash; assign a control holdout
      (${num(inc.treatment.total)} treatment, ${num(inc.control.total)} control cases in range).</div>`}
  </div>`;
}

// --- cases list -------------------------------------------------------
let casesFilter = { leg: "", status: "", offset: 0 };
async function renderCases() {
  const m = encodeURIComponent(MERCHANT);
  const q = new URLSearchParams({ limit: "25", offset: String(casesFilter.offset) });
  if (casesFilter.leg) q.set("leg", casesFilter.leg);
  if (casesFilter.status) q.set("status", casesFilter.status);
  const data = await api(`/reports/${m}/cases?` + q.toString());
  const legs = ["PAYMENT_DEGRADATION", "CHECKOUT_ABANDONMENT", "SUBSCRIPTION_FAILURE", "B2B_RECEIVABLE"];
  const statuses = ["DETECTED", "DIAGNOSING", "PLAYBOOK_ACTIVE", "ESCALATED_TO_HUMAN",
    "PAUSED", "RECOVERED", "PARTIALLY_RECOVERED", "EXHAUSTED", "CANCELLED", "WRITTEN_OFF"];
  view.innerHTML = `
  <div class="panel">
    <div class="rowflex">
      <h2>Cases &mdash; ${num(data.total)}</h2>
      <div class="btnrow">
        <select id="fleg" aria-label="Filter by leg"><option value="">All legs</option>
          ${legs.map((l) => `<option value="${l}" ${casesFilter.leg === l ? "selected" : ""}>${titleize(l)}</option>`).join("")}</select>
        <select id="fstatus" aria-label="Filter by status"><option value="">All statuses</option>
          ${statuses.map((s) => `<option value="${s}" ${casesFilter.status === s ? "selected" : ""}>${titleize(s)}</option>`).join("")}</select>
      </div>
    </div>
    <div class="table-wrap"><table class="stackable"><thead><tr><th>Case</th><th>Leg</th><th>Status</th>
      <th class="num">Revenue at risk</th><th>Attribution</th>
      <th class="num">Recovered</th><th>Opened</th></tr></thead><tbody>
      ${data.items.map((c) => `<tr class="clickable edge-row" tabindex="0" role="button" data-case="${c.case_id}">
        <td class="edge ${STATUS_EDGE[c.status] || ""}" data-label="Case"><span class="faint mono">${c.case_id.slice(0, 8)}</span></td>
        <td data-label="Leg">${titleize(c.leg_type)}</td><td data-label="Status">${statusPill(c.status)}</td>
        <td class="num" data-label="Revenue at risk">${rupees(c.revenue_at_risk)}</td>
        <td data-label="Attribution">${c.recovery_type ? `<span class="pill ${c.recovery_type === "SELF_RECOVERED" ? "blue" : "green"}">${titleize(c.recovery_type)}</span>` : '<span class="faint">—</span>'}</td>
        <td class="num" data-label="Recovered">${c.recovered_amount ? rupees(c.recovered_amount) : "—"}</td>
        <td class="faint" data-label="Opened">${when(c.opened_at)}</td></tr>`).join("")
        || '<tr><td colspan="7" class="empty">No cases match</td></tr>'}
    </tbody></table></div>
    <div class="btnrow mt">
      <button ${casesFilter.offset === 0 ? "disabled" : ""} id="prev">&larr; Prev</button>
      <button ${casesFilter.offset + 25 >= data.total ? "disabled" : ""} id="next">Next &rarr;</button>
      <span class="faint" style="align-self:center">showing ${data.items.length ? casesFilter.offset + 1 : 0}–${casesFilter.offset + data.items.length}</span>
    </div>
  </div>`;
  $("#fleg").onchange = (e) => { casesFilter.leg = e.target.value; casesFilter.offset = 0; renderCases(); };
  $("#fstatus").onchange = (e) => { casesFilter.status = e.target.value; casesFilter.offset = 0; renderCases(); };
  $("#prev").onclick = () => { casesFilter.offset = Math.max(0, casesFilter.offset - 25); renderCases(); };
  $("#next").onclick = () => { casesFilter.offset += 25; renderCases(); };
  wireClickableRows();
}
function wireClickableRows() {
  view.querySelectorAll("tr[data-case]").forEach((tr) => {
    const go = () => { location.hash = "#/cases/" + tr.dataset.case; };
    tr.addEventListener("click", go);
    tr.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); }
    });
  });
}

// --- canonical Case View (#/cases/:id and #/console/:id alias) --------
// One component replaces the former split of a read-only case detail and a
// separate, action-bearing console pane. Everything above the action rail
// is always visible regardless of entry point; the action rail itself is
// state-gated exactly as it always has been (canResolve/canPause/canUnpause).
//
// Composition mirrors the decision workspace this case represents: what
// happened -> how much is at risk -> why Torque believes recovery is
// possible -> what the AI adds -> what will happen next -> what a human
// can do -> the full trace -> the evidence -> comparable precedent.
async function renderCaseView(caseId, opts) {
  const viaConsole = !!(opts && opts.viaConsole);
  const m = encodeURIComponent(MERCHANT);
  const [c, events] = await Promise.all([
    api(`/reports/${m}/cases/${caseId}`),
    api(`/reports/${m}/cases/${caseId}/events`),
  ]);
  const b = c.recovery_score_breakdown;
  const ex = b && b.explain;
  const canResolve = c.status === "ESCALATED_TO_HUMAN";
  const canPause = c.status === "PLAYBOOK_ACTIVE";
  const canUnpause = c.status === "PAUSED";
  const showActionRail = canResolve || canPause || canUnpause;
  const showNextStep = !c.is_terminal && b && b.next_step_action_type;

  view.innerHTML = `
  <a class="back" href="${viaConsole ? "#/console" : "#/cases"}">&larr; ${viaConsole ? "Queue" : "All cases"}</a>

  <div class="panel casehead lg mt" id="case-snapshot">
    <div class="idrow">
      <div>
        <div class="who">${esc(c.counterparty_label)}</div>
        <div class="cid mono">${c.case_id}</div>
      </div>
      <div style="display:flex;align-items:center;gap:16px">
        ${statusPill(c.status)}
        ${c.recovery_score != null ? `<div class="gauge-card">
          ${confidenceRing(c.recovery_probability, 88, 50)}
          <div class="v mono">${prob(c.recovery_probability)}</div>
          <div class="k">Recovery probability</div>
        </div>` : ""}
      </div>
    </div>
    <div class="casefacts">
      ${fact("Leg", titleize(c.leg_type))}
      ${fact("Revenue at risk", rupeesExact(c.revenue_at_risk))}
      ${fact("Amount at risk now", rupeesExact(c.amount_at_risk))}
      ${fact("Root cause", c.root_cause_code ? titleize(c.root_cause_code) : "—")}
      ${fact("Opened", when(c.opened_at))}
      ${fact("Attribution", c.recovery_type ? titleize(c.recovery_type) : "—")}
      ${fact("Recovered", c.recovered_amount ? rupeesExact(c.recovered_amount) : "—")}
      ${c.escalation_resolution ? fact("Human resolution", `${titleize(c.escalation_resolution)} (${esc(c.escalation_resolved_by || "agent")})`) : c.in_human_queue ? fact("Human queue", titleize(c.human_queue_reason)) : fact("Diagnosis confidence", c.diagnosis_confidence == null ? "—" : c.diagnosis_confidence.toFixed(2))}
    </div>
  </div>

  ${showNextStep ? `<div class="next-step mt">
    <span class="tag">Next</span>
    <span>Torque plans to attempt <b>${titleize(b.next_step_action_type)}</b>${b.cost_channels && b.cost_channels.length ? " via " + esc(b.cost_channels[0]) : ""} for this case.</span>
  </div>` : ""}

  <div class="grid cols-2 mt">
    <div class="panel">
      <h2>Why Torque prioritized this case</h2>
      ${ex ? `
      <ul class="signals">
        ${(ex.why || []).map((w) => `<li>${esc(w)}</li>`).join("")}
        ${b && b.promise_keeping_rate != null ? `<li>Customer has kept ${prob(b.promise_keeping_rate)} of past payment promises</li>` : ""}
      </ul>
      <div class="faint mt" style="margin-top:10px">Amount at risk ${rupeesExact(ex.amount_at_risk)} &middot;
        expected intervention cost ${rupeesExact(ex.expected_cost)} &middot; priority score ${num(Math.round(Number(ex.priority_score)))}.
        probability &times; amount &divide; expected cost &mdash; computed server-side, rendered verbatim.</div>`
      : '<div class="empty">Not scored yet (terminal or pre-diagnosis case).</div>'}
    </div>

    <div class="panel ai-card" id="aiCard">
      <div class="rowflex"><h2><span class="aihdr">AI Assessment</span></h2></div>
      <p class="ai-intro">Torque's AI reads this case's evidence and explains it. It never changes anything.</p>
      <button type="button" class="ai" id="doExplain">Explain this case</button>
      <div id="aiPanel"></div>
    </div>
  </div>

  ${showActionRail ? `
  <div class="panel mt action-rail" id="actionRail">
    <h2>Actions</h2>
    <div class="btnrow">
      <select id="res" aria-label="Resolution">
        <option value="RECOVERED_BY_HUMAN">Resolve — recovered</option>
        <option value="PARTIALLY_RECOVERED_BY_HUMAN">Resolve — partial</option>
        <option value="WRITTEN_OFF">Write off</option>
      </select>
      <input id="amt" type="number" placeholder="recovered ₹ (optional)" style="width:170px" aria-label="Recovered amount" />
      <button class="primary" id="doResolve" ${canResolve ? "" : "disabled"}>Resolve</button>
      <button id="doPause" ${canPause ? "" : "disabled"}>Pause</button>
      <button id="doUnpause" ${canUnpause ? "" : "disabled"}>Un-pause</button>
    </div>
    <div class="faint" style="margin-top:6px">Resolve is available only for an escalated case; pause only for one still in a playbook.</div>
  </div>` : ""}

  <div class="panel mt">
    <h2>Timeline</h2>
    <ul class="timeline">
      ${events.map(renderEvent).join("") || '<li class="empty">No events</li>'}
    </ul>
  </div>

  ${evidencePanel(c)}

  <div class="panel mt" id="precedentCard">
    <h2>Similar cases</h2>
    <div class="faint" style="margin-bottom:8px">Generate an AI assessment to surface comparable resolved cases.</div>
  </div>`;

  const pane = view;
  $("#doExplain").onclick = () => explainCase(m, caseId, pane);
  $("#aiPanel").addEventListener("click", (e) => {
    const chip = e.target.closest("[data-cite]");
    if (chip) focusCitation(chip.dataset.cite);
  });

  if (showActionRail) {
    const act = async (path, body) => {
      try {
        const out = await api(`/agent-console/${m}/cases/${caseId}/${path}`, {
          method: "POST", headers: { "content-type": "application/json" },
          body: JSON.stringify(body),
        });
        toast(`${titleize(out.from_status)} → ${titleize(out.to_status)}`);
        await renderCaseView(caseId, opts);
      } catch (e) { toast(friendlyError(e), true); }
    };
    $("#doResolve").onclick = () => act("resolve", {
      resolution: $("#res").value, agent_id: "demo-agent",
      recovered_amount: $("#amt").value || null,
    });
    $("#doPause").onclick = () => act("pause", { agent_id: "demo-agent" });
    $("#doUnpause").onclick = () => act("unpause", { agent_id: "demo-agent" });
    if (viaConsole) $("#actionRail").scrollIntoView({ block: "nearest" });
  }
}
const fact = (k, v) => `<div class="fact"><div class="k">${k}</div><div class="v">${v}</div></div>`;

// A single semi-circular gauge — used sparingly (the case header's recovery
// probability), never as a dashboard-wide pattern. Pure inline SVG, no
// charting library. `size`/`h` let it size up for the header gauge-card.
function confidenceRing(p, size, h) {
  if (p == null) return "";
  const frac = Math.max(0, Math.min(1, Number(p)));
  const W = size || 64, H = h || 36;
  const r = 26, c = Math.PI * r; // half-circumference (semicircle)
  const dash = c * frac;
  return `<svg class="ring" width="${W}" height="${H}" viewBox="0 0 64 36" aria-hidden="true">
    <path d="M 4 34 A 28 28 0 0 1 60 34" fill="none" stroke="var(--line)" stroke-width="6" stroke-linecap="round" />
    <path d="M 4 34 A 28 28 0 0 1 60 34" fill="none" stroke="var(--blue)" stroke-width="6" stroke-linecap="round"
      stroke-dasharray="${dash.toFixed(1)} ${c.toFixed(1)}" />
  </svg>`;
}

// Evidence — Actions taken rendered as a dedicated, scannable list (first-
// class evidence, not folded only into the timeline), grouped so a
// guardrail block reads as its own category rather than one row among
// many. Promises are not shown here: CaseDetail exposes no promise list
// today — the honest choice is to omit the section rather than fabricate
// one from data the API does not return.
function evidenceRow(a) {
  return `<li>
    <div>
      <div class="et">${titleize(a.action_type)}${a.channel ? " · " + titleize(a.channel) : ""}</div>
      <div class="em">${a.executed_at ? when(a.executed_at) : "not executed"}${a.block_reason ? " · " + titleize(a.block_reason) : ""}</div>
    </div>
    <span class="pill ${a.outcome === "BLOCKED_BY_GUARDRAIL" ? "amber" : a.outcome === "FAILED" || a.outcome === "NO_RESPONSE" ? "red" : "green"}">${titleize(a.outcome)}</span>
  </li>`;
}
function evidencePanel(c) {
  const actions = c.actions || [];
  if (!actions.length) {
    return `<div class="panel mt"><h2>Evidence</h2><div class="empty">No actions recorded yet.</div></div>`;
  }
  const blocked = actions.filter((a) => a.outcome === "BLOCKED_BY_GUARDRAIL");
  const executed = actions.filter((a) => a.outcome !== "BLOCKED_BY_GUARDRAIL");
  return `<div class="panel mt">
    <h2>Evidence</h2>
    ${blocked.length ? `<div class="evidence-group blocked">
      <div class="gk">Blocked by guardrail</div>
      <ul class="evidence-list">${blocked.map(evidenceRow).join("")}</ul>
    </div>` : ""}
    ${executed.length ? `<div class="evidence-group executed">
      <div class="gk">Executed</div>
      <ul class="evidence-list">${executed.map(evidenceRow).join("")}</ul>
    </div>` : ""}
  </div>`;
}

function renderEvent(e) {
  const cls = e.event_type === "PAYMENT_RECONCILED" ? "ok"
    : e.event_type === "ACTION_BLOCKED" ? "block"
    : e.event_type === "HUMAN_RESOLVED" ? "ok" : "";
  const p = e.payload || {};
  let extra = "";
  if (e.event_type === "DIAGNOSIS_COMPLETED")
    extra = `<span class="why">${titleize(p.root_cause_code)} &middot; confidence ${Number(p.diagnosis_confidence).toFixed(2)}</span>`;
  else if (e.event_type === "ACTION_EXECUTED")
    extra = `<span class="why">${titleize(p.action_type)} → ${titleize(p.outcome)}${p.channel ? " via " + p.channel : ""}</span>`;
  else if (e.event_type === "ACTION_BLOCKED")
    extra = `<span class="why">${titleize(p.action_type)} blocked — ${titleize(p.block_reason)}</span>`;
  else if (e.event_type === "PAYMENT_RECONCILED")
    extra = `<span class="pay">${rupeesExact(p.recovered_amount)} recovered (${titleize(p.recovery_type)})</span>`;
  else if (e.event_type === "STATUS_CHANGED")
    extra = `<span class="why">${titleize(p.from_status)} → ${titleize(p.to_status)}</span>`;
  else if (e.event_type === "HUMAN_RESOLVED")
    extra = `<span class="why">${titleize(p.resolution)} by ${esc(p.agent_id)}</span>`;
  const actionAttr = p.action_id ? ` data-action-id="${esc(p.action_id)}"` : "";
  const promiseAttr = p.promise_id ? ` data-promise-id="${esc(p.promise_id)}"` : "";
  return `<li class="${cls}" data-event-seq="${e.event_seq_id}"${actionAttr}${promiseAttr}>
    <div class="ts">${when(e.timestamp)} &middot; #${e.event_seq_id} &middot; ${e.actor}</div>
    <div class="ev">${titleize(e.event_type)}</div>
    ${e.reasoning ? `<div class="why">${esc(e.reasoning)}</div>` : extra}
  </li>`;
}

// --- AI case explanation --------------------------------------------
// Read-only decision support: a citation-grounded narrative fetched only on
// request (never on page load), rendered from the CaseNarrative schema
// as-is — no parallel frontend representation, no chat UI. Every citation
// resolves back to a row already shown in the case view above it.

function citationLabel(id) {
  const [type, ref] = String(id).split(":");
  const names = {
    case: "Case snapshot",
    case_event: `Event ${ref}`,
    action: `Action ${String(ref || "").slice(0, 8)}`,
    promise: `Promise ${String(ref || "").slice(0, 8)}`,
    counterparty_relationship: "Customer relationship",
  };
  return names[type] || String(id);
}

function citeGroup(ids) {
  if (!ids || !ids.length) return '<span class="faint">(no citation)</span>';
  return ids.map((id) =>
    `<button type="button" class="cite" data-cite="${esc(id)}">${esc(citationLabel(id))}</button>`
  ).join(" ");
}

function claimLine(nc) {
  return `<p class="claim">${esc(nc.claim)} ${citeGroup(nc.citation_ids)}</p>`;
}
function claimList(arr) {
  if (!arr.length) return '<div class="faint">None recorded.</div>';
  return `<ul class="claims">${arr.map((nc) =>
    `<li>${esc(nc.claim)} ${citeGroup(nc.citation_ids)}</li>`).join("")}</ul>`;
}

function renderPrecedent(p) {
  if (!p.found || !p.cases.length) {
    return `<div class="hatch">${esc(p.note)}</div>`;
  }
  return `<div class="table-wrap"><table class="stackable"><thead><tr><th>Case</th><th>Root cause</th><th>Outcome</th>
    <th>Evidence</th></tr></thead><tbody>
    ${p.cases.map((pc) => `<tr>
      <td class="faint mono" data-label="Case">${esc(pc.case_id).slice(0, 8)}</td>
      <td data-label="Root cause">${esc(titleize(pc.root_cause_code))}</td>
      <td data-label="Outcome">${pc.recovered ? '<span class="pill green">Recovered</span>' : '<span class="pill">Not recovered</span>'}
        <span class="faint">${esc(pc.outcome_summary)}</span></td>
      <td data-label="Evidence">${citeGroup([pc.evidence_id])}</td>
    </tr>`).join("")}
  </tbody></table></div>`;
}

function renderNarrative(n) {
  return `
  <div class="ai-narrative">
    <p class="ai-summary">${esc(n.summary)}</p>
    <div class="ai-block"><div class="ai-k">Current state</div>${claimLine(n.current_state)}</div>
    <div class="ai-block"><div class="ai-k">Root cause</div>${claimLine(n.root_cause_explanation)}</div>
    <div class="ai-block"><div class="ai-k">Timeline</div>${claimList(n.timeline)}</div>
    <div class="ai-block"><div class="ai-k">Actions taken</div>${claimList(n.actions_taken)}</div>
    ${n.guardrail_explanation.length ? `<div class="ai-block"><div class="ai-k">Guardrails</div>${claimList(n.guardrail_explanation)}</div>` : ""}
    ${n.recommended_human_attention ? `<div class="ai-block"><div class="ai-k">Worth a second look</div><div class="ai-callout">${esc(n.recommended_human_attention)}</div></div>` : ""}
    <div class="ai-block"><div class="ai-k">Uncertainty</div><p class="faint">${esc(n.uncertainty)}</p></div>
    ${n.evidence_gaps.length ? `<div class="ai-block"><div class="ai-k">What Torque doesn't know yet</div><ul class="why-lines">${n.evidence_gaps.map((g) => `<li>${esc(g)}</li>`).join("")}</ul></div>` : ""}
    <div class="faint ai-meta">Generated ${when(n.generated_at)} &middot; ${esc(n.provider_id)} &middot; ${esc(n.prompt_version)}</div>
  </div>`;
}

async function explainCase(m, caseId, pane) {
  const btn = pane.querySelector("#doExplain");
  const out = pane.querySelector("#aiPanel");
  btn.disabled = true;
  out.innerHTML = `<div class="ai-loading">${skelLine("w80")}${skelLine("w60")}${skelLine("w40")}</div>`;
  try {
    const n = await api(`/ai/${m}/cases/${caseId}/explain`);
    out.innerHTML = renderNarrative(n);
    markExplained(caseId);
    const pc = pane.querySelector("#precedentCard");
    if (pc) pc.outerHTML = `<div class="panel mt ai-card" id="precedentCard">
      <h2><span class="aihdr">Similar cases</span></h2>${renderPrecedent(n.precedent)}</div>`;
  } catch (e) {
    let msg = "Could not generate an explanation right now.";
    if (e.status === 503) msg = "AI explanations are not enabled for this deployment.";
    else if (e.status === 404) msg = "This case could not be found.";
    else if (e.status >= 500) msg = "The AI explanation could not be generated for this case.";
    out.innerHTML = `<div class="ai-error">${esc(msg)}</div>`;
  }
  btn.disabled = false;
}

// A citation id is only ever `source_type:source_id` from the AI schema's
// own scheme (torque.ai.schemas.EvidenceReference.reference_id) — validated
// with a strict pattern before it ever becomes part of a CSS selector, so a
// citation string can never be used to inject an arbitrary selector.
function focusCitation(id) {
  const s = String(id);
  let m = /^case_event:(\d+)$/.exec(s);
  if (m) {
    const li = view.querySelector(`li[data-event-seq="${m[1]}"]`);
    if (!li) { toast(`Event #${m[1]} is not shown in this view`); return; }
    return flashElement(li);
  }
  m = /^action:([0-9a-fA-F-]+)$/.exec(s);
  if (m) {
    const li = view.querySelector(`li[data-action-id="${cssEscape(m[1])}"]`);
    if (!li) { toast("Referenced: " + citationLabel(id)); return; }
    return flashElement(li);
  }
  m = /^promise:([0-9a-fA-F-]+)$/.exec(s);
  if (m) {
    const li = view.querySelector(`li[data-promise-id="${cssEscape(m[1])}"]`);
    if (!li) { toast("Referenced: " + citationLabel(id)); return; }
    return flashElement(li);
  }
  if (/^case:/.test(s)) {
    const el = view.querySelector("#case-snapshot");
    if (!el) { toast("Referenced: " + citationLabel(id)); return; }
    el.classList.add("case-anchor");
    return flashElement(el);
  }
  if (/^counterparty_relationship:/.test(s)) {
    toast("Customer relationship — not shown in this view");
    return;
  }
  toast("Referenced: " + citationLabel(id));
}
// Defensive escaping for a value used inside an attribute-selector string —
// CSS.escape when available, a conservative manual fallback otherwise.
function cssEscape(s) {
  if (window.CSS && CSS.escape) return CSS.escape(s);
  return String(s).replace(/[^a-zA-Z0-9_-]/g, "\\$&");
}
function flashElement(el) {
  el.scrollIntoView({ behavior: "smooth", block: "center" });
  el.classList.add("cite-hit");
  setTimeout(() => el.classList.remove("cite-hit"), 1600);
}

// --- Agent Console ----------------------------------------------------
async function renderConsole() {
  const m = encodeURIComponent(MERCHANT);
  const queue = await api(`/reports/${m}/human-queue`);
  view.innerHTML = `
  <div class="panel">
    <div class="rowflex"><h2>Human queue &mdash; ${queue.items.length}</h2>
      <span class="faint">ordered by economic priority</span></div>
    ${priorityFeed(queue.items.map((q) => feedRow({
      caseId: q.case_id,
      href: "#/console/" + q.case_id,
      edge: "amber",
      title: esc(q.counterparty_label),
      badges: "",
      sub: `${titleize(q.leg_type)} &middot; ${statusPill(q.status)}`,
      amountLabel: "At risk",
      amount: rupees(q.amount_at_risk),
      metaLines: `<div><span class="pill amber">${titleize(q.reason)}</span></div>
        <div>Priority ${num(Math.round(q.priority))}</div>`,
    })))}
  </div>`;
  wireFeedRows(view);
}

// --- Live Demo ----------------------------------------------------
async function renderDemo() {
  const m = encodeURIComponent(MERCHANT);
  const [scenarios, dm] = await Promise.all([
    api("/demo/scenarios"), api("/demo/merchant"),
  ]);
  view.innerHTML = `
  <div class="grid cols-2">
    <div class="panel">
      <h2>Inject a synthetic event</h2>
      <div class="faint">Each button runs the real ingestion / compliance code &mdash; no fake data.</div>
      <div class="grid mt" style="gap:8px">
        ${scenarios.map((s) => `<button class="scenario" data-key="${s.key}">
          <span class="lbl">${esc(s.label)} ${s.kind === "restraint" ? '<span class="pill amber">restraint</span>' : '<span class="pill green">acts</span>'}</span>
          <span class="desc">${esc(s.description)}</span></button>`).join("")}
      </div>
      <div class="btnrow mt">
        <button id="seed">${dm.seeded ? "Re-seed demo data" : "Seed demo data"}</button>
        <a class="btn" href="#/dashboard">Open dashboard &rarr;</a>
      </div>
    </div>
    <div class="panel">
      <div class="rowflex"><h2>Live feed</h2><span id="dot" class="faint">polling every 3s…</span></div>
      <ul class="feed" id="feed" aria-live="polite"><li class="empty">Waiting for events…</li></ul>
    </div>
  </div>`;

  view.querySelectorAll("button[data-key]").forEach((btn) => btn.onclick = async () => {
    btn.disabled = true;
    try {
      const out = await api(`/demo/inject/${btn.dataset.key}`, { method: "POST" });
      toast(`Injected — case ${out.case_id.slice(0, 8)} ${out.block_reason ? "blocked (" + titleize(out.block_reason) + ")" : "created"}`);
      await pollFeed(true);
    } catch (e) { toast(friendlyError(e), true); }
    btn.disabled = false;
  });
  $("#seed").onclick = async () => {
    $("#seed").disabled = true;
    try { const r = await api("/demo/seed?reset=true", { method: "POST" });
      toast(`Seeded — ${r.case_count} cases`); await pollFeed(true); }
    catch (e) { toast(friendlyError(e), true); }
    $("#seed").disabled = false;
  };

  let lastSeq = 0;
  async function pollFeed(force) {
    let feed;
    try { feed = await api(`/reports/${m}/activity?limit=40`); }
    catch (e) { return; }
    const items = feed.items;
    const maxSeq = items.length ? items[0].event_seq_id : 0;
    if (!force && maxSeq === lastSeq) return;
    lastSeq = maxSeq;
    $("#feed").innerHTML = items.map((e, i) => `<li class="${i < 3 ? "fresh" : ""}">
      <span class="seq">#${e.event_seq_id}</span>
      <span class="body"><span class="et">${titleize(e.event_type)}</span>
        <span class="faint"> &middot; ${titleize(e.leg_type)} &middot; ${titleize(e.case_status)}</span>
        <div class="faint">${esc(e.reasoning || "")}</div></span></li>`).join("")
      || '<li class="empty">No activity yet — inject an event</li>';
  }
  await pollFeed(true);
  pollTimer = setInterval(pollFeed, 3000);
}

// --- mobile nav ------------------------------------------------------
const navToggle = $("#navToggle");
const navEl = $("#nav");
function closeMobileNav() {
  navEl.classList.remove("open");
  if (navToggle) navToggle.setAttribute("aria-expanded", "false");
}
if (navToggle) {
  navToggle.addEventListener("click", () => {
    const open = navEl.classList.toggle("open");
    navToggle.setAttribute("aria-expanded", open ? "true" : "false");
  });
}

// --- boot ----------------------------------------------------------
merchantInput.value = MERCHANT;
merchantInput.addEventListener("change", () => {
  MERCHANT = merchantInput.value.trim();
  localStorage.setItem("torque.merchant", MERCHANT);
  route();
});
window.addEventListener("hashchange", route);
if (!location.hash) location.hash = "#/dashboard";
route();
