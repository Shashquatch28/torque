"""Module 2 — Signal Ingestion, the post-`Event` half (Milestone 7b, Leg 1).

M7a delivered the HTTP front door: verified, deduplicated `Event` rows. M7b
turns a verified `payment.failed` `Event` into a `PAYMENT_DEGRADATION`
`RevenueLeakCase`, with the two ingestion-logic gates the blueprint puts in
between:

* `buffer` — the §2.3 same-session self-recovery buffer (a Celery delayed job;
  a later `payment.captured` for the same payment ⇒ no case).
* `dedup` — the §2.4 cross-leg Merge (an open `CHECKOUT_ABANDONMENT` case for
  the same cart ⇒ superseded into the new payment case).

Scope is **Leg 1 only**. `subscription.charged.failed`, `invoice.overdue` /
B2B bundling, `checkout.abandoned` ingestion, systemic detection, and the
reverse Merge direction are NOT here — see `documentation/ai-memory/DEFERRED.md`.
"""
