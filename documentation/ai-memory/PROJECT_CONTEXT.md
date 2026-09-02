# PROJECT CONTEXT

Slow-changing background. If you have read `CURRENT_STATE.md`, this is the "why"
and "how we work" layer beneath it. Derived documentation — the blueprint and
repo are authoritative.

---

## 1. What Torque is

**Pitch (blueprint §0):** an agent that closes the revenue-leakage loop across
all four legs of the payments funnel — degrading payments, abandoned checkouts,
failed subscriptions, and overdue B2B invoices — by diagnosing root cause,
selecting a bounded recovery playbook, executing it, and reporting exactly how
much money came back, how, and what it could not fix.

**The four legs (one shared engine, leg-specific config):**

1. **Payment degradation** — soft/hard declines, issuer/network failures on live payments.
2. **Checkout abandonment** — drop-off before or during payment.
3. **Subscription / mandate failure** — UPI AutoPay, NACH, card recurring.
4. **B2B receivables** — overdue invoices, dunning, promise-to-pay.

**Five differentiators (the build must back these, not just assert them):**

- **Root-cause diagnosis**, not templated triggers.
- **One case object, one ledger**, across all four legs.
- **Incrementality-aware measurement** — lift over a held-out control, not gross "messaged-then-paid" totals.
- **Compliance-by-construction** — quiet hours, consent logging, promise-broken de-escalation, full audit trail.
- **Resource-aware prioritization** — chase `(probability × amount) ÷ cost`, not everyone equally.

## 2. Objective of the current build

Implement **Module 1 (Core Data Model)** and then **Modules 2–13**, strictly per
`Torque_Blueprint_v7_FullSystem.md`, in **small, individually reviewable
milestones**. The near-term objective as of this writing: Module 1 / blueprint
Part A is **done** (M1–M6b); the next objective is **Module 2 (Signal
Ingestion)**.

The build is hackathon-scoped in ambition but full-fidelity in design: every
entity/field is tagged 🔧 build / 📋 design-only / 🔮 roadmap in the blueprint.
**Build constraint (locked): everything runs on free tiers.** No paid services,
no per-message spend outside our control (blueprint §0). Card Account Updater is
excluded entirely (no free tier).

## 3. Architectural philosophy (as evidenced by the code so far)

- **Schema and invariants first.** Each milestone lands tables + ORM models +
  migrations + the *pure, side-effect-free* logic that later modules will call
  (predicates, validators, state machines), plus exhaustive tests. Runtime
  wiring (HTTP, queues, workflow engine, external APIs) is deferred to the
  module that owns it.
- **Invariants are enforced structurally, not by convention.** Multi-tenancy,
  append-only history, typed contexts, playbook immutability, attribution
  sum-to-1, Action↔CaseEvent atomicity, and promise transitions are all enforced
  at flush time in `torque.models.guards` and/or by Postgres triggers/constraints
  — never left as "remember to do this". See `INVARIANTS.md`.
- **One history mechanism.** `CaseEvent` is the *only* audit/history table.
  `AuditLogEntry`, `PlaybookRun.step_history`, and `Action.merged_case_ids` are
  eliminated — never to be recreated (blueprint §2.3).
- **PII isolation.** Raw PII (`name`, `phone`, `email`) lives *only* on
  `Counterparty`. Everything else references `counterparty_id`. Erasure = null
  three fields on one row (blueprint §2.2).
- **Policy values are configuration, not literals.** Tunable windows/thresholds
  live in `torque.config.PolicyConfig`, not scattered as magic numbers.
- **Pure predicates isolated for testing.** `torque.compliance.*` is entirely
  side-effect-free; enforcement/execution that consumes it is a later module.
- **Deviations from the blueprint are explicit.** Where Torque strengthens or
  diverges from the blueprint (see `DECISIONS.md`, "intentional deviations"),
  it is called out in the code docstring and the milestone report.

## 4. Current stage

Blueprint **Part A / Module 1 complete** (all Section 3 entities implemented).
**Modules 2–13 not started.** No HTTP surface, no queue/worker, no workflow
engine, no external API calls anywhere in the codebase yet. `pyproject.toml`
notes FastAPI + uvicorn enter with Module 2.

## 5. Repository structure

```
Torque_Blueprint_v7_FullSystem.md   <- THE SPEC. Read it.
Torque_Blueprint_v4.md / _v5.md      <- historical Module-1 revision logs; rationale only, never current
README.md                            <- STALE (see CURRENT_STATE.md "known contradictions")
docker-compose.yml                   <- Postgres (host 5442) + Redis (host 6389, unused until Module 2)
alembic.ini
pyproject.toml                       <- deps; ruff (E,F,I,UP,B, line 100); pytest config
.env.example

migrations/versions/0001..0012       <- one or two migrations per milestone
migrations/env.py                    <- reads TORQUE_ALEMBIC_URL / config

src/torque/
  enums.py            <- ALL blueprint §4 enums (single reference); ALL_ENUMS tuple
  config.py           <- Settings (DB URLs, Razorpay secrets) + PolicyConfig (tunables)
  exceptions.py       <- every domain error, one module
  db/
    base.py           <- DeclarativeBase + NAMING_CONVENTION + TenantScoped marker mixin
    scoped.py         <- TenantScope: the sanctioned merchant-bound data-access facade
    session.py        <- engine, SessionLocal, session_scope(); wires guards onto SessionLocal
  models/
    __init__.py       <- importing this registers all 23 tables on Base.metadata
    mixins.py         <- TimestampMixin, uuid_pk()
    guards.py         <- before_flush invariant enforcement (load-bearing)
    <entity>.py       <- one file per table
  contexts/           <- typed leg-context Pydantic models + validate_context (used by guards)
  events/
    payloads.py       <- 10 locked CaseEvent payload schemas + validate_payload
    case_event_writer.py <- atomic(), append_case_event(), write_action_and_event(), Attribution
  playbooks/          <- StepGraph / StoppingRules models, validation, merchant-override resolution (pure)
  compliance/         <- pure predicates: mac_registry, pre_debit, retry_rails, systemic, whatsapp
  promises.py         <- PromiseToPay.status lifecycle (PROMISE_TRANSITIONS, transition_promise)
  security/
    razorpay_signature.py <- pure HMAC-SHA256 raw-body verify helper
  state_machine.py    <- RevenueLeakCase.status transitions, apply_network_directive, sync_control_group

tests/                <- Postgres-backed (skips cleanly if no server); one test file per area
  conftest.py         <- DB harness (drop/recreate schema, alembic upgrade, joined-txn session) + factories
```

## 6. Technology choices

| Concern | Choice | Notes |
|---|---|---|
| Language | Python ≥ 3.11 | blueprint Part D item 2 was "never formally chosen" — Python is the de-facto choice, Pydantic used throughout |
| ORM | SQLAlchemy 2.0, typed `Mapped[]` / `mapped_column` | |
| Migrations | Alembic | deterministic constraint/index naming via `NAMING_CONVENTION` in `db/base.py` |
| Validation | Pydantic v2 (+ pydantic-settings) | leg contexts, CaseEvent payloads, playbook models, config |
| Database | PostgreSQL 16 | native ENUM types, triggers, CHECK constraints, JSONB |
| Env / deps | `uv` (`.venv`), `pip install -e ".[dev]"` also works | run tools via `uv run <tool>` |
| Test | pytest, real Postgres (docker-compose `db`, host port 5442), `torque_test` DB | suite runs migrations then joins each test to a rolled-back outer txn |
| Lint | ruff (`E`, `F`, `I`, `UP`, `B`; line length 100) | |
| Deferred to later modules | FastAPI + uvicorn (Module 2), BullMQ/Redis (Module 2), Temporal or Postgres-polling fallback (Module 5), Meta/Resend/Fast2SMS/Razorpay API adapters (Module 5), econml/scikit-uplift (Modules 8–9) | |

## 7. Source-of-truth documents

1. **`Torque_Blueprint_v7_FullSystem.md`** (repo root) — the locked spec. Structure:
   - **Part A** — Module 1 Core Data Model: §0 vision, §1 module map, §2
     cross-cutting decisions, §3 full entity reference, §4 enums + state machine,
     §5 Outreach Coordinator spec, §6 incrementality, §7 relationship diagram,
     §8 Decisions table A–M, §9 open items.
   - **Part B** — Modules 2–13, each implementable against Part A.
   - **Part C** — corrections/additions to Module 1 surfaced while writing later modules.
   - **Part D** — 4 decisions needing human input.
   - **Part E** — 13 system-wide open items.
2. **The repository itself** — code, migrations, tests. Where docs and code
   disagree, code wins.
3. `Torque_Blueprint_v4.md` / `v5.md` — superseded. Rationale archaeology only.
4. This `documentation/ai-memory/` folder — derived, non-authoritative.

## 8. How the project evolves — the milestone loop

Every milestone follows the same loop (full detail in `CONTINUATION_PROTOCOL.md`):

```
Inspect  ->  Reconstruct Context  ->  Propose Milestone  ->  User Review
   ->  Approval (decisions locked)  ->  Implement (approved scope ONLY)
   ->  Verify  ->  Update Memory  ->  STOP
```

- The agent **proposes** a milestone as written scope, with every ambiguity
  flagged as an explicit question.
- The **maintainer locks** the scope and every open decision.
- The agent implements **only** what was approved — no scope creep, no
  "while I'm here" changes, no starting the next module.
- **The maintainer performs all Git operations.** The agent never commits.
- Verification is mandatory and reported in full before stopping.

## 9. What "done" means, per milestone type

A milestone is done when **all** of the following hold and are reported:

**Schema / model milestone (M1–M6b pattern):**
- New tables have migrations; `alembic upgrade head` clean; **migration
  up→down→up roundtrip clean** (`tests/test_zz_migrations_roundtrip.py`).
- ORM models registered in `src/torque/models/__init__.py`; typed `Mapped[]`.
- All invariants for the new entities enforced structurally (guard, trigger,
  CHECK, or unique constraint) — not just documented.
- New tests cover: schema introspection (columns/constraints/indexes/enum
  types), tenant scoping, every invariant (happy + violation paths), and any
  pure predicate/validator.
- **Full suite green** (`uv run pytest`), **`ruff check .` clean**.
- `state_machine.py` and `guards.py` diffs are intentional and shown (empty if
  the milestone was not approved to touch them).
- Blueprint deviations documented in code + `DECISIONS.md` + the milestone report.
- `documentation/ai-memory/` updated per the Memory Update Protocol.
- A recommended commit message is provided; the maintainer commits.

**Runtime / logic milestone (Module 2 onward — expected pattern):**
- Everything above, plus: the new runtime path has integration tests; external
  calls are mocked/faked (free-tier / test-tier only); new policy values live in
  `PolicyConfig`; no invariant from earlier milestones is weakened.
