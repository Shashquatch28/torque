/* Torque — Module 10 UI. Vanilla JS, no build. Renders backend data only:
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
const prob = (v) => v == null ? "—" : Math.round(Number(v) * 100) + "%";
const num = (v) => Number(v || 0).toLocaleString("en-IN");
const titleize = (s) => String(s || "").replace(/_/g, " ").toLowerCase()
  .replace(/\b\w/g, (c) => c.toUpperCase());
const when = (s) => s ? new Date(s).toLocaleString("en-IN",
  { hour12: false, dateStyle: "medium", timeStyle: "short" }) : "—";

function statusPill(s) {
  const cls = { RECOVERED: "green", PARTIALLY_RECOVERED: "green", CANCELLED: "blue",
    ESCALATED_TO_HUMAN: "amber", EXHAUSTED: "red", WRITTEN_OFF: "red",
    PAUSED: "amber" }[s] || "";
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
  document.querySelectorAll(".nav a").forEach((a) =>
    a.classList.toggle("active", a.dataset.nav === name));
}

// --- routing --------------------------------------------------------
async function route() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  const hash = location.hash.replace(/^#\/?/, "") || "dashboard";
  const [name, arg] = hash.split("/");
  setActiveNav(name);
  if (!MERCHANT) { await bootstrapMerchant(); }
  view.innerHTML = '<div class="loading">Loading…</div>';
  try {
    if (name === "dashboard") return await renderDashboard();
    if (name === "cases" && arg) return await renderCaseDetail(arg);
    if (name === "cases") return await renderCases();
    if (name === "console" && arg) return await renderConsole(arg);
    if (name === "console") return await renderConsole(null);
    if (name === "demo") return await renderDemo();
    view.innerHTML = '<div class="empty">Not found</div>';
  } catch (e) {
    view.innerHTML = `<div class="panel"><h2>Could not load</h2>
      <p class="muted">${esc(e.message)}</p>
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

// --- dashboard (§10.1 / 10.2 / 10.3 / 10.4 / 10.11) ---------------
async function renderDashboard() {
  const m = encodeURIComponent(MERCHANT);
  const [rep, legs, series, top, exc] = await Promise.all([
    api(`/reports/${m}/summary`),
    api(`/reports/${m}/by-intervention?by=leg`),
    api(`/reports/${m}/over-time?bucket=day`),
    api(`/reports/${m}/top-at-risk?limit=8`),
    api(`/reports/${m}/exceptions`),
  ]);

  const ce = rep.cost_efficiency_ratio;
  view.innerHTML = `
  <div class="grid cols-2">
    <div class="panel hero">
      <div class="label">Revenue recovered by Torque</div>
      <div class="big mono">${rupees(rep.recovered_amount)}</div>
      <div class="sub">${num(rep.recovered_case_count)} recovered cases &middot;
        self-recovered (not counted): ${rupees(rep.self_recovered_amount)}</div>
    </div>
    <div class="stats">
      ${stat("Revenue at risk", rupees(rep.revenue_at_risk))}
      ${stat("Recovery rate", pct(rep.amount_recovery_rate), "pos")}
      ${stat("Unresolved", `${num(rep.unresolved_case_count)} &middot; ${rupees(rep.unresolved_amount)}`)}
      ${stat("Human escalations", num(rep.escalated_case_count), "warn")}
      ${stat("Blocked (by rule)", rupees(rep.blocked_amount), "warn")}
      ${stat("Deferred (by rule)", rupees(rep.deferred_amount), "warn")}
      ${stat("Recovered cases", num(rep.recovered_case_count), "pos")}
      ${stat("Cost efficiency", ce == null ? "—" : Number(ce).toFixed(0) + "×")}
    </div>
  </div>

  <div class="grid cols-2 mt">
    <div class="panel">
      <h2>Recovery by leg</h2>
      <table><thead><tr><th>Leg</th><th class="num">Cases</th>
        <th class="num">At risk</th><th class="num">Recovered</th>
        <th class="num">Rate</th></tr></thead><tbody>
        ${legs.map((l) => `<tr>
          <td>${titleize(l.leg_type)}</td>
          <td class="num">${num(l.cases_attempted)} / <span class="faint">${num(l.cases_recovered)} rec.</span></td>
          <td class="num">${rupees(l.revenue_at_risk)}</td>
          <td class="num" style="color:var(--green)">${rupees(l.recovered_amount)}</td>
          <td class="num">${pct(l.amount_recovery_rate)}</td></tr>`).join("")}
      </tbody></table>
    </div>
    <div class="panel">
      <h2>Recovery over time</h2>
      ${series.length ? barChart(series) : '<div class="empty">No recoveries in range yet</div>'}
      <div class="faint" style="margin-top:8px">Torque-credited recoveries, by day (UTC).</div>
    </div>
  </div>

  <div class="panel mt">
    <div class="rowflex"><h2>Top at-risk cases</h2>
      <span class="faint">ranked by Module&nbsp;8 recovery score (backend order)</span></div>
    <table><thead><tr><th>Customer</th><th>Leg</th><th>Status</th>
      <th class="num">At risk</th><th class="num">Probability</th>
      <th class="num">Score</th><th>Next</th></tr></thead><tbody>
      ${top.items.map((c) => `<tr class="clickable" data-case="${c.case_id}">
        <td>${esc(c.counterparty_label)}${c.escalated ? ' <span class="pill amber">human</span>' : ""}</td>
        <td>${titleize(c.leg_type)}</td><td>${statusPill(c.status)}</td>
        <td class="num">${rupees(c.amount_at_risk)}</td>
        <td class="num">${prob(c.recovery_probability)}</td>
        <td class="num mono">${c.recovery_score == null ? "—" : num(Math.round(c.recovery_score))}</td>
        <td class="faint">${c.next_intervention ? titleize(c.next_intervention) : "—"}</td>
      </tr>`).join("") || '<tr><td colspan="7" class="empty">No open cases</td></tr>'}
    </tbody></table>
  </div>

  <div class="panel mt">
    <div class="rowflex"><h2>Where Torque deliberately held back</h2>
      <span class="faint">compliance-by-construction &mdash; not failures</span></div>
    <table><thead><tr><th>Guardrail block reason</th><th class="num">Actions</th>
      <th class="num">Cases</th><th class="num">Revenue held</th></tr></thead><tbody>
      ${exc.blocked_by_reason.map((b) => `<tr>
        <td><span class="pill amber">${titleize(b.block_reason)}</span></td>
        <td class="num">${num(b.action_count)}</td>
        <td class="num">${num(b.case_count)}</td>
        <td class="num">${rupees(b.revenue_at_risk)}</td></tr>`).join("")
        || '<tr><td colspan="4" class="empty">No blocked actions</td></tr>'}
      ${exc.deferred_action_count ? `<tr><td><span class="pill amber">Outreach Coordinator Deferred</span></td>
        <td class="num">${num(exc.deferred_action_count)}</td>
        <td class="num">${num(exc.deferred_case_count)}</td><td class="num faint">rescheduled</td></tr>` : ""}
    </tbody></table>
  </div>`;

  view.querySelectorAll("tr[data-case]").forEach((tr) =>
    tr.addEventListener("click", () => { location.hash = "#/cases/" + tr.dataset.case; }));
}
const stat = (k, v, cls = "") =>
  `<div class="stat"><div class="k">${k}</div><div class="v ${cls} mono">${v}</div></div>`;

function barChart(series) {
  const max = Math.max(...series.map((s) => Number(s.recovered_amount)), 1);
  return `<div class="bars">${series.slice(-14).map((s) => {
    const h = Math.round((Number(s.recovered_amount) / max) * 118);
    const d = new Date(s.bucket_start);
    return `<div class="bar" title="${rupeesExact(s.recovered_amount)} on ${d.toDateString()}">
      <div class="col" style="height:${h}px"></div>
      <div class="cap">${d.getUTCDate()}/${d.getUTCMonth() + 1}</div></div>`;
  }).join("")}</div>`;
}

// --- cases list (§10.1) ---------------------------------------------
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
        <select id="fleg"><option value="">All legs</option>
          ${legs.map((l) => `<option value="${l}" ${casesFilter.leg === l ? "selected" : ""}>${titleize(l)}</option>`).join("")}</select>
        <select id="fstatus"><option value="">All statuses</option>
          ${statuses.map((s) => `<option value="${s}" ${casesFilter.status === s ? "selected" : ""}>${titleize(s)}</option>`).join("")}</select>
      </div>
    </div>
    <table><thead><tr><th>Case</th><th>Leg</th><th>Status</th>
      <th class="num">Revenue at risk</th><th>Attribution</th>
      <th class="num">Recovered</th><th>Opened</th></tr></thead><tbody>
      ${data.items.map((c) => `<tr class="clickable" data-case="${c.case_id}">
        <td class="faint mono">${c.case_id.slice(0, 8)}</td>
        <td>${titleize(c.leg_type)}</td><td>${statusPill(c.status)}</td>
        <td class="num">${rupees(c.revenue_at_risk)}</td>
        <td>${c.recovery_type ? `<span class="pill ${c.recovery_type === "SELF_RECOVERED" ? "blue" : "green"}">${titleize(c.recovery_type)}</span>` : '<span class="faint">—</span>'}</td>
        <td class="num">${c.recovered_amount ? rupees(c.recovered_amount) : "—"}</td>
        <td class="faint">${when(c.opened_at)}</td></tr>`).join("")
        || '<tr><td colspan="7" class="empty">No cases match</td></tr>'}
    </tbody></table>
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
  view.querySelectorAll("tr[data-case]").forEach((tr) =>
    tr.addEventListener("click", () => { location.hash = "#/cases/" + tr.dataset.case; }));
}

// --- case detail + explainability (§10.5 / 10.6) ------------------
async function renderCaseDetail(caseId) {
  const m = encodeURIComponent(MERCHANT);
  const [c, events] = await Promise.all([
    api(`/reports/${m}/cases/${caseId}`),
    api(`/reports/${m}/cases/${caseId}/events`),
  ]);
  const b = c.recovery_score_breakdown;
  const ex = b && b.explain;
  view.innerHTML = `
  <a class="back" href="#/cases">&larr; All cases</a>
  <div class="grid cols-2 mt">
    <div class="panel">
      <h2>Case overview</h2>
      <div class="rowflex"><div>
        <div style="font-size:18px;font-weight:650">${esc(c.counterparty_label)}</div>
        <div class="faint mono">${c.case_id}</div>
      </div>${statusPill(c.status)}</div>
      <table class="mt"><tbody>
        ${kv("Leg", titleize(c.leg_type))}
        ${kv("Revenue at risk", rupeesExact(c.revenue_at_risk))}
        ${kv("Amount at risk (current)", rupeesExact(c.amount_at_risk))}
        ${kv("Root cause", c.root_cause_code ? titleize(c.root_cause_code) : "—")}
        ${kv("Diagnosis confidence", c.diagnosis_confidence == null ? "—" : c.diagnosis_confidence.toFixed(2))}
        ${kv("Recovery score", c.recovery_score == null ? "—" : num(Math.round(c.recovery_score)))}
        ${kv("Recovery probability", prob(c.recovery_probability))}
        ${kv("Attribution", c.recovery_type ? titleize(c.recovery_type) : "—")}
        ${kv("Recovered", c.recovered_amount ? rupeesExact(c.recovered_amount) : "—")}
        ${c.escalation_resolution ? kv("Human resolution", `${titleize(c.escalation_resolution)} (by ${esc(c.escalation_resolved_by || "agent")})`) : ""}
        ${c.in_human_queue ? kv("Human queue", titleize(c.human_queue_reason)) : ""}
      </tbody></table>
    </div>
    <div class="panel">
      <h2>Why this case?</h2>
      ${ex ? `<div class="why">
        <div class="metric"><div class="k">Recovery probability</div><div class="v">${prob(b.probability)}</div></div>
        <div class="metric"><div class="k">Amount at risk</div><div class="v">${rupeesExact(ex.amount_at_risk)}</div></div>
        <div class="metric"><div class="k">Expected intervention cost</div><div class="v">${rupeesExact(ex.expected_cost)}</div></div>
        <div class="metric"><div class="k">Priority score</div><div class="v">${num(Math.round(Number(ex.priority_score)))}</div></div>
      </div>
      <ul class="why-lines">${(ex.why || []).map((w) => `<li>${esc(w)}</li>`).join("")}</ul>
      <div class="faint">probability &times; amount &divide; expected cost &mdash; computed by Module&nbsp;8, rendered verbatim.</div>`
      : '<div class="empty">Not scored yet (terminal or pre-diagnosis case).</div>'}
    </div>
  </div>

  <div class="panel mt">
    <h2>Audit trail &mdash; why the agent did this</h2>
    <ul class="timeline">
      ${events.map(renderEvent).join("") || '<li class="empty">No events</li>'}
    </ul>
  </div>`;
}
const kv = (k, v) => `<tr><td class="faint">${k}</td><td class="right">${v}</td></tr>`;

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
  return `<li class="${cls}">
    <div class="ts">${when(e.timestamp)} &middot; #${e.event_seq_id} &middot; ${e.actor}</div>
    <div class="ev">${titleize(e.event_type)}</div>
    ${e.reasoning ? `<div class="why">${esc(e.reasoning)}</div>` : extra}
  </li>`;
}

// --- Agent Console (§10.7 / 10.8) --------------------------------
async function renderConsole(caseId) {
  const m = encodeURIComponent(MERCHANT);
  const queue = await api(`/reports/${m}/human-queue`);
  const detail = caseId
    ? `<div id="cpane" class="panel">Loading case…</div>`
    : `<div class="panel"><div class="empty">Select a case from the queue.</div></div>`;
  view.innerHTML = `
  <div class="grid cols-2">
    <div class="panel">
      <div class="rowflex"><h2>Human queue &mdash; ${queue.items.length}</h2>
        <span class="faint">ordered by economic priority (Module&nbsp;8 seam)</span></div>
      <table><thead><tr><th>Customer</th><th>Reason</th><th>Status</th>
        <th class="num">At risk</th><th class="num">Priority</th></tr></thead><tbody>
        ${queue.items.map((q) => `<tr class="clickable" data-case="${q.case_id}">
          <td>${esc(q.counterparty_label)}</td>
          <td><span class="pill amber">${titleize(q.reason)}</span></td>
          <td>${statusPill(q.status)}</td>
          <td class="num">${rupees(q.amount_at_risk)}</td>
          <td class="num mono">${num(Math.round(q.priority))}</td></tr>`).join("")
          || '<tr><td colspan="5" class="empty">Queue is empty</td></tr>'}
      </tbody></table>
    </div>
    ${detail}
  </div>`;
  view.querySelectorAll("tr[data-case]").forEach((tr) =>
    tr.addEventListener("click", () => { location.hash = "#/console/" + tr.dataset.case; }));
  if (caseId) await renderConsolePane(caseId);
}

async function renderConsolePane(caseId) {
  const m = encodeURIComponent(MERCHANT);
  const pane = $("#cpane");
  const [c, events] = await Promise.all([
    api(`/reports/${m}/cases/${caseId}`),
    api(`/reports/${m}/cases/${caseId}/events`),
  ]);
  const b = c.recovery_score_breakdown, ex = b && b.explain;
  const canResolve = c.status === "ESCALATED_TO_HUMAN";
  const canPause = c.status === "PLAYBOOK_ACTIVE";
  const canUnpause = c.status === "PAUSED";
  pane.innerHTML = `
    <div class="rowflex"><div>
      <div style="font-size:16px;font-weight:650">${esc(c.counterparty_label)}</div>
      <div class="faint mono">${c.case_id.slice(0, 8)} &middot; ${titleize(c.leg_type)}</div>
    </div>${statusPill(c.status)}</div>
    <div class="stats mt" style="grid-template-columns:repeat(2,1fr)">
      ${stat("Revenue at risk", rupees(c.revenue_at_risk))}
      ${stat("Recovery score", c.recovery_score == null ? "—" : num(Math.round(c.recovery_score)))}
    </div>
    ${ex ? `<ul class="why-lines mt">${(ex.why || []).map((w) => `<li>${esc(w)}</li>`).join("")}</ul>` : ""}
    <div class="btnrow mt">
      <select id="res">
        <option value="RECOVERED_BY_HUMAN">Resolve — recovered</option>
        <option value="PARTIALLY_RECOVERED_BY_HUMAN">Resolve — partial</option>
        <option value="WRITTEN_OFF">Write off</option>
      </select>
      <input id="amt" type="number" placeholder="recovered ₹ (optional)" style="width:170px" />
      <button class="primary" id="doResolve" ${canResolve ? "" : "disabled"}>Resolve</button>
      <button id="doPause" ${canPause ? "" : "disabled"}>Pause</button>
      <button id="doUnpause" ${canUnpause ? "" : "disabled"}>Un-pause</button>
    </div>
    <div class="faint" style="margin-top:6px">Resolve is available only for an escalated case; pause only for one still in a playbook.</div>
    <h2 class="mt">Audit trail</h2>
    <ul class="timeline">${events.slice(-8).map(renderEvent).join("")}</ul>`;

  const act = async (path, body) => {
    try {
      const out = await api(`/agent-console/${m}/cases/${caseId}/${path}`, {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
      });
      toast(`${titleize(out.from_status)} → ${titleize(out.to_status)}`);
      await renderConsole(caseId);
    } catch (e) { toast(e.message, true); }
  };
  $("#doResolve").onclick = () => act("resolve", {
    resolution: $("#res").value, agent_id: "demo-agent",
    recovered_amount: $("#amt").value || null,
  });
  $("#doPause").onclick = () => act("pause", { agent_id: "demo-agent" });
  $("#doUnpause").onclick = () => act("unpause", { agent_id: "demo-agent" });
}

// --- Live Demo (§10.9 / 10.10 / 10.17) --------------------------
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
      <ul class="feed" id="feed"><li class="empty">Waiting for events…</li></ul>
    </div>
  </div>`;

  view.querySelectorAll("button[data-key]").forEach((btn) => btn.onclick = async () => {
    btn.disabled = true;
    try {
      const out = await api(`/demo/inject/${btn.dataset.key}`, { method: "POST" });
      toast(`Injected — case ${out.case_id.slice(0, 8)} ${out.block_reason ? "blocked (" + titleize(out.block_reason) + ")" : "created"}`);
      await pollFeed(true);
    } catch (e) { toast(e.message, true); }
    btn.disabled = false;
  });
  $("#seed").onclick = async () => {
    $("#seed").disabled = true;
    try { const r = await api("/demo/seed?reset=true", { method: "POST" });
      toast(`Seeded — ${r.case_count} cases`); await pollFeed(true); }
    catch (e) { toast(e.message, true); }
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
