# AI Features Blueprint — Next AI/ML Capabilities for Torque

**Status of this document:** RESEARCH + BLUEPRINT ONLY. No source code, migrations, dependencies, or existing decisions were modified while producing this document. This is a new, independent research pass that sits *on top of* the existing `AI_BLUEPRINT.md` (Phases 0–8, all `COMPLETE` except Phase 9 "Demo polish"). It does not re-open, contradict, or silently change anything in `AI_BLUEPRINT.md`, `DECISIONS.md`, or `INVARIANTS.md`. Every existing LOCKED decision referenced below is quoted, not reinterpreted.

**Label legend** (used throughout, per the governing task instructions):
`LOCKED` = already established elsewhere in the repo, not being reconsidered here · `RECOMMENDED` = research-backed, awaiting implementation · `EXPERIMENTAL` = worth building but evidence/data is currently insufficient for anything beyond a labeled demo · `DEFERRED` = useful, out of hackathon scope · `REJECTED` = investigated and deliberately excluded · `NEEDS HUMAN DECISION` = cannot responsibly be decided by this document alone.

A note on scoring direction used throughout this document: every 1–10 criterion, **including "Effort,"** is scored so that **higher = better**. For Effort specifically, 10 = trivial/near-zero work, 1 = very large effort. This avoids the usual ambiguity where "high effort score" could be misread as "hard."

---

## Executive answer (read this first)

> **Given Torque's actual architecture, actual data, hackathon constraints, and existing AI capabilities, what are the 3 highest-ROI AI/ML capabilities we can realistically build next?**

1. **Feature C — Time-to-Recovery Survival Curves** (Kaplan-Meier, uses *all* 16 cases via censoring, zero new dependencies, ~half a day)
2. **Feature A — Recovery Likelihood & Explainable Risk Panel** (finishes wiring the already-built-but-unwired Phase 7 shadow model + adds a precedent-based nearest-neighbor baseline, ~1 day)
3. **Feature B — Statistical Systemic-Spike Anomaly Detector** (replaces the "unvalidated placeholder" 5× multiplier with a real, explainable statistical test, ~1 day)

All three are read-only, additive, independently implementable in any combination, require no new paid infrastructure, and none of them ask a learned model to make a Torque decision. None of them touch `state_machine.py`, guardrails, playbook selection, retry limits, or accounting. Full detail below.

---

## 1. What Torque already is (baseline, verified against source)

Torque is a deterministic revenue-leak recovery engine for Indian payment merchants, covering four "legs" sharing one case object (`RevenueLeakCase`): **payment degradation**, **checkout abandonment**, **subscription/mandate failure**, and **B2B receivables**. The pipeline is ingestion → diagnosis → policy/playbook selection → guardrail-checked execution → reconciliation/attribution → recovery scoring → reporting, plus a causal (treatment/control) measurement layer. Modules 1–12a are `IMPLEMENTED`; Module 13 (Demo Script) and AI Phase 9 (Demo polish) are the only incomplete items in the whole repository. 1436 tests pass at the current commit (`20b6a57`, "Phase 8 — Hardening"), 210 of them AI-specific.

**The governing rule, quoted verbatim and treated as `LOCKED` for this entire document:**

> "Deterministic Torque decides. AI reads and explains. AI does not mutate Torque business state." — `src/torque/ai/__init__.py`, restated in `AI_BLUEPRINT.md` §1/§3.

### 1.1 Already implemented (AI layer, Phases 0–8)

| Capability | Where | Maturity |
|---|---|---|
| Read-only evidence interface | `src/torque/ai/evidence.py` — `gather_case_evidence()`, typed/redacted DTOs, PII-excluded (never reads `Counterparty`, never reads `Action.content_sent`) | Complete, tested |
| Citation model | `src/torque/ai/citations.py` — `reference_id = f"{source_type}:{source_id}"`, pure resolution, never fabricates | Complete, tested |
| Deterministic precedent retrieval | `src/torque/ai/retrieval.py` — `find_precedent()`: exact metadata filter (merchant, leg_type, root_cause_code, terminal-only) → Postgres full-text search as secondary ranking → recency tiebreak. No vector DB (explicit decision D-141, justified by corpus size) | Complete, tested |
| LLM case explanation | `src/torque/ai/narrative.py`, `prompts.py`, `providers/` — full pipeline wired to an API route and a UI button | Complete, but **only `MockProvider` exists — no real LLM is integrated anywhere in this codebase** |
| Faithfulness/evaluation machinery | `src/torque/ai/evaluation.py` — citation existence/coverage, lexical-overlap "unsupported claim" proxy (explicitly *not* semantic entailment), retrieval precision@K | Complete, tested against a 6-case hand-labeled fixture set |
| Agent Console integration | `src/torque/api/ai.py` (`GET /ai/{merchant_id}/cases/{case_id}/explain`) + `torque.js` "Explain this case" button | Complete, gated by `AISettings.enabled` (default `False`) |
| Observational shadow ML | `src/torque/ai/shadow/{labels,schemas,features,model,evaluation,training,scoring}.py` | **Fully implemented and tested as a library. Zero API route, zero UI surface, zero persistence — by explicit Phase 7 scope decision (D-149).** This is the single largest "already built, not yet visible" opportunity in the codebase. |
| Security/boundary enforcement | `tests/test_ai_boundary.py` — AST-based static import scanner (forbids `torque.state_machine`, `torque.policy`, `torque.execution`, `torque.diagnosis`, `torque.scoring`, `torque.coordination`, `torque.agent_console`, `torque.ingestion`, `torque.events`, `torque.reconciliation`, `torque.promises`, `torque.api` anywhere under `src/torque/ai/`) + a substring write-scanner (`.add(`, `.delete(`, `.commit(`, raw SQL mutation keywords) | Complete, runs as part of the normal test suite, recursively covers `shadow/` automatically |

**The shadow ML classifier, precisely** (Phase 7): `sklearn.linear_model.LogisticRegression` (`max_iter=1000, random_state=0`, fully deterministic) over a `DictVectorizer`-encoded 9-feature dict (5 numeric + 4 categorical, one-hot expanded). Target: `y = 1 if status ∈ {RECOVERED, CANCELLED} else 0`. Split: **temporal**, not random (sorted by `as_of` = the case's own `DIAGNOSIS_COMPLETED` timestamp; earliest → train, most recent → test). Every output DTO carries a non-optional `disclaimer` field (fixed `SHADOW_DISCLAIMER` string) and `n_training_cases` — a caller cannot construct one without both. `MIN_CASES_FOR_MEANINGFUL_EVALUATION = 30` is already coded as the "don't trust this yet" floor.

### 1.2 Planned but not implemented

- A real, network-backed LLM provider (`D-AI-03`, marked `NEEDS HUMAN DECISION` — API budget/key procurement).
- LLM-as-judge / semantic-entailment faithfulness scoring (`D-144`, "deliberately deferred, no target phase").
- Any API/UI surface for the shadow model or its `EvaluationReport` (`D-149`).
- The blueprint's own named future model — XGBoost + SHAP + T/X-learner uplift meta-learners — explicitly gated on **500+ resolved cases** (Decision F, §8.4).
- Real channel adapters (WhatsApp/email/SMS/retry APIs are stubs — `run_action` performs no real I/O).
- Module 13 (Demo Script) and AI Phase 9 (Demo polish).

### 1.3 Architectural boundaries that MUST NOT be violated (verified against source, not assumed)

These are enforced in code today, and every feature proposed in this document is designed to sit entirely on the "reads" side of each line:

1. **Retry-limit / compliance guardrails** (`src/torque/execution/guardrails.py`) — network hard-stop tiers, UPI AutoPay's NPCI-mandated 3-attempt cap, NACH representment ceiling, card-network dual-window budget, RBI 24h pre-debit gap. `INV-46`: "The UPI AutoPay hard cap is never exceeded."
2. **Playbook legality/eligibility** (`src/torque/policy/engine.py`, `selection.py`) — state gating, merchant `enabled` flag, version pinning (`INV-03`).
3. **Escalation ceiling / stopping rules** (`src/torque/execution/runner.py`) — `max_attempts`, `max_duration_days`, validated at playbook-save time.
4. **WhatsApp consent + template approval gates** (`outreach_coordinator.whatsapp_gate`) — fail-closed, Meta-owned vocabulary.
5. **Systemic hold** (`case_under_systemic_hold`) — once flagged, blocks all retry/contact actions regardless of any score.
6. **State transitions** (`torque.state_machine.transition_case`) — every status change centrally validated.
7. **Tenant isolation** (`TenantScope`, used in every AI read path today) — "not found" and "wrong tenant" collapse to the same exception everywhere, to avoid a cross-tenant existence oracle.
8. **Exactly-once execution** (`ScheduledJob` claim via `FOR UPDATE SKIP LOCKED`).
9. **Credit-weight / attribution arithmetic** (`ActionCase`, Σ`credit_weight == Decimal("1.00000")` exactly) — `INV-12`.

Every feature below is designed to be structurally incapable of touching any of these nine, the same way Phases 1–8 are today (enforced, where applicable, by the same static import-boundary test).

### 1.4 Extension seams the codebase itself already names

The most useful finding from source inspection: the deterministic core is not opaque to ML — several of its own docstrings **already name themselves as the intended point where a learned model would plug in**, without the core needing to change:

- `src/torque/scoring/__init__.py`: *"The roadmap upgrade (XGBoost + SHAP + T/X-learner uplift, once 500+ resolved cases exist — Decision F / §8.4) is deliberately not built here."* `benchmarks.cold_start_probability()` is the exact call site (`score.py:226-231`); `amount_bucket()` is a pre-wired, currently-inert feature waiting for a model to use it.
- `src/torque/coordination/outreach_coordinator.priority()` is "the single seam" (`D-098`/`D-113`) that every consumer of case priority (human queue order, merge-group primary selection) reads through — a learned score could replace `compute_recovery_score()`'s output here without any caller changing.
- `diagnosis_confidence_threshold` (default 0.65) is explicitly commented as an "uncalibrated launch default" (Decision E).
- `torque.policy.selection.select_playbook_id()` is currently a strict 1-to-1 lookup — eligibility (root-cause validity, merchant enable/disable, version pinning) is already cleanly separated from "which playbook," so it could in principle widen to a candidate-set + ranker without restructuring.
- `systemic_threshold_breached()`'s fixed 5× multiplier and floors are explicitly commented in `config.py` as "U-04 placeholders (no blueprint figure) — configurable, not empirically validated."

None of these seams are touched by the three recommended features below in a way that changes their behavior — they are named here because they show the architecture was already built with future learned components in mind, which is exactly why the three recommendations below fit without rework.

---

## 2. What data Torque actually has (verified against seed code + migrations, not documentation claims)

This is the single most important constraint on this entire exercise, so it is stated plainly: **the real, current dataset is tiny.**

### 2.1 Today's dataset (exact, from `src/torque/demo/seed.py`)

- **2 merchants** (`acc_demo`, plus `acc_demo_up` — a contamination fixture for the SUTVA adjustment demo).
- **16 cases** in `acc_demo` (+2 more in `acc_demo_up`), fully deterministic, hand-authored, no `random` module anywhere in the seed path, fixed clock (`2026-09-15T12:00:00Z`).
- **7 terminal cases**: 5 `RECOVERED`, 1 `CANCELLED`, 1 `EXHAUSTED`.
- **6 ML-eligible (labeled) cases** — the `CANCELLED` case is excluded because it self-recovered before diagnosis ran, so no feature vector exists for it.
- **Measured shadow-model split** (already computed in the codebase, confirmed in `AI_BLUEPRINT.md`): `n_train=5, n_test=1`, class distribution `{recovered: 5, not_recovered: 1}`.
- **16 distinct counterparties**, all in a single ~5-day window (`opened_ago_hours` 3–120h before the fixed demo clock) — longitudinal in shape, but one narrow window, not months of history.
- **Treatment/control**: 3 of 16 counterparties (`in_control_cohort=True`) vs 13 treatment — a fixed ~19%/81% split, hardcoded, not randomized at runtime.
- **Actions per case**: essentially 1 primary action per case in almost every archetype — shallow, not a multi-step history. No `PlaybookRun` rows exist in seed data at all.
- **No factory_boy/Faker anywhere in the repo.** No persisted database dump exists. Every number above comes from reading deterministic seed code, cross-confirmed by the project's own `DECISIONS.md` (D-146) and `AI_BLUEPRINT.md`.
- The 7 "one-click scenario" injectors (`src/torque/demo/scenarios.py`) add *open* or *blocked* cases for live-clicking during a demo — **none of them ever produce a new terminal case**, so they add ingestion/compliance volume but zero additional ML-labeled examples.

### 2.2 A modestly larger hackathon-generated dataset

Nothing prevents writing a **parameterized synthetic generator** (extending, not replacing, `seed_demo()`) that produces e.g. 100–500 cases across more merchants/counterparties, with randomized-but-reproducible (seeded RNG) timestamps, outcomes, and root causes drawn from realistic distributions. This is explicitly addressed in §7 (Synthetic Data Policy) below and is a live design element of Feature A. It changes what evaluation *can be shown live in a demo*, but must never be presented as evidence the model works on real merchant behavior.

### 2.3 A future production-scale dataset

At 500+ resolved cases (the blueprint's own existing gate, Decision F, `LOCKED`, not reopened here), the existing recommendation to revisit XGBoost + SHAP + T/X-learner uplift becomes appropriate to re-evaluate — see §9.14 (LR vs. XGBoost) below, which reaffirms rather than silently changes that gate. At thousands of cases per merchant, embeddings, sequence models, and individual-level uplift/CATE modeling would all become newly defensible — none of them are defensible today (§5).

### 2.4 Schema facts that matter for feasibility

- `CaseEvent` is a single globally-ordered append-only table (`event_seq_id` BIGINT PK), immutable by DB trigger — a clean, leakage-safe event log already exists.
- `MerchantCounterparty.in_control_cohort` is a genuine, once-assigned, immutable treatment/control flag — a real (if tiny) causal-inference substrate already exists, with a working Wilson-score-CI / Newcombe-hybrid-CI reporting layer (`src/torque/reporting/incrementality.py`) already computing average treatment effect on demand.
- `RevenueLeakCase.opened_at`/`closed_at` exist on every case (terminal or not) — this is what makes survival analysis (Feature C) able to use all 16 cases, not just the 6 labeled ones.
- The shadow feature schema already excludes every post-outcome field by construction (`ShadowFeatureVector` structurally cannot represent `recovery_type`, `recovered_amount`, `recovery_score`, `escalation_resolution`, `closed_at`, or `status`) — the leakage discipline this document must follow is already demonstrated in the existing code (e.g. the B2B `amount_at_risk` leakage fix, D-148, and the `network_directive_tier` as-of-cutoff reconstruction).

---

## 3. Data sufficiency gates (research-derived, not the placeholder thresholds from the task prompt)

Rather than reuse an arbitrary <100/100–499/500+ ladder, the following thresholds are derived from the specific statistics literature relevant to each technique family, and are used consistently in every feature's Evaluation section below.

| Technique | Rule of thumb | Source | Applied floor |
|---|---|---|---|
| Multivariate logistic regression | ≥10 "events per variable" (EPV); newer work says sample-size-for-calibration formulas typically demand *more*, not fewer, cases than the EPV=10 rule | Peduzzi et al. 1996, *J Clin Epidemiol* 49(12):1373-9; van Smeden et al. 2019, *Stat Methods Med Res* | With ~9 raw features (~15-20 one-hot columns after `DictVectorizer` expansion), a defensible floor is **~150-200 cases**, not 30 |
| "Illustrative pipeline, not evidence of skill" (already coded) | `MIN_CASES_FOR_MEANINGFUL_EVALUATION = 30` | `src/torque/ai/shadow/training.py` (existing, `LOCKED`) | Below 30 → explicitly labeled non-evidentiary (already enforced in code) |
| Non-parametric survival curve (Kaplan-Meier) per stratum | No hard minimum for an unbiased estimate, but a stratum needs a handful of *events* (not just cases) for the curve to carry any information; standard applied guidance suggests **≥10 events per stratum** for a stable-looking curve | General survival-analysis methodology (Kaplan & Meier 1958 as the base estimator; practical guidance is consistent across clinical/actuarial survival texts) | Below 10 events per leg → pool across legs rather than showing a per-leg curve |
| Uplift / CATE (individual treatment effect) | Needs enough *per-covariate-stratum* sample in **both** arms to estimate heterogeneity, typically hundreds to thousands, far beyond what's needed for a pooled ATE | Yao et al., "A unified survey of treatment effect heterogeneity modeling and uplift modeling," arXiv:2007.12769 | Current 13 treatment / 3 control is adequate for a pooled ATE (already built) and nowhere near adequate for CATE — see §9.10 |
| Isotonic probability calibration | Needs a held-out calibration set large enough that the non-parametric monotone fit doesn't just memorize noise; explicitly flagged as prone to overfitting on small calibration sets | Kull et al. and related work on classifier calibration for small datasets, arXiv:2002.10199 | Not attempted below ~100 held-out cases (§9.13) |
| Entity embeddings for categorical variables | The originating paper's own benefit case is "high cardinality" categories with enough examples per category to learn a meaningful vector | Guo & Berkhahn, "Entity Embeddings of Categorical Variables," arXiv:1604.06737 | Torque has 2 merchants and ~18 counterparties — cardinality is the *opposite* problem; rejected outright (§9.6) |

---

## 4. Synthetic data policy

**RECOMMENDED**, scoped narrowly:

- Synthetic data may be used to make a **demo** more visually complete (e.g., a survival curve with more steps, an anomaly detector with a realistic spike to click), but every number computed on synthetic data **must be labeled "synthetic demonstration"** in the UI and evaluation report, distinct from any number computed on the 16 real seeded cases.
- Synthetic data must never be mixed into the same evaluation set as real cases, and must never be used to report a metric (accuracy, AUC, coverage) that is then presented as if it reflects real merchant behavior.
- Where a feature's real-data evaluation is honestly weak (Feature A, n=6), the correct response is to **say so explicitly in the UI** (the existing `SHADOW_DISCLAIMER` pattern), not to backfill with synthetic cases to make the number look better.
- Assumptions introduced by any synthetic generator (e.g., "root causes are drawn i.i.d. from a fixed distribution," "no covariate drift over time") must be stated next to any synthetic result shown to a judge.

---

## 5. Candidates considered (research pass — 13 named, narrowed to 5 serious, then 3 final)

Per the task's requirement to research broadly rather than anchor on prior discussion, all eight previously-discussed ideas (recovery prediction, anomaly detection, merchant embeddings, action-outcome prediction, temporal/sequence models, knowledge graphs, contextual bandits, reinforcement learning) were treated as hypotheses, not conclusions, alongside additional candidates surfaced during literature research.

| # | Candidate | Verdict | One-line reason |
|---|---|---|---|
| 1 | Recovery-likelihood shadow-model surfacing (finish wiring Phase 7) | **SELECTED → Feature A** | Already built, just unwired; real supervised learning; explainable |
| 2 | Precedent-based nearest-neighbor recovery rate | **Folded into Feature A** | Reuses existing retrieval; more defensible than LR at n=6 |
| 3 | Statistical systemic-spike anomaly detection | **SELECTED → Feature B** | Decoupled from the n=6 case-outcome problem; genuinely different ML paradigm (unsupervised) |
| 4 | Time-to-recovery survival analysis (Kaplan-Meier) | **SELECTED → Feature C** | Uses all 16 cases via censoring; cheapest to build; zero new dependencies |
| 5 | Conformal-prediction uncertainty wrapper | **Folded into Feature A** (as an evaluation-section technique, not a standalone feature) | Valid at small n per literature, but not a feature on its own |
| 6 | LLM-as-judge / NLI-based faithfulness upgrade | **DEFERRED** | Real substance, but low demo impact and a new heavy dependency; scores MEDIUM below |
| 7 | Real LLM provider integration (Anthropic API) | **REJECTED for this program / NEEDS HUMAN DECISION** | High demo "wow," but near-zero *new* AI/ML substance (it's a swap of `MockProvider`), needs a paid API key/budget decision (already flagged `D-AI-03`), and risks the `LOCKED` free-tier constraint |
| 8 | Uplift / CATE / heterogeneous treatment effects | **REJECTED** | 13 treatment / 3 control is nowhere near enough for individual-level effects (§9.10) |
| 9 | Merchant/counterparty behavioral embeddings | **REJECTED** | 2 merchants, ~18 counterparties — cardinality is inverted from what embeddings need (§9.6) |
| 10 | Contextual bandits / next-best-action optimization | **REJECTED (hackathon) / DEFERRED (research)** | No repeated-trial-per-arm data exists (≈1 action per case); bandits handle cold start for *new arms*, not zero historical pulls at all (§9.8) |
| 11 | Learning-to-rank playbook selection (widen candidate set + ranker) | **REJECTED (hackathon) / DEFERRED (research)** | Today exactly one playbook is eligible per (leg, root cause) — there is no historical *comparative choice* signal to rank against (§9.9) |
| 12 | Graph-based merchant-counterparty relationship ML | **REJECTED** | 2 merchants / ~18 counterparties is not a graph, it's a short list; no meaningful topology exists |
| 13 | Weak-supervision label expansion for the shadow classifier | **REJECTED as standalone** | Risks contaminating the tiny real evaluation set with proxy labels; folded into Feature A's synthetic-data policy instead, kept clearly separate from real evaluation |

### 5.1 Scoring framework

Weights per the governing task instructions: Business value 20%, AI/ML substance 20%, Demo impact 20%, Effort 15%, Data feasibility 10%, Evaluation feasibility 5%, Explainability 5%, Infra cost 5%. All scores 1–10, higher = better (see the Effort convention note at the top of this document).

| Candidate | Business | AI substance | Demo | Effort | Data | Eval | Explain | Infra | **Weighted** | Priority |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| **A. Recovery Likelihood Panel** | 9 | 8 | 9 | 7 | 5 | 7 | 9 | 10 | **8.05** | VERY HIGH |
| **B. Systemic Anomaly Detector** | 7 | 7 | 8 | 8 | 8 | 6 | 8 | 10 | **7.60** | VERY HIGH |
| **C. Survival Curves** | 7 | 7 | 7 | 8 | 8 | 6 | 8 | 10 | **7.40** | HIGH |
| Real LLM provider integration | 6 | 3 | 8 | 6 | 9 | 5 | 7 | 4 | 6.00 | MEDIUM — `NEEDS HUMAN DECISION` |
| LLM-as-judge faithfulness | 5 | 6 | 4 | 5 | 7 | 6 | 6 | 6 | 5.35 | MEDIUM — `DEFERRED` |
| Uplift / CATE | 6 | 7 | 6 | 3 | 2 | 2 | 5 | 8 | ~4.5 | LOW — `REJECTED` |
| Merchant embeddings | 3 | 5 | 5 | 4 | 1 | 2 | 3 | 8 | ~3.4 | LOW — `REJECTED` |
| Contextual bandits | 5 | 6 | 6 | 2 | 1 | 2 | 4 | 7 | ~3.8 | LOW — `REJECTED`/`DEFERRED` |
| Learning-to-rank playbooks | 5 | 5 | 5 | 3 | 1 | 3 | 5 | 8 | ~4.0 | LOW — `REJECTED`/`DEFERRED` |
| Graph ML on merchant/counterparty | 2 | 4 | 4 | 3 | 1 | 2 | 3 | 8 | ~2.9 | REJECT |

(Data feasibility for A is intentionally scored moderately, not high — n=6 real labeled cases is genuinely thin; this is treated honestly rather than smoothed over. It is Feature A's business alignment, demo impact, and near-zero incremental effort that carry its score, not a false claim of statistical strength.)

---

## 6. Dependency graph

```
                          Existing Torque Core
                    (deterministic, unchanged by any of this)
                                   │
        ┌──────────────────────────┼──────────────────────────┐
        │                          │                          │
   Feature C                  Feature A                  Feature B
 (Survival Curves)      (Recovery Likelihood Panel)   (Systemic Anomaly Score)
        │                          │                          │
  reads: RevenueLeakCase     reads: existing shadow/    reads: Event / CaseEvent
  (opened_at, closed_at,     features + retrieval        counts, grouped by
   status, leg_type)         (unchanged)                 issuer/network scope
```

Each feature can be implemented alone, in any pair, or all three, with no code shared between them beyond already-existing Torque infrastructure. Optional (never required) enhancements:

```
Feature C ─ ─ ─ optional ─ ─ → Feature A   (a case's "days since opened" percentile,
                                             from C's survival curve, could become one
                                             more input feature/context line in A's
                                             explanation panel — NOT required)

Feature B ─ ─ ─ optional ─ ─ → Feature A / LLM narrative
                               (an anomaly score could be added as one more evidence
                                field for the LLM explanation prompt — NOT required)
```

Dashed arrows are enhancements a future pass could add if all three ship; none is a hard dependency, and none is assumed in the effort estimates below.

---

## 7. Feature A — Recovery Likelihood & Explainable Risk Panel

### A. Problem

The only "probability of recovery" number anywhere in Torque today is `benchmarks.cold_start_probability()` — an 8-row hardcoded lookup table keyed on `(leg_type, time-bucket)`, explicitly commented in the code as the intended replacement point for a learned model once enough data exists. A fully-built, fully-tested shadow logistic-regression classifier (Phase 7) already predicts this more richly (9 features, not 2) — but it has no API route and no UI surface (D-149 deliberately scoped it out). Feature A closes that gap: it makes the *existing* learned probability visible, advisory, and explainable, without touching `cold_start_probability()`, `compute_recovery_score()`, or any other deterministic path.

### B. AI/ML formulation

- **Type**: supervised binary classification (existing, unchanged) **plus** a new case-based/instance-based reasoning baseline (nearest-neighbor over existing retrieval).
- **Input**: `ShadowFeatureVector` — the existing 9-field feature dict, computed as-of the case's own `DIAGNOSIS_COMPLETED` event (existing leakage-safe cutoff).
- **Output**: `P(recovered) ∈ [0,1]` (from LR) shown alongside "N of M comparable precedent cases recovered" (from nearest-neighbor), each carrying its own confidence framing, plus an exact coefficient-based attribution breakdown.
- **Target**: `y = 1 if status ∈ {RECOVERED, CANCELLED} else 0` — reused exactly from `torque.ai.shadow.labels.recovered_label`. **Not reinvented.**
- **Prediction horizon**: none — a point-in-time snapshot probability, not a fixed N-day-ahead forecast (a horizon-aware version would require Feature C's survival framing; deliberately not conflated here).
- **Unit of prediction**: one open (non-terminal), already-diagnosed case, evaluated at view time.
- **Training objective**: unchanged — existing `sklearn.linear_model.LogisticRegression`, `max_iter=1000`, MLE/log-loss.

### C. Data

Exactly the existing `torque.ai.shadow.features.extract_features` / `build_shadow_dataset` read path: `RevenueLeakCase`, `CaseEvent` (for the `DIAGNOSIS_COMPLETED` cutoff and `NETWORK_DIRECTIVE_RECEIVED` reconstruction), `MerchantCounterparty` (`promise_keeping_rate`, `risk_score`), `B2BInvoice` (for B2B `amount_at_risk`). The nearest-neighbor baseline additionally reuses `torque.ai.retrieval.find_precedent` unchanged (same-merchant, same `leg_type` + `root_cause_code`, terminal-only, top-K).

### D. Feature set

| Feature | Source | Type | Leakage risk | Missingness | Transformation |
|---|---|---|---|---|---|
| `leg_type` | `RevenueLeakCase.leg_type` | categorical | None (fixed at case creation) | Never missing | One-hot via `DictVectorizer` |
| `root_cause_code` | `RevenueLeakCase.root_cause_code` (as of diagnosis) | categorical | None (read at the diagnosis cutoff, not later) | `"MISSING"` sentinel | One-hot |
| `diagnosis_confidence` | `RevenueLeakCase.diagnosis_confidence` | numeric | None | Mean-imputed + `_missing` indicator | As-is |
| `amount_at_risk` | Current row (all legs) / Σ`B2BInvoice.original_amount` (B2B only — leakage fix already applied, D-148) | numeric | **Already mitigated**: raw live column would leak post-recovery decrements for B2B | Mean-imputed + indicator | Cast to float |
| `days_since_failure` | Derived from case timestamps as of cutoff | numeric | None | Mean-imputed + indicator | As-is |
| `promise_keeping_rate` | `MerchantCounterparty.promise_keeping_rate` | numeric | None (no in-codebase writer during a case's life — static) | Mean-imputed + indicator | As-is |
| `risk_score` | `MerchantCounterparty.risk_score` | numeric | None (no writers exist — always `None` in practice today) | Mean-imputed + indicator | As-is |
| `mandate_type` | Case `context` (subscription leg only) | categorical | None | `"MISSING"` sentinel | One-hot |
| `network_directive_tier` | Reconstructed from `NETWORK_DIRECTIVE_RECEIVED` events ≤ cutoff (not the live column) | categorical | **Already mitigated**: the live column can ratchet more restrictive *after* diagnosis but before closure | `"MISSING"` sentinel | One-hot |

### E. Label

```text
y = 1  if case.status ∈ {RECOVERED, CANCELLED}
y = 0  otherwise (for terminal, diagnosed cases only)
```
Identical to the existing, `LOCKED` definition in `torque.ai.shadow.labels.recovered_label`. Not redefined here.

### F. Leakage analysis (mandatory section)

Fields that must **never** be available at prediction time, and how each is already excluded structurally (verified, not assumed): `recovery_type`, `recovered_amount`, `recovery_score`/`recovery_score_breakdown`, `escalation_resolution`/`escalation_resolved_by`/`escalation_resolved_at`, `closed_at`, `status` itself — none of these appear in `ShadowFeatureVector`'s schema at all (not merely "unused," structurally absent). The two known historical leakage bugs the team already found and fixed (B2B `amount_at_risk` via live vs. invoice-sum; `network_directive_tier` via live column vs. as-of-cutoff reconstruction) are cited here as evidence of the discipline this feature inherits, not problems introduced by this document.

### G. Model candidates

| Candidate | Verdict | Rationale |
|---|---|---|
| **Logistic Regression** (existing) | **Keep — `LOCKED`, D-146** | Already the project's own documented departure from XGBoost, justified by n=6. Reaffirmed, not reopened (see §9.14). |
| **NEW: Nearest-neighbor / precedent recovery-rate** (via existing `find_precedent`) | **RECOMMENDED, add alongside** | Zero parametric assumptions, needs no "fitting," every neighbor is a real case a human can click into (reuses the existing citation UI for free). More defensible than LR at this n because it makes no claim about coefficients or feature interactions — it just counts. |
| Random Forest / GBM / XGBoost / CatBoost / LightGBM | **REJECTED for current n** | Peduzzi (1996) and the PMLBmini small-tabular-data benchmark (arXiv:2409.01635) both show tree ensembles need substantially more rows-per-parameter than linear models to avoid unstable splits; at n=6 there is no chance of a stable split. Reaffirms, does not reverse, D-146. |
| Naive Bayes | **REJECTED** | No evidence it would outperform LR or the NN baseline here; adds a third model family for no demonstrated benefit at this n. |

### H. Evaluation

- **Split**: existing temporal split, unchanged (`temporal_train_test_split`, sorted by `as_of`, earliest→train). Currently `n_train=5, n_test=1`.
- **Baseline**: existing majority-class baseline (already computed and compared against, per the explicit code instruction "do not report impressive-looking metrics without checking baseline performance").
- **Metrics**: accuracy/precision/recall/F1/ROC-AUC (already computed; `None` when undefined by a single-class test fold — never fabricated).
- **New**: Wilson-score confidence interval around the nearest-neighbor recovery-rate ratio — **reuses the exact CI helper already built for `torque.reporting.incrementality`**, zero new statistics code required.
- **Calibration**: explicitly **not attempted** at this n. Isotonic regression is documented to overfit small calibration sets (arXiv:2002.10199); Platt scaling needs a held-out calibration split this dataset cannot spare. Raw probabilities are shown with the mandatory disclaimer instead — this matches, rather than changes, the existing shadow-model philosophy.
- **Class imbalance**: acknowledged (5:1 in the current split) — not corrected for via resampling (SMOTE-style oversampling at n=6 would fabricate data), left visible in the reported class distribution instead.
- **Minimum sample requirements** (§3): logistic regression with ~15-20 one-hot columns needs on the order of 150-200 cases for EPV-defensible coefficients; nearest-neighbor with Wilson CI is usable earlier but the CI width must be shown, not hidden, below ~30 cases.

### I. Explainability

- **LR**: exact coefficient × (encoded feature value) decomposition. This is not an approximation — for a linear model, this *is* what SHAP reduces to (Lundberg & Lee, NeurIPS 2017, §"additive feature importance"), so no separate SHAP dependency is needed to make an equivalent claim.
- **NN**: the retrieved precedent cases themselves, rendered via the *already-built* Phase 3/6 citation and precedent UI — zero new explainability code required for this half of the feature.

### J. UI/demo

```
Recovery likelihood (Experimental — based on 6 historical cases)
62%
Similar cases
3 of 4 comparable precedents recovered  [view precedents →]
Top drivers
+ Promise-keeping history (0.82)
− Case age (14 days)
+ Low network directive severity
⚠ Below the 30-case threshold for meaningful evaluation — directional only
```

Rendered as a new collapsible panel in the existing Agent Console pane (`torque.js`), next to — not replacing — the existing "Explain this case" narrative button.

### K. Architecture

```
Torque domain (RevenueLeakCase, CaseEvent, MerchantCounterparty, B2BInvoice)
        ↓
torque.ai.shadow.features (existing, unchanged)
        ↓
torque.ai.shadow.model / training (existing, unchanged — refit on demand, in-process; not persisted, consistent with D-AI-09's "no caching table" precedent)
        ↓
NEW: torque.ai.shadow.serving — combines LR output + find_precedent NN rate + coefficient attribution → new DTO
        ↓
NEW: GET /ai/{merchant_id}/cases/{case_id}/recovery-likelihood  (same AISettings.enabled gate, same error-mapping conventions as /explain)
        ↓
Agent Console UI (new panel, reuses existing citation-rendering JS)
```

### L. Failure behavior

- Model untrained / single-class training data → existing constant-predictor fallback, `limitations` populated (already coded).
- Case not yet diagnosed → explicit 404-style gap message, mirroring `EvidenceNotFoundError`.
- `n_training_cases < 30` → mandatory "insufficient data — directional only" banner (existing threshold constant, reused).
- Unseen categorical value at inference → `DictVectorizer` already contributes zero silently; surfaced explicitly as "unseen category, no historical signal" in the drivers list rather than left silent.
- Any exception → generic 5xx with no internal detail leaked, matching the existing `/explain` route's Phase 8 hardening pattern.

### M. Integration boundary

- **READS FROM**: `RevenueLeakCase`, `CaseEvent`, `MerchantCounterparty`, `B2BInvoice`, existing `torque.ai.shadow.*`, existing `torque.ai.retrieval`.
- **WRITES TO**: nothing. No persistence, no `CaseEvent`, no case column — matches `INV-65` ("Shadow-ML predictions are structurally incapable of influencing authoritative Torque state").
- **MUST NOT MODIFY**: `recovery_score`/`compute_recovery_score`, the diagnosis engine, playbook selection, any state transition. Automatically covered by the existing AST import-boundary test (`test_ai_boundary.py`) since this code lives under `src/torque/ai/`.

### Stop condition

```
IMPLEMENT IF:
  the team wants a visible, genuinely-learned "prediction" surface for judges,
  and is comfortable presenting it with an honest small-n disclaimer.

DO NOT IMPLEMENT IF:
  the team decides the "n=6, directional only" framing undercuts the demo's
  confidence — in that case, prioritize Feature C (no such asterisk) instead.
```

### Effort

**S–M** (~0.5–1 day). New: one serving module (~80-120 LOC combining two already-built pipelines), one DTO, one API route (mirrors `/explain` almost line-for-line), one UI panel, targeted tests. No new dependency.

---

## 8. Feature B — Statistical Systemic-Spike Anomaly Detector

### A. Problem

`systemic_threshold_breached()` gates a hard compliance action (suppressing retries/contact during a suspected issuer/network outage) on a fixed rule: `failure_rate ≥ 5× baseline AND baseline ≥ floor AND count ≥ floor`. The 5× multiplier and both floors are explicitly commented in `config.py` as *"U-04 placeholders (no blueprint figure) — configurable, not empirically validated."* This feature adds a genuine, continuous, statistically-grounded anomaly score as an **advisory annotation** alongside that gate — never as its replacement — giving both a strong live demo moment (a real spike, scored in real time) and a principled way to sanity-check whether "5×" is a reasonable choice.

### B. AI/ML formulation

- **Type**: unsupervised statistical anomaly detection (time-series / rate-based), not classification — a genuinely different ML paradigm from Feature A, which strengthens the independence and breadth of the three-feature set.
- **Input**: a rolling per-minute failure count for a given scope (issuer/network), using the same trailing-window baseline definition the code already computes (`_baseline_failure_rate`: 7-day trailing average, excluding the live 10-minute detection window so a spike cannot inflate its own baseline).
- **Output**: a continuous anomaly score — e.g. `z = (observed_rate − baseline_rate) / sqrt(baseline_rate / window_minutes)` (a Poisson-rate approximation, appropriate for count data) or an EWMA control-chart deviation — plus a plain-language "how many σ above baseline" statement.
- **No target/label** — unsupervised by design.

### C. Data

Failure-event timestamps grouped by `(issuer_code, network)` scope, derivable from existing `Event`/`CaseEvent` rows. The *baseline* computation already exists in `src/torque/ingestion/systemic.py`; this feature adds a scoring layer, not a new data pipeline.

### D. Feature set

Effectively one input series per scope: current-window rate vs. trailing baseline rate. Minimal feature engineering, which is itself a strength at this data scale — there is nothing to overfit.

### E. Label

None (unsupervised). For **evaluation only**, synthetic injected spikes (extending the existing scenario-injector pattern) serve as known-positive test cases — explicitly and permanently labeled "synthetic evaluation," never conflated with a real-spike-history claim (§4), because no real spike history exists to evaluate against.

### F. Leakage analysis

The existing baseline window already excludes the live detection window from its own average (preventing a spike from inflating its own baseline) — this feature reuses that logic rather than reinventing it, and must not shorten or remove that exclusion.

**Architectural note (must be followed, not optional):** `test_ai_boundary.py` forbids anything under `src/torque/ai/` from importing `torque.ingestion` (where the existing baseline calculation lives). Rather than requesting an exception to that boundary test, this feature should be placed in **`src/torque/reporting/`** (e.g. `reporting/systemic_anomaly.py`), architecturally parallel to the existing `reporting/incrementality.py` — a statistical-but-not-LLM analytics module, reading via `TenantScope`, computed on demand, never persisted. This avoids relitigating the AI-boundary import list and follows an already-established precedent in the codebase rather than inventing a new one.

### G. Model candidates

| Candidate | Verdict | Rationale |
|---|---|---|
| Fixed 5× multiplier (existing) | **Keep — untouched, still the authoritative compliance gate** | Not a candidate to replace; this feature is additive/advisory only |
| **Poisson-rate z-score / EWMA control chart** | **RECOMMENDED** | Standard, simple, works from the first event (no training data needed), fully explainable as "N σ above baseline" |
| Isolation Forest over engineered windows | **REJECTED for v1** | Needs many more historical windows than exist at demo/hackathon event volume; also less transparent than a rate-ratio test for a live judge-facing demo, without a data-volume benefit to justify the opacity (Liu, Ting & Zhou, ICDM 2008 — a general-purpose method, not specifically suited to sparse count data) |
| Bayesian changepoint detection | **REJECTED** | Overkill for hackathon scope; harder to explain live than a single z-score |

### H. Evaluation

Inject N synthetic spikes at known times via an extended scenario injector; measure detection latency and false-positive rate against quiet baseline periods. Explicitly labeled synthetic (§4) — there is no real historical spike-labeled data to validate against, and that absence is stated plainly rather than glossed over.

### I. Explainability

Maximal — "current rate is `X`σ above the 7-day baseline of `Y`/min" is a single interpretable number plus a chart, no model internals to explain.

### J. UI/demo

A small gauge/sparkline on the merchant dashboard or systemic-event card: *"Anomaly score: 4.2σ above 7-day baseline"* with a historical trend line, live-triggerable via the existing scenario injector for a judge to click during the demo.

### K. Architecture

```
Event / CaseEvent timestamps (existing)
        ↓
torque.reporting.systemic_anomaly (NEW — pure stats, TenantScope-read only,
duplicates the small baseline-rate calculation locally rather than importing
torque.ingestion, following the same documented-duplication discipline already
used elsewhere, e.g. torque.ai.retrieval's local terminal-status mirror)
        ↓
NEW: GET /reports/{merchant_id}/systemic-anomaly-score
        ↓
Dashboard widget
```

### L. Failure behavior

Insufficient event history (e.g. a cold-start merchant with <7 days of data) → explicit `insufficient_baseline_data=True`, never a fabricated score. Zero-variance scope → guarded divide-by-zero (mirrors the existing baseline-floor config pattern).

### M. Integration boundary

- **READS FROM**: `Event`/`CaseEvent` counts via `TenantScope`.
- **WRITES TO**: nothing.
- **MUST NOT MODIFY**: `systemic_threshold_breached()` or any input to it. This score is presented *alongside*, never *instead of*, the deterministic gate. Feeding it into the actual compliance decision is explicitly out of scope for this document and would require its own, separately-approved phase — the same posture the existing AI layer already takes toward its own shadow model (D-149 / `INV-65`).

### Stop condition

```
IMPLEMENT IF:
  the team wants a statistically genuine anomaly-detection demo moment that
  is fully decoupled from the tiny case-outcome dataset.

DO NOT IMPLEMENT IF:
  synthetic event volume cannot be made large enough to show a convincing
  baseline-vs-spike contrast live (low risk — the scenario injector can
  already fire events on demand).
```

### Effort

**S–M** (~0.5–1 day). New: ~50-80 LOC duplicated/adapted baseline+scoring logic, one API route, one dashboard widget, a synthetic-spike test harness. No new dependency (pure Python/numpy-level math, no numpy even strictly required).

---

## 9. Feature C — Time-to-Recovery Survival Curves

### A. Problem

Torque has no notion today of "how long recovery should reasonably take." Cases are prioritized only by the static economic score; there is no way to tell whether a given open case is on track or already an outlier in duration. Survival analysis answers exactly this, and — uniquely among the three features — can use **all 16 seeded cases**, not just the 6 labeled-terminal ones, by treating still-open cases as right-censored rather than discarding them.

### B. AI/ML formulation

- **Type**: unsupervised/descriptive time-to-event modeling (survival analysis) — a third distinct ML paradigm, alongside Feature A's supervised classification and Feature B's unsupervised anomaly detection.
- **Input**: for every case, `(duration_days, event_observed)` where `duration_days = (closed_at or now) − opened_at`.
- **Output**: the Kaplan-Meier survival function `Ŝ(t) = P(not yet recovered by day t)`, stratified by `leg_type` where each stratum has enough events (§3), with a median time-to-recovery and a Greenwood's-formula confidence interval.
- **`event_observed`**: `1` if `status ∈ {RECOVERED, CANCELLED}` (the **same** label definition as Feature A and the existing shadow model — deliberately reused, not reinvented, for cross-feature consistency); `0` (censored) for every other case — including cases still open, and, as a stated simplification, cases that reached `EXHAUSTED`/`WRITTEN_OFF` (a full competing-risks treatment is possible future work, not attempted here — see Limitations).
- **Unit of analysis**: one case.

### C. Data

`RevenueLeakCase.opened_at`, `closed_at`, `status`, `leg_type` only. No dependency on diagnosis, features, or the shadow pipeline at all — the cleanest, most self-contained of the three features.

### D. Feature set

None in the predictive-modeling sense (Kaplan-Meier is non-parametric and covariate-free); `leg_type` is used only as a stratification key, not a model input, which keeps leakage risk essentially at zero.

### E. Label

```text
event_observed = 1  if status ∈ {RECOVERED, CANCELLED}, at time = duration_days
event_observed = 0  otherwise (open, or reached a non-recovery terminal state),
                     at time = duration_days measured to now (open) or to
                     closed_at (non-recovery terminal)
```

### F. Leakage analysis

Not applicable in the classic feature-leakage sense (no covariates are used), but two care points: (1) censoring time for still-open cases must use *query time*, never a future `closed_at` — standard survival-analysis practice, straightforward to get right; (2) `recovered_amount`/`recovery_type` are not used at all, so there is no risk of the label leaking into a covariate the way it could in a classification setting.

### G. Model candidates

| Candidate | Verdict | Rationale |
|---|---|---|
| **Kaplan-Meier** | **RECOMMENDED** | Non-parametric, no distributional assumption — the standard first choice for time-to-event data with censoring (Kaplan & Meier 1958; used as the baseline throughout the collections/credit-scoring survival literature, e.g. the invoice-payment-time study, arXiv:1912.10828). Fully honest at small n: it doesn't pretend a shape it hasn't observed. |
| Cox Proportional Hazards | **REJECTED for now** | Needs covariates and enough events to estimate stable hazard ratios — the same EPV-style argument as Feature A applies; 6-7 events cannot support a multivariate Cox model responsibly. |
| Random Survival Forest | **REJECTED for now** | Literature shows RSF can outperform Cox at *ranking* payment times (Springer, "Recovery process optimization using survival regression") but requires substantially more events than exist here to avoid pure overfitting; revisit at production scale. |
| Parametric survival (Weibull/exponential) | **REJECTED** | Distributional assumptions are unverifiable at this n; Kaplan-Meier is strictly the more honest choice. |

### H. Evaluation

This is a descriptive statistic, not a held-out predictive claim — there is no train/test split to report. Instead: report the KM curve with Greenwood confidence bands (which will be visibly wide, and should be shown as such, not hidden); state N and the number of observed events vs. censored explicitly next to every curve (`N=16, 7 events, 9 censored`); apply the §3 floor (≥10 events per stratum) before showing any *per-leg* curve — pool across legs when a stratum falls short, rather than showing a single-step, information-free "curve."

### I. Explainability

Maximal by construction — the output *is* the explanation (a step function plus a median and an N).

### J. UI/demo

```
Expected time to recovery — Payment Degradation
[step-function chart]
Median: 2.1 days (95% CI: 0.8–4.6, based on 4 historical events)
This case is at day 3 — past the median for its leg.
```

### K. Architecture

```
RevenueLeakCase (opened_at, closed_at, status, leg_type)
        ↓
NEW: torque.reporting.survival — pure functions, TenantScope-read, no
persistence, architecturally parallel to torque.reporting.incrementality
        ↓
NEW: GET /reports/{merchant_id}/time-to-recovery
        ↓
Dashboard chart
```

### L. Failure behavior

A `leg_type` stratum with fewer than the §3 event floor → fall back to a pooled (unstratified) curve with an explicit note, never a fabricated per-leg curve. Merchant with zero terminal cases → explicit empty state.

### M. Integration boundary

- **READS FROM**: `RevenueLeakCase` only.
- **WRITES TO**: nothing.
- **MUST NOT MODIFY**: `recovery_score`, human-queue ordering. An "aging percentile" derived from this feature could *optionally* enrich Feature A's explanation panel in the future (§6's dashed-line enhancement) — never a hard dependency, and not built in this pass.

### Stop condition

```
IMPLEMENT IF:
  the team wants the cheapest, most statistically defensible of the three —
  it uses the full N=16 dataset honestly via censoring and needs zero new
  dependencies.

DO NOT IMPLEMENT IF:
  every leg has fewer than ~2 observed events even pooled (not the case
  today — pooled N=7 events across 16 cases is enough for one honest
  overall curve even if per-leg curves must be suppressed).
```

### Effort

**S** (~0.5 day). Kaplan-Meier and Greenwood's formula are each ~30-40 lines of pure arithmetic — hand-rolling is recommended over adding a `lifelines` dependency, both to keep the dependency footprint at zero and because the computation is simple enough that hand-rolling it is genuinely less overhead than vetting a new library.

---

## 10. Candidates investigated and rejected (detail beyond the summary table)

### 9.6 Merchant/counterparty behavioral embeddings — `REJECTED`

The originating technique (Guo & Berkhahn, arXiv:1604.06737) is designed for categorical variables with many examples *per category* — its stated benefit is learning structure among categories with enough data to make similar categories land near each other in the embedding space. Torque has 2 merchants and ~18 counterparties total. There is no meaningful "structure among categories" to learn with 1-16 examples per category, and an embedding trained on this would memorize noise, not behavior. **Do not implement unless the merchant/counterparty count reaches the thousands.**

### 9.8 Contextual bandits / next-best-action — `REJECTED (hackathon)` / `DEFERRED (research)`

Contextual bandits are specifically good at the cold-start problem *for new arms in an ongoing system with repeated trials* — but Torque's actual data has ~1 action per case, not repeated pulls of different arms against the same context to learn from. There is no exploration/exploitation loop to bootstrap from; building one would require accumulating genuine online interaction data first, which is an infrastructure change (multiple channel/timing options tried per case, tracked), not a modeling change. **Do not implement until real-world channel adapters are live and produce enough repeated-trial volume per merchant to support even a simple epsilon-greedy baseline.**

### 9.9 Learning-to-rank playbook selection — `REJECTED (hackathon)` / `DEFERRED (research)`

`select_playbook_id()` is a strict 1-to-1 map: exactly one playbook is eligible per `(leg_type, root_cause_code, mandate_type)`. There is no historical record of "playbook X was chosen over playbook Y for a comparable case" because no such comparison has ever existed — there is nothing to rank against. Building this would first require widening the eligibility map to produce genuine candidate *sets* (a policy/product decision, not an ML one) before any ranker has signal to learn from. **Do not implement until multiple eligible playbooks per root cause exist and enough comparative outcome data accumulates.**

### 9.10 Uplift / CATE / heterogeneous treatment effects — `REJECTED`

Investigated rigorously per the task's specific instruction to check treatment assignment mechanism, sample size, overlap, SUTVA, temporal leakage, and positivity:

- **Treatment assignment**: genuinely clean — `in_control_cohort` is assigned once per merchant-counterparty relationship, before any case exists, immutable thereafter (`CohortAlreadyAssignedError` on re-assignment). No temporal leakage.
- **Sample size**: 13 treatment / 3 control counterparties. Adequate for a **pooled** average treatment effect (which is exactly what the existing Wilson-score/Newcombe-hybrid reporting already computes) but far short of what's needed to estimate *heterogeneous* effects, which requires enough sample **within each covariate subgroup, in both arms** — with only 3 control counterparties total, there is no subgroup with usable within-arm variation.
- **Overlap/positivity**: cannot be meaningfully assessed at this n — there's no way to check whether treatment and control counterparties have comparable covariate distributions with 3 control units.
- **SUTVA**: intra-merchant spillover is already handled correctly (counterparty-level, not case-level, assignment). Cross-merchant contamination exists and is already handled via an explicit adjustment in `incrementality.py` — this is good, existing work, not something CATE modeling would improve on.

**Verdict**: the existing ATE machinery (`torque.reporting.incrementality`, Wilson + Newcombe CIs) is already the statistically correct tool for this data and should be left exactly as-is — it is not superseded by anything in this document. Individual-level uplift/CATE modeling should not be attempted until the control cohort is at least in the low hundreds of counterparties per merchant, with enough per-subgroup representation to estimate heterogeneity honestly (Yao et al., arXiv:2007.12769).

### 9.13 Isotonic/Platt calibration — `REJECTED` (for the current shadow model)

Both are documented to need a calibration set independent of the training data; isotonic regression specifically is flagged in the small-data-calibration literature (arXiv:2002.10199) as prone to overfitting when that set is small. At n=6, no defensible split exists for a third calibration partition on top of the existing train/test split. **Revisit only once the training population is large enough to spare a genuine calibration holdout — order-of-magnitude 100+ cases.**

### 9.14 XGBoost + SHAP re-evaluation (task-mandated re-check, not a silent change)

```
EXISTING DECISION: Torque_Blueprint_v7_FullSystem.md §8.4 "RECOMMENDED": XGBoost +
SHAP + T/X-learner uplift, once 500+ resolved cases exist. Re-affirmed as D-146
(LOCKED) by the existing AI-layer team, which chose plain LogisticRegression instead
for the current Phase 7 shadow model, citing the 6-case reality.

PROPOSED CHANGE: none. This document does not change the 500-case gate or the
LogisticRegression choice below it.

EVIDENCE: Peduzzi et al. (1996) — logistic regression remains stable from ~25
events per free parameter, while a comparable tree ensemble required up to 1000
events per free parameter for robust performance in a directly comparable
simulation study. The PMLBmini small-tabular-data benchmark (arXiv:2409.01635)
independently found LightGBM/XGBoost/CatBoost underperforming logistic regression
at small sample sizes, only overtaking it as data grows. Neither result is
specific to Torque, but both point the same direction as D-146's own reasoning.

RATIONALE: the existing 500-case gate for XGBoost is not just reasonable, it is
arguably conservative in the right direction given this literature — no change
recommended. The 6-16 case regime Torque is in today is squarely in the "favor
logistic regression / non-parametric methods" zone across every source reviewed.
```

---

## 11. Small-data-appropriate methods — summary comparison

| Method | Verdict at Torque's current n (6–16) | Verdict at 500+ cases |
|---|---|---|
| Logistic regression | **Appropriate** (already in use, D-146) | Still appropriate, revisit only if nonlinearity is demonstrated |
| Random forest / GBM / XGBoost / LightGBM / CatBoost | Inappropriate — unstable splits, no evidence of benefit | Appropriate — the blueprint's own existing gate (Decision F) |
| Isolation Forest / other unsupervised anomaly detection | Appropriate for event-rate data (Feature B), inappropriate as a case-outcome model | Appropriate either way |
| Survival models (Kaplan-Meier) | **Appropriate** (Feature C) — non-parametric, uses censored data honestly | Cox/RSF become viable |
| Bayesian models | Not investigated as a priority — plausible future direction for principled small-n uncertainty, not selected here for effort/familiarity reasons | Still plausible |
| Entity embeddings | Inappropriate — wrong cardinality direction entirely | Only if entity counts (merchants/counterparties) grow by orders of magnitude, not just case counts |
| Neural networks / Transformers | Inappropriate — no justification for the added complexity or compute at this n, and no genuine sequence-length signal to exploit (≈1 action/case) | Only with real sequential/longitudinal action histories, which don't exist yet even at higher case counts unless action depth also grows |
| Graph neural networks | Inappropriate — the merchant/counterparty graph has no meaningful topology at this scale | Only with hundreds+ of merchants and dense counterparty relationships |
| Reinforcement learning / contextual bandits | Inappropriate — no repeated-trial-per-arm data exists | Only after real channel adapters produce genuine online interaction volume |

---

## 12. Security / governance checklist (all three features)

- **No raw PII**: none of the three features touch `Counterparty.name/phone/email` — Feature A reuses the existing PII-safe read paths; Features B and C never read `Counterparty` at all.
- **Tenant isolation**: every read in all three features goes through `TenantScope`, matching the discipline already used everywhere in `torque.ai` and `torque.reporting`.
- **Auditability/reproducibility**: none of the three persist anything — every output is a pure function of current Torque state, computed on demand, matching the existing `D-AI-09` ("no caching table") precedent for consistency across the AI/reporting surface.
- **No execution authority**: all three are read-only informational surfaces; none can trigger an action, transition a case, or write a `CaseEvent`.
- **No new paid infrastructure**: zero new external services; Feature A adds zero new dependencies, Feature B adds zero, Feature C is recommended to be hand-rolled specifically to add zero.

---

## 13. Implementation effort & recommended sequence

| Feature | Files/modules (new) | Approx. LOC | New dependency | Migration? | API work | UI work | Effort |
|---|---|---|---|---|---|---|---|
| C — Survival curves | `reporting/survival.py`, 1 route | ~150-250 | None | No | S | S (1 chart) | **S** |
| A — Recovery likelihood panel | `ai/shadow/serving.py`, 1 DTO, 1 route | ~150-250 | None | No | S | S (1 panel) | **S–M** |
| B — Systemic anomaly score | `reporting/systemic_anomaly.py`, 1 route | ~150-200 | None | No | S | S (1 widget) | **S–M** |

### Recommended order: **C → A → B**

**Reasoning** (maximizing demo value delivered per unit of remaining hackathon time): C is the cheapest and carries no "small-n asterisk" — build it first to bank a guaranteed, statistically clean win using the full 16-case dataset. A is the highest business/demo-alignment feature (a real "AI reads case, predicts, explains" moment matching exactly what the original blueprint named as its future direction) but requires the team to be comfortable presenting an honest small-n disclaimer — sequence it second, once the team has a working demo in hand and time to think about framing. B closes with the strongest live "wow" moment (a real-time anomaly score reacting to a judge's own click) but needs a small amount of new synthetic-injection test scaffolding — sequence it last so it doesn't block the other two if time runs short.

Each feature is independently stoppable: implementing only C, only A, only B, or any pairing, requires no rework of the others.

---

## 14. Phase plan

```
AI Feature Track (this document)

Feature C — Time-to-Recovery Survival Curves
  ├── Research gate:     PASSED (this document, §9)
  ├── Data gate:         PASSED — uses all 16 seeded cases via censoring
  ├── Implementation:    reporting/survival.py + 1 route
  ├── Evaluation:        Greenwood CI reported alongside every curve; per-leg
  │                      pooling fallback below 10 events/stratum
  └── UI/demo:           1 chart in the reporting dashboard

Feature A — Recovery Likelihood & Explainable Risk Panel
  ├── Research gate:     PASSED (this document, §7)
  ├── Data gate:         PASSED WITH CAVEAT — n=6 real labeled cases,
  │                      EXPERIMENTAL/observational only, mandatory disclaimer
  ├── Implementation:    ai/shadow/serving.py + 1 route
  ├── Evaluation:        existing temporal split + new Wilson-CI NN baseline
  └── UI/demo:           1 panel in the Agent Console

Feature B — Statistical Systemic-Spike Anomaly Detector
  ├── Research gate:     PASSED (this document, §8)
  ├── Data gate:         PASSED — decoupled from case-outcome volume;
  │                      evaluation itself is synthetic-labeled, clearly marked
  ├── Implementation:    reporting/systemic_anomaly.py + 1 route
  ├── Evaluation:        synthetic spike-injection test harness
  └── UI/demo:           1 gauge/sparkline widget
```

If any one feature is abandoned mid-build, the other two remain fully implementable — none shares code, a migration, or a schema change with another.

---

## 15. Final recommendation table

| Feature | AI substance | Business ROI | Demo impact | Effort (10=trivial) | Data feasibility | Recommended |
|---|---:|---:|---:|---:|---:|---|
| A — Recovery Likelihood Panel | 8 | 9 | 9 | 7 | 5 | **YES** |
| B — Systemic Anomaly Detector | 7 | 7 | 8 | 8 | 8 | **YES** |
| C — Survival Curves | 7 | 7 | 7 | 8 | 8 | **YES** |

### Recommended implementation sequence

```
1. Feature C  — cheapest, cleanest data story, zero new dependencies
2. Feature A  — highest business/demo alignment, requires honest framing
3. Feature B  — strongest live "wow" moment, needs small test scaffolding
```

---

## 16. Literature review

Every recommendation above traces to at least one of the following, prioritizing peer-reviewed/major-venue sources per the governing instructions:

1. **Peduzzi, P., Concato, J., Kemper, E., Holford, T.R., Feinstein, A.R. (1996).** "A simulation study of the number of events per variable in logistic regression analysis." *Journal of Clinical Epidemiology*, 49(12), 1373–1379. — Establishes the events-per-variable (EPV) framework used throughout §3 and §9.14 to argue logistic regression remains defensible at far smaller n than tree ensembles, and to size the "how many cases would Feature A need" floor.
2. **van Smeden, M., Moons, K.G.M., de Groot, J.A.H., Collins, G.S., Altman, D.G., Eijkemans, M.J.C., Reitsma, J.B. (2019).** "Sample size for binary logistic prediction models: Beyond events per variable criteria." *Statistical Methods in Medical Research*. — Refines the blunt EPV=10 rule with calibration-focused sample-size guidance, used to justify treating "150-200 cases" as a floor rather than a ceiling for Feature A's real-evaluation claims.
3. **Lundberg, S.M., Lee, S.-I. (2017).** "A Unified Approach to Interpreting Model Predictions." *Advances in Neural Information Processing Systems 30 (NeurIPS 2017)*. — The SHAP paper; cited in Feature A §I to justify that an exact coefficient decomposition for a linear model is SHAP-equivalent, avoiding the need for a separate SHAP dependency.
4. **Liu, F.T., Ting, K.M., Zhou, Z.-H. (2008).** "Isolation Forest." *2008 Eighth IEEE International Conference on Data Mining (ICDM)*, 413–422. — The foundational isolation-based anomaly detection method; cited in Feature B §G to explain why a general-purpose isolation-based detector is rejected in favor of a rate-based statistical test at Torque's current event volume.
5. **Guo, C., Berkhahn, F. (2016).** "Entity Embeddings of Categorical Variables." arXiv:1604.06737. — Cited in §9.6 to explain precisely why merchant/counterparty embeddings are rejected: the technique's own stated benefit requires cardinality Torque doesn't have.
6. **PMLBmini authors (2024).** "PMLBmini: A Tabular Classification Benchmark Suite for Data-Scarce Applications." arXiv:2409.01635. — Empirical small-tabular-data benchmark showing logistic regression matching or beating LightGBM/XGBoost/CatBoost at small sample sizes; used in §9.14 as independent evidence for D-146.
7. **Trauma-triage simulation study (2021).** "The advanced machine learner XGBoost did not reduce prehospital trauma mistriage compared with logistic regression: a simulation study." PMC8215793. — Direct comparative evidence of XGBoost's much larger per-parameter data requirement vs. logistic regression, used in §9.14.
8. **Yao, L. et al.** "A unified survey of treatment effect heterogeneity modeling and uplift modeling." arXiv:2007.12769. — Used in §9.10 to ground the rejection of individual-level uplift/CATE modeling on Torque's current 13-treatment/3-control cohort.
9. **Kull, M. et al. and related work on classifier calibration for small datasets.** arXiv:2002.10199, "Better Classifier Calibration for Small Data Sets." — Used in §9.13 to justify rejecting isotonic/Platt calibration for the current shadow model.
10. **Kaplan, E.L., Meier, P. (1958).** "Nonparametric Estimation from Incomplete Observations." *Journal of the American Statistical Association*. — The foundational survival-curve estimator recommended in Feature C.
11. **Cash-collection / invoice-payment survival literature** — e.g. "Optimize Cash Collection: Use Machine learning to Predicting Invoice Payment" (arXiv:1912.10828) and "Recovery process optimization using survival regression" (*Operational Research*, Springer, 2022) — cited in Feature C §G as domain-adjacent evidence that survival methods (and specifically that Random Survival Forests need materially more events than Kaplan-Meier to earn their added complexity) are an established, not speculative, technique for exactly this kind of collections/recovery time-to-event problem.
12. **ACM Transactions on Recommender Systems** — "User Cold-start Problem in Multi-armed Bandits" (dl.acm.org/10.1145/3554819) — cited in §9.8 to precisely distinguish "bandits handle cold-start for new arms" from "Torque has zero repeated-trial history," which is the actual blocking condition here.

### Rejected approaches, summarized with reasons (cross-referenced to detail sections above)

- **XGBoost/GBM as the primary shadow model today** — rejected, not because it's a bad algorithm, but because Torque's own existing decision (D-146) plus independent literature (items 1, 2, 6, 7 above) agree it needs far more data than exists; reaffirmed, not overturned (§9.14).
- **Merchant/counterparty embeddings** — rejected on cardinality grounds (§9.6, item 5).
- **Uplift/CATE modeling** — rejected on sample-size/overlap grounds, with the existing ATE machinery affirmed as correct and sufficient (§9.10, item 8).
- **Contextual bandits / RL-driven next-best-action** — rejected on missing repeated-trial data (§9.8, item 12).
- **Learning-to-rank playbook selection** — rejected on missing comparative-choice data (§9.9).
- **Graph ML on merchant/counterparty relationships** — rejected, no meaningful topology exists at 2 merchants / ~18 counterparties.
- **Isotonic/Platt probability calibration** — rejected at current n (§9.13, item 9).
- **A real, network-backed LLM provider swap** — not rejected outright, but explicitly kept out of the "3 selected AI/ML features" because its primary value is integration/demo polish rather than new learning/prediction/ranking/anomaly/causal substance, and it carries its own `NEEDS HUMAN DECISION` gate (API budget) already flagged in the existing `AI_BLUEPRINT.md` (D-AI-03).

---

## Final verification checklist

- [x] Actual repository inspected (docs, `src/torque/ai/`, `src/torque/{scoring,policy,execution,coordination,diagnosis}/`, models, migrations, seed data, tests) via four parallel research passes.
- [x] Current AI implementation inspected in detail (evidence, citations, retrieval, narrative, evaluation, shadow ML, API, UI, Agent Console).
- [x] Actual data availability investigated: 16 seeded cases, 7 terminal, 6 ML-eligible, 5-train/1-test — stated plainly, not smoothed over.
- [x] 13 candidate techniques considered (§5).
- [x] 5 serious candidates compared with full weighted scoring (§5.1).
- [x] 3 final candidates selected, each with a complete mini-architecture (§7–9).
- [x] External literature reviewed, prioritizing peer-reviewed/major-venue sources (§16).
- [x] Small-data feasibility explicitly addressed throughout, with a dedicated comparison table (§11).
- [x] Data leakage explicitly analyzed per feature (§7.F, §8.F, §9.F).
- [x] Temporal validation addressed (Feature A's existing temporal split; Feature C's inherently temporal censoring design).
- [x] Causal validity rigorously checked and uplift/CATE explicitly rejected with reasoning (§9.10).
- [x] Synthetic data policy stated and kept separate from real evaluation everywhere it's used (§4, §8.H).
- [x] Every final feature independently implementable; none depends on another newly-proposed feature (§6).
- [x] The deterministic Torque core remains fully authoritative — no feature writes anything or touches any of the nine hard boundaries (§1.3, each feature's §M).
- [x] Implementation effort estimated per feature (§13).
- [x] Demo value explicitly evaluated per feature (§5.1, each feature's §J).
- [x] Failure modes defined per feature (§L sections).
- [x] Implement/do-not-implement gates defined per feature (Stop conditions).
- [x] Existing `LOCKED` decisions (D-146, the 500-case XGBoost gate, the free-tier constraint, "AI reads, Torque decides," D-149's Phase-7 scope) were not silently changed — reaffirmed or explicitly labeled where re-examined (§9.14).
- [x] This document is implementation-ready: each feature's §K (Architecture) and §M (Integration boundary) is specific enough to hand directly to an implementer as "Implement Feature A" (or C, or B) without further research.
