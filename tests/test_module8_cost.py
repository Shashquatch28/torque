"""Module 8 §8.2 / D-111 — the forward-looking intervention cost.

`cost` = Σ `ChannelRateCard.rate_per_unit` for the channel(s) the assigned
playbook's *next likely step* would use. Real DB: seeded rate card
(`whatsapp` 0.8850, `email` 0.0100, `sms` 0.2000) and the seeded catalog.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select

from torque.enums import CaseStatus, LegType
from torque.models import ChannelRateCard, PlaybookRun
from torque.scoring.cost import CostBasis, NextStepSource, compute_cost

_WA = Decimal("0.8850")
_EMAIL = Decimal("0.0100")


# --- live run: price the node at `active_step_id` -----------------------


def test_live_run_next_step_is_whatsapp_priced_from_rate_card(db, make_active_run):
    # PLAYBOOK_SUGGEST_UPI_INTENT entry node is SEND_WHATSAPP.
    case, run, _job = make_active_run(
        leg=LegType.CHECKOUT_ABANDONMENT,
        root_cause_code="UPI_COLLECT_FRICTION",
        context={
            "cart_id": "c1", "cart_value": "500.00",
            "drop_stage": "vpa_entry", "payment_method_attempted": "UPI_COLLECT",
        },
    )
    cost = compute_cost(db, case)
    assert cost.next_step_source is NextStepSource.LIVE_RUN
    assert cost.cost_basis is CostBasis.PRICED
    assert cost.channels == ("whatsapp",)
    assert cost.raw_cost == _WA
    assert cost.effective_cost == _WA
    assert cost.floor_applied is False


def test_live_run_advanced_to_email_step_prices_email(db, make_active_run):
    case, run, _job = make_active_run(
        leg=LegType.CHECKOUT_ABANDONMENT,
        root_cause_code="UPI_COLLECT_FRICTION",
        context={
            "cart_id": "c2", "cart_value": "500.00",
            "drop_stage": "vpa_entry", "payment_method_attempted": "UPI_COLLECT",
        },
    )
    # step 2 of PLAYBOOK_SUGGEST_UPI_INTENT is "email" (SEND_EMAIL).
    run.active_step_id = "email"
    db.flush()
    cost = compute_cost(db, case)
    assert cost.next_step_action_type == "SEND_EMAIL"
    assert cost.channels == ("email",)
    assert cost.raw_cost == _EMAIL
    assert cost.effective_cost == _EMAIL  # 0.0100 == the floor → priced, no floor bit
    assert cost.floor_applied is False
    assert cost.cost_basis is CostBasis.PRICED


def test_next_step_retry_payment_has_no_channel_and_floors(db, make_active_run):
    # PLAYBOOK_NSF_RETRY entry node is RETRY_PAYMENT (no messaging channel).
    case, run, _job = make_active_run(
        leg=LegType.PAYMENT_DEGRADATION, root_cause_code="ISSUER_SOFT_DECLINE_NSF"
    )
    cost = compute_cost(db, case)
    assert cost.next_step_action_type == "RETRY_PAYMENT"
    assert cost.channels == ()
    assert cost.cost_basis is CostBasis.FLOOR_NO_CHANNEL
    assert cost.raw_cost == Decimal("0")
    assert cost.effective_cost == Decimal("0.01")
    assert cost.floor_applied is True


def test_next_step_payment_link_channel_is_unpriced_and_floors(db, make_active_run):
    # PLAYBOOK_REQUEST_NEW_INSTRUMENT entry node is GENERATE_PAYMENT_LINK →
    # channel "payment_link", which has no ChannelRateCard row.
    case, run, _job = make_active_run(
        leg=LegType.PAYMENT_DEGRADATION,
        root_cause_code="ISSUER_HARD_DECLINE_CARD_EXPIRED",
    )
    cost = compute_cost(db, case)
    assert cost.channels == ("payment_link",)
    assert cost.unpriced_channels == ("payment_link",)
    assert cost.cost_basis is CostBasis.FLOOR_UNPRICED_CHANNEL
    assert cost.effective_cost == Decimal("0.01")


# --- candidate playbook: diagnosed, but no run yet --------------------


def test_candidate_playbook_entry_step_priced_when_no_run(db, seeded_catalog, make_case):
    case = make_case(
        leg=LegType.CHECKOUT_ABANDONMENT,
        status=CaseStatus.PLAYBOOK_ACTIVE,
        root_cause_code="UPI_COLLECT_FRICTION",
        context={
            "cart_id": "c3", "cart_value": "500.00",
            "drop_stage": "vpa_entry", "payment_method_attempted": "UPI_COLLECT",
        },
    )
    runs = db.scalars(select(PlaybookRun).where(PlaybookRun.case_id == case.case_id)).all()
    assert runs == []
    cost = compute_cost(db, case)
    assert cost.next_step_source is NextStepSource.CANDIDATE_PLAYBOOK
    assert cost.cost_basis is CostBasis.PRICED
    assert cost.raw_cost == _WA


def test_no_run_no_root_cause_is_floor_no_playbook(db, seeded_catalog, make_case):
    case = make_case(leg=LegType.PAYMENT_DEGRADATION, context={"gateway": "razorpay"})
    cost = compute_cost(db, case)
    assert cost.next_step_source is NextStepSource.NONE
    assert cost.cost_basis is CostBasis.FLOOR_NO_PLAYBOOK
    assert cost.next_step_action_type is None
    assert cost.effective_cost == Decimal("0.01")


def test_trivial_root_cause_with_no_catalog_playbook_floors(db, seeded_catalog, make_case):
    # DISPUTE_SUSPECTED has no automated playbook (§4.1) → select_playbook_id None.
    case = make_case(
        leg=LegType.B2B_RECEIVABLE,
        status=CaseStatus.PLAYBOOK_ACTIVE,
        root_cause_code="DISPUTE_SUSPECTED",
        context={},
    )
    cost = compute_cost(db, case)
    assert cost.cost_basis is CostBasis.FLOOR_NO_PLAYBOOK
    assert cost.next_step_source is NextStepSource.NONE


# --- rate-card edge cases -------------------------------------------


def test_missing_rate_card_row_makes_the_channel_unpriced(db, make_active_run):
    case, run, _job = make_active_run(
        leg=LegType.CHECKOUT_ABANDONMENT,
        root_cause_code="UPI_COLLECT_FRICTION",
        context={
            "cart_id": "c4", "cart_value": "500.00",
            "drop_stage": "vpa_entry", "payment_method_attempted": "UPI_COLLECT",
        },
    )
    db.execute(ChannelRateCard.__table__.delete().where(ChannelRateCard.channel == "whatsapp"))
    db.flush()
    cost = compute_cost(db, case)
    assert cost.unpriced_channels == ("whatsapp",)
    assert cost.cost_basis is CostBasis.FLOOR_UNPRICED_CHANNEL
    assert cost.effective_cost == Decimal("0.01")


def test_zero_rate_is_priced_but_floors_the_divisor(db, make_active_run):
    case, run, _job = make_active_run(
        leg=LegType.CHECKOUT_ABANDONMENT,
        root_cause_code="UPI_COLLECT_FRICTION",
        context={
            "cart_id": "c5", "cart_value": "500.00",
            "drop_stage": "vpa_entry", "payment_method_attempted": "UPI_COLLECT",
        },
    )
    db.execute(
        ChannelRateCard.__table__.update()
        .where(ChannelRateCard.channel == "whatsapp")
        .values(rate_per_unit=Decimal("0"))
    )
    db.flush()
    cost = compute_cost(db, case)
    assert cost.raw_cost == Decimal("0")
    assert cost.cost_basis is CostBasis.PRICED          # a real rate was found
    assert cost.effective_cost == Decimal("0.01")       # …but the divisor still floors
    assert cost.floor_applied is True


def test_cost_floor_is_policy_driven(db, make_active_run, monkeypatch):
    from torque.config import PolicyConfig

    monkeypatch.setattr(
        "torque.scoring.cost.get_policy", lambda: PolicyConfig(recovery_score_cost_floor=0.5)
    )
    case, run, _job = make_active_run(
        leg=LegType.PAYMENT_DEGRADATION, root_cause_code="ISSUER_SOFT_DECLINE_NSF"
    )
    cost = compute_cost(db, case)
    assert cost.effective_cost == Decimal("0.5")
