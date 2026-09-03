"""Module 4 — playbook selection (Blueprint §4.1). Pure, no DB."""

from __future__ import annotations

import pytest

from torque.diagnosis.root_causes import RootCauseCode
from torque.enums import LegType, MandateType
from torque.policy import catalog as C
from torque.policy import select_playbook_id

RC = RootCauseCode
PD = LegType.PAYMENT_DEGRADATION
CO = LegType.CHECKOUT_ABANDONMENT
SUB = LegType.SUBSCRIPTION_FAILURE
B2B = LegType.B2B_RECEIVABLE
P_UPI = C.PLAYBOOK_SUBSCRIPTION_RETRY_UPI_AUTOPAY
P_RENEW = C.PLAYBOOK_REQUEST_MANDATE_RENEWAL


@pytest.mark.parametrize(
    ("leg", "cause", "mandate", "expected"),
    [
        # Leg 1
        (PD, RC.ISSUER_SOFT_DECLINE_NSF, None, C.PLAYBOOK_NSF_RETRY),
        (PD, RC.ISSUER_SOFT_DECLINE_OTHER, None, C.PLAYBOOK_GENERIC_SOFT_RETRY),
        (PD, RC.GATEWAY_TIMEOUT, None, C.PLAYBOOK_GENERIC_SOFT_RETRY),
        (PD, RC.ISSUER_HARD_DECLINE_CARD_EXPIRED, None, C.PLAYBOOK_REQUEST_NEW_INSTRUMENT),
        (PD, RC.INSTRUMENT_NOT_RECURRING_CAPABLE, None, C.PLAYBOOK_REQUEST_NEW_INSTRUMENT),
        # Leg 2
        (CO, RC.UPI_COLLECT_FRICTION, None, C.PLAYBOOK_SUGGEST_UPI_INTENT),
        (CO, RC.NO_PAYMENT_METHOD_ATTEMPTED, None, C.PLAYBOOK_GENERIC_CART_NUDGE),
        (CO, RC.UNKNOWN_ABANDONMENT, None, C.PLAYBOOK_GENERIC_CART_NUDGE),
        # Leg 3 — mandate-specific NSF
        (SUB, RC.NSF_SOFT_DECLINE, MandateType.CARD, C.PLAYBOOK_SUBSCRIPTION_RETRY_CARD),
        (SUB, RC.NSF_SOFT_DECLINE, MandateType.UPI_AUTOPAY, P_UPI),
        (SUB, RC.NSF_SOFT_DECLINE, MandateType.NACH, C.PLAYBOOK_SUBSCRIPTION_RETRY_NACH),
        (SUB, RC.MANDATE_CANCELLED_BY_CUSTOMER, MandateType.CARD, P_RENEW),
        (SUB, RC.INSTRUMENT_NOT_RECURRING_CAPABLE, MandateType.NACH, P_RENEW),
        # Leg 4
        (B2B, RC.LIQUIDITY_DELAY_LOW_RISK, None, C.PLAYBOOK_B2B_LOW_RISK_DUNNING),
        (B2B, RC.LIQUIDITY_DELAY_HIGH_RISK, None, C.PLAYBOOK_B2B_HIGH_RISK_DUNNING),
    ],
)
def test_selection(leg, cause, mandate, expected):
    assert (
        select_playbook_id(leg_type=leg, root_cause_code=cause.value, mandate_type=mandate)
        == expected
    )


@pytest.mark.parametrize(
    ("leg", "cause"),
    [
        # "Trivial" causes §4.1 deliberately omits → no automated playbook.
        (PD, RC.ISSUER_HARD_DECLINE_FRAUD_SUSPECTED),
        (SUB, RC.UPI_AUTOPAY_CAP_EXHAUSTED),
        (SUB, RC.NACH_CLEARING_PENDING),
        (SUB, RC.CARD_EXPIRED_OR_REISSUED),
        (B2B, RC.DISPUTE_SUSPECTED),
        (B2B, RC.UNKNOWN_RECEIVABLE_RISK),
        (CO, RC.AUTH_3DS_TIMEOUT),
    ],
)
def test_no_playbook_for_trivial_causes(leg, cause):
    assert (
        select_playbook_id(leg_type=leg, root_cause_code=cause.value, mandate_type=MandateType.CARD)
        is None
    )


def test_unknown_root_cause_string_returns_none():
    assert select_playbook_id(leg_type=PD, root_cause_code="NOT_A_CODE") is None


def test_subscription_nsf_without_mandate_type_returns_none():
    # mandate_type is required to disambiguate the three subscription retry rails.
    assert select_playbook_id(
        leg_type=SUB, root_cause_code=RC.NSF_SOFT_DECLINE.value
    ) is None
