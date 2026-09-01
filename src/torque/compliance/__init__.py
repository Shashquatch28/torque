"""Pure compliance predicates for the three retry rails and pre-debit gating.

Every function here is side-effect-free: it takes plain values (or a read-only
session, for the two that query a table) and returns a bool / lookup result.
There is **no enforcement, no retry execution, no GuardrailEngine wiring** in
this package — those are Modules 5 and 6. This is the checkable logic they will
call, isolated so it can be unit-tested in one place.

Blueprint references: Section 2.6 (three rails, three postures), Section 3
(entity specs), Decision K (demo scenarios).
"""

from torque.compliance.mac_registry import tier_for
from torque.compliance.pre_debit import PRE_DEBIT_MIN_GAP_HOURS, gap_satisfied
from torque.compliance.retry_rails import (
    CARD_ATTEMPTS_24H_CAP,
    CARD_ATTEMPTS_30D_CAP,
    IST,
    UPI_AUTOPAY_HARD_CAP,
    UPI_PEAK_WINDOWS_IST,
    card_retry_within_budget,
    nach_retry_eligible,
    upi_attempt_gate_open,
    within_upi_execution_window,
)

__all__ = [
    "tier_for",
    "PRE_DEBIT_MIN_GAP_HOURS",
    "gap_satisfied",
    "CARD_ATTEMPTS_24H_CAP",
    "CARD_ATTEMPTS_30D_CAP",
    "IST",
    "UPI_AUTOPAY_HARD_CAP",
    "UPI_PEAK_WINDOWS_IST",
    "card_retry_within_budget",
    "nach_retry_eligible",
    "upi_attempt_gate_open",
    "within_upi_execution_window",
]
