# CONTINUATION PROTOCOL

**If you are an AI agent picking up the Torque project, this file tells you how to
proceed. Follow it.**

You have been pointed at this repository and told to continue Torque
development. You do **not** have the previous conversation. That is fine — this
folder plus the repository and `Torque_Blueprint_v7_FullSystem.md` contain
everything you need.

---

## The standard workflow

```
Inspect  ->  Reconstruct Context  ->  Propose Milestone  ->  User Review
   ->  Approval (decisions locked)  ->  Implement (approved scope ONLY)
   ->  Verify  ->  Update Memory  ->  STOP
```

You run one milestone per cycle. You **never** skip "User Review" or "Approval".
You **never** perform Git write operations. You **stop** after "Update Memory"
and hand back a verification report.

---

## The 20 steps

### A. Inspect (steps 1–5)

1. **Read `CURRENT_STATE.md`** in full. It is the one-page snapshot.
2. **Read this file** (`CONTINUATION_PROTOCOL.md`) in full.
3. **Verify the snapshot against the live repo** with read-only commands:
   - `git log --oneline -10` — confirm HEAD matches `CURRENT_STATE.md`'s
     "Git HEAD" and the commit list in `MILESTONES.md`.
   - `git status` — confirm the working tree is clean. If it is **not** clean,
     stop and ask the maintainer what the pending changes are before doing
     anything else.
   - `uv run alembic heads` and `uv run alembic current` — confirm the head
     matches (`0012_...` at the time of writing).
   - `uv run pytest -q` — confirm the count and that everything passes. If the
     count differs from `CURRENT_STATE.md`, the memory is stale: note the delta
     and trust the live result.
   - `uv run ruff check .` — confirm clean.
   If the repo has no Postgres running, `docker compose up -d db` first (or the
   suite skips — a skip is not a pass).
4. **Read `MILESTONES.md`** to see exactly what each past milestone delivered and
   where it stopped.
5. **Read `ARCHITECTURE.md`, `DECISIONS.md`, `INVARIANTS.md`, `DEFERRED.md`,
   `UNRESOLVED.md`.** For the milestone you are about to propose, re-read the
   relevant blueprint section(s) directly from
   `Torque_Blueprint_v7_FullSystem.md` — the memory is a guide, the blueprint is
   the spec.

### B. Reconstruct Context (steps 6–8)

6. **Confirm what is `IMPLEMENTED` vs `PLANNED`/`DEFERRED`/`UNRESOLVED`** for the
   area you intend to touch. Open the actual source files. Do not describe
   planned behaviour as existing.
7. **Check `DEFERRED.md`** — make sure the thing you are about to build is not
   something a later milestone is supposed to own. If it is deferred, either you
   are proposing that milestone (fine) or you have the scope wrong (stop).
8. **Check `UNRESOLVED.md`** — if your proposed work touches an unresolved
   question (especially U-01, the state-machine edges), that question must be put
   to the maintainer *in your proposal*, not silently resolved.

### C. Propose Milestone (steps 9–12)

9. **Pick the next milestone.** Default: the next unbuilt module in blueprint
   order (as of this writing, **Module 2 — Signal Ingestion**). If the module is
   large (Module 2 is), propose a **sub-milestone** with a tight scope (e.g. "7a:
   FastAPI app + Razorpay signature endpoint + `Event` write + idempotency;
   nothing else").
10. **Write the proposal as explicit scope**, covering:
    - Objective (one paragraph).
    - Exactly which files/modules/migrations will be added or changed.
    - Which entities/tables/enums (if any).
    - Which invariants are added and how they are enforced.
    - What is explicitly **out of scope** for this milestone.
    - Test plan (what new test files, what they cover).
    - Whether `state_machine.py` / `guards.py` will be touched (they should not
      be, unless the milestone is specifically about them — call it out loudly).
11. **List every ambiguity as a numbered question** for the maintainer to answer.
    Include any `UNRESOLVED.md` item the milestone touches. Do not proceed on a
    guess where a decision is needed — offer a recommended default and ask.
12. **Present the proposal and STOP.** Wait for the maintainer.

### D. User Review & Approval (steps 13–14)

13. The maintainer reviews, edits scope, and **answers every question / locks
    every decision**. Do not start coding on a partial approval.
14. **Restate the locked scope and decisions** back in one short block so there
    is no ambiguity, then begin.

### E. Implement (steps 15–16)

15. **Implement only the approved scope.** No scope creep. No "while I'm here"
    refactors. No starting the next milestone. No touching files the proposal
    did not name. Match the surrounding code's style, typing, and docstring
    density. Document any approved blueprint deviation in the code docstring.
16. **Do not run any Git write command.** Not `add`, `commit`, `push`, `reset`,
    `rebase`, `amend`, `merge`, `cherry-pick`, `stash`, `checkout -- <path>`,
    `restore`, `switch`, `clean`, or `tag`. Read-only git (`log`, `show`,
    `status`, `diff`, `cat-file`, `ls-files`, `ls-tree`, `rev-parse`,
    `for-each-ref`) is allowed. **If you need per-commit history, use
    `git show <rev>:<path>` — never check out a path.** The maintainer performs
    all VCS.

### F. Verify (steps 17–18)

17. **Run the full verification suite and capture output:**
    - `uv run pytest` — must be fully green (no fails, no unexpected skips).
    - `uv run ruff check .` — must be clean.
    - `uv run alembic upgrade head`, then confirm the roundtrip test passes
      (`uv run pytest tests/test_zz_migrations_roundtrip.py -q`) — up→down→up
      must be clean, and any new enum types must be dropped in `downgrade`.
    - `git diff HEAD -- src/torque/state_machine.py` — expect **empty** unless
      the milestone was approved to change it; if non-empty, show the diff and
      justify it.
    - `git diff HEAD -- src/torque/models/guards.py` — same expectation.
    - `git --no-pager diff --stat HEAD` — the complete list of changed files;
      confirm it matches the approved scope exactly.
18. **Write the verification report:** files created, files modified, migration
    revision(s), test count before/after, ruff status, roundtrip status,
    `state_machine.py`/`guards.py` diff status, any blueprint deviations with
    justification, any new `DEFERRED.md` / `UNRESOLVED.md` items, and a
    **recommended commit message**. If anything failed, say so plainly with the
    output — do not report success you did not verify.

### G. Update Memory & Stop (steps 19–20)

19. **Update `documentation/ai-memory/`** per the Memory Update Protocol below:
    - Append a new `## Milestone N — …` section to `MILESTONES.md`.
    - Append any new decisions to `DECISIONS.md` (never edit old ones).
    - Update `ARCHITECTURE.md` (flip items from `PLANNED` to `IMPLEMENTED`; add
      new entities; keep the tags honest).
    - Add/adjust `INVARIANTS.md` entries for any new invariant.
    - Remove from `DEFERRED.md` only what was actually built; add anything newly
      deferred.
    - Move any answered question in `UNRESOLVED.md` to its "Resolved" section
      with a dated note; add any newly-surfaced question.
    - **Rewrite `CURRENT_STATE.md`** to the new snapshot (this file is meant to
      be replaced each milestone — it is the only one that is).
20. **STOP.** Post the verification report. Do not commit. Do not begin the next
    milestone. Wait for the maintainer.

---

## Hard rules (do not violate, ever)

1. **No Git write operations.** See step 16. The maintainer handles all VCS by
   hand. (There was a 2026-09-02 incident where an agent ran `git stash` /
   `git checkout -- <paths>` in a loop and briefly corrupted `main`. Do not
   repeat it. If you think you need a git write, you are wrong — ask.)
2. **The blueprint is law.** `Torque_Blueprint_v7_FullSystem.md`. Deviate only
   when explicitly proposed, justified, approved, documented in the code
   docstring, and recorded in `DECISIONS.md` as an "intentional deviation".
3. **One milestone at a time.** Inspect → propose → lock → implement approved
   scope only → verify → report → stop.
4. **Do not implement `DEFERRED.md` work as a side effect.**
5. **Do not resolve `UNRESOLVED.md` questions unilaterally.** Surface them in the
   proposal.
6. **`state_machine.py` and `guards.py` are load-bearing.** `state_machine.py`
   has been byte-stable since **M1** (`abbab18`); `guards.py` was last changed in
   **M6a** (`624ebb2`). Changing either requires explicit approval and a shown
   diff in the verification report.
7. **Every milestone verifies:** `pytest` green, `ruff` clean, migration
   up/down/up roundtrip clean, `state_machine.py` diff shown.
8. **Tests are not "optional if hard".** New entities/logic get schema-
   introspection tests, tenant-scoping tests, and happy+violation tests for
   every invariant.
9. **This memory folder is derived, not authoritative.** If it contradicts the
   code, fix the memory and note the contradiction in your report.
10. **Preserve history.** `DECISIONS.md` and `MILESTONES.md` are append-only.

---

## Memory Update Protocol

How future agents keep `documentation/ai-memory/` correct without destroying its
history.

### General

- **Never rewrite history.** `DECISIONS.md` and `MILESTONES.md` past sections are
  immutable. `ARCHITECTURE.md`, `INVARIANTS.md`, `DEFERRED.md`, `UNRESOLVED.md`
  are living catalogues — you edit them, but you do not erase the record of a
  past state (that record lives in `MILESTONES.md` and `DECISIONS.md`).
- **`CURRENT_STATE.md` is the exception** — it is a snapshot and is meant to be
  replaced wholesale each milestone. Keep the same section structure.
- **Flag contradictions, do not silently "fix" them.** If you find the code
  disagreeing with a memory file (or two memory files disagreeing), add a short
  "⚠️ CONTRADICTION:" note stating both sides and which one you believe is
  currently true, and mention it in your verification report. Only remove the
  note once the underlying disagreement is genuinely gone.

### Per file

**`MILESTONES.md`** — append one `## Milestone N — <name>` section using the same
field set as the existing sections (commit, migrations, objective, scope
delivered, decisions, deviations, deferred work introduced, unresolved
introduced, tests at completion, verification status, recommended commit
message). Never edit a prior section; if a later milestone changes something an
earlier one described, say so in the new section.

**`DECISIONS.md`** — append `## D-0NN — <title>` entries (continue the numbering).
Use the full field set (Milestone, Decision, Chosen, Alternatives, Reasoning,
Consequence, Status). If a new decision reverses an old one:
- add the new entry with `Status: IN FORCE`;
- edit **only the `Status:` line** of the superseded entry to
  `SUPERSEDED BY D-0NN` — leave the rest of that entry exactly as written.

**`ARCHITECTURE.md`** — update tags (`PLANNED` → `IMPLEMENTED` when a thing gets
built; add new entities/modules; add `DEFERRED`/`UNRESOLVED` markers as they
arise). Keep the "what is NOT here" section honest.

**`INVARIANTS.md`** — add `## INV-NN` entries for new structurally-enforced
rules; move rules out of the "PLANNED" section as they become enforced. If an
invariant's enforcement mechanism changes, update the entry and note the change.

**`DEFERRED.md`** — strike an item **only** when it is actually implemented (and
that is recorded in `MILESTONES.md`). Add newly-deferred work under the owning
module.

**`UNRESOLVED.md`** — when a question is answered, add "RESOLVED (YYYY-MM-DD):
<answer>" under it and move it to the "Resolved (kept for history)" section; if
it produced a decision, cross-reference the new `DECISIONS.md` id. Add
newly-surfaced questions with the full field set.

**`CURRENT_STATE.md`** — rewrite to the new reality: HEAD commit, migration head,
test count, what is now implemented, the new "next likely milestone", updated
unresolved list, updated known-contradictions list.

**`PROJECT_CONTEXT.md`** — rarely changes. Update only if a foundational fact
changes (stack choice, build philosophy, what "done" means).

**`README.md` (this folder's)** — update the "Provenance" line's commit ref when
you do a full re-reconstruction; otherwise leave it.

---

## How to start the next chat (for the maintainer)

Open a new Claude Code session in the repo root and say something like:

> Load the Torque project memory in `documentation/ai-memory/` (start with
> `CURRENT_STATE.md` and `CONTINUATION_PROTOCOL.md`), verify it against the repo
> (`git log`, `alembic heads`, `pytest`), then propose the next milestone as a
> written scope with every ambiguity flagged as a question. Do not write any
> code or run any Git write command until I approve the scope. The blueprint
> (`Torque_Blueprint_v7_FullSystem.md`) is the source of truth; the memory
> folder is a guide.
