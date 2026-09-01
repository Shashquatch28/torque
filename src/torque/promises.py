"""`PromiseToPay.status` lifecycle (Blueprint Section 3).

Structured like `torque.state_machine` (for `RevenueLeakCase.status`), but for
`PromiseToPay.status` **only**. It does NOT touch `RevenueLeakCase.status` or
`state_machine.py`, and it writes **no** `CaseEvent` — `PROMISE_CAPTURED` is the
capture-time event and remains a Module 5 execution concern.

Legal transitions:

    PENDING -> KEPT
    PENDING -> BROKEN

`KEPT` and `BROKEN` are terminal. A `PromiseToPay` is created `PENDING`.

`on_broken`: a `BROKEN` promise routes to the human queue (Module 6 runtime
behaviour). That routing is deliberately NOT persisted as per-row configuration
— there is no `on_broken` column.

The `before_flush` guard in `torque.models.guards` enforces exactly this graph:
a new `PromiseToPay` must be `PENDING`, and any `status` change on an existing
row must be one of the transitions above.
"""

from __future__ import annotations

from torque.enums import PromiseStatus
from torque.exceptions import PromiseTransitionError

PROMISE_TRANSITIONS: dict[PromiseStatus, set[PromiseStatus]] = {
    PromiseStatus.PENDING: {PromiseStatus.KEPT, PromiseStatus.BROKEN},
    PromiseStatus.KEPT: set(),
    PromiseStatus.BROKEN: set(),
}

TERMINAL_PROMISE_STATUSES: frozenset[PromiseStatus] = frozenset(
    {PromiseStatus.KEPT, PromiseStatus.BROKEN}
)


def assert_promise_transition(current: PromiseStatus, target: PromiseStatus) -> None:
    """Raise `PromiseTransitionError` unless `current -> target` is legal."""
    current = PromiseStatus(current)
    target = PromiseStatus(target)
    if target not in PROMISE_TRANSITIONS[current]:
        raise PromiseTransitionError(
            f"PromiseToPay.status {current} -> {target} is not a legal transition "
            f"(only PENDING -> KEPT and PENDING -> BROKEN are permitted; "
            f"KEPT and BROKEN are terminal)"
        )


def transition_promise(promise, target: PromiseStatus) -> None:
    """Validate and apply a `PromiseToPay.status` change. Writes no `CaseEvent`.

    `promise` is a `PromiseToPay` instance; the caller controls the transaction.
    """
    assert_promise_transition(PromiseStatus(promise.status), target)
    promise.status = PromiseStatus(target)
