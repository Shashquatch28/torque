"""Phase 7 — the training-population and label definitions. Pure, no I/O.

Two independent questions, each answered by its own small function:

1. **Which cases are even eligible to have a label at all?** Only a case
   that has reached a terminal status — its story is over, one way or
   another — can be scored "did it recover or not." A case still
   `PLAYBOOK_ACTIVE`/`ESCALATED_TO_HUMAN`/etc. has no label yet, full stop
   (`is_training_eligible`).
2. **Given an eligible case, did it recover?** `recovered_label` — a
   binary target, `True` iff `status in {RECOVERED, CANCELLED}`.

**Target definition — locked, not invented here.** This is the exact
population Module 9b's own intent-to-treat measurement already uses
(`torque.reporting.incrementality._RECOVERED_STATUSES`) and the exact
target `documentation/ai-memory/AI_BLUEPRINT.md` §10 names for Phase 7:
"the customer's at-risk money came back, by any means" — broader than
Module 9's dashboard "Torque-attributed" `recovery_rate` (D-116) on
purpose, because a case a customer paid off entirely on their own
(`CANCELLED`, `recovery_type=SELF_RECOVERED`) is still a real, legitimate
"not leaked" outcome for a model trying to predict eventual recovery, not
one trying to measure Torque's own causal contribution (that is Module
9b's separate, already-answered question — see D-133).

**Deliberate, documented duplication — same discipline as
`torque.ai.retrieval`.** `torque.ai`'s forbidden-import boundary
(`tests/test_ai_boundary.py`) blocks the whole `torque.state_machine`
module (including its pure `TERMINAL_STATUSES`/`is_terminal`) and the whole
`torque.reconciliation`/`torque.reporting` surface is not itself forbidden,
but `_RECOVERED_STATUSES` there is a private, non-`__all__` name — cross-
module reuse of a private name is not this codebase's convention. So both
constants are mirrored here, byte-for-byte, exactly as
`torque.ai.retrieval._terminal_statuses_for_leg` already mirrors
`torque.state_machine.is_terminal`. `tests/test_ai_shadow_labels.py` cross-
checks both mirrors against the real functions so any future drift breaks
the build loudly rather than silently.
"""

from __future__ import annotations

from torque.enums import CaseStatus, LegType

#: Byte-for-byte mirror of `torque.state_machine.TERMINAL_STATUSES` — see
#: `torque.ai.retrieval._ALWAYS_TERMINAL` for the original instance of this
#: same mirror, kept independently here per the documented-duplication
#: discipline (each `torque.ai` module that needs it mirrors it itself).
_ALWAYS_TERMINAL: frozenset[CaseStatus] = frozenset(
    {
        CaseStatus.RECOVERED,
        CaseStatus.EXHAUSTED,
        CaseStatus.CANCELLED,
        CaseStatus.WRITTEN_OFF,
    }
)

#: Byte-for-byte mirror of
#: `torque.reporting.incrementality._RECOVERED_STATUSES` — Module 9b's own
#: intent-to-treat "recovered" definition, reused as Phase 7's binary
#: target per `documentation/ai-memory/AI_BLUEPRINT.md` §10.
_RECOVERED_STATUSES: frozenset[CaseStatus] = frozenset(
    {CaseStatus.RECOVERED, CaseStatus.CANCELLED}
)


def _terminal_statuses_for_leg(leg_type: LegType | str) -> frozenset[CaseStatus]:
    """Mirrors `torque.state_machine.is_terminal` exactly: `PARTIALLY_RECOVERED`
    is terminal for every leg EXCEPT `B2B_RECEIVABLE` (a partial B2B payment
    keeps the case open for further dunning of the remainder)."""
    if LegType(leg_type) is LegType.B2B_RECEIVABLE:
        return _ALWAYS_TERMINAL
    return _ALWAYS_TERMINAL | {CaseStatus.PARTIALLY_RECOVERED}


def is_training_eligible(status: CaseStatus | str, leg_type: LegType | str) -> bool:
    """`True` iff `status` is a terminal status for `leg_type` — i.e. this
    case's outcome is decided and it may be given a `recovered_label`.

    A case still open (`DETECTED`, `DIAGNOSING`, `SYSTEMIC_HOLD`,
    `PLAYBOOK_ACTIVE`, `ESCALATED_TO_HUMAN`, `PAUSED`, or a B2B
    `PARTIALLY_RECOVERED` case still accepting further payments) is not
    eligible — it has no outcome yet, so no amount of feature engineering
    can give it a legitimate label.
    """
    return CaseStatus(status) in _terminal_statuses_for_leg(leg_type)


def recovered_label(status: CaseStatus | str) -> bool:
    """The binary training target: `True` iff `status in {RECOVERED,
    CANCELLED}` — "the customer's at-risk money came back, by any means."

    Callers must check `is_training_eligible` first; calling this on a
    non-terminal status is meaningless (though not an error here — this
    function only ever looks at the two-member `_RECOVERED_STATUSES` set,
    so any other status, terminal or not, simply returns `False`).
    """
    return CaseStatus(status) in _RECOVERED_STATUSES


__all__ = ["is_training_eligible", "recovered_label"]
