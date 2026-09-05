# Torque UI/UX Blueprint

**Scope of this document:** presentation-layer redesign only. Torque's domain/state-machine logic, guardrails, tenant isolation, and the AI layer (Phases 0–8, `ai-layer` branch) are stable and are treated as fixed contracts. This blueprint is grounded directly in the current repository — `src/torque/ui/static/{index.html,torque.css,torque.js}`, `src/torque/api/{ai,agent_console,reporting}.py`, and `src/torque/ai/schemas.py` — not in assumptions about what a "typical" product like this looks like. Every screen, field, and endpoint named below is verified against that code; where a recommendation would require a backend change, it is called out explicitly in §26 and nowhere else.

---

## 1. Design Objective

Torque already works. Module 1–12a are implemented and tested (pytest green in the thousands across the modules; see `documentation/ai-memory/MILESTONES.md`), and the AI layer (evidence → citations → precedent → narrative → faithfulness evaluation → Agent Console integration) is complete through Phase 8. What is missing is not functionality — it is legibility. A first-time viewer (a hackathon judge, a new operator) cannot currently tell, in the time they're willing to give it, that any of this exists.

One sentence governs every decision in this document:

> **Make the complexity of Torque feel simple.** A reviewer should understand the product in about 30 seconds, and should be able to answer, unprompted, at every point in the product: *where am I, what am I looking at, what does Torque know, what does the AI think, why, and what should I do next.*

This is a presentation-layer program. It does not add features. Two of the highest-value moves in this blueprint — surfacing the AI panel on the primary case page, and anchoring evidence citations to on-screen rows — are **information-architecture and rendering fixes**, not new capabilities: the data these need already flows through the existing API today (see §15, §16).

---

## 2. Product Experience Principles

1. **Torque decides. The UI never blurs that.** Every screen must make it visually unambiguous which numbers are authoritative case state (status, amount recovered, guardrail blocks) and which are AI interpretation (a narrative claim, a precedent, a shadow score — the last of which has no UI surface today and should get none, see §26). The current codebase already enforces this at the API level (`torque.ai` cannot write; `CaseNarrative`'s identity fields are server-stamped, never provider-trusted); the UI's job is to make that same boundary *visible*, not just true.
2. **One case, one page.** Today the product renders a case twice — once as a read-only `Case Detail` view (`renderCaseDetail`, full field table, no actions, no AI) and once as a stripped-down `Agent Console` pane (`renderConsolePane`, fewer fields, has actions and the AI button). A judge who browses `Cases → [click a case]` never sees the "Explain this case" button at all. This is the single biggest fix in this document (§5, §14).
3. **Every AI claim is a pointer, not a paragraph.** A narrative claim without a citation is not shown as fact; a citation without an on-screen destination is not shown as a link. Today two of the five evidence types (`action`, `promise`) already carry an anchorable id in their `CaseEvent` payload but nothing in the DOM exposes it (§16) — fix the rendering, not the data model.
4. **Numbers earn their size.** One hero number per screen, maximum. Today the dashboard has exactly one (₹ recovered); the case page has none — recovery score and probability sit in a plain table row despite being the entire reason a case is being looked at.
5. **Restraint is a feature, not an apology.** Torque's guardrails/compliance blocks are a genuine differentiator ("compliance-by-construction"). The current "Where Torque deliberately held back" table is a good instinct — keep the *concept*, upgrade the *presentation* to read as confidence, not as an error log.
6. **Nothing is invented for the demo.** Every visualization, badge, and metric in this blueprint maps to a field the API already returns (see the field inventories in §7, §19). Where something doesn't exist yet, §26 says so plainly instead of quietly assuming it.

---

## 3. Current UI Audit

### 3.1 What exists today (verified against code)

| Area | Current state |
|---|---|
| Stack | Hand-written static SPA — `index.html` + `torque.css` + `torque.js`, vanilla JS, no framework, no build step (D-122). Hash router (`#/dashboard`, `#/cases`, `#/cases/:id`, `#/console`, `#/console/:id`, `#/demo`). Mounted at `/ui` alongside the JSON API on one process/port. |
| Screens | Dashboard, Cases (list), Case Detail, Agent Console (queue + pane), Live Demo. Five screens total — no settings, no auth UI (single-merchant-id text field in the top bar, backed by `localStorage`). |
| Visual base | **Already dark-canvas, charcoal-surface, hairline-border, no-heavy-shadow** — `--bg:#0b0f14`, `--panel:#121821`, `--panel-2:#171f2b`, `--line:#24303f`, single `10px` radius, `18px 20px` panel padding. This is closer to the reference direction than a typical "basic" product; the gap is in *hierarchy, scale, and one missing accent color*, not in having to invent a dark theme from nothing. |
| Color roles in use | `--green` (success/positive), `--amber` (warning), `--red` (danger), `--blue` (used for **two unrelated things**: general "informational" pills *and* the AI/citation accent — the AI narrative left-rail, citation chips, and the Module 9b incrementality card all use the same blue as ordinary info pills). No gold/accent color exists anywhere in the stylesheet. |
| Typography | System font stack (`-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial`), no webfont, no CDN dependency — consistent with the project's offline/no-build/free-tier constraint (D-122; blueprint §0 "everything runs on free tiers"). One real hero size (46px, the dashboard's recovered-amount number); everything else is 11–22px with limited scale steps. |
| Grid | `.grid.cols-2` / `.cols-3`, one breakpoint at 900px collapsing to a single column. No tablet-specific column count, no table-to-card transform, no touch-target sizing pass. |
| Loading | A single literal string, `"Loading…"`, replaces the entire `#view` on every navigation — no skeleton, no partial-content preservation. |
| Empty states | Consistent `.empty` convention already used across every table ("No open cases", "No cases match", "Queue is empty") — this pattern is good and should be kept, just restyled. |
| Errors | Generic panel dump of `e.message` in most routes; the AI route (`explainCase`) already has a good, human-worded mapping (503 → "AI explanations are not enabled…", 404 → "This case could not be found.") — this pattern should be generalized to every other route instead of invented fresh. |
| Toasts | Bottom-right, green/red border, 3.2s auto-dismiss. Reasonable, minimal — keep the mechanism, restyle. |
| Accessibility | No explicit `:focus-visible` styling anywhere in the stylesheet (relies on browser default). No `aria-current` on the active nav link (class-only). No `prefers-reduced-motion` guard on the toast/citation-flash keyframes. Status is always paired with a text label, not color alone (good). |
| Responsiveness | Effectively **two-tier** (desktop / "everything ≤900px squeezed into one column"), not three-tier. No horizontal-scroll containers on any table — on a narrow viewport, the 7-column Cases table and Top-at-risk table will compress or overflow the page rather than scrolling in place. |

### 3.2 The five concrete problems, in priority order

1. **AI is orphaned.** "Explain this case" and the citation-grounded narrative exist only inside the Agent Console pane (`renderConsolePane`), reachable by clicking a human-queue row or manually editing the URL to `#/console/<case_id>`. The primary browsing path — `Cases → click a row → Case Detail` (`renderCaseDetail`) — has no AI entry point at all. For a hackathon judge, this means the product's headline differentiator is invisible unless they happen to go through the escalation queue.
2. **Two competing case views.** `renderCaseDetail` (read-only, full field table, no actions) and `renderConsolePane` (fewer fields, has resolve/pause/AI) are separately maintained partial views of the same case. This is real duplication with real drift risk, and it splits "what is this case" from "what can I do about it."
3. **AI accent color collides with "informational."** `--blue` means both "this is a link/info pill" and "this is AI-generated" today. A reviewer has no color cue to tell authoritative-blue from AI-blue apart.
4. **Evidence has no visual home.** `Action` and `PromiseToPay` are cited by AI narratives (`action:<id>`, `promise:<id>`) but rendered nowhere as their own row — they only appear indirectly, folded into `CaseEvent` timeline entries. A citation click for these types cannot resolve to anything on screen today (`focusCitation` only handles `case_event:<seq>`; everything else falls back to a toast). Two of the five evidence types (`case`, `counterparty_relationship`) genuinely have no matching authoritative UI to point at yet — see §26.
5. **No responsive design system**, just a single collapse point — real risk on tablet/mobile for a data-dense product whose primary content is tables.

None of these are backend problems. All five are addressed in §5, §14, §15, §16 without touching `torque.ai`, `torque.reporting`, `torque.agent_console`, or the state machine.

---

## 4. Target Experience

Torque should read as an **instrument panel for a revenue-recovery operator**, not a finance dashboard and not a chat product bolted onto a table. Concretely:

- The existing dark/charcoal palette is kept and refined, not replaced.
- A gold/amber-adjacent-but-distinct accent (`--ai`, see §10) is introduced and used **exclusively** for AI-sourced content — never for status, never for warnings, never decoratively.
- One canonical `CaseView` component replaces the two competing case renderers; Agent Console becomes that same view plus a contextual action rail, not a separate page.
- Every screen keeps (and sharpens) the existing "flow ribbon" concept — it is already a good instinct (a one-line explanation of the whole recovery loop, visible on every page) and should be leaned into, not removed.
- A judge's 30-second path: **Dashboard hero number → a top-at-risk row → Case header (status + amount, unmistakably authoritative) → AI Assessment card (unmistakably AI, gold rail, one summary + a confidence cue) → a citation chip → the exact evidence row it points to, highlighted → Precedent → done.** Every one of those steps exists in the API today; only the last (a properly-anchored `action`/`promise` citation) needs a small, purely-frontend rendering fix (§16).

---

## 5. Information Architecture

### 5.1 Navigation (unchanged structure, sharpened labels)

```
Dashboard        (was: Dashboard — keep)
Cases            (was: Cases — keep; becomes the canonical case entry point)
Agent Console    (was: Agent Console — keep; becomes "Cases + queue + actions" context, not a second case renderer)
Live Demo        (was: Live Demo — keep, judges use this directly)
```

No new top-level nav item. A settings/admin screen is explicitly a non-goal (§29) — there is no such backend surface today and none is proposed.

### 5.2 The core IA fix

Today:

```
Cases ──click──▶ Case Detail (renderCaseDetail)     [no AI, no actions]
Agent Console ──click a queue row──▶ Console Pane (renderConsolePane)  [AI + actions, fewer fields]
                                        ▲
                         (only reachable via the queue, or a hand-typed URL)
```

Target:

```
Cases ──click──▶  Case View  (one component)
Agent Console ──click a queue row──▶  same Case View, same URL space (#/cases/:id)
                                        │
                                        ├─ always renders: header, summary, AI Assessment
                                        │  entry point, timeline, evidence, precedent
                                        └─ conditionally renders: the action rail
                                           (resolve/pause/unpause), shown only when
                                           the case is actually ESCALATED_TO_HUMAN /
                                           PLAYBOOK_ACTIVE / PAUSED — i.e. exactly the
                                           states that already gate those buttons today
```

`#/console/:id` becomes an alias that opens the same `Case View` with the action rail expanded by default; `#/console` (no id) stays the queue list. This removes the duplication without removing a single existing capability — every current permission check (`canResolve`, `canPause`, `canUnpause`) carries over unchanged.

### 5.3 The five orienting questions, per screen

| Screen | Where am I? | What am I looking at? | What can I do? | What changed? | What deserves attention? |
|---|---|---|---|---|---|
| Dashboard | Top nav "Dashboard" active | Merchant-wide recovery performance | Drill into a leg, a top-at-risk case, or an exception | Recovery-over-time chart | Top-at-risk list, exceptions table |
| Cases | Top nav "Cases" active, filter chips shown | A filtered, paginated case list | Filter by leg/status, open a case | (list re-sorts/filters) | Escalated / blocked rows visually flagged |
| Case View | Breadcrumb back to Cases (or Queue) | One case: identity → summary → AI → timeline → evidence → precedent | Explain this case; resolve/pause if eligible | Live status pill, new events at top of timeline | AI Assessment card, "why" lines |
| Agent Console (queue) | Top nav "Agent Console" active | Cases currently needing a human, priority-ordered | Open one → Case View with action rail | Queue count | Reason pill, priority |
| Live Demo | Top nav "Live Demo" active | Scenario buttons + live activity feed | Seed data, inject a scenario | Feed items flash in | "restraint" vs "acts" labelled scenarios |

---

## 6. User Journeys

**J1 — Judge, cold start (the demo journey; see §24 for the full script).** Land on Dashboard → read the hero number and flow ribbon → open a top-at-risk case → read the case header (authoritative) → open AI Assessment → click a citation → watch the exact evidence row highlight → check Precedent → done. Target: under 30 seconds to the first "oh, I get it."

**J2 — Operator, working the queue.** Agent Console → sorted by priority → open the top row → read the "why" lines (already server-computed, `recovery_score_breakdown.explain.why`) → optionally generate an AI explanation for extra context → resolve or pause. This is today's `renderConsolePane` flow, preserved, just merged into the canonical Case View.

**J3 — Analyst, investigating a leg.** Dashboard → "Recovery by leg" table → Cases filtered by that leg + status → sort/browse → open specific cases for root-cause patterns → cross-reference Precedent sections across a few cases.

**J4 — Skeptic, verifying an AI claim.** Case View → AI Assessment → pick any claim → click its citation chip → confirm the underlying evidence row is the exact same authoritative data already visible in the timeline/evidence panel above — never a second, parallel representation.

---

## 7. Screen-by-Screen Specification

### 7.1 Dashboard (`#/dashboard`)

**Data source (unchanged):** `GET /reports/{m}/summary`, `/by-intervention?by=leg`, `/over-time?bucket=day`, `/top-at-risk`, `/exceptions`, `/incrementality`.

```
DESKTOP (≥1200px)
┌────────────────────────────────────────────────────────────────────────┐
│ Torque   Dashboard  Cases  Agent Console  Live Demo         merchant:▢ │
├────────────────────────────────────────────────────────────────────────┤
│ Revenue at Risk → AI/Decisioning → Priority → Guardrails → Action → ₹  │
├───────────────────────────────────┬──────────────────────────────────┤
│ HERO: ₹ Recovered by Torque        │ Revenue at risk   │ Recovery rate │
│ 46px, green accent line             │ Unresolved         │ Escalations   │
│ recovered cases · self-recovered    │ Blocked            │ Deferred      │
│ (shown, not counted)                │ Recovered cases    │ Cost eff. ×   │
├───────────────────────────────────┴──────────────────────────────────┤
│ Recovery by leg (table)             │ Recovery over time (bar chart)   │
├──────────────────────────────────────────────────────────────────────┤
│ Incrementality — estimated causal effect   [causal estimate pill]      │
│ treatment rate | control rate | lift | SUTVA-adjusted lift (4 metrics) │
├──────────────────────────────────────────────────────────────────────┤
│ Top at-risk cases (clickable rows, ranked by recovery_score)            │
├──────────────────────────────────────────────────────────────────────┤
│ Where Torque deliberately held back (guardrail exceptions)              │
└──────────────────────────────────────────────────────────────────────┘
```

Changes from current: hero card gains a slightly larger radius (20px vs 10px) to read as the "instrument panel" centerpiece; stat tiles get a consistent 4-up→2-up→1-up responsive collapse (see §12); the incrementality card's blue accent is kept (it is genuinely "informational/statistical," not AI-generated — a real, deliberate distinction from the AI-gold accent, see §10.4); top-at-risk rows gain a small AI-gold dot when `escalated` is true *and* a narrative has plausibly not yet been reviewed (frontend-only convention, no new field required — see §26 if a "has this been explained" flag is wanted later).

### 7.2 Cases (`#/cases`)

Filter bar (leg, status) + paginated table, unchanged data contract (`GET /reports/{m}/cases`). Row click → Case View. Add: status-colored left-edge bar per row (2px) instead of relying solely on the pill, for faster scanning; escalated/blocked cases get a small indicator so an operator can triage the list without opening every row.

### 7.3 Case View (`#/cases/:id`, alias `#/console/:id`) — the canonical single-case screen

This is the merge of today's `renderCaseDetail` + `renderConsolePane`. Full spec in §14.

### 7.4 Agent Console queue (`#/console`)

Unchanged: priority-ordered human queue (`GET /reports/{m}/human-queue`), reason pill, amount, priority. Row click → Case View with the action rail expanded.

### 7.5 Live Demo (`#/demo`)

Unchanged mechanism (scenario buttons calling `POST /demo/inject/{key}`, 3s-polled activity feed from `GET /reports/{m}/activity`). Visual refresh only: scenario buttons already correctly distinguish "acts" (green pill) vs "restraint" (amber pill) kinds — keep this, it is one of the product's best existing storytelling devices; give it more visual weight (§24).

---

## 8. Design Language

Extracted from the two reference screenshots and adapted — explicitly **not** copied — for an operational case-management product:

| Reference characteristic | Torque adaptation |
|---|---|
| Near-black canvas, charcoal cards, hairline borders, no drop shadows | Already Torque's baseline (`--bg`/`--panel`/`--line`) — keep, refine radius scale |
| Gold/yellow as one sparse highlight (the "Stocks 85%" bar, the portfolio-chart callout) | A new `--ai` gold token, used **only** for AI-sourced content — never decoratively, never for a status pill |
| Semi-circular gauge for a single 0–100 score | Adopted for exactly one place: an optional confidence/probability ring on the Case header (§14, §19) — not overused |
| Diagonal-hatch texture for an inactive/no-data series ("Crypto" column) | Adopted for empty-state chart placeholders and the "no precedent" panel — a textured absence, not a blank box |
| Large, confident hero numbers with tiny uppercase labels above them | Applied to: dashboard ₹ recovered (already present), and newly to the Case header's recovery score |
| Row of small circular source-logo chips | Conceptually mirrors Torque's citation chips — keep chips pill-shaped (not circular avatars; Torque's citations are labeled facts, not brand marks) |
| Minimal iconography, one icon button per card | Torque should stay at or below this bar — no icon library, unicode/CSS-drawn glyphs only (matches the existing `◧`/`→` marks in `index.html`, zero new dependency) |

**What is deliberately NOT adopted:** ticker-style sparkline rows (no market-data analog in Torque), a fintech color story (no red/green as "market direction" — red/green stay strictly status-semantic per §10), any stock-app chrome (logos, tickers, asset-class language).

---

## 9. Typography System

Keep the existing system-font stack (no webfont, no CDN — matches the offline/free-tier/no-build constraint). Extend the scale:

| Role | Size / weight | Usage |
|---|---|---|
| Display | 46px / 750, tabular-nums | Dashboard ₹ recovered (existing), Case-header recovery score (new) |
| H1 (page title) | 20px / 650 | Not currently used as a distinct level — introduce for page-level titles ("Case · <counterparty>") |
| H2 (section) | 13px / 550, uppercase, 0.08em tracking | Existing `.panel h2` style — keep verbatim, it already reads as a clean section label |
| Body | 14px / 400, 1.5 line-height | Existing base — keep |
| Metadata / label | 11–11.5px / 550, uppercase, letter-spacing | Existing `.stat .k`, `.pill` sizing — keep |
| Numeric / tabular data | inherit size, `font-variant-numeric: tabular-nums` | Already applied via `.mono` — extend to every currency/score/percentage, not just the ones that currently opt in |
| Button | 13px / 600 | Existing — keep |
| AI claim text | 14px / 400, no italics (never signal AI with italics — the gold rail + icon already do that job) | New — see §15 |

No size above 46px; no more than five weights in the whole system (400/550/600/650/750, all already in use).

---

## 10. Color System

### 10.1 Tokens (kept, refined, one addition)

```css
--bg:        #0b0f14   /* app canvas — unchanged */
--panel:     #121821   /* elevated surface — unchanged */
--panel-2:   #171f2b   /* secondary/hover surface — unchanged */
--line:      #24303f   /* hairline border — unchanged */
--ink:       #e8eef6   /* primary text — unchanged */
--ink-dim:   #93a1b4   /* secondary text — unchanged */
--ink-faint: #63728a   /* muted/tertiary text — unchanged */
--green:     #35d07f   /* success / positive / recovered — unchanged */
--green-dim: #1f6f4a
--amber:     #f2b544   /* warning / guardrail-blocked / paused — unchanged, semantic ONLY */
--red:       #ef6a6a   /* danger / exhausted / written-off — unchanged */
--blue:      #5aa0f0   /* informational / links / statistical (incrementality) — narrowed scope, see 10.4 */
--ai:        #d9a441   /* NEW — AI-sourced content only. A deliberately different value from --amber
                          (deeper, less saturated gold) so the two are never mistaken at a glance even
                          though both sit in the amber/gold family. */
--ai-dim:    #6b4f1e   /* NEW — AI accent's border/dim companion, mirrors the --green/--green-dim pattern */
```

### 10.2 Semantic rules

- **Green** = money actually recovered, a successful resolution. Never used for anything else.
- **Amber** = the system deliberately restrained itself (guardrail block, paused case, deferred outreach) or a human-attention state (escalated). This is a *positive* signal in Torque's own story (compliance-by-construction) — style it calm, not alarming.
- **Red** = terminal negative outcomes only (exhausted, written off, hard failures). Used sparingly — Torque should not read as an error-heavy product.
- **Blue** = ordinary informational chrome: links, the incrementality/causal card, neutral pills (e.g. "Cancelled"). This is **not** the AI color.
- **Gold (`--ai`)** = exclusively AI-sourced content: the AI Assessment card's left rail and header icon, citation chips, the narrative's confidence/uncertainty line, precedent-section accents. If a human could mistake a gold element for authoritative case data, the design has failed — gold must never appear on a status pill, a table row, or a KPI tile.

### 10.3 Contrast

All text-on-surface pairs above already meet WCAG AA at body-text sizes (`--ink` on `--bg`/`--panel` ≈ 14:1; `--ink-dim` on `--panel` ≈ 5.2:1; `--ink-faint` on `--panel` ≈ 3.1:1 — used only for non-essential metadata, never for a value a user must read). `--ai` (`#d9a441`) on `--panel` (`#121821`) ≈ 7.4:1 — passes AA for text use, not just decorative accents.

### 10.4 Why blue stays on the incrementality card

The Module 9b causal-lift card is **statistical, not AI-generated** — it is a deterministic Wilson/Newcombe confidence-interval computation over real treatment/control cohorts (`torque.reporting.incrementality`), with zero LLM involvement. Giving it the gold AI accent would misrepresent it as AI output. Blue (informational/statistical) is the correct, honest color for this card, and this document keeps it there deliberately.

---

## 11. Spacing & Layout System

| Token | Value | Usage |
|---|---|---|
| Page gutter | 26px (existing `.view` padding) — keep | Outer page margin |
| Max content width | 1180px (existing) — keep | `.view` |
| Card padding | 20px standard / 16px "tight" (existing `.panel` / `.panel.tight`) — keep | |
| Grid gap | 16px section-to-section / 12px within a stat row (existing) — keep | |
| Spacing scale | 4 · 8 · 12 · 16 · 24 · 32 · 48 | New explicit scale — codify the values already used ad hoc |
| Radius scale | 8px (chips/pills, unchanged) · 12px (standard panel, up from 10px) · 20px (hero/dashboard cards) | Slight expansion — hero cards get the larger, more "instrument panel" radius from the reference screenshots; nested tiles stay tighter |
| Control height | 36px standard (up from ~30px) · 44px on touch (tablet/mobile) | Accessibility fix — see §22 |

---

## 12. Responsive Design System

Current state is effectively one breakpoint (900px). Replace with three tiers:

**Desktop (≥1200px).** Full multi-column layouts as specified per screen (§7). Tables render in full, all columns visible. Nav is a plain horizontal row (unchanged).

**Tablet (768–1199px).** Two-column grids collapse to one column top-to-bottom in priority order (hero/summary first, breakdowns second). Wide tables (Cases list, Top-at-risk, Recovery-by-leg) get an explicit `overflow-x: auto` wrapper — the table itself does not reflow, it scrolls within its own card, and the page body never scrolls horizontally. Nav stays a horizontal row but wraps to a second line if needed rather than being hidden.

**Mobile (<768px).** Single column everywhere. The four-column stat-tile grid becomes 2×2 then 1-per-row below ~400px. Tables of 5+ columns convert to a **stacked card per row** (label:value pairs), not a horizontally-scrolling table — this is a genuine transform, not a shrink: each Cases-list row becomes a small card showing counterparty, status pill, amount, and a "View" affordance, with leg/attribution/opened-date demoted to a secondary line. The Case View's evidence/timeline/precedent sections become **stacked accordions** (collapsed by default below Case Header + AI summary, tap to expand) so the 30-second story still fits above the fold. Citation chips remain tappable inline text, never hidden behind a hover-only affordance. Minimum touch target 44×44px for every button/pill/nav link (a real change from today's ~30px controls). The merchant-id field and nav collapse into a single top-bar row with the brand mark and a compact menu.

No component in this system requires horizontal page scroll at any width; the only intentional horizontal scroll is the contained one described for tablet-width tables.

---

## 13. Component System

| Component | Purpose | Key states | Responsive note |
|---|---|---|---|
| `AppShell` | Top bar, nav, flow ribbon, footer (all exist today) | active nav (add `aria-current`) | Mobile: collapses to brand + hamburger |
| `FlowRibbon` | The existing recovery-loop strip — kept, not replaced | static | Wraps to 2 lines on narrow widths rather than disappearing |
| `PageHeader` | Title + breadcrumb + primary action | — | — |
| `MetricCard` / `StatTile` | One KPI (existing `.stat`) | pos/warn coloring (existing) | 4→2→1 columns |
| `HeroMetric` | The one big number per screen (existing `.hero`, extended to Case header's score) | — | Font scales 46→36→30px |
| `CaseHeader` | Identity, status pill, leg, key authoritative facts | — | Stacks vertically on mobile |
| `AIAssessmentCard` | The gold-railed AI summary + entry point (new, see §15) | idle / loading / generated / disabled(503) / not-found(404) / error(502/500) | Accordion-collapsible on mobile |
| `ConfidenceRing` | Optional semi-circular gauge for one 0–1 score | — | Used sparingly (§19) |
| `Timeline` / `TimelineEvent` | Existing `.timeline` list, `data-event-seq` anchors — keep, extend styling | ok/block/default (existing) | — |
| `EvidenceCard` / `EvidencePanel` | **New** — a dedicated list of `Action`/`PromiseToPay` rows, each carrying `data-action-id`/`data-promise-id` so citations resolve (§16) | — | Collapsible accordion on mobile |
| `Citation` / `CiteChip` | Existing `.cite` pill — restyle in `--ai` gold, keep click-to-locate behavior | resolved / unresolved-toast fallback | — |
| `PrecedentCard` | Existing precedent table inside the narrative — promote to its own card (§18) | found / not-found (textured empty state) | — |
| `DataTable` | Existing `<table>` pattern | hover row (existing) | Tablet: scroll wrapper; Mobile: card-stack transform |
| `StatusBadge`/`Pill` | Existing `.pill` — keep, semantic colors only | green/amber/red/blue (never gold) | — |
| `EmptyState` | Existing `.empty` — restyle with the hatch-texture treatment for chart-adjacent emptiness | — | — |
| `LoadingState` | **New** — skeleton blocks matching the target layout, replacing the literal "Loading…" string | — | — |
| `ErrorState` | Existing pattern from the AI route, generalized to every route | — | — |
| `Toast` | Existing, kept | success/error | Respect `prefers-reduced-motion` |
| `Modal`/`Drawer` | Not currently used; **not introduced** — Torque's flows (resolve/pause) are simple enough for inline controls, and a modal would fight the "no chatbot-in-a-dashboard" instruction. Keep inline. |
| `Tabs` | Not currently used; not introduced — the case page uses vertical progressive disclosure instead (§14), which better matches "hierarchy instead of excessive text" |
| `Filters`/`Search` | Existing `<select>` filter bar on Cases — keep, restyle to 36px control height |

---

## 14. Case Experience

This is the core fix. One component (`CaseView`), rendered at `#/cases/:id`, reachable from every entry point (Cases list, Dashboard top-at-risk, Agent Console queue).

```
DESKTOP
┌──────────────────────────────────────────────────────────────────┐
│ ← Back           Case · Priya N.                    [PLAYBOOK_ACTIVE]│
├──────────────────────────────────────────────────────────────────┤
│ CASE HEADER — leg, revenue at risk, amount at risk, opened, root   │
│ cause, recovery score (hero-sized), recovery probability, human    │
│ queue flag if present. Everything here is AUTHORITATIVE (ink text, │
│ no gold anywhere in this block).                                   │
├──────────────────────────────────────┬─────────────────────────┤
│ WHY THIS CASE? (recovery_score        │ AI ASSESSMENT               │
│ _breakdown.explain, server-computed,   │ [gold left rail]             │
│ authoritative — probability × amount   │ "Explain this case" (idle)  │
│ ÷ expected cost, + why[] lines)         │ → summary, current-state,   │
│                                         │   root-cause claim, each     │
│                                         │   with citation chips        │
├──────────────────────────────────────┴─────────────────────────┤
│ ACTION RAIL (only if case is ESCALATED_TO_HUMAN / PLAYBOOK_ACTIVE / │
│ PAUSED) — resolve / pause / unpause, unchanged from today            │
├──────────────────────────────────────────────────────────────────┤
│ TIMELINE — full CaseEvent audit trail, event_seq_id order            │
│ (existing, kept)                                                     │
├──────────────────────────────────────────────────────────────────┤
│ EVIDENCE — Actions taken + Promises captured, each row citable        │
│ (NEW panel — see §16)                                                │
├──────────────────────────────────────────────────────────────────┤
│ PRECEDENT — comparable resolved cases (promoted out of the narrative  │
│ fold into its own card, see §18)                                      │
└──────────────────────────────────────────────────────────────────┘
```

Hierarchy rationale (matches the user's requested cascade exactly): **What is this case?** (header) → **What happened?** (timeline) → **What does Torque know?** (Why-this-case, authoritative score) → **What does the AI think?** (AI Assessment) → **Why?** (claims + citations) → **What evidence supports it?** (Evidence panel) → **Are there precedents?** (Precedent) → **What should the operator consider?** (recommended_human_attention, inside the AI card, styled as a callout not a command).

The action rail is the only element that changes based on role/state — everything above it is always visible to anyone who opens the case, which is what makes this one screen instead of two.

---

## 15. AI Experience

**Principle:** AI-assisted investigation, not chat. There is no chat input anywhere in this design, matching the existing on-demand, citation-validated pattern (`explain_case` is never called on page load or polled — only on click, exactly as today).

**AIAssessmentCard states** (all already produced by the existing API contract — no new endpoint):

- **Idle:** gold-railed card, header "AI Assessment," one sentence of framing copy ("Torque's AI reads this case's evidence and explains it. It never changes anything."), a single "Explain this case" button.
- **Loading:** replace the button area with a short skeleton (3 shimmering lines), not a spinner-only state — reduces perceived latency.
- **Generated:** render `CaseNarrative` in this fixed order: `summary` (one line, larger weight) → `current_state` claim → `root_cause_explanation` claim → `timeline` claims (compact list) → `actions_taken` claims → `guardrail_explanation` claims (only if non-empty, exactly as today) → `recommended_human_attention` (styled as a distinct callout box, plain text, never a button, never auto-actioned — reinforcing it is a suggestion, not a command) → `uncertainty` (muted, small) → `evidence_gaps` (a short bullet list, only if non-empty). Footer metadata line unchanged: `Generated {time} · {provider_id} · {prompt_version}`.
- **Disabled (503):** "AI explanations are not enabled for this deployment." — keep verbatim, it is already the right tone.
- **Not found (404) / generation failed (502) / unexpected (500):** keep the existing friendly mappings; this pattern is the model for every other error state in the product (§21).

**Every claim line carries its citation chips inline**, gold-pill styled (not blue, see §10), using the existing `citeGroup`/`citationLabel` logic. No paragraph of AI prose is ever rendered without at least the option to see what it's grounded in.

**What is deliberately not shown:** the Phase 5 `EvaluationReport` (citation existence rate, coverage, faithfulness metrics) and the Phase 7 shadow-ML prediction are backend/evaluation artifacts with **no API endpoint today** and, per their own governing documentation, no UI surface was ever intended for the shadow model. This blueprint does not invent one (see §26 if that changes later) — showing a "confidence: 87%" number the product cannot actually produce would be exactly the fabricated-functionality the brief prohibits.

---

## 16. Evidence & Citation UX

Today, `focusCitation` only resolves `case_event:<seq>` ids by scrolling to `<li data-event-seq>`. The other four citation types need a destination:

| `SourceType` | Today | Fix |
|---|---|---|
| `case_event` | ✅ Works — scrolls/flashes the timeline `<li>` | Keep as-is |
| `action` | ❌ Falls back to a toast | **Frontend-only fix.** `ACTION_EXECUTED`/`ACTION_BLOCKED` `CaseEvent` payloads already carry `action_id` (the sanctioned Action↔CaseEvent link, per `write_action_and_event`). Add `data-action-id` to those timeline `<li>`s (or, better, render them a second time inside the new Evidence panel, §14) and resolve `action:<id>` against it. **No backend change required.** |
| `promise` | ❌ Falls back to a toast | Same fix — `PROMISE_CAPTURED` payload already carries the promise reference. Anchor to the Evidence panel's Promise row. **No backend change required.** |
| `case` | ❌ Falls back to a toast | **Frontend-only fix.** Give the Case Header block `id="case-snapshot"`; a `case:<id>` citation scrolls/flashes the whole header. The header already shows every field `CaseSnapshot` cites (status, root cause, recovery score, etc.). |
| `counterparty_relationship` | ❌ Falls back to a toast, **and there is nothing on screen to point to** — `promise_keeping_rate`/`risk_score` are read by the AI evidence layer but never rendered in the authoritative UI today | **Needs one additive field on `CaseDetail`** (§26) before a real anchor can exist. Until then, keep the toast fallback honestly labeled ("Customer relationship — not shown in this view") rather than pretending to resolve it. |

This table is the concrete deliverable for "the UI should make citations intuitive": four of five evidence types are fixable with zero backend change; the fifth is named plainly rather than glossed over.

---

## 17. Timeline UX

Keep the existing mechanism entirely: `CaseEvent` list, strict `event_seq_id` order, per-type "why" line rendering (`STATUS_CHANGED` → from/to, `DIAGNOSIS_COMPLETED` → root cause + confidence, `ACTION_EXECUTED`/`ACTION_BLOCKED` → action type + outcome/block reason, `PAYMENT_RECONCILED` → recovered amount, `HUMAN_RESOLVED` → resolution + agent). This is already a strong, information-dense pattern (`renderEvent` in `torque.js`) — the only changes are visual (larger touch target on the timeline dot for mobile, `:focus-visible` ring for keyboard navigation into `data-event-seq` targets) and structural (surfacing `action_id`/`promise_id` as data attributes per §16).

---

## 18. Precedent UX

Promote from "one collapsed sub-block inside the AI narrative" to its own card in the Case View (§14), directly below Evidence. Same data (`PrecedentSection` — `found`, `cases[]`, `note`), same table shape (case id, root cause, outcome, evidence citation). Empty state (`found: false`) gets the diagonal-hatch texture treatment from §8 instead of a flat `.empty` box — visually distinguishing "no precedent exists yet" (a real, honest, occasionally-informative fact about a novel root cause) from a generic "nothing here" empty state.

---

## 19. Data Visualization Guidelines

Every visualization below maps to a field the API returns today; none is decorative.

| Data | Current treatment | Recommended treatment | Why |
|---|---|---|---|
| ₹ recovered (dashboard) | Hero number | Keep as hero number | Already correct — one confident number |
| Recovery-over-time | CSS bar chart, zero-padded to 7 bars for legibility on sparse data | Keep the mechanism; refine bar styling (rounded caps, gold-free — this is authoritative, not AI) | The zero-padding logic is a genuinely good, honest handling of sparse real data — preserve it exactly |
| Recovery by leg | Table | Keep as table | Four legs, a handful of numbers each — a table is more scannable than four small charts |
| Recovery score / probability | Plain table row | **Optional** `ConfidenceRing` (semi-circular gauge, §8) for `recovery_probability` on the Case header — one ring, one place, not a dashboard-wide pattern | Matches the reference screenshots' single strongest visual idea; overusing it would violate "don't add charts because they look impressive" |
| Incrementality (treatment/control/lift) | 4-metric grid with CI ranges | Keep — already the right shape for a causal estimate; do not chart-ify it into a graph, the numbers-with-CI format is more honest for a small-sample statistic |
| Guardrail exceptions | Table | Keep as table; consider a small horizontal proportion-bar per block reason (blocked revenue vs total at risk) only if it adds signal, not as decoration |
| AI citation existence / faithfulness | Not exposed | Do not visualize — no backend source (§26) |

---

## 20. Interaction & Microinteraction Guidelines

- **Hover:** existing row-hover (`tbody tr:hover`) and button border-brighten — keep, apply consistently to every clickable row (some routes currently only add `.clickable` inconsistently).
- **Focus:** add a visible `:focus-visible` outline (2px, `--blue` for standard controls, `--ai` gold for citation chips) — currently absent entirely.
- **Loading:** replace the literal "Loading…" with layout-matching skeleton blocks (§13); AI panel gets its own 3-line shimmer, independent of the rest of the page.
- **Citation click:** keep the existing scroll-to + 1.6s flash (`cite-hit`/`citeflash`) — it's a good, restrained microinteraction; extend it to the new anchor types (§16) and gate the flash animation behind `prefers-reduced-motion: no-preference`.
- **AI generation:** button disables during the request (existing) — keep; add the skeleton described above instead of leaving the panel blank.
- **Filtering:** existing instant re-fetch on `<select>` change — keep.
- **Case switching:** no page-level transition needed; a subtle 120ms fade on `#view` content swap is enough — avoid anything that reads as "marketing site."
- **Errors:** toast for transient action failures (existing), inline panel for full-page load failures (existing) — keep both, generalize the friendly-message mapping from the AI route to every route.
- **Success:** existing toast pattern (`"{from} → {to}"` on resolve/pause) — keep.

---

## 21. Loading / Empty / Error States

- **Loading:** skeletons matching final layout (§13), never a full-page blank.
- **Empty:** keep the existing `.empty` convention and copy style ("No open cases", "Queue is empty") — it's already terse and correct; add the hatch-texture treatment specifically where the emptiness is chart-adjacent (recovery-over-time with zero data, precedent not found).
- **Error:** generalize the AI route's human-worded mapping to every route — a 404 always says what wasn't found, a 5xx always says "try again" framing, never a raw `e.message`/stack string. Cross-tenant/unknown-merchant 404s (already returned identically by every router, per `_require_merchant`) get one shared friendly message across the whole app.

---

## 22. Accessibility

- **Keyboard navigation:** every clickable table row must also be a real focusable element (currently rows are `<tr>` with a JS click handler and no `tabindex`/`role="button"` — add both, or wrap the row content in a real `<a>`).
- **Focus states:** add `:focus-visible` styling everywhere (§20) — this is a genuine gap today, not a refinement.
- **Semantic HTML:** the shell already uses `<header>`/`<nav>`/`<main>`/`<footer>` correctly — keep; add `aria-current="page"` to the active nav link (currently class-only).
- **ARIA:** minimal — a status pill needs no `aria-live` (it's not a stream); the Live Demo feed, which *does* update on a 3s poll, should get `aria-live="polite"` so screen-reader users hear new events without a firehose of noise.
- **Contrast:** all token pairs verified in §10.3.
- **Touch targets:** 44×44px minimum on tablet/mobile (§11) — a real change from today's ~30px controls.
- **Reduced motion:** wrap `flash`/`citeflash`/toast transitions in `@media (prefers-reduced-motion: no-preference)`.
- **Color-independent status:** already satisfied — every status pill pairs color with a text label; keep this invariant for every new component (the AI gold rail is always paired with an "AI Assessment" text header, never color-only).

---

## 23. Content & Terminology Guidelines

Principles: no backend/technical vocabulary leaks into the UI; every label is the shortest phrase that stays unambiguous; AI disclaimers are one line, not a paragraph, repeated only where a claim is actually shown (not on every page).

| Current term (code/backend) | User-facing term | Reason |
|---|---|---|
| `RevenueLeakCase` | Case | Domain-internal name; "case" is what every screen already calls it |
| `leg_type` (e.g. `PAYMENT_DEGRADATION`) | "Payment failure" / "Checkout abandonment" / "Subscription failure" / "B2B receivable" (title-cased, already done via `titleize`) | Keep the existing `titleize` convention; it already strips the enum-y underscores |
| `recovery_score_breakdown.explain` | "Why this case?" | Already the exact label in use — correct, keep |
| `CaseNarrative` | "AI Assessment" | "Narrative" reads as a technical schema name; "Assessment" matches how a reviewer thinks about it |
| `NarrativeClaim` | (no user-facing label needed — rendered as plain sentences with citation chips) | Internal only |
| `evidence_gaps` | "What Torque doesn't know yet" | Plainer than "evidence gaps," keeps the honest, non-fabricating tone |
| `recommended_human_attention` | "Worth a second look" (callout heading) | Avoids sounding like an instruction/command |
| `PrecedentSection` | "Similar cases" | Plainer than "precedent," though "Precedent" is acceptable and already understood in a case-management context — either is fine; pick one and use it everywhere (this document uses "Precedent" for consistency with the case-management framing) |
| `escalation_resolution` | "Resolution" | Drop the backend prefix |
| `block_reason` (e.g. `TEMPLATE_NOT_APPROVED`) | Already `titleize`d in the exceptions table | Keep |
| `cost_efficiency_ratio` | "Cost efficiency" (already labeled, suffixed `×`) | Keep — already good |
| citation `SourceType` values (`case_event`, `counterparty_relationship`, …) | "Event #N", "Case snapshot", "Action …", "Promise …", "Customer relationship" (already implemented in `citationLabel`) | Keep verbatim — this mapping is already exactly right |

General rule for AI disclaimers: one line, present only on the AI Assessment card itself ("Torque's AI reads this case's evidence and explains it. It never changes anything.") — do not repeat a disclaimer on every claim line; the citation chips already do the trust-building work per-claim.

---

## 24. Hackathon Demo Flow

The ideal judge path, using only what exists today plus the fixes above:

1. **Land on Dashboard.** Hero ₹ recovered + flow ribbon communicate "this is a revenue-recovery system that acts and reports" in under 5 seconds.
2. **Open Live Demo, seed data** (if not already seeded) — one click, deterministic 16-case dataset across all four legs and every archetype (recovered, self-paid, B2B-partial, blocked, deferred, escalated, exhausted, open).
3. **Inject one "acts" scenario and one "restraint" scenario** — the live feed shows both a real recovery action and a real guardrail block, proving the compliance-by-construction story with actual data, not a slide.
4. **Return to Dashboard**, point at "Where Torque deliberately held back" — restraint as a feature, not a failure.
5. **Open a top-at-risk case** → Case View. Header = authoritative facts (unmistakably not AI — no gold anywhere).
6. **Click "Explain this case."** Gold-railed AI Assessment appears with a summary, claims, and citation chips.
7. **Click one citation chip.** The exact evidence row (a timeline event, an action, a promise) highlights below — proving groundedness live, not by assertion.
8. **Scroll to Precedent.** If the seeded root cause has a comparable resolved case, show it; if not, the honest textured empty state makes the same point the other way (Torque doesn't fabricate precedent).
9. **Open Agent Console**, resolve or pause the same case — the action rail is the same screen, same data, proving there's one case model, not a demo view and a real view.

Total: under two minutes, zero fabricated functionality, every step backed by a real API call already in the codebase today.

---

## 25. Implementation Boundaries

**DO NOT CHANGE:**
- Domain/business logic, state-machine semantics (`torque.state_machine`), guards (`torque.models.guards`).
- Tenant isolation (`TenantScope`).
- AI evidence rules, citation validation, AI non-authoritative behavior (`torque.ai.*`'s forbidden-import boundary and read-only posture).
- API semantics — every existing endpoint's request/response contract stays as-is. The only additive change proposed anywhere in this document is one optional field on `CaseDetail` (§26).
- Database schema — no migration is required by anything in §1–§24; §26's one optional addition is the only schema-adjacent item, and it's explicitly optional.
- Existing security controls (signature verification, tenant scoping, the `AISettings.enabled` feature flag).

**This redesign operates entirely at the presentation layer** — `src/torque/ui/static/{index.html,torque.css,torque.js}` (or a like-for-like replacement kept to the same no-build, no-framework, no-new-dependency constraint per D-122) plus, optionally, the one additive field named in §26.

---

## 26. Potential Backend/API Dependencies

Everything in §1–§25 requires **zero** backend change. The following are named separately, precisely because they are not silently assumed anywhere above:

1. **`CounterpartyRelationshipEvidence` fields on `CaseDetail` (optional).** `promise_keeping_rate` and `risk_score` are read by `torque.ai.evidence` and cited by AI narratives (`counterparty_relationship:<id>`), but `torque.reporting.metrics.case_detail` does not currently expose them, so there is nothing authoritative on the Case page for that citation type to point to (§16). *Needed for:* a fully-resolvable fifth citation type. *Optional:* yes — until added, the UI honestly labels this citation type as "not shown in this view" rather than fabricating a destination. *Does the current API already provide enough?* No — this is the one genuine gap. A minimal additive field (two nullable numbers) on the existing `CaseDetail` schema would close it with no migration (the underlying `MerchantCounterparty` columns already exist).
2. **A "does this case already have a generated explanation" hint on `top-at-risk`/`cases` list rows (optional).** Would let the Dashboard/Cases list show a small AI-available/AI-reviewed affordance without the reviewer opening every case. *Optional:* yes — nothing in this blueprint depends on it; the on-demand model (generate only when asked) is preserved either way and is the correct behavior per the AI layer's own design.
3. **Exposing `EvaluationReport` (Phase 5 faithfulness metrics) via an API (not recommended for this pass).** Named only to explicitly rule it out: no endpoint exists today, `evaluate_narrative` is test-only, and its own governing documentation gives it no target phase for a UI surface. This blueprint deliberately does not add a "faithfulness score" badge anywhere.
4. **Exposing shadow-ML predictions (`torque.ai.shadow.scoring.score_case`) via an API (explicitly out of scope).** Named only to rule it out: Phase 7 is backend/evaluation-only by its own governing task ("no new API route, no UI surface"). This blueprint respects that boundary and shows nothing derived from the shadow model.
5. **`recovery_score_breakdown` on the human-queue list response (optional).** Today the queue list returns a bare `priority` scalar; the full "why" breakdown is only available after opening the case. Inlining a one-line preview would save a click for an operator triaging the queue, but is a genuine nice-to-have, not a requirement — the merged Case View (§14) already puts the full breakdown one click away.

None of the above blocks any part of this blueprint from being implemented as specified; all five are strictly additive and independently optional.

---

## 27. UI Acceptance Criteria

- [ ] A user can go `Cases → click a row → see the AI Assessment entry point` without visiting Agent Console — the single required fix.
- [ ] `#/console/:id` and `#/cases/:id` render the same underlying case data (no field appears on one and not the other, except the action rail, which is state-gated as specified in §14).
- [ ] No AI-sourced element (narrative text, citation chip, precedent card) ever uses `--green`, `--amber`, `--red`, or `--blue` as its identifying accent — only `--ai` gold.
- [ ] No authoritative element (status pill, header field, KPI tile) ever uses `--ai` gold.
- [ ] Every `NarrativeClaim` with non-empty `citation_ids` renders at least one clickable chip; every chip either scrolls/flashes a real on-screen anchor or, for the one named unresolved type (§16, `counterparty_relationship`), shows an honest "not shown in this view" state rather than a silent no-op.
- [ ] Every table wider than the viewport scrolls within its own container on tablet width; no route causes page-level horizontal scroll at any width.
- [ ] Every interactive control has a visible `:focus-visible` state and is reachable by keyboard alone.
- [ ] Every route's error state uses a human-worded message (no raw `Error.message`/stack leakage), matching the pattern already proven in the AI route.
- [ ] No screen shows a fabricated number — every value traces to a named field in §7/§19's data-source tables.
- [ ] Mobile: no interactive control smaller than 44×44px; every multi-column table has a stacked-card equivalent below 768px.

---

## 28. Implementation Order

1. **Design tokens & base styles** — add `--ai`/`--ai-dim`, extend the radius/spacing scale, add `:focus-visible` and `prefers-reduced-motion` rules. Zero behavior change, safest first step.
2. **Merge `CaseView`** — combine `renderCaseDetail` + `renderConsolePane` into one component with a state-gated action rail; repoint `#/console/:id` as an alias. This is the highest-value, highest-risk step — do it early, alone, and verify against the existing agent-console/case-detail test coverage before layering anything else on top.
3. **AI Assessment card restyle** — move the AI panel into the merged Case View, apply the gold accent, add the loading skeleton.
4. **Evidence panel + citation anchoring** — add the new Actions/Promises evidence list with `data-action-id`/`data-promise-id`, extend `focusCitation` for the two newly-anchorable types, add the `case:<id>` header anchor.
5. **Precedent promotion** — pull the precedent block out of the narrative fold into its own card.
6. **Responsive pass** — three-tier breakpoints, table scroll containers, mobile card-stack transform, touch-target sizing.
7. **Loading/error/empty generalization** — skeletons everywhere, the AI route's error-mapping pattern generalized to every route.
8. **Accessibility pass** — keyboard-focusable rows, `aria-current`, `aria-live` on the demo feed.
9. **(Optional, only if §26 item 1 is greenlit) `CaseDetail` schema addition** — coordinate with whoever owns `torque.reporting`, since this is the one item outside pure presentation.

---

## 29. Non-Goals

- No settings/admin screen (no backend surface exists or is proposed for one).
- No chat interface anywhere — AI stays strictly "ask this specific case a specific question via one button," never a freeform conversation.
- No new visualization library, icon library, webfont, or CDN dependency — the no-build, offline, free-tier constraint (D-122) is preserved.
- No exposure of the Phase 5 evaluation metrics or the Phase 7 shadow-ML score (§26).
- No real-time push/WebSocket layer — the existing 3-second poll on the Live Demo feed is sufficient for the demo's own scale and is documented as a deliberate choice (D-124), not a gap to fix here.
- No redesign of the AI architecture, prompt system, citation model, or evaluation harness — all of it is presentation-consumed, none of it is presentation-modified.
- No multi-tenant "switch merchant" UI beyond the existing plain text field — this is a demo-scale, single-operator surface today and this document does not propose scope creep beyond the brief.

---

## Self-Critique

Checked against the brief's own 17-point list before finishing:

- **Polish vs. today:** yes — the gap closed is real (AI discoverability, one case view instead of two, a distinct AI accent, a genuine responsive system), not cosmetic.
- **Visual language vs. references:** the gold-sparse-accent, hairline-border, no-shadow, large-radius-hero-card, hatch-texture-for-absence ideas are all adopted; ticker/logo/stock-app chrome is explicitly not.
- **Still Torque, not a generic dashboard:** the flow ribbon, the leg/root-cause/guardrail vocabulary, and the "restraint as a feature" framing are all preserved and reinforced, not replaced with generic SaaS patterns.
- **AI clearly differentiated:** one exclusive color, one exclusive component, never present without a citation.
- **Authoritative vs. AI separation:** codified as an acceptance criterion (§27), not just prose.
- **30-second understanding:** the demo flow (§24) is timed and grounded in real clicks against real endpoints.
- **Information hierarchy:** explicit in §14's cascade, matching the brief's own requested order.
- **Unnecessary text removed:** §23's terminology table cuts backend vocabulary at every point it currently leaks.
- **Mobile/tablet/desktop:** three real tiers specified in §12, with an explicit table-to-card transform, not a shrink.
- **Reusable components:** §13 names one canonical `CaseView` instead of two, specifically to kill duplication.
- **Loading/error/empty:** specified per-state in §21, generalizing a pattern that already exists in one place (the AI route) to the whole app.
- **Accessibility:** §22 names concrete, currently-absent fixes (`:focus-visible`, `aria-current`, `aria-live`, touch targets, reduced motion) rather than a generic "make it accessible" line.
- **Implementable without guessing:** every field, endpoint, class name, and function name cited is verified against the uploaded source, not inferred from the architecture docs alone.
- **No backend changes silently required:** §25/§26 draw the line explicitly; only one optional, additive, no-migration field is named, and it's called out as optional in three separate places.
- **No unsupported features invented:** §26 explicitly rules out an evaluation-faithfulness badge and a shadow-ML score precisely because the temptation to add them is real and the brief warns against exactly this.
