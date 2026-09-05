# Demo Features

Every feature worth showing a judge, where to find it, what to do, what
should happen, and which subsystem is responsible. Verified against the
running application.

## Money-flow pipeline

- **Demonstrates:** the core mental model (risk → guardrails → in motion →
  recovered) as one visual, not four disconnected KPI tiles.
- **Where:** Dashboard, directly under the hero number.
- **Action:** none — read it.
- **Expect:** four connected stages: "Revenue at risk," "Held back by
  guardrails," "Still in motion," "Recovered," each an independently true
  figure (never a proportional/stacked chart implying an exact waterfall).
- **Subsystem:** `torque.reporting.metrics` (`RecoverySummary`).

## Recovery-over-time chart

- **Demonstrates:** a real analytical time series with genuine interaction,
  not decorative charting.
- **Where:** Dashboard, "Recovery over time."
- **Action:** hover over the line; click Day / Week / Month.
- **Expect:** a tooltip with the exact date and recovered amount; the chart
  re-fetches from `/reports/{merchant}/over-time?bucket=` on tab switch.
- **Subsystem:** `torque.reporting.metrics.recovery_over_time`.

## Recovery by leg

- **Demonstrates:** which of the four funnels is performing, at a glance.
- **Where:** Dashboard, "Recovery by leg."
- **Action:** none — read the proportional bars.
- **Subsystem:** `torque.reporting.metrics` (`LegBreakdown`).

## Top at-risk cases (priority feed)

- **Demonstrates:** Torque's own economic prioritization, not a fixed sort.
- **Where:** Dashboard, "Top at-risk cases."
- **Action:** click a row.
- **Expect:** navigates to the canonical Case View for that case.
- **Subsystem:** `torque.scoring.score_case` (ranks), `torque.reporting`
  (serves the ranked list).

## "Where Torque deliberately held back"

- **Demonstrates:** compliance-by-construction as a visible, provable
  feature, not a claim.
- **Where:** Dashboard, bottom table.
- **Action:** trigger a restraint scenario in Live Demo first (see below),
  then return here.
- **Expect:** a new row, or an incremented count, for the guardrail reason
  that just fired.
- **Subsystem:** `torque.compliance.*` (pure predicates), `torque.execution`
  (writes `ACTION_BLOCKED`).

## Incrementality / causal effect

- **Demonstrates:** the difference between descriptive reporting and a
  causal claim — a genuine technical differentiator for an AI/data track.
- **Where:** Dashboard, "Incrementality — estimated causal effect."
- **Action:** none — read it. Requires enough seeded treatment/control cases
  to compute (the seed provides this).
- **Expect:** treatment rate, control rate, incremental lift, and a
  SUTVA-adjusted lift (removes cross-merchant-contaminated control
  counterparties), each with a Wilson/Newcombe 95% confidence interval.
- **Subsystem:** `torque.reporting.incrementality`.

## Canonical Case View

- **Demonstrates:** one case, one page — no duplicated/competing views
  depending on entry point.
- **Where:** any case row anywhere → `#/cases/:id`; the same view is also
  reachable at `#/console/:id` from the Agent Console queue.
- **Action:** navigate in from both entry points.
- **Expect:** identical case data on both routes; the action rail
  (Resolve/Pause/Un-pause) is the only element that differs, and only
  because it's state-gated (shown only when the case's status legally
  permits that action).
- **Subsystem:** `src/torque/ui/static/torque.js` (`renderCaseView`),
  `torque.reporting.metrics.case_detail`.

## Recovery-probability gauge + "Next" banner

- **Demonstrates:** forward-looking, explainable prioritization on a single
  case.
- **Where:** Case View header.
- **Action:** none — read it.
- **Expect:** a semicircular gauge showing recovery probability; below it, a
  banner naming the exact next action Torque's scoring model plans to
  attempt (`recovery_score_breakdown.next_step_action_type`) — omitted for
  terminal cases.
- **Subsystem:** `torque.scoring.score` (`RecoveryScore.to_dict`).

## AI Assessment

- **Demonstrates:** citation-grounded, on-demand AI explanation — decision
  support, not a chatbot.
- **Where:** Case View, gold-railed card.
- **Prerequisite:** `TORQUE_AI_ENABLED=true` (off by default).
- **Action:** click "Explain this case."
- **Expect:** a narrative with a summary, current-state and root-cause
  claims (each with citation chips), a guardrail explanation if relevant,
  an optional "Worth a second look" callout, an uncertainty line, and a
  generation-metadata footer (`provider_id`, `prompt_version`).
- **Subsystem:** `torque.ai.narrative.explain_case` via `GET
  /ai/{merchant}/cases/{case_id}/explain`.

## Citation anchoring

- **Demonstrates:** every AI claim is a pointer to real, on-screen evidence
  — never an unverifiable assertion.
- **Where:** any citation chip inside a generated AI Assessment.
- **Action:** click a chip.
- **Expect:** the exact evidence element (a timeline `<li>`, or the case
  header for a `case:` citation) scrolls into view and flashes gold.
- **Subsystem:** `torque.ai.citations` (server side, stable ids);
  `focusCitation` (`torque.js`, client-side anchoring).

## Similar cases (precedent)

- **Demonstrates:** honest retrieval — a real comparable case if one exists,
  a plain "none yet" if it doesn't, never a fabricated one.
- **Where:** Case View, bottom card, populated after "Explain this case."
- **Subsystem:** `torque.ai.retrieval.find_precedent` (Postgres full-text
  search over an exact `(merchant, leg_type, root_cause_code)` filter).

## Evidence panel

- **Demonstrates:** actions taken (or blocked) as first-class evidence, not
  buried inside the timeline.
- **Where:** Case View, "Evidence."
- **Expect:** two groups when both are present — "Blocked by guardrail"
  (amber) and "Executed" (green/neutral).
- **Subsystem:** `torque.reporting.metrics.case_detail` (`ActionSummary`
  list).

## Agent Console / human queue

- **Demonstrates:** human oversight is real, not decorative — a human can
  override any automated case.
- **Where:** `#/console`.
- **Action:** click a queue row, then Resolve or Pause on the Case View that
  opens.
- **Expect:** a real state transition (`POST
  /agent-console/{merchant}/cases/{id}/resolve` or `.../pause`), a toast
  confirming the `from_status → to_status` change, a new timeline event.
- **Subsystem:** `torque.agent_console.resolve` /
  `torque.agent_console.pause_case` / `unpause_case`.

## Live Demo scenario buttons

- **Demonstrates:** the entire pipeline is real; nothing is a canned
  animation.
- **Where:** `#/demo`.
- **Action:** click any of the seven scenario buttons.
- **Expect (per button):**

  | Button | Kind | What actually runs |
  |---|---|---|
  | Payment failure | acts | `create_or_attach_case` — a real degraded-payment ingestion |
  | Checkout abandonment | acts | `create_checkout_case` — a real checkout-drop ingestion |
  | Network hard-stop (MAC 03) | restraint | Seeds a Tier-1 do-not-retry directive, asserts the real predicate refuses the retry, writes `ACTION_BLOCKED` |
  | UPI AutoPay retry cap | restraint | Seeds an exhausted NPCI retry budget, asserts the real cap predicate blocks the retry |
  | NACH representment ceiling | restraint | Seeds an exhausted NACH ceiling, asserts the real predicate blocks it |
  | Cross-leg merge | acts | The real §2.4 bidirectional merge — one counterparty, two signals, one case |
  | B2B invoice bundle | acts | The real B2B grouping rule — a second overdue invoice folds into the existing open receivable |

- **Subsystem:** `torque.demo.scenarios.inject_scenario`.

## Live activity feed

- **Demonstrates:** system activity is legible to a non-engineer in
  real time.
- **Where:** `#/demo`, right panel.
- **Expect:** updates within 3 seconds of any scenario injection (polling,
  not push — a documented, deliberate choice at this scale).
- **Subsystem:** `GET /reports/{merchant}/activity`.

## Seed / re-seed demo data

- **Demonstrates:** a reproducible, deterministic starting point — the demo
  never opens empty and never needs live traffic.
- **Where:** `#/demo`, "Seed demo data" / "Re-seed demo data."
- **Action:** click it.
- **Expect:** a toast reporting the case count (16 in the current seed);
  every dashboard/case/queue screen repopulates.
- **Subsystem:** `torque.demo.seed`, `POST /demo/seed?reset=true`.
