# Demo Script

A presenter script for the flow in [`DEMO_FLOW.md`](DEMO_FLOW.md). Each beat
lists what to click, what to say, and what the judge should notice.

**Before you start:** run `docker compose up -d db redis`, `uv run alembic
upgrade head`, `uv run python -m torque`. If you want the AI Assessment to
work, start with `TORQUE_AI_ENABLED=true uv run python -m torque` instead —
without it, "Explain this case" will honestly say "AI explanations are not
enabled for this deployment," which is also a fine thing to show (see beat 3).
Open the app and go to **Live Demo → Seed demo data** once.

---

### Beat 1 — Dashboard

**Click:** nothing yet, land on `#/dashboard`.

**Say:** *"Torque is an autonomous revenue-recovery system. This number is
money it actually recovered — not messages sent, not retries attempted.
Right below it is the whole product in one picture: revenue at risk, what we
deliberately held back, what's still being worked, and what came back."*

**Notice:** the four-stage pipeline. Point at "Held back by guardrails" —
*"that's not a bug, that's the product refusing to do something it isn't
allowed to do."*

---

### Beat 2 — Prioritization

**Click:** the top row under "Top at-risk cases."

**Say:** *"This list isn't sorted by amount, and it isn't sorted by age.
It's sorted by an explicit formula — probability of recovery times amount at
risk, divided by what the next action would cost. A ₹50,000 case that's
unlikely to ever pay loses to a ₹5,000 case that's fresh and cheap to chase.
That's the whole prioritization story, and it's the same score both the
automation and the human queue use."*

**Notice:** the recovery-probability gauge and "Next" banner in the case
header that opens.

---

### Beat 3 — AI Assessment

**Click:** "Explain this case."

**Say (if AI is enabled):** *"This is on-demand — it never runs
automatically, never on page load. It reads the same evidence you can see
on this page and explains it. Every claim carries a citation."* **Click one
chip.** *"Watch — it scrolls to and highlights the exact evidence it's
citing. If a claim can't be traced to real evidence, the whole narrative is
rejected server-side before it ever reaches this screen."*

**Say (if AI is disabled):** *"This deployment has the AI layer off by
default — it's opt-in, which is itself part of the story: nothing about
Torque's core decisioning depends on an LLM being available."*

**Notice:** the gold accent is used *only* for AI content — nowhere else on
the page.

---

### Beat 4 — A live event

**Click:** Live Demo → "Payment failure."

**Say:** *"That just ran the real ingestion pipeline — signature-shaped
event, de-duplication, a short self-recovery hold — the same code path a
real Razorpay webhook would hit."*

**Notice:** the feed updates within a few seconds.

---

### Beat 5 — Restraint

**Click:** Live Demo → "Network hard-stop (MAC 03)."

**Say:** *"The card network sent a do-not-retry instruction. Watch what
Torque does with it — it refuses the retry and logs exactly why."* Navigate
to the dashboard. *"That block just showed up here, in 'Where Torque
deliberately held back.' A system that can prove what it refused to do is
more trustworthy than one that only shows successes."*

---

### Beat 6 — One ledger

**Click:** Live Demo → "Cross-leg merge."

**Say:** *"This customer just abandoned a checkout, then their retry for the
same order failed. Most tools would open two tickets. Torque opens one case
— one ledger, one history — because it's the same underlying loss."*

---

### Beat 7 — Human oversight

**Click:** Agent Console → any escalated row → Resolve (or Pause).

**Say:** *"Automation has a ceiling. When a case exhausts it, or the
diagnosis isn't confident, or a promise to pay gets broken, it lands here —
ordered by the same economic score — and a human has the final say. This
isn't a separate app; it's the same case, same data, one click away."*

---

### Beat 8 — The causal claim

**Click:** back to Dashboard, scroll to "Incrementality."

**Say:** *"Anyone can report a big recovered-revenue number. We go further:
this section estimates the *incremental* lift — treatment cohort versus a
held-out control — with a real confidence interval, and we say outright
that it's not proof of causation. We'd rather be precise than impressive."*

---

### Close

**Say:** *"Every number on every screen you just saw came from a real
database call, computed by the backend — the frontend never invents a
metric. Happy to open the code for any subsystem you want to look at."*

Hand over [`TECHNICAL_REPORT.md`](TECHNICAL_REPORT.md) if they want the
written version.
