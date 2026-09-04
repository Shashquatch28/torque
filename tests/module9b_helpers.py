"""Shared builders for the Module 9b incrementality tests (not a `test_` module).

A cohort case is just a `RevenueLeakCase` with `control_group` set (True =
control, False = treatment) and a status that is or is not an intent-to-treat
recovery (`RECOVERED` / `CANCELLED` count; everything else does not). `opened_at`
places it in / out of the measurement window.
"""

from __future__ import annotations

from datetime import UTC, datetime

from torque.enums import CaseStatus, LegType

#: A fixed instant well inside every test's default window.
WINDOW_MID = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
WINDOW_START = datetime(2026, 6, 1, 0, 0, tzinfo=UTC)
WINDOW_END = datetime(2026, 7, 1, 0, 0, tzinfo=UTC)
BEFORE_WINDOW = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)

_CTX_FOR_LEG = {
    LegType.PAYMENT_DEGRADATION: {"gateway": "razorpay"},
    LegType.SUBSCRIPTION_FAILURE: {
        "mandate_id": "mand_9b", "mandate_type": "CARD",
        "billing_cycle": "monthly", "subscription_id": "sub_9b",
    },
    LegType.CHECKOUT_ABANDONMENT: {
        "cart_id": "cart_9b", "cart_value": "1000.00",
        "drop_stage": "vpa_entry", "payment_method_attempted": "UPI_COLLECT",
    },
    LegType.B2B_RECEIVABLE: {},
}


def cohort_case(
    make_case,
    merchant,
    *,
    control: bool,
    recovered: bool = True,
    counterparty=None,
    opened_at: datetime = WINDOW_MID,
    leg: LegType = LegType.PAYMENT_DEGRADATION,
    status: CaseStatus | None = None,
):
    """One cohort-assigned case. `recovered=True` → `RECOVERED`; `False` →
    `PLAYBOOK_ACTIVE` (open, not recovered). Pass `status=` to override."""
    if status is None:
        status = CaseStatus.RECOVERED if recovered else CaseStatus.PLAYBOOK_ACTIVE
    return make_case(
        merchant=merchant,
        counterparty=counterparty,
        leg=leg,
        control_group=control,
        status=status,
        opened_at=opened_at,
        context=dict(_CTX_FOR_LEG[leg]),
    )
