# Demo Flow

The ideal judge-facing walkthrough, using only screens and controls that
exist in the repository today. Target: 5–7 minutes. Every step below was
executed against a freshly seeded local instance before being written down.

## 0. Setup (before the judge arrives)

```bash
docker compose up -d db redis
uv run alembic upgrade head
uv run python -m torque
```
Open `http://127.0.0.1:8000` (redirects to `/ui/`), then **Live Demo → Seed
demo data**. This creates a deterministic 16-case dataset across all four
legs (`torque.demo.seed`).

## 1. Establish revenue at risk — Dashboard (`#/dashboard`)

Land on the dashboard. Read the hero number ("Revenue recovered by Torque")
and, directly below it, the **money-flow pipeline**: Revenue at risk → Held
back by guardrails → Still in motion → Recovered. This single visual is the
whole product thesis — say it out loud: *"Torque doesn't just show a number,
it shows the decision path that number came from."*

## 2. Show prioritization — Top at-risk cases

Scroll to "Top at-risk cases." Point out that the list is ordered by
Torque's own recovery-priority score (`(probability × amount at risk) ÷
expected next-step cost`) — not a fixed rule, not alphabetical, not "biggest
amount first." Open the top row.

## 3. Show the decision workspace — Case View (`#/cases/:id`)

Walk the case header top to bottom, which mirrors how an operator actually
reasons about it:

1. Who is this, what's at risk, what's the recovery probability (the gauge).
2. **"Next"** — the forward-looking banner naming exactly what Torque's
   scoring model plans to attempt next, and why.
3. **"Why Torque prioritized this case"** — the plain-language reasoning:
   leg, age, benchmark probability, any relationship-history adjustment,
   the customer's promise-keeping rate if known.
4. **AI Assessment** (gold-railed, right of "Why"). Click **"Explain this
   case."** *(Requires `TORQUE_AI_ENABLED=true` — see
   [`DEMO_SCRIPT.md`](DEMO_SCRIPT.md) if it says "not enabled.")* A
   citation-grounded narrative appears — summary, current-state and
   root-cause claims, each with a clickable citation chip.
5. Click one citation chip. The exact evidence it points to — a timeline
   event, or the case header itself — scrolls into view and flashes gold.
   This is the "prove it, don't assert it" moment.
6. Scroll to **Timeline** (the full audit trail) and **Evidence** (actions
   taken, split into "Blocked by guardrail" vs "Executed" if any were
   blocked).
7. Scroll to **Similar cases** — populated by the AI Assessment call above,
   or an honest "no comparable resolved case exists yet" if none exist.

## 4. Trigger a live recovery event — Live Demo (`#/demo`)

Click **"Payment failure."** A toast confirms a real case was created; the
live feed (right panel) shows the event within 3 seconds. Say: *"This just
ran the real ingestion code — signature-shaped payload, de-dup, the
self-recovery hold — not a canned animation."*

## 5. Show restraint — a guardrail scenario

Click **"Network hard-stop (MAC 03)."** The feed shows a case reaching the
playbook stage and then an `ACTION_BLOCKED` event. Navigate back to the
Dashboard — "Where Torque deliberately held back" now includes this block.
Say: *"A system that can show you what it refused to do is more credible
than one that claims to always succeed."*

## 6. Show cross-case intelligence — the merge scenario

Click **"Cross-leg merge."** This runs the real bidirectional cross-leg merge
path: the same counterparty's checkout-abandonment signal and a matching
payment-failure signal fold into **one case**, not two. This is the "one
ledger" differentiator, demonstrated live.

## 7. Show human oversight — Agent Console (`#/console`)

Open **Agent Console**. The human queue is ordered by the same economic
score as the dashboard. Open the escalated case shown there (or the one from
step 3 if it qualifies), and either **Resolve** or **Pause** it — a real
`POST /agent-console/{merchant}/cases/{id}/resolve` call, a real state
transition, a new `HUMAN_RESOLVED` timeline event.

## 8. Close with the causal story — back to Dashboard

Scroll to **Incrementality — estimated causal effect**. Point out the
explicit language distinguishing *descriptive* (what happened) from *causal*
(treatment vs. a held-out control, with a Wilson/Newcombe confidence
interval) — "not proof of causation," stated on screen, not just in a
README.

## 9. Technical close

Hand the judge [`TECHNICAL_REPORT.md`](TECHNICAL_REPORT.md) or point them at
the [root README](../../README.md)'s architecture diagrams if they want to
go deeper on any subsystem.

---

Total: under 7 minutes, every step backed by a real API call and real
database state — nothing in this flow is a scripted animation or a
hard-coded number.
