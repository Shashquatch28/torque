# Architecture — Deep Dive

Companion to the [root README](../../README.md#system-architecture)'s
top-level diagram. This document goes one level deeper on the two areas most
likely to draw follow-up questions: the frontend's architectural decision,
and the guardrail engine's decision procedure.

## Process topology

```mermaid
flowchart LR
    subgraph Host/Container
        PG[(PostgreSQL 16\nsingle durable source of truth)]
        RD[(Redis\nCelery broker transport ONLY\nno result backend, no durable state)]
        API[api process\npython -m torque\nFastAPI + static UI, one port]
        WRK[worker process\nexecutes every torque.* Celery task]
        BEAT[beat process\nrepeatable-timer trigger only:\nsystemic 60s, exec poll 10s/60s,\ndaily rescore]
    end
    API -->|reads/writes| PG
    WRK -->|reads/writes| PG
    API -->|enqueues tasks| RD
    RD -->|delivers tasks| WRK
    BEAT -->|fires on schedule| RD
    Browser[Browser\nstatic HTML/CSS/JS] -->|fetch, same origin| API
```

No task ever holds durable state in Redis — `scheduled_job` (Postgres) is the
one durable execution timer table; `beat` only fires triggers against it.

## Request lifecycle (one HTTP call)

```mermaid
sequenceDiagram
    participant Client
    participant Router as FastAPI router
    participant Guard as _require_merchant
    participant Domain as domain module
    participant DB as Postgres (TenantScope)

    Client->>Router: HTTP request
    Router->>Guard: verify merchant_id exists
    alt unknown/cross-tenant merchant
        Guard-->>Client: 404 (identical message either way — never a leak)
    else known
        Router->>Domain: call the one domain function for this route
        Domain->>DB: TenantScope-scoped query/write
        DB-->>Domain: rows
        Domain-->>Router: typed result / domain exception
        Router-->>Client: response_model-validated JSON, or a mapped HTTP error
    end
```

Every router (`reporting.py`, `agent_console.py`, `ai.py`, `demo.py`,
`webhooks.py`, `checkout_injection.py`) follows this exact shape — one
`_require_merchant` guard, one call into a domain module, no business logic
in the router itself.

## Guardrail decision procedure

```mermaid
flowchart TD
    START[Action due] --> HARD{Do-not-retry\nnetwork directive?}
    HARD -->|yes| BLOCK1[BLOCK: hard stop]
    HARD -->|no| BUDGET{Retry budget\nexhausted?\ncard / UPI / NACH}
    BUDGET -->|yes| BLOCK2[BLOCK: budget exceeded]
    BUDGET -->|no| PREDEBIT{RBI pre-debit\nnotice missing?}
    PREDEBIT -->|yes, fixable| HEAL[SELF-HEAL: send notice,\nreschedule +24h]
    PREDEBIT -->|no| OUTAGE{Systemic\noutage active?}
    OUTAGE -->|yes| DEFER1[DEFER: held for outage]
    OUTAGE -->|no| QUIET{Cross-leg 4h\nquiet period active?}
    QUIET -->|yes| DEFER2[DEFER: quiet period]
    QUIET -->|no| CONSENT{WhatsApp consent +\napproved template?}
    CONSENT -->|no| BLOCK3[BLOCK: consent/template]
    CONSENT -->|yes| LIVECHAT{Live conversation\nopen?}
    LIVECHAT -->|yes| DEFER3[DEFER: suspend, route to human]
    LIVECHAT -->|no| HOURS{Outside allowed\ncontact hours?}
    HOURS -->|yes| DEFER4[DEFER: quiet hours]
    HOURS -->|no| ALLOW[ALLOW: execute]
```

First-failure-wins, evaluated in this fixed order by
`torque.compliance.*`'s pure predicate functions, consulted through one
callable interface the execution layer calls before every action. Every
`BLOCK` is written as an `ACTION_BLOCKED` `CaseEvent` with its reason — this
is the data source for the dashboard's "Where Torque deliberately held back"
panel; nothing is computed retroactively.

## Frontend: why vanilla JS, and what that costs

The frontend is a hand-written SPA — `index.html` + `torque.css` +
`torque.js`, hash-routed, no build step, served by the same FastAPI process
on the same port as the API (`torque.api.ui`). This was evaluated twice
during the project (once for the initial UI/UX overhaul, once explicitly
re-asked whether a framework migration was warranted) and kept both times.
The reasoning:

**What a framework would have bought:** component-file organization,
built-in reactivity, a component ecosystem for charts/animation.

**What it would have cost:** a build step (npm/bundler) in a project whose
explicit constraint is "one command, offline, free-tier, no Node" (see the
root README's stack line); a rewrite of every existing render function under
time pressure, with real risk of a partially-migrated, partially-working
app; and — critically — none of the actual reported problems (generic
visual hierarchy, weak product storytelling, a missing money-flow narrative)
were caused by the technology. They were caused by *layout and composition*
decisions, which are exactly as fixable in vanilla JS/inline SVG as in JSX.

**What vanilla JS cannot do that a framework would help with**, honestly:
fine-grained reactive state diffing (this app instead does targeted DOM
patches — e.g. the dashboard's chart-bucket switch replaces one `<div>`, not
the whole page), and a component-file structure for very large component
trees (this app instead uses one file with named render functions per
component — `loopPipeline()`, `feedRow()`, `evidencePanel()`, `confidenceRing()`,
etc. — which stays legible at this app's actual size, five screens).

**The concrete guardrail against regressing on this decision silently:**
`tests/test_module10_ui.py` and `tests/test_module9b_ui.py` assert, by
scanning the shipped source, that specific API paths, specific DOM
structures, and specific escaping/error-handling patterns exist — a future
change (framework migration or otherwise) that breaks these contracts fails
the build, not just a visual review.

## Frontend component inventory

| Function (in `torque.js`) | Renders |
|---|---|
| `renderDashboard` | Hero, money-flow pipeline, leg bars, interactive chart, incrementality card, priority feed, exceptions table |
| `renderCaseView` | The canonical case screen — header, gauge, next-step banner, reasoning signals, AI Assessment, action rail, timeline, evidence, precedent |
| `renderCases` | Filterable/paginated case list |
| `renderConsole` | Human-queue priority feed |
| `renderDemo` | Scenario buttons + live activity feed |
| `loopPipeline`, `legBars`, `areaChartSvg`, `confidenceRing`, `feedRow`, `evidencePanel`, `renderNarrative`, `renderPrecedent` | Shared presentational components used across the screens above |
| `explainCase`, `focusCitation`, `citeGroup` | The AI-assessment fetch/render/anchor pipeline |

## Data flow: dashboard load

```mermaid
sequenceDiagram
    participant JS as torque.js
    participant API as /reports/{m}/*
    participant DB as Postgres

    JS->>API: summary, by-intervention, over-time, top-at-risk, exceptions, incrementality (parallel)
    API->>DB: six independent read queries, TenantScope-scoped
    DB-->>API: rows
    API-->>JS: six typed JSON responses
    JS->>JS: render — zero client-side aggregation of any of these values
```
