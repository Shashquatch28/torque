# Demo Checklist

Run through this immediately before presenting. Each line is a real command
or a real click — verify, don't assume.

## Environment

- [ ] `docker ps` shows `db` (and `redis`, if the AI/execution demo needs it)
      as `healthy`.
- [ ] `uv run alembic current` reports `0018_escalation_resolution` (head).
- [ ] `uv run python -m torque` is running; `http://127.0.0.1:8000` loads
      the shell (nav bar, flow ribbon) within a couple of seconds.
- [ ] If you want the AI Assessment to work: the process was started with
      `TORQUE_AI_ENABLED=true`. (Restarting to flip this mid-demo is fine —
      it doesn't affect seeded data.)

## Data

- [ ] Live Demo → **Seed demo data** clicked at least once this session; the
      toast reports a case count.
- [ ] Dashboard hero number is non-zero.
- [ ] "Top at-risk cases" is populated.
- [ ] Agent Console → "Human queue" has at least one row (the seed includes
      escalated cases).

## Screens

- [ ] Dashboard: pipeline, leg bars, chart (try clicking Week/Month once),
      incrementality card, exceptions table all render without a console
      error.
- [ ] Open one case from "Top at-risk cases" — header, gauge, "Why
      Torque prioritized," AI Assessment card, timeline, evidence all
      present.
- [ ] Click "Explain this case" once on a case you intend to demo — confirm
      it resolves (either a narrative, or the honest "not enabled" message
      if AI is off) before you're in front of a judge.
- [ ] Agent Console → open a queue row → confirm Resolve/Pause buttons are
      enabled as expected for that case's status.
- [ ] Live Demo → click each of the 7 scenario buttons once; confirm each
      produces a toast and a new feed entry within ~3 seconds.

## Browser hygiene

- [ ] DevTools console open, no red errors during the walkthrough above.
- [ ] Network tab shows no failed (red) requests during the walkthrough.
- [ ] Window is wide enough for the desktop layout (≥1200px) unless you are
      specifically demonstrating responsive behavior.

## Reset before the real thing

- [ ] If you clicked Resolve/Pause while rehearsing, click **Re-seed demo
      data** once more so the judge sees a fresh, escalated case rather than
      one you already resolved.

## If something looks wrong

See [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md).
