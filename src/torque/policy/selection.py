"""Playbook selection — Blueprint §4.1.

Maps a diagnosed case's `(leg_type, root_cause_code, mandate_type)` to the
eligible catalog playbook id, or `None` when no automated playbook applies.

Selection depends on:
* `root_cause_code` (set by Module 3) — the primary key;
* `leg_type` — `INSTRUMENT_NOT_RECURRING_CAPABLE` is shared across legs and maps
  to a different playbook per leg (§3.1 / §4.1);
* `mandate_type` (from `SubscriptionFailureContext`) — the three subscription
  `NSF_SOFT_DECLINE` retry playbooks differ only by rail.

`network_directive_tier` is **not** a separate selection input: Module 3 already
folds it into the `root_cause_code` (TIER_1 → *_FRAUD_SUSPECTED /
MANDATE_CANCELLED_BY_CUSTOMER; TIER_3 → INSTRUMENT_NOT_RECURRING_CAPABLE), so
selecting on the root cause honours the directive without re-reading the tier.

`None` (no playbook) is the correct, faithful result for the "trivial" root causes
§4.1 deliberately omits — a suspected-fraud hard stop, an exhausted UPI cap, a
still-clearing NACH batch, a suspected dispute, a cold-start unknown. The engine
routes those to human review (D-086), it does not invent a playbook for them.
"""

from __future__ import annotations

from torque.diagnosis.root_causes import RootCauseCode
from torque.enums import LegType, MandateType
from torque.policy import catalog as C

RC = RootCauseCode
_PD = LegType.PAYMENT_DEGRADATION
_CO = LegType.CHECKOUT_ABANDONMENT
_SUB = LegType.SUBSCRIPTION_FAILURE
_B2B = LegType.B2B_RECEIVABLE

# (leg_type, root_cause_code) -> playbook_id, for the mandate-independent cases.
_BY_LEG_AND_CAUSE: dict[tuple[LegType, RootCauseCode], str] = {
    # Leg 1
    (_PD, RC.ISSUER_SOFT_DECLINE_NSF): C.PLAYBOOK_NSF_RETRY,
    (_PD, RC.ISSUER_SOFT_DECLINE_OTHER): C.PLAYBOOK_GENERIC_SOFT_RETRY,
    (_PD, RC.GATEWAY_TIMEOUT): C.PLAYBOOK_GENERIC_SOFT_RETRY,
    (_PD, RC.ISSUER_HARD_DECLINE_CARD_EXPIRED): C.PLAYBOOK_REQUEST_NEW_INSTRUMENT,
    (_PD, RC.INSTRUMENT_NOT_RECURRING_CAPABLE): C.PLAYBOOK_REQUEST_NEW_INSTRUMENT,
    # Leg 2
    (_CO, RC.UPI_COLLECT_FRICTION): C.PLAYBOOK_SUGGEST_UPI_INTENT,
    (_CO, RC.NO_PAYMENT_METHOD_ATTEMPTED): C.PLAYBOOK_GENERIC_CART_NUDGE,
    (_CO, RC.UNKNOWN_ABANDONMENT): C.PLAYBOOK_GENERIC_CART_NUDGE,
    # Leg 3 (mandate-independent subscription causes)
    (_SUB, RC.MANDATE_CANCELLED_BY_CUSTOMER): C.PLAYBOOK_REQUEST_MANDATE_RENEWAL,
    (_SUB, RC.INSTRUMENT_NOT_RECURRING_CAPABLE): C.PLAYBOOK_REQUEST_MANDATE_RENEWAL,
    # Leg 4
    (_B2B, RC.LIQUIDITY_DELAY_LOW_RISK): C.PLAYBOOK_B2B_LOW_RISK_DUNNING,
    (_B2B, RC.LIQUIDITY_DELAY_HIGH_RISK): C.PLAYBOOK_B2B_HIGH_RISK_DUNNING,
}

# Subscription NSF_SOFT_DECLINE is rail-specific (§4.1).
_SUBSCRIPTION_NSF_BY_MANDATE: dict[MandateType, str] = {
    MandateType.CARD: C.PLAYBOOK_SUBSCRIPTION_RETRY_CARD,
    MandateType.UPI_AUTOPAY: C.PLAYBOOK_SUBSCRIPTION_RETRY_UPI_AUTOPAY,
    MandateType.NACH: C.PLAYBOOK_SUBSCRIPTION_RETRY_NACH,
}


def select_playbook_id(
    *,
    leg_type: LegType,
    root_cause_code: str,
    mandate_type: MandateType | None = None,
) -> str | None:
    """The eligible catalog playbook id for a diagnosed case, or `None`.

    `root_cause_code` is the raw string persisted on the case; an unrecognised
    value (or a "trivial" cause with no playbook) returns `None`.
    """
    try:
        cause = RootCauseCode(root_cause_code)
    except ValueError:
        return None
    leg = LegType(leg_type)

    if (
        leg is LegType.SUBSCRIPTION_FAILURE
        and cause is RC.NSF_SOFT_DECLINE
        and mandate_type is not None
    ):
        return _SUBSCRIPTION_NSF_BY_MANDATE.get(MandateType(mandate_type))

    return _BY_LEG_AND_CAUSE.get((leg, cause))
